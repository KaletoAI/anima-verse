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
/// <c>--check bridges</c> (part of every <c>--check</c>, Task 31): the browser's bridge clips with root motion on the
/// hand-written world <c>fixtures/bridges/</c> (README "Bridges world") — the walk world's flat ground with three
/// figures on open grass, real rigs (Test3_mia, Soldier), the real clip library (idle, walk, sitting-at-the-table,
/// laying, get-up-chair, get-up-bed, commanding as a ramping "start-walk") and the reference rig. Measured at the
/// CONSUMER: the WORLD positions of the rendered foot bones, frame by frame at 30 fps.
///
///   B1 the fit per rig: get-up-chair / get-up-bed carry a travel, a lift and a turn; the chair's |ψ_end| ≤ 8°, the
///      bed's ψ_end in [−115°, −98°] (smoke_bridge_root.mjs [B13]);
///   B2 poll 2 asks Mia (sitting) to stand at the server's stand point: the first frame opens get-up-chair, holds the
///      facing, the root stays on the seat (pace 0 — no step out of the chair, [Y3]);
///   B3 planted-foot drift on every bridge frame from 0.30 s on, the check's OWN contact detection (not the core's):
///      ≤ 1.5 cm for the chair and the bed ([6]);
///   B4 the hand-over (a 0 s frame): the rendered feet move ≤ 1 cm ([7]); the root yaw is base + ψ_end;
///   B5 the spot is kept (standSettle): within 0.25 m of the server's stand point, and the NPC does not walk;
///   B6 the chair's end: per side the lowest foot bone over the rig's rest floor, median from 3.5 s on, within ±1 cm
///      ([B17]); the lift at the end is endLift × baseScale;
///   B7 Rae (standing) walks off through the RAMPING bridge (accel 0.5): step k = 3.4/30 · pace_k with pace_1 = 0.02
///      (paceLimitFor before the clip is asked), pace_k = max(0.02, 0.5·(k−1)/30) — README "Bridges world";
///   B8 the deadline: the bridge gate opens at start + length + 0.5 s even without the clip's end.
/// </summary>
public static class BridgeCheck
{
    private const double Fps = 30;
    private const double Dt = 1 / Fps;
    private const double FadeSkipS = 0.30;
    private const double DriftMaxCm = 1.5;
    private const double HandoverMaxCm = 1.0;
    private const double ChairTurnMaxDeg = 8;
    private static readonly double[] BedTurnDeg = { -115, -98 };
    private const double EndFeetMaxCm = 1.0;
    private const double EndFromS = 3.5;
    /// <summary>The bed surface Bea's root lies on before poll 2, m (README "Bridges world").</summary>
    private const double BedM = 0.40;
    private static readonly string[] Points = { "leftfoot", "lefttoebase", "rightfoot", "righttoebase" };
    private static readonly string[] LeftFoot = { "leftfoot", "lefttoebase", "lefttoe_end" };
    private static readonly string[] RightFoot = { "rightfoot", "righttoebase", "righttoe_end" };

    /// <summary>One rendered frame of a figure: clip time, bridging, root, the bridge lift, the foot bones' world positions (m).</summary>
    private sealed record Sample(double T, bool Bridging, Vector3 Root, double Lift, Dictionary<string, Vector3> Feet);

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        await PropActionsCheck.CheckBedEntry(host,fixtures);
        var dir = Path.Combine(fixtures, "bridges");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "BridgeWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-bridges] " + line), strict: true);
        FigureManager? mgr = null;
        try
        {
            await builder.BuildAsync(world, "Hall");
            mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-bridges] " + line), strict: true)
            {
                ClipFit = ClipFitMode.OnDemandSync,
                AutoTick = false, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
            };
            world.AddChild(mgr);
            await mgr.InitAsync();
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap.json"))))
                await mgr.Apply(map.RootElement);
            var mia = mgr.Figures["Mia Chair"];
            var bea = mgr.Figures["Bea Bed"];
            var rae = mgr.Figures["Rae Ramp"];
            Expect("B0 every figure a model with the library", new[] { mia, bea, rae }.All(f => f.IsGlb && f.Player is not null),
                   string.Join(", ", new[] { mia, bea, rae }.Select(f => $"{f.CharacterName} glb {f.IsGlb}")));

            // ---- B1 the fit ----
            var chair = Extras(mia, "get-up-chair");
            var bed = Extras(bea, "get-up-bed");
            Expect("B1 chair: travel, lift and turn measured on Test3_mia", chair is { Path: not null, Lift: not null, Turn: not null },
                   $"{chair?.Path is not null} {chair?.Lift is not null} {chair?.Turn is not null}");
            Expect("B1 bed: travel, lift and turn measured on Soldier", bed is { Path: not null, Lift: not null, Turn: not null },
                   $"{bed?.Path is not null} {bed?.Lift is not null} {bed?.Turn is not null}");
            double chairPsi = Deg(chair!.Turn!.Yaw[^1]);
            double bedPsi = Deg(bed!.Turn!.Yaw[^1]);
            Expect($"B1 chair |ψ_end| ≤ {ChairTurnMaxDeg}°", Math.Abs(chairPsi) <= ChairTurnMaxDeg, $"{chairPsi:0.00}°");
            Expect($"B1 bed ψ_end in [{BedTurnDeg[0]}, {BedTurnDeg[1]}]°", bedPsi >= BedTurnDeg[0] && bedPsi <= BedTurnDeg[1], $"{bedPsi:0.00}°");
            Expect("B1 the ramp bridge carries no travel (no root motion in its listing)", Extras(rae, "start-walk")?.Path is null, "path");

            // Poll 1: everybody on the spot, facing south after one 0.1 s frame (π, the default target), then the seat
            // and bed clips for one second.
            mgr.Tick(0.1);
            for (int i = 0; i < 30; i++) mgr.Tick(Dt);
            Expect("B0 Mia sits, Bea lies, Rae stands", mia.CurrentKind == "sitting-at-the-table" && bea.CurrentKind == "laying"
                                                        && rae.CurrentKind == "idle", $"{mia.CurrentKind} {bea.CurrentKind} {rae.CurrentKind}");
            Near("B0 Mia faces south", Math.Abs(mia.Rotation.Y), Math.PI, 1e-5);
            // Bea lies IN A BED: the room placement puts a lying root on the bed surface (free placement cannot say so),
            // so her root is put on a 0.40 m bed in the frame before poll 2 — the bridge then starts the lift there.
            bea.Position = new Vector3(bea.Position.X, (float)BedM, bea.Position.Z);
            var seat = mia.Position;
            var bedSpot = bea.Position;
            var raeStart = rae.Position;
            double baseYaw = mia.Yaw, bedBaseYaw = bea.Yaw;

            // ---- poll 2 ----
            JsonElement row2(JsonDocument d, string name) => d.RootElement.GetProperty("characters").EnumerateArray().First(c => c.GetProperty("name").GetString() == name);
            Vector3 miaServer, beaServer;
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap_poll2.json"))))
            {
                var pm = row2(map, "Mia Chair").GetProperty("pos");
                var pb = row2(map, "Bea Bed").GetProperty("pos");
                miaServer = new Vector3((float)pm.GetProperty("x").GetDouble(), 0, (float)pm.GetProperty("z").GetDouble());
                beaServer = new Vector3((float)pb.GetProperty("x").GetDouble(), 0, (float)pb.GetProperty("z").GetDouble());
                await mgr.Apply(map.RootElement);
            }
            mgr.Tick(Dt);                                                                                   // F1
            Expect("B2 Mia opens get-up-chair", mia.Bridging && mia.CurrentKind == "get-up-chair", mia.CurrentKind);
            Expect("B2 Bea opens get-up-bed", bea.Bridging && bea.CurrentKind == "get-up-bed", bea.CurrentKind);
            Expect("B2 a holding bridge holds the facing and the height", mia.HoldsFacing && mia.HoldsHeight && mia.PaceLimit == 0,
                   $"facing {mia.HoldsFacing} height {mia.HoldsHeight} pace {mia.PaceLimit}");
            Expect("B2 no step out of the chair on the opening frame", Flat(mia.Position - seat) == 0, $"{mia.Position - seat}");
            // B2: the owner put the root onto the floor (0) and handed the bed's height to the lift (start lift 0.40; the
            // ramp starts LIFT_RAMP_S before the first contact, after F1).
            NearD("B2 Bea's root on the floor", bea.Position.Y, 0, 1e-6);
            NearD("B2 Bea's lift = the bed (0.40 m)", bea.Lift, BedM, 1e-6);
            Expect("B2 the ramp has not begun at F1", BridgeLift.LiftRamp(bed.Lift!.FirstContactS).From > Dt, $"{bed.Lift.FirstContactS}");
            // B7 F1: paceLimitFor asked BEFORE the clip — the bridge that WOULD open: bridgePace(0.5, 0) = 0.02.
            NearD("B7 F1 Rae steps 3.4/30 · 0.02", rae.Position.Z - raeStart.Z, 3.4 / 30 * 0.02, 1e-5);
            Expect("B7 F1 Rae opens the ramping start-walk, keeps her facing", rae.Bridging && rae.CurrentKind == "start-walk" && !rae.HoldsFacing,
                   $"{rae.CurrentKind} facing {rae.HoldsFacing}");
            double raeStartClock = mgr.Clock;
            double raeZ = rae.Position.Z;

            // ---- the bridges, frame by frame from F1 (frame k = clip time k/30) ----
            var miaRun = new List<Sample> { SampleOf(mia, Dt) };
            var beaRun = new List<Sample> { SampleOf(bea, Dt) };
            bool miaHeld = true;
            int frame = 1;
            while ((mia.Bridging || bea.Bridging || mia.HoldsTravel || bea.HoldsTravel || frame < 10) && frame < 400)
            {
                frame++;
                mgr.Tick(Dt);
                double t = frame * Dt;
                if (frame <= 10)
                {
                    // B7: the ramp, hand-derived (README "Bridges world").
                    double pace = Math.Max(0.02, Math.Min(1, 0.5 * (frame - 1) / Fps));
                    NearD($"B7 F{frame} Rae steps 3.4/30 · {pace:0.####}", rae.Position.Z - raeZ, 3.4 / 30 * pace, 1e-5);
                    raeZ = rae.Position.Z;
                    if (frame == 10) Expect("B7 Rae still in the ramp after 10 frames", rae.Bridging, "released");
                }
                if (mia.Bridging || mia.HoldsTravel)
                {
                    miaRun.Add(SampleOf(mia, t));
                    miaHeld &= Flat(mia.Position - seat) == 0;
                }
                if (bea.Bridging || bea.HoldsTravel) beaRun.Add(SampleOf(bea, t));
                // The frame a bridge ended: its last pose is on screen, the travel not yet taken (the owner takes it at
                // the start of the next frame). The hand-over with no time advanced: a 0 s frame (B4).
                if (!mia.Bridging && mia.HoldsTravel)
                {
                    var before = SampleOf(mia, t);
                    mgr.Tick(0);
                    var after = SampleOf(mia, t);
                    NearD($"B4 Mia's hand-over moves the feet ≤ {HandoverMaxCm} cm", MaxFootMoveCm(before, after), 0, HandoverMaxCm);
                    NearD("B4 Mia's root keeps base + ψ_end", WrapDelta(mia.Yaw, baseYaw + chair.Turn.Yaw[^1]), 0, 1e-6);
                    Expect("B4 Mia's travel taken, the body back on its base", !mia.HoldsTravel && mia.BodyOffset.X == 0 && mia.BodyOffset.Z == 0,
                           $"{mia.BodyOffset}");
                    NearD("B6 Mia's lift at the end = endLift × baseScale", mia.Lift, chair.Lift!.EndLift * mia.BaseScale, 1e-6);
                }
                if (!bea.Bridging && bea.HoldsTravel)
                {
                    var before = SampleOf(bea, t);
                    mgr.Tick(0);
                    var after = SampleOf(bea, t);
                    NearD($"B4 Bea's hand-over moves the feet ≤ {HandoverMaxCm} cm", MaxFootMoveCm(before, after), 0, HandoverMaxCm);
                    NearD("B4 Bea's root keeps base + ψ_end", WrapDelta(bea.Yaw, bedBaseYaw + bed.Turn.Yaw[^1]), 0, 1e-6);
                    NearD("B6 Bea's lift at the end = endLift × baseScale", bea.Lift, bed.Lift!.EndLift * bea.BaseScale, 1e-6);
                }
            }
            Expect("B3 Mia's root stays on the seat for the whole bridge", miaHeld, "moved");
            // The deadline did not cut them: they ran to their clips' ends.
            NearD("B3 get-up-chair ran its whole clip", miaRun.Last(r => r.Bridging).T, AnimLength(mia, "get-up-chair"), 1.5 * Dt);
            double chairDrift = PlantedDriftCm(mia, miaRun);
            double bedDrift = PlantedDriftCm(bea, beaRun);
            NearD($"B3 chair planted-foot drift ≤ {DriftMaxCm} cm", chairDrift, 0, DriftMaxCm);
            NearD($"B3 bed planted-foot drift ≤ {DriftMaxCm} cm", bedDrift, 0, DriftMaxCm);

            // ---- B5 the kept spot ----
            double off = Flat(mia.Position - miaServer);
            Expect("B5 Mia stands within 0.25 m of the server's stand point and keeps it",
                   off <= 0.25 && mia.Settle is not null, $"{off * 100:0.0} cm settle {mia.Settle is not null}");
            var kept = mia.Position;
            for (int i = 0; i < 15; i++) mgr.Tick(Dt);
            Expect("B5 Mia does not walk after standing up", !mia.Moving && Flat(mia.Position - kept) < 1e-6, $"{mia.Position - kept}");

            // ---- B6 the chair's end, both feet on the floor ----
            // The lift's end: endLift = rest floor − the last frame's lowest foot point, so WITH the lift that point
            // stands exactly on the rest floor (float noise only).
            NearD("B6 chair: the last frame's lowest foot point on the rest floor (cm)", LowestCm(mia, miaRun.Last(r => r.Bridging)), 0, 0.1);
            NearD("B6 bed: the last frame's lowest foot point on the rest floor (cm)", LowestCm(bea, beaRun.Last(r => r.Bridging)), 0, 0.1);
            var (left, right) = EndFeetCm(mia, miaRun);
            NearD($"B6 chair end: left foot over the rest floor (median from {EndFromS} s)", left, 0, EndFeetMaxCm);
            NearD($"B6 chair end: right foot over the rest floor (median from {EndFromS} s)", right, 0, EndFeetMaxCm);

            // ---- B8 the deadline (Rae's ramp; start = the clock of F1) ----
            double len = AnimLength(rae, "start-walk");
            if (rae.Bridging)
            {
                double deadline = raeStartClock + len + 0.5;
                rae.Clock = () => deadline - 1e-6;
                Expect("B8 before the deadline the bridge still holds", rae.Bridging, "released");
                rae.Clock = () => deadline + 1e-6;
                Expect("B8 past start + length + 0.5 s the gate opens", !rae.Bridging && rae.PaceLimit == 1, $"pace {rae.PaceLimit}");
                rae.Clock = () => mgr.Clock;
            }
            var report = $"bridges B1..B8 ok (chair ψ {chairPsi:0.0}° drift {chairDrift:0.00} cm, bed ψ {bedPsi:0.0}° drift {bedDrift:0.00} cm, "
                         + $"end feet {left:0.00}/{right:0.00} cm, spot {off * 100:0.0} cm, ramp 10 frames)";
            GD.Print($"[check-bridges] {report}");
            return report;
        }
        finally
        {
            world.QueueFree();
        }
    }

    // ---- measurement (the check's own code: rendered bones, own contact detection) ----------------------------------

    /// <summary>The fit's extras of a clip (fitted now if the lazy fit has not done it yet, Task 35b).</summary>
    private static ClipExtras? Extras(Figure f, string kind)
        => f.EnsureClip(kind) && f.Player is { } p && f.Extras.TryGetValue(p.GetAnimation(kind), out var x) ? x : null;

    private static double AnimLength(Figure f, string kind) => f.EnsureClip(kind) ? f.Player!.GetAnimation(kind).Length : double.NaN;

    private static double Deg(double rad) => rad * 180 / Math.PI;

    private static double Flat(Vector3 v) => Math.Sqrt((double)v.X * v.X + (double)v.Z * v.Z);

    private static double WrapDelta(double a, double b) => Math.Abs(Math.Atan2(Math.Sin(a - b), Math.Cos(a - b)));

    private static Dictionary<string, int> FootBones(Skeleton3D skel)
    {
        var map = new Dictionary<string, int>();
        for (int i = 0; i < skel.GetBoneCount(); i++)
        {
            var key = BoneNames.Norm(skel.GetBoneName(i));
            if (Points.Contains(key) || key is "lefttoe_end" or "righttoe_end") map.TryAdd(key, i);
        }
        return map;
    }

    private static Sample SampleOf(Figure f, double t)
    {
        var skel = f.Skeleton!;
        var feet = new Dictionary<string, Vector3>();
        foreach (var (key, i) in FootBones(skel)) feet[key] = (skel.GlobalTransform * skel.GetBoneGlobalPose(i)).Origin;
        return new Sample(t, f.Bridging, f.Position, f.Lift, feet);
    }

    private static double MaxFootMoveCm(Sample a, Sample b)
        => Points.Where(a.Feet.ContainsKey).Max(k => Flat(a.Feet[k] - b.Feet[k]) * 100);

    /// <summary>
    /// The rig's rest floor in the figure's root frame: the lowest foot bone of the bind pose × the body scale, on the
    /// body's bind anchoring height (<c>groundY</c>: the mesh's lowest point on the root, Task 32).
    /// </summary>
    private static double RestFloorM(Figure f)
    {
        var skel = f.Skeleton!;
        var inst = (Node3D)f.Body!.GetChild(0);
        var rig = BridgeFit.RigOf(inst, skel);
        var pose = new RigPose(rig);
        var byKey = rig.BonesByKey();
        double floor = double.PositiveInfinity;
        foreach (var k in Points.Concat(new[] { "lefttoe_end", "righttoe_end" }))
            if (byKey.TryGetValue(k, out int b)) floor = Math.Min(floor, pose.WorldPosition(b).Y);
        return floor * f.BaseScale + f.BindOffset.Y;
    }

    /// <summary>
    /// smoke_bridge_root.mjs [6] at the consumer: the frames from 0.30 s on; per point its heights over the rest floor
    /// (cm), its ground = the 5th percentile capped at its rest height; weight = band(height − ground, 2, 5) ×
    /// band(|vy|, 15, 30) (central difference); a frame ≥ 0.999 is FULL; drift = the largest horizontal distance a point
    /// moves from where its run of FULL frames began.
    /// </summary>
    private static double PlantedDriftCm(Figure f, List<Sample> run)
    {
        double floorM = RestFloorM(f);
        var frames = run.Where(s => s.T >= FadeSkipS && s.Bridging).ToList();
        double worst = 0;
        // Rest heights over the lowest foot bone (cm), from the bind pose.
        var inst = (Node3D)f.Body!.GetChild(0);
        var rig = BridgeFit.RigOf(inst, f.Skeleton!);
        var pose = new RigPose(rig);
        var byKey = rig.BonesByKey();
        foreach (var k in Points)
        {
            if (!byKey.TryGetValue(k, out int b) || frames.Count < 3) continue;
            double rest = (pose.WorldPosition(b).Y * f.BaseScale + f.BindOffset.Y - floorM) * 100;
            var h = frames.Select(s => (s.Feet[k].Y - s.Root.Y - floorM) * 100).ToArray();
            var sorted = h.OrderBy(x => x).ToArray();
            double ground = Math.Min(sorted[Math.Min(sorted.Length - 1, (int)Math.Floor(0.05 * (sorted.Length - 1)))], rest);
            static double Band(double v, double lo, double hi) => v <= lo ? 1 : v >= hi ? 0 : (hi - v) / (hi - lo);
            Vector3? start = null;
            for (int i = 0; i < frames.Count; i++)
            {
                int a = Math.Max(i - 1, 0), c = Math.Min(i + 1, frames.Count - 1);
                double vy = (h[c] - h[a]) / ((c - a) / Fps);
                double w = Band(h[i] - ground, 2, 5) * Band(Math.Abs(vy), 15, 30);
                var p = frames[i].Feet[k];
                if (w >= 0.999)
                {
                    start ??= p;
                    worst = Math.Max(worst, Flat(p - start.Value) * 100);
                }
                else start = null;
            }
        }
        return worst;
    }

    /// <summary>The lowest foot bone of one frame over the rest floor, cm, lift included.</summary>
    private static double LowestCm(Figure f, Sample s)
        => s.Feet.Values.Min(p => (p.Y - s.Root.Y - RestFloorM(f)) * 100);

    /// <summary>
    /// [B17]: per side the lowest of Foot / ToeBase / Toe_End over the rest floor (cm), median over t ≥ 3.5 s — the clip
    /// as adapted and pinned, i.e. WITHOUT the bridge lift (the browser smoke measures a figure no owner lifts).
    /// </summary>
    private static (double Left, double Right) EndFeetCm(Figure f, List<Sample> run)
    {
        double floorM = RestFloorM(f);
        var frames = run.Where(s => s.T >= EndFromS && s.Bridging).ToList();
        double Median(string[] side)
        {
            var v = frames.Select(s => side.Where(s.Feet.ContainsKey).Min(k => (s.Feet[k].Y - s.Root.Y - s.Lift - floorM) * 100)).OrderBy(x => x).ToArray();
            return v.Length == 0 ? double.NaN : v.Length % 2 == 1 ? v[v.Length / 2] : (v[v.Length / 2 - 1] + v[v.Length / 2]) / 2;
        }
        return (Median(LeftFoot), Median(RightFoot));
    }

    // ---- expectations ----------------------------------------------------------------------------------------------

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"bridges: {what} FAILED ({detail})");
    }

    private static void Near(string what, double got, double want, double tol)
        => Expect(what, Math.Abs(got - want) <= tol, $"got {got:R}, want {want:R} ± {tol}");

    private static void NearD(string what, double got, double want, double tol)
    {
        Expect(what, double.IsFinite(got) && Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");
        GD.Print($"[check-bridges] {what}: {got:0.####}");
    }
}
