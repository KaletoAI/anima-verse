using System;
using System.IO;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 67 #2/#3: isolated real disk trees; worker gates never depend on xUnit class scheduling.</summary>
public sealed class CacheReviewTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "anima-review-cache-" + Guid.NewGuid().ToString("N"));
    public void Dispose() { if (Directory.Exists(_root)) Directory.Delete(_root, true); }

    [Fact]
    public void WarmHitsBatchLastUsedUntilShutdownAndKeepAtomicIndex()
    {
        var now = DateTimeOffset.Parse("2026-10-29T12:00:00Z");
        using var cache = new DiskCache(_root, new Uri("https://fixture.test"), now: () => now);
        using (var api = new AnimaApi("https://fixture.test", cache: cache))
        {
            cache.Store("clip", new byte[] { 1, 2 }, "one", new(true, true, now, "immutable"));
            cache.FlushIndex(); // Establish the durable baseline before testing memory-only touches.
            string index = Path.Combine(cache.DirectoryPath, "index.json");
            string initial = File.ReadAllText(index);
            now = now.AddSeconds(1);
            for (int i = 0; i < 20; i++) Assert.NotNull(cache.Read("clip"));
            Assert.Equal(initial, File.ReadAllText(index));
        }
        using var saved = JsonDocument.Parse(File.ReadAllText(Path.Combine(cache.DirectoryPath, "index.json")));
        Assert.Equal(now, saved.RootElement.GetProperty("entries")[0].GetProperty("last_used").GetDateTimeOffset());
        Assert.Empty(Directory.GetFiles(cache.DirectoryPath, "*.tmp"));
    }

    [Fact]
    public async Task ReadoutReturnsSnapshotWhileWorkerOwnsStoreLock()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        bool block = false;
        var now = DateTimeOffset.UtcNow;
        using var cache = new DiskCache(_root, new Uri("https://fixture.test"), now: () => {
            if (block) { entered.Set(); release.Wait(); }
            return now;
        });
        cache.Store("first", new byte[4], null, new(true, true, now, "immutable"));
        block = true;
        var worker = Task.Run(() => cache.Store("second", new byte[3], null, new(true, true, now, "immutable")));
        Task<DiskCache.Stats>? reading = null;
        bool completed = false;
        try
        {
            Assert.True(await Task.Run(() => entered.Wait(TimeSpan.FromSeconds(5))));
            reading = Task.Run(() => cache.Readout);
            completed = await Task.WhenAny(reading, Task.Delay(2000)) == reading;
            if (completed) Assert.Equal(new DiskCache.Stats(4, cache.LimitBytes, 1), await reading);
        }
        finally { release.Set(); await worker; if (reading is not null) await reading; }
        Assert.True(completed, "main-thread readout waited for the worker lock");
        Assert.Equal(new DiskCache.Stats(7, cache.LimitBytes, 2), cache.Readout);
        cache.RequestClear();
        Assert.Equal(new DiskCache.Stats(0, cache.LimitBytes, 0), cache.Readout);
    }
    /// <summary>Task 67 #2: background persistence eventually saves hot LRU state without a shutdown.</summary>
    [Fact]
    public async Task BackgroundFlushPersistsTouchesWithoutFurtherWrites()
    {
        var now = DateTimeOffset.Parse("2026-10-29T12:00:00Z");
        using var cache = new DiskCache(_root, new Uri("https://fixture.test"), now: () => now);
        cache.Store("clip", new byte[] { 1 }, null, new(true, true, now, "immutable"));
        cache.FlushIndex(); // Only the subsequent read may trigger persistence in this test.
        now = now.AddSeconds(1);
        cache.Read("clip");
        var until = DateTime.UtcNow.AddSeconds(10);
        DateTimeOffset saved;
        do
        {
            using var index = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(cache.DirectoryPath, "index.json")));
            saved = index.RootElement.GetProperty("entries")[0].GetProperty("last_used").GetDateTimeOffset();
            if (saved == now) break;
            await Task.Delay(50);
        } while (DateTime.UtcNow < until);
        Assert.Equal(now, saved);
        Assert.Empty(Directory.GetFiles(cache.DirectoryPath, "*.tmp"));
    }

    /// <summary>Task 67 #2: metadata belongs to validated inputs; a changed/no-store entry cannot reuse it.</summary>
    [Fact]
    public void KnownDigestDoesNotReopenBodyAndRejectsUnknownOrReplacedInputs()
    {
        using var cache = new DiskCache(_root, new Uri("https://fixture.test"));
        var policy = new HttpCachePolicy(true, true, cache.Now, "immutable");
        var original = new byte[] { 1, 2 };
        cache.Store("clip", original, "one", policy);
        var hit = cache.Read("clip")!.Value;
        File.Delete(Path.Combine(cache.DirectoryPath, hit.Entry.File));
        Assert.Equal(hit.Entry.Digest, cache.KnownEntry("clip", hit.Body)?.Digest);
        Assert.Null(cache.KnownEntry("clip", new byte[] { 1, 2 }));
        Assert.Null(cache.KnownEntry("other", hit.Body));
        cache.Store("clip", new byte[] { 3, 4 }, "two", policy);
        Assert.Null(cache.KnownEntry("clip", hit.Body));
        var replacement = cache.Read("clip")!.Value;
        cache.Refresh("clip", "two", new(false, false, cache.Now, "no-store"));
        Assert.Null(cache.KnownEntry("clip", replacement.Body));
    }
    /// <summary>Task 67 #2: a 304 may replace the validator while retaining the already validated bytes.</summary>
    [Fact]
    public void RevalidatedBodyUsesLatestValidatorWithoutAnotherRead()
    {
        using var cache = new DiskCache(_root, new Uri("https://fixture.test"));
        var policy = new HttpCachePolicy(true, false, cache.Now, "no-cache");
        cache.Store("clip", new byte[] { 1, 2 }, "old", policy);
        var hit = cache.Read("clip")!.Value;
        cache.Refresh("clip", "new", policy);
        File.Delete(Path.Combine(cache.DirectoryPath, hit.Entry.File));
        Assert.Equal("new", cache.KnownEntry("clip", hit.Body)?.Etag);
    }
}
