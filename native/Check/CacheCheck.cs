using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using AnimaNative.Sync;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 62 / E10-T1: two actual fixture world builds with the production byte cache and HTTP
/// path. A fixture transport supplies inventory §2.1 validators; all other checks stay cache-free.
/// Every run owns a temporary subtree, also when --cache-dir selects its parent.</summary>
public static class CacheCheck
{
    private sealed class Transport(FixtureSource source, JsonCacheCheck json) : HttpMessageHandler
    {
        private readonly HashSet<string> _known = JsonSerializer.Deserialize<Dictionary<string, string>>(
            File.ReadAllText(Path.Combine(source.Dir, "urls.json")))!.Keys.ToHashSet(StringComparer.Ordinal);
        public int Bodies, Revalidations;
        public string? Changed;
        public readonly Dictionary<string, string> Aliases = new();
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage req, CancellationToken ct)
        {
            string key = req.RequestUri!.PathAndQuery;
            if (!_known.Contains(Aliases.GetValueOrDefault(key, key))) return await json.AnswerAsync(req);
            string etag = key == Changed ? "\"changed\"" : "\"fixture\"";
            bool same = req.Headers.IfNoneMatch.Any(e => e.ToString() == etag);
            var res = new HttpResponseMessage(same ? HttpStatusCode.NotModified : HttpStatusCode.OK);
            res.Headers.TryAddWithoutValidation("ETag", etag);
            string policy = key.Contains("/model3d/", StringComparison.Ordinal) || key.Contains("/animation-clips/", StringComparison.Ordinal)
                ? "public, max-age=31536000, immutable" : key == "/assets/animation-rig" ? "public, max-age=86400"
                : key.StartsWith("/play/", StringComparison.Ordinal) || key.Contains("/images/", StringComparison.Ordinal)
                ? "no-cache" : "public, max-age=3600";
            res.Headers.TryAddWithoutValidation("Cache-Control", policy);
            if (same) Revalidations++;
            else
            {
                var bytes = await source.GetBytesAsync(Aliases.GetValueOrDefault(key, key));
                Bodies++; res.Content = new ByteArrayContent(bytes);
            }
            return res;
        }
    }

    public static async Task<string> RunAsync(Node3D host, string fixtures, string? cacheDir = null)
    {
        string root = Path.Combine(cacheDir ?? Path.GetTempPath(), "anima-cache-check-" + Guid.NewGuid().ToString("N"));
        int checks = 0;
        void Expect(bool ok, string what) { checks++; if (!ok) throw new InvalidOperationException("cache: " + what); }
        var origin = new Uri("https://fixture.test");
        var raw = new FixtureSource(fixtures);
        var urls = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(fixtures, "urls.json")))!.Keys.ToArray();
        var json = new JsonCacheCheck(raw);
        var transport = new Transport(raw, json);
        try
        {
            int[] bodies = new int[2], revalidations = new int[2];
            int[] jsonBodies = new int[2], jsonRequests = new int[2], scene304 = new int[2];
            for (int boot = 0; boot < 2; boot++)
            {
                using var api = new AnimaApi(origin.ToString(), transport, new DiskCache(root, origin));
                var source = new JsonCacheCheck.Source(api, new FixtureSource(fixtures));
                json.Epoch = "boot" + (boot + 1);
                int jsonBefore = json.Bodies("tiles") + json.Bodies("masks") + json.Bodies("terrain");
                int requestsBefore = json.Requests("tiles") + json.Requests("masks") + json.Requests("terrain");
                int conditionalBefore = json.Scene304;
                var world = new Node3D(); host.AddChild(world);
                var builder = new WorldBuilder(source, _ => { }, strict: true);
                int before = transport.Bodies, conditional = transport.Revalidations;
                try
                {
                    var stats = await builder.BuildAsync(world, "harbour");
                    Expect(stats.Buildings == 1, "real world building count");
                    foreach (var url in urls)
                    {
                        var bytes = await api.GetBytesAsync(url);
                        Expect(bytes.Length > 0, "fixture body is present");
                    }
                    bodies[boot] = transport.Bodies - before;
                    revalidations[boot] = transport.Revalidations - conditional;
                    jsonBodies[boot] = json.Bodies("tiles") + json.Bodies("masks") + json.Bodies("terrain") - jsonBefore;
                    jsonRequests[boot] = json.Requests("tiles") + json.Requests("masks") + json.Requests("terrain") - requestsBefore;
                    scene304[boot] = json.Scene304 - conditionalBefore;
                }
                finally { builder.Models?.FreeAll(); world.Free(); }
            }
            Expect(bodies[0] == urls.Length, "cold boot fetches N fixture bodies");
            Expect(bodies[1] == 0, "warm boot fetches zero bodies");
            Expect(revalidations[1] > 0, "warm no-cache bodies revalidate");
            Expect(raw.ByteRequests.Count == urls.Length, "ByteRequests counts bodies only");
            Expect(jsonBodies[0] > 0 && jsonRequests[0] == jsonBodies[0], "cold world build downloads terrain JSON");
            Expect(jsonRequests[1] == 0, "warm world build makes zero tile/mask/terrain requests");
            Expect(json.Bodies("scenes") > 0 && scene304[1] == json.Bodies("scenes"), "warm scenes all revalidate with 304");
            await json.ProveChanges(root, origin, transport, Expect);
            var store = new DiskCache(root, origin);
            using var next = new AnimaApi(origin.ToString(), transport, store);
            string model = urls.Single(u => u.StartsWith("/play/locations/", StringComparison.Ordinal));
            transport.Changed = model;
            int start = transport.Bodies;
            await next.GetBytesAsync(model);
            Expect(transport.Bodies - start == 1, "changed ETag fetches exactly one body");
            string clip = urls.First(u => u.StartsWith("/assets/animation-clips/", StringComparison.Ordinal));
            string version = clip.Split('?')[0] + "?v=new";
            transport.Aliases[version] = clip;
            start = transport.Bodies;
            await next.GetBytesAsync(version);
            Expect(transport.Bodies - start == 1, "changed v fetches exactly one body");
            var entry = store.Read(clip)!.Value.Entry;
            File.WriteAllBytes(Path.Combine(store.DirectoryPath, entry.File), new byte[] { 0 });
            start = transport.Bodies;
            await next.GetBytesAsync(clip);
            Expect(transport.Bodies - start == 1, "corrupt entry refetches");

            var now = DateTimeOffset.Parse("2026-10-29T00:00:00Z");
            string tinyRoot = Path.Combine(root, "tiny");
            var tiny = new DiskCache(tinyRoot, origin, 8, now: () => now);
            var immutable = new HttpCachePolicy(true, true, now, "immutable");
            tiny.Store("/a", new byte[4], "\"a\"", immutable); now = now.AddSeconds(1);
            tiny.Store("/b", new byte[4], "\"b\"", immutable); now = now.AddSeconds(1);
            tiny.Read("/a"); now = now.AddSeconds(1);
            tiny.Store("/c", new byte[4], "\"c\"", immutable);
            Expect(tiny.Read("/b") is null && tiny.Read("/a") is not null && tiny.Bytes == 8, "LRU evicts b after touching a");
            Expect(new DiskCache(tinyRoot, origin, 4).Bytes == 4, "startup eviction");
            string old = store.DirectoryPath;
            var bumped = new DiskCache(root, origin, formatVersion: DiskCache.FormatVersion + 1);
            Expect(!Directory.Exists(old) && bumped.Count == 0, "format bump discards old tree");
            GD.Print($"cache proof: boot1 bodies={bodies[0]} boot2 bodies={bodies[1]} boot2 304={revalidations[1]} ETag=1 v=1 corrupt=1 LRU=8->4 version=empty");
            GD.Print($"cache JSON proof: boot1 bodies={jsonBodies[0]} boot2 requests={jsonRequests[1]} scene304={scene304[1]}");
            return $"cache checks={checks} boot1={bodies[0]} boot2={bodies[1]} JSON_boot2={jsonRequests[1]} scene304={scene304[1]}";
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
