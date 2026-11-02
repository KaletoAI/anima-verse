using System;
using System.IO;
using System.Text.Json;
using AnimaNative.Figures;
using Xunit;

namespace AnimaNative.Tests;

public class ClipShiftTests
{
    [Fact]
    public void SharedVectorsAndHorizontalLeanCompensation()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "shared/test-vectors/clip_shift.json"))) dir = dir.Parent;
        Assert.NotNull(dir);
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir!.FullName, "shared/test-vectors/clip_shift.json")));
        Assert.Equal("anima-test-vectors/1", doc.RootElement.GetProperty("format").GetString());
        foreach (var v in doc.RootElement.GetProperty("cases").EnumerateArray())
        {
            var shift = ClipShift.Parse(v.GetProperty("shift_cm"));
            var world = shift.World(v.GetProperty("yaw_deg").GetDouble() * Math.PI / 180);
            var expected = v.GetProperty("world_m");
            Assert.Equal(expected[0].GetDouble(), world.X, 10);
            Assert.Equal(expected[1].GetDouble(), world.Z, 10);
        }
        // side=25 cm, forward=-40 cm: inverse lean Rx(90) maps forward
        // into local Y. World displacement must still stay horizontal.
        var local = new ClipShift(25, -40).Local(Math.PI / 2, 0);
        Assert.Equal(.25, local.X, 10);
        Assert.Equal(-.4, local.Y, 10);
        Assert.Equal(0, local.Z, 10);
        using var malformed = JsonDocument.Parse("[true, 2]");
        Assert.Equal(default, ClipShift.Parse(malformed.RootElement));
    }
}
