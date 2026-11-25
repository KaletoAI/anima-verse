using System;

namespace AnimaNative.Nav;

/// <summary>How the client bakes the storey meshes (decision 1; task 5 keeps one and deletes the other).</summary>
public enum NavBakeMode { Polygon, Voxel }

/// <summary>
/// The bake parameters of one mode. Both modes: agent radius 0.25 m, height 1.8 m, climb 0.25 m, slope 40°
/// (the <c>max_slope_deg</c> default), link connection radius 0.6 m. Polygon: cells 0.05 / 0.05, edge margin 0.1;
/// Voxel: cells 0.1 / 0.1, edge margin 0.25.
/// </summary>
public sealed record NavBakeParams(NavBakeMode Mode, double AgentRadius, double AgentHeight, double AgentMaxClimb,
                                   double AgentMaxSlopeDeg, double CellSize, double CellHeight, double EdgeConnectionMargin,
                                   double LinkConnectionRadius)
{
    /// <summary>Part of every fingerprint: raise it when the source rules change.</summary>
    public const int Version = 1;
    public const double MinCellSize = 0.05;
    public const double ElevatorEnterCost = 20;
    public const double ElevatorTravelCost = 10;

    /// <summary>The mode's own parameters.</summary>
    public static NavBakeParams For(NavBakeMode mode) => mode switch
    {
        NavBakeMode.Polygon => Create(mode, 0.05, 0.05),
        _ => Create(mode, 0.1, 0.1),
    };

    /// <summary>The mode's parameters with the given cells, each floored at <see cref="MinCellSize"/> — the one clamp.</summary>
    public static NavBakeParams Create(NavBakeMode mode, double cellSize, double cellHeight)
        => new(mode, 0.25, 1.8, 0.25, 40, Floor(cellSize), Floor(cellHeight),
               mode == NavBakeMode.Polygon ? 0.1 : 0.25, 0.6);

    private static double Floor(double v) => double.IsFinite(v) ? Math.Max(v, MinCellSize) : MinCellSize;
}
