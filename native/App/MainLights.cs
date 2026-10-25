using System.Text.Json;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Main, lights: the night gate from the world clock, the prop lights / mirror passes / door swing of the frame, and
/// the room ambience eased onto the stage (main.ts' frame hook + <c>engine.applyAmbience</c>).
///
/// NEUTRAL BASE UNTIL E3: no game-hour light model yet — <see cref="StageAmbience"/> scales and tints the fixed stage
/// of <see cref="BuildStage"/>; the night factor is the only thing the world clock drives so far.
/// </summary>
public partial class Main : Node3D
{
    /// <summary>main.ts <c>setInterval(takeGameHour, 60_000)</c>.</summary>
    private const double GameHourIntervalS = 60;

    private StageAmbience? _stage;
    /// <summary><c>engine.nightFactor</c>: 0 = day until the first clock reading (the browser's engine starts at 0 too).</summary>
    private double _night;
    private AmbienceState _ambience = AmbienceState.Neutral;

    /// <summary><c>takeGameHour</c>: a map with a numeric <c>game_time.hour_fraction</c> sets the night factor.</summary>
    private void TakeGameHour(JsonElement map)
    {
        if (Ambience.GameHourOf(map) is not { } hour) return;
        double night = Ambience.NightFactorAt(hour);
        if (night != _night) Log($"world clock {hour:0.00} h → night {night:0.###}");
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
    }
}
