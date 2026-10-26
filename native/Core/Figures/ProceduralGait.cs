using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Figures;

/// <summary>
/// One bone of a skeleton for <see cref="ProceduralGait.FindLegChains"/>: its name, the index of its parent BONE (null =
/// the immediate parent is not a bone) and its world position, in traversal order (proceduralGait.ts <c>GaitBone</c>).
/// </summary>
public readonly record struct GaitBone(string Name, int? Parent, V3 Position);

/// <summary>A world-space box (proceduralGait.ts <c>GaitBox</c>, three's <c>Box3</c>).</summary>
public readonly record struct GaitBox(V3 Min, V3 Max);

/// <summary>
/// One detected leg (proceduralGait.ts <c>GaitChain</c>): the chain's top joint (hip/shoulder) and its foot as bone
/// indices, the WORLD-space swing axis (the renderer converts it into the joint's parent frame) and the gait phases in
/// radians.
/// </summary>
public sealed record GaitChain(int Bone, int Foot, V3 Axis, double PhaseWalk, double PhaseRun)
{
    public double PhaseWalk { get; set; } = PhaseWalk;
    public double PhaseRun { get; set; } = PhaseRun;
}

/// <summary>
/// The procedural gait of a clip-less rig (packages/scene-render/src/proceduralGait.ts, vectors animal_legs.json and
/// animal_gait.json): the leg chains of an arbitrary skeleton and the swing / bob / breathing amplitudes. Ported line by
/// line; every JS sort is stable, and so are the LINQ <c>OrderBy</c> calls here.
/// </summary>
public static class ProceduralGait
{
    /// <summary>
    /// <c>findLegChains(bones, box)</c>: leaf bones within 0.25 · height of the box's bottom, followed up while the
    /// parent has exactly one child bone; a chain whose top rises at least 0.12 · height over its foot counts once. The
    /// four lowest feet (stable on ties) keep their chains. Swing axis: X when the footprint is longer in Z (square
    /// included), else Z. Four legs walk a lateral sequence (0, π/2, π, 3π/2) and trot on the diagonals; any other count
    /// swings left against right (the centre belongs to the positive side).
    /// </summary>
    public static List<GaitChain> FindLegChains(IReadOnlyList<GaitBone> bones, GaitBox box)
    {
        if (bones.Count == 0) return new List<GaitChain>();
        var size = box.Max - box.Min;
        double centerX = (box.Min.X + box.Max.X) * 0.5, centerZ = (box.Min.Z + box.Max.Z) * 0.5;
        double height = Math.Max(size.Y, 1e-3);
        var children = new int[bones.Count];
        foreach (var bone in bones)
            if (bone.Parent is { } p) children[p]++;
        var found = new List<(int Bone, int Foot)>();
        for (int leaf = 0; leaf < bones.Count; leaf++)
        {
            if (children[leaf] != 0) continue;
            var foot = bones[leaf].Position;
            if (foot.Y > box.Min.Y + height * 0.25) continue;
            int top = leaf;
            while (bones[top].Parent is { } parent && children[parent] == 1) top = parent;
            if (top == leaf) continue;
            if (bones[top].Position.Y - foot.Y < height * 0.12) continue;
            if (!found.Any(f => f.Bone == top)) found.Add((top, leaf));
        }
        found = found.OrderBy(c => bones[c.Foot].Position.Y).ToList();
        bool longX = size.X > size.Z;
        V3 axis = longX ? new V3(0, 0, 1) : new V3(1, 0, 0);
        var chains = found.Take(4).Select(c => new GaitChain(c.Bone, c.Foot, axis, 0, 0)).ToList();
        double Long(GaitChain c) => longX ? bones[c.Foot].Position.X : bones[c.Foot].Position.Z;
        double Cross(GaitChain c) => longX ? bones[c.Foot].Position.Z : bones[c.Foot].Position.X;
        if (chains.Count == 4)
        {
            var byLong = chains.OrderBy(Long).ToList();
            var a = byLong.Take(2).OrderBy(Cross).ToList();
            var b = byLong.Skip(2).OrderBy(Cross).ToList();
            GaitChain aL = a[0], aR = a[1], bL = b[0], bR = b[1];
            aL.PhaseWalk = 0; bL.PhaseWalk = Math.PI / 2;
            aR.PhaseWalk = Math.PI; bR.PhaseWalk = Math.PI * 1.5;
            aL.PhaseRun = 0; bR.PhaseRun = 0;
            aR.PhaseRun = Math.PI; bL.PhaseRun = Math.PI;
        }
        else
        {
            double center = longX ? centerZ : centerX;
            foreach (var c in chains)
            {
                double p = Cross(c) >= center ? 0 : Math.PI;
                c.PhaseWalk = p;
                c.PhaseRun = p;
            }
        }
        return chains;
    }

    /// <summary>
    /// <c>advanceProceduralPhase(phase, dt, gait)</c>: unwrapped radians at 1.6 rad/s idle (<paramref name="gait"/> null),
    /// 7 walking, 11 running.
    /// </summary>
    public static double AdvancePhase(double phase, double dt, string? gait)
        => phase + dt * (gait is null ? 1.6 : gait == "run" ? 11 : 7);

    /// <summary><c>proceduralGaitAmplitudes(phase, legPhase, height)</c>: swing in radians, bob in the units of height.</summary>
    public static (double Swing, double Bob) GaitAmplitudes(double phase, double legPhase, double height)
        => (Math.Sin(phase + legPhase) * 0.45, Math.Abs(Math.Sin(phase)) * height * 0.02);

    /// <summary><c>proceduralIdleAmplitudes(phase)</c>: the idle bob in metres and breathing as a relative scale.</summary>
    public static (double Bob, double Scale) IdleAmplitudes(double phase)
        => (Math.Sin(phase) * 0.012, 1 + Math.Sin(phase * 0.5) * 0.006);
}
