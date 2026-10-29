using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 64: actual library imports, two template builds and lazy fits over restart, compared with an
/// independent cache-free fit. Only Mia's set contains the chair bridge, so changing it must fit exactly one user.
/// Every invocation owns transport state and its disk tree, including under --cache-dir.</summary>
internal static class FigureCacheCheck
{
    private sealed class Transport(FixtureSource source) : HttpMessageHandler
    {
        public readonly Dictionary<string, string> Aliases = new();
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            string url = request.RequestUri!.PathAndQuery;
            var response = new HttpResponseMessage(HttpStatusCode.OK);
            response.Headers.TryAddWithoutValidation("ETag", "\"" + url.GetHashCode().ToString("x") + "\"");
            response.Headers.TryAddWithoutValidation("Cache-Control", "public, max-age=86400");
            response.Content = new ByteArrayContent(await source.GetBytesAsync(Aliases.GetValueOrDefault(url, url)));
            return response;
        }
    }
    private sealed class Source(FixtureSource other, Func<string, Task<byte[]>> download) : IWorldSource
    {
        public bool ChangedClip, ChangedModel;
        public Task<byte[]> GetBytesAsync(string url) => download(url);
        public Task<JsonDocument> GetWorldMapAsync() => other.GetWorldMapAsync();
        public Task<JsonDocument> GetHeightfieldAsync() => other.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys) => other.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys) => other.GetHeightTileStatsAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync() => other.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id) => other.GetLocationSceneAsync(id);
        public Task<JsonDocument> GetTerrainAsync() => other.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys) => other.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync() => other.GetSurfaceTexturesAsync();
        public async Task<JsonDocument?> GetCharacterModelAsync(string name)
        {
            using var doc = await other.GetCharacterModelAsync(name);
            if (doc is null) return null;
            var root = JsonNode.Parse(doc.RootElement.GetRawText())!;
            if (ChangedModel && name == "Mia Chair") root["model"]!["url"] = ModelNew;
            return JsonDocument.Parse(root.ToJsonString());
        }
        public async Task<JsonDocument> GetAnimationClipsAsync()
        {
            using var doc = await other.GetAnimationClipsAsync();
            var root = JsonNode.Parse(doc.RootElement.GetRawText())!;
            foreach (var clip in root["clips"]!.AsArray())
                if (clip!["kind"]!.GetValue<string>() == "get-up-chair")
                {
                    clip["set"] = "chair";
                    if (ChangedClip) clip["url"] = ClipNew;
                }
            return JsonDocument.Parse(root.ToJsonString());
        }
    }
    private const string ClipOld = "/assets/animation-clips/get-up-chair.fbx?v=bridgegetupchair";
    private const string ClipNew = "/assets/animation-clips/get-up-chair.fbx?v=changed-chair";
    private const string ModelOld = "/characters/Mia%20Chair/model3d/file?v=bridgemia0001";
    private const string ModelNew = "/characters/Mia%20Chair/model3d/file?v=changed-mia";

    public static async Task RunAsync(Node3D host, string fixtures, string root, Action<bool, string> expect)
    {
        string dir = Path.Combine(fixtures, "bridges");
        var origin = new Uri("https://figure.fixture.test");
        var raw = new FixtureSource(dir, fixtures);
        var transport = new Transport(raw);
        transport.Aliases[ClipNew] = "/assets/animation-clips/get-up-bed.fbx?v=bridgegetupbed";
        transport.Aliases[ModelNew] = ModelOld;
        var world = new Node3D(); host.AddChild(world);
        var builder = new WorldBuilder(raw, _ => { }, strict: true);
        var managers = new List<FigureManager>();
        using var doc = await raw.GetWorldMapAsync();
        var mapNode = JsonNode.Parse(doc.RootElement.GetRawText())!;
        mapNode["characters"]![0]!["animation_sets"] = new JsonArray("chair");
        using var map = JsonDocument.Parse(mapNode.ToJsonString());
        try
        {
            await builder.BuildAsync(world, "Hall");
            async Task<(FigureManager Manager, FigureCache? Cache)> Boot(bool persist, bool changedClip = false, bool changedModel = false, bool synchronous = false, string? separateRoot = null)
            {
                var disk = persist ? new DiskCache(separateRoot ?? root, origin) : null;
                // API must remain alive until all lazy fits finish. The transport owns no external resources.
                using var api = new AnimaApi(origin.ToString(), transport, disk);
                var source = new Source(raw, persist ? api.GetBytesAsync : raw.GetBytesAsync)
                    { ChangedClip = changedClip, ChangedModel = changedModel };
                var cache = disk is not null ? new FigureCache(disk) : null;
                var mgr = new FigureManager(source, builder.Height!, _ => { }, strict: true, cache)
                    { AutoTick = false, ClipFit = synchronous ? ClipFitMode.OnDemandSync : ClipFitMode.Lazy };
                world.AddChild(mgr); managers.Add(mgr);
                await mgr.InitAsync();
                await mgr.Apply(map.RootElement);
                if (synchronous)
                {
                    var clips = mgr.ClipsOf("Mia Chair")!;
                    expect(!clips.Library.HasAnimation("get-up-chair"), "sync probe starts with an unfitted bridge");
                    expect(clips.Request("get-up-chair") && clips.Library.HasAnimation("get-up-chair"),
                        "OnDemandSync bridge is ready in the requesting call");
                }
                foreach (var name in mgr.Figures.Keys)
                    if (mgr.ClipsOf(name) is { } clips) await clips.EnsureAllAsync();
                expect(mgr.Clips.ClipsLoaded == 7 && mgr.Figures.Values.All(f => mgr.ClipsOf(f.CharacterName) is not null), "all fixture figures have library plans");
                GD.Print(cache?.Describe() ?? "figures cache: fresh reference");
                return (mgr, cache);
            }
            var cold = await Boot(true);
            expect(cold.Cache!.Imports == 8 && cold.Cache.Plans == 2 && cold.Cache.Fits == 11, "cold: rig + seven imports, two plans, eleven library fits (embedded takes win)");
            var warm = await Boot(true);
            expect(warm.Cache!.Imports == 0 && warm.Cache.Plans == 0 && warm.Cache.Fits == 0, "warm: zero FBX imports, plan computations and fits");
            expect(warm.Cache.ImportedHits == 8 && warm.Cache.PlanHits == 2 && warm.Cache.FitHits == 11, "warm entries came from disk");
            var sync = await Boot(true, synchronous: true);
            expect(sync.Cache!.Imports == 0 && sync.Cache.Plans == 0 && sync.Cache.Fits == 0,
                "synchronous warm mode reuses every import, plan and fit");
            var syncCold = await Boot(true, synchronous: true, separateRoot: Path.Combine(root, "sync-cold"));
            expect(syncCold.Cache!.Fits == 11, "synchronous cache misses fit and persist in the requesting call");
            var fresh = await Boot(false);
            int actions = 0, tracks = 0; long keys = 0;
            foreach (string name in warm.Manager.Figures.Keys)
            {
                var a = warm.Manager.ClipsOf(name)!; var b = fresh.Manager.ClipsOf(name)!;
                expect(a.Actions.SequenceEqual(b.Actions) && a.PlannedClips == b.PlannedClips && a.PlannedTracks == b.PlannedTracks
                    && a.PlannedKeys == b.PlannedKeys, "cached and fresh plan totals/action order equal");
                foreach (string action in a.Actions)
                {
                    var x = a.Library.GetAnimation(action); var y = b.Library.GetAnimation(action);
                    expect(a.Digests[x] == b.Digests[y], "cached BoundClip.Digest equals a fresh fit bit for bit");
                    expect(ClipFitCheck.SameKeys(x, y, out var why, ref tracks, ref keys), "cached final keys equal fresh: " + why);
                    expect((a.Extras.TryGetValue(x, out var ex) ? ClipFitCheck.Bits(ex) : "none")
                        == (b.Extras.TryGetValue(y, out var ey) ? ClipFitCheck.Bits(ey) : "none"), "cached bridge/ground extras equal fresh bits");
                    actions++;
                }
            }
            string[] KeysOf(string prefix)
            {
                using var index = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(warm.Cache.Disk.DirectoryPath, "index.json")));
                return index.RootElement.GetProperty("entries").EnumerateArray().Select(e => e.GetProperty("key").GetString()!)
                    .Where(k => k.StartsWith(prefix, StringComparison.Ordinal)).ToArray();
            }
            // Physical same-length corruption is rejected before ResourceLoader sees any damaged bytes.
            var imported = warm.Manager.Clips.Clip("get-up-chair", "chair")!;
            string importKey = warm.Cache.ImportKey(imported.Url, imported.CacheIdentity!);
            var entry = warm.Cache.Disk.Read(importKey + ":res")!.Value.Entry;
            string file = Path.Combine(warm.Cache.Disk.DirectoryPath, entry.File);
            var damaged = File.ReadAllBytes(file); damaged[damaged.Length / 2] ^= 0x40; File.WriteAllBytes(file, damaged);
            var repaired = await Boot(true);
            expect(repaired.Cache!.Imports == 1 && repaired.Cache.Plans == 0 && repaired.Cache.Fits == 0,
                "corrupt imported resource reimports only that clip and reuses unchanged plans/fits");
            // A valid JSON sidecar with a stale extraction version is still a miss.
            var sidecar = JsonNode.Parse(repaired.Cache.Disk.Read(importKey + ":json")!.Value.Body)!;
            sidecar["Data"]!["ImportVersion"] = 0;
            await repaired.Cache.WriteJson(importKey + ":json", sidecar);
            var oldImport = await Boot(true);
            expect(oldImport.Cache!.Imports == 1 && oldImport.Cache.Fits == 0, "old import-code sidecar is a miss");
            // An old fit/plan version under a current key also cannot be resurrected.
            string planKey = KeysOf("derived:plan:")[0];
            var planData = await oldImport.Cache!.ReadJson<TemplateClips.PlanData>(planKey);
            await oldImport.Cache.WriteJson(planKey, planData! with { FitVersion = 0 });
            string fitKey = KeysOf("derived:fit:").First(k => k.EndsWith(":json", StringComparison.Ordinal));
            var fitData = JsonNode.Parse(oldImport.Cache.Disk.Read(fitKey)!.Value.Body)!;
            fitData["Data"]!["FitVersion"] = 0;
            await oldImport.Cache.WriteJson(fitKey, fitData);
            var oldFit = await Boot(true);
            expect(oldFit.Cache!.Imports == 0 && oldFit.Cache.Plans == 1 && oldFit.Cache.Fits == 1,
                "old fit-code sidecars recompute exactly one plan and fit");
            string resourceKey = fitKey[..^5] + ":res";
            entry = oldFit.Cache.Disk.Read(resourceKey)!.Value.Entry;
            file = Path.Combine(oldFit.Cache.Disk.DirectoryPath, entry.File);
            damaged = File.ReadAllBytes(file); damaged[damaged.Length / 2] ^= 0x40; File.WriteAllBytes(file, damaged);
            var corruptFit = await Boot(true);
            expect(corruptFit.Cache!.Imports == 0 && corruptFit.Cache.Plans == 0 && corruptFit.Cache.Fits == 1,
                "corrupt fitted resource refits only that clip");
            var incomplete = JsonNode.Parse(corruptFit.Cache!.Disk.Read(planKey)!.Value.Body)!;
            incomplete.AsObject().Remove("Bindings");
            await corruptFit.Cache.WriteJson(planKey, incomplete);
            var incompletePlan = await Boot(true);
            expect(incompletePlan.Cache!.Plans == 1 && incompletePlan.Cache.Fits == 0,
                "a plan without persisted action bindings is a miss, with unchanged fits retained");
            var changed = await Boot(true, changedClip: true);
            expect(changed.Cache!.Imports == 1 && changed.Cache.Plans == 1 && changed.Cache.Fits == 1,
                "changed chair clip imports/plans/fits only Mia; every other fit is reused");
            var model = await Boot(true, changedModel: true);
            expect(model.Cache!.Imports == 0 && model.Cache.Plans == 1 && model.Cache.Fits == 7,
                "changed Mia model v plans one template and fits its seven library clips only");
            GD.Print($"cache figures proof: boot1 import/plan/fit=8/2/11 boot2=0/0/0 BoundClip digests/actions={actions} tracks={tracks} keys={keys} changed_clip=1/1/1 changed_model=0/1/7");
        }
        finally { foreach (var manager in managers) manager.Free(); builder.Models?.FreeAll(); world.Free(); }
    }
}
