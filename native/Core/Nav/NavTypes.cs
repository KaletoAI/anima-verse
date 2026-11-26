using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

// The Godot-free navigation source of one location (plan 2026-11-25-client-ausfuehrung-e2, decisions 2, 7, 8, 13):
// 2D outlines per storey in WORLD xz, heights as numbers, built by NavSource.Build and baked by the client.

/// <summary>A walkable area of one storey: outline and holes in world xz (counter-clockwise in (x, z)).</summary>
public sealed record NavFloor(P2[] Outline, P2[][] Holes);

/// <summary>
/// Something the agent cannot walk through, as a world-xz outline with its height band in world metres.
/// <see cref="Kind"/> is <c>"wall"</c>, <c>"seal"</c> (a door gap closed for the storey mesh) or <c>"prop"</c>.
/// </summary>
public sealed record NavObstacle(P2[] Outline, double BottomY, double TopY, string Kind);

/// <summary>
/// The walkable region across a sealed doorway (decision 2; fix plan "Kollision im nativen Client", step 2): an hourglass of
/// three convex parts. <see cref="Parts"/>[0] is the neck, ±(w/2 − r) along the wall and ±t/2 across it; [1] and [2] are the
/// funnels, one per side, each a trapezoid from the wall face (±(w/2 − r) wide) to the storey edge t/2 + r off the wall line
/// (±w/2 wide), so a walk that meets the door off centre slides into the neck instead of stopping. Every part is
/// counter-clockwise in (x, z) (positive shoelace area) and starts at the corner with the smallest x + z (then x): an
/// axis-aligned rectangle runs (x0, z0) → (x1, z0) → (x1, z1) → (x0, z1). <see cref="Outside"/> is the doorway's own
/// <c>outside</c> flag; <see cref="OuterPoint"/> (outside doors only) = threshold centre + outward normal · (t/2 + r).
/// </summary>
public sealed record NavThreshold(int Doorway, int Level, P2[][] Parts, double Y, string[] Rooms, bool Outside, P2? OuterPoint);

/// <summary>One off-mesh connection: a stair flight or one lift hop between two neighbouring stops.</summary>
public sealed record NavLinkSpec(ulong Owner, string Kind, Vec3 Start, Vec3 End, int FromLevel, int ToLevel, double EnterCost);

/// <summary>
/// One storey's source. <see cref="FollowGround"/>: vertices outside every <see cref="Hulls"/> polygon sit on the
/// terrain, inside on <see cref="FloorY"/> (decision 7). A floor's holes are only those no other plate of the storey covers.
/// </summary>
public sealed record NavStoreySource(int Level, double FloorY, bool FollowGround, IReadOnlyList<P2[]> Hulls,
                                     IReadOnlyList<NavFloor> Floors, IReadOnlyList<NavObstacle> Obstacles);

/// <summary>A finding of the build: <c>door_too_narrow</c> (doorway index) or <c>boundary_offset</c> (−1).</summary>
public sealed record NavProblem(string Kind, int Doorway);

/// <summary>The whole navigation source of a location plus its cache key (SHA-256, lowercase hex).</summary>
public sealed record NavSourceData(IReadOnlyList<NavStoreySource> Storeys, IReadOnlyList<NavThreshold> Thresholds,
                                   IReadOnlyList<NavLinkSpec> Links, IReadOnlyList<NavProblem> Problems, string Fingerprint)
{
    /// <summary>No walkable area at all: nothing to bake.</summary>
    public bool IsEmpty => Storeys.All(s => s.Floors.Count == 0);
}

/// <summary>
/// One obstacle rectangle of a furniture placement on storey <see cref="Level"/>: a world-xz outline (counter-clockwise in
/// (x, z)) and the height band it occupies (<see cref="PropFootprint"/>; a placement gives one entry per rectangle).
/// </summary>
public sealed record NavProp(int Level, double BottomY, double TopY, P2[] Outline)
{
    /// <summary>An axis-aligned world box as one entry (outline (x0, z0) → (x1, z0) → (x1, z1) → (x0, z1)).</summary>
    public static NavProp Box(int level, Vec3 min, Vec3 max)
        => new(level, min.Y, max.Y, new[] { new P2(min.X, min.Z), new P2(max.X, min.Z), new P2(max.X, max.Z), new P2(min.X, max.Z) });
}

/// <summary>Navigation layers: one bit per storey (level + 8, clamped to 0…30), links on bit 31; queries use all.</summary>
public static class NavLayers
{
    public const uint Links = 1u << 31;
    public const uint All = uint.MaxValue;

    public static uint ForLevel(int level) => 1u << System.Math.Clamp(level + 8, 0, 30);
}

/// <summary>Link owner ids (decision 13): stairs <c>(1 &lt;&lt; 16) | flight</c>, lift <c>(2 &lt;&lt; 16) | (lowerLevel + 128)</c>.</summary>
public static class NavLinkOwner
{
    private const ulong StairsTag = 1UL << 16, ElevatorTag = 2UL << 16, Low = 0xFFFF;

    public static ulong Stairs(int flight) => StairsTag | ((ulong)flight & Low);

    public static ulong Elevator(int lowerLevel) => ElevatorTag | ((ulong)(lowerLevel + 128) & Low);

    public static bool TryStairs(ulong owner, out int flight)
    {
        flight = (int)(owner & Low);
        return (owner & ~Low) == StairsTag;
    }

    public static bool TryElevator(ulong owner, out int lowerLevel)
    {
        lowerLevel = (int)(owner & Low) - 128;
        return (owner & ~Low) == ElevatorTag;
    }
}
