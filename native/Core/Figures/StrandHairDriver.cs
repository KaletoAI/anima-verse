using System;
using System.Collections.Generic;
using System.Diagnostics;

namespace AnimaNative.Figures;

/// <summary>The pose of one frame the strand sim reads: per record follow bone and for the head the endpoint rule's
/// bind→world (collision.ts &lt;c&gt;jointNowFrom&lt;/c&gt;), and the own capsules now (world).</summary>
public sealed class StrandPose
{
    public IReadOnlyList<double[]> Follow = Array.Empty<double[]>();
    public double[] Head = new double[16];
    public IReadOnlyList<(double[] A, double[] B, double R)> Capsules = Array.Empty<(double[], double[], double)>();
}

/// <summary>
/// The clock of per-strand hair on one figure (hairSim.ts &lt;c&gt;createStrandHair&lt;/c&gt; minus three; its module docstring
/// "THE CLOCK" and "THE ROOT'S MOTION" are the reference): a fixed 1/60 s step with the remainder carried, at most
/// &lt;see cref="MaxSteps"/&gt; steps a frame (a longer frame: its last 4/60 s, the head's motion before them carried
/// rigidly), every step at its own time (the follow matrices and the head slerped between the last frame's pose and
/// this one's, the capsule ends linear); a delta &gt; 0.25 s or a head jump &gt; 0.5 m resets the sim to the targets; the
/// root's motion beyond the felt limits is carried (&lt;see cref="RootInertia"/&gt;); the rebuild after the last step of a
/// frame, through the head of that step. Partners (other figures' capsules) are NOT ported: own capsules only.
/// Godot-free; the Godot side (&lt;c&gt;Figures/StrandHairRuntime.cs&lt;/c&gt;) samples the pose and uploads
/// &lt;see cref="Pos"/&gt; / &lt;see cref="Nrm"/&gt;.
/// </summary>
public sealed class StrandHairDriver
{
    public const double Dt = 1.0 / 60;
    public const int MaxSteps = 4;
    public const double ResetDeltaS = 0.25;
    public const double ResetJumpM = 0.5;
    /// <summary>The cost estimate per card before a figure has run (ms per frame), &lt;c&gt;STRAND_MS_PER_CARD&lt;/c&gt;.</summary>
    public const double MsPerCard = 0.015;
    private const double CostEma = 0.1;

    public readonly HairStrandRecord Record;
    public readonly StrandSim Sim;
    public readonly StrandParams BaseParams;
    public StrandParams Params;
    /// <summary>Head-bind-space positions / normals of the hair primitive after the last rebuild.</summary>
    public readonly float[] Pos, Nrm;
    /// <summary>The targets of the last step (world).</summary>
    public readonly F32 Targets;

    private readonly int _nf;
    private readonly double[][] _nowFollow, _fromFollow, _stepFollow;
    private readonly double[] _nowHead = new double[16], _fromHead = new double[16], _stepHead = new double[16];
    private readonly StrandCapsule[] _frameCaps;
    private readonly (double[] A, double[] B, double R)[] _nowCaps, _fromCaps;
    private double _acc;
    private double[]? _lastHead;
    private bool _enabled;
    private readonly RootInertia _inertia = new();
    private readonly Stopwatch _clock = new();

    /// <summary>EMA of a stepping frame's whole update (ms), the estimate &lt;c&gt;cards × 0.015&lt;/c&gt; before the first.</summary>
    public double CostMs { get; private set; }
    private bool _costRan;
    public bool Enabled => _enabled;
    /// <summary>Steps of the last update (0 when it did not step).</summary>
    public int LastSteps { get; private set; }
    /// <summary>Whether the last update reset the sim.</summary>
    public bool LastReset { get; private set; }

    /// <param name="binds">The own capsules' bind ends in the hair primitive's geometry space, in the order the pose
    /// will hand the capsules (the record's hair capsules without the head region, Ruling H-R7).</param>
    public StrandHairDriver(HairStrandRecord record, StrandSim sim, IReadOnlyList<StrandBind> binds)
    {
        Record = record; Sim = sim;
        BaseParams = record.Params; Params = record.Params;
        _nf = record.FollowBones.Length;
        _nowFollow = NewMats(_nf); _fromFollow = NewMats(_nf); _stepFollow = NewMats(_nf);
        _frameCaps = new StrandCapsule[binds.Count];
        for (int i = 0; i < binds.Count; i++) _frameCaps[i] = new StrandCapsule(new double[3], new double[3], 0, binds[i]);
        _nowCaps = new (double[], double[], double)[binds.Count];
        _fromCaps = new (double[], double[], double)[binds.Count];
        for (int i = 0; i < binds.Count; i++) { _nowCaps[i] = (new double[3], new double[3], 0); _fromCaps[i] = (new double[3], new double[3], 0); }
        Pos = (float[])sim.Binding.Pos0.Clone(); Nrm = (float[])sim.Binding.Nrm0.Clone();
        Targets = new F32(sim.N * 3);
        CostMs = record.Cards * MsPerCard;
    }

    private static double[][] NewMats(int n) { var m = new double[n][]; for (int i = 0; i < n; i++) m[i] = new double[16]; return m; }
    private static void Copy(double[] src, double[] dst) => Array.Copy(src, dst, 16);

    /// <summary>The Stiffness slider: × the record's stiffness.</summary>
    public void SetStiffness(double factor)
        => Params = BaseParams with { Stiffness = BaseParams.Stiffness * (double.IsFinite(factor) && factor > 0 ? factor : 1) };

    private void Sample(StrandPose pose)
    {
        if (pose.Follow.Count != _nf) throw new StrandMismatch($"{pose.Follow.Count} follow matrices for {_nf} bones");
        for (int k = 0; k < _nf; k++) Copy(pose.Follow[k], _nowFollow[k]);
        Copy(pose.Head, _nowHead);
        for (int i = 0; i < _nowCaps.Length && i < pose.Capsules.Count; i++)
        {
            var c = pose.Capsules[i];
            Array.Copy(c.A, _nowCaps[i].A, 3); Array.Copy(c.B, _nowCaps[i].B, 3);
            _nowCaps[i].R = c.R;
        }
    }

    private void PoseAt(double s)
    {
        double t = s >= 1 - 1e-9 ? 1 : s;
        for (int k = 0; k < _nf; k++) StrandSim.LerpFrame(_fromFollow[k], _nowFollow[k], t, _stepFollow[k]);
        StrandSim.LerpFrame(_fromHead, _nowHead, t, _stepHead);
        StrandSim.Targets(Record, _stepFollow, Targets);
        for (int i = 0; i < _frameCaps.Length; i++)
        {
            var a = _fromCaps[i]; var b = _nowCaps[i]; var fc = _frameCaps[i];
            for (int d = 0; d < 3; d++)
            {
                fc.A[d] = a.A[d] + (b.A[d] - a.A[d]) * t;
                fc.B[d] = a.B[d] + (b.B[d] - a.B[d]) * t;
            }
            fc.R = a.R + (b.R - a.R) * t;
        }
    }

    private void KeepPose()
    {
        for (int k = 0; k < _nf; k++) Copy(_nowFollow[k], _fromFollow[k]);
        Copy(_nowHead, _fromHead);
        for (int i = 0; i < _nowCaps.Length; i++)
        {
            Array.Copy(_nowCaps[i].A, _fromCaps[i].A, 3); Array.Copy(_nowCaps[i].B, _fromCaps[i].B, 3);
            _fromCaps[i].R = _nowCaps[i].R;
        }
    }

    private static void MovePoint(double[] m, double[] p)
    {
        double x = p[0], y = p[1], z = p[2];
        p[0] = m[0] * x + m[4] * y + m[8] * z + m[12];
        p[1] = m[1] * x + m[5] * y + m[9] * z + m[13];
        p[2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    }

    private void CarryAll(double[] m, bool pose)
    {
        Sim.Carry(m);
        for (int o = 0; o < Targets.Length; o += 3)
        {
            double x = Targets[o], y = Targets[o + 1], z = Targets[o + 2];
            Targets[o] = m[0] * x + m[4] * y + m[8] * z + m[12];
            Targets[o + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
            Targets[o + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
        }
        if (!pose) return;
        for (int k = 0; k < _nf; k++) Copy(StrandMath.Mul(m, _fromFollow[k]), _fromFollow[k]);
        Copy(StrandMath.Mul(m, _fromHead), _fromHead);
        foreach (var c in _fromCaps) { MovePoint(m, c.A); MovePoint(m, c.B); }
    }

    private void StartAtStep()
    {
        for (int k = 0; k < _nf; k++) Copy(_stepFollow[k], _fromFollow[k]);
        Copy(_stepHead, _fromHead);
        for (int i = 0; i < _frameCaps.Length; i++)
        {
            Array.Copy(_frameCaps[i].A, _fromCaps[i].A, 3); Array.Copy(_frameCaps[i].B, _fromCaps[i].B, 3);
            _fromCaps[i].R = _frameCaps[i].R;
        }
    }

    private void Rebuild() => Sim.Rebuild(StrandSim.InvertAffine(_stepHead), Pos, Nrm);

    private void ResetSim(double[] root)
    {
        KeepPose();
        PoseAt(1);
        Sim.Reset(Targets);
        _acc = 0;
        _inertia.Reset();
        _inertia.Update(root, 0);
        Rebuild();
    }

    /// <summary>On (hairSim.ts &lt;c&gt;setEnabled(true)&lt;/c&gt;): sample, reset to the targets, rebuild.</summary>
    public void Enable(StrandPose pose, double[] root)
    {
        if (_enabled) return;
        _enabled = true;
        Sample(pose);
        _lastHead = new[] { _nowHead[12], _nowHead[13], _nowHead[14] };
        ResetSim(root);
    }

    /// <summary>Off: nothing is stepped or written until the next &lt;see cref="Enable"/&gt;.</summary>
    public void Disable() { _enabled = false; _lastHead = null; _acc = 0; }

    /// <summary>One frame (hairSim.ts &lt;c&gt;update&lt;/c&gt;). True when &lt;see cref="Pos"/&gt; / &lt;see cref="Nrm"/&gt; changed.</summary>
    public bool Update(double realDelta, Func<StrandPose> pose, double[] root, bool frozen = false)
    {
        LastSteps = 0; LastReset = false;
        if (!_enabled || frozen) return false;
        _clock.Restart();
        Sample(pose());
        var h = new[] { _nowHead[12], _nowHead[13], _nowHead[14] };
        double jump = _lastHead is { } lh ? StrandMath.Hypot(h[0] - lh[0], h[1] - lh[1], h[2] - lh[2]) : 0;
        _lastHead = h;
        if (!(realDelta <= ResetDeltaS) || jump > ResetJumpM) { ResetSim(root); LastReset = true; return true; }
        var carry = _inertia.Update(root, realDelta);
        if (carry is not null) CarryAll(carry, true);
        double delta = Math.Max(0, realDelta);
        int steps = (int)Math.Floor((_acc + delta) / Dt + 1e-6);
        double start = -_acc, span = delta;
        if (steps > MaxSteps)
        {
            steps = MaxSteps;
            PoseAt(1 - steps * Dt / delta);
            CarryAll(StrandMath.Mul(_stepHead, StrandSim.InvertAffine(_fromHead)), false);
            StartAtStep();
            start = 0;
            span = steps * Dt;
            _acc = 0;
        }
        else _acc = Math.Max(0, _acc + delta - steps * Dt);
        var frame = new StrandFrame { Targets = Targets, Head = _stepHead, Capsules = _frameCaps, Follow = _stepFollow };
        for (int k = 1; k <= steps; k++)
        {
            PoseAt((start + k * Dt) / span);
            Sim.Step(Dt, frame, Params);
        }
        KeepPose();
        LastSteps = steps;
        if (steps == 0) return false;
        Rebuild();
        double ms = _clock.Elapsed.TotalMilliseconds;
        CostMs = _costRan ? CostMs + (ms - CostMs) * CostEma : ms;
        _costRan = true;
        return true;
    }
}
