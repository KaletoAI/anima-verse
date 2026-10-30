using System;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Sync;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 71: drive Main's real take-control and F handlers with a delayed switch and fixture map sequence.</summary>
public static class AvatarRecoveryCheck
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static void Set(Main main, string name, object? value) => typeof(Main).GetField(name, Private)!.SetValue(main, value);
    private static T Get<T>(Main main, string name) => (T)typeof(Main).GetField(name, Private)!.GetValue(main)!;
    private static object? Call(Main main, string name, params object?[] args) => typeof(Main).GetMethod(name, Private)!.Invoke(main, args);

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        int n = 0;
        void Is(string label, bool value) { n++; if (!value) throw new InvalidOperationException("avatar recovery " + label); }
        var source = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        var world = new Node3D { Name = "AvatarRecoveryWorld" }; host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        // Keep Main outside the tree: _Ready would start another client. Its actual handlers still use real tree nodes.
        var main = new Main();
        var hud = new HudOverlay();
        AvatarRecovery? recovery = null;
        try
        {
            await builder.BuildAsync(world, "Fixture Hall");
            var figures = new FigureManager(source, builder.Height!, _ => { }, strict: true)
            { AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, Slots = () => builder.Slots };
            world.AddChild(figures); figures.SetProcess(false); await figures.InitAsync();
            var camera = new OverviewCamera(); world.AddChild(camera); camera.SetProcess(false);
            var boot = new BootTracker(() => 0);
            foreach (var stage in BootProgress.Stages) boot.Report(stage);
            Set(main, "_source", source); Set(main, "_builder", builder); Set(main, "_figures", figures);
            Set(main, "_camera", camera); Set(main, "_hud", hud); Set(main, "_bootState", boot);
            Call(main, "AttachEmbody", hud);
            recovery = (AvatarRecovery)Call(main, "SessionAvatar")!;
            await recovery.RememberFirstMapAsync(builder.FirstMap!.Value);
            var original = JsonNode.Parse(builder.FirstMap.Value.GetRawText())!;
            JsonElement Map(string? avatar, bool point)
            {
                var map = original.DeepClone(); map["avatar"] = avatar;
                map["characters"] = point ? new JsonArray(new JsonObject
                {
                    ["name"] = "fixture-avatar", ["location_id"] = "", ["room_id"] = "",
                    ["pos"] = new JsonObject { ["x"] = -12, ["z"] = -10 }, ["height_cm"] = 170
                }) : new JsonArray();
                return JsonSerializer.Deserialize<JsonElement>(map.ToJsonString());
            }
            var missing = Map(null, false); var present = Map("fixture-avatar", true);
            async Task WaitForFigure()
            {
                ulong deadline = Time.GetTicksMsec() + 5000;
                while (!figures.Figures.TryGetValue("fixture-avatar", out var avatar) || avatar.Loading)
                {
                    if (Time.GetTicksMsec() >= deadline) throw new InvalidOperationException("avatar recovery figure did not finish loading");
                    await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                }
            }
            figures.ApplyPolled(present); await figures.FirstPollDone;
            await WaitForFigure();
            var autoBoot = new BootTracker(() => 0);
            Set(main, "_bootState", autoBoot);
            Call(main, "TryAutoTakeControl");
            Is("automatic control waits for arrival", !Get<EmbodyMode>(main, "_embody").Active);
            Set(main, "_bootState", boot);
            Set(main, "_options", new CliOptions(null,null,"Fixture Hall",false));
            Call(main, "TryAutoTakeControl");
            Is("goto keeps overview", !Get<EmbodyMode>(main, "_embody").Active);
            Set(main, "_autoControlHandled", false);
            Set(main, "_options", new CliOptions(null,null,null,false));
            Set(main, "_showAll", true);
            Call(main, "TryAutoTakeControl");
            Is("admin overview keeps overview", !Get<EmbodyMode>(main, "_embody").Active);
            Set(main, "_autoControlHandled", false); Set(main, "_showAll", false);
            Call(main, "TryAutoTakeControl");
            Is("arrival automatically controls session avatar", Get<EmbodyMode>(main, "_embody").Active);
            hud.Handlers["exitEmbodied"](new JsonArray());
            Call(main, "TryAutoTakeControl");
            Is("Esc is not undone by automation", !Get<EmbodyMode>(main, "_embody").Active);
            Set(main, "_autoControlHandled", false);
            Call(main, "TryAutoTakeControl");
            Is("fresh resume session automatically controls", Get<EmbodyMode>(main, "_embody").Active);
            hud.Handlers["exitEmbodied"](new JsonArray());
            var adminRecovery = new AvatarRecovery(source, () => Task.CompletedTask);
            Set(main, "_avatarRecovery", adminRecovery); Set(main, "_autoControlHandled", false);
            Call(main, "TryAutoTakeControl");
            Is("account without avatar stays overview", !Get<EmbodyMode>(main, "_embody").Active);
            adminRecovery.Dispose(); Set(main, "_avatarRecovery", recovery);
            Set(main, "_autoControlHandled", true);
            figures.ApplyPolled(missing);
            source.AvatarMaps.Enqueue(missing); source.AvatarMaps.Enqueue(present);
            var oldPoll = (Task)Call(main, "FetchWorldMapAsync")!;
            await oldPoll;
            var stale = oldPoll.GetType().GetProperty("Result")!.GetValue(oldPoll);
            Call(main, "ApplyWorldMap", stale);
            source.CharacterSwitchGate = new TaskCompletionSource();
            Set(main, "_autoControlHandled", false);
            Call(main, "TryAutoTakeControl");
            hud.Handlers["takeControl"](new JsonArray());
            Is("automatic control waits for recovery POST", Get<bool>(main, "_pendingTakeControl") && recovery.Waiting);
            Is("second press never double posts", source.CharacterSwitchRequests.Count == 1);
            Is("exact remembered request body", source.CharacterSwitchRequests[0].GetRawText() == "{\"character_name\":\"fixture-avatar\"}");
            Is("no map repoll before accepted switch", source.AvatarMapRequests == 1);
            source.CharacterSwitchGate.SetResult(); await recovery.Request!;
            Is("immediate worldmap repoll", source.AvatarMapRequests == 2 && figures.AvatarName == "fixture-avatar");
            Call(main, "ApplyWorldMap", stale);
            Is("pre-switch poll cannot erase restored avatar", figures.AvatarName == "fixture-avatar");
            await figures.Apply(present); await figures.EnsurePool();
            await WaitForFigure();
            Call(main, "TickEmbody");
            Is("restored request becomes embodied", Get<EmbodyMode>(main, "_embody").Active && !Get<bool>(main, "_pendingTakeControl"));
            hud.Handlers["exitEmbodied"](new JsonArray());

            // F goes through the same recovery even if selection still describes the vanished avatar.
            figures.ApplyPolled(missing);
            source.AvatarMaps.Enqueue(present); source.CharacterSwitchGate = null;
            Call(main, "TickEmbody");
            hud.SetState("selected", new JsonObject { ["isAvatar"] = true });
            hud.RouteSceneKey(new InputEventKey { Keycode = Key.F, Pressed = true });
            await recovery.Request!; await figures.Apply(present); await figures.EnsurePool();
            await WaitForFigure(); Call(main, "TickEmbody");
            Is("F uses recovery and then embodies",
                source.CharacterSwitchRequests.Count == 2 && Get<EmbodyMode>(main, "_embody").Active);
            hud.Handlers["exitEmbodied"](new JsonArray());

            // A later account release/switch during place loading still belongs to this same control press.
            var placed = JsonNode.Parse(present.GetRawText())!;
            placed["characters"]![0]!["location_id"] = "loc-hall";
            placed["characters"]![0]!["pos"] = new JsonObject { ["x"] = -3, ["z"] = 1 };
            var placedMap = JsonSerializer.Deserialize<JsonElement>(placed.ToJsonString());
            figures.ApplyPolled(placedMap); await WaitForFigure();
            builder.Slots["loc-hall"].Ready = false;
            hud.Handlers["takeControl"](new JsonArray());
            Is("own place readiness holds without POST", Get<bool>(main, "_pendingArrivalTakeControl") && source.CharacterSwitchRequests.Count == 2);
            var other = JsonNode.Parse(present.GetRawText())!;
            other["avatar"] = "fixture-npc"; other["characters"]![0]!["name"] = "fixture-npc";
            figures.ApplyPolled(JsonSerializer.Deserialize<JsonElement>(other.ToJsonString()));
            source.AvatarMaps.Enqueue(present);
            Call(main, "TickEmbody");
            Is("changed avatar during arrival restores own once", source.CharacterSwitchRequests.Count == 3
                && source.CharacterSwitchRequests[2].GetProperty("character_name").GetString() == "fixture-avatar"
                && !Get<EmbodyMode>(main, "_embody").Active);
            await recovery.Request!; await WaitForFigure(); Call(main, "TickEmbody");
            Is("arrival recovers only own figure", Get<EmbodyMode>(main, "_embody").Active && figures.AvatarName == "fixture-avatar");
            hud.Handlers["exitEmbodied"](new JsonArray()); builder.Slots["loc-hall"].Ready = true;

            figures.ApplyPolled(missing);
            source.CharacterSwitchStatus = 403; source.CharacterSwitchDetail = "No access to character 'fixture-avatar'";
            hud.Handlers["takeControl"](new JsonArray()); await recovery.Request!;
            Is("refused switch preserves server sentence", recovery.Failure == "No access to character 'fixture-avatar'");
            int polls = source.AvatarMapRequests; Call(main, "TickEmbody"); Call(main, "TickEmbody");
            Is("refusal ends pending with no retry or poll", !Get<bool>(main, "_pendingTakeControl") && source.CharacterSwitchRequests.Count == 4 && source.AvatarMapRequests == polls);

            // A session with no remembered identity must not adopt a later map's character.
            recovery.Dispose();
            recovery = new AvatarRecovery(source, () => Task.CompletedTask);
            await recovery.RememberFirstMapAsync(missing); Set(main, "_avatarRecovery", recovery);
            figures.ApplyPolled(missing); hud.Handlers["takeControl"](new JsonArray());
            Is("unknown own avatar keeps old terminal path", recovery.OwnCharacter is null && !Get<bool>(main, "_pendingTakeControl") && source.CharacterSwitchRequests.Count == 4);
            return $"avatar_recovery={n} own_only=1 switch_once=1 immediate_poll=1 take_control=embodied F=embodied refusal=verbatim unknown=no_post";
        }
        finally
        {
            Call(main, "DetachEmbody");
            recovery?.Dispose(); main.Free(); hud.Free(); builder.Models?.FreeAll(); world.QueueFree();
        }
    }
}
