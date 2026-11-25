using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Plan E3 Task 6, the avatar's orders at the controller level (native/fixtures/README.md, "Orders world", R2–R2d):
///   R2  a refusal at t = 0.8 s aborts the local order where it stands — no further phase — and turns the avatar away;
///   R2b the reservation answer held back for 30 frames: the avatar moves in the first frame after the click;
///   R2c a second click on B while A's request runs: A's acceptance is cancelled BEFORE B is requested, B's 409
///       <c>request_in_progress</c> is retried once and never shown; only B stays reserved, the avatar stands at B's access;
///   R2d a walk over the stairs: the ride asks for the room; refused → <c>link_refused</c> at the stair foot, no room
///       change; accepted → the server room changes before the ride ends.
///   R6  (plan E3 Task 7) the answer's order reports_arrival: at the access the avatar sends <c>/play/order/arrived</c>
///       exactly once and plays the entry at once (answer ok → the loop); R6x the answer <c>arrive_too_far</c> aborts the
///       order at the access, lets go of the run and hands the avatar back;
///   R6b between <c>arrived_access</c> and <c>loop_started</c> no <c>/play/pos</c> goes to the source.
/// R2–R2c and R6 run on the propactions world (fixture-avatar at (−3, −2), bench-56 access (2, −1), straight walk at 1.4 m/s),
/// R2d on the orders world (Nia Nav in r-a at (97, −1), stairs 1 foot (101, 0, −3.3) → head (104.5, 3, −3.3)).
/// </summary>
public static partial class OrderCheck
{
    private static async Task<int> AvatarAsync(Node3D host, string fixtures, WorldBuilder ordersBuilder, Node3D ordersWorld, List<FigureManager> runs)
    {
        int checks = 0;
        void Is(string what, bool ok, string detail = "") { checks++; Expect(what, ok, detail); }
        void NearXZ(string what, Vector3 got, double x, double z) { checks++; Expect(what, Math.Abs(got.X - x) <= TolM && Math.Abs(got.Z - z) <= TolM, $"got ({got.X:0.####}, {got.Z:0.####}), want ({x}, {z})"); }
        void Near(string what, double got, double want, double tol) { checks++; Expect(what, Math.Abs(got - want) <= tol, $"got {got:0.####}, want {want} ± {tol}"); }

        // ---- R2, R2b, R2c: the propactions world through the real offers controller ----
        foreach (string scenario in new[] { "R2", "R2b", "R2c", "R6", "R6x" })
        {
            var fixture = new FixtureSource(Path.Combine(fixtures, "propactions"), fixtures);
            var source = new PropActionsCheck.MenuSource(fixture) { CancelKeepsWorld = true };
            foreach (var row in source.Offers) { row!["enabled"] = true; row["reason"] = ""; }
            if (scenario == "R2c")
            {
                // A second bench B: one slot (−1, 2) facing 0, the actor's access (−1, 1).
                var scene = JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir, "scene_loc-props.json")))!.AsObject();
                var b = scene["markers"]![0]!.DeepClone().AsObject();
                b["id"] = "prop-bench-57-seat57"; b["marker_id"] = "seat57"; b["placement_id"] = "bench-57"; b["capacity"] = 1;
                b["at_world"] = new JsonArray(-1, 2); b["anchor"] = new JsonArray(-1, 2); b["slots"] = new JsonArray(new JsonArray(-1, 2)); b["facing"] = 0;
                b["access"] = JsonNode.Parse("""{"actor":{"x":-1,"y":0,"z":1,"yaw":0}}""");
                scene["markers"]!.AsArray().Add(b);
                source.SceneOverride = scene;
            }
            var world = new Node3D { Name = "OrderAvatar" + scenario };
            host.AddChild(world);
            var builder = new WorldBuilder(source, _ => { }, strict: true);
            var hud = new HudOverlay();
            AvatarPositionController? position = null;
            AvatarOffersController? offers = null;
            double now = 1000;
            try
            {
                await builder.BuildAsync(world, "Fixture Prop Room");
                builder.SetOpen("loc-props", true);
                builder.Slots["loc-props"].Fade.Snap(1);
                var m = new FigureManager(source, builder.Height!, _ => { }, strict: true) { AutoTick = false, Slots = () => builder.Slots, GroundYAt = builder.FigureGroundY };
                world.AddChild(m);
                using var map = await source.GetWorldMapAsync();
                await m.Apply(map.RootElement);
                var avatar = m.Figures[m.AvatarName];
                var states = new List<(OrderState State, double T)>();
                m.OrderFrameShown += (name, frame) =>
                {
                    if (name == m.AvatarName && (states.Count == 0 || states[^1].State != frame.State)) states.Add((frame.State, m.Clock));
                };
                var steering = new PlayerSteering(m, builder);
                steering.SetActive(true);
                position = new(m, builder, steering, source, () => now);
                position.SetActive(true, map.RootElement);
                offers = new(m, builder, steering, source, hud, position, () => now);
                offers.SetActive(true);
                if (offers.PendingPropAction is { } initial) await initial;
                void Frame() { now += Dt * 1000; m.Tick(Dt); offers.Tick(); }
                void Click(string placement)
                {
                    var action = source.Offers[0]!.DeepClone().AsObject();
                    action["target"]!["placement_id"] = placement;
                    hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(), action["target"]!.DeepClone(), action["definition_revision"]!.DeepClone()));
                }
                string States() => string.Join(" ", states.Select(s => $"{s.State}@{s.T:0.###}"));
                var answers = new Queue<TaskCompletionSource<JsonDocument>>();
                source.OnRequest = _ => { var t = new TaskCompletionSource<JsonDocument>(); answers.Enqueue(t); return t.Task; };
                static JsonDocument Doc(string json) => JsonDocument.Parse(json);
                double t0 = m.Clock;

                if (scenario == "R2")
                {
                    var said = new List<string>();
                    offers.ReasonToast = (code, _) => said.Add(code);
                    Click("bench-56");
                    while (m.Clock < t0 + 0.8 - 1e-9) Frame();
                    answers.Dequeue().SetResult(Doc("""{"execution_id":"","status":"refused","reason":"no_free_slot"}"""));
                    await offers.PendingPropAction!;
                    var stoodAt = avatar.Position;
                    for (int i = 0; i < 60; i++) Frame();
                    // 0.8 s × 1.4 m/s = 1.12 m along (5, 1)/√26 from (−3, −2) → (−1.901750, −1.780350).
                    NearXZ("R2 aborted where the refusal found it", stoodAt, -1.901750, -1.780350);
                    // The hand-back lets go of the aborted order: no Idle frame, and no phase after the abort.
                    Is("R2 Walk → Abort, no further phase", states.Select(s => s.State).SequenceEqual(new[] { OrderState.Walk, OrderState.Abort }), States());
                    Near("R2 Abort at 0.8 s", states[1].T - t0, 0.8, TolS);
                    NearXZ("R2 the avatar stays where it stopped", avatar.Position, -1.901750, -1.780350);
                    Is("R2 the avatar is the player's again", !m.HasLiveOrder(m.AvatarName) && !m.ServerDriven && !steering.PropActionDriven);
                    // Away from the bench's slot (2, 0.129, 0): atan2(−1.901750 − 2, −1.780350 − 0) = −114.527°.
                    Near("R2 turned away from the furniture", Math.IEEERemainder(avatar.Yaw * 180 / Math.PI + 114.527, 360), 0, 1.0);
                    // The HUD gets the CODE and shows the sentence of propActionReasons.ts (review Task 6 I1), never the raw code.
                    Is("R2 the refusal reaches the HUD by its code", said.SequenceEqual(new[] { "no_free_slot" }), string.Join(",", said));
                }
                else if (scenario == "R2b")
                {
                    // The answer here carries no order; its adoption in place is checked in PropActionsCheck (CheckOwnOrders).
                    Click("bench-56");
                    var before = avatar.Position;
                    Frame();
                    double first = new Vector2(avatar.Position.X - before.X, avatar.Position.Z - before.Z).Length();
                    // One frame at 1.4 m/s: 0.023333 m.
                    Is("R2b the avatar moves in the first frame after the click", first > 0, $"moved {first:0.######}");
                    Near("R2b the first frame's step", first, 1.4 / 60, 0.005);
                    for (int i = 1; i < 30; i++) Frame();
                    Is("R2b the answer is still held back", answers.Count == 1 && !answers.Peek().Task.IsCompleted);
                    // 30 frames = 0.5 s → 0.7 m → (−2.313594, −1.862719).
                    NearXZ("R2b walked 0.7 m before any answer", avatar.Position, -2.313594, -1.862719);
                    source.StateOverride = new JsonObject { ["current"] = new JsonArray(new JsonObject { ["execution_id"] = "run-b", ["status"] = "approaching" }), ["outgoing"] = new JsonArray() };
                    answers.Dequeue().SetResult(Doc("""{"execution_id":"run-b","status":"approaching"}"""));
                    await offers.PendingPropAction!;
                    while (m.Clock < t0 + 5.0) Frame();
                    // √26 / 1.4 = 3.642157 s to the access (2, −1); the local order waits there for the server's order.
                    NearXZ("R2b at the access after the answer", avatar.Position, 2, -1);
                    Is("R2b Walk → WaitAccess", states.Select(s => s.State).SequenceEqual(new[] { OrderState.Walk, OrderState.WaitAccess }), States());
                    Near("R2b at the access at 3.642 s", states[1].T - t0, 3.642157, TolS);
                }
                else if (scenario is "R6" or "R6x")
                {
                    // The answer carries the run's order (fixture-avatar reports_arrival; eta = issued + √26 / 1.4).
                    bool refuse = scenario == "R6x";
                    var said = new List<string>();
                    offers.ReasonToast = (code, _) => said.Add(code);
                    source.StateOverride = PropActionsCheck.RunState("run-r6");
                    source.OnRequest = _ => Task.FromResult(Doc(new JsonObject
                    {
                        ["execution_id"] = "run-r6", ["status"] = "approaching", ["order"] = PropActionsCheck.OwnOrder("run-r6", m.MotionNow),
                    }.ToJsonString()));
                    if (refuse)
                        source.OnArrived = _ => Task.FromException<JsonDocument>(new ApiException(409, "/play/order/arrived",
                            """{"execution_id":"","status":"refused","reason":"arrive_too_far"}"""));
                    var answered = new List<string>();
                    m.OrderArrivalAnswered += (name, order, reason) => answered.Add($"{name}:{order.Id}:{reason}");
                    var reportsAt = new Dictionary<string, int>();
                    m.OrderFrameShown += (name, frame) =>
                    {
                        if (name != m.AvatarName) return;
                        foreach (var e in frame.Events) reportsAt.TryAdd(e, source.PositionReports);
                    };
                    int reportsAtClick = source.PositionReports;
                    Click("bench-56");
                    await offers.PendingPropAction!;
                    while (m.Clock < t0 + 7.0) Frame();
                    await offers.PendingPropAction!;
                    // √26 / 1.4 = 3.642157 s to the access (2, −1): ONE report there, for the run's order, in its room.
                    Is($"{scenario} arrived is sent exactly once", source.Arrivals.Count == 1, $"{source.Arrivals.Count}");
                    Is($"{scenario} for run-r6 in r-props", source.Arrivals.All(a => a.OrderId == "run-r6" && a.RoomId == "r-props"));
                    if (source.Arrivals.Count > 0) NearXZ($"{scenario} reported at the access", new Vector3((float)source.Arrivals[0].X, 0, (float)source.Arrivals[0].Z), 2, -1);
                    if (!refuse)
                    {
                        Is("R6 the answer is ok", answered.SequenceEqual(new[] { "fixture-avatar:run-r6:" }), string.Join(",", answered));
                        // No wait at the access: the entry starts on the arrival, the loop follows (entry ≤ 2.5 s).
                        Is("R6 Walk → Entry → Loop", states.Select(s => s.State).SequenceEqual(new[] { OrderState.Walk, OrderState.Entry, OrderState.Loop }), States());
                        Near("R6 the entry starts at the arrival, 3.642 s", states.Count > 1 ? states[1].T - t0 : -1, 3.642157, TolS);
                        // R6b: the order owns the avatar from the click to the loop: no /play/pos
                        // goes out during the walk either (the server keeps the plan's position;
                        // contract § A11b transport (5)), so none between arrived_access and loop_started.
                        Is("R6b arrived_access and loop_started seen", reportsAt.ContainsKey("arrived_access") && reportsAt.ContainsKey("loop_started"),
                           string.Join(",", reportsAt.Keys));
                        Is("R6b no /play/pos from the click to loop_started",
                           reportsAt.GetValueOrDefault("arrived_access", -1) == reportsAtClick
                           && reportsAt.GetValueOrDefault("loop_started", -2) == reportsAtClick,
                           $"{reportsAtClick} → {reportsAt.GetValueOrDefault("arrived_access", -1)} → {reportsAt.GetValueOrDefault("loop_started", -2)}");
                    }
                    else
                    {
                        Is("R6x the refusal is read", answered.SequenceEqual(new[] { "fixture-avatar:run-r6:arrive_too_far" }), string.Join(",", answered));
                        Is("R6x Walk → Entry → Abort", states.Select(s => s.State).Take(3).SequenceEqual(new[] { OrderState.Walk, OrderState.Entry, OrderState.Abort }), States());
                        Near("R6x aborted at the arrival, 3.642 s", states.Count > 2 ? states[2].T - t0 : -1, 3.642157, TolS);
                        NearXZ("R6x stands at the access", avatar.Position, 2, -1);
                        Is("R6x the run is let go", source.Calls.Contains("cancel:run-r6"), string.Join(",", source.Calls));
                        Is("R6x the refusal reaches the HUD by its code", said.SequenceEqual(new[] { "arrive_too_far" }), string.Join(",", said));
                        Is("R6x the avatar is the player's again", !m.HasLiveOrder(m.AvatarName) && !steering.PropActionDriven);
                    }
                }
                else
                {
                    Click("bench-56");
                    for (int i = 0; i < 10; i++) Frame();
                    var a = answers.Dequeue();
                    Click("bench-57");
                    Is("R2c B waits for A's request", answers.Count == 0 && source.Calls.SequenceEqual(new[] { "request:bench-56" }), string.Join(",", source.Calls));
                    Is("R2c the avatar walks B's local order", m.OrderPlayerOf(m.AvatarName)?.Current?.Id == "local:2", m.OrderPlayerOf(m.AvatarName)?.Current?.Id ?? "none");
                    // B's first request finds A still ending (409 request_in_progress), its retry is accepted.
                    int bRequests = 0;
                    source.OnRequest = _ => ++bRequests == 1
                        ? Task.FromException<JsonDocument>(new ApiException(409, "/play/prop-actions/request", "request_in_progress"))
                        : Task.FromResult(Doc("""{"execution_id":"run-b","status":"approaching"}"""));
                    source.StateOverride = new JsonObject { ["current"] = new JsonArray(new JsonObject { ["execution_id"] = "run-b", ["status"] = "approaching" }), ["outgoing"] = new JsonArray() };
                    var toasts = new List<string>();
                    offers.Toast = toasts.Add;
                    offers.ReasonToast = (code, _) => toasts.Add(code);
                    a.SetResult(Doc("""{"execution_id":"run-a","status":"approaching"}"""));
                    await offers.PendingPropAction!;
                    for (int i = 0; i < 5 && source.Calls.Count < 4; i++) { await Task.Yield(); await offers.PendingPropAction!; }
                    Is("R2c cancel(A) before request B, B retried once", source.Calls.SequenceEqual(new[] { "request:bench-56", "cancel:run-a", "request:bench-57", "request:bench-57" }),
                       string.Join(",", source.Calls));
                    Is("R2c the 409 is never shown", toasts.Count == 0, string.Join(" | ", toasts));
                    Is("R2c only B is reserved", source.Reserved.SetEquals(new[] { "run-b" }), string.Join(",", source.Reserved));
                    while (m.Clock < t0 + 8.0) Frame();
                    NearXZ("R2c the avatar stands at B's access", avatar.Position, -1, 1);
                    Is("R2c B's local order waits at its access", m.OrderPlayerOf(m.AvatarName)?.RunState == OrderState.WaitAccess, $"{m.OrderPlayerOf(m.AvatarName)?.RunState}");
                }
            }
            finally
            {
                offers?.Dispose(); position?.Dispose(); hud.Free();
                builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            }
        }

        // ---- R2d the avatar's order walk over the stairs asks for the loft ----
        var ordersDir = Path.Combine(fixtures, "orders");
        var slot = ordersBuilder.Slots["loc-nav"];
        foreach (bool accept in new[] { false, true })
        {
            var src = new FixtureSource(ordersDir, fixtures);
            src.SelectRoomScenario(accept ? "nav-up" : "nav-up-rejected");
            var hud = new HudOverlay();
            AvatarRoomsController? rooms = null;
            try
            {
                var m = new FigureManager(src, ordersBuilder.Height!, _ => { }, strict: true)
                {
                    AutoTick = false, Slots = () => ordersBuilder.Slots, GroundYAt = ordersBuilder.FigureGroundY,
                    NavOf = loc => ordersBuilder.Slots.TryGetValue(loc, out var s) ? ordersBuilder.NavFor(s) : null,
                };
                ordersWorld.AddChild(m);
                runs.Add(m);
                await m.InitAsync();
                m.SetProcess(false);
                using var map = await src.GetWorldMapAsync();
                await m.Apply(map.RootElement);
                var f = m.Figures[m.AvatarName];
                var steering = new PlayerSteering(m, ordersBuilder) { RoomId = "r-a" };
                double now = 0;
                rooms = new AvatarRoomsController(m, ordersBuilder, steering, src, hud, () => now);
                rooms.SetActive(true);
                var events = new List<string>();
                m.OrderFrameShown += (name, frame) => { if (name == m.AvatarName) events.AddRange(frame.Events); };
                var start = new OrderPoint(f.Position.X, f.Position.Y, f.Position.Z, 0);
                // The goal on the loft (storey 1) where NavCheck A0 found the nearest loft point: (100.35, 3, 0.8).
                var walk = LocalOrders.Walk(1, m.MotionNow, LocalOrders.DefaultSpeedMS, m.AvatarName, start, "r-a", 0,
                                            new OrderPoint(100.35, 3, 0.8, 0), "loc-nav", "r-up", 1);
                Is($"R2d {(accept ? "accept" : "refuse")}: the walk starts", m.StartLocalOrder(walk));
                // The hook is wired AFTER the avatar's player exists (review Task 6 I4: MainWorld applies the first map before
                // MainEmbody sets it): the ride is chosen at the stair foot, so the room is still asked for. On 09af630c6 the
                // player kept the NPC rides built at its birth — no room request, no link_refused.
                m.AvatarLinkRide = rooms.OrderLinkRide;
                double? roomAtY = null;
                for (int i = 0; i < 60 * 25; i++)
                {
                    now += Dt * 1000;
                    m.Tick(Dt);
                    if (roomAtY is null && steering.RoomId == "r-up") roomAtY = f.Position.Y;
                    if (events.Contains("link_refused") || m.OrderPlayerOf(m.AvatarName)?.RunState == OrderState.Loop) break;
                    await Task.Yield();
                }
                if (!accept)
                {
                    Is("R2d refused: link_refused", events.Contains("link_refused"), string.Join(",", events));
                    NearXZ("R2d refused: stays at the stair foot", f.Position, 101, -3.3);
                    Near("R2d refused: on storey 0", f.Position.Y, 0, TolM);
                    Is("R2d refused: no room change", steering.RoomId == "r-a" && roomAtY is null, steering.RoomId);
                    Is("R2d refused: one room request", src.RoomRequests.Count == 1, $"{src.RoomRequests.Count}");
                }
                else
                {
                    Is("R2d accepted: the walk reaches the loft", m.OrderPlayerOf(m.AvatarName)?.RunState == OrderState.Loop, string.Join(",", events));
                    Is("R2d accepted: the room changed before the ride ended", roomAtY is { } y && y < 3 - TolM, $"room at y {roomAtY}");
                    NearXZ("R2d accepted: on the loft goal", f.Position, 100.35, 0.8);
                    Near("R2d accepted: on storey 1", f.Position.Y, 3, TolM);
                }
            }
            finally { rooms?.Dispose(); hud.Free(); }
        }
        return checks;
    }
}
