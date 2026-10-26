using System.Text.Json;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Main, lights: the world clock (<c>engine.setGameHour</c>: sun, sky, colours, intensities and the night gate), the
/// prop lights / mirror passes / door swing of the frame, the room ambience eased onto the clock base
/// (<c>engine.applyAmbience</c>) and the sun following the camera target (engine.ts frame()).
/// </summary>
public partial class Main : Node3D
{
    /// <summary>main.ts <c>setInterval(takeGameHour, 60_000)</c>.</summary>
    private const double GameHourIntervalS = 60;

    private StageAmbience? _stage;
    /// <summary><c>engine.nightFactor</c>: 0 = day until the first clock reading (the browser's engine starts at 0 too).</summary>
    private double _night;
    private AmbienceState _ambience = AmbienceState.Neutral;

    /// <summary>
    /// <c>takeGameHour</c> → <c>engine.setGameHour</c>: a map with a numeric <c>game_time.hour_fraction</c> moves the sun,
    /// the sky and the light colours/intensities and sets the night factor (<c>onDayNight</c>).
    /// </summary>
    private void TakeGameHour(JsonElement map)
    {
        if (Ambience.GameHourOf(map) is not { } hour) return;
        double night = Ambience.NightFactorAt(hour);
        bool changed = _stage?.Hour != hour;
        _stage?.SetHour(hour);
        if (changed && _stage is not null)
        {
            var f = _stage.Frame;
            Log($"world clock {hour:0.00} h → night {night:0.###}, sun {f.Sun.Energy:0.###} hemi {f.Ambient.Energy:0.###} "
                + $"fill {f.Fill.Energy:0.###} (Godot energy = three intensity / π)");
        }
        _night = night;
    }

    /// <summary>
    /// The frame's lights: the focus is the camera target (the overview — embodied it is the avatar, E7); the prop lights,
    /// mirrors and doors tick; the room under the focus in the open location gives the ambience target, eased with τ 0.5.
    /// </summary>
    private void TickLights(double delta)
    {
        if (_builder is null || _camera is null) return;
        var focus = _camera.Target;
        _builder.TickProps(delta, _camera, focus, _night);
        var target = Ambience.Target(_builder.AmbienceAt(_openView.OpenId, focus));
        _ambience = Ambience.Step(_ambience, target, delta);
        _stage?.Apply(_ambience);
        _stage?.Track(focus, _camera.Distance);
    }
}
