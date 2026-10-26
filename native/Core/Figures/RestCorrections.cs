using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>Lowest heel and toe point of one sole, in the root-bone frame (<c>RestPose.soles</c>).</summary>
public readonly record struct Sole(V3 Heel, V3 Toe);

/// <summary>
/// A skeleton's REST pose as plain data — the pose-data form of <c>RestPose</c> in
/// packages/scene-render/src/clipRetarget.ts. Keys are normalised bone names;
/// <see cref="Order"/> is the hierarchy walk (parents first), the iteration order of the JS Maps.
/// <c>World</c> = R_b (every node rotation from the model root down to the bone), <c>Parent</c> = the same
/// for the node above (the armature frame for the root bone), <c>ParentBone</c> = the bone above (null at the
/// root bone), <c>Position</c> = the rest head position, <c>Soles</c> = optional sole points per side
/// (<c>left</c>/<c>right</c>) that the Godot adapter samples off the skinned mesh (<c>restSolesOf</c>).
/// </summary>
public sealed class RestPoseData
{
    public List<string> Order { get; } = new();
    public Dictionary<string, Quat> World { get; } = new();
    public Dictionary<string, Quat> Parent { get; } = new();
    public Dictionary<string, string?> ParentBone { get; } = new();
    public Dictionary<string, V3> Position { get; } = new();
    public Dictionary<string, Sole>? Soles { get; set; }

    /// <summary>Add a bone (first one of a key wins, like <c>restPoseOf</c>'s <c>!world.has(key)</c>).</summary>
    public void Add(string key, Quat world, Quat parent, string? parentBone, V3 position)
    {
        if (World.ContainsKey(key)) return;
        Order.Add(key);
        World[key] = world;
        Parent[key] = parent;
        ParentBone[key] = parentBone;
        Position[key] = position;
    }

    /// <summary>The root bone: the first bone in walk order without a bone above (<c>rootRest</c>'s loop), or null.</summary>
    public string? RootBone => Order.FirstOrDefault(k => ParentBone[k] is null);
}

/// <summary>The two factors of <c>q = Left·c·Right</c> for one bone: K_p⁻¹ and K_b (<c>RestCorrection</c>).</summary>
public readonly record struct RestFix(Quat Left, Quat Right);

/// <summary>One keyframe track of a clip as plain data (three <c>KeyframeTrack</c>: name, times, flat values).</summary>
public sealed record ClipTrack(string Name, float[] Times, float[] Values);

/// <summary>
/// The browser's rest-pose correction on plain pose data, ported line for line from
/// <c>restCorrections</c> / <c>legStance</c> / <c>torsoStance</c> / <c>footStance</c> /
/// <c>bindRelativeValues</c> / <c>bindRelativeClip</c> in packages/scene-render/src/clipRetarget.ts
/// (vectors: shared/test-vectors/retarget.json, hand derivations in scripts/smoke_clip_retarget.mjs).
/// The target must DEFORM like the donor, W_t,b = W_d,b·K_b with K_b = R̃_d,b⁻¹·S_b·R̃_t,b (rests read in
/// each rig's ROOT BONE frame, S_b the optional stance turn), hence <c>q_b = K_p⁻¹·c_b·K_b</c>; the root
/// bone's left factor is the armature term (A_d⁻¹·A_t)⁻¹. Bones whose two factors both stay under
/// <c>epsDeg</c> are left out (verbatim copy = the exact identity). Quaternion products follow three
/// (<see cref="Quat"/>): <c>a.multiply(b)</c> = <c>a * b</c>, <c>a.premultiply(x)</c> = <c>x * a</c>.
/// The Godot side only reads rests and samples soles off the mesh (native/Figures/RestCorrection.cs).
/// </summary>
public static class RestCorrections
{
    public const double LegStanceToleranceDeg = 3;
    public const double TorsoStanceToleranceDeg = 6;
    public const double FootStanceToleranceDeg = 6;

    private static readonly V3 AxisX = new(1, 0, 0), AxisZ = new(0, 0, 1);
    private static readonly Regex MixamoPrefix = new("^mixamorig:?", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>The browser's <c>normBoneName</c>: strip a leading <c>mixamorig</c>/<c>mixamorig:</c>, drop colons, lower-case.</summary>
    public static string NormBoneName(string name) => MixamoPrefix.Replace(name, "").Replace(":", "").ToLowerInvariant();

    /// <summary>Rotation angle in degrees (<c>angleOf</c>).</summary>
    public static double AngleOf(Quat q) => 2 * Math.Acos(Math.Min(1, Math.Abs(q.W))) * (180 / Math.PI);

    /// <summary><c>q.premultiply(k.left).multiply(k.right)</c>.</summary>
    public static Quat Apply(RestFix k, Quat c) => k.Left * c * k.Right;

    private static V3 Rot(Quat? inverseRoot, V3 v) => inverseRoot is { } q ? q.Rotate(v) : v;

    /// <summary>Every bone at or below <paramref name="top"/> (the JS parent walks over <c>self.world.keys()</c>).</summary>
    private static IEnumerable<string> Under(RestPoseData self, string top)
    {
        foreach (var key in self.Order)
        {
            string? above = key;
            while (above is not null && above != top) above = self.ParentBone.GetValueOrDefault(above);
            if (above == top) yield return key;
        }
    }

    /// <summary><c>restCorrections(three, donor, target, epsDeg)</c> on pose data.</summary>
    /// <param name="stanceBones">optional: receives the bones a stance rule turned (for the importer cross-check).</param>
    public static Dictionary<string, RestFix> Build(RestPoseData donor, RestPoseData self, double epsDeg = 0.05,
                                                    ICollection<string>? stanceBones = null)
    {
        var output = new Dictionary<string, RestFix>();
        if (donor.World.Count == 0) return output;
        Quat? RootRest(RestPoseData p) => p.RootBone is { } r ? p.World[r] : null;
        var donorRoot = RootRest(donor);
        var targetRoot = RootRest(self);
        Quat InRootFrame(Quat? root, Quat q) => root is { } r ? r.Inverse() * q : q;

        var stance = LegStance(donor, self, donorRoot, targetRoot);
        foreach (var (key, s) in TorsoStance(donor, self, donorRoot, targetRoot)) stance.TryAdd(key, s);
        foreach (var (key, s) in FootStance(self, targetRoot, stance)) stance[key] = s;
        if (stanceBones is not null)
            foreach (var key in stance.Keys.Where(donor.World.ContainsKey)) stanceBones.Add(key);

        var k = new Dictionary<string, Quat>();
        var kOrder = new List<string>();
        foreach (var key in self.Order)
        {
            if (!donor.World.TryGetValue(key, out var donorWorld)) continue;
            var kb = InRootFrame(donorRoot, donorWorld).Inverse();
            if (stance.TryGetValue(key, out var s)) kb *= s;
            k[key] = kb * InRootFrame(targetRoot, self.World[key]);
            kOrder.Add(key);
        }
        foreach (var key in kOrder)
        {
            var right = k[key];
            var above = self.ParentBone.GetValueOrDefault(key);
            Quat left;
            if (above is null)
            {
                if (!donor.Parent.TryGetValue(key, out var dp) || !self.Parent.TryGetValue(key, out var tp)) continue;
                left = (dp.Inverse() * tp).Inverse();
            }
            else
            {
                if (!k.TryGetValue(above, out var parentK)) continue;
                left = parentK.Inverse();
            }
            if (AngleOf(right) > epsDeg || AngleOf(left) > epsDeg) output[key] = new RestFix(left, right);
        }
        return output;
    }

    /// <summary><c>legStance</c>: stand a spread/knock-kneed bind the clip's way (pair mean beyond 3°).</summary>
    private static Dictionary<string, Quat> LegStance(RestPoseData donor, RestPoseData self, Quat? donorRoot, Quat? targetRoot)
    {
        var output = new Dictionary<string, Quat>();
        double? Angle(RestPoseData pose, Quat? root, string side)
        {
            if (!pose.Position.TryGetValue(side + "upleg", out var hip) || !pose.Position.TryGetValue(side + "foot", out var foot))
                return null;
            var d = Rot(root?.Inverse(), foot - hip);
            return Math.Atan2(d.X, -d.Y);
        }
        var sides = new List<(string Side, double Delta, double Outward)>();
        foreach (var side in new[] { "left", "right" })
        {
            var t = Angle(self, targetRoot, side);
            var d = Angle(donor, donorRoot, side);
            if (!self.Position.TryGetValue(side + "upleg", out var hip) || t is null || d is null) return output;
            var lateral = Rot(targetRoot?.Inverse(), hip);
            var rootKey = self.RootBone;
            var centre = rootKey is not null ? Rot(targetRoot?.Inverse(), self.Position[rootKey]) : V3.Zero;
            double outward = Math.Sign(lateral.X - centre.X);
            if (outward == 0) outward = 1;
            sides.Add((side, d.Value - t.Value, outward * (t.Value - d.Value)));
        }
        double mean = (sides[0].Outward + sides[1].Outward) / 2;
        if (Math.Abs(mean) * 180 / Math.PI <= LegStanceToleranceDeg) return output;
        foreach (var s in sides)
        {
            var rot = Quat.FromAxisAngle(AxisZ, s.Delta);
            foreach (var key in Under(self, s.Side + "upleg")) output[key] = rot;
        }
        return output;
    }

    /// <summary><c>torsoStance</c>: a hollow back beyond 6° (mean of three trunk segments) turned to the donor's.</summary>
    private static Dictionary<string, Quat> TorsoStance(RestPoseData donor, RestPoseData self, Quat? donorRoot, Quat? targetRoot)
    {
        var output = new Dictionary<string, Quat>();
        string[] chain = { "spine", "spine1", "spine2", "neck", "head" };
        if (chain.Any(k => !donor.Position.ContainsKey(k) || !self.Position.ContainsKey(k))) return output;
        double Angle(RestPoseData pose, Quat? root, int i)
        {
            var d = Rot(root?.Inverse(), pose.Position[chain[i + 1]] - pose.Position[chain[i]]);
            return Math.Atan2(d.Z, d.Y);
        }
        var deltas = Enumerable.Range(0, chain.Length - 1)
                               .Select(i => Angle(donor, donorRoot, i) - Angle(self, targetRoot, i)).ToArray();
        double mean = (deltas[0] + deltas[1] + deltas[2]) / 3;
        if (Math.Abs(mean) * 180 / Math.PI <= TorsoStanceToleranceDeg) return output;
        var segments = new Dictionary<string, Quat>();
        for (int i = 0; i < chain.Length - 1; i++) segments[chain[i]] = Quat.FromAxisAngle(AxisX, deltas[i]);
        foreach (var key in self.Order)
        {
            string? above = key;
            while (above is not null && !segments.ContainsKey(above)) above = self.ParentBone.GetValueOrDefault(above);
            if (above is not null) output[key] = segments[above];
        }
        return output;
    }

    /// <summary><c>footStance</c>: a heel-up sole (pair mean beyond 6°) laid flat, from <see cref="RestPoseData.Soles"/>.</summary>
    private static Dictionary<string, Quat> FootStance(RestPoseData self, Quat? targetRoot, Dictionary<string, Quat> legs)
    {
        var output = new Dictionary<string, Quat>();
        var inverseRoot = targetRoot?.Inverse();
        var sides = new List<(string Side, V3 Ankle, V3 Heel, V3 Toe)>();
        foreach (var side in new[] { "left", "right" })
        {
            if (!self.Position.TryGetValue(side + "foot", out var ankle) || !self.Position.ContainsKey(side + "toebase"))
                return output;
            sides.Add((side, Rot(inverseRoot, ankle), default, default));
        }
        for (int i = 0; i < 2; i++)
        {
            if (self.Soles is null || !self.Soles.TryGetValue(sides[i].Side, out var sole)) return output;
            sides[i] = (sides[i].Side, sides[i].Ankle, sole.Heel, sole.Toe);
        }
        if (sides.Any(s => !double.IsFinite(s.Heel.Y) || !double.IsFinite(s.Toe.Y))) return output;
        static double Tilt(V3 h, V3 t) => Math.Atan2(h.Y - t.Y, Math.Abs(t.Z - h.Z));
        var tilts = new double[2];
        for (int i = 0; i < 2; i++)
        {
            var heel = sides[i].Heel - sides[i].Ankle;
            var toe = sides[i].Toe - sides[i].Ankle;
            if (legs.TryGetValue(sides[i].Side + "foot", out var leg)) { heel = leg.Rotate(heel); toe = leg.Rotate(toe); }
            tilts[i] = Tilt(heel, toe);
        }
        double mean = (tilts[0] + tilts[1]) / 2;
        if (mean * 180 / Math.PI <= FootStanceToleranceDeg) return output;
        for (int i = 0; i < 2; i++)
        {
            var top = sides[i].Side + "foot";
            var rot = Quat.FromAxisAngle(AxisX, -tilts[i]);
            if (legs.TryGetValue(top, out var leg)) rot *= leg;
            foreach (var key in Under(self, top)) output[key] = rot;
        }
        return output;
    }

    /// <summary>
    /// <c>bindRelativeValues(three, values, k)</c>: every quaternion of a flat <c>[x,y,z,w,…]</c> track as
    /// <c>K_p⁻¹·c·K_b</c>, written to Float32 like the browser; null without a correction (keep the track).
    /// </summary>
    public static float[]? BindRelativeValues(IReadOnlyList<double> values, RestFix? k)
    {
        if (k is not { } fix) return null;
        var output = new float[values.Count];
        for (int i = 0; i + 3 < values.Count; i += 4)
        {
            var q = Apply(fix, new Quat(values[i], values[i + 1], values[i + 2], values[i + 3]));
            output[i] = (float)q.X; output[i + 1] = (float)q.Y; output[i + 2] = (float)q.Z; output[i + 3] = (float)q.W;
        }
        return output;
    }

    /// <summary>
    /// <c>bindRelativeClip(three, clip, corrections)</c>: the clip's quaternion tracks through
    /// <see cref="BindRelativeValues"/>, keyed by <see cref="NormBoneName"/> of the track's node. No correction or
    /// no touched track → the SAME list back; untouched tracks stay the same objects.
    /// </summary>
    public static IReadOnlyList<ClipTrack> BindRelativeClip(IReadOnlyList<ClipTrack> tracks,
                                                            IReadOnlyDictionary<string, RestFix> corrections)
    {
        if (corrections.Count == 0) return tracks;
        var output = new List<ClipTrack>(tracks.Count);
        int touched = 0;
        foreach (var track in tracks)
        {
            int dot = track.Name.LastIndexOf('.');
            RestFix? k = dot > 0 && track.Name[(dot + 1)..] == "quaternion"
                         && corrections.TryGetValue(NormBoneName(track.Name[..dot]), out var f) ? f : null;
            var values = BindRelativeValues(track.Values.Select(v => (double)v).ToArray(), k);
            if (values is null) { output.Add(track); continue; }
            touched++;
            output.Add(new ClipTrack(track.Name, track.Times, values));
        }
        return touched == 0 ? tracks : output;
    }
}
