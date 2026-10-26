using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>
/// One skinned surface of a probe rig: bind-pose vertices (mesh space), the bind index and weight per slot, the bind
/// table (bind → probe node, its bind pose) and <see cref="Frame"/>, the transform of the skinned output into the
/// probe's world (Godot: the MeshInstance3D's transform from the model root's parent frame — the pick's convention).
/// </summary>
public sealed class ProbeSkin
{
    public required float[] Rest { get; init; }
    public required int[] Bones { get; init; }
    public required float[] Weights { get; init; }
    public required int Slots { get; init; }
    /// <summary>Per bind: the probe node it follows (−1 = none: the skeleton frame).</summary>
    public required int[] BindNodes { get; init; }
    public required Affine[] BindPoses { get; init; }
    public required Affine Frame { get; init; }
    /// <summary>The engine object the surface came from (opaque to the core).</summary>
    public object? Owner { get; init; }
    public int VertexCount => Rest.Length / 3;

    /// <summary>Every <paramref name="stride"/>-th vertex of this surface from the first on (bind table and frame unchanged).</summary>
    public ProbeSkin Strided(int stride)
    {
        int n = (VertexCount + stride - 1) / stride;
        var rest = new float[n * 3];
        var bones = new int[n * Slots];
        var weights = new float[n * Slots];
        for (int i = 0, v = 0; v < VertexCount; i++, v += stride)
        {
            Array.Copy(Rest, v * 3, rest, i * 3, 3);
            Array.Copy(Bones, v * Slots, bones, i * Slots, Slots);
            Array.Copy(Weights, v * Slots, weights, i * Slots, Slots);
        }
        return new ProbeSkin
        {
            Rest = rest, Bones = bones, Weights = weights, Slots = Slots, BindNodes = BindNodes, BindPoses = BindPoses,
            Frame = Frame, Owner = Owner,
        };
    }
}

/// <summary>
/// WHERE A CLIP PUTS THE BODY over the ground — client3d/src/scene/clipGround.ts on the native probe. The lowest body
/// point of every clip is measured once on the SKINNING (25 poses × ≤ 1024 strided vertices) against the bind pose's
/// lowest point; <see cref="GroundOffsetOf"/> is the pure rule. No shared vector: the cases of
/// client3d/scripts/smoke_clip_ground.mjs [1] are copied into tests/BridgeCoreTests.cs, the measurement is checked on a
/// hand-built skinned rig there.
/// </summary>
public static class ClipGround
{
    /// <summary>Frames a clip is sampled at, evenly over its whole duration (this many + 1 poses).</summary>
    public const int SampleFrames = 24;
    /// <summary>Vertex budget per pose, over ALL skinned surfaces with one stride.</summary>
    public const int SampleVertices = 1024;

    /// <summary><c>groundOffsetOf(clipMinY, bindMinY)</c>: the drop <c>clipMinY − bindMinY</c> when positive and finite, else 0.</summary>
    public static double GroundOffsetOf(double clipMinY, double bindMinY)
    {
        double drop = clipMinY - bindMinY;
        return double.IsFinite(drop) && drop > 0 ? drop : 0;
    }

    /// <summary>
    /// The clip times of the 25 poses: <c>duration · f / 24</c> played by a LOOPING action (three's
    /// <c>action.play()</c> default), so the last one wraps to 0 again.
    /// </summary>
    public static double[] SampleTimes(double duration)
    {
        var t = new double[SampleFrames + 1];
        for (int f = 0; f <= SampleFrames; f++)
        {
            double time = duration * f / SampleFrames;
            if (duration > 0 && time >= duration) time -= duration * Math.Floor(time / duration);
            t[f] = time;
        }
        return t;
    }

    private static double MinY(RigPose pose, IReadOnlyList<ProbeSkin> skins, int stride, Affine rootInv)
    {
        double min = double.PositiveInfinity;
        foreach (var skin in skins)
        {
            var mats = new Affine[skin.BindNodes.Length];
            for (int b = 0; b < mats.Length; b++)
                mats[b] = rootInv.Times(pose.World(skin.BindNodes[b])).Times(skin.BindPoses[b]);
            int n = skin.VertexCount;
            for (int v = 0; v < n; v += stride)
            {
                double x = skin.Rest[v * 3], y = skin.Rest[v * 3 + 1], z = skin.Rest[v * 3 + 2];
                double sx = 0, sy = 0, sz = 0;
                for (int k = 0; k < skin.Slots; k++)
                {
                    float w = skin.Weights[v * skin.Slots + k];
                    if (w <= 0) continue;
                    int b = skin.Bones[v * skin.Slots + k];
                    if ((uint)b >= (uint)mats.Length) continue;
                    var p = mats[b].Apply(x, y, z);
                    sx += w * p.X; sy += w * p.Y; sz += w * p.Z;
                }
                double wy = skin.Frame.Apply(sx, sy, sz).Y;
                if (wy < min) min = wy;
            }
        }
        return min;
    }

    /// <summary>
    /// <c>measureGroundOffsets(clips, target)</c>: <see cref="ProbeClip.GroundOffset"/> of every clip — the lowest
    /// skinned point over its 25 poses against the lowest of ALL vertices in the rest pose. A rig without a skinned
    /// surface is left alone (its clips keep 0).
    /// </summary>
    public static void Measure(IReadOnlyList<ProbeClip> clips, ProbeRig rig, IReadOnlyList<ProbeSkin> skins)
    {
        if (clips.Count == 0 || skins.Count == 0) return;
        Measure(clips, rig, skins, BindMinY(rig, skins));
    }

    /// <summary>
    /// The rest pose's lowest point over ALL vertices (stride 1) — <c>bindMinY</c> of <see cref="Measure(IReadOnlyList{ProbeClip}, ProbeRig, IReadOnlyList{ProbeSkin})"/>.
    /// It depends on the rig and its skins only, so a caller that measures one clip at a time (the native lazy fit,
    /// Task 35b) computes it ONCE per rig and hands it to <see cref="Measure(IReadOnlyList{ProbeClip}, ProbeRig, IReadOnlyList{ProbeSkin}, double)"/>.
    /// +∞ without a skinned surface. Pure: safe on any thread while nobody mutates the rig or the skins.
    /// </summary>
    public static double BindMinY(ProbeRig rig, IReadOnlyList<ProbeSkin> skins)
        => skins.Count == 0 ? double.PositiveInfinity : MinY(new RigPose(rig), skins, 1, RigMath.Inverse(rig.Root));

    /// <summary>
    /// The vertices <see cref="Measure(IReadOnlyList{ProbeClip}, ProbeRig, IReadOnlyList{ProbeSkin})"/> samples, kept
    /// alone: per surface every stride-th vertex, the stride taken over ALL surfaces' vertices as the measurement takes it
    /// (≤ <see cref="SampleVertices"/> + one per surface). A caller that measures clip after clip long after the build
    /// (the native lazy fit, Task 35b) holds these ~1 000 vertices instead of the whole mesh;
    /// <see cref="MeasureSampled"/> visits exactly them, in the same order.
    /// </summary>
    public static List<ProbeSkin> SampledSkins(IReadOnlyList<ProbeSkin> skins)
    {
        int total = skins.Sum(s => s.VertexCount);
        int stride = Math.Max(1, (total + SampleVertices - 1) / SampleVertices);
        return skins.Select(s => s.Strided(stride)).ToList();
    }

    /// <summary>
    /// <see cref="Measure(IReadOnlyList{ProbeClip}, ProbeRig, IReadOnlyList{ProbeSkin}, double)"/> on the
    /// <see cref="SampledSkins"/> of the rig's surfaces (stride 1 over them: the very vertices the full measurement
    /// visits) against the full surfaces' <see cref="BindMinY"/> — the same offsets bit for bit.
    /// </summary>
    public static void MeasureSampled(IReadOnlyList<ProbeClip> clips, ProbeRig rig, IReadOnlyList<ProbeSkin> sampled, double bindMinY)
    {
        if (clips.Count == 0 || sampled.Count == 0) return;
        var pose = new RigPose(rig);
        var rootInv = RigMath.Inverse(rig.Root);
        foreach (var clip in clips)
        {
            double minY = double.PositiveInfinity;
            foreach (double t in SampleTimes(clip.Duration))
            {
                pose.Pose(clip, t);
                minY = Math.Min(minY, MinY(pose, sampled, 1, rootInv));
            }
            clip.GroundOffset = GroundOffsetOf(minY, bindMinY);
        }
    }

    /// <summary>
    /// <see cref="Measure(IReadOnlyList{ProbeClip}, ProbeRig, IReadOnlyList{ProbeSkin})"/> against a <paramref name="bindMinY"/>
    /// measured before (<see cref="BindMinY"/>): the same offsets bit for bit — the rest pose is a fresh
    /// <see cref="RigPose"/>'s in both, and every clip is posed from its own tracks.
    /// </summary>
    public static void Measure(IReadOnlyList<ProbeClip> clips, ProbeRig rig, IReadOnlyList<ProbeSkin> skins, double bindMinY)
    {
        if (clips.Count == 0 || skins.Count == 0) return;
        var pose = new RigPose(rig);
        var rootInv = RigMath.Inverse(rig.Root);
        int total = skins.Sum(s => s.VertexCount);
        int stride = Math.Max(1, (total + SampleVertices - 1) / SampleVertices);
        foreach (var clip in clips)
        {
            double minY = double.PositiveInfinity;
            foreach (double t in SampleTimes(clip.Duration))
            {
                pose.Pose(clip, t);
                minY = Math.Min(minY, MinY(pose, skins, stride, rootInv));
            }
            clip.GroundOffset = GroundOffsetOf(minY, bindMinY);
        }
    }
}
