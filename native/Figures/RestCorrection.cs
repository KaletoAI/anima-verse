using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The Godot side of the rest-pose correction — only what needs the engine: read a skeleton's REST pose
/// (<c>restPoseOf</c>) and sample the soles off its skinned mesh (<c>restSolesOf</c>) into plain
/// <see cref="RestPoseData"/>; the math itself is <see cref="RestCorrections"/> in native/Core (vectors
/// shared/test-vectors/retarget.json). Godot's quaternion product equals three's <c>multiply</c>
/// (<c>a * b</c> applies b first), so the conversion is component-wise.
/// </summary>
public static class RestAdapter
{
    public static Quat ToQuat(Quaternion q) => new(q.X, q.Y, q.Z, q.W);
    public static Quaternion ToGodot(Quat q) => new((float)q.X, (float)q.Y, (float)q.Z, (float)q.W);
    private static V3 ToV3(Vector3 v) => new(v.X, v.Y, v.Z);

    /// <summary><c>q = K_p⁻¹·c·K_b</c> in Godot types.</summary>
    public static Quaternion Apply(RestFix k, Quaternion c) => ToGodot(RestCorrections.Apply(k, ToQuat(c)));

    /// <summary>
    /// <c>restPoseOf(three, root)</c>: walk <paramref name="root"/> → … → <paramref name="skel"/> (node rotations,
    /// <paramref name="root"/> included), then the bones from their rests, keyed by <see cref="ClipLibrary.NormBone"/>.
    /// Works outside the scene tree.
    /// </summary>
    public static RestPoseData Of(Node3D root, Skeleton3D skel)
    {
        var pose = new RestPoseData();
        var chain = new List<Node3D>();
        for (Node? n = skel; n is not null; n = n.GetParent())
        {
            if (n is Node3D n3) chain.Add(n3);
            if (n == root) break;
        }
        chain.Reverse();
        var aboveQ = Quaternion.Identity;
        var aboveXf = Transform3D.Identity;
        foreach (var n in chain)
        {
            aboveQ *= n.Quaternion;
            aboveXf *= n.Transform;
        }
        void Walk(int bone, Quaternion above, Transform3D aboveM, string? aboveBone)
        {
            var rest = skel.GetBoneRest(bone);
            var here = above * rest.Basis.GetRotationQuaternion();
            var m = aboveM * rest;
            var key = ClipLibrary.NormBone(skel.GetBoneName(bone));
            pose.Add(key, ToQuat(here), ToQuat(above), aboveBone, ToV3(m.Origin));
            foreach (int child in skel.GetBoneChildren(bone)) Walk(child, here, m, key);
        }
        foreach (int r in skel.GetParentlessBones()) Walk(r, aboveQ, aboveXf, null);
        return pose;
    }

    /// <summary>
    /// <c>restSolesOf(three, target, self)</c>: per side the lowest skinned vertex behind the ankle (heel) and
    /// ahead of the ball (toe), in the root-bone frame; each vertex assigned by its dominant skin joint (the foot or
    /// toe bones of that side). Rest skinning is the identity (bind = inverse global rest, what a glTF skin
    /// stores). A side without a finite heel AND toe is left out (then <c>footStance</c> does nothing).
    /// </summary>
    public static Dictionary<string, Sole> SolesOf(Node3D root, Skeleton3D skel, RestPoseData self)
    {
        var output = new Dictionary<string, Sole>();
        Quat? inverseRoot = self.RootBone is { } rb ? self.World[rb].Inverse() : null;
        V3 Rot(V3 v) => inverseRoot is { } q ? q.Rotate(v) : v;
        var sides = new List<(string Side, V3 Ankle, V3 Ball)>();
        foreach (var side in new[] { "left", "right" })
        {
            if (!self.Position.TryGetValue(side + "foot", out var ankle) || !self.Position.TryGetValue(side + "toebase", out var ball))
                return output;
            sides.Add((side, Rot(ankle), Rot(ball)));
        }
        var inf = new V3(0, double.PositiveInfinity, 0);
        var heel = new[] { inf, inf };
        var toe = new[] { inf, inf };
        foreach (var mi in skel.FindChildren("*", "MeshInstance3D", true, false).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is not ArrayMesh mesh || mi.Skin is not { } skin) continue;
            // Skin joint index → side (0 left, 1 right, −1 none).
            var owners = new int[skin.GetBindCount()];
            for (int b = 0; b < owners.Length; b++)
            {
                int bone = skin.GetBindBone(b);
                var key = ClipLibrary.NormBone(bone >= 0 ? skel.GetBoneName(bone) : skin.GetBindName(b).ToString());
                owners[b] = -1;
                for (int s = 0; s < 2; s++)
                    if (key == sides[s].Side + "foot" || key.StartsWith(sides[s].Side + "toe", StringComparison.Ordinal))
                    { owners[b] = s; break; }
            }
            var xf = root.Transform * root.GlobalTransformOf(mi);
            for (int surf = 0; surf < mesh.GetSurfaceCount(); surf++)
            {
                var arrays = mesh.SurfaceGetArrays(surf);
                var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
                var bones = arrays[(int)Mesh.ArrayType.Bones].AsInt32Array();
                var weights = arrays[(int)Mesh.ArrayType.Weights].AsFloat32Array();
                if (verts.Length == 0 || bones.Length == 0 || weights.Length != bones.Length) continue;
                int per = bones.Length / verts.Length;
                for (int i = 0; i < verts.Length; i++)
                {
                    int dominant = 0;
                    for (int j = 1; j < Math.Min(per, 4); j++)
                        if (weights[i * per + j] > weights[i * per + dominant]) dominant = j;
                    int joint = bones[i * per + dominant];
                    if (joint < 0 || joint >= owners.Length) continue;
                    int s = owners[joint];
                    if (s < 0 || weights[i * per + dominant] <= 0) continue;
                    var v = Rot(ToV3(xf * verts[i]));
                    if (v.Z < sides[s].Ankle.Z && v.Y < heel[s].Y) heel[s] = v;
                    if (v.Z > sides[s].Ball.Z && v.Y < toe[s].Y) toe[s] = v;
                }
            }
        }
        for (int s = 0; s < 2; s++)
            if (double.IsFinite(heel[s].Y) && double.IsFinite(toe[s].Y)) output[sides[s].Side] = new Sole(heel[s], toe[s]);
        return output;
    }

    /// <summary>
    /// <c>restCorrections(three, donor, template)</c> for a Godot skeleton: its rest pose + soles, then the Core math.
    /// </summary>
    public static Dictionary<string, RestFix> Build(RestPoseData donor, Node3D targetRoot, Skeleton3D skel,
                                                    double epsDeg = 0.05, ICollection<string>? stanceBones = null)
    {
        var self = Of(targetRoot, skel);
        self.Soles = SolesOf(targetRoot, skel, self);
        return RestCorrections.Build(donor, self, epsDeg, stanceBones);
    }
}
