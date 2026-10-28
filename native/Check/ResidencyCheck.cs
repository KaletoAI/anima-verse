using System;
using System.IO;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Api;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 44 / E6-T4 hand-derived stream flight on the s3c footprints. The avatar is removed to isolate the
/// camera probe: (64,120) → (600,128) → (2000,2000). Open's ±5 m footprint is near at the start;
/// closed's ±4 m footprint is also near (100²+16² distance). Far's west edge x596 is 532 m away,
/// so far (≤560); at (600,128) it promotes near, open/closed demote far (531 and 636 m, both ≤672).
/// At (2000,2000), all three leave (>672) and gone at that position enters near with the borrowed Watch Post recipe. Pinning far while
/// the probe is exactly 600 m outside its east edge must promote it near. An awaited scene fetch
/// invalidated by DropVanished must roll back without publishing ready. R7 reuses only the GLB template;
/// R8 expires a completed reveal's predicate; R9 removes storey 1; R10 closes during a shell await; R11 frees
/// the world during a detail await; R12 invalidates a sweep before its fetch replies. R13 advances two 0.5 s
/// frames (one stream tick), pins current/open at the same 600 m footprint distance, and puts a probe on each
/// of two distant locations. R14 removes the placement fixture's stool/cot and therefore their sit/lie spots.
/// Expected order is checked per id, because the two independent queue slots may interleave their commits.
/// </summary>
public static class ResidencyCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var source = new ControlledSource(new FixtureSource(Path.Combine(fixtures, "s3c"), fixtures));
        var world = new Node3D { Name = "ResidencyWorld" }; host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-residency] " + line), strict: true);
        var order = new Dictionary<string, List<Ring>>();
        builder.ResidencyChanged += (id, ring) =>
        { if (!order.ContainsKey(id)) order[id] = new(); order[id].Add(ring); };
        var ready = new List<string>(); builder.Ready += slot => ready.Add(slot.Loc.Id);
        try
        {
            await builder.BuildAsync(world, "Glass");
            var map = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "s3c", "worldmap.json")))!;
            map["avatar"] = ""; map["characters"] = new System.Text.Json.Nodes.JsonArray();
            using var doc = System.Text.Json.JsonDocument.Parse(map.ToJsonString());
            builder.SetOpen("loc-open", false);
            builder.SetStreamView(doc.RootElement, new[] { (64.0, 120.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R1 start", builder.Residency.Ring("loc-open") == Ring.Near && builder.Residency.Ring("loc-far") == Ring.Far);
            builder.SetStreamView(doc.RootElement, new[] { (600.0, 128.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R2 promotion/demotion", builder.Residency.Ring("loc-far") == Ring.Near && builder.Residency.Ring("loc-open") == Ring.Far
                 && builder.Residency.Ring("loc-closed") == Ring.Far);
            builder.SetStreamView(doc.RootElement, new[] { (2000.0, 2000.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R3 drop/build beyond boot", builder.Residency.Ring("loc-open") == Ring.Gone && builder.Residency.Ring("loc-far") == Ring.Gone
                 && builder.Residency.Ring("loc-gone") == Ring.Near && builder.Slots["loc-gone"].Ready
                 && builder.Slots["loc-gone"].Placements.Any(r => r.Node is not null));
            Need("R3 per-id stage order", order["loc-open"].SequenceEqual(new[] { Ring.Far, Ring.Near, Ring.Far, Ring.Gone })
                && order["loc-closed"].SequenceEqual(new[] { Ring.Far, Ring.Near, Ring.Far, Ring.Gone })
                && order["loc-far"].SequenceEqual(new[] { Ring.Far, Ring.Near, Ring.Far, Ring.Gone })
                && order["loc-gone"].SequenceEqual(new[] { Ring.Far, Ring.Near }));
            map["avatar"] = "Pia";
            map["characters"] = new JsonArray(new JsonObject { ["name"] = "Pia", ["location_id"] = "",
                ["pos"] = new JsonObject { ["x"] = 1204, ["z"] = 128 }, ["travel"] = new JsonObject { ["target_id"] = "loc-far" } });
            using var travel = JsonDocument.Parse(map.ToJsonString());
            builder.SetStreamView(travel.RootElement, new[] { (1204.0, 128.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R4 travel pin 600 m from footprint", builder.Residency.Ring("loc-far") == Ring.Near && builder.Slots["loc-far"].Ready
                && builder.StreamPins["travel"] == "loc-far" && builder.StreamPins["boot"] is null);
            builder.SetStreamView(doc.RootElement, new[] { (1204.0, 128.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R5 pin release holds far hysteresis", builder.Residency.Ring("loc-far") == Ring.Far && !builder.Slots["loc-far"].Ready);
            builder.SetStreamView(doc.RootElement, new[] { (1277.0, 128.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R5 beyond 672 drops", builder.Residency.Ring("loc-far") == Ring.Gone);

            // Two new places at the probe: one held before shell construction, one held in an indoor GLB load.
            // A scene with an indoor lamp + picture/mirror-free box makes detail ownership observable.
            var revealMap = (JsonObject)map.DeepClone(); revealMap["avatar"] = ""; revealMap["characters"] = new JsonArray();
            revealMap["locations"] = new JsonArray(Location("held-shell"), Location("held-detail"));
            using var revealDoc = JsonDocument.Parse(revealMap.ToJsonString());
            builder.SetStreamView(revealDoc.RootElement, new[] { (0.0, 0.0) });
            var revealing = builder.RevealAsync(revealDoc.RootElement, () => true);
            await Wait(host, () => source.ShellRequested && source.DetailRequested);
            Need("R6 not ready during awaited mount", !ready.Contains("held-shell") && !ready.Contains("held-detail")
                && builder.Slots["held-detail"].Ring == Ring.Far && !builder.Slots["held-detail"].Ready);
            builder.DropVanished(doc.RootElement);
            source.Release(); await revealing; await builder.WhenResidencyIdle();
            Need("R6 rollback never publishes ready", !ready.Contains("held-shell") && !ready.Contains("held-detail")
                && !builder.Slots.ContainsKey("held-shell") && !builder.Slots.ContainsKey("held-detail")
                && builder.Residency.Ring("held-detail") == Ring.Gone);

            // Rediscovery uses the retained GLB template, never a node or light registration of the old mount.
            await builder.RevealAsync(revealDoc.RootElement, () => true);
            Need("R7 rediscovery ready", builder.Slots["held-detail"].Ready && builder.Slots["held-shell"].Ready);
            var indoor = builder.Slots["held-detail"].Placements.Single();
            var template = await builder.Models!.GetAsync("/residency/detail.glb");
            Need("R7 template retained", template is not null && GodotObject.IsInstanceValid(template.Root)
                && indoor.Node is not null && indoor.LightId is not null);
            builder.SetStreamView(doc.RootElement, new[] { (2000.0, 2000.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R7 node freed, template retained", indoor.Node is null && indoor.LightId is null && GodotObject.IsInstanceValid(template!.Root));
            bool viewStillValid = true;
            ((JsonArray)revealMap["locations"]!).Add(Location("epoch-place"));
            using var epoch = JsonDocument.Parse(revealMap.ToJsonString());
            builder.SetStreamView(epoch.RootElement, new[] { (0.0, 0.0) });
            await builder.RevealAsync(epoch.RootElement, () => viewStillValid);
            viewStillValid = false; // Completed reveal must no longer own a revision predicate.
            builder.SetStreamView(epoch.RootElement, new[] { (2000.0, 2000.0) }); builder.TickStreamRings(); await builder.WhenResidencyIdle();
            builder.SetStreamView(epoch.RootElement, new[] { (0.0, 0.0) }); builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R8 completed reveal survives revision change", builder.Known.Contains("epoch-place") && builder.Slots["epoch-place"].Ready);

            ((JsonArray)revealMap["locations"]!).Add(Location("mutable"));
            using var mutable = JsonDocument.Parse(revealMap.ToJsonString());
            await builder.RevealAsync(mutable.RootElement, () => true);
            Need("R9 select upper storey", builder.SetLevel("mutable", 1));
            source.Upper = false;
            await builder.SweepAsync();
            Need("R9 removed storey resets to ground", builder.Slots["mutable"].LevelFilter == 0);
            builder.SetOpen("mutable", true);
            source.MutableModel = true;
            var sweeping = builder.SweepAsync();
            await Wait(host, () => source.MutableRequested);
            Need("R10 rebuilding absent slot", !builder.Slots.ContainsKey("mutable"));
            builder.SetOpen("mutable", false);
            source.ReleaseMutable(); await sweeping;
            Need("R10 close during rebuild releases desired pin", !builder.Slots["mutable"].Open);
            var previous = builder.Slots["mutable"];
            int readyBefore = ready.Count(id => id == "mutable");
            bool sweepValid = true;
            source.Revision++; source.SweepGate = new TaskCompletionSource();
            var invalidSweep = builder.SweepAsync(() => sweepValid);
            await Wait(host, () => source.SweepRequested);
            sweepValid = false; source.SweepGate.SetResult();
            await invalidSweep; await builder.WhenResidencyIdle();
            Need("R12 stale sweep publishes no remount/ready", ReferenceEquals(previous, builder.Slots["mutable"])
                && ready.Count(id => id == "mutable") == readyBefore);
            int streamTicks = 0;
            var currentMap = (JsonObject)map.DeepClone();
            currentMap["characters"]![0]!["location_id"] = "loc-far";
            currentMap["characters"]![0]!["travel"] = null;
            using var current = JsonDocument.Parse(currentMap.ToJsonString());
            builder.RefreshStreamView = () => { streamTicks++; builder.SetStreamView(current.RootElement, new[] { (1204.0, 128.0) }); };
            builder.TickView(0.5, new Vector3(5000, 50, 5000));
            Need("R13 no early stream tick", streamTicks == 0);
            builder.TickView(0.5, new Vector3(5000, 50, 5000)); await builder.WhenResidencyIdle();
            Need("R13 1 Hz current pin uses probe, not eye", streamTicks == 1 && builder.Residency.Ring("loc-far") == Ring.Near
                && builder.StreamPins["current"] == "loc-far");
            builder.RefreshStreamView = null;
            Need("R13 open pin set", builder.SetOpen("loc-far", true));
            builder.SetStreamView(doc.RootElement, new[] { (1204.0, 128.0) }); builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R13 open pin holds distant near", builder.Residency.Ring("loc-far") == Ring.Near && builder.StreamPins["open"] == "loc-far");
            builder.SetOpen("loc-far", false);
            builder.SetStreamView(doc.RootElement, new[] { (600.0, 128.0), (2000.0, 2000.0) }); builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R13 both probes participate", builder.Residency.Ring("loc-far") == Ring.Near && builder.Residency.Ring("loc-gone") == Ring.Near);
            await Furniture(host, fixtures);
            await Shutdown(host, fixtures);
            return "residency R1-R14 ok (order, pins, hysteresis, rollback, ownership, reveal epoch, storey/close rebuild, shutdown)";
        }
        finally { builder.StopResidency(); await builder.WhenResidencyIdle(); builder.Models?.FreeAll(); world.Free(); }
    }
    /// <summary>R14: placement fixture's stool/cot supply sit/lie spots; at probe x600 both buildings are far (≤672 m), so no indoor furniture remains.</summary>
    private static async Task Furniture(Node3D host, string fixtures)
    {
        var source = new FixtureSource(Path.Combine(fixtures, "placement"), fixtures);
        var world = new Node3D(); host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        try
        {
            await builder.BuildAsync(world, "Inn");
            var inn = builder.Slots["loc-inn"];
            Need("R14 furniture supplies spots", inn.Stands.SitSpots.Count > 0 && inn.Stands.LieSpots.Count > 0);
            using var map = await source.GetWorldMapAsync();
            var node = JsonNode.Parse(map.RootElement.GetRawText())!; node["avatar"] = ""; node["characters"] = new JsonArray();
            using var moved = JsonDocument.Parse(node.ToJsonString());
            builder.SetOpen("loc-inn", false); builder.SetStreamView(moved.RootElement, new[] { (600.0, 128.0) });
            builder.TickStreamRings(); await builder.WhenResidencyIdle();
            Need("R14 removed furniture leaves no spots", inn.Ring == Ring.Far && inn.Stands.SitSpots.Count == 0 && inn.Stands.LieSpots.Count == 0);
        }
        finally { builder.StopResidency(); await builder.WhenResidencyIdle(); builder.Models?.FreeAll(); world.Free(); }
    }

    private static async Task Shutdown(Node3D host, string fixtures)
    {
        var source = new ControlledSource(new FixtureSource(Path.Combine(fixtures, "s3c"), fixtures));
        var world = new Node3D(); host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        try
        {
            await builder.BuildAsync(world, "Glass"); builder.SetOpen("loc-open", false);
            using var doc = JsonDocument.Parse(new JsonObject { ["locations"] = new JsonArray(Location("held-detail")) }.ToJsonString());
            builder.SetStreamView(doc.RootElement, new[] { (0.0, 0.0) });
            var reveal = builder.RevealAsync(doc.RootElement, () => true);
            await Wait(host, () => source.DetailRequested);
            builder.StopResidency(); world.Free(); builder.Models!.FreeAll(); source.Release();
            await reveal.WaitAsync(TimeSpan.FromSeconds(5)); await builder.WhenResidencyIdle().WaitAsync(TimeSpan.FromSeconds(5));
            Need("R11 stopped mount drains after scene disposal", !builder.Residency.HasJob("held-detail") && !builder.Slots.ContainsKey("held-detail"));
        }
        finally { builder.StopResidency(); builder.Models?.FreeAll(); if (GodotObject.IsInstanceValid(world)) world.Free(); }
    }
    private static JsonObject Location(string id) => new()
    {
        ["id"] = id, ["name"] = id, ["pos_x"] = 0, ["pos_z"] = 0, ["plan_width_m"] = 8,
        ["boundary"] = new JsonArray(new JsonArray(-4, -4), new JsonArray(4, -4), new JsonArray(4, 4), new JsonArray(-4, 4)),
    };
    private static async Task Wait(Node host, Func<bool> ready)
    {
        ulong start = Time.GetTicksMsec();
        while (!ready())
        {
            if (Time.GetTicksMsec() - start > 5000) throw new InvalidOperationException("residency gate timed out");
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }
    private sealed class ControlledSource(FixtureSource fixture) : IWorldSource
    {
        private readonly TaskCompletionSource _shell = new(), _detail = new();
        public bool ShellRequested, DetailRequested, MutableRequested;
        public bool Upper = true, MutableModel;
        public int Revision; public bool SweepRequested; public TaskCompletionSource? SweepGate;
        private readonly TaskCompletionSource _mutable = new();
        public void ReleaseMutable() => _mutable.TrySetResult();
        public void Release() { _shell.TrySetResult(); _detail.TrySetResult(); }
        public async Task<JsonDocument?> GetLocationSceneAsync(string id)
        {
            // The initially gone footprint borrows the existing Watch Post recipe, proving a real mesh arrives.
            if (id == "loc-gone") return await fixture.GetLocationSceneAsync("loc-far");
            if (id == "held-shell") { ShellRequested = true; await _shell.Task; return JsonDocument.Parse("{}"); }
            if (id == "mutable")
            {
                if (SweepGate is { } gate) { SweepRequested = true; await gate.Task; }
                var scene = JsonNode.Parse("""{"k":1,"signature":"v1","levels":[{"level":0,"floor_y":0}],"rooms":[{"room_id":"inside","level":0}],"markers":[{"id":"stand","room_id":"inside"}]}""")!;
                scene["signature"] = (MutableModel ? "v3" : Upper ? "v1" : "v2") + ":" + Revision;
                if (Upper) ((JsonArray)scene["levels"]!).Add(new JsonObject { ["level"] = 1, ["floor_y"] = 3 });
                if (MutableModel) scene["models"] = new JsonArray(new JsonObject { ["id"] = "hull", ["role"] = "building", ["display"] = "shell",
                    ["variants"] = new JsonObject { ["full"] = "/residency/mutable.glb" }, ["anchor"] = new JsonArray(0, 0),
                    ["max_m"] = 1, ["measure"] = "xyz", ["bottom_y"] = 0 });
                return JsonDocument.Parse(scene.ToJsonString());
            }
            if (id == "held-detail") return JsonDocument.Parse("""
                {"signature":"detail","k":1,"levels":[{"level":0,"floor_y":0}],
                 "rooms":[{"room_id":"inside","level":0}],
                 "models":[{"id":"lamp","role":"prop","room_id":"inside","level":0,
                  "variants":{"full":"/residency/detail.glb"},"anchor":[0,0],"bottom_y":0,"max_m":1,"measure":"xyz",
                  "light":{"type":"point","color":"#ffffff","intensity":1,"range_m":3}}]}
                """);
            return await fixture.GetLocationSceneAsync(id);
        }
        public async Task<byte[]> GetBytesAsync(string url)
        {
            if (url == "/residency/mutable.glb") { MutableRequested = true; await _mutable.Task; return await fixture.GetBytesAsync("/assets/doors/s3c0001/model?tier=full"); }
            if (url == "/residency/detail.glb") { DetailRequested = true; await _detail.Task; return await fixture.GetBytesAsync("/assets/doors/s3c0001/model?tier=full"); }
            return await fixture.GetBytesAsync(url);
        }
        public Task<JsonDocument> GetWorldMapAsync() => fixture.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightfieldAsync() => fixture.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => fixture.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync() => fixture.GetLocations3dAsync();
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => fixture.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => fixture.GetAnimationClipsAsync();
        public Task<JsonDocument> GetTerrainAsync() => fixture.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys) => fixture.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync() => fixture.GetSurfaceTexturesAsync();
    }
    private static void Need(string label, bool ok) { if (!ok) throw new InvalidOperationException(label); }
}
