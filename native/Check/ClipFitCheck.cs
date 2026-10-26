using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check clips</c> (part of every <c>--check</c>, Task 35b, ruling P3-R15): the LAZY clip fit — the live client's
/// mode, with its worker threads and main-thread turns — on the bridges world (<c>fixtures/bridges/</c>: Test3_mia and
/// Soldier, the real clip library with its root-motion bridges) and the pairs world (<c>fixtures/pairs/</c>), measured
/// against an EAGER fit of the same world (every clip at build, on the main thread: the arithmetic every other check
/// runs on).
///
///   C1 the build fits the movement poses and what each figure plays (its activity), nothing else: Mia's chair bridge
///      is planned (an action) but not fitted, and her first frame already plays her activity;
///   C2 a clip played the first time later: poll 2 asks Mia and Bea to stand up through bridges nobody fitted yet. While
///      the bridge clips are fitted the figures hold — no step out of the chair, Bea's root stays on the bed — and then
///      the bridges open with the whole height handed to the lift, as on the eager fit's first frame (B2);
///   C3 identity: every action of every template, fitted lazily (the bridges on first play, the rest afterwards),
///      against the eager fit — every track's path, type, interpolation and every key's time, transition and value bit
///      for bit, the loop mode and length, and the extras (travel, turn, lift, pivot, ground offset) bit for bit;
///   C4 the same POSE: lazy and eager figure of each character, the same clip at the same times — every bone's
///      position, rotation and scale bit for bit;
///   C5 memory: the lazy fit holds fewer keys than the eager fit until everything was played;
///   C6 a pair half adopted later (pairs world, poll 2: Ben joins Ann) holds the figure on its point until fitted, then
///      plays in phase with its partner.
/// </summary>
public static class ClipFitCheck
{
    private const double Dt = 1.0 / 30;
    /// <summary>The bed surface Bea's root lies on before poll 2 (as in <see cref="BridgeCheck"/>).</summary>
    private const double BedM = 0.40;
    /// <summary>How many frames a lazy fit may take in the check (headless, small rigs) before it counts as stuck.</summary>
    private const int MaxWaitFrames = 120;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var bridges = await BridgesAsync(host, fixtures);
        var pairs = await PairsAsync(host, fixtures);
        var report = $"clips C1..C6 ok ({bridges}; {pairs})";
        GD.Print($"[check-clips] {report}");
        return report;
    }

    private static FigureManager Manager(FixtureSource source, WorldBuilder builder, ClipFitMode mode, string tag)
        => new(source, builder.Height!, line => GD.Print($"[check-clips {tag}] " + line), strict: true)
        {
            ClipFit = mode, AutoTick = false, Slots = () => builder.Slots,
            GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
            SeatYAt = builder.PairSeatY, RoomStandAt = builder.PairRoomStandY,
        };

    private static async Task<string> BridgesAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "bridges");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "ClipFitWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-clips] " + line), strict: true);
        try
        {
            await builder.BuildAsync(world, "Hall");
            var lazy = Manager(source, builder, ClipFitMode.Lazy, "lazy");
            world.AddChild(lazy);
            await lazy.InitAsync();
            await Apply(lazy, dir, "worldmap.json");
            var mia = lazy.Figures["Mia Chair"];
            var bea = lazy.Figures["Bea Bed"];
            var miaClips = lazy.ClipsOf(mia.CharacterName) ?? throw new InvalidOperationException("clips: Mia has no lazy template");
            var beaClips = lazy.ClipsOf(bea.CharacterName) ?? throw new InvalidOperationException("clips: Bea has no lazy template");

            // ---- C1 what the build fitted ----
            Expect("C1 Mia's chair bridge is an action of her rig", mia.ClipKinds.Contains("get-up-chair"), string.Join(",", mia.ClipKinds));
            Expect("C1 ... but not fitted at build", !mia.Player!.HasAnimation("get-up-chair") && !bea.Player!.HasAnimation("get-up-bed"),
                   "fitted");
            foreach (var (fig, kinds) in new[] { (mia, new[] { "idle", "walk", "sitting-at-the-table" }), (bea, new[] { "idle", "walk", "laying" }) })
                foreach (var k in kinds)
                    Expect($"C1 {fig.CharacterName}: '{k}' fitted before the body was shown", fig.Player!.HasAnimation(k), "missing");
            int miaBuilt = miaClips.FittedClips, miaPlanned = miaClips.FittableClips;
            Expect("C1 Mia's template fitted fewer clips than it plans", miaBuilt < miaPlanned, $"{miaBuilt} of {miaPlanned}");
            lazy.Tick(0.1);
            Expect("C1 the first frame plays the activity", mia.CurrentKind == "sitting-at-the-table" && bea.CurrentKind == "laying",
                   $"{mia.CurrentKind} {bea.CurrentKind}");
            for (int i = 0; i < 30; i++) lazy.Tick(Dt);
            bea.Position = new Vector3(bea.Position.X, (float)BedM, bea.Position.Z);
            var seat = mia.Position;
            var bed = bea.Position;

            // ---- C2 the bridges asked for the first time ----
            await Apply(lazy, dir, "worldmap_poll2.json");
            int waited = 0;
            bool held = true;
            lazy.Tick(Dt);
            Expect("C2 F1: the chair bridge is being fitted, Mia still sits", !mia.Bridging && mia.CurrentKind == "sitting-at-the-table"
                   && mia.PendingBridgeAccel is <= 0, $"bridging {mia.Bridging} kind {mia.CurrentKind}");
            while ((!mia.Bridging || !bea.Bridging) && waited < MaxWaitFrames)
            {
                held &= (mia.Bridging || Same(mia.Position, seat)) && (bea.Bridging || Same(bea.Position, bed));
                await NextFrame(host);
                lazy.Tick(Dt);
                waited++;
            }
            Expect("C2 the bridges opened once fitted", mia.Bridging && mia.CurrentKind == "get-up-chair" && bea.Bridging
                   && bea.CurrentKind == "get-up-bed", $"after {waited} frames: {mia.CurrentKind} {bea.CurrentKind}");
            Expect("C2 while waiting Mia kept her seat and Bea her bed (position and height)", held, "moved");
            Expect("C2 Mia's opening frame holds facing, height and pace", mia.HoldsFacing && mia.HoldsHeight && mia.PaceLimit == 0,
                   $"facing {mia.HoldsFacing} height {mia.HoldsHeight} pace {mia.PaceLimit}");
            NearD("C2 Bea's root on the floor", bea.Position.Y, 0, 1e-6);
            NearD("C2 Bea's lift = the whole bed (0.40 m), as on the eager fit's F1", bea.Lift, BedM, 1e-6);
            double longest = lazy.LongestClipTurnMs;

            // ---- C3 identity against the eager fit ----
            var eager = Manager(source, builder, ClipFitMode.Eager, "eager");
            world.AddChild(eager);
            await eager.InitAsync();
            await Apply(eager, dir, "worldmap.json");
            long heldLazy = lazy.UniqueClipKeys, heldEager = eager.UniqueClipKeys;
            int actions = 0, tracks = 0, extras = 0;
            long keys = 0;
            var names = lazy.Figures.Keys.OrderBy(n => n, StringComparer.Ordinal).ToList();
            foreach (var name in names)
            {
                var a = lazy.ClipsOf(name);
                var b = eager.ClipsOf(name);
                if (a is null || b is null) continue;
                Expect($"C3 {name}: the same plan", a.Actions.SequenceEqual(b.Actions) && a.PlannedKeys == b.PlannedKeys,
                       $"{a.Actions.Count}/{b.Actions.Count} actions");
                await a.EnsureAllAsync();
                foreach (var action in a.Actions)
                {
                    var x = a.Library.GetAnimation(action);
                    var y = b.Library.GetAnimation(action);
                    Expect($"C3 {name} {action}: keys bit for bit", SameKeys(x, y, out string why, ref tracks, ref keys), why);
                    var ex = a.Extras.TryGetValue(x, out var e1) ? Bits(e1) : "none";
                    var ey = b.Extras.TryGetValue(y, out var e2) ? Bits(e2) : "none";
                    Expect($"C3 {name} {action}: extras bit for bit", ex == ey, $"{ex} vs {ey}");
                    if (ex != "none") extras++;
                    actions++;
                }
            }
            Expect("C3 compared the library", actions > 0 && keys > 0, $"{actions} actions");

            // ---- C4 the same pose ----
            int poses = 0;
            foreach (var name in new[] { "Mia Chair", "Bea Bed" })
            {
                var lf = lazy.Figures[name];
                var ef = eager.Figures[name];
                foreach (var action in new[] { name == "Mia Chair" ? "get-up-chair" : "get-up-bed", "idle", "walk" })
                {
                    double len = lf.Player!.GetAnimation(action).Length;
                    foreach (double t in new[] { 0, 0.37, len / 2, len * 0.9, len })
                    {
                        Expect($"C4 {name} {action} @ {t:0.###} s: the same pose bit for bit", SamePose(lf, ef, action, t, out string why), why);
                        poses++;
                    }
                }
            }

            // ---- C5 memory ----
            Expect("C5 the lazy fit held fewer keys than the eager fit before everything was played", heldLazy < heldEager,
                   $"{heldLazy} vs {heldEager}");
            var fits = lazy.ClipFits.Where(f => f.OnDemand).ToList();
            lazy.QueueFree();
            eager.QueueFree();
            return $"Mia {miaBuilt} of {miaPlanned} clips fitted before her body was shown, bridges fitted on first play in {waited} frames, "
                   + $"longest main-thread turn {longest:0.0} ms; lazy = eager: {actions} actions, {tracks} tracks, {keys} keys, "
                   + $"{extras} extras bit-identical, {poses} poses bit-identical; held keys {heldLazy} lazy vs {heldEager} eager; "
                   + $"{fits.Count} on-demand fits, worker {fits.Sum(f => f.WorkerMs):0} ms, main {fits.Sum(f => f.MainMs):0.0} ms";
        }
        finally
        {
            world.QueueFree();
        }
    }

    private static async Task<string> PairsAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "pairs");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "ClipFitPairs" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-clips] " + line), strict: true);
        try
        {
            await builder.BuildAsync(world, "Inn");
            builder.Slots["loc-inn"].Fade.Snap(1);
            var lazy = Manager(source, builder, ClipFitMode.Lazy, "pairs");
            world.AddChild(lazy);
            await lazy.InitAsync();
            await Apply(lazy, dir, "worldmap.json");
            Figure ann = lazy.Figures["Ann Hand"], ben = lazy.Figures["Ben Hand"];
            Expect("C6 Ann's half was fitted before her body was shown", ann.Player!.HasAnimation("greeting-handshake__a"), "missing");
            for (int i = 0; i < 30; i++) lazy.Tick(Dt);
            Expect("C6 Ann plays her half from the first second", ann.CurrentClip == "greeting-handshake__a", ann.CurrentClip);
            Expect("C6 Ben's half is not fitted before he joins", !ben.Player!.HasAnimation("greeting-handshake__b"), "fitted");
            var own = ben.Position;
            await Apply(lazy, dir, "worldmap_poll2.json");
            int waited = 0;
            bool held = true;
            lazy.Tick(Dt);
            while (ben.CurrentClip != "greeting-handshake__b" && waited < MaxWaitFrames)
            {
                held &= Same(ben.Position, own);
                await NextFrame(host);
                lazy.Tick(Dt);
                waited++;
            }
            Expect("C6 Ben plays his half once fitted", ben.CurrentClip == "greeting-handshake__b", $"after {waited} frames: {ben.CurrentClip}");
            Expect("C6 while waiting Ben held his own point", held && waited > 0, $"held {held} waited {waited}");
            NearD("C6 Ben's player at his clip clock + 1 frame (seek, then advance)", ben.ClipTime, ben.Pair!.ClipT + Dt, 1e-4);
            NearD("C6 Ann and Ben in phase", ann.ClipTime - ben.ClipTime, 0, 1e-4);
            lazy.QueueFree();
            return $"pair half fitted on join in {waited} frames, in phase";
        }
        finally
        {
            world.QueueFree();
        }
    }

    private static async Task Apply(FigureManager mgr, string dir, string file)
    {
        using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, file)));
        await mgr.Apply(map.RootElement);
    }

    private static async Task NextFrame(Node host) => await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);

    private static bool Same(Vector3 a, Vector3 b) => a == b;

    /// <summary>Two animations with the same tracks and keys, bit for bit (times, transitions, values), loop mode and length.</summary>
    private static bool SameKeys(Animation a, Animation b, out string why, ref int tracks, ref long keys)
    {
        why = "";
        if (a.GetTrackCount() != b.GetTrackCount() || BitConverter.DoubleToInt64Bits(a.Length) != BitConverter.DoubleToInt64Bits(b.Length)
            || a.LoopMode != b.LoopMode) { why = "header"; return false; }
        for (int t = 0; t < a.GetTrackCount(); t++)
        {
            int n = a.TrackGetKeyCount(t);
            if (a.TrackGetPath(t) != b.TrackGetPath(t) || a.TrackGetType(t) != b.TrackGetType(t) || n != b.TrackGetKeyCount(t)
                || a.TrackGetInterpolationType(t) != b.TrackGetInterpolationType(t)) { why = $"track {t}"; return false; }
            tracks++;
            for (int k = 0; k < n; k++)
            {
                keys++;
                if (BitConverter.DoubleToInt64Bits(a.TrackGetKeyTime(t, k)) != BitConverter.DoubleToInt64Bits(b.TrackGetKeyTime(t, k))
                    || BitConverter.SingleToInt32Bits(a.TrackGetKeyTransition(t, k)) != BitConverter.SingleToInt32Bits(b.TrackGetKeyTransition(t, k))
                    || ValueBits(a.TrackGetKeyValue(t, k)) != ValueBits(b.TrackGetKeyValue(t, k)))
                {
                    why = $"track {a.TrackGetPath(t)} key {k}";
                    return false;
                }
            }
        }
        return true;
    }

    private static string ValueBits(Variant v) => v.VariantType switch
    {
        Variant.Type.Quaternion => Hex(v.AsQuaternion().X, v.AsQuaternion().Y, v.AsQuaternion().Z, v.AsQuaternion().W),
        Variant.Type.Vector3 => Hex(v.AsVector3().X, v.AsVector3().Y, v.AsVector3().Z),
        _ => v.ToString(),
    };

    private static string Hex(params float[] f) => string.Join(",", f.Select(x => BitConverter.SingleToInt32Bits(x).ToString("x8")));
    private static string Hex(params double[] d) => string.Join(",", d.Select(x => BitConverter.DoubleToInt64Bits(x).ToString("x16")));

    /// <summary>Every number of a clip's extras by its bits.</summary>
    private static string Bits(ClipExtras x)
    {
        var sb = new StringBuilder();
        sb.Append("g:").Append(Hex(x.GroundOffset));
        if (x.Path is { } p) sb.Append(" path:").Append(Hex(p.Times)).Append('/').Append(Hex(p.Xz));
        if (x.Turn is { } t) sb.Append(" turn:").Append(Hex(t.Times)).Append('/').Append(Hex(t.Yaw)).Append('/').Append(Hex(t.Pivot.X, t.Pivot.Y, t.Pivot.Z));
        if (x.Lift is { } l) sb.Append(" lift:").Append(Hex(l.EndLift, l.FirstContactS));
        if (x.PivotFrame is { } f) sb.Append(" pivot:").Append(Hex(f.X, f.Y, f.Z));
        return sb.ToString();
    }

    /// <summary>
    /// Both figures' players on <paramref name="action"/> alone (stopped, started without a blend), sought to
    /// <paramref name="t"/> with an update: every bone's pose position / rotation / scale bit for bit.
    /// </summary>
    private static bool SamePose(Figure a, Figure b, string action, double t, out string why)
    {
        why = "";
        var sa = Pose(a, action, t);
        var sb = Pose(b, action, t);
        if (sa.Count != sb.Count) { why = $"{sa.Count} vs {sb.Count} bones"; return false; }
        for (int i = 0; i < sa.Count; i++)
            if (sa[i] != sb[i]) { why = $"bone {i}: {sa[i]} vs {sb[i]}"; return false; }
        return true;
    }

    private static List<string> Pose(Figure f, string action, double t)
    {
        var p = f.Player!;
        var skel = f.Skeleton!;
        p.Stop();
        p.Play(action, 0);
        p.Seek(t, true);
        var list = new List<string>();
        for (int i = 0; i < skel.GetBoneCount(); i++)
        {
            var pos = skel.GetBonePosePosition(i);
            var rot = skel.GetBonePoseRotation(i);
            var sc = skel.GetBonePoseScale(i);
            list.Add($"{Hex(pos.X, pos.Y, pos.Z)}|{Hex(rot.X, rot.Y, rot.Z, rot.W)}|{Hex(sc.X, sc.Y, sc.Z)}");
        }
        return list;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"clips: {what} FAILED ({detail})");
    }

    private static void NearD(string what, double got, double want, double tol)
    {
        Expect(what, double.IsFinite(got) && Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");
        GD.Print($"[check-clips] {what}: {got:0.######}");
    }
}
