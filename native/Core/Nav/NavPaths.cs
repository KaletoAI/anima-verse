using System.Collections.Generic;
using AnimaNative.Overview;

namespace AnimaNative.Nav;

// The seam between the Godot-free route logic and the client's navigation map (plan 2026-11-25-client-ausfuehrung-e2,
// decision 13). The client implements IPathProvider over NavigationServer3D; the tests use a hand-checkable fake.

/// <summary>
/// One path query's answer in world metres. <see cref="Owners"/>[i] is the link owner of point i, 0 for a region
/// point. Contract (decision 13): <c>Owners[i] ≠ 0</c> ⇒ the off-mesh link section is
/// <c>(Owners[i], Points[i], Points[i + 1])</c>; only the entry point carries the owner.
/// </summary>
public sealed record NavPath(IReadOnlyList<Vec3> Points, IReadOnlyList<ulong> Owners, double Length);

/// <summary>A navigation map the route logic can ask: shortest path and closest walkable point (3D, all storeys).</summary>
public interface IPathProvider
{
    /// <summary>The map answers with its current state (a fresh map or a lock change has taken effect).</summary>
    bool Ready { get; }

    NavPath Query(Vec3 from, Vec3 to);

    Vec3 Closest(Vec3 p);
}
