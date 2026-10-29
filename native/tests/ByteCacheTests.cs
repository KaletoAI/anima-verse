using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 62 / E10-T1: real API + disk, with only the server and clock replaced; each test owns its tree.</summary>
public sealed class ByteCacheTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "anima-cache-test-" + Guid.NewGuid().ToString("N"));
    private DateTimeOffset _now = DateTimeOffset.Parse("2026-10-29T12:00:00Z");
    private DiskCache Cache(long limit = DiskCache.DefaultLimitBytes, int version = DiskCache.FormatVersion)
        => new(_root, new Uri("https://fixture.test"), limit, version, () => _now);
    public void Dispose() { if (Directory.Exists(_root)) Directory.Delete(_root, true); }

    private sealed class Server : HttpMessageHandler
    {
        public int Bodies, Requests, NotModified;
        public string Etag = "\"one\"";
        public string Policy = "no-cache";
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage r, CancellationToken ct)
        {
            Requests++;
            bool same = r.Headers.IfNoneMatch.Any(e => e.ToString() == Etag);
            var res = new HttpResponseMessage(same ? HttpStatusCode.NotModified : HttpStatusCode.OK);
            res.Headers.TryAddWithoutValidation("ETag", Etag);
            res.Headers.TryAddWithoutValidation("Cache-Control", Policy);
            res.Headers.TryAddWithoutValidation("Set-Cookie", "av_session=DO_NOT_STORE");
            if (same) NotModified++;
            else { Bodies++; res.Content = new ByteArrayContent(new byte[] { 1, 2, 3, 4 }); }
            return Task.FromResult(res);
        }
    }

    [Fact]
    public void FailedClearRetainsMarkerWithoutPreventingStartup()
    {
        if (OperatingSystem.IsWindows() || Environment.UserName == "root") return;
        var cache = Cache();
        cache.Store("body", new byte[4], null, new HttpCachePolicy(true, true, _now, "immutable"));
        cache.RequestClear();
        var original = File.GetUnixFileMode(cache.DirectoryPath);
        try
        {
            File.SetUnixFileMode(cache.DirectoryPath, UnixFileMode.UserRead | UnixFileMode.UserExecute);
            bool enabled = true;
            Assert.Null(Record.Exception(() => enabled = DiskCache.PrepareRoot(_root)));
            Assert.False(enabled);
            Assert.True(File.Exists(Path.Combine(_root, "pending_clear")));
        }
        finally { File.SetUnixFileMode(cache.DirectoryPath, original); }
    }

    [Fact]
    public async Task ClearIsDeferredAcrossReloadAndNextBootRefetchesEverything()
    {
        var server = new Server { Policy = "public, immutable" };
        var cache = Cache();
        using (var api = new AnimaApi("https://fixture.test", server, cache))
            await api.GetBytesAsync("/assets/animation-clips/a.fbx?v=a");
        string body = Path.Combine(cache.DirectoryPath, cache.Read("/assets/animation-clips/a.fbx?v=a")!.Value.Entry.File);
        cache.RequestClear(); cache.RequestClear();
        Assert.True(File.Exists(body)); Assert.Equal(0, cache.Readout.Bytes); Assert.Equal(0, cache.Readout.Entries);
        Assert.Equal(DiskCache.DefaultLimitBytes, cache.Readout.LimitBytes);
        var reload = Cache(); Assert.Equal(0, reload.Readout.Bytes); Assert.Equal(1, reload.Count);
        reload.Store("derived", new byte[3], null, new HttpCachePolicy(true, true, _now, "immutable"));
        Assert.Equal(0, reload.Readout.Bytes);
        Directory.CreateDirectory(Path.Combine(_root, "v99")); File.WriteAllText(Path.Combine(_root, "keep.txt"), "keep");
        DiskCache.PrepareRoot(_root);
        Assert.False(File.Exists(body)); Assert.False(Directory.Exists(Path.Combine(_root, "v99")));
        Assert.True(File.Exists(Path.Combine(_root, "keep.txt")));
        var cold = Cache(); Assert.Equal(0, cold.Count);
        using (var api = new AnimaApi("https://fixture.test", server, cold))
            await api.GetBytesAsync("/assets/animation-clips/a.fbx?v=a");
        Assert.Equal(2, server.Bodies); Assert.Equal(4, cold.Readout.Bytes);
        DiskCache.PrepareRoot(_root); Assert.Equal(1, Cache().Count);
        DiskCache.PrepareRoot(_root, clear: true); Assert.Equal(0, Cache().Count);
    }

    [Theory]
    [InlineData("/assets/animation-clips/a.fbx?v=one", "public, max-age=31536000, immutable", 0)]
    [InlineData("/characters/A/model3d/file?v=one", "public, max-age=31536000, immutable", 0)]
    [InlineData("/characters/A/model3d/texture?v=one", "public, immutable", 0)]
    [InlineData("/assets/props/p/model?tier=full", "public, max-age=3600", 0)]
    [InlineData("/assets/doors/p/model", "public, max-age=3600", 0)]
    [InlineData("/assets/surface-textures/a.png", "public, max-age=3600", 0)]
    [InlineData("/assets/props/p/image", "public, max-age=3600", 0)]
    [InlineData("/assets/animation-rig", "public, max-age=86400", 0)]
    [InlineData("/play/locations/p/model?tier=full", "no-cache", 1)]
    [InlineData("/play/rooms/p/model", "no-cache", 1)]
    [InlineData("/characters/A/images/p.png?transparent=1", "no-cache", 1)]
    [InlineData("/static/client3d/models/manifest.json", "no-cache", 1)]
    [InlineData("/assets/audio/music.ogg", "no-cache", 1)]
    public async Task RestartReusesBodiesByResponsePolicy(string url, string policy, int requests)
    {
        var first = new Server { Policy = policy };
        using (var api = new AnimaApi("https://fixture.test", first, Cache()))
            Assert.Equal(new byte[] { 1, 2, 3, 4 }, await api.GetBytesAsync(url));
        var second = new Server { Policy = policy };
        using (var api = new AnimaApi("https://fixture.test", second, Cache()))
            Assert.Equal(new byte[] { 1, 2, 3, 4 }, await api.GetBytesAsync(url));
        Assert.Equal(1, first.Bodies);
        Assert.Equal(0, second.Bodies);
        Assert.Equal(requests, second.Requests);
        Assert.Equal(requests, second.NotModified);
        Assert.DoesNotContain("DO_NOT_STORE", File.ReadAllText(Path.Combine(Cache().DirectoryPath, "index.json")));
    }

    [Theory]
    [InlineData("/assets/props/p/model", 3600)]
    [InlineData("/assets/doors/p/model", 3600)]
    [InlineData("/assets/surface-textures/a.png", 3600)]
    [InlineData("/assets/props/p/image", 3600)]
    [InlineData("/assets/animation-rig", 86400)]
    public async Task FreshnessExpiresAtInventoryWindow(string url, int seconds)
    {
        var server = new Server { Policy = $"public, max-age={seconds}" };
        using var api = new AnimaApi("https://fixture.test", server, Cache());
        await api.GetBytesAsync(url);
        _now = _now.AddSeconds(seconds - 1);
        await api.GetBytesAsync(url);
        Assert.Equal(1, server.Requests);
        _now = _now.AddSeconds(1);
        await api.GetBytesAsync(url);
        Assert.Equal(2, server.Requests);
        Assert.Equal(1, server.NotModified);
    }

    [Fact]
    public async Task StaleVersionNeverBecomesImmutableAndChangesRefetchOnlyOneEntry()
    {
        var server = new Server();
        using var api = new AnimaApi("https://fixture.test", server, Cache());
        string a = "/assets/animation-clips/a.fbx?v=stale", b = "/assets/animation-clips/b.fbx?v=b";
        await api.GetBytesAsync(a); await api.GetBytesAsync(b);
        await api.GetBytesAsync(a); await api.GetBytesAsync(b);
        Assert.Equal(2, server.NotModified);
        server.Etag = "\"two\"";
        await api.GetBytesAsync(a);
        Assert.Equal(3, server.Bodies);
        await api.GetBytesAsync("/assets/animation-clips/b.fbx?v=new");
        Assert.Equal(4, server.Bodies);
    }

    [Theory]
    [InlineData("/play/worldmap")]
    [InlineData("/assets/animation-clips")]
    [InlineData("/characters/A/model3d")]
    [InlineData("/play/locations/p/scene")]
    [InlineData("/play/heightfield/tiles?keys=0,0")]
    [InlineData("/play/terrain-layers?keys=0,0")]
    [InlineData("/play/terrain")]
    [InlineData("/play/tts/one")]
    [InlineData("/assets/props/p/model?password=SECRET")]
    public async Task ExcludedClassesAndCredentialsNeverPersist(string url)
    {
        var server = new Server { Policy = "public, immutable" };
        using var api = new AnimaApi("https://fixture.test", server, Cache());
        await api.GetBytesAsync(url); await api.GetBytesAsync(url);
        Assert.Equal(2, server.Bodies);
        Assert.Empty(Directory.GetFiles(Cache().DirectoryPath, "*.bin"));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CorruptOrShortBodyRefetches(bool shortFile)
    {
        var server = new Server { Policy = "public, immutable" };
        var cache = Cache();
        using var api = new AnimaApi("https://fixture.test", server, cache);
        await api.GetBytesAsync("/assets/props/p/model");
        File.WriteAllBytes(Directory.GetFiles(cache.DirectoryPath, "*.bin").Single(), shortFile ? new byte[] { 9 } : new byte[] { 9, 9, 9, 9 });
        await api.GetBytesAsync("/assets/props/p/model");
        Assert.Equal(2, server.Bodies);
    }

    [Fact]
    public async Task LruUsesReadsAndEvictsAfterWriteAndAtStart()
    {
        var server = new Server { Policy = "public, immutable" };
        var cache = Cache(8);
        using (var api = new AnimaApi("https://fixture.test", server, cache))
        {
            await api.GetBytesAsync("/assets/props/a/model"); _now = _now.AddSeconds(1);
            await api.GetBytesAsync("/assets/props/b/model"); _now = _now.AddSeconds(1);
            await api.GetBytesAsync("/assets/props/a/model"); _now = _now.AddSeconds(1);
            await api.GetBytesAsync("/assets/props/c/model");
            await api.GetBytesAsync("/assets/props/a/model");
            Assert.Equal(3, server.Bodies);
            await api.GetBytesAsync("/assets/props/b/model");
            Assert.Equal(4, server.Bodies);
        }
        Assert.Equal(8, cache.Bytes);
        Assert.Equal(4, Cache(4).Bytes);
        Assert.Single(Directory.GetFiles(cache.DirectoryPath, "*.bin"));
    }

    [Fact]
    public async Task VersionBumpDropsWholeOldTreeAndOriginsAreIsolated()
    {
        var old = Cache();
        using (var api = new AnimaApi("https://fixture.test", new Server { Policy = "immutable" }, old))
            await api.GetBytesAsync("/assets/props/p/model");
        File.WriteAllText(Path.Combine(old.DirectoryPath, "orphan"), "old");
        var other = new DiskCache(_root, new Uri("https://other.test"));
        Assert.Equal(0, other.Bytes);
        var bumped = Cache(version: DiskCache.FormatVersion + 1);
        Assert.False(Directory.Exists(old.DirectoryPath));
        Assert.Equal(0, bumped.Bytes);
    }

    [Fact]
    public async Task NotModifiedRefreshesMetadataWithoutRewritingBody()
    {
        var server = new Server();
        var cache = Cache();
        using var api = new AnimaApi("https://fixture.test", server, cache);
        await api.GetBytesAsync("/assets/props/p/model");
        string body = Directory.GetFiles(cache.DirectoryPath, "*.bin").Single();
        var stamp = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(body, stamp);
        await api.GetBytesAsync("/assets/props/p/model");
        Assert.Equal(stamp, File.GetLastWriteTimeUtc(body));
    }

    [Fact]
    public async Task NoStoreReplacesOldEntryAndConcurrentDownloadsKeepIndexConsistent()
    {
        var server = new Server();
        var cache = Cache();
        using var api = new AnimaApi("https://fixture.test", server, cache);
        await api.GetBytesAsync("/assets/props/p/model");
        server.Policy = "no-store"; server.Etag = "\"two\"";
        await api.GetBytesAsync("/assets/props/p/model");
        await api.GetBytesAsync("/assets/props/p/model");
        Assert.Equal(3, server.Bodies);
        Assert.Equal(0, cache.Bytes);
        server.Policy = "immutable";
        await Task.WhenAll(Enumerable.Range(0, 20).Select(i => api.GetBytesAsync($"/assets/props/{i}/model")));
        cache.FlushIndex();
        using var restarted = Cache();
        Assert.Equal(80, restarted.Bytes);
    }
}
