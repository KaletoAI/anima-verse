using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>Bone-name keys shared by the browser and the native rigs.</summary>
public static class BoneNames
{
    /// <summary>
    /// The browser's <c>normBoneName</c> (strip a leading <c>mixamorig</c>/<c>mixamorig:</c>, lower-case) plus a
    /// namespace strip and Godot's <c>mixamorig_</c> / <c>mixamorig1_</c> spelling.
    /// </summary>
    public static string Norm(string name)
    {
        int colon = name.LastIndexOf(':');
        var s = colon >= 0 ? name[(colon + 1)..] : name;
        if (s.StartsWith("mixamorig", StringComparison.OrdinalIgnoreCase))
        {
            s = s[9..];
            while (s.Length > 0 && char.IsDigit(s[0])) s = s[1..];
            if (s.StartsWith('_')) s = s[1..];
        }
        return s.ToLowerInvariant();
    }
}

/// <summary>One node of a probe rig: its parent (−1 = the probe root), whether it is a bone, its rest TRS (local).</summary>
public sealed record ProbeNode(string Name, int Parent, bool IsBone, V3 Position, Quat Rotation, V3 Scale);

/// <summary>
/// A skeleton as three's probe clone sees it (footLockMeasure.ts / clipGround.ts <c>SkeletonUtils.clone(template)</c>):
/// <see cref="Root"/> is the probe object's own matrix (the template root's transform — on Godot the model root's
/// transform times the chain down to the Skeleton3D), the nodes hang below it. Never mutated by a probe run.
/// </summary>
public sealed class ProbeRig
{
    public Affine Root { get; }
    public IReadOnlyList<ProbeNode> Nodes { get; }
    /// <summary>Node indices in three's <c>traverse</c> order (depth first, children in list order).</summary>
    public IReadOnlyList<int> PreOrder { get; }

    public ProbeRig(Affine root, IReadOnlyList<ProbeNode> nodes)
    {
        Root = root;
        Nodes = nodes;
        var children = nodes.Select(_ => new List<int>()).ToList();
        var roots = new List<int>();
        for (int i = 0; i < nodes.Count; i++)
        {
            int p = nodes[i].Parent;
            if (p < 0 || p >= nodes.Count) roots.Add(i); else children[p].Add(i);
        }
        var order = new List<int>();
        void Visit(int i)
        {
            order.Add(i);
            foreach (var c in children[i]) Visit(c);
        }
        foreach (var r in roots) Visit(r);
        PreOrder = order;
    }

    private Dictionary<string, int>? _byName;

    /// <summary>First node (traverse order) whose name is exactly <paramref name="name"/> (three's PropertyBinding), or −1.</summary>
    public int FindByName(string name)
    {
        if (_byName is null)
        {
            _byName = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (int i in PreOrder) _byName.TryAdd(Nodes[i].Name, i);
        }
        return _byName.TryGetValue(name, out int at) ? at : -1;
    }

    /// <summary>Key (<see cref="BoneNames.Norm"/>) → the FIRST bone in traverse order with it (footLockMeasure.ts <c>byKey</c>).</summary>
    public Dictionary<string, int> BonesByKey()
    {
        var byKey = new Dictionary<string, int>();
        foreach (int i in PreOrder)
            if (Nodes[i].IsBone) byKey.TryAdd(BoneNames.Norm(Nodes[i].Name), i);
        return byKey;
    }

    public bool IsBelow(int node, int ancestor)
    {
        for (int p = Nodes[node].Parent; p >= 0; p = Nodes[p].Parent)
            if (p == ancestor) return true;
        return false;
    }
}

/// <summary>One keyframe track of a probe clip: the node it binds (by exact name), <c>position</c> or <c>quaternion</c>, float keys like three.</summary>
public sealed class ProbeTrack
{
    public required string Node { get; init; }
    /// <summary><c>"position"</c> (3 values per key) or <c>"quaternion"</c> (4, x y z w).</summary>
    public required string Prop { get; init; }
    public required float[] Times { get; init; }
    public required float[] Values { get; init; }
    /// <summary>Set when a probe run wrote this track (the caller copies it back into its engine clip).</summary>
    public bool Rewritten { get; init; }
}

/// <summary>
/// A clip as the probe plays it, plus the per-clip stores of the browser's WeakMaps: the root travel
/// (<c>clipRootPath</c>), the turn (<c>clipRootTurn</c>), the lift (<c>clipBridgeLift</c>) and the ground offset
/// (<c>userData.groundOffset</c>). A probe run replaces tracks and stores in place, like three mutates the clip.
/// </summary>
public sealed class ProbeClip
{
    public required string Name { get; init; }
    public required double Duration { get; init; }
    public required List<ProbeTrack> Tracks { get; init; }
    public RootPath? Path { get; set; }
    public RootTurn? Turn { get; set; }
    public BridgeLiftSpec? Lift { get; set; }
    public double GroundOffset { get; set; }

    private static bool Matches(ProbeTrack t, string prop, string key) => t.Prop == prop && BoneNames.Norm(t.Node) == key;

    /// <summary>
    /// footLockMeasure.ts <c>replaceTrack</c>: the <paramref name="prop"/> track of the bone (whatever spelling of its
    /// name) replaced by one on <paramref name="times"/> in place of the first match, later matches removed; appended
    /// when there was none.
    /// </summary>
    public void ReplaceTrack(string boneName, string prop, float[] times, float[] values)
    {
        string key = BoneNames.Norm(boneName);
        var track = new ProbeTrack { Node = boneName, Prop = prop, Times = times, Values = values, Rewritten = true };
        int at = Tracks.FindIndex(t => Matches(t, prop, key));
        if (at < 0)
        {
            Tracks.Add(track);
            return;
        }
        Tracks[at] = track;
        for (int i = Tracks.Count - 1; i > at; i--)
            if (Matches(Tracks[i], prop, key)) Tracks.RemoveAt(i);
    }
}

/// <summary>Matrix helpers with three.js semantics (Matrix4.compose / decompose / invert, setFromRotationMatrix).</summary>
public static class RigMath
{
    public static Affine Compose(V3 t, Quat q, V3 s)
    {
        double x = q.X, y = q.Y, z = q.Z, w = q.W;
        double x2 = x + x, y2 = y + y, z2 = z + z;
        double xx = x * x2, xy = x * y2, xz = x * z2, yy = y * y2, yz = y * z2, zz = z * z2;
        double wx = w * x2, wy = w * y2, wz = w * z2;
        return new Affine(
            (1 - (yy + zz)) * s.X, (xy + wz) * s.X, (xz - wy) * s.X,
            (xy - wz) * s.Y, (1 - (xx + zz)) * s.Y, (yz + wx) * s.Y,
            (xz + wy) * s.Z, (yz - wx) * s.Z, (1 - (xx + yy)) * s.Z,
            t.X, t.Y, t.Z);
    }

    public static double Determinant(Affine m)
        => m.Xx * (m.Yy * m.Zz - m.Zy * m.Yz) - m.Yx * (m.Xy * m.Zz - m.Zy * m.Xz) + m.Zx * (m.Xy * m.Yz - m.Yy * m.Xz);

    public static Affine Inverse(Affine m)
    {
        double det = Determinant(m);
        if (det == 0) return new Affine(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        double inv = 1 / det;
        // rows of the inverse 3×3 = cofactors transposed
        double a00 = (m.Yy * m.Zz - m.Zy * m.Yz) * inv, a01 = (m.Zx * m.Yz - m.Yx * m.Zz) * inv, a02 = (m.Yx * m.Zy - m.Zx * m.Yy) * inv;
        double a10 = (m.Zy * m.Xz - m.Xy * m.Zz) * inv, a11 = (m.Xx * m.Zz - m.Zx * m.Xz) * inv, a12 = (m.Zx * m.Xy - m.Xx * m.Zy) * inv;
        double a20 = (m.Xy * m.Yz - m.Yy * m.Xz) * inv, a21 = (m.Yx * m.Xz - m.Xx * m.Yz) * inv, a22 = (m.Xx * m.Yy - m.Yx * m.Xy) * inv;
        double ox = -(a00 * m.Ox + a01 * m.Oy + a02 * m.Oz);
        double oy = -(a10 * m.Ox + a11 * m.Oy + a12 * m.Oz);
        double oz = -(a20 * m.Ox + a21 * m.Oy + a22 * m.Oz);
        return new Affine(a00, a10, a20, a01, a11, a21, a02, a12, a22, ox, oy, oz);
    }

    /// <summary>three <c>Matrix4.decompose</c>: position, rotation (setFromRotationMatrix of the unscaled basis), scale (sx negated for det &lt; 0).</summary>
    public static (V3 Position, Quat Rotation, V3 Scale) Decompose(Affine m)
    {
        double sx = Math.Sqrt(m.Xx * m.Xx + m.Xy * m.Xy + m.Xz * m.Xz);
        double sy = Math.Sqrt(m.Yx * m.Yx + m.Yy * m.Yy + m.Yz * m.Yz);
        double sz = Math.Sqrt(m.Zx * m.Zx + m.Zy * m.Zy + m.Zz * m.Zz);
        if (Determinant(m) < 0) sx = -sx;
        double ix = 1 / sx, iy = 1 / sy, iz = 1 / sz;
        double m11 = m.Xx * ix, m21 = m.Xy * ix, m31 = m.Xz * ix;
        double m12 = m.Yx * iy, m22 = m.Yy * iy, m32 = m.Yz * iy;
        double m13 = m.Zx * iz, m23 = m.Zy * iz, m33 = m.Zz * iz;
        return (new V3(m.Ox, m.Oy, m.Oz), FromRotationMatrix(m11, m12, m13, m21, m22, m23, m31, m32, m33), new V3(sx, sy, sz));
    }

    /// <summary>three <c>Quaternion.setFromRotationMatrix</c> (m_rc = row r, column c).</summary>
    public static Quat FromRotationMatrix(double m11, double m12, double m13, double m21, double m22, double m23,
                                          double m31, double m32, double m33)
    {
        double trace = m11 + m22 + m33;
        if (trace > 0)
        {
            double s = 0.5 / Math.Sqrt(trace + 1.0);
            return new Quat((m32 - m23) * s, (m13 - m31) * s, (m21 - m12) * s, 0.25 / s);
        }
        if (m11 > m22 && m11 > m33)
        {
            double s = 2.0 * Math.Sqrt(1.0 + m11 - m22 - m33);
            return new Quat(0.25 * s, (m12 + m21) / s, (m13 + m31) / s, (m32 - m23) / s);
        }
        if (m22 > m33)
        {
            double s = 2.0 * Math.Sqrt(1.0 + m22 - m11 - m33);
            return new Quat((m12 + m21) / s, 0.25 * s, (m23 + m32) / s, (m13 - m31) / s);
        }
        {
            double s = 2.0 * Math.Sqrt(1.0 + m33 - m11 - m22);
            return new Quat((m13 + m31) / s, (m23 + m32) / s, 0.25 * s, (m21 - m12) / s);
        }
    }

    public static Quat RotationOf(Affine m) => Decompose(m).Rotation;

    public static V3 Origin(Affine m) => new(m.Ox, m.Oy, m.Oz);

    public static V3 Apply(Affine m, V3 p)
    {
        var r = m.Apply(p.X, p.Y, p.Z);
        return new V3(r.X, r.Y, r.Z);
    }

    public static double Dot(Quat a, Quat b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z + a.W * b.W;

    /// <summary>three <c>Quaternion.slerpFlat</c> (the QuaternionLinearInterpolant's step).</summary>
    public static Quat SlerpFlat(Quat a, Quat b, double t)
    {
        if (t == 0) return a;
        if (t == 1) return b;
        double x0 = a.X, y0 = a.Y, z0 = a.Z, w0 = a.W;
        double x1 = b.X, y1 = b.Y, z1 = b.Z, w1 = b.W;
        if (w0 != w1 || x0 != x1 || y0 != y1 || z0 != z1)
        {
            double s = 1 - t;
            double cos = x0 * x1 + y0 * y1 + z0 * z1 + w0 * w1;
            double dir = cos >= 0 ? 1 : -1;
            double sqrSin = 1 - cos * cos;
            if (sqrSin > 2.220446049250313e-16)   // Number.EPSILON
            {
                double sin = Math.Sqrt(sqrSin), len = Math.Atan2(sin, cos * dir);
                s = Math.Sin(s * len) / sin;
                t = Math.Sin(t * len) / sin;
            }
            double tDir = t * dir;
            x0 = x0 * s + x1 * tDir;
            y0 = y0 * s + y1 * tDir;
            z0 = z0 * s + z1 * tDir;
            w0 = w0 * s + w1 * tDir;
            if (s == 1 - t)
            {
                double f = 1 / Math.Sqrt(x0 * x0 + y0 * y0 + z0 * z0 + w0 * w0);
                x0 *= f; y0 *= f; z0 *= f; w0 *= f;
            }
        }
        return new Quat(x0, y0, z0, w0);
    }

    /// <summary>A rotation about +Y by <paramref name="rad"/> (three <c>makeRotationY</c>).</summary>
    public static Affine RotationY(double rad) => Affine.RotationY(rad);
}

/// <summary>
/// A posed probe: three's <c>SkeletonUtils.clone(template)</c> played by one action at weight 1 —
/// <see cref="Pose"/> evaluates a clip at a clip time (LoopOnce + clamp: the time is clamped into [0, duration]),
/// every bound property from its track (linear / slerpFlat between keys, clamped at both ends, Float32 output like
/// three's interpolant buffer), every other property at its rest value (three restores the original state when the
/// action stops). World matrices are <c>Root · … · local</c>.
/// </summary>
public sealed class RigPose
{
    private readonly ProbeRig _rig;
    private readonly Affine[] _world;
    private readonly V3[] _pos;
    private readonly Quat[] _rot;

    public RigPose(ProbeRig rig)
    {
        _rig = rig;
        _world = new Affine[rig.Nodes.Count];
        _pos = new V3[rig.Nodes.Count];
        _rot = new Quat[rig.Nodes.Count];
        Rest();
    }

    public ProbeRig Rig => _rig;

    /// <summary>World matrix of a node (−1 = the probe root).</summary>
    public Affine World(int node) => node < 0 ? _rig.Root : _world[node];
    public V3 WorldPosition(int node) => RigMath.Origin(World(node));
    public Quat WorldRotation(int node) => RigMath.RotationOf(World(node));
    /// <summary>The node's local rotation as posed (three's <c>bone.quaternion</c>).</summary>
    public Quat LocalRotation(int node) => _rot[node];

    /// <summary>The rest pose (no clip).</summary>
    public void Rest()
    {
        for (int i = 0; i < _rig.Nodes.Count; i++)
        {
            _pos[i] = _rig.Nodes[i].Position;
            _rot[i] = _rig.Nodes[i].Rotation;
        }
        UpdateWorld();
    }

    /// <summary>The clip at clip time <paramref name="t"/> (clamped into [0, duration]).</summary>
    public void Pose(ProbeClip clip, double t)
    {
        double time = Math.Min(Math.Max(t, 0), clip.Duration);
        for (int i = 0; i < _rig.Nodes.Count; i++)
        {
            _pos[i] = _rig.Nodes[i].Position;
            _rot[i] = _rig.Nodes[i].Rotation;
        }
        var seen = new HashSet<(int, string)>();
        foreach (var track in clip.Tracks)
        {
            int node = _rig.FindByName(track.Node);
            if (node < 0 || !seen.Add((node, track.Prop))) continue;
            if (track.Prop == "position") _pos[node] = SampleVector(track, time);
            else if (track.Prop == "quaternion") _rot[node] = SampleQuat(track, time);
        }
        UpdateWorld();
    }

    private void UpdateWorld()
    {
        foreach (int i in _rig.PreOrder)
        {
            var n = _rig.Nodes[i];
            var local = RigMath.Compose(_pos[i], _rot[i], n.Scale);
            _world[i] = (n.Parent < 0 ? _rig.Root : _world[n.Parent]).Times(local);
        }
    }

    /// <summary>The key pair around t and the blend weight (three's interpolant; clamped outside the keys).</summary>
    private static (int A, int B, double W) Interval(float[] times, double t)
    {
        int n = times.Length;
        if (n <= 1 || t <= times[0]) return (0, 0, 0);
        if (t >= times[n - 1]) return (n - 1, n - 1, 0);
        int lo = 0, hi = n - 1;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) >> 1;
            if (times[mid] <= t) lo = mid; else hi = mid;
        }
        double span = times[hi] - (double)times[lo];
        return (lo, hi, span > 0 ? (t - times[lo]) / span : 0);
    }

    public static V3 SampleVector(ProbeTrack track, double t)
    {
        var (a, b, w) = Interval(track.Times, t);
        var v = track.Values;
        double F(int i) => (float)(v[a * 3 + i] * (1 - w) + v[b * 3 + i] * w);
        return new V3(F(0), F(1), F(2));
    }

    public static Quat SampleQuat(ProbeTrack track, double t)
    {
        var (a, b, w) = Interval(track.Times, t);
        var v = track.Values;
        var qa = new Quat(v[a * 4], v[a * 4 + 1], v[a * 4 + 2], v[a * 4 + 3]);
        if (a == b) return qa;
        var qb = new Quat(v[b * 4], v[b * 4 + 1], v[b * 4 + 2], v[b * 4 + 3]);
        var q = RigMath.SlerpFlat(qa, qb, w);
        return new Quat((float)q.X, (float)q.Y, (float)q.Z, (float)q.W);
    }
}
