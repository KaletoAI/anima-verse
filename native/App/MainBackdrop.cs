using AnimaNative.Ui;
using Godot;

namespace AnimaNative;

public partial class Main
{
    private double _backdropWait;
    private bool _backdropCaptured;

    /// <summary>Wait until the existing fade has removed the title and the avatar has arrived, then three seconds.</summary>
    private void TickTitleBackdrop(double delta)
    {
        if (_backdropCaptured || _options is null || _api is null || _stop.IsCancellationRequested
            || !TitleSnapshotCapture.CanCapture(_options.Check || _options.CheckBench, _options.Bench)) return;
        if (_loading is not null || !ControlBootReady || AvatarFigure() is not { Loading: false }
            || AvatarWaitsForPlace())
        {
            _backdropWait = 0;
            return;
        }
        _backdropWait += delta;
        if (_backdropWait < 3) return;
        _backdropCaptured = true;
        var path = TitleBackdropMath.PathFor(ProjectSettings.GlobalizePath("user://backdrop"), _api.BaseUri.ToString());
        if (path is not null) _ = TitleSnapshotCapture.CaptureAsync(this, path, _options.Check, _options.Bench, Log);
    }
}
