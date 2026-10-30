using System;
using System.Globalization;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Ui;

/// <summary>Scales only the main viewport's 3D buffer; 2D overlays keep their output resolution.</summary>
public sealed class RenderResolution : IDisposable
{
    private readonly Viewport _viewport;
    private readonly Action<string> _log;
    private double? _pref;
    private string? _last;

    public RenderResolution(Viewport viewport, Action<string> log)
    {
        _viewport = viewport;
        _log = log;
        _viewport.SizeChanged += Resize;
    }

    public void Apply(double? pref)
    {
        _pref = pref;
        Resize();
    }

    private void Resize()
    {
        var size = _viewport.GetVisibleRect().Size;
        double scale = GraphicsPrefs.EffectiveRenderScale(_pref, size.X, size.Y);
        var mode = scale < 1 ? Viewport.Scaling3DModeEnum.Fsr : Viewport.Scaling3DModeEnum.Bilinear;
        _viewport.Scaling3DMode = mode;
        _viewport.Scaling3DScale = (float)scale;
        string pref = _pref?.ToString("0.##", CultureInfo.InvariantCulture) ?? "auto";
        string line = FormattableString.Invariant($"render scale: {pref} → {scale:0.00} ({size.X:0}×{size.Y:0} → {Math.Round(size.X * scale):0}×{Math.Round(size.Y * scale):0}, {(scale < 1 ? "FSR" : "Bilinear")})");
        if (line == _last) return;
        _last = line;
        _log(line);
    }

    public void Dispose() => _viewport.SizeChanged -= Resize;
}
