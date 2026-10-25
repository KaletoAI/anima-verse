using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>A storey's slot in the level switch: its level and the button text.</summary>
public readonly record struct LevelButton(int Level, string Label);

/// <summary>
/// The storey decisions of the browser's open view that are not yet in a shared vector — the level switch, the
/// room labels, the door and boundary marks, the per-frame storey gates — ported from the inline code of
/// client3d/src/scene/sceneRecipe.ts (<c>mountShell</c> steps 16/17), client3d/src/scene/tiles.ts
/// (<c>applyLevelDisplay</c>, <c>applyTileFade</c>), client3d/src/main.ts (the frame hook, <c>buildDoorMarks</c>)
/// and client3d/src/game/doors.ts / locks.ts. The per-piece rules that ARE vector-checked stay in
/// <see cref="SceneView"/> (RoomVisible, StoreyPieceOpacity, WallVisible, BasementHole, DoorMarkTransform,
/// BoundaryMarkTransform); this class only adds what sits around them. Hand-derived cases: tests/StoreyViewTests.cs.
/// </summary>
public static class StoreyView
{
    /// <summary>The fade above which the interior is up and the level display runs (<c>tile.fade &gt; 0.03</c>).</summary>
    public const double InteriorUpFade = 0.03;
    /// <summary>The fade above which room labels and door marks show (<c>fade &gt; 0.5</c>).</summary>
    public const double LabelsFade = 0.5;
    /// <summary>The switch position without a lift: <c>elevatorXZ?.x ?? 2.2</c>, <c>?.y ?? 0</c>.</summary>
    public const double SwitchDefaultX = 2.2, SwitchDefaultZ = 0;

    // ---- the level switch (sceneRecipe.ts mountShell step 17) -------------------------------------------

    /// <summary>A switch is built only when the payload declares more than one storey (<c>levels.length &gt; 1</c>).</summary>
    public static bool HasLevelSwitch(IReadOnlyCollection<SceneLevel> levels) => levels.Count > 1;

    /// <summary>One button per declared storey, sorted ascending; <c>'EG'</c> for 0, else <c>`${lv}.`</c>.</summary>
    public static List<LevelButton> SwitchButtons(IEnumerable<SceneLevel> levels)
        => levels.Select(l => l.Level).OrderBy(l => l).Select(l => new LevelButton(l, SwitchLabel(l))).ToList();

    public static string SwitchLabel(int level)
        => level == 0 ? "EG" : level.ToString(CultureInfo.InvariantCulture) + ".";

    /// <summary>
    /// <c>elevatorXZ</c>: the centre (x, z) of the FIRST extra whose kind starts with <c>elevator_</c> — a stair box
    /// never anchors the switch (finding 2026-08-25). Null without a lift.
    /// </summary>
    public static P2? ElevatorAnchor(IEnumerable<SceneExtra> extras)
    {
        foreach (var e in extras)
            if (e.Kind.StartsWith("elevator_", StringComparison.Ordinal) && e.Center.Length >= 3)
                return new P2(e.Center[0], e.Center[2]);
        return null;
    }

    /// <summary>
    /// <c>swAt(lv)</c>, tile-local: (elevator x ?? 2.2, (floorYof(lv) ?? lv·storey_m) + storey_m·⅔, elevator z ?? 0).
    /// <paramref name="floorY"/> = the level's declared <c>floor_y</c>, null when the level is not declared.
    /// </summary>
    public static Vec3 SwitchPosition(P2? elevator, double? floorY, int level, double storeyM)
        => new(elevator?.X ?? SwitchDefaultX, (floorY ?? level * storeyM) + storeyM * (2.0 / 3.0), elevator?.Z ?? SwitchDefaultZ);

    // ---- room labels (mountShell step 16 + tiles.ts deriveRoomSpots' rectangle) -------------------------

    /// <summary>
    /// <c>areaLoc</c>: a nature site, an area location, an area-detail scene, or a building model shown as ground or
    /// shell area — zones instead of rooms, so no room names are drawn.
    /// </summary>
    public static bool AreaLocation(bool natureSite, bool isBuilding, bool areaDetail, IEnumerable<SceneModelSpec> models)
        => natureSite || !isBuilding || areaDetail
           || models.Any(m => m.Role == "building" && (m.Display == "ground" || m.Display == "shell_area"));

    /// <summary>
    /// <c>tile.roomFloors</c>' hulls: storey 0 from <c>floor_plan</c> (a <c>polygon_world</c> of at least 3 points), a
    /// declared storey (level ≠ 0) from its room block's own <c>outline</c> (at least 3 points) — the second loop
    /// writes over the first, as the browser's <c>Map.set</c> does.
    /// </summary>
    public static Dictionary<string, P2[]> RoomHulls(ScenePayload scene)
    {
        var hulls = new Dictionary<string, P2[]>();
        foreach (var f in scene.FloorPlan)
            if (f.RoomId.Length > 0 && f.PolygonWorld.Length >= 3) hulls[f.RoomId] = f.PolygonWorld;
        foreach (var r in scene.Rooms)
            if (r.RoomId.Length > 0 && r.Level != 0 && r.Outline.Length >= 3) hulls[r.RoomId] = r.Outline;
        return hulls;
    }

    /// <summary><c>roomRects</c>' centre: the middle of the hull's bounding box; null for an empty hull.</summary>
    public static P2? RectCentre(IReadOnlyList<P2>? hull)
    {
        if (hull is null || hull.Count == 0) return null;
        double minX = double.PositiveInfinity, maxX = double.NegativeInfinity, minZ = double.PositiveInfinity, maxZ = double.NegativeInfinity;
        foreach (var p in hull)
        {
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        if (!double.IsFinite(minX)) return null;
        return new P2((minX + maxX) / 2, (minZ + maxZ) / 2);
    }

    /// <summary>
    /// The label's tile-local point: the rectangle centre (else (0, 0)) at <c>floorY + min(1.5, storey_m·0.8)</c>,
    /// floorY = <c>floorYof(roomLevel ?? 0) ?? 0</c>.
    /// </summary>
    public static Vec3 RoomLabelPosition(P2? centre, double? floorY, double storeyM)
        => new(centre?.X ?? 0, (floorY ?? 0) + Math.Min(1.5, storeyM * 0.8), centre?.Z ?? 0);

    // ---- door marks (main.ts buildDoorMarks, game/doors.ts doorMarkers) ----------------------------------

    /// <summary><c>doorMarkers(scene, level)</c>: the usable doorways of one storey, in payload order.</summary>
    public static List<SceneDoorway> DoorMarkers(IEnumerable<SceneDoorway> doorways, int level)
        => doorways.Where(d => d.Level == level && d.Usable).ToList();

    /// <summary>
    /// The depth floor of a storey's marks: the thickness of its FIRST wall that is not a pane (glass / leaf are
    /// thinner on purpose), 0 when the storey has none.
    /// </summary>
    public static double DoorMarkThickness(IEnumerable<SceneWall> walls, int level)
        => walls.FirstOrDefault(w => w.Level == level && !w.Glass && !w.Leaf)?.Thickness ?? 0;

    // ---- locks (game/locks.ts) ---------------------------------------------------------------------------

    /// <summary><c>isLocked</c>: the id is a KEY of the map (an empty reason is still a lock).</summary>
    public static bool IsLocked(IReadOnlyDictionary<string, string>? locks, string id)
        => locks is not null && id.Length > 0 && locks.ContainsKey(id);

    /// <summary>
    /// <c>doorwayLock</c>: the reason of the first locked room behind the doorway (the room the avatar stands in left
    /// out), "" for a lock without words, null when nothing behind it is barred.
    /// </summary>
    public static string? DoorwayLock(IEnumerable<string> roomIds, IReadOnlyDictionary<string, string> locks, string currentRoom = "")
    {
        foreach (var id in roomIds)
        {
            if (id == currentRoom) continue;
            if (IsLocked(locks, id)) return locks[id];
        }
        return null;
    }

    // ---- the per-frame gates (main.ts frame hook, tiles.ts applyTileFade / applyLevelDisplay) -------------

    /// <summary>The level display and the wall culling run for an openable tile while its fade is above 0.03.</summary>
    public static bool LevelDisplayActive(double fade) => fade > InteriorUpFade;

    /// <summary>A storey's contour plate (<c>levelSlabs</c>) shows only on its own storey.</summary>
    public static bool SlabVisible(int level, int filter) => level == filter;

    /// <summary>
    /// The storey half of <c>applyWallCulling</c> for an outline wall (the camera half runs in the recipe shader,
    /// the GPU twin of <see cref="SceneView.WallVisible"/>). While the level display is off, an OUTDOOR outline wall
    /// keeps standing (the native reading of "the culling runs only with the interior up", Task 15).
    /// </summary>
    public static bool OutlineWallStoreyVisible(int level, int filter, bool levelDisplay) => !levelDisplay || level == filter;

    /// <summary><c>sm.visible = !(f &gt; 0.03 &amp;&amp; levelFilter &lt; 0)</c> for a ground model: a basement view hides it.</summary>
    public static bool GroundModelHidden(double fade, int filter) => fade > InteriorUpFade && filter < 0;

    /// <summary>The ground opens over a basement only while a storey below ground is the displayed one.</summary>
    public static bool BasementOpen(bool hasBasement, double fade, int filter) => hasBasement && fade > InteriorUpFade && filter < 0;

    /// <summary><c>tile.hasBasement</c>: any declared level below 0.</summary>
    public static bool HasBasement(IEnumerable<SceneLevel> levels) => levels.Any(l => l.Level < 0);

    /// <summary>Door marks (and room labels) show once the interior has resolved: <c>fade &gt; 0.5</c>.</summary>
    public static bool MarksVisible(double fade) => fade > LabelsFade;

    /// <summary>
    /// The room labels' visibility: <c>interiorLabels.visible = labelsVisible</c> is written by <c>applyTileFade</c>,
    /// which runs only for an openable tile — a label of a tile that cannot open keeps its initial <c>visible</c>
    /// (true); its parent chain still decides.
    /// </summary>
    public static bool LabelsOn(bool openable, double fade) => !openable || fade > LabelsFade;
}

/// <summary>
/// The avatar's lock verdicts as the HUD publishes them (bus.ts <c>lockedRooms</c> / <c>lockedLoc</c> /
/// <c>lockedLocations</c>, HUD-owned) plus the room the avatar stands in (main.ts <c>roomOf.get(avatarName)</c>).
/// </summary>
public sealed record LockState(IReadOnlyDictionary<string, string> Rooms, string Loc,
                               IReadOnlyDictionary<string, string> Locations, string AvatarRoom)
{
    public static readonly LockState None = new(new Dictionary<string, string>(), "", new Dictionary<string, string>(), "");

    /// <summary>
    /// The HUD's fields as they arrive over the bridge: <c>lockedRooms</c> / <c>lockedLocations</c> objects of id →
    /// reason (a non-string reason is a lock without words, ""), <c>lockedLoc</c> a string; anything else reads empty.
    /// </summary>
    public static LockState FromHud(System.Text.Json.Nodes.JsonNode? rooms, System.Text.Json.Nodes.JsonNode? loc,
                                    System.Text.Json.Nodes.JsonNode? locations, string avatarRoom)
    {
        static Dictionary<string, string> Map(System.Text.Json.Nodes.JsonNode? n)
        {
            var d = new Dictionary<string, string>();
            if (n is System.Text.Json.Nodes.JsonObject o)
                foreach (var (k, v) in o)
                    d[k] = v is System.Text.Json.Nodes.JsonValue jv && jv.TryGetValue<string>(out var str) ? str : "";
            return d;
        }
        string l = loc is System.Text.Json.Nodes.JsonValue lv && lv.TryGetValue<string>(out var ls) ? ls : "";
        return new LockState(Map(rooms), l, Map(locations), avatarRoom);
    }

    /// <summary>The rooms painted locked in <paramref name="locationId"/>: only the avatar's own location (<c>lockedLoc</c>).</summary>
    public IReadOnlyDictionary<string, string> RoomsFor(string locationId) => locationId == Loc ? Rooms : None.Rooms;
}
