using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Cache;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 72: real body IO, explicit durability boundaries and deterministic metadata-lock contention.</summary>
public sealed class CacheConcurrencyTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "anima-concurrent-cache-" + Guid.NewGuid().ToString("N"));
    private static readonly Uri Origin = new("https://fixture.test");
    private DiskCache Open() => new(_root, Origin);
    private static HttpCachePolicy Policy => new(true, true, DateTimeOffset.UtcNow, "immutable");
    public void Dispose() { if (Directory.Exists(_root)) Directory.Delete(_root, true); }

    // Keep test synchronization out of the production API. A held metadata lock must prevent publication,
    // but cannot prevent the hash and complete body write that precede publication.
    private static object Gate(DiskCache cache) => typeof(DiskCache)
        .GetField("_gate", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(cache)!;

    [Fact]
    public async Task StorePreparesHashedBodyWithoutOwningTheMetadataLock()
    {
        using var cache = Open();
        var body = new byte[4 * 1024 * 1024];
        body[0] = 72;
        Task storing;
        bool bodyWritten;
        lock (Gate(cache))
        {
            storing = Task.Factory.StartNew(() => cache.Store("large", body, "one", Policy),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            bodyWritten = SpinWait.SpinUntil(() => Directory.GetFiles(cache.DirectoryPath, "*.bin").Length == 1,
                TimeSpan.FromSeconds(10));
            // Publication is still blocked, independently of machine speed or thread-pool scheduling.
            Assert.False(storing.IsCompleted);
            Assert.Equal(0, cache.Readout.Entries);
        }
        await storing.WaitAsync(TimeSpan.FromSeconds(30));
        Assert.True(bodyWritten, "Store waited for the metadata lock before hashing/writing its body");
        Assert.Equal(body, cache.Read("large")!.Value.Body);
    }

    [Fact]
    public async Task TwoHundredBootStoresAndReadsFinishTogetherAndSurviveFlush()
    {
        using var cache = Open();
        var body = new byte[256 * 1024];
        body[0] = 72;
        for (int i = 0; i < 200; i++) cache.Store("read/" + i, body, "seed", Policy);
        using var start = new ManualResetEventSlim();
        var workers = Enumerable.Range(0, 200).SelectMany(i => new[] {
            Task.Run(() => { start.Wait(); cache.Store("write/" + i, body, "new", Policy); }),
            Task.Run(() => { start.Wait(); Assert.Equal(body, cache.Read("read/" + i)!.Value.Body); }),
        }).ToArray();
        var all = Task.WhenAll(workers);
        start.Set();
        try { await all.WaitAsync(TimeSpan.FromSeconds(60)); }
        finally { await all; } // Never remove the test's tree while a worker still uses it.
        Assert.Equal(400, cache.Count);
        Assert.Equal(400L * body.Length, cache.Bytes);
        cache.FlushIndex();
        using var restarted = Open();
        Assert.Equal(400, restarted.Count);
        for (int i = 0; i < 200; i++) Assert.Equal(body, restarted.Read("write/" + i)!.Value.Body);
        Assert.Empty(Directory.GetFiles(cache.DirectoryPath, "*.tmp"));
    }

    [Fact]
    public async Task EvictionCannotDeleteAnIdenticalBodyAwaitingPublication()
    {
        using var cache = new DiskCache(_root, Origin, limitBytes: 1);
        cache.Store("a", new byte[] { 1 }, "old", Policy);
        string path = Path.Combine(cache.DirectoryPath, cache.Read("a")!.Value.Entry.File);
        Task rewriting;
        bool prepared;
        lock (Gate(cache))
        {
            // Removing the old body lets us observe exactly when the replacement rename finishes.
            File.Delete(path);
            rewriting = Task.Factory.StartNew(() => cache.Store("a", new byte[] { 1 }, "new", Policy),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            prepared = SpinWait.SpinUntil(() => File.Exists(path), TimeSpan.FromSeconds(10));
            cache.Store("b", new byte[] { 2 }, "evict-a", Policy);
            Assert.Equal(1, cache.Count);
        }
        await rewriting.WaitAsync(TimeSpan.FromSeconds(30));
        Assert.True(prepared, "replacement body must be prepared before eviction");
        Assert.Equal(new byte[] { 1 }, cache.Read("a")!.Value.Body);
        Assert.Null(cache.Read("b"));
        Assert.Single(Directory.GetFiles(cache.DirectoryPath, "*.bin"));
    }

    [Fact]
    public async Task ObsoleteCleanupCannotDeleteAConcurrentReturnToEarlierContent()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        int block = 0;
        using var cache = new DiskCache(_root, Origin, now: () => {
            if (Interlocked.CompareExchange(ref block, 0, 1) == 1) { entered.Set(); release.Wait(); }
            return DateTimeOffset.UtcNow;
        });
        cache.Store("same", new byte[] { 1 }, "first", Policy);
        string first = Path.Combine(cache.DirectoryPath, cache.Read("same")!.Value.Entry.File);
        var stamp = new DateTime(2000, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(first, stamp);
        block = 1;
        var changing = Task.Factory.StartNew(() => cache.Store("same", new byte[] { 2 }, "second", Policy),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        Task? returning = null;
        bool prepared = false;
        try
        {
            Assert.True(entered.Wait(TimeSpan.FromSeconds(10)), "first replacement must own the metadata lock");
            returning = Task.Factory.StartNew(() => cache.Store("same", new byte[] { 1 }, "third", Policy),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            prepared = SpinWait.SpinUntil(() => File.GetLastWriteTimeUtc(first) != stamp, TimeSpan.FromSeconds(10));
        }
        finally
        {
            release.Set();
            await changing.WaitAsync(TimeSpan.FromSeconds(30));
            if (returning is not null) await returning.WaitAsync(TimeSpan.FromSeconds(30));
        }
        Assert.True(prepared, "returning content must finish its rename before obsolete cleanup");
        var hit = cache.Read("same")!.Value;
        Assert.Equal("third", hit.Entry.Etag);
        Assert.Equal(new byte[] { 1 }, hit.Body);
        Assert.Single(Directory.GetFiles(cache.DirectoryPath, "*.bin"));
    }

    [Fact]
    public void StoresAndRefreshesBatchTheirIndexUntilExplicitFlush()
    {
        using var cache = Open();
        cache.Store("seed", new byte[] { 1 }, "old", Policy);
        cache.FlushIndex();
        string index = Path.Combine(cache.DirectoryPath, "index.json");
        string saved = File.ReadAllText(index);
        lock (Gate(cache))
        {
            cache.Store("new", new byte[] { 2 }, "new", Policy);
            cache.Refresh("seed", "refreshed", Policy);
            Assert.Equal(saved, File.ReadAllText(index));
            cache.FlushIndex();
        }
        using var restarted = Open();
        Assert.Equal(2, restarted.Count);
        Assert.Equal("refreshed", restarted.Read("seed")!.Value.Entry.Etag);
        Assert.Equal(new byte[] { 2 }, restarted.Read("new")!.Value.Body);
    }

    [Fact]
    public void CrashLosesUnflushedEntriesAndRemovesTheirOrphanBodies()
    {
        var crashed = Open();
        string orphan;
        lock (Gate(crashed))
        {
            crashed.Store("durable", new byte[] { 1 }, "saved", Policy);
            crashed.FlushIndex();
            crashed.Store("unflushed", new byte[] { 2, 3 }, "lost", Policy);
            orphan = Path.Combine(crashed.DirectoryPath, crashed.Read("unflushed")!.Value.Entry.File);
            File.WriteAllText(Path.Combine(crashed.DirectoryPath, "interrupted.tmp"), "partial");
            // Simulate process death, without Dispose/FlushIndex, and prevent its worker from waking later.
            (typeof(DiskCache).GetField("_flushTimer", BindingFlags.Instance | BindingFlags.NonPublic)!
                .GetValue(crashed) as Timer)?.Dispose();
        }
        Assert.True(File.Exists(orphan));
        using var restarted = Open();
        Assert.Equal(1, restarted.Count);
        Assert.Equal(new byte[] { 1 }, restarted.Read("durable")!.Value.Body);
        Assert.Null(restarted.Read("unflushed"));
        Assert.False(File.Exists(orphan));
        Assert.Empty(Directory.GetFiles(restarted.DirectoryPath, "*.tmp"));
    }

    [Fact]
    public void TornPersistedBodyIsAMissAfterRestart()
    {
        var cache = Open();
        cache.Store("torn", new byte[4096], "one", Policy);
        string body = Path.Combine(cache.DirectoryPath, cache.Read("torn")!.Value.Entry.File);
        cache.Dispose();
        using (var stream = new FileStream(body, FileMode.Open, FileAccess.Write)) stream.SetLength(100);
        using var restarted = Open();
        Assert.Equal(1, restarted.Count); // Prove the index survived before exercising body validation.
        Assert.Null(restarted.Read("torn"));
        Assert.Equal(0, restarted.Count);
        Assert.False(File.Exists(body));
    }

    [Theory]
    [InlineData("refresh")]
    [InlineData("no-store")]
    [InlineData("no-store-write")]
    [InlineData("oversized")]
    public void ClosedCacheRejectsLateMetadataChanges(string operation)
    {
        using var cache = new DiskCache(_root, Origin, limitBytes: 4);
        cache.Store("kept", new byte[] { 1 }, "saved", Policy);
        cache.Dispose();
        if (operation == "refresh") cache.Refresh("kept", "late", Policy);
        else if (operation == "no-store") cache.Refresh("kept", null, new(false, false, cache.Now, "no-store"));
        else if (operation == "no-store-write") cache.Store("kept", new byte[] { 2 }, null, new(false, false, cache.Now, "no-store"));
        else cache.Store("kept", new byte[5], "late", Policy);
        Assert.Equal("saved", cache.Read("kept")!.Value.Entry.Etag);
        using var restarted = Open();
        Assert.Equal(new byte[] { 1 }, restarted.Read("kept")!.Value.Body);
    }

    [Fact]
    public void ApiShutdownFlushesStoresRefreshesAndRemovalsAndClosesTheCache()
    {
        var cache = Open();
        using (var api = new AnimaApi(Origin.ToString(), cache: cache))
        {
            cache.Store("kept", new byte[] { 1 }, "old", Policy);
            cache.Store("removed", new byte[] { 2 }, "old", Policy);
            cache.FlushIndex();
            cache.Refresh("kept", "refreshed", Policy);
            cache.Refresh("removed", null, new(false, false, cache.Now, "no-store"));
            cache.Store("new", new byte[] { 3 }, "new", Policy);
        }
        // The API owns this cache: late publication cannot restart its background writer after shutdown.
        int bodies = Directory.GetFiles(cache.DirectoryPath, "*.bin").Length;
        cache.Store("late", new byte[] { 4 }, "late", Policy);
        Assert.Equal(bodies, Directory.GetFiles(cache.DirectoryPath, "*.bin").Length);
        Assert.Null(cache.Read("late"));
        using var restarted = Open();
        Assert.Equal(2, restarted.Count);
        Assert.Equal("refreshed", restarted.Read("kept")!.Value.Entry.Etag);
        Assert.Equal(new byte[] { 3 }, restarted.Read("new")!.Value.Body);
        Assert.Null(restarted.Read("removed"));
        Assert.Null(restarted.Read("late"));
    }
}
