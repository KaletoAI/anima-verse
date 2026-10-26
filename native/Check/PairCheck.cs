using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check pairs</c> (part of every <c>--check</c>, Task 32): pair clips like the browser (§ A8a: npcs.ts
/// <c>adoptInteraction</c> / <c>tickInteraction</c>, figures.ts <c>playPair</c>) and the figure normalisation (ruling
/// P3-R14, the Figure constructor's bind anchoring) on the hand-written world <c>fixtures/pairs/</c> (README "Pairs
/// world"): the placement world's inn and ground, real rigs (Test3_mia for role a, Soldier for role b), the real pair
/// clips (greeting-handshake, greeting-hug, comforting__b only), sitting-at-the-table + get-up-chair, and a box model
/// whose mesh bottom lies at −0.3 m. Measured at the consumer: the figures' roots, their players' clip times, their bodies.
///
///   Q0 normalisation: the box stands with its lowest point on the root and its XZ centre on it (offset (−0.6, 0.6,
///      0.2) at scale 2); every skinned body's bind box likewise (Test3_mia's mesh bottom lies 1.0 model units under its
///      origin — 0.85 m sunk before);
///   Q1 the root path of the halves is the sidecar's (handshake ±0.367 m, hug ±0.212 m, comforting__b +0.300 m);
///   Q2 the anchor transform and the height rule: on the ground (terrain), on a place (slot 0), in a room (its stand);
///   Q3 lockstep: two halves adopted at the same server time play the same clip time; after a resync (a poll 0.5 s
///      ahead: one figure snaps, its partner adopts) they are in phase again; a poll within 0.3 s keeps the local clock;
///   Q4 a frozen world (rate 0) stops the clip and the clock;
///   Q5 the solo fallback: a half the library lacks leaves its figure at its own point with its ordinary clip, the
///      partner still plays at the anchor;
///   Q6 <c>playPair</c> ends a running bridge (getting up from a chair when the handshake comes);
///   Q7 a one-shot holds its last frame, both partners alike;
///   Q8 the loop flag is per figure (Task 35): two figures sharing one Animation, one playing it once and one as a cycle,
///      each keeps its own end — the shared Animation keeps the listing's flag, the one-shot figure plays a bit-identical
///      twin;
///   Q9 clip memory (Task 35): the one-call key writer stores every key bit for bit as the key-by-key insert and frees
///      less memory; the same model fitted at another height shares every clip object except the re-locked bridges.
/// </summary>
public static class PairCheck
{
    private const double Dt = 1.0 / 30;
    /// <summary>Godot's float positions (world metres around x 64 carry ~4e-6).</summary>
    private const double PosTol = 1e-4;
    /// <summary>The sidecars round the roots to 3 decimals.</summary>
    private const double SidecarTol = 1e-3;
    private const double ClipTol = 1e-4;

    /// <summary>The ground of the fixture world (README "Terrain": g(x, z) = x/32 + z/64 on tile (0, 0)).</summary>
    private static double G(double x, double z) => x / 32 + z / 64;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "pairs");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "PairWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-pairs] " + line), strict: true);
        try
        {
            await builder.BuildAsync(world, "Inn");
            var inn = builder.Slots["loc-inn"];
            inn.Fade.Snap(1);
            var bench = inn.Places.Markers["r-hall"]["bench1"].Slots;
            NearD("Q0 bench1 slot height (README \"Placement world\": 4.096875)", bench[0].Y, 4.096875, 1e-6);
            var mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-pairs] " + line), strict: true)
            {
                ClipFit = ClipFitMode.OnDemandSync,
                AutoTick = false, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
                SeatYAt = builder.PairSeatY, RoomStandAt = builder.PairRoomStandY,
            };
            world.AddChild(mgr);
            await mgr.InitAsync();
            await Apply(mgr, dir, "worldmap.json");
            var f = mgr.Figures;
            Figure ann = f["Ann Hand"], ben = f["Ben Hand"], cy = f["Cy Seat"], dee = f["Dee Seat"], gil = f["Gil Loft"],
                   hal = f["Hal Loft"], eve = f["Eve Solo"], fay = f["Fay Solo"], box = f["Box Low"];
            var rigged = new[] { ann, ben, cy, dee, gil, hal, eve, fay };
            Expect("Q0 every pair figure is a rigged model with a player", rigged.All(x => x.IsGlb && x.Player is not null),
                   string.Join(", ", rigged.Where(x => x.Player is null).Select(x => x.CharacterName)));

            // ---- Q0 normalisation ----
            Expect("Q0 the box is a model without a rig", box.IsGlb && box.Player is null, $"glb {box.IsGlb}");
            NearD("Q0 box scale = 1.70 / 0.85", box.BaseScale, 2, 1e-6);
            NearV("Q0 box bind offset", box.BindOffset, -0.6, 0.6, 0.2, 1e-6);
            var boxAabb = ModelPlacement.Measure(box.Body!, Transform3D.Identity);
            NearD("Q0 box: lowest point on the root (was −0.6 m)", boxAabb.Position.Y, 0, 1e-5);
            NearD("Q0 box: centred in x", boxAabb.GetCenter().X, 0, 1e-5);
            NearD("Q0 box: centred in z", boxAabb.GetCenter().Z, 0, 1e-5);
            NearD("Q0 box: height 1.70", boxAabb.Size.Y, 1.7, 1e-5);
            var bodyOffsets = new List<string>();
            foreach (var x in new[] { ann, ben })
            {
                // The skinned rest pose (three's Box3.setFromObject, BridgeFit.BindBox) in the root frame: on the root, centred.
                var bb = BridgeFit.BindBox(x.Body!);
                NearD($"Q0 {x.CharacterName}: skinned bind bottom on the root", bb.Position.Y, 0, 1e-4);
                NearD($"Q0 {x.CharacterName}: skinned bind centre x", bb.GetCenter().X, 0, 1e-4);
                NearD($"Q0 {x.CharacterName}: skinned bind centre z", bb.GetCenter().Z, 0, 1e-4);
                bodyOffsets.Add($"{x.CharacterName} y {x.BindOffset.Y:0.###}");
            }
            NearD("Q0 Test3_mia's body is lifted 0.85 m (its origin in the middle of a 2 m mesh, scale 0.85)", ann.BindOffset.Y, 0.85, 2e-3);

            // ---- Q1 the root paths (Godot's FBX import is in metres; the sidecars' anchor_xz_m) ----
            RootNear(mgr, "greeting-handshake__a", 1.5, -0.367, 0);
            RootNear(mgr, "greeting-handshake__b", 1.5, 0.367, 0);
            RootNear(mgr, "greeting-hug__a", 1.8, -0.212, 0);
            RootNear(mgr, "greeting-hug__b", 1.8, 0.212, 0);
            RootNear(mgr, "comforting__b", 1.2, 0.3, 0);
            Expect("Q1 comforting__a is not in the library", mgr.Clips.PairRootAt("comforting__a", 0) is null, "loaded");
            var ra = mgr.Clips.PairRootAt("greeting-handshake__a", 0)!.Value;
            var rb = mgr.Clips.PairRootAt("greeting-handshake__b", 0)!.Value;
            var ha = mgr.Clips.PairRootAt("greeting-hug__a", 0)!.Value;
            var hb = mgr.Clips.PairRootAt("greeting-hug__b", 0)!.Value;
            var cb = mgr.Clips.PairRootAt("comforting__b", 0)!.Value;

            // ---- poll 1, one second ----
            for (int i = 0; i < 30; i++) mgr.Tick(Dt);
            // Q2 Ann on the ground, anchor (20, 40), yaw −π/2 (c = 0, s = −1): x = 20 − rz = 20, z = 40 + rx.
            NearV("Q2 Ann at anchor + R(−π/2)·root, on the terrain", ann.Position, 20, G(20, 40 + ra.X), 40 + ra.X, PosTol);
            NearD("Q2 Ann turned to the anchor's yaw", Wrap(ann.Yaw + Math.PI / 2), 0, 1e-4);
            // Ben has no interaction yet: his own point, the standing clip.
            NearV("Q2 Ben stands on his own point", ben.Position, 20, G(20, 41), 41, PosTol);
            Expect("Q2 Ben plays the standing clip", ben.CurrentKind == "idle" && ben.Pair is null, ben.CurrentKind);
            // Q2 Cy and Dee on the bench (place bench1, yaw 0): x = 64 + rx, z = 131, y = slot 0.
            NearV("Q2 Cy on the bench, at slot height", cy.Position, 64 + ha.X, 4.096875, 131, PosTol);
            NearV("Q2 Dee on the bench, at slot height", dee.Position, 64 + hb.X, 4.096875, 131, PosTol);
            // Q3: adopted at 0.5 s, one second later: clip clock 1.5, the player one frame ahead (seek, then advance).
            NearD("Q3 Cy's clip clock 0.5 + 1", cy.Pair!.ClipT, 1.5, 1e-9);
            NearD("Q3 Cy's player at 1.5 + 1/30", cy.ClipTime, 1.5 + Dt, ClipTol);
            NearD("Q3 Cy and Dee in lockstep", cy.ClipTime - dee.ClipTime, 0, ClipTol);
            Expect("Q3 Cy plays greeting-hug__a, Dee __b", cy.CurrentClip == "greeting-hug__a" && dee.CurrentClip == "greeting-hug__b",
                   $"{cy.CurrentClip} {dee.CurrentClip}");
            NearD("Q3 Ann's clip clock 1 + 1", ann.Pair!.ClipT, 2.0, 1e-9);
            NearD("Q3 Ann's player at 2 + 1/30", ann.ClipTime, 2.0 + Dt, ClipTol);
            // Q5 Eve's half (comforting__a) is not loaded: her own point and clip; Fay plays at the anchor.
            Expect("Q5 Eve keeps her interaction but plays solo", eve.Pair is not null && eve.CurrentKind == "idle", eve.CurrentKind);
            NearV("Q5 Eve stands on her own point", eve.Position, 30, G(30, 40), 40, PosTol);
            NearV("Q5 Fay at the anchor (30.5, 40) + root", fay.Position, 30.5 + cb.X, G(30.5 + cb.X, 40), 40, PosTol);
            Expect("Q5 Fay plays comforting__b", fay.CurrentClip == "comforting__b", fay.CurrentClip);
            NearV("Q0 the box figure's root on the ground", box.Position, 40, G(40, 40), 40, PosTol);
            Expect("Q6 Gil sits", gil.CurrentKind == "sitting-at-the-table", gil.CurrentKind);
            double annBefore = ann.ClipTime;

            // ---- poll 2: the server 0.5 s ahead of Ann; Ben joins; Gil stands up; Cy/Dee 0.1 s off ----
            await Apply(mgr, dir, "worldmap_poll2.json");
            mgr.Tick(Dt);
            NearD("Q3 resync: Ann snapped to 2.5 (+1 frame)", ann.Pair.ClipT, 2.5 + Dt, 1e-9);
            NearD("Q3 resync: Ben adopted 2.5 (+1 frame)", ben.Pair!.ClipT, 2.5 + Dt, 1e-9);
            NearD("Q3 resync: Ann's player re-seeked (drift 0.5 > 0.2)", ann.ClipTime, 2.5 + 2 * Dt, ClipTol);
            NearD("Q3 resync: Ann and Ben in phase", ann.ClipTime - ben.ClipTime, 0, ClipTol);
            Expect("Q3 the resync moved Ann's clip", ann.ClipTime - annBefore > 0.4, $"{annBefore:0.###} → {ann.ClipTime:0.###}");
            NearV("Q2 Ben at anchor + R(−π/2)·root (opposite Ann)", ben.Position, 20, G(20, 40 + rb.X), 40 + rb.X, PosTol);
            NearD("Q3 keep: Cy's clock not pulled to 1.6 (|1.5 − 1.6| ≤ 0.3)", cy.Pair.ClipT, 1.5 + Dt, 1e-9);
            NearD("Q3 keep: Cy and Dee still in lockstep", cy.ClipTime - dee.ClipTime, 0, ClipTol);
            Expect("Q6 Gil gets up through get-up-chair", gil.Bridging && gil.CurrentKind == "get-up-chair", gil.CurrentKind);
            for (int i = 0; i < 15; i++) mgr.Tick(Dt);
            Expect("Q6 Gil still in the bridge", gil.Bridging, "released");

            // ---- poll 3: Gil and Hal shake hands in the loft; the bench pair freezes; Ann/Ben 0.17 s off ----
            double cyFrozen = cy.ClipTime, deeFrozen = dee.ClipTime;
            var cyAt = cy.Position;
            await Apply(mgr, dir, "worldmap_poll3.json");
            mgr.Tick(Dt);
            Expect("Q6 the handshake ended Gil's bridge", !gil.Bridging && !gil.HoldsHeight && gil.CurrentClip == "greeting-handshake__a",
                   $"bridging {gil.Bridging} kind {gil.CurrentKind}");
            // The loft: declared 3.02 over the datum 4 → floor 7.02, stand + 0.01 = 7.03 (the room rung).
            NearV("Q2 Gil in the loft at its stand height", gil.Position, 64 + ra.X, 7.03, 128, PosTol);
            NearV("Q2 Hal in the loft at its stand height", hal.Position, 64 + rb.X, 7.03, 128, PosTol);
            NearD("Q3 keep: Ann not pulled to 3.2 (|3.0333 − 3.2| ≤ 0.3)", ann.Pair.ClipT, 2.5 + 17 * Dt, 1e-9);
            NearD("Q3 Ann and Ben still in phase", ann.ClipTime - ben.ClipTime, 0, ClipTol);
            for (int i = 0; i < 10; i++) mgr.Tick(Dt);
            NearD("Q4 frozen: Cy's player stands", cy.ClipTime, cyFrozen, 1e-9);
            NearD("Q4 frozen: Dee's player stands", dee.ClipTime, deeFrozen, 1e-9);
            NearD("Q4 frozen: Cy's clip clock stands", cy.Pair.ClipT, 1.5 + 16 * Dt, 1e-9);
            // The bridge's travel and the rest of its turn were taken over (dropped: the anchor places Gil) — none held.
            Expect("Q6 no bridge travel left on Gil", !gil.HoldsTravel && gil.BodyOffset.X == 0 && gil.BodyOffset.Z == 0,
                   $"holds {gil.HoldsTravel} offset {gil.BodyOffset}");
            NearV("Q6 Gil still at the anchor", gil.Position, 64 + ra.X, 7.03, 128, PosTol);
            NearV("Q4 frozen: Cy keeps her place", cy.Position, cyAt.X, cyAt.Y, cyAt.Z, 1e-6);

            // ---- Q7 the one-shot's end: Ann/Ben pass 3.533 s ----
            for (int i = 0; i < 20; i++) mgr.Tick(Dt);
            double len = ann.Player!.GetAnimation("greeting-handshake__a").Length;
            Expect("Q7 the handshake's clock ran past its end", ann.Pair.ClipT > len, $"{ann.Pair.ClipT:0.###} ≤ {len:0.###}");
            NearD("Q7 Ann holds the last frame", ann.ClipTime, len, 2e-3);
            NearD("Q7 Ben holds the last frame", ben.ClipTime, len, 2e-3);
            NearD("Q7 Ann and Ben end together", ann.ClipTime - ben.ClipTime, 0, ClipTol);

            double resyncMs = Math.Abs(ann.ClipTime - ben.ClipTime) * 1000;

            // ---- Q8 the loop flag is per figure (Task 35): Ann and Hal share Test3_mia's greeting-hug__a (listed: cycle) ----
            const string hug = "greeting-hug__a";
            ann.EnsureClip(hug);   // fitted lazily (Task 35b): the play below would; the check reads it first
            hal.EnsureClip(hug);
            var sharedHug = ann.Player.GetAnimation(hug);
            Expect("Q8 Ann and Hal play the same shared Animation", sharedHug.GetInstanceId() == hal.Player!.GetAnimation(hug).GetInstanceId(),
                   "two objects");
            Expect("Q8 the listing calls the hug a cycle", sharedHug.LoopMode == Animation.LoopModeEnum.Linear, $"{sharedHug.LoopMode}");
            double hugLen = sharedHug.Length;
            // Directly, without the manager's tick (which would put their handshakes back): Hal one-shot, Ann cycling —
            // the order the old code lost: the LAST writer's flag on the shared Animation won for both.
            hal.PlayPair(hug, 0.2, false, loop: false);
            ann.PlayPair(hug, 0.2, false, loop: true);
            int steps = (int)Math.Ceiling((hugLen + 0.5) / Dt);
            for (int i = 0; i < steps; i++)
            {
                hal.UpdateFigure(Dt);
                ann.UpdateFigure(Dt);
            }
            double ran = 0.2 + steps * Dt;
            NearD("Q8 Hal holds the hug's last frame (one-shot)", hal.ClipTime, hugLen, 2e-3);
            NearD("Q8 Ann's hug wrapped around (cycle)", ann.ClipTime, ran % hugLen, 2e-3);
            Expect("Q8 the shared Animation keeps the listing's flag", sharedHug.LoopMode == Animation.LoopModeEnum.Linear, $"{sharedHug.LoopMode}");
            var twin = hal.LoopTwin(hug);
            Expect("Q8 Hal plays his own one-shot twin, Ann the shared cycle", twin is { LoopMode: Animation.LoopModeEnum.None }
                   && hal.Player.AssignedAnimation == $"{Figure.LoopTwinLibrary}/{hug}" && ann.Player.AssignedAnimation == hug
                   && ann.LoopTwin(hug) is null, $"hal {hal.Player.AssignedAnimation} ann {ann.Player.AssignedAnimation}");
            Expect("Q8 the twin carries the shared keys bit for bit", SameKeys(sharedHug, twin!, out string why), why);

            // ---- Q9 clip memory (Task 35, ruling P3-R11) ----
            var kw = mgr.CompareKeyWritersForCheck("Ann Hand");
            Expect("Q9 one-call keys = inserted keys, bit for bit", kw.Mismatches == 0 && kw.Keys > 0,
                   $"{kw.Mismatches} mismatches, first {kw.FirstMismatch}");
            Expect("Q9 the one-call tracks hold less memory", kw.BulkBytes < kw.InsertBytes || kw.InsertBytes == 0,
                   $"bulk {kw.BulkBytes} B, insert {kw.InsertBytes} B");
            var refit = await mgr.RefitAtHeightForCheck("Ann Hand", 1.5);
            Expect("Q9 the same model at 1.50 m shares every clip but the re-locked bridges", refit.OtherOwn == 0
                   && refit.SameObject > 0 && refit.SameObject + refit.RootMotionOwn == refit.Actions,
                   $"{refit.Actions} actions: {refit.SameObject} shared objects, {refit.RootMotionOwn} root-motion own, {refit.OtherOwn} other own");
            string memory = $"keys {kw.Keys} in {kw.Tracks} tracks bit-identical, freed {kw.BulkBytes / 1024.0:0} KiB one-call vs "
                            + $"{kw.InsertBytes / 1024.0:0} KiB inserted; refit at 1.50 m: {refit.SameObject}/{refit.Actions} actions shared, "
                            + $"{refit.RootMotionOwn} root-motion own";
            GD.Print($"[check-pairs] Q9 {memory}");

            var report = $"pairs Q0..Q9 ok (box bottom {boxAabb.Position.Y:0.000} m, {string.Join(", ", bodyOffsets)}; handshake ±{-ra.X:0.000} m, "
                         + $"hug ±{-ha.X:0.000} m; seat 4.097, loft 7.03; resync Δ {resyncMs:0.0} ms; "
                         + $"frozen 10 frames; solo Eve; loop twin Hal once / Ann cycle; {memory})";
            GD.Print($"[check-pairs] {report}");
            return report;
        }
        finally
        {
            world.QueueFree();
        }
    }

    /// <summary>Two animations with the same tracks and keys, bit for bit (times, transitions, values).</summary>
    private static bool SameKeys(Animation a, Animation b, out string why)
    {
        why = "";
        if (a.GetTrackCount() != b.GetTrackCount() || a.Length != b.Length) { why = "header"; return false; }
        for (int t = 0; t < a.GetTrackCount(); t++)
        {
            int n = a.TrackGetKeyCount(t);
            if (a.TrackGetPath(t) != b.TrackGetPath(t) || a.TrackGetType(t) != b.TrackGetType(t) || n != b.TrackGetKeyCount(t)
                || a.TrackGetInterpolationType(t) != b.TrackGetInterpolationType(t)) { why = $"track {t}"; return false; }
            for (int k = 0; k < n; k++)
                if (BitConverter.DoubleToInt64Bits(a.TrackGetKeyTime(t, k)) != BitConverter.DoubleToInt64Bits(b.TrackGetKeyTime(t, k))
                    || a.TrackGetKeyTransition(t, k) != b.TrackGetKeyTransition(t, k)
                    || !a.TrackGetKeyValue(t, k).Equals(b.TrackGetKeyValue(t, k))) { why = $"track {a.TrackGetPath(t)} key {k}"; return false; }
        }
        return true;
    }

    private static async Task Apply(FigureManager mgr, string dir, string file)
    {
        using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, file)));
        await mgr.Apply(map.RootElement);
    }

    private static void RootNear(FigureManager mgr, string clip, double t, double x, double z)
    {
        var r = mgr.Clips.PairRootAt(clip, t) ?? throw new InvalidOperationException($"pairs: Q1 {clip} has no root path");
        NearD($"Q1 {clip} root x at {t} s (sidecar)", r.X, x, SidecarTol);
        NearD($"Q1 {clip} root z at {t} s (sidecar)", r.Z, z, SidecarTol);
    }

    private static double Wrap(double a) => Math.Atan2(Math.Sin(a), Math.Cos(a));

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"pairs: {what} FAILED ({detail})");
    }

    private static void NearD(string what, double got, double want, double tol)
    {
        Expect(what, double.IsFinite(got) && Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");
        GD.Print($"[check-pairs] {what}: {got:0.######}");
    }

    private static void NearV(string what, Vector3 got, double x, double y, double z, double tol)
        => Expect(what, Math.Abs(got.X - x) <= tol && Math.Abs(got.Y - y) <= tol && Math.Abs(got.Z - z) <= tol,
                  $"got ({got.X:0.######}, {got.Y:0.######}, {got.Z:0.######}), want ({x:0.######}, {y:0.######}, {z:0.######}) ± {tol}");

    private static void NearV(string what, V3 got, double x, double y, double z, double tol)
        => NearV(what, new Vector3((float)got.X, (float)got.Y, (float)got.Z), x, y, z, tol);
}
