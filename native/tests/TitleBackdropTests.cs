using System;
using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

public class TitleBackdropTests
{
    [Fact]
    public void CoverCentersBothAspectRatiosAndPingPongsWithoutExposingEdges()
    {
        foreach (var (w, h, iw, ih) in new[] { (1600d, 900d, 800d, 800d), (400d, 600d, 1920d, 1080d) })
        foreach (var seconds in new[] { 0d, 10, 20, 40, 60, 80 })
        {
            var r = TitleBackdropMath.Cover(w, h, iw, ih, seconds);
            Assert.True(r.X <= 0 && r.Y <= 0 && r.X + r.Width >= w && r.Y + r.Height >= h);
        }
        var first = TitleBackdropMath.Cover(1600, 900, 1600, 900, 0);
        Assert.Equal(1696, first.Width, 6);
        Assert.Equal(954, first.Height, 6);
        Assert.Equal(first, TitleBackdropMath.Cover(1600, 900, 1600, 900, 80));
        Assert.Equal(1824, TitleBackdropMath.Cover(1600, 900, 1600, 900, 40).Width, 6);
    }

    [Fact]
    public void BackdropPathsUseTheCacheOriginHash()
    {
        var path = TitleBackdropMath.PathFor("/tmp/backdrop", "example.org:8000");
        Assert.Equal(path, TitleBackdropMath.PathFor("/tmp/backdrop", "http://example.org:8000/"));
        Assert.NotEqual(path, TitleBackdropMath.PathFor("/tmp/backdrop", "https://example.org:8000"));
        Assert.EndsWith(".jpg", path);
        Assert.Null(TitleBackdropMath.PathFor("/tmp/backdrop", ""));
    }
}
