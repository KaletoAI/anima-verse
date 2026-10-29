using System;
using System.Globalization;
using System.IO;
using AnimaNative.Cache;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 64: derived resources share the HTTP store's integrity, restart, LRU and version boundary.</summary>
public sealed class DerivedCacheTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "anima-derived-test-" + Guid.NewGuid().ToString("N"));
    private DiskCache Open(long limit = 100) => new(_root, new Uri("https://fixture.test"), limit);
    public void Dispose() { if (Directory.Exists(_root)) Directory.Delete(_root, true); }

    [Fact]
    public void ResourcesAndSidecarsSurviveRestartAndShareTheByteBudget()
    {
        using var disk = Open();
        var policy = new HttpCachePolicy(true, true, disk.Now, "immutable");
        disk.Store("res", new byte[30], null, policy, extension: ".res");
        disk.Store("meta", new byte[20], null, policy, extension: ".json");
        disk.Dispose(); // Shutdown publishes the batched index before restart.
        using var restarted = Open(50);
        Assert.EndsWith(".res", restarted.Read("res")!.Value.Entry.File);
        Assert.EndsWith(".json", restarted.Read("meta")!.Value.Entry.File);
        restarted.Store("http", new byte[40], null, policy);
        Assert.InRange(restarted.Bytes, 40, 50);
        Assert.Null(restarted.Read("res"));
        Assert.Null(restarted.Read("meta"));
    }

    [Fact]
    public void SameLengthCorruptResourceIsAMiss()
    {
        using var disk = Open();
        disk.Store("res", new byte[] { 1, 2 }, null, new(true, true, disk.Now, "immutable"), extension: ".res");
        var entry = disk.Read("res")!.Value.Entry;
        File.WriteAllBytes(Path.Combine(disk.DirectoryPath, entry.File), new byte[] { 2, 1 });
        disk.Dispose();
        using var restarted = Open();
        Assert.Equal(1, restarted.Count); // The persisted entry must reach digest validation.
        Assert.Null(restarted.Read("res"));
    }

    [Fact]
    public void CachedWorkIsVisibleInTheStageSplit()
    {
        var measurements = new AnimaNative.Sync.BootMeasurements();
        measurements.Add("clip", "cached", 25);
        Assert.Contains("cached=25", AnimaNative.Sync.BootMeasurements.Split(measurements.Snapshot()));
    }

    [Fact]
    public void DependencyKeysAreUnambiguousAndCultureIndependent()
    {
        string first = DerivedKeys.Template("/m?v=1", new[] { "a,b", "c" }, 1.75, "rig", "model");
        Assert.NotEqual(first, DerivedKeys.Template("/m?v=1", new[] { "a", "b,c" }, 1.75, "rig", "model"));
        Assert.NotEqual(first, DerivedKeys.Template("/m?v=2", new[] { "a,b", "c" }, 1.75, "rig", "model"));
        Assert.NotEqual(first, DerivedKeys.Template("/m?v=1", new[] { "a,b", "c" }, 1.75, "rig2", "model"));
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
            Assert.Equal(first, DerivedKeys.Template("/m?v=1", new[] { "a,b", "c" }, 1.75, "rig", "model"));
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }
}
