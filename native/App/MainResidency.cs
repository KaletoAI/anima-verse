using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Api;
using Json = AnimaNative.World.Json;
using Godot;

namespace AnimaNative;

/// <summary>Task 44 / E6-T4: runtime residency wiring, kept out of MainWorld.cs's foreign debug edits.</summary>
public partial class Main
{
    private bool ResidencyRebuildHoldsOpen(string id) => _builder?.IsRebuilding(id) == true;

    /// <summary>
    /// main.ts streamPoints/syncStreamPins: read the rendered root on every 1 Hz LOD tick, with the latest
    /// accepted map's pos fallback, plus the camera TARGET. The eye only drives model tiers. Boot ends here,
    /// after FigureManager's initial placement; current, travel and open remain independently owned pins.
    /// </summary>
    private void StartResidency()
    {
        if (_builder is not { } builder) return;
        builder.RefreshStreamView = () =>
        {
            var map = _figures?.LatestMap ?? builder.FirstMap;
            if (map is not { } snapshot || _camera is null) return;
            var points = new List<(double X, double Z)>();
            var avatar = Json.Str(snapshot, "avatar");
            if (_figures is { } figures && figures.Figures.TryGetValue(avatar, out var fig) && IsInstanceValid(fig))
            {
                var rendered = fig.GlobalPosition;
                points.Add((rendered.X, rendered.Z));
            }
            else
                foreach (var row in Json.Arr(snapshot, "characters"))
                    if (avatar.Length > 0 && Json.Str(row, "name") == avatar
                        && row.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object
                        && Json.NumOrNull(pos, "x") is { } x && Json.NumOrNull(pos, "z") is { } z)
                    { points.Add((x, z)); break; }
            var target = _camera.Target;
            points.Add((target.X, target.Z));
            builder.SetStreamView(snapshot, points, bootDone: _figures?.FirstPollDone.IsCompleted == true);
        };
        builder.TickStreamRings();
    }
}
