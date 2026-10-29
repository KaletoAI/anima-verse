using AnimaNative.Hud;

namespace AnimaNative;

/// <summary>Task 55 / E7-T10: drive the browser's minimap cadence from the frame clock; retain only the last
/// finished wire in the persistent HUD so reconnects receive the current state without rebuilding relief.</summary>
public partial class Main
{
    private SceneMinimap _minimap = new();

    private void TickMinimap(double dt)
    {
        if (_hud is null || _builder is null || _camera is null) return;
        if (_minimap.Tick(dt, Embodied && !Leaving, _builder, _figures, _camera.Yaw))
            _hud.SetMinimap(_minimap.State);
    }

    private void ResetMinimap()
    {
        _hud?.SetMinimap(null);
        _minimap = new();
    }
}
