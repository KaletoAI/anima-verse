using System.Collections.Generic;
using System.Text.Json.Nodes;

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
    /// <summary>Task 57: exact public local/owned prop route uses its receipt clock and unsmoothed sampled path.</summary>
    public JsonObject? ExactPath { get; set; }
    public bool OwnedApproach { get; set; }
    public double CatchUpRate { get; set; }
    public bool AccessLogged { get; set; }
    public bool Settled { get; set; }
    public double ReceivedAt { get; set; }
}

/// <summary>
/// Task 43 / E6-T3: npcs.ts reckon observation, in world metres and elapsed real seconds. The poll stamp gates
/// measurement; a rejected interval retains RateMS, whereas a measured zero replaces it. Route adoption or
/// arrival discards the observation, so a later journey cannot inherit its rate. Arithmetic stays in TravelPath.
/// </summary>
public sealed record DeadReckoning((double X, double Z) Pos, double AtS, int Stamp, double? RateMS);
