using System;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 38 (E4-T3): held textures survive LRU pressure; refusals are remembered without pinning entries.</summary>
public sealed class ImpostorCacheTests
{
    private sealed class Texture : IDisposable { public int Disposals; public void Dispose() => Disposals++; }
    [Fact]
    public void HeldEntrySurvivesPressureAndReleaseEvictsOldestUnheld()
    {
        using var cache = new ImpostorCache<Texture>(1);
        var held = new Texture(); var spare = new Texture();
        cache.Store("held", held);
        Assert.Same(held, cache.Acquire("held"));
        cache.Store("spare", spare);
        Assert.Equal(0, held.Disposals);
        Assert.Equal(1, spare.Disposals);
        cache.Release("held");
        cache.Store("new", new Texture());
        Assert.Equal(1, held.Disposals);
    }
    [Fact]
    public void TouchOrdersLruAndRefusalIsEvictable()
    {
        using var cache = new ImpostorCache<Texture>(2);
        var a = new Texture(); var b = new Texture();
        cache.Store("a", a); cache.Store("b", b);
        cache.Acquire("a"); cache.Release("a");
        cache.Store("refused", null);
        Assert.Equal(0, a.Disposals); Assert.Equal(1, b.Disposals);
        Assert.True(cache.Contains("refused")); Assert.Null(cache.Acquire("refused"));
        cache.Acquire("a"); cache.Release("a");
        cache.Store("c", new Texture());
        Assert.False(cache.Contains("refused"));
    }
    [Fact]
    public void MultipleLeasesAndOvershootAreReleasedExactlyOnce()
    {
        var cache = new ImpostorCache<Texture>(1);
        var a = new Texture(); var b = new Texture();
        cache.Store("a", a); cache.Acquire("a"); cache.Acquire("a");
        cache.Store("b", b, acquire: true);
        Assert.Equal(2, cache.Count);
        cache.Release("a"); Assert.Equal(0, a.Disposals);
        cache.Release("a"); Assert.Equal(1, a.Disposals);
        cache.Dispose(); cache.Dispose();
        Assert.Equal(1, a.Disposals); Assert.Equal(1, b.Disposals);
    }
}
