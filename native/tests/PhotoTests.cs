using System;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Photo;
using Xunit;

namespace AnimaNative.Tests;

public class PhotoTests
{
    // Same hand derivation as smoke_photo_view.mjs: vertical FOV 90°, aspect 2,
    // z=-10 gives x edges ±20 and y edges ±10. Height 3-1=2; depth sqrt(500).
    [Fact]
    public void FramingMatchesBrowserEdgesAndExclusions()
    {
        var subjects = new[] {
            new PhotoSubject("centre", new(0,3,-10)), new("left", new(-20,3,-10)),
            new("right", new(20,3,-10)), new("top", new(0,13,-10)), new("bottom", new(0,-7,-10)),
            new("behind", new(0,3,10)), new("outside", new(21,3,-10)),
            new("near", new(0,3,-.1)), new("far", new(0,3,-101)) };
        var view = PhotoView.Build(new(0,3,0), new(0,0,-1), new(1,0,0), new(0,1,0), 90, 2, .2, 100, subjects, 1);
        Assert.Equal(new[]{"centre","left","right","top","bottom"}, view.visible.Select(v=>v.name));
        Assert.Equal(.5, view.visible[0].screen_x, 9); Assert.Equal(.5, view.visible[0].screen_y, 9);
        Assert.Equal(0, view.visible[1].screen_x, 9); Assert.Equal(1, view.visible[2].screen_x, 9);
        Assert.Equal(0, view.visible[3].screen_y, 9); Assert.Equal(1, view.visible[4].screen_y, 9);
        Assert.Equal(22.360679774997898, view.visible[1].depth_m, 9);
        Assert.Equal(2, view.camera.height_m); Assert.Equal(90, view.camera.fov_deg);
        var down = PhotoView.Build(new(0,3,0), new(0,-.5,-Math.Sqrt(.75)), new(1,0,0), new(0,Math.Sqrt(.75),-.5),
            90, 2, .2, 100, [], 4);
        Assert.Equal(-30, down.camera.pitch_deg, 9); Assert.Equal(0, down.camera.height_m);
    }

    [Fact]
    public void FlightUsesPitchWorldVerticalNormalizedAxesAndRealClampedDelta()
    {
        var c = new PhotoControl(); c.Enter(new(0,0,0), 0, -Math.PI/6);
        c.Key("w", true); c.Step(.1);
        Assert.Equal(-.2, c.Position.Y, 9); Assert.Equal(-.3464101615137755, c.Position.Z, 9);
        c.ReleaseKeys(); c.Key("e", true); c.Key("shift", true); c.Step(10);
        Assert.Equal(1, c.Position.Y, 9); // .1 s clamp × 4 m/s × 3, added to -.2.
        c.Enter(new(0,0,0), 0, 0); c.Key("w", true); c.Key("d", true); c.Step(.1);
        Assert.Equal(.4, Math.Sqrt(c.Position.X*c.Position.X+c.Position.Z*c.Position.Z), 9);
        c.Leave(); c.Step(.1); Assert.Empty(c.Keys); Assert.False(c.Active);
    }

    [Fact]
    public void SpeedPitchAndKeyLifecycleMatchBrowser()
    {
        var c = new PhotoControl(); Assert.Equal(4,c.Speed);
        c.Enter(new(0,0,0),0,0); c.Wheel(-100);
        Assert.Equal(4*Math.Exp(.12),c.Speed,9);
        c.Wheel(-100000); Assert.Equal(20,c.Speed); c.Wheel(100000); Assert.Equal(.5,c.Speed);
        c.Look(100,100000); Assert.Equal(-.5,c.Yaw,9); Assert.Equal(-Math.PI*.49,c.Pitch,9);
        c.Look(0,-100000); Assert.Equal(Math.PI*.49,c.Pitch,9);
        c.Key("w",true); c.Leave(); c.Enter(new(0,0,0),0,0); Assert.Empty(c.Keys);
        Assert.Equal(.5,c.Speed); // Browser keeps the speed between sessions.
    }
}
