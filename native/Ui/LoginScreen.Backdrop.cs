using System;
using System.IO;
using System.Threading.Tasks;
using Godot;

namespace AnimaNative.Ui;

/// <summary>The last local view of this origin, decoded on a worker; GPU texture creation stays on the main thread.</summary>
public partial class LoginScreen
{
    private string _backdropRoot = "";
    private int _backdropGeneration;
    private TextureRect? _snapshot;
    private ImageTexture? _snapshotTexture;
    private double _backdropSeconds;
    private ShaderMaterial _backdropWash = null!;

    private async Task LoadBackdropAsync()
    {
        var generation = ++_backdropGeneration;
        RemoveSnapshot();
        var path = TitleBackdropMath.PathFor(_backdropRoot, _server.Text);
        if (path is null) return;
        // Reading and JPEG decoding can both exceed a frame on a slow disk or a 1920 px image.
        using var image = await Task.Run(() =>
        {
            try
            {
                if (!File.Exists(path)) return null;
                var bytes = File.ReadAllBytes(path);
                var loaded = new Image();
                if (loaded.LoadJpgFromBuffer(bytes) == Error.Ok) return loaded;
                loaded.Dispose();
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
            return null;
        });
        if (image is null || !IsInstanceValid(this) || generation != _backdropGeneration) return;
        _snapshotTexture = ImageTexture.CreateFromImage(image);
        _snapshot = new TextureRect
        {
            Name = "WorldSnapshot", MouseFilter = MouseFilterEnum.Ignore,
            ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize, Texture = _snapshotTexture,
        };
        AddChild(_snapshot);
        MoveChild(_snapshot, 0);
        _backdropWash.SetShaderParameter("snapshot", true);
        _backdropSeconds = 0;
        TickBackdrop(0);
    }

    private void RemoveSnapshot()
    {
        if (_snapshot is not null)
        {
            RemoveChild(_snapshot);
            _snapshot.QueueFree();
            _snapshot = null;
        }
        _snapshotTexture?.Dispose();
        _snapshotTexture = null;
        _backdropWash?.SetShaderParameter("snapshot", false);
    }

    private void TickBackdrop(double delta)
    {
        if (_snapshot?.Texture is not { } texture) return;
        _backdropSeconds = (_backdropSeconds + delta) % 80;
        var rect = TitleBackdropMath.Cover(Size.X, Size.Y, texture.GetWidth(), texture.GetHeight(), _backdropSeconds);
        _snapshot.Position = new Vector2((float)rect.X, (float)rect.Y);
        _snapshot.Size = new Vector2((float)rect.Width, (float)rect.Height);
    }
}
