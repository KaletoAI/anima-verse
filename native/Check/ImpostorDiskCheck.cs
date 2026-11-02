using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Cache;
using AnimaNative.Gltf;
using AnimaNative.Scatter;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 91: finished mip chains survive a process/store restart; identity and cache ownership matter.</summary>
public static class ImpostorDiskCheck
{
    public static async Task RunAsync(Node host, FixtureSource source)
    {
        void Need(bool ok, string what) { if (!ok) throw new InvalidOperationException("impostor disk: " + what); }
        string root = Path.Combine(Path.GetTempPath(), "anima-impostors-" + Guid.NewGuid().ToString("N"));
        var origin = new Uri("https://fixture.test");
        const string url = "/assets/props/tree/model.glb?tier=low&v=one";
        var frame = new ImpostorFrame(1.25, 0.75);
        byte[] pixels;
        using (var image = Image.CreateEmpty(128, 128, false, Image.Format.Rgba8))
        {
            image.Fill(new Color(0.25f, 0.5f, 0.75f, 0.5f)); image.GenerateMipmaps(); pixels = image.GetData();
        }
        var data = new ImpostorPixels(128, frame, pixels);
        try
        {
            using (var stop = new CancellationTokenSource())
            {
                var drawing = ImpostorBaker.WaitForDrawAsync(stop.Token);
                stop.Cancel();
                bool cancelled = false;
                try { await drawing; } catch (OperationCanceledException) { cancelled = true; }
                Need(cancelled, "closing a baker cancels its wait for a rendered frame");
            }
            using (var store = new DiskCache(root, origin))
            {
                var cache = new ImpostorDiskCache(store);
                Need(cache.Read(url, 128) is null, "cold miss");
                cache.Store(url, data);
                cache.Store("/assets/props/old.glb", data);
                Need(store.Count == 1, "unversioned URLs never persist without response identity");
            }
            using (var store = new DiskCache(root, origin))
            {
                var cache = new ImpostorDiskCache(store);
                var hit = cache.Read(url, 128);
                Need(hit is not null && hit.Frame == frame && hit.RgbaMips.SequenceEqual(pixels), "RGBA8 + all mips + frame roundtrip");
                Need(pixels.Length == 87380, "128-square RGBA8 full mip chain = 87380 bytes");
                Need(cache.Read(url.Replace("v=one", "v=two"), 128) is null, "changed content version misses");
                Need(cache.Read(url, 64) is null, "changed texture size misses");
                Need(new ImpostorDiskCache(store, ImpostorDiskCache.BakeCodeVersion + 1).Read(url, 128) is null, "changed bake code misses");
                var fixture = new FixtureSource(source.Dir);
                var baker = new ImpostorBaker(fixture, _ => { }, store); host.AddChild(baker);
                Need(baker.Acquire(url) is null, "disk lookup yields without blocking Acquire");
                var deadline = Stopwatch.StartNew();
                while (baker.PendingCount > 0 && deadline.Elapsed.TotalSeconds < 5)
                    await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                Need(baker.PendingCount == 0, "disk lookup completes");
                var baked = baker.Acquire(url);
                Need(baked is not null && baked.Frame == frame && fixture.ByteRequests.Count == 0,
                    "disk hit serves actual baker with zero GLB downloads/render/readback, including dummy renderer");
                baker.Release(url); baker.Free();
                // Structurally invalid data must miss even if the byte store's digest is valid.
                var entry = store.Read(ImpostorDiskCache.Key(url, 128)!)!.Value.Entry;
                store.Store(entry.Key, new byte[] { 1, 2, 3 }, null, new HttpCachePolicy(true, true, store.Now, "immutable"));
                Need(cache.Read(url, 128) is null, "bad bake payload is a miss");
                store.RequestClear();
            }
            Need(DiskCache.PrepareRoot(root), "shared clear succeeds");
            using (var store = new DiskCache(root, origin)) Need(new ImpostorDiskCache(store).Read(url, 128) is null, "shared clear removes bakes");
            using (var tiny = new DiskCache(Path.Combine(root, "tiny"), origin, pixels.Length - 1))
            {
                new ImpostorDiskCache(tiny).Store(url, data);
                Need(tiny.Count == 0, "shared disk limit applies");
            }
            var clock = DateTimeOffset.Parse("2026-11-02T00:00:00Z");
            using (var lru = new DiskCache(Path.Combine(root, "lru"), origin, 2 * (pixels.Length + 28), now: () => clock))
            {
                var cache = new ImpostorDiskCache(lru);
                string second = url.Replace("v=one", "v=two"), third = url.Replace("v=one", "v=three");
                cache.Store(url, data); clock = clock.AddSeconds(1);
                cache.Store(second, data); clock = clock.AddSeconds(1);
                cache.Read(url, 128); clock = clock.AddSeconds(1);
                cache.Store(third, data);
                Need(cache.Read(url, 128) is not null && cache.Read(second, 128) is null && cache.Read(third, 128) is not null,
                    "disk hit touches shared LRU; least-recent bake evicted");
            }
            await CheckRenderedPixels(host, source, root, origin);
            GD.Print("[check] impostor disk: rgba+mips=87380 frame=exact restart=hit downloads/render/readback=0 v/size/code=miss clear/limit/LRU=pass");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task CheckRenderedPixels(Node host, FixtureSource source, string root, Uri origin)
    {
        if (RenderingServer.GetRenderingDevice() is null)
        {
            GD.Print("[check] impostor GPU: SKIP pixel equality/readback timing/cold v rebake (no RenderingDevice); rerun --check scatter with a Vulkan display");
            return;
        }
        void Need(bool ok, string what) { if (!ok) throw new InvalidOperationException("impostor GPU: " + what); }
        const string fixtureUrl = "/assets/props/broadleaf/model.glb?tier=low";
        var bytes = await source.GetBytesAsync(fixtureUrl);
        var parsed = GlbLoader.Parse(GlbLoader.Prepare(bytes), fixtureUrl);
        using var doc = parsed.Doc; using var state = parsed.State;
        var model = GlbLoader.Generate(doc, state, fixtureUrl);
        SubViewport? viewport = null;
        try
        {
            var setup = ImpostorBaker.CreateBakeViewport(model) ?? throw new InvalidOperationException("fixture bake has no frame");
            viewport = setup.Viewport; host.AddChild(viewport);
            viewport.RenderTargetUpdateMode = SubViewport.UpdateMode.Once;
            await host.ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
            // Legacy reference from exactly the same rendered pixels, before any frame can change them.
            using var legacy = viewport.GetTexture().GetImage();
            legacy.Convert(Image.Format.Rgba8); legacy.GenerateMipmaps();
            byte[] reference = legacy.GetData();
            Need(reference.Where((_, i) => i < 128 * 128 * 4 && i % 4 == 3).Any(a => a > 0), "fixture is not an empty transparent frame");
            // Warm the callable/JIT; measure the next request without including asynchronous wait time.
            await ImpostorBaker.ReadPixelsAsync(viewport.GetTexture(), 128).WaitAsync(TimeSpan.FromSeconds(15));
            long started = Stopwatch.GetTimestamp();
            var read = ImpostorBaker.ReadPixelsAsync(viewport.GetTexture(), 128);
            double requestMs = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
            Need(!read.IsCompleted, "GPU completion is asynchronous");
            var actual = await Task.Run(async () => ImpostorBaker.FinishPixels(await read, setup.Frame)).WaitAsync(TimeSpan.FromSeconds(15));
            Need(actual.RgbaMips.SequenceEqual(reference), "async pixels and all generated mips equal legacy GetImage bit for bit");
            Need(requestMs < 5, $"main-thread readback request {requestMs:0.###} ms exceeds 5 ms");
            GD.Print(FormattableString.Invariant($"[check] impostor GPU: fixture RGBA8+mips=bit-exact main_request={requestMs:0.###} ms"));
        }
        finally { if (viewport is not null) viewport.Free(); model.Free(); }

        int downloads = 0;
        var sourceWithVersions = new FixtureSource(source.Dir) { ByteDownload = _ => { downloads++; return Task.FromResult(bytes); } };
        string cacheRoot = Path.Combine(root, "rendered");
        const string url = fixtureUrl + "&v=first";
        using (var disk = new DiskCache(cacheRoot, origin))
        {
            var baker = new ImpostorBaker(sourceWithVersions, GD.Print, disk); host.AddChild(baker);
            try
            {
                await baker.BakeAndStoreAsync(url).WaitAsync(TimeSpan.FromSeconds(15));
                Need(baker.CachedCount == 1 && downloads == 1 && new ImpostorDiskCache(disk).Read(url, 128) is not null, "cold miss renders and persists");
            }
            finally { baker.Free(); }
        }
        using (var disk = new DiskCache(cacheRoot, origin))
        {
            var baker = new ImpostorBaker(sourceWithVersions, GD.Print, disk); host.AddChild(baker);
            try
            {
                await baker.BakeAndStoreAsync(url).WaitAsync(TimeSpan.FromSeconds(15));
                Need(baker.CachedCount == 1 && downloads == 1, "second baker uses disk without download/render/readback");
                string changed = url.Replace("v=first", "v=second");
                await baker.BakeAndStoreAsync(changed).WaitAsync(TimeSpan.FromSeconds(15));
                Need(baker.CachedCount == 2 && downloads == 2 && new ImpostorDiskCache(disk).Read(changed, 128) is not null, "changed v actually rebakes");
            }
            finally { baker.Free(); }
        }
        GD.Print("[check] impostor GPU: cold=1 restart=0 changed-v=1 render/readback, persisted=2");
    }
}
