using System;

namespace AnimaNative.Nav;

/// <summary>
/// The bake parameters (decision 1; the polygon bake won the measurement of decision 9, plan E2 Task 5,
/// docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md): agent radius 0.25 m, height 1.8 m,
/// climb 0.25 m, slope 40° (the <c>max_slope_deg</c> default), cells 0.05 / 0.05, edge connection margin 0.1, link
/// connection radius 0.6 m.
/// </summary>
public sealed record NavBakeParams(double AgentRadius, double AgentHeight, double AgentMaxClimb, double AgentMaxSlopeDeg,
                                   double CellSize, double CellHeight, double EdgeConnectionMargin, double LinkConnectionRadius)
{
    /// <summary>Part of every fingerprint: raise it when the source rules or the bake change.</summary>
    public const int Version = 3;
    public const double MinCellSize = 0.05;
    public const double ElevatorEnterCost = 20;
    public const double ElevatorTravelCost = 10;

    /// <summary>The parameters every location is baked with.</summary>
    public static NavBakeParams Current { get; } = Create(0.05, 0.05);

    /// <summary>The parameters with the given cells, each floored at <see cref="MinCellSize"/> — the one clamp.</summary>
    public static NavBakeParams Create(double cellSize, double cellHeight)
        => new(0.25, 1.8, 0.25, 40, Floor(cellSize), Floor(cellHeight), 0.1, 0.6);

    private static double Floor(double v) => double.IsFinite(v) ? Math.Max(v, MinCellSize) : MinCellSize;
}
