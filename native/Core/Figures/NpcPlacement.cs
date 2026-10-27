using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>A held place of a worldmap row: the marker id and the slot (null = <c>'pair'</c>, the mean of the slots).</summary>
public readonly record struct PlaceRef(string Id, int? Slot);

/// <summary>What the room ladder reads off a worldmap row (a subset of <c>MapCharacter</c>).</summary>
public sealed record PlacementRow(string Name, P2? Pos = null, PlaceRef? Place = null, string ActivityAnimation = "",
                                  string MovementTargetId = "");

/// <summary>
/// The tile as the ladder reads it — view state and inventory in one (npcPlacement.ts <c>PlacementTile</c>): the frame,
/// footprint width and kind, the interior fade and shown storey, and the room maps keyed by room id AND name.
/// </summary>
public sealed class PlacementTile
{
    public required TileFrame Frame { get; init; }
    public double Width { get; init; }
    public bool IsBuilding { get; init; }
    /// <summary>View state: interior fade (&gt; 0.5 = revealed) and the shown storey.</summary>
    public double Fade { get; init; }
    public int LevelFilter { get; init; }
    public IReadOnlySet<string> AlwaysVisibleRooms { get; init; } = new HashSet<string>();
    public IReadOnlyDictionary<string, Vec3> RoomCenters { get; init; } = new Dictionary<string, Vec3>();
    public IReadOnlyDictionary<string, int> RoomLevels { get; init; } = new Dictionary<string, int>();
    public IReadOnlyDictionary<string, Dictionary<string, PlaceEntry>> RoomMarkers { get; init; }
        = new Dictionary<string, Dictionary<string, PlaceEntry>>();
    public IReadOnlyDictionary<string, IReadOnlyList<Vec3>> RoomSitSpots { get; init; } = new Dictionary<string, IReadOnlyList<Vec3>>();
    public IReadOnlyDictionary<string, IReadOnlyList<Vec3>> RoomLieSpots { get; init; } = new Dictionary<string, IReadOnlyList<Vec3>>();
    /// <summary>The storey corridors' room ids (<c>tile.corridors[].roomId</c>).</summary>
    public IReadOnlyList<string> Corridors { get; init; } = Array.Empty<string>();
}

/// <summary>The lookups the ladder needs from around it (npcPlacement.ts <c>PlacementContext</c>).</summary>
public sealed class PlacementContext
{
    /// <summary>The location's id (a movement target equal to it is not faced).</summary>
    public string LocId { get; init; } = "";
    /// <summary>View state: the tile is in the NEAR ring (seats and surfaces exist).</summary>
    public bool Near { get; init; }
    /// <summary>The room a character is in (null / "" = none).</summary>
    public Func<string, string?> RoomOf { get; init; } = _ => null;
    /// <summary>Where the figure was drawn the last time.</summary>
    public Func<string, ShownPlacement?> ShownOf { get; init; } = _ => null;
    /// <summary>The point a held place puts the figure on (<c>slotFor</c>).</summary>
    public Func<PlaceEntry, int?, Vec3?> SeatOf { get; init; } = (e, slot) => PlaceSlots.SlotFor(e.Slots, slot);
    /// <summary>The standing height in a room at a TILE-LOCAL point (<c>tiles.roomStandY</c>), null = unknown.</summary>
    public Func<string, double, double, double?> RoomStandY { get; init; } = (_, _, _) => null;
    /// <summary>The ground a huddle figure stands on at a WORLD point (<c>tiles.tileGroundY</c>).</summary>
    public Func<double, double, double> GroundY { get; init; } = (_, _) => 0;
    /// <summary>The centre of a known location, null when unknown.</summary>
    public Func<string, Vec3?> TargetCentre { get; init; } = _ => null;
}

/// <summary>One figure of a location as the ladder places it; <see cref="Face"/> / <see cref="Lean"/> null = none.</summary>
public sealed record LocatedFigure(PlacementRow Row, string Branch, Vec3 Pos, Vec3? Face, (double Tilt, double Roll)? Lean,
                                   string? InRoom, bool InteriorShown, bool Hidden, FigureTransition Transition)
{
    public string SurfaceGroup { get; init; } = "ground";
}

/// <summary>
/// JavaScript's <c>String.prototype.localeCompare</c> without arguments (the ICU root collation V8 uses): .NET's
/// InvariantCulture runs on the same ICU collator, so "bo" sorts between "Ada" and "Cem" (an ordinal compare puts it
/// last). Proven against the browser's order in tests/NpcPlacementVectorTests.cs.
/// </summary>
public sealed class LocaleCompare : IComparer<string>
{
    public static readonly LocaleCompare Instance = new();

    public int Compare(string? a, string? b) => string.Compare(a, b, CultureInfo.InvariantCulture, CompareOptions.None);
}

/// <summary>
/// WHERE THE FIGURES OF ONE LOCATION ARE DRAWN — client3d/src/game/npcPlacement.ts (<c>huddleOffset</c>,
/// <c>placeAtLocation</c>), the room ladder of <c>main.computeNpcPlacements</c>; checked against
/// shared/test-vectors/npc_placement.json. Rows sorted by <see cref="LocaleCompare"/> (a stable sort, like
/// <c>Array.sort</c>); per character: in a revealed room seat &gt; sit/lie pool &gt; corridor stand &gt; server
/// <c>pos</c> at the room's standing height &gt; room centre; otherwise the huddle on the tile ground. Facing towards the
/// movement target's place; hidden on another storey or in a closed interior; transition from the last placement.
/// </summary>
public static class NpcPlacement
{
    /// <summary><c>huddleOffset</c>: a 2.3 m row at width·0.36 in front of a building, a 2.6 m ring on an open place.</summary>
    public static P2 HuddleOffset(bool isBuilding, double width, int index, int count)
    {
        if (isBuilding) return new P2((index - (count - 1) / 2.0) * 2.3, width * 0.36);
        double angle = (double)index / Math.Max(count, 1) * Math.PI * 2;
        return new P2(Math.Cos(angle) * 2.6, Math.Sin(angle) * 2.6);
    }

    private static bool Truthy(double? v) => v is { } x && x != 0 && !double.IsNaN(x);

    public static List<LocatedFigure> PlaceAtLocation(IReadOnlyList<PlacementRow> rows, PlacementTile tile, PlacementContext ctx)
    {
        var chars = rows.OrderBy(r => r.Name, LocaleCompare.Instance).ToList();
        var roomMates = new Dictionary<string, List<string>>();
        foreach (var c in chars)
        {
            var room = ctx.RoomOf(c.Name);
            if (string.IsNullOrEmpty(room)) continue;
            if (!roomMates.TryGetValue(room, out var list)) roomMates[room] = list = new List<string>();
            list.Add(c.Name);
        }
        var result = new List<LocatedFigure>(chars.Count);
        for (int i = 0; i < chars.Count; i++)
        {
            var c = chars[i];
            string branch;
            Vec3 pos;
            Vec3? face = null;
            (double, double)? lean = null;
            var surfaceGroup = "ground";
            var room = ctx.RoomOf(c.Name);
            bool hasRoom = !string.IsNullOrEmpty(room);
            Vec3? roomCenter = hasRoom && tile.RoomCenters.TryGetValue(room!, out var rc) ? rc : null;
            bool interiorShown = tile.Fade > 0.5 || (hasRoom && tile.AlwaysVisibleRooms.Contains(room!));
            string? inRoom = roomCenter is not null && hasRoom && interiorShown ? room : null;
            if (inRoom is not null && roomCenter is { } centre)
            {
                int idx = roomMates[inRoom].IndexOf(c.Name);
                var kind = c.ActivityAnimation ?? "";
                PlaceEntry? held = ctx.Near && c.Place is { } pr && tile.RoomMarkers.TryGetValue(inRoom, out var byId)
                                   && byId.TryGetValue(pr.Id, out var e) ? e : null;
                Vec3? seat = held is not null && c.Place is { } p2 ? ctx.SeatOf(held, p2.Slot) : null;
                IReadOnlyList<Vec3>? sit = ctx.Near && tile.RoomSitSpots.TryGetValue(inRoom, out var s) ? s : null;
                IReadOnlyList<Vec3>? lieDown = ctx.Near && tile.RoomLieSpots.TryGetValue(inRoom, out var l) ? l : null;
                var family = FigureClips.AnimFamily(kind);
                IReadOnlyList<Vec3>? pool = family == "lie" ? (lieDown is { Count: > 0 } ? lieDown : sit)
                    : family == "sit" ? (sit is { Count: > 0 } ? sit : lieDown) : null;
                if (held is not null && seat is { } seatAt)
                {
                    branch = "seat";
                    pos = seatAt;
                    surfaceGroup = ClipHeightOffsets.Surface(held.Group);
                    if (held.Rotation is { } rot)
                    {
                        double a = rot * (Math.PI / 180);
                        var dir = SceneView.TileDirToWorld(tile.Frame.Yaw, Math.Sin(a), Math.Cos(a));
                        face = new Vec3(dir.X, 0, dir.Z);
                    }
                    if (Truthy(held.Tilt) || Truthy(held.Roll))
                        lean = (Truthy(held.Tilt) ? held.Tilt!.Value : 0, Truthy(held.Roll) ? held.Roll!.Value : 0);
                }
                else if (pool is { Count: > 0 })
                {
                    branch = "pool";
                    pos = pool[idx % pool.Count];
                    surfaceGroup = ReferenceEquals(pool, lieDown) ? "lie" : "seat";
                }
                else if (tile.Corridors.Contains(inRoom))
                {
                    branch = "corridor";
                    pos = centre;
                }
                else if (c.Pos is { } at)
                {
                    branch = "pos";
                    var local = SceneView.WorldToTile(tile.Frame, at.X, at.Z);
                    pos = new Vec3(at.X, ctx.RoomStandY(inRoom, local.X, local.Z) ?? centre.Y, at.Z);
                }
                else
                {
                    branch = "centre";
                    pos = centre;
                }
            }
            else
            {
                branch = "huddle";
                var slot = HuddleOffset(tile.IsBuilding, tile.Width, i, chars.Count);
                var w = SceneView.TileToWorld(tile.Frame, slot.X, slot.Z);
                pos = new Vec3(w.X, ctx.GroundY(w.X, w.Z), w.Z);
            }
            var transition = FigureGround.Transition(ctx.ShownOf(c.Name), new ShownPlacement(inRoom, interiorShown));
            var target = string.IsNullOrEmpty(c.MovementTargetId) ? null : ctx.TargetCentre(c.MovementTargetId);
            if (target is { } t && c.MovementTargetId != ctx.LocId && face is null)
                face = new Vec3(t.X - pos.X, 0, t.Z - pos.Z);
            bool wrongStorey = inRoom is not null && tile.Fade > 0.5 && !tile.AlwaysVisibleRooms.Contains(inRoom)
                               && (tile.RoomLevels.TryGetValue(inRoom, out var lv) ? lv : 0) != tile.LevelFilter;
            bool roomIsClosed = inRoom is null && hasRoom && roomCenter is not null;
            result.Add(new LocatedFigure(c, branch, pos, face, lean, inRoom, interiorShown, wrongStorey || roomIsClosed, transition)
            {
                SurfaceGroup = surfaceGroup,
            });
        }
        return result;
    }
}
