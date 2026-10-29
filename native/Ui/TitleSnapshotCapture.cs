using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using Godot;

namespace AnimaNative.Ui;

/// <summary>A single rendered 3D frame with every 2D overlay hidden, then an atomic local JPEG replacement.</summary>
public static class TitleSnapshotCapture
{
    public static bool CanCapture(bool check, bool bench)
        => !check && !bench && DisplayServer.GetName() != "headless"
            && DisplayServer.WindowGetMode() != DisplayServer.WindowMode.Minimized
            && RenderingServer.RenderLoopEnabled && DisplayServer.WindowCanDraw();

    public static async Task<bool> CaptureAsync(Node host, string path, bool check, bool bench, Action<string> log)
    {
        if (!CanCapture(check, bench) || !host.IsInsideTree()) return false;
        var started = Stopwatch.GetTimestamp();
        Image? image = null;
        var layers = new List<(CanvasLayer Layer, bool Visible)>();
        var items = new List<(CanvasItem Item, bool Visible)>();
        void Find(Node parent, bool covered = false)
        {
            foreach (var child in parent.GetChildren())
            {
                // Other render targets do not draw on the captured viewport.
                if (child is SubViewport) continue;
                var childCovered = covered;
                if (child is CanvasLayer layer)
                {
                    layers.Add((layer, layer.Visible));
                    childCovered = true;
                }
                else if (!covered && child is CanvasItem item)
                {
                    items.Add((item, item.Visible));
                    childCovered = true;
                }
                Find(child, childCovered);
            }
        }
        Find(host.GetTree().Root);
        var frame = new TaskCompletionSource<bool>();
        bool restored = false, finished = false;
        void Restore()
        {
            if (restored) return;
            restored = true;
            foreach (var (layer, visible) in layers) if (GodotObject.IsInstanceValid(layer)) layer.Visible = visible;
            foreach (var (item, visible) in items) if (GodotObject.IsInstanceValid(item)) item.Visible = visible;
        }
        void Drawn()
        {
            if (finished) return;
            finished = true;
            try
            {
                if (GodotObject.IsInstanceValid(host) && host.IsInsideTree() && CanCapture(check, bench))
                    image = host.GetViewport().GetTexture().GetImage();
            }
            catch (Exception e) { log($"title backdrop: capture skipped ({e.GetType().Name})"); }
            finally
            {
                // Restore inside FramePostDraw itself, regardless of when the Task continuation is scheduled.
                Restore();
                frame.TrySetResult(true);
            }
        }
        void Leaving()
        {
            if (finished) return;
            finished = true;
            Restore();
            frame.TrySetResult(false);
        }
        RenderingServer.FramePostDraw += Drawn;
        host.TreeExiting += Leaving;
        try
        {
            foreach (var (layer, _) in layers) layer.Visible = false;
            foreach (var (item, _) in items) item.Visible = false;
            await frame.Task;
        }
        finally
        {
            RenderingServer.FramePostDraw -= Drawn;
            if (GodotObject.IsInstanceValid(host)) host.TreeExiting -= Leaving;
            Restore();
        }
        if (image is null) return false;
        using (image)
        {
            if (image.IsEmpty()) return false;
            // Resizing, JPEG encoding and disk IO run after overlays have been restored, off the frame thread.
            var size = await Task.Run(() => Save(image, path));
            if (size is null) return false;
            log($"title backdrop: {size.Value.Width}x{size.Value.Height}, {size.Value.Bytes} bytes, {Stopwatch.GetElapsedTime(started).TotalMilliseconds:0.#} ms");
            return true;
        }
    }

    private static (int Width, int Height, long Bytes)? Save(Image image, string path)
    {
        var tmp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            if (image.GetWidth() > 1920)
                image.Resize(1920, Math.Max(1, (int)Math.Round(image.GetHeight() * 1920d / image.GetWidth())), Image.Interpolation.Lanczos);
            var bytes = image.SaveJpgToBuffer(0.85f);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllBytes(tmp, bytes);
            File.Move(tmp, path, overwrite: true);
            return (image.GetWidth(), image.GetHeight(), bytes.LongLength);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
        finally { try { File.Delete(tmp); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { } }
    }
}
