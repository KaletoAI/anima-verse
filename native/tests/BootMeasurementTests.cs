using AnimaNative.Sync;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 62: concurrent work counters are stage deltas, never cumulative boot stamps.</summary>
public sealed class BootMeasurementTests
{
    [Theory]
    [InlineData("/characters/A/model3d/texture", "texture")]
    [InlineData("/characters/A/model3d/file", "character GLB")]
    [InlineData("/assets/props/p/source", "texture")]
    [InlineData("/play/rooms/p/model", "scene GLB")]
    public void ByteCategoriesMatchTheirParseCategories(string path, string category)
        => Assert.Equal(category, BootMeasurements.Category(path));

    [Fact]
    public void CompletedBootStopsAccumulatingPollSamplesAndResetStartsNextBoot()
    {
        var measurements = new BootMeasurements();
        var boot = new BootTracker(() => 0) { Measurements = measurements };
        measurements.Add("JSON", "download", 1, 1, 4);
        foreach (var stage in AnimaNative.Overview.BootProgress.Stages) boot.Report(stage);
        for (int i = 0; i < 1000; i++) measurements.Add("JSON", "download", 1, 1, 4);
        Assert.Single(measurements.Snapshot());
        measurements.Reset();
        measurements.Add("JSON", "download", 1, 1, 4);
        Assert.Single(measurements.Snapshot());
    }

    [Fact]
    public void StagesSnapshotIndependentDownloadParseAndCpuSums()
    {
        double now = 0;
        var measurements = new BootMeasurements();
        var boot = new BootTracker(() => now) { Measurements = measurements };
        measurements.Add("scene GLB", "download", 10, 1, 100);
        measurements.Add("scene GLB", "parse", 4);
        measurements.Add("scene GLB", "generate", 2);
        now = 20; boot.Report("world");
        measurements.Add("clip", "clip import", 3);
        measurements.Add("character GLB", "fitting", 5);
        now = 40; boot.Report("scenes");
        boot.Report("world");
        Assert.Contains("world 20 ms [download=10 parse=4 CPU=2 ms", boot.Describe());
        Assert.Contains("scenes 40 ms [download=0 parse=0 CPU=8 ms", boot.Describe());
        Assert.Contains("scene GLB: requests=1 bytes=100 download=10 parse=4 CPU=2 ms", measurements.Describe());
        Assert.Contains("generate=2", boot.Describe());
        Assert.Contains("clip import=3", boot.Describe());
        Assert.Contains("fitting=5", boot.Describe());
    }
}
