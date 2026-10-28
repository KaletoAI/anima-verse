using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Collections.Generic;
using AnimaNative.Api;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 40 (E4-T5): runtime parity against e4.worldProps, horizontal distance, prefs, sync and redrape.</summary>
public static class WorldPropCheck
{
    public static async Task RunAsync(Node3D world, FixtureSource source, WorldHeight height, string dir)
    {
        void Need(string label, bool ok) { if (!ok) throw new InvalidOperationException("world props: " + label); }
        using var reference = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "scatter_reference.json")));
        using var map = await source.GetWorldMapAsync();
        var cache = new ModelCache(source, _ => { });
        var layer = new WorldPropsLayer(cache, height, null, _ => { }); world.AddChild(layer);
        var camera = new Vector3(40, 9000, 110);
        try
        {
            layer.SyncWorldMap(map.RootElement);
            await layer.TickAsync(camera);
            var expected = reference.RootElement.GetProperty("e4").GetProperty("worldProps");
            foreach (var e in expected.EnumerateArray())
            {
                var r = layer.Records[e.GetProperty("id").GetString()!];
                Need("fixture tier " + r.Id, r.Tier == e.GetProperty("tier").GetByte());
                Need("horizontal distance " + r.Id, Math.Abs(r.Distance - e.GetProperty("distance").GetDouble()) < 1e-9);
                Need("fixture bottom " + r.Id, Math.Abs(r.Spec.BottomY - e.GetProperty("spec").GetProperty("bottom_y").GetDouble()) < 1e-6);
            }
            var near = layer.Records["wp-fixture-near"];
            Need("near full mounted", near.Node is not null && near.ShownUrl.EndsWith("tier=full"));
            Need("culled record retained without a mount", layer.Records["wp-fixture-culled"].Node is null);
            var standing = near.Node;
            layer.SyncWorldMap(map.RootElement);
            Need("unchanged sig preserves node", near.Node == standing);
            var field = new ScatterField(source, height, _ => { }); world.AddChild(field);
            field.Tick(64, 0, 98, 0, 1, 60, 1);
            using var terrain = await source.GetTerrainAsync();
            field.SetTerrain(TerrainPayload.Parse(terrain.RootElement), Array.Empty<P2[]>(), inline: true);
            ScatterDetail.Apply(new ScatterLodCfg(5, 8, 10), field, layer);
            await layer.WhenIdleAsync();
            Need("one prefs change retiers both layers", field.Lod.CullM == 10 && field.Props.All(p => p.HighN == 0)
                && layer.Lod.CullM == 30 && near.Tier == 1 && layer.Records["wp-fixture-far"].Tier == 2);
            field.Free();
            layer.SetLod(ScatterLod.Defaults);
            await layer.TickAsync(new Vector3(564, 9000, 128));
            Need("previously culled appears", layer.Records["wp-fixture-culled"] is { Tier: 0, Node: not null });
            await layer.TickAsync(new Vector3(764, 9000, 128));
            Need("full swaps to low", layer.Records["wp-fixture-culled"].ShownUrl.EndsWith("tier=low"));
            await layer.TickAsync(new Vector3(1200, 0, 128));
            Need("tier 2 hides existing node", !layer.Records["wp-fixture-culled"].Node!.Visible);
            await Lifecycle(world, source, map.RootElement);
            await LatestWish(world, source, height, map.RootElement);
            GD.Print("[check] world-props: tiers=0/1/2 distances=30/224.72205054244233/524.3090691567331 prefs=both appear/swap/hide=pass sync/redrape/water/light/stale=pass");
        }
        finally { layer.Free(); cache.FreeAll(); }
    }
    /// <summary>Task 40: fixture-only mutations prove translation keeps the node, shape rebuilds it, sheets
    /// follow tiers, lamps survive culling, and height revisions move the bottom and source without a reload.</summary>
    private static async Task Lifecycle(Node3D world, FixtureSource source, JsonElement fixture)
    {
        void Need(string label, bool ok) { if (!ok) throw new InvalidOperationException("world props lifecycle: " + label); }
        using var flat = JsonDocument.Parse("""{"heights":[[0,0],[0,0]],"step_m":1024}""");
        var height = new WorldHeight(HeightfieldOverview.Parse(flat.RootElement));
        var cache = new ModelCache(source, _ => { });
        var pool = new PropLightPool(); world.AddChild(pool);
        var layer = new WorldPropsLayer(cache, height, pool, _ => { }); world.AddChild(layer);
        var row = JsonNode.Parse(fixture.GetProperty("world_props")[0].GetRawText())!.AsObject();
        row["x"] = 0; row["z"] = 0; row["offset_y"] = 0.5; row["ground_offset_m"] = -0.2;
        row["light"] = JsonNode.Parse("""{"color":"#ffffff","intensity":2,"range_m":10,"height_m":2,"offset_m":[1,2]}""");
        row["water"] = JsonNode.Parse("""{"regions":[{"outline":[[0,0],[2,0],[2,2],[0,2]],"y":1,"opacity":0.5,"tint":"#337799"}]}""");
        int revision = 0;
        void Sync() => layer.SyncWorldMap(JsonSerializer.SerializeToElement(new JsonObject {
            ["world_props_sig"] = "lifecycle-" + revision++, ["world_props"] = new JsonArray(row.DeepClone()) }));
        try
        {
            Sync(); await layer.TickAsync(Vector3.Zero);
            var r = layer.Records.Values.Single();
            var node = r.Node!;
            string lightId = r.LightId!;
            Need("sheet mounted independent of model", r.Sheets.Count == 1 && r.Sheets[0].Visible && pool.State.Count == 1);
            row["x"] = 2; row["z"] = 3; Sync();
            Need("translation retains mesh and lamp", r.Node == node && r.Node.Position.X == 2 && r.Node.Position.Z == 3 && r.LightId == lightId);
            using var raised = JsonDocument.Parse("""{"heights":[[8,8],[8,8]],"step_m":1024}""");
            height.Reset(HeightfieldOverview.Parse(raised.RootElement)); layer.Redrape();
            Need("redrape keeps model and seats its measured bottom", r.Node == node
                && Math.Abs(ModelPlacement.Measure(node, Transform3D.Identity).Position.Y - 8.3) < 1e-4);
            Need("sheet and light relift", Math.Abs(r.Sheets[0].Position.Y - 9) < 1e-6
                && Math.Abs(pool.State.PositionOf(lightId)!.Value.Y - 10.3) < 1e-5);
            await layer.TickAsync(new Vector3(1000, 0, 0));
            Need("cull hides water and mesh, keeps registered light", r.Tier == 2 && !r.Sheets[0].Visible && !node.Visible
                && r.LightId == lightId && pool.State.Count == 1);
            await layer.TickAsync(Vector3.Zero);
            Need("unhide restores sheet and mesh", node.Visible && r.Sheets[0].Visible);
            row["max_m"] = 6; Sync(); await layer.TickAsync(Vector3.Zero);
            Need("shape replaces mesh", r.Node != node && r.Spec.MaxM == 6 && r.LightId == lightId);
            row.Remove("water"); row.Remove("light"); Sync();
            Need("removed attributes release owned effects", r.Sheets.Count == 0 && pool.State.Count == 0);
            layer.SyncWorldMap(JsonSerializer.SerializeToElement(new JsonObject { ["world_props_sig"] = "empty", ["world_props"] = new JsonArray() }));
            Need("removed id releases node and record", layer.Records.Count == 0 && r.Disposed && r.Node is null);
        }
        finally { layer.Free(); pool.Free(); cache.FreeAll(); }
    }

    /// <summary>Task 40: hold real fixture GLB bytes at the I/O boundary to force a low request to finish after
    /// the camera returned to the shown full URL; then remove/re-add an id while its first mount is in flight.</summary>
    private static async Task LatestWish(Node3D world, FixtureSource source, WorldHeight height, JsonElement map)
    {
        void Need(string label, bool ok) { if (!ok) throw new InvalidOperationException("world props stale: " + label); }
        var row = map.GetProperty("world_props")[0];
        var one = JsonSerializer.SerializeToElement(new { world_props_sig = "one", world_props = new[] { row } });
        foreach (bool remove in new[] { false, true })
        {
            var delayed = new DelayedModels(source, row.GetProperty("variants").GetProperty(remove ? "full" : "low").GetString()!);
            var cache = new ModelCache(delayed, _ => { });
            var layer = new WorldPropsLayer(cache, height, null, _ => { }); world.AddChild(layer);
            try
            {
                layer.SyncWorldMap(one);
                if (!remove) await layer.TickAsync(new Vector3(64, 0, 128));
                var old = layer.Records.Values.Single(); var node = old.Node;
                var pending = layer.TickAsync(new Vector3(remove ? 64 : 264, 0, 128));
                Need("fixture request held", delayed.Requested && !pending.IsCompleted);
                if (remove)
                {
                    layer.SyncWorldMap(JsonSerializer.SerializeToElement(new { world_props_sig = "empty", world_props = Array.Empty<object>() }));
                    layer.SyncWorldMap(one);
                    _ = layer.TickAsync(new Vector3(64, 0, 128));
                }
                else _ = layer.TickAsync(new Vector3(64, 0, 128));
                delayed.Release(); await pending; await layer.WhenIdleAsync();
                var current = layer.Records.Values.Single();
                Need("latest wish installs full only", current.Node is not null && current.ShownUrl.EndsWith("tier=full"));
                Need("record identity protects remove/readd; shown URL cancels stale low", remove
                    ? old.Disposed && old.Node is null && current != old
                    : current.Node == node && current.Tier == 0);
            }
            finally { delayed.Release(); await layer.WhenIdleAsync(); layer.Free(); cache.FreeAll(); }
        }
    }

    private sealed class DelayedModels(FixtureSource source, string heldUrl) : IWorldSource
    {
        private readonly TaskCompletionSource _release = new();
        public bool Requested;
        public void Release() => _release.TrySetResult();
        public async Task<byte[]> GetBytesAsync(string url)
        {
            if (url == heldUrl) { Requested = true; await _release.Task; }
            return await source.GetBytesAsync(url);
        }
        public Task<JsonDocument> GetWorldMapAsync() => source.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightfieldAsync() => source.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => source.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync() => source.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id) => source.GetLocationSceneAsync(id);
        public Task<JsonDocument?> GetCharacterModelAsync(string name) => source.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync() => source.GetAnimationClipsAsync();
        public Task<JsonDocument> GetTerrainAsync() => source.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys) => source.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync() => source.GetSurfaceTexturesAsync();
    }

}
