using System;
using Godot;
using AnimaNative.Figures;

namespace AnimaNative.Figures;

/// <summary>
/// scene-render pairHeightPose.ts <c>applyPairHeight</c> (owner decision 2026-11-25, <see cref="PairHeight"/>): the hips
/// move straight up or down by the figure's pair-height offset (world metres) and a two-bone leg IK
/// (<see cref="LegPin.TwoBoneIk"/>, pole = the knee) brings every PLANTED leg's ankle back to where the clip put it, the
/// foot keeping its rotation; a leg that is not planted moves with the hips. A SkeletonModifier3D, so it runs after the
/// animation player wrote the clip pose and — kept FIRST among the skeleton's modifiers — before the secondary motion,
/// the strand hair and the garment push (phase B of the browser's frame). An offset of exactly 0 touches nothing.
/// </summary>
public partial class PairHeightModifier : SkeletonModifier3D
{
    private readonly int _hips;
    private readonly (int Upper, int Lower, int Foot)?[] _legs;

    /// <summary>The offset applied this frame (metres, + = up; already weighted), and the legs [left, right] the IK holds.</summary>
    public double OffsetM { get; set; }
    public bool[] Planted { get; set; } = Array.Empty<bool>();

    private PairHeightModifier(int hips, (int, int, int)?[] legs)
    {
        _hips = hips;
        _legs = legs;
        Name = "PairHeight";
    }

    /// <summary><c>pairHeightRigOf</c>: the hips and per side the thigh/shin/foot chain (Mixamo names, <c>NormBoneName</c>); null without hips.</summary>
    public static PairHeightModifier? TryCreate(Skeleton3D skel)
    {
        int Find(string key)
        {
            for (int i = 0; i < skel.GetBoneCount(); i++)
                if (RestCorrections.NormBoneName(skel.GetBoneName(i)) == key) return i;
            return -1;
        }
        bool Below(int bone, int ancestor)
        {
            for (int p = skel.GetBoneParent(bone); p >= 0; p = skel.GetBoneParent(p)) if (p == ancestor) return true;
            return false;
        }
        int hips = Find("hips");
        if (hips < 0) return null;
        var legs = new (int, int, int)?[2];
        string[] sides = { "left", "right" };
        for (int s = 0; s < 2; s++)
        {
            int u = Find(sides[s] + "upleg"), l = Find(sides[s] + "leg"), f = Find(sides[s] + "foot");
            legs[s] = u >= 0 && l >= 0 && f >= 0 && Below(u, hips) && Below(l, u) && Below(f, l) ? (u, l, f) : null;
        }
        var mod = new PairHeightModifier(hips, legs);
        skel.AddChild(mod);
        skel.MoveChild(mod, 0);
        return mod;
    }

    public override void _ProcessModificationWithDelta(double delta)
    {
        double offset = OffsetM;
        if (!(offset != 0 && double.IsFinite(offset)) || GetSkeleton() is not { } skel) return;
        var basis = skel.IsInsideTree() ? skel.GlobalTransform.Basis : skel.Transform.Basis;
        // world (0, offset, 0) in the skeleton's space (uniform scale and a yaw: still vertical)
        var up = basis.Inverse() * new Vector3(0, (float)offset, 0);
        var held = new (Vector3 Ankle, Basis Foot)?[_legs.Length];
        for (int i = 0; i < _legs.Length; i++)
        {
            if (_legs[i] is not { } leg || i >= Planted.Length || !Planted[i]) continue;
            var g = skel.GetBoneGlobalPose(leg.Foot);
            held[i] = (g.Origin, g.Basis);
        }
        var hips = skel.GetBoneGlobalPose(_hips);
        SetGlobal(skel, _hips, new Transform3D(hips.Basis, hips.Origin + up));
        for (int i = 0; i < _legs.Length; i++)
        {
            if (held[i] is not { } h || _legs[i] is not { } leg) continue;
            var gu = skel.GetBoneGlobalPose(leg.Upper);
            var gl = skel.GetBoneGlobalPose(leg.Lower);
            var gf = skel.GetBoneGlobalPose(leg.Foot);
            var (upper, lower) = LegPin.TwoBoneIk(V(gu.Origin), V(gl.Origin), V(gf.Origin), V(h.Ankle), V(gl.Origin));
            SetGlobal(skel, leg.Upper, new Transform3D(new Basis(Q(upper)) * gu.Basis, gu.Origin));
            gl = skel.GetBoneGlobalPose(leg.Lower);
            SetGlobal(skel, leg.Lower, new Transform3D(new Basis(Q(lower)) * gl.Basis, gl.Origin));
            gf = skel.GetBoneGlobalPose(leg.Foot);
            SetGlobal(skel, leg.Foot, new Transform3D(h.Foot, gf.Origin));
        }
    }

    private static V3 V(Vector3 v) => new(v.X, v.Y, v.Z);
    private static Quaternion Q(WQuat q) => new Quaternion((float)q.X, (float)q.Y, (float)q.Z, (float)q.W).Normalized();

    /// <summary>A bone's pose from a skeleton-space transform (its parent's current global pose inverted).</summary>
    private static void SetGlobal(Skeleton3D skel, int bone, Transform3D global)
    {
        int parent = skel.GetBoneParent(bone);
        var local = parent >= 0 ? skel.GetBoneGlobalPose(parent).AffineInverse() * global : global;
        skel.SetBonePosePosition(bone, local.Origin);
        skel.SetBonePoseRotation(bone, local.Basis.GetRotationQuaternion());
        skel.SetBonePoseScale(bone, local.Basis.Scale);
    }
}
