using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Threading;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 89: stored-token handoff, first upstairs placement and bounded final writes, without a world DB.</summary>
public static class ResumeCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        int n = 0;
        void Is(string name, bool value) { n++; if (!value) throw new InvalidOperationException("resume " + name); }
        static PositionAnswer Answer() => new(200, JsonSerializer.Deserialize<JsonElement>("{\"ok\":true}"));
        var handoff = typeof(HudOverlay).GetMethod(nameof(HudOverlay.HandoffScript))!;
        Is("handoff accepts same-session protection", handoff.GetParameters().Length == 5);
        string Script(bool end) => (string)handoff.Invoke(null, new object?[] { "stored-token", false,
            "http://fixture/static/client3d/hud.html?bridge=gdcef", null, end })!;
        Is("same-token handoff cannot log out", !Script(false).Contains("/auth/logout"));
        Is("different-token recovery retains guarded logout", Script(true).Contains(HudOverlay.EndSessionScript));
        File.WriteAllText(ProjectSettings.GlobalizePath("user://task89-handoff.json"), JsonSerializer.Serialize(new
        { fresh = Script(true), same = Script(false), recovery = Script(true) }));

        var source = new FixtureSource(Path.Combine(fixtures, "placement"), fixtures);
        var world = new Node3D { Name = "ResumeWorld" }; host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        try
        {
            await builder.BuildAsync(world, "Inn");
            var node = JsonNode.Parse(builder.FirstMap!.Value.GetRawText())!;
            node["characters"] = new JsonArray(new JsonObject
            {
                ["name"] = "Tess Vale", ["location_id"] = "loc-inn", ["room_id"] = "r-loft",
                ["pos"] = new JsonObject { ["x"] = 64, ["z"] = 128 }, ["yaw"] = 1.2,
                ["height_cm"] = 170, ["travel"] = null
            });
            using var map = JsonDocument.Parse(node.ToJsonString());
            var inn = builder.Slots["loc-inn"]; inn.Fade.Snap(0); builder.SetLevel("loc-inn", 0);
            var prepare = typeof(WorldBuilder).GetMethod("PrepareAvatarArrival");
            Is("arrival preparation exists", prepare is not null);
            var manager = new FigureManager(source, builder.Height!, _ => { }, strict: true)
            { AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, Slots = () => builder.Slots,
                PrepareAvatarPlacement = builder.PrepareAvatarArrival };
            world.AddChild(manager); manager.SetProcess(false); await manager.InitAsync();
            inn.Ready = false;
            await manager.Apply(map.RootElement);
            Is("unready room never renders the outdoor fallback", !manager.Figures.ContainsKey("Tess Vale"));
            inn.Ready = true;
            await manager.Apply(map.RootElement); await manager.EnsurePool();
            Is("storey and interior precede the figure", inn.LevelFilter == 1 && inn.Fade.Fade == 1);
            var fig = manager.Figures["Tess Vale"];
            Is("first placement is server point at upstairs floor", fig.Position.DistanceTo(new Vector3(64, 7.03f, 128)) < .002);
            Is("first yaw is authoritative", Math.Abs(fig.Yaw - 1.2) < .0001);
            manager.SetPlayerDriven("Tess Vale"); manager.Tick(.016);
            Is("takeover starts no walking bridge", fig.Target == fig.Position && !fig.Bridging && fig.Waypoints.Count == 0);
            Is("first frame remains upstairs", Math.Abs(fig.Position.Y - 7.03) < .002);

            // Drive Main's actual shutdown barrier through the production API serializer/transport.
            using var transport = new PositionFixture();
            using var api = new AnimaApi("http://fixture.invalid", transport);
            api.AdoptSession("stored-token");
            var steering = new PlayerSteering(manager, builder); steering.SetActive(true);
            using var position = new AvatarPositionController(manager, builder, steering, api, () => 340);
            position.SetActive(true, map.RootElement);
            var hud = new HudOverlay();
            using var roomController = new AvatarRoomsController(manager, builder, steering, api, hud, () => 340);
            roomController.SetActive(true);
            roomController.Channel.Walk("r-loft", new(64, 128),
                new[] { new AnimaNative.Scene.ElevatorRoom("__floor__1", 1, new(64, 128)) }, 1);
            manager.SnapPlayerTo("Tess Vale", new(64.25f, 7.03f, 128));
            var main = new Main();
            try
            {
                const BindingFlags fields = BindingFlags.Instance | BindingFlags.NonPublic;
                typeof(Main).GetField("_figures", fields)!.SetValue(main, manager);
                typeof(Main).GetField("_avatarPosition", fields)!.SetValue(main, position);
                typeof(Main).GetField("_avatarRooms", fields)!.SetValue(main, roomController);
                await (Task)typeof(Main).GetMethod("FlushPlayerOnExitAsync", fields)!.Invoke(main, null)!;
                Is("Main waits for position then dirty room before shutdown", transport.Paths.Count == 2
                    && transport.Paths[0] == "/play/pos" && transport.Paths[1] == "/play/enter-room");
                Is("actual HTTP body carries final rendered point", transport.Position.GetProperty("x").GetDouble() == 64.25);
            }
            finally { main.Free(); hud.Free(); }
        }
        finally
        {
            builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }

        double now = 330;
        var writes = new List<PositionReport>();
        using var channel = new PositionChannel((p, _) => { writes.Add(p); return Task.FromResult(Answer()); }, () => now);
        channel.Tick(new(1, 1), true); now = 340; channel.Tick(new(2, 1), true);
        Is("last step is throttled and dirty", writes.Count == 1 && channel.Dirty);
        var flush = typeof(PositionChannel).GetMethod("FlushOnShutdownAsync");
        Is("shutdown flush exists", flush is not null);
        await (Task)flush!.Invoke(channel, new object?[] { new AnimaNative.Scatter.P2(2, 1), 1000 })!;
        Is("shutdown awaits final position", writes.Count == 2 && writes[1].x == 2 && !channel.InFlight);

        var rooms = new List<string>();
        using var room = new RoomEntryChannel((id, _) => { rooms.Add(id); return Task.FromResult(Answer()); }, () => now);
        room.Walk("bath", new(2, 1), new[] { new AnimaNative.Scene.ElevatorRoom("guest", 1, new(2, 1)) }, 1);
        Is("room change waits for ordinary hysteresis", rooms.Count == 0);
        var flushRoom = typeof(RoomEntryChannel).GetMethod("FlushOnShutdownAsync");
        Is("room shutdown flush exists", flushRoom is not null);
        await (Task)flushRoom!.Invoke(room, null)!;
        Is("quit preserves dirty room before disposal", rooms.Count == 1 && rooms[0] == "guest");

        var first = new TaskCompletionSource<PositionAnswer>();
        writes.Clear(); now = 330;
        using (var queued = new PositionChannel((p, _) => { writes.Add(p); return writes.Count == 1 ? first.Task : Task.FromResult(Answer()); }, () => now))
        {
            queued.Tick(new(1, 1), true); now = 340; queued.Tick(new(3, 1), true);
            var shutdown = queued.FlushOnShutdownAsync(new(3, 1));
            Is("quit waits for existing flight", !shutdown.IsCompleted && writes.Count == 1);
            first.SetResult(Answer());
            Is("newest point drains after old flight", await shutdown && writes.Count == 2 && writes[1].x == 3);
        }
        bool cancelled = false;
        using (var hung = new PositionChannel((_, ct) => { ct.Register(() => cancelled = true); return new TaskCompletionSource<PositionAnswer>().Task; }, () => now))
        {
            hung.Tick(new(1, 1), true);
            var timer = System.Diagnostics.Stopwatch.StartNew();
            Is("stalled shutdown is bounded and cancels HTTP", !await hung.FlushOnShutdownAsync(new(1, 1), 100)
                && cancelled && timer.ElapsedMilliseconds < 600);
        }
        using (var owned = new PositionChannel((_, _) => throw new InvalidOperationException("must not stand up"), () => now))
        {
            owned.CanReport = () => false;
            Is("seated or server-owned shutdown sends nothing", await owned.FlushOnShutdownAsync(null));
        }
        using (var clean = new PositionChannel((_, _) => throw new InvalidOperationException("clean shutdown must not author movement"), () => now))
            Is("clean idle shutdown sends no synthetic movement", await clean.FlushOnShutdownAsync(new(1, 1)));
        return $"resume cases={n}";
    }

    private sealed class PositionFixture : HttpMessageHandler
    {
        public List<string> Paths { get; } = new();
        public JsonElement Position { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            string path = request.RequestUri!.AbsolutePath;
            Paths.Add(path);
            using var body = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(ct));
            if (path == "/play/pos") Position = body.RootElement.Clone();
            else if (path != "/play/enter-room") throw new InvalidOperationException("unexpected shutdown request " + path);
            return new HttpResponseMessage(HttpStatusCode.OK)
                { Content = new StringContent("{\"ok\":true,\"location_id\":\"loc-inn\",\"room_id\":\"r-loft\"}") };
        }
    }
}
