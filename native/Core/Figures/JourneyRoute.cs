using System.Collections.Generic;

namespace AnimaNative.Figures;

/// <summary>
/// Task 42 / E6-T2: npcs.ts route view state. Identity is journey id plus the full polyline; a payload stamp gates
/// reconciliation while cached 1 Hz placement may adopt paces. Target and display progress advance once per frame.
/// </summary>
public sealed class JourneyRoute
{
    public required string Key { get; init; }
    public required IReadOnlyList<(double X, double Z)> Points { get; init; }
    public required double TotalM { get; init; }
    public IReadOnlyList<double?>? Paces { get; set; }
    public double TargetM { get; set; }
    public double ShownM { get; set; }
    public int Stamp { get; set; }
}
