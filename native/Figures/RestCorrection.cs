using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// A skeleton's REST pose in model-root orientations, keyed by normalised bone
/// name — the port of <c>restPoseOf</c> (packages/scene-render/src/clipRetarget.ts).
/// <c>World</c> = R_b (the product of every node rotation from the model root
/// down to the bone, rest rotations for bones), <c>Parent</c> = the same for the
/// node above (the armature frame for the root bone), <c>ParentBone</c> = the
/// normalised name of the bone above (null at the root bone), <c>Position</c> =
/// the rest head position (full transforms, scale included).
/// Insertion order is the hierarchy walk (parents first), like the JS Map.
/// </summary>
public sealed class RestPose
{
    public List<string> Order { get; } = new();
    public Dictionary<string, Quaternion> World { get; } = new();
    public Dictionary<string, Quaternion> Parent { get; } = new();
    public Dictionary<string, string?> ParentBone { get; } = new();
    public Dictionary<string, Vector3> Position { get; } = new();

    /// <summary>Normalised name of the root bone (first bone without a bone above), or null.</summary>
    public string? RootBone => Order.FirstOrDefault(k => ParentBone[k] is null);

    /// <summary>
    /// Walk <paramref name="root"/> → … → <paramref name="skel"/> (node rotations,
    /// <paramref name="root"/> included, like <c>restPoseOf(three, root)</c>), then
    /// the bones from their rests. Works outside the scene tree.
    /// </summary>
    public static RestPose Of(Node3D root, Skeleton3D skel)
    {
        var pose = new RestPose();
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
            if (!pose.World.ContainsKey(key))
            {
                pose.Order.Add(key);
                pose.World[key] = here;
                pose.Parent[key] = above;
                pose.ParentBone[key] = aboveBone;
                pose.Position[key] = m.Origin;
            }
            foreach (int child in skel.GetBoneChildren(bone)) Walk(child, here, m, key);
        }
        foreach (int r in skel.GetParentlessBones()) Walk(r, aboveQ, aboveXf, null);
        return pose;
    }
}

/// <summary>The two factors of <c>q = Left·c·Right</c> for one bone: K_p⁻¹ and K_b.</summary>
public readonly record struct RestFix(Quaternion Left, Quaternion Right);

/// <summary>
/// The browser's rest-pose correction, ported line for line from
/// <c>restCorrections</c> / <c>legStance</c> / <c>torsoStance</c> /
/// <c>footStance</c> / <c>bindRelativeValues</c> in
/// packages/scene-render/src/clipRetarget.ts (used by client3d
/// <c>figures.fitLibraryAsync</c> → <c>adaptExternalClips</c>). The derivation
/// lives there: the target must DEFORM like the donor, W_t,b = W_d,b·K_b with
/// K_b = R̃_d,b⁻¹·S_b·R̃_t,b (rests read in each rig's ROOT BONE frame, S_b the
/// optional stance turn), hence <c>q_b = K_p⁻¹·c_b·K_b</c>; the root bone's left
/// factor is the armature term (A_d⁻¹·A_t)⁻¹. Bones with both factors under
/// <paramref name="epsDeg"/> are left out (verbatim copy = the exact identity).
///
/// Godot's quaternion product is three's <c>multiply</c> (a*b applies b first),
/// <c>premultiply(x)</c> = <c>x * this</c>.
/// </summary>
public static class RestCorrections
{
    public const double LegStanceToleranceDeg = 3;
    public const double TorsoStanceToleranceDeg = 6;
    public const double FootStanceToleranceDeg = 6;

    private static readonly Vector3 AxisX = new(1, 0, 0), AxisZ = new(0, 0, 1);

    public static Quaternion Apply(RestFix k, Quaternion c) => k.Left * c * k.Right;

    /// <summary>Rotation angle in degrees (<c>angleOf</c>).</summary>
    public static double AngleOf(Quaternion q) => 2 * Math.Acos(Math.Min(1, Math.Abs(q.W))) * (180 / Math.PI);

    /// <param name="stanceBones">optional: receives the bones a stance rule (leg/torso/foot) turned.</param>
    public static Dictionary<string, RestFix> Build(RestPose donor, Node3D targetRoot, Skeleton3D skel,
                                                    double epsDeg = 0.05, ICollection<string>? stanceBones = null)
    {
        var output = new Dictionary<string, RestFix>();
        if (donor.World.Count == 0) return output;
        var self = RestPose.Of(targetRoot, skel);
        // Both rests, read in their own rig's ROOT BONE frame.
        Quaternion? RootRest(RestPose p) => p.RootBone is { } r ? p.World[r] : null;
        var donorRoot = RootRest(donor);
        var selfRoot = RootRest(self);
        Quaternion InRootFrame(Quaternion? root, Quaternion q) => root is { } r ? r.Inverse() * q : q;

        var stance = LegStance(donor, self, donorRoot, selfRoot);
        // Legs descend from the uplegs, the torso from spine; a leg under the spine keeps the leg rule.
        foreach (var (key, s) in TorsoStance(donor, self, donorRoot, selfRoot)) stance.TryAdd(key, s);
        foreach (var (key, s) in FootStance(targetRoot, skel, self, selfRoot, stance)) stance[key] = s;
        if (stanceBones is not null)
            foreach (var key in stance.Keys.Where(donor.World.ContainsKey)) stanceBones.Add(key);

        var k = new Dictionary<string, Quaternion>();
        foreach (var key in self.Order)
        {
            if (!donor.World.TryGetValue(key, out var donorWorld)) continue;
            var kb = InRootFrame(donorRoot, donorWorld).Inverse();
            if (stance.TryGetValue(key, out var s)) kb *= s;
            k[key] = kb * InRootFrame(selfRoot, self.World[key]);
        }
        foreach (var key in self.Order)
        {
            if (!k.TryGetValue(key, out var right)) continue;
            var above = self.ParentBone[key];
            Quaternion left;
            if (above is null)
            {
                // The armature frame: A_d⁻¹·A_t, inverted.
                if (!donor.Parent.TryGetValue(key, out var dp) || !self.Parent.TryGetValue(key, out var tp)) continue;
                left = (dp.Inverse() * tp).Inverse();
            }
            else
            {
                // A parent the donor does not carry leaves this bone alone.
                if (!k.TryGetValue(above, out var parentK)) continue;
                left = parentK.Inverse();
            }
            if (AngleOf(right) > epsDeg || AngleOf(left) > epsDeg) output[key] = new RestFix(left, right);
        }
        return output;
    }

    /// <summary>Every bone at or below <paramref name="top"/> (parent walk, like the JS loops).</summary>
    private static IEnumerable<string> Under(RestPose self, string top)
    {
        foreach (var key in self.Order)
        {
            string? above = key;
            while (above is not null && above != top) above = self.ParentBone.GetValueOrDefault(above);
            if (above == top) yield return key;
        }
    }

    private static Vector3 Rot(Quaternion? inverseRoot, Vector3 v) => inverseRoot is { } q ? q * v : v;

    /// <summary><c>legStance</c>: stand a spread/knock-kneed bind the clip's way (pair mean beyond 3°).</summary>
    private static Dictionary<string, Quaternion> LegStance(RestPose donor, RestPose self, Quaternion? donorRoot, Quaternion? selfRoot)
    {
        var output = new Dictionary<string, Quaternion>();
        double? Angle(RestPose pose, Quaternion? root, string side)
        {
            if (!pose.Position.TryGetValue(side + "upleg", out var hip) || !pose.Position.TryGetValue(side + "foot", out var foot))
                return null;
            var d = Rot(root?.Inverse(), foot - hip);
            return Math.Atan2(d.X, -d.Y);
        }
        var sides = new List<(string Side, double Delta, double Outward)>();
        foreach (var side in new[] { "left", "right" })
        {
            var t = Angle(self, selfRoot, side);
            var d = Angle(donor, donorRoot, side);
            if (!self.Position.TryGetValue(side + "upleg", out var hip) || t is null || d is null) return output;
            var lateral = Rot(selfRoot?.Inverse(), hip);
            var rootKey = self.Order.FirstOrDefault(k => self.ParentBone[k] is null);
            var centre = rootKey is not null ? Rot(selfRoot?.Inverse(), self.Position[rootKey]) : Vector3.Zero;
            double outward = Math.Sign(lateral.X - centre.X);
            if (outward == 0) outward = 1;
            sides.Add((side, d.Value - t.Value, outward * (t.Value - d.Value)));
        }
        double mean = (sides[0].Outward + sides[1].Outward) / 2;
        if (Math.Abs(mean) * 180 / Math.PI <= LegStanceToleranceDeg) return output;
        foreach (var s in sides)
        {
            var rot = new Quaternion(AxisZ, (float)s.Delta);
            foreach (var key in Under(self, s.Side + "upleg")) output[key] = rot;
        }
        return output;
    }

    /// <summary><c>torsoStance</c>: a hollow back beyond 6° (mean of three trunk segments) turned to the donor's.</summary>
    private static Dictionary<string, Quaternion> TorsoStance(RestPose donor, RestPose self, Quaternion? donorRoot, Quaternion? selfRoot)
    {
        var output = new Dictionary<string, Quaternion>();
        string[] chain = { "spine", "spine1", "spine2", "neck", "head" };
        if (chain.Any(k => !donor.Position.ContainsKey(k) || !self.Position.ContainsKey(k))) return output;
        double Angle(RestPose pose, Quaternion? root, int i)
        {
            var d = Rot(root?.Inverse(), pose.Position[chain[i + 1]] - pose.Position[chain[i]]);
            return Math.Atan2(d.Z, d.Y);
        }
        var deltas = Enumerable.Range(0, chain.Length - 1)
                               .Select(i => Angle(donor, donorRoot, i) - Angle(self, selfRoot, i)).ToArray();
        double mean = (deltas[0] + deltas[1] + deltas[2]) / 3;
        if (Math.Abs(mean) * 180 / Math.PI <= TorsoStanceToleranceDeg) return output;
        var segments = new Dictionary<string, Quaternion>();
        for (int i = 0; i < chain.Length - 1; i++) segments[chain[i]] = new Quaternion(AxisX, (float)deltas[i]);
        foreach (var key in self.Order)
        {
            string? above = key;
            while (above is not null && !segments.ContainsKey(above)) above = self.ParentBone.GetValueOrDefault(above);
            if (above is not null) output[key] = segments[above];
        }
        return output;
    }

    /// <summary>
    /// <c>footStance</c>: a heel-up sole (pair mean beyond 6°) laid flat. The sole is
    /// read off the skinned mesh in its rest: per side the lowest vertex behind the
    /// ankle (heel) and ahead of the ball (toe), each vertex assigned by its dominant
    /// skin joint (foot or toe bones of that side). Rest skinning is taken as the
    /// identity (bind = inverse global rest, which is what a glTF skin stores).
    /// </summary>
    private static Dictionary<string, Quaternion> FootStance(Node3D root, Skeleton3D skel, RestPose self,
                                                             Quaternion? selfRoot, Dictionary<string, Quaternion> legs)
    {
        var output = new Dictionary<string, Quaternion>();
        var inverseRoot = selfRoot?.Inverse();
        var sides = new List<(string Side, Vector3 Ankle, Vector3 Ball)>();
        foreach (var side in new[] { "left", "right" })
        {
            if (!self.Position.TryGetValue(side + "foot", out var ankle) || !self.Position.TryGetValue(side + "toebase", out var ball))
                return output;
            sides.Add((side, Rot(inverseRoot, ankle), Rot(inverseRoot, ball)));
        }
        var heel = new[] { new Vector3(0, float.PositiveInfinity, 0), new Vector3(0, float.PositiveInfinity, 0) };
        var toe = new[] { new Vector3(0, float.PositiveInfinity, 0), new Vector3(0, float.PositiveInfinity, 0) };
        foreach (var mi in Meshes(skel))
        {
            if (mi.Mesh is not ArrayMesh mesh || mi.Skin is not { } skin) continue;
            // Skin joint index → side (0 left, 1 right, −1 none).
            var owners = new int[skin.GetBindCount()];
            for (int b = 0; b < owners.Length; b++)
            {
                int bone = skin.GetBindBone(b);
                var name = bone >= 0 ? skel.GetBoneName(bone) : skin.GetBindName(b).ToString();
                var key = ClipLibrary.NormBone(name);
                owners[b] = -1;
                for (int s = 0; s < 2; s++)
                    if (key == sides[s].Side + "foot" || key.StartsWith(sides[s].Side + "toe", StringComparison.Ordinal))
                    { owners[b] = s; break; }
            }
            var xf = RootInclusive(root, mi);
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
                    var v = Rot(inverseRoot, xf * verts[i]);
                    if (v.Z < sides[s].Ankle.Z && v.Y < heel[s].Y) heel[s] = v;
                    if (v.Z > sides[s].Ball.Z && v.Y < toe[s].Y) toe[s] = v;
                }
            }
        }
        if (heel.Concat(toe).Any(v => !float.IsFinite(v.Y))) return output;
        static double Tilt(Vector3 h, Vector3 t) => Math.Atan2(h.Y - t.Y, Math.Abs(t.Z - h.Z));
        var tilts = new double[2];
        for (int s = 0; s < 2; s++)
        {
            var h = heel[s] - sides[s].Ankle;
            var t = toe[s] - sides[s].Ankle;
            if (legs.TryGetValue(sides[s].Side + "foot", out var leg)) { h = leg * h; t = leg * t; }
            tilts[s] = Tilt(h, t);
        }
        double mean = (tilts[0] + tilts[1]) / 2;
        if (mean * 180 / Math.PI <= FootStanceToleranceDeg) return output;
        for (int s = 0; s < 2; s++)
        {
            var top = sides[s].Side + "foot";
            var rot = new Quaternion(AxisX, (float)-tilts[s]);
            if (legs.TryGetValue(top, out var leg)) rot *= leg;
            foreach (var key in Under(self, top)) output[key] = rot;
        }
        return output;
    }

    /// <summary>Skinned meshes driven by <paramref name="skel"/> (its children, as the glTF importer builds them).</summary>
    private static IEnumerable<MeshInstance3D> Meshes(Skeleton3D skel)
    {
        foreach (var child in skel.FindChildren("*", "MeshInstance3D", true, false))
            if (child is MeshInstance3D mi) yield return mi;
    }

    /// <summary>Transform root → node with the root's own transform included (three's <c>matrixWorld</c> of a template).</summary>
    private static Transform3D RootInclusive(Node3D root, Node3D node) => root.Transform * root.GlobalTransformOf(node);
}
