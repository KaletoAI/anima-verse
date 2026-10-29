using System.Collections.Generic;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Hud;

/// <summary>Task 55 / E7-T10: runtime inputs shared by Main and the offline minimap check. Only known map
/// locations reach the producer; the avatar dot follows the locally walked figure, never its stale poll row.
/// The terrain catalog is the ground's currently held payload, and relief uses the native height revision.</summary>
public sealed class SceneMinimap
{
    private readonly MinimapProducer _producer = new();
    public MinimapState? State => _producer.State;

    public bool Tick(double dt, bool embodied, WorldBuilder builder, FigureManager? figures, double followYaw)
    {
        P2? position = figures?.Figures.GetValueOrDefault(figures.AvatarName) is { } avatar
            ? new(avatar.Position.X, avatar.Position.Z) : null;
        return _producer.Tick(dt, embodied, builder.Ground?.Catalog, builder.Height,
            figures?.LatestMap ?? builder.FirstMap, position, followYaw);
    }
}
