using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check orders</c> (part of every <c>--check</c>, plan E3 Task 5): NPC furniture approaches played from orders on the
/// real navigation of the orders world (<c>fixtures/orders/</c> = the nav world plus a stool; NPC "Ona Order" seated on the
/// stool, NPC "Uli Up" standing in r-a at (97, −1)). Every number is the hand derivation of native/fixtures/README.md,
/// section "Orders world" (R1–R14 there). Frames of 1/60 s through a real <see cref="FigureManager"/> fed by
/// <see cref="FigureManager.Apply"/> — the worldmap poll path; tolerances: positions 0.05 m, lengths ± 0.05, times ± 0.1 s.
///
///   R1  Ona → bed: Exit → Walk → Entry → Loop, each once, through three polls of the same order with other position
///       fields; chain end 5.68 ± 0.1, |end − (flip − issued)| ≤ 1.5;          R3 lag 2.5 → Walk at 1.82 m;
///   R3b status active → Loop on the slot;  R4 revision 2 (+30 s) restarts nothing, a new cancel id aborts the walk;
///   R5  awaits reaction → WaitAccess, the revision without it starts the entry at 4.0;
///   R9  every orders fixture: access ≤ 0.4 m from the mesh, final piece through no wall, links within the radius;
///   R10 two-person run: the pair interaction of the rows, both on their slots, no re-placement;
///   R11 a phase revision changes the pose from the row, no new run;  R12 late entry in phase 2 shows that phase;
///   R13 a row without order (order_seq ≥ seq) blends into the rest placement; R13b an older row changes nothing;
///   R13c a local walk outlives a row without order;
///   R14 a held member's follow pose has no exit clip, a cancel for one member exits only that one.
/// </summary>
public static class OrderCheck
{
    private const double Dt = 1.0 / 60, TolM = 0.05, TolS = 0.1;
    private const string Ona = "Ona Order", Uli = "Uli Up";
    // README "Orders world": exit 1.2 + walk 2.911549 / 1.4 + entry 2.4.
    private const double ChainEndS = 5.679678, FlipRelS = 6.096489, WalkLenM = 2.911549;
    private static readonly Vec3 BedSlot = new(104, 0.5, 1.5);

    private sealed class Run
    {
        public required FigureManager M;
        public readonly List<(string Name, OrderState State, double T)> States = new();
        public readonly List<(string Name, string Event, double T)> Events = new();
        public IEnumerable<OrderState> Of(string name) => States.Where(s => s.Name == name).Select(s => s.State);
        public double? At(string name, OrderState st) => States.Where(s => s.Name == name && s.State == st).Select(s => (double?)s.T).FirstOrDefault();
        public void Until(double t) { while (M.Clock < t - 1e-9) M.Tick(Dt); }
        public Figure F(string name) => M.Figures[name];
    }

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "orders");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "OrdersWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        var runs = new List<FigureManager>();
        int checks = 0;
        try
        {
            await builder.BuildAsync(world, "Navhaus");
            var slot = builder.Slots["loc-nav"];
            builder.SetOpen("loc-nav", true);
            slot.Fade.Snap(1);
            LocationNav? nav = null;
            for (int i = 0; i < 240 && (nav = builder.NavFor(slot)) is null; i++)
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
            if (nav is null) throw new InvalidOperationException("orders: no navigation within 240 physics frames");
            for (int i = 0; i < 120 && !nav.Ready; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);

            JsonObject Read(string name) => JsonNode.Parse(File.ReadAllText(Path.Combine(dir, name)))!.AsObject();
            var baseMap = Read("worldmap.json");
            JsonObject Row(JsonObject map, string name) => map["characters"]!.AsArray().Select(c => c!.AsObject()).First(c => (string?)c["name"] == name);
            JsonObject Map(Action<JsonObject>? edit = null) { var m = (JsonObject)baseMap.DeepClone(); edit?.Invoke(m); return m; }
            JsonObject OrderOf(JsonObject map) => Row(map, Ona)["order"]!.AsObject();
            void Shift(JsonObject order, double s)
            {
                foreach (var k in new[] { "issued_motion_s", "eta_motion_s", "flip_motion_s", "deadline_motion_s" })
                    if (order[k] is { } v) order[k] = v.GetValue<double>() + s;
            }
            async Task<Run> Start(JsonObject map)
            {
                var m = new FigureManager(source, builder.Height!, _ => { }, strict: true)
                {
                    AutoTick = false, Slots = () => builder.Slots, GroundYAt = builder.FigureGroundY,
                    NavOf = loc => builder.Slots.TryGetValue(loc, out var s) ? builder.NavFor(s) : null,
                };
                world.AddChild(m);
                runs.Add(m);
                await m.InitAsync();
                m.SetProcess(false);
                var run = new Run { M = m };
                var last = new Dictionary<string, OrderState>();
                m.OrderFrameShown += (name, frame) =>
                {
                    if (!last.TryGetValue(name, out var was) || was != frame.State) run.States.Add((name, frame.State, m.Clock));
                    last[name] = frame.State;
                    foreach (var e in frame.Events) run.Events.Add((name, e, m.Clock));
                };
                await m.Apply(JsonSerializer.SerializeToElement(map));
                return run;
            }
            Task Poll(Run run, JsonObject map) => run.M.Apply(JsonSerializer.SerializeToElement(map));
            void NearXZ(string what, Vector3 got, Vec3 want) { checks++; Expect(what, Math.Abs(got.X - want.X) <= TolM && Math.Abs(got.Z - want.Z) <= TolM, $"got ({got.X:0.###}, {got.Z:0.###}), want ({want.X}, {want.Z})"); }
            void Near(string what, double? got, double want, double tol) { checks++; Expect(what, got is { } g && Math.Abs(g - want) <= tol, $"got {got?.ToString("0.######") ?? "null"}, want {want} ± {tol}"); }
            void Is(string what, bool ok, string detail = "") { checks++; Expect(what, ok, detail); }
            string Seq(Run r, string n) => string.Join(" ", r.States.Where(s => s.Name == n).Select(s => $"{s.State}@{s.T:0.###}"));

            // ---- R9 the orders fixtures against the map ----
            var walls = Collide.WallSegments(slot.Scene, 0, new P2(100, 0));
            var fixtureOrders = new List<JsonObject>();
            foreach (var name in new[] { "worldmap.json", "worldmap_poll2.json" })
                foreach (var c in Read(name)["characters"]!.AsArray())
                    if (c!["order"] is JsonObject o) fixtureOrders.Add(o);
            foreach (var o in Read("orders.json")["orders"]!.AsArray()) fixtureOrders.Add(o!.AsObject());
            Is("R9 fixture orders found", fixtureOrders.Count == 3, $"{fixtureOrders.Count}");
            foreach (var wire in fixtureOrders)
            {
                var order = OrderParse.From(JsonSerializer.SerializeToElement(wire));
                Is("R9 fixture order parses", order is not null);
                foreach (var a in order!.Actors)
                {
                    if (a.Access is not { } access) continue;
                    var on = nav.Closest(access.Pos);
                    double gap = Math.Sqrt((on.X - access.X) * (on.X - access.X) + (on.Z - access.Z) * (on.Z - access.Z));
                    Is($"R9 {order.Id} {a.Name} access ≤ 0.4 m from the mesh", gap <= 0.4, $"gap {gap:0.###}");
                    Is($"R9 {order.Id} {a.Name} final piece crosses no wall", !walls.Any(w => Crosses(on.X, on.Z, access.X, access.Z, w)));
                }
            }
            double radius = NavigationServer3D.MapGetLinkConnectionRadius(nav.Map);
            foreach (var (owner, rid) in nav.Links)
                foreach (var end in new[] { NavigationServer3D.LinkGetStartPosition(rid), NavigationServer3D.LinkGetEndPosition(rid) })
                {
                    var c = NavigationServer3D.MapGetClosestPoint(nav.Map, end);
                    Is($"R9 link {owner} end within the connection radius", c.DistanceTo(end) <= radius, $"{c.DistanceTo(end):0.###} > {radius}");
                }

            // ---- R1 Ona → bed, three polls of the same order with other position fields ----
            var r1 = await Start(Map());
            var poll2 = Read("worldmap_poll2.json");
            r1.Until(1.0); await Poll(r1, poll2);
            r1.Until(3.0); await Poll(r1, poll2);
            r1.Until(5.0); await Poll(r1, poll2);
            r1.Until(7.0);
            var states = r1.Of(Ona).ToList();
            Is("R1 exactly Exit → Walk → Entry → Loop", states.SequenceEqual(new[] { OrderState.Exit, OrderState.Walk, OrderState.Entry, OrderState.Loop }), Seq(r1, Ona));
            Near("R1 Exit from t ≈ 0", r1.At(Ona, OrderState.Exit), 0, Dt + 1e-6);
            Near($"R1 chain end ({Seq(r1, Ona)}, walked {r1.M.OrderPlayerOf(Ona)?.WalkedM:0.######})", r1.At(Ona, OrderState.Loop), ChainEndS, TolS);
            Is("R1 |end − (flip − issued)| ≤ 1.5", r1.At(Ona, OrderState.Loop) is { } chainEnd && Math.Abs(chainEnd - FlipRelS) <= 1.5);
            Near("R1 walked length", r1.M.OrderPlayerOf(Ona)?.WalkedM, WalkLenM, TolM);
            NearXZ("R1 on the bed slot", r1.F(Ona).Position, BedSlot);
            var settled = r1.F(Ona).Position;
            await Poll(r1, poll2); r1.Until(7.5);
            Is("R1 a poll after the loop does not move the figure", r1.F(Ona).Position.DistanceTo(settled) <= 1e-4, $"{r1.F(Ona).Position}");

            // ---- R1b the orders topic: GET /play/orders?since= feeds the same player ----
            var r1b = await Start(Map(m => { Row(m, Ona).Remove("order"); m["order_seq"] = 0; }));
            await r1b.M.PullOrdersAsync();
            r1b.Until(0.5);
            Is("R1b pulled order plays", r1b.Of(Ona).FirstOrDefault() == OrderState.Exit, Seq(r1b, Ona));
            await r1b.M.PullOrdersAsync();
            r1b.Until(1.0);
            Is("R1b since follows the highest seq seen (0, then 1)", source.OrdersSince.TakeLast(2).SequenceEqual(new long[] { 0, 1 }),
               string.Join(",", source.OrdersSince));
            Is("R1b the same order twice restarts nothing", r1b.Of(Ona).SequenceEqual(new[] { OrderState.Exit }), Seq(r1b, Ona));

            // ---- R3 a late order seeks into the walk ----
            var r3 = await Start(Map(m => m["motion_now"] = 102.5));
            r3.Until(Dt);
            Is("R3 starts in Walk", r3.Of(Ona).FirstOrDefault() == OrderState.Walk, Seq(r3, Ona));
            Near("R3 walked 1.82 m", r3.M.OrderPlayerOf(Ona)?.WalkedM, (2.5 - 1.2) * 1.4, TolM);

            // ---- R3b status active → the loop on the slot at once ----
            var r3b = await Start(Map(m => OrderOf(m)["status"] = "active"));
            r3b.Until(Dt);
            Is("R3b starts in Loop", r3b.Of(Ona).FirstOrDefault() == OrderState.Loop, Seq(r3b, Ona));
            NearXZ("R3b on the slot", r3b.F(Ona).Position, BedSlot);

            // ---- R4 a revision moves nothing, a new id aborts ----
            var r4 = await Start(Map());
            r4.Until(2.0);
            double issued = r4.M.OrderPlayerOf(Ona)!.IssuedLocal;
            await Poll(r4, Map(m => { var o = OrderOf(m); o["revision"] = 2; o["seq"] = 2; Shift(o, 30); m["order_seq"] = 2; m["motion_now"] = 102; }));
            r4.Until(3.0);
            Is("R4 revision restarts nothing", r4.Of(Ona).SequenceEqual(new[] { OrderState.Exit, OrderState.Walk }), Seq(r4, Ona));
            Near("R4 IssuedLocal unchanged", r4.M.OrderPlayerOf(Ona)!.IssuedLocal, issued, 1e-9);
            await Poll(r4, Map(m =>
            {
                var o = OrderOf(m);
                o["order_id"] = "ord-cancel"; o["kind"] = "cancel"; o["status"] = "ended"; o["seq"] = 3; m["order_seq"] = 3; m["motion_now"] = 103;
                Shift(o, 3.0);
                var a = o["actors"]![0]!.AsObject();
                a["sequence"] = new JsonArray(); a["stand"] = new JsonObject { ["x"] = 102.5, ["y"] = 0, ["z"] = 0, ["yaw"] = 0 };
            }));
            r4.Until(3.1);
            Is("R4 cancel aborts out of the walk", r4.Of(Ona).SequenceEqual(new[] { OrderState.Exit, OrderState.Walk, OrderState.Abort, OrderState.Idle }), Seq(r4, Ona));
            Near("R4 abort at 3.0", r4.At(Ona, OrderState.Abort), 3.0, 2 * Dt);

            // ---- R5 awaits a reaction: waits at the access, the revision without it enters at 4.0 ----
            var r5 = await Start(Map(m => { var o = OrderOf(m); o["awaits"] = "reaction"; o["status"] = "waiting"; o.Remove("flip_motion_s"); }));
            r5.Until(4.0);
            Is("R5 waits at the access", r5.Of(Ona).LastOrDefault() == OrderState.WaitAccess, Seq(r5, Ona));
            NearXZ("R5 stands at the access", r5.F(Ona).Position, new Vec3(103.15, 0, 1.5));
            await Poll(r5, Map(m => { var o = OrderOf(m); o["revision"] = 2; o["seq"] = 2; m["order_seq"] = 2; m["motion_now"] = 104; }));
            r5.Until(4.5);
            Near("R5 entry from 4.0", r5.At(Ona, OrderState.Entry), 4.0, 2 * Dt);

            // ---- R10 a two-person run: the pair of the rows, both on their slots ----
            JsonObject PairMap(Action<JsonObject>? edit = null) => Map(m =>
            {
                var o = OrderOf(m);
                o["order_id"] = "ord-pair"; o["status"] = "active";
                var b = o["actors"]![0]!.DeepClone().AsObject();
                b["name"] = Uli; b["role"] = "b"; b["clip_role"] = "b";
                b["start"] = new JsonObject { ["x"] = 97, ["y"] = 0, ["z"] = -1, ["yaw"] = 0, ["room_id"] = "r-a", ["level"] = 0 };
                b["anchor"] = new JsonObject { ["x"] = 104, ["y"] = 0.5, ["z"] = 1.0, ["yaw"] = 90, ["root_offset"] = 0 };
                b["access"] = new JsonObject { ["x"] = 103.15, ["y"] = 0, ["z"] = 1.0, ["yaw"] = 90 };
                o["actors"]!.AsArray().Add(b);
                Row(m, Uli)["order"] = o.DeepClone();
                foreach (var (n, role) in new[] { (Ona, "a"), (Uli, "b") })
                {
                    var row = Row(m, n);
                    row["room_id"] = "r-b"; row["activity_animation"] = "pair-pose";
                    row["interaction"] = JsonNode.Parse($$"""{"id":"pair-1","kind":"pair-pose","role":"{{role}}","members":{"a":"{{Ona}}","b":"{{Uli}}"},"anchor":{"x":104,"z":1.25,"yaw":1.5708,"place_id":"bed"},"elapsed_s":3,"clip_s":2.5,"clip_duration_s":4,"loop":true,"rate":1}""");
                }
                edit?.Invoke(m);
            });
            var r10 = await Start(PairMap());
            r10.Until(0.5);
            Is("R10 both in Loop", r10.Of(Ona).FirstOrDefault() == OrderState.Loop && r10.Of(Uli).FirstOrDefault() == OrderState.Loop, Seq(r10, Ona) + " / " + Seq(r10, Uli));
            Is("R10 both adopt the row's pair on clip_s", r10.F(Ona).Pair is { Id: "pair-1" } po && r10.F(Uli).Pair is { Id: "pair-1" } pu
               && Math.Abs(po.ClipT - 2.5) <= 0.6 && Math.Abs(pu.ClipT - 2.5) <= 0.6, $"{r10.F(Ona).Pair?.ClipT} {r10.F(Uli).Pair?.ClipT}");
            NearXZ("R10 Ona on her slot", r10.F(Ona).Position, BedSlot);
            NearXZ("R10 Uli on his slot", r10.F(Uli).Position, new Vec3(104, 0.5, 1.0));
            var (ona10, uli10) = (r10.F(Ona).Position, r10.F(Uli).Position);
            await Poll(r10, PairMap(m => { Row(m, Ona)["pos"] = new JsonObject { ["x"] = 99, ["z"] = 3 }; Row(m, Uli)["pos"] = new JsonObject { ["x"] = 98, ["z"] = 3 }; }));
            r10.Until(1.0);
            Is("R10 no re-placement by a poll", r10.F(Ona).Position.DistanceTo(ona10) <= 1e-4 && r10.F(Uli).Position.DistanceTo(uli10) <= 1e-4,
               $"{r10.F(Ona).Position} {r10.F(Uli).Position}");

            // ---- R11 combined: a phase revision changes the pose from the row, no new run ----
            JsonObject Phased(int phase, bool late = false) => Map(m =>
            {
                var o = OrderOf(m);
                o["status"] = "active"; o["revision"] = phase; o["seq"] = phase; m["order_seq"] = phase;
                var seq = o["actors"]![0]!["sequence"]!.AsArray();
                if (phase >= 2) seq.Add(new JsonObject { ["step"] = "phase", ["pose_kind"] = "seat", ["pose_key"] = "sitting", ["nominal_s"] = 0 });
                Row(m, Ona)["activity_animation"] = phase >= 2 ? "sitting" : "laying";
                if (late) m["motion_now"] = 130;
            });
            var r11 = await Start(Phased(1));
            r11.Until(0.5);
            double issued11 = r11.M.OrderPlayerOf(Ona)!.IssuedLocal;
            await Poll(r11, Phased(2));
            r11.Until(1.0);
            Is("R11 still the one loop", r11.Of(Ona).SequenceEqual(new[] { OrderState.Loop }), Seq(r11, Ona));
            Is("R11 the phase pose from the row", r11.F(Ona).Activity == "sitting" && r11.M.OrderPlayerOf(Ona)!.PhasePoseKind == "seat",
               $"{r11.F(Ona).Activity} {r11.M.OrderPlayerOf(Ona)!.PhasePoseKind}");
            Near("R11 no new run (IssuedLocal)", r11.M.OrderPlayerOf(Ona)!.IssuedLocal, issued11, 1e-9);
            NearXZ("R11 stays on the slot", r11.F(Ona).Position, BedSlot);

            // ---- R12 late entry in phase 2 ----
            var r12 = await Start(Phased(2, late: true));
            r12.Until(Dt);
            Is("R12 Loop at once", r12.Of(Ona).FirstOrDefault() == OrderState.Loop, Seq(r12, Ona));
            Is("R12 the phase-2 pose", r12.M.OrderPlayerOf(Ona)!.PhasePoseKind == "seat" && r12.F(Ona).Activity == "sitting");
            NearXZ("R12 on the slot", r12.F(Ona).Position, BedSlot);

            // ---- R13 a row without order: blend into the rest placement; R13b an older row changes nothing ----
            JsonObject Ended(long orderSeq) => Map(m =>
            {
                m["order_seq"] = orderSeq;
                var row = Row(m, Ona); row.Remove("order");
                row["pos"] = new JsonObject { ["x"] = 103.6, ["z"] = 1.5 };
                row["activity_animation"] = "laying";
            });
            var r13 = await Start(Map(m => OrderOf(m)["status"] = "active"));
            r13.Until(0.5);
            await Poll(r13, Ended(0));
            r13.Until(1.0);
            Is("R13b an older row keeps the order", r13.M.HasLiveOrder(Ona) && !r13.Events.Any(e => e.Event == "ended"), Seq(r13, Ona));
            NearXZ("R13b still on the slot", r13.F(Ona).Position, BedSlot);
            await Poll(r13, Ended(1));
            r13.Until(1.0 + Dt);
            Is("R13 ended", r13.Events.Any(e => e.Name == Ona && e.Event == "ended") && !r13.M.HasLiveOrder(Ona));
            Is("R13 no poll snap: the first frame is still near the slot", Math.Abs(r13.F(Ona).Position.X - 104) <= TolM, $"x {r13.F(Ona).Position.X:0.###}");
            r13.Until(1.4);
            NearXZ("R13 blended into the rest placement", r13.F(Ona).Position, new Vec3(103.6, 0, 1.5));
            r13.Until(2.0);
            NearXZ("R13 stays in the rest placement", r13.F(Ona).Position, new Vec3(103.6, 0, 1.5));

            // ---- R13c a local walk outlives a row without order ----
            var r13c = await Start(Map(m => Row(m, Ona).Remove("order")));
            var local = OrderParse.From(JsonSerializer.SerializeToElement(JsonNode.Parse($$"""
                {"order_id":"local:1","revision":1,"seq":0,"kind":"walk","issued_motion_s":100,"eta_motion_s":102,"flip_motion_s":102,
                 "deadline_motion_s":112,"status":"approaching","awaits":"","gait":"walk","speed_m_s":1.4,
                 "target":{"location_id":"loc-nav","room_id":"r-a","level":0,"x":99,"y":0,"z":0},"hint_route":[],"snap":false,
                 "actors":[{"name":"{{Uli}}","role":"","clip_role":"","height_cm":180,"start":{"x":97,"y":0,"z":-1,"yaw":0,"room_id":"r-a","level":0},
                            "access":null,"anchor":null,"entry_mode":"","sequence":[{"step":"walk","pose_kind":"","pose_key":"","nominal_s":0}],"reports_arrival":false}]}
                """)))!;
            r13c.M.AdoptOrders(new[] { local }, 100);
            r13c.Until(0.5);
            Is("R13c walking", r13c.Of(Uli).LastOrDefault() == OrderState.Walk, Seq(r13c, Uli));
            await Poll(r13c, Map(m => { Row(m, Ona).Remove("order"); m["order_seq"] = 9; }));
            r13c.Until(0.6);
            Is("R13c the row does not end the local walk", r13c.M.HasLiveOrder(Uli) && r13c.Of(Uli).LastOrDefault() == OrderState.Walk, Seq(r13c, Uli));
            r13c.Until(3.0);
            NearXZ("R13c arrives at the goal", r13c.F(Uli).Position, new Vec3(99, 0, 0));

            // ---- R14 a held member's follow pose; a cancel for one member ----
            var r14 = await Start(PairMap());
            r14.Until(0.5);
            await Poll(r14, PairMap(m =>
            {
                var follow = Row(m, Uli)["order"]!.AsObject();
                follow["order_id"] = "ord-follow"; follow["seq"] = 2; m["order_seq"] = 2;
                follow["actors"] = new JsonArray(follow["actors"]![1]!.DeepClone());
                follow["actors"]![0]!["sequence"] = new JsonArray(new JsonObject { ["step"] = "loop", ["pose_kind"] = "seat", ["pose_key"] = "sitting", ["nominal_s"] = 0 });
            }));
            r14.Until(1.0);
            await Poll(r14, PairMap(m =>
            {
                var cancel = Row(m, Ona)["order"]!.AsObject();
                cancel["order_id"] = "ord-end"; cancel["kind"] = "cancel"; cancel["status"] = "ended"; cancel["seq"] = 3; m["order_seq"] = 3; m["motion_now"] = 101;
                Shift(cancel, 1.0);
                var a = cancel["actors"]![0]!.DeepClone().AsObject();
                a["sequence"] = new JsonArray(new JsonObject { ["step"] = "exit", ["pose_kind"] = "lie", ["pose_key"] = "laying", ["nominal_s"] = 1.0 });
                a["stand"] = new JsonObject { ["x"] = 103.05, ["y"] = 0, ["z"] = 1.5, ["yaw"] = -90 };
                cancel["actors"] = new JsonArray(a);
                Row(m, Uli).Remove("order");
                foreach (var n in new[] { Ona, Uli }) Row(m, n).Remove("interaction");
            }));
            r14.Until(3.0);
            Is("R14 the held member never exits", !r14.Of(Uli).Contains(OrderState.Exit), Seq(r14, Uli));
            Is("R14 exactly one exit, for Ona", r14.Of(Ona).Count(s => s == OrderState.Exit) == 1, Seq(r14, Ona));

            return $"orders {checks} checks (chain end {r1.At(Ona, OrderState.Loop):0.###} s, walked {r1.M.OrderPlayerOf(Ona)?.WalkedM:0.###} m)";
        }
        finally
        {
            foreach (var m in runs) m.QueueFree();
            builder.StopResidency();
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static bool Crosses(double ax, double az, double bx, double bz, WallSegment s)
    {
        double rx = bx - ax, rz = bz - az, sx = s.Bx - s.Ax, sz = s.Bz - s.Az;
        double denom = rx * sz - rz * sx;
        if (Math.Abs(denom) < 1e-12) return false;
        double qx = s.Ax - ax, qz = s.Az - az;
        double t = (qx * sz - qz * sx) / denom, u = (qx * rz - qz * rx) / denom;
        return t >= 0 && t <= 1 && u >= 0 && u <= 1;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"orders {what}: {detail}");
    }
}
