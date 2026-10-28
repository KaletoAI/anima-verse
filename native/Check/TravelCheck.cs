using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Water;
using AnimaNative.Overview;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 42 / E6-T2, A11: fixtures/travel with fixed receipts. Age = (300 + (500-200)/2 + 40)/1000 = .49 s.
/// Timeless leg consumes 10 m without time, the duplicate consumes zero: adopted target = 10 + 1.4*.49 = 10.686.
/// Twenty-four .25 s frames have equal target/shown, hence shown[i] = 10.686 + .35*i. Root catches up .85 m per
/// frame against .35 m of progress; after joining it matches the arc point within .01 m every frame. At poll 2,
/// target=17+1.4*.49=17.686, shown=19.086; next .5 s shown=19.786-1.4*(1-exp(-.5))=19.23514292359769.
/// A synthetic fresh poll at progress 0 gives target 10 (no receipt age), a >6 m back snap; progress 35 gives
/// a >6 m forward snap of the display while retaining root catch-up. Arrival is the poll-2 free point (62,-80).
/// </summary>
public static class TravelCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var source = new FixtureSource(Path.Combine(fixtures, "travel"), fixtures);
        using var hf = await source.GetHeightfieldAsync();
        var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
        var world = new Node3D { Name = "TravelWorld" };
        host.AddChild(world);
        var mgr = new FigureManager(source, height, _ => { }, strict: true) { AutoTick = false, GroundYAt = (_, _) => 0 };
        world.AddChild(mgr);
        try
        {
            using var first = await source.GetWorldMapAsync();
            await mgr.Apply(first.RootElement);
            var t = mgr.Figures["Timeless Traveller"];
            var pending = mgr.Figures["Pending Traveller"];
            var frozen = mgr.Figures["Frozen Traveller"];
            // Use flat ground for the XZ proof; fresh placement itself correctly uses the terrain sampler.
            foreach (var f in mgr.Figures.Values) f.Position = new Vector3(f.Position.X, 0, f.Position.Z);
            var p0 = pending.Position; var f0 = frozen.Position;
            Near("adopted target from receipt age", t.Route!.TargetM, 10.686);
            for (int i = 1; i <= 24; i++)
            {
                mgr.Tick(.25);
                Near($"frame {i} hand shown", t.Route.ShownM, 10.686 + .35 * i);
                if (i >= 22) AtRoute(t);
                Expect("journey never runs", !t.Running);
                if (i % 4 == 0)
                {
                    var target = t.Route.TargetM; var shown = t.Route.ShownM;
                    mgr.TickPlacement();
                    Near("cached stamp keeps target", t.Route.TargetM, target);
                    Near("cached stamp keeps shown", t.Route.ShownM, shown);
                }
                Expect("pending holds", pending.Position == p0 && !pending.Moving);
                Expect("frozen holds", frozen.Position == f0 && !frozen.Moving);
            }
            using var second = await source.GetWorldMapFileAsync("worldmap_poll2.json");
            var arrival = mgr.Figures["Arrival Traveller"];
            await mgr.Apply(second.RootElement);
            Near("second receipt target", t.Route.TargetM, 17.686);
            Expect("arrival drops route and snaps", arrival.Route is null && Math.Abs(arrival.Position.X - 62) < .001 && arrival.Waypoints.Count == 0);
            Expect("arrival counted once", mgr.Stats.Arrive == 1);
            mgr.Tick(.5);
            Near("poll correction smoother by hand", t.Route.ShownM, 19.23514292359769);
            AtRoute(t);
            var changed = JsonNode.Parse(second.RootElement.GetRawText())!;
            changed.AsObject().Remove("_nativeReceipt");
            var row = changed["characters"]![3]!;
            row["travel"]!["progress_m"] = 0;
            using (var back = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(back.RootElement);
            Expect("back snap counted", mgr.Stats.TravBack == 1);
            Near("back shown", t.Route.ShownM, 10);
            Near("back root at route point", t.Position.X, 0);
            var rootBeforeForward = t.Position;
            row["travel"]!["progress_m"] = 35;
            using (var forward = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(forward.RootElement);
            Expect("forward counted, root keeps catch-up", mgr.Stats.TravFwd == 1 && t.Position == rootBeforeForward);
            Near("forward shown", t.Route.ShownM, 35);
            mgr.Tick(.25);
            Near("forward root catch-up .85 m", t.Position.X, .85, .001);
            Expect("route error observed", mgr.SyncCounters.TravErrMaxM > 0);
            var perf = new PerfProbe().Frame(true, .3, world)!;
            Expect("actual perf probe receives manager counters", perf["sync"]!["travBack"]!.GetValue<int>() == 1
                && perf["sync"]!["travFwd"]!.GetValue<int>() == 1 && perf["sync"]!["arrive"]!.GetValue<int>() == 1);
            // A new route turns north after the timeless east leg. With .25 s frames the height ease is 1,
            // so bed=(z+80)*.1 must match the reached point exactly, rather than the old poll height.
            row["travel"]!["waypoints"] = JsonNode.Parse("[[-10,-80],[0,-80],[0,-80],[0,-50]]");
            row["travel"]!["progress_m"] = 9.9;
            using (var corner = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(corner.RootElement);
            t.Position = new Vector3(-.1f, 0, -80);
            mgr.GroundYAt = (_, z) => (z + 80) * .1;
            for (int i = 1; i <= 12; i++)
            {
                mgr.Tick(.25);
                // Starting at m9.9, first .25 s crosses the last .1 of the timeless leg and walks .35 north.
                Near("corner shown by hand", t.Route.ShownM, 10 + .35 * i);
                AtRoute(t);
                Near("height at reached point", t.Position.Y, .035 * i, .001);
            }
            await CheckBridgeAndWater(host, fixtures);
            return "travel vectors=134 age=.49 target=10.686 frames=24 shown=19.086 smooth=19.2351429236 back=1 fwd=1 arrive=1 corner=12 bridge=held+handover water=move+idle epsilon=.01";
        }
        finally { world.QueueFree(); }
    }
    /// <summary>
    /// Task 42: reuse the measured bridge assets, with an ordinary travel block instead of the non-route order.
    /// A running route holds the root through get-up; a zero-delta hand-over must preserve foot world positions
    /// within .01 m and consume travel once. On water the mirror is 1.5 m, move sink .35, idle sink 1.3.
    /// </summary>
    private static async Task CheckBridgeAndWater(Node3D host, string fixtures)
    {
        var source = new FixtureSource(Path.Combine(fixtures, "bridges"), fixtures);
        using var hf = await source.GetHeightfieldAsync();
        var mgr = new FigureManager(source, new WorldHeight(HeightfieldOverview.Parse(hf.RootElement)), _ => { }, strict: true)
        { AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, GroundYAt = (_, _) => 0 };
        host.AddChild(mgr);
        try
        {
            await mgr.InitAsync();
            using var map = await source.GetWorldMapAsync();
            await mgr.Apply(map.RootElement);
            var mia = mgr.Figures["Mia Chair"];
            mgr.Tick(.1);
            for (int i = 0; i < 30; i++) mgr.Tick(1.0 / 30);
            var seat = mia.Position;
            var changed = JsonNode.Parse(map.RootElement.GetRawText())!;
            var row = changed["characters"]![0]!;
            row["activity_animation"] = "";
            row["travel"] = JsonNode.Parse("""
                {"journey_id":"bridge-route","waypoints":[[-60,30],[-60,130]],"progress_m":0,
                 "total_m":100,"starts_in_s":2,"paces_m_s_real":null}
                """);
            using (var pending = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(pending.RootElement);
            mgr.Tick(1.0 / 30);
            Expect("pending route opens holding get-up", mia.Bridging && mia.PaceLimit == 0 && mia.Position == seat);
            row["travel"]!["starts_in_s"] = null;
            row["travel"]!["paces_m_s_real"] = new JsonArray(1.4);
            using (var running = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(running.RootElement);
            int frames = 0;
            while (mia.Bridging && frames++ < 400)
            {
                mgr.Tick(1.0 / 30);
                Expect("early route cannot pull root under bridge", mia.Position == seat);
            }
            Expect("get-up completed with travel held", !mia.Bridging && mia.HoldsTravel && frames < 400);
            var skel = mia.Skeleton!;
            Vector3[] Feet()
            {
                var feet = new System.Collections.Generic.List<Vector3>();
                for (int i = 0; i < skel.GetBoneCount(); i++)
                    if (BoneNames.Norm(skel.GetBoneName(i)) is "leftfoot" or "rightfoot")
                        feet.Add((skel.GlobalTransform * skel.GetBoneGlobalPose(i)).Origin);
                return feet.ToArray();
            }
            var before = Feet();
            Expect("both feet measured", before.Length == 2);
            mgr.Tick(0);
            var after = Feet();
            for (int i = 0; i < before.Length; i++) Near("route hand-over feet continuity", before[i].DistanceTo(after[i]), 0, .01);
            Expect("travel taken without settle", !mia.HoldsTravel && mia.Settle is null && mia.Position != seat);
            var taken = mia.Position;
            mgr.Tick(0);
            Expect("travel consumed exactly once", mia.Position == taken);

            row["travel"]!["waypoints"] = new JsonArray(new JsonArray(taken.X, taken.Z), new JsonArray(taken.X, taken.Z + 30));
            row["travel"]!["progress_m"] = 0;
            using (var lake = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(lake.RootElement);
            mgr.GroundMoveAt = (_, _) => new GroundMove(FigureClips.Swim, new GroundSink(.35, 1.3), 1.5, 1, 1, GroundScope.Wilderness, null);
            mgr.Tick(.25);
            Near("route floats on mirror", mia.Position.Y, 1.5, .001);
            Near("route moving sink", mia.Drop, .35, .001);
            Expect("route swims without run and has ghost", mia.Moving && !mia.Running && mia.CurrentKind == "breast-stroke" && mia.Ghost is { Visible: true });
            Near("route ghost uses ungated mirror", mia.Ghost!.CutY, 1.5, .001);
            row["travel"]!["paces_m_s_real"] = null;
            using (var frozen = JsonDocument.Parse(changed.ToJsonString())) await mgr.Apply(frozen.RootElement);
            var at = mia.Position;
            mgr.Tick(.25);
            Expect("frozen route treads water", !mia.Moving && mia.CurrentKind == "treading-water" && mia.Position == at);
            Near("route idle sink", mia.Drop, 1.3, .001);
        }
        finally { mgr.QueueFree(); }
    }

    private static void AtRoute(Figure f)
    {
        var p = TravelPath.PointAtDistance(f.Route!.Points, f.Route.ShownM)!.Value;
        Near("rendered X vs route", f.Position.X, p.X, .01);
        Near("rendered Z vs route", f.Position.Z, p.Z, .01);
    }
    private static void Expect(string field, bool ok) { if (!ok) throw new Exception($"travel {field}"); }
    private static void Near(string field, double actual, double expected, double eps = 1e-8)
    { if (!double.IsFinite(actual) || Math.Abs(actual - expected) > eps) throw new Exception($"travel {field}: actual {actual:R}, expected {expected:R}, epsilon {eps}"); }
}
