using System;
using System.IO;
using AnimaNative.Cache;

namespace AnimaNative.Ui;

/// <summary>Aspect-fill at every drift position; a 40 s eased leg, then the same path back.</summary>
public static class TitleBackdropMath
{
    public readonly record struct Rect(double X, double Y, double Width, double Height);

    public static Rect Cover(double width, double height, double imageWidth, double imageHeight, double seconds)
    {
        if (width <= 0 || height <= 0 || imageWidth <= 0 || imageHeight <= 0) return default;
        var t = (1 - Math.Cos(seconds * Math.PI / 40)) / 2;
        var scale = Math.Max(width / imageWidth, height / imageHeight) * (1.06 + 0.08 * t);
        var w = imageWidth * scale;
        var h = imageHeight * scale;
        return new((width - w) / 2 + width * 0.015 * (2 * t - 1),
                   (height - h) / 2 - height * 0.01 * (2 * t - 1), w, h);
    }

    public static string? PathFor(string root, string server)
        => LauncherSettings.NormalizeServer(server) is { } normalized
            ? Path.Combine(root, DiskCache.OriginHash(new Uri(normalized)) + ".jpg")
            : null;
}
