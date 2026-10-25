using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The storeys of ONE mounted location — the native twin of the browser's per-frame storey passes (client3d/src/
/// scene/tiles.ts <c>applyRoomVisibility</c>, <c>applyLevelDisplay</c>, <c>applyWallCulling</c>' storey half, the
/// ground-model line of <c>applyTileFade</c>; client3d/src/main.ts the door- and boundary-mark visibility and
/// <c>applyDoorLocks</c>). Every storey is mounted once (<see cref="RecipeMeshes"/>, the indoor specs in their room
/// groups); <see cref="Apply"/> only flips what shows for the location's <c>levelFilter</c>. The decisions are the
/// Core's (<see cref="SceneView"/> / <see cref="StoreyView"/>); this class writes them onto nodes, and only when the
/// filter, the interior state or the marks gate changed:
///
///   • every frame, every location: a room group shows when it is outdoor / always visible or on the filter's storey;
///   • an openable location at fade &gt; 0.03 (the level display): the storey slabs and the outline walls of the
///     filter's storey stand, the others go; room plates wear their solid twin on the displayed storey, their ghost
///     elsewhere; an outdoor outline wall turns solid once its storey has been displayed; a ground model hides
///     while a storey below ground is shown;
///   • door marks at fade &gt; 0.5, the filter's storey only; their lock look from the avatar's verdicts;
///   • boundary marks (world frame) only while the avatar may not step into the location.
/// </summary>
public sealed class LocationStoreys
{
    /// <summary>A declared room's group: its node, its storey, and whether it hangs off the tile (always shown).</summary>
    public sealed record RoomGroup(string Id, Node3D Node, int Level, bool Outdoor);

    private sealed record Swap(MeshInstance3D Mesh, int Level, Material Solid);

    public Dictionary<string, RoomGroup> Rooms { get; } = new();
    /// <summary>The level-switch buttons (empty = no switch: one storey or none).</summary>
    public List<LevelButton> Buttons { get; init; } = new();
    /// <summary>The switch's anchor: the first lift box, else null (→ (2.2, 0)).</summary>
    public P2? Elevator { get; init; }
    public double StoreyM { get; init; }
    /// <summary><c>floorYof</c>: the declared floor of a storey, null when undeclared.</summary>
    public Func<int, double?> FloorY { get; init; } = _ => null;
    /// <summary><c>tile.hasBasement</c>.</summary>
    public bool HasBasement { get; init; }
    /// <summary>The door marks (one group per storey) in the tile group; null when none were built.</summary>
    public Node3D? DoorMarks { get; private set; }
    /// <summary>The boundary marks in the WORLD frame (hung beside the tile group); null when none.</summary>
    public Node3D? BoundaryMarks { get; private set; }
    public List<RoomLabel> Labels { get; } = new();

    private readonly List<(MeshInstance3D Mesh, int Level)> _slabs = new();
    private readonly List<(MeshInstance3D Mesh, int Level)> _walls = new();
    private readonly List<(MeshInstance3D Mesh, int Level)> _outdoorWalls = new();
    private readonly List<Swap> _roomPlates = new();
    private readonly List<Swap> _outdoorWallSolids = new();
    private readonly List<(Node3D Node, int Level)> _doorStoreys = new();
    private readonly List<(MeshInstance3D Mesh, string[] Rooms)> _doorMeshes = new();
    private readonly HashSet<int> _solidLevels = new();
    private int? _displayFilter;
    private (int Filter, bool Display, bool Marks, bool Ground)? _applied;

    /// <summary>The storey the location's room plates were last displayed at (null = never: the composed ghosts).</summary>
    public int? DisplayFilter => _displayFilter;

    /// <summary>File one mounted recipe mesh under its storey rule.</summary>
    public void Add(RecipePiece piece)
    {
        var u = piece.Unit;
        switch (u.Role)
        {
            case StoreyRole.Slab:
                _slabs.Add((piece.Mesh, u.Level));
                break;
            case StoreyRole.OutlineWall when u.Outdoor:
                _outdoorWalls.Add((piece.Mesh, u.Level));
                if (piece.Solid is { } ws) _outdoorWallSolids.Add(new Swap(piece.Mesh, u.Level, ws));
                break;
            case StoreyRole.OutlineWall:
                _walls.Add((piece.Mesh, u.Level));
                break;
            case StoreyRole.RoomPlate when piece.Solid is { } ps:
                _roomPlates.Add(new Swap(piece.Mesh, u.Level, ps));
                break;
        }
    }

    // ---- per frame ----------------------------------------------------------------------------------------

    /// <summary>
    /// The storey passes of one frame for this location (<paramref name="fade"/> = its crossfade, 0 for a location
    /// that cannot open: the browser runs applyTileFade / applyLevelDisplay only for an openable tile).
    /// </summary>
    public void Apply(int filter, double fade, bool openable, LocationFade lf)
    {
        bool display = openable && StoreyView.LevelDisplayActive(fade);
        bool marks = StoreyView.MarksVisible(fade);
        bool ground = openable && StoreyView.GroundModelHidden(fade, filter);
        var key = (filter, display, marks, ground);
        if (_applied == key) return;
        bool filterChanged = _applied?.Filter != filter;
        _applied = key;

        // applyRoomVisibility — every resident, every frame (only the filter moves it).
        if (filterChanged)
            foreach (var r in Rooms.Values)
            {
                bool v = SceneView.RoomVisible(r.Outdoor, r.Level, filter);
                if (r.Node.Visible != v) r.Node.Visible = v;
            }

        if (display)
        {
            // applyLevelDisplay + the storey half of applyWallCulling.
            _displayFilter = filter;
            _solidLevels.Add(filter);
            foreach (var (m, lv) in _slabs) Set(m, StoreyView.SlabVisible(lv, filter));
            foreach (var (m, lv) in _walls) Set(m, StoreyView.OutlineWallStoreyVisible(lv, filter, true));
            foreach (var (m, lv) in _outdoorWalls) Set(m, StoreyView.OutlineWallStoreyVisible(lv, filter, true));
            foreach (var s in _roomPlates)
            {
                // storeyPieceOpacity: the displayed storey solid (1), every other one its composed ghost.
                var want = SceneView.StoreyPieceOpacity(s.Level, filter, 0) == 1 ? s.Solid : null;
                if (s.Mesh.MaterialOverride != want) s.Mesh.MaterialOverride = want;
            }
            foreach (var s in _outdoorWallSolids)
                if (_solidLevels.Contains(s.Level) && s.Mesh.MaterialOverride != s.Solid) s.Mesh.MaterialOverride = s.Solid;
        }
        else
        {
            // Closed: an outdoor outline wall stands whatever its storey (the culling and the filter run only with the
            // interior up); the interior pieces are hidden with the interior group anyway.
            foreach (var (m, lv) in _outdoorWalls) Set(m, StoreyView.OutlineWallStoreyVisible(lv, filter, false));
        }
        if (openable) lf.SetGroundHidden(ground);

        // Door marks: shown where the interior resolved, on the displayed storey only.
        if (DoorMarks is not null)
        {
            if (DoorMarks.Visible != marks) DoorMarks.Visible = marks;
            foreach (var (n, lv) in _doorStoreys) Set(n, lv == filter);
        }
    }

    private static void Set(Node3D n, bool visible)
    {
        if (n.Visible != visible) n.Visible = visible;
    }

    /// <summary>
    /// The lock look of the door marks (main.ts <c>applyDoorLocks</c>): locked red where a room behind the doorway is
    /// barred for the avatar — only in the avatar's own location, the room it stands in left out; and the boundary
    /// marks shown only while the location itself is refused (<c>isLocked(lockedLocations, id)</c>).
    /// </summary>
    public void ApplyLocks(LockState locks, string locationId)
    {
        var rooms = locks.RoomsFor(locationId);
        foreach (var (mesh, ids) in _doorMeshes)
        {
            var mat = StoreyView.DoorwayLock(ids, rooms, locks.AvatarRoom) is not null ? MarkLooks.Locked : MarkLooks.Open;
            if (mesh.MaterialOverride != mat) mesh.MaterialOverride = mat;
        }
        if (BoundaryMarks is not null) BoundaryMarks.Visible = StoreyView.IsLocked(locks.Locations, locationId);
    }

    /// <summary>The door-mark meshes and whether each wears the locked look (for the check).</summary>
    public IEnumerable<(MeshInstance3D Mesh, string[] Rooms, int Level)> DoorMeshes()
    {
        foreach (var (mesh, rooms) in _doorMeshes)
            yield return (mesh, rooms, (int)mesh.GetParent().GetMeta("level").AsInt32());
    }

    // ---- the marks (built at the mount) ---------------------------------------------------------------------

    /// <summary>
    /// <c>buildDoorMarks</c>: one group per DECLARED storey (<c>scene.levels</c>) with a quad per usable doorway —
    /// <see cref="SceneView.DoorMarkTransform"/> in the TILE frame (the group carries the tile's turn), depth floor =
    /// the storey's first non-pane wall, gold at 0.35 (locked: iron red at 0.6), drawn late, never picked, hidden
    /// until the interior has resolved. Built for a building only.
    /// </summary>
    public void BuildDoorMarks(Node3D tileGroup, ScenePayload scene)
    {
        var root = new Node3D { Name = "DoorMarks", Visible = false };
        foreach (var level in scene.Levels.Select(l => l.Level))
        {
            var marks = StoreyView.DoorMarkers(scene.Doorways, level);
            if (marks.Count == 0) continue;
            double thickness = StoreyView.DoorMarkThickness(scene.Walls, level);
            var storey = new Node3D { Name = $"DoorMarks_L{level}" };
            storey.SetMeta("level", level);
            foreach (var d in marks)
            {
                var t = SceneView.DoorMarkTransform(d.WidthM, thickness, d.Along, d.AtWorld, d.BaseY);
                var mesh = MarkMesh(t, MarkLooks.Open);
                storey.AddChild(mesh);
                _doorMeshes.Add((mesh, d.Rooms));
            }
            root.AddChild(storey);
            _doorStoreys.Add((storey, level));
        }
        if (root.GetChildCount() == 0)
        {
            root.Free();
            return;
        }
        tileGroup.AddChild(root);
        DoorMarks = root;
        _applied = null;
    }

    /// <summary>
    /// <c>buildBoundaryMarks</c>: a red quad on every boundary opening with a positive width, in the WORLD frame (the
    /// payload point and its inward direction turned by the tile, y = the ground there + 0.05,
    /// <see cref="SceneView.BoundaryMarkTransform"/>); hidden until the avatar is refused the location.
    /// </summary>
    public void BuildBoundaryMarks(string locationId, TileFrame frame, ScenePayload scene, Func<double, double, double> groundAt)
    {
        var root = new Node3D { Name = $"BoundaryMarks_{locationId}", Visible = false };
        foreach (var o in scene.BoundaryOpenings)
        {
            if (!double.IsFinite(o.WidthM) || o.WidthM <= 0) continue;
            var at = SceneView.TileToWorld(frame, o.AtWorld.X, o.AtWorld.Z);
            var inward = SceneView.TileDirToWorld(frame.Yaw, o.Inward.X, o.Inward.Z);
            var t = SceneView.BoundaryMarkTransform(o.WidthM, inward, at.X, at.Z, groundAt(at.X, at.Z));
            root.AddChild(MarkMesh(t, MarkLooks.Locked));
        }
        if (root.GetChildCount() == 0)
        {
            root.Free();
            return;
        }
        BoundaryMarks = root;
    }

    private static MeshInstance3D MarkMesh(MarkTransform t, Material look)
    {
        var mesh = new MeshInstance3D
        {
            Mesh = MarkLooks.Quad,
            MaterialOverride = look,
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            Position = new Vector3((float)t.Position.X, (float)t.Position.Y, (float)t.Position.Z),
            Rotation = new Vector3(0, (float)t.Yaw, 0),
            Scale = new Vector3((float)t.Scale.X, (float)t.Scale.Y, (float)t.Scale.Z),
        };
        mesh.SetMeta(LocationFade.OverlayMeta, true);
        return mesh;
    }
}

/// <summary>
/// The looks of the flat marks (main.ts <c>DOOR_MARK_GEO</c> / <c>DOOR_MARK_MAT</c> / <c>DOOR_MARK_LOCKED_MAT</c>): a
/// unit quad in the XZ plane facing up, and two unlit, translucent, depth-write-free materials drawn late
/// (<c>renderOrder 3</c>). The browser clones the pair per tile only because its occlusion fade writes the material's
/// opacity; the native occlusion rides on the instance transparency, so one shared pair serves every location.
/// </summary>
public static class MarkLooks
{
    private static PlaneMesh? _quad;
    private static StandardMaterial3D? _open, _locked;

    /// <summary><c>PlaneGeometry(1, 1).rotateX(−π/2)</c>: Godot's plane already lies in XZ facing +y.</summary>
    public static PlaneMesh Quad => _quad ??= new PlaneMesh { Size = new Vector2(1, 1) };

    /// <summary>The gold of the UI, <c>0xf2d98c</c> at 0.35.</summary>
    public static StandardMaterial3D Open => _open ??= Make(new Color(0xf2 / 255f, 0xd9 / 255f, 0x8c / 255f, 0.35f));
    /// <summary>A locked threshold: iron red <c>0x9b3b2f</c> at 0.6.</summary>
    public static StandardMaterial3D Locked => _locked ??= Make(new Color(0x9b / 255f, 0x3b / 255f, 0x2f / 255f, 0.6f));

    private static StandardMaterial3D Make(Color c) => new()
    {
        ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
        AlbedoColor = c,
        Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
        DepthDrawMode = BaseMaterial3D.DepthDrawModeEnum.Disabled,
        RenderPriority = 3,
    };
}

/// <summary>
/// One room's name over the open interior (sceneRecipe.ts mountShell step 16, the <c>.room-label</c> CSS): system-ui
/// 11 px, <c>#f5efe2</c> on <c>rgba(30, 34, 40, .75)</c>, a 1 px border <c>rgba(242, 205, 110, .5)</c>, radius 9,
/// padding 1 × 7 px, centred on its anchor (CSS2D) — at the room rectangle's centre,
/// <c>floorY + min(1.5, 0.8·storey_m)</c> up, inside the room's group (so the storey filter, the interior and the
/// neighbour occlusion take it along). Shown while the location's labels are on (<see cref="StoreyView.LabelsOn"/>).
/// </summary>
public sealed class RoomLabel : IOverlayLabel
{
    public const int FontSize = 11;
    public const float PadX = 7, PadY = 1, Border = 1, Radius = 9;
    public static readonly Color TextColor = new("f5efe2");
    private static StyleBoxFlat? _box;
    private readonly TextLine _line;

    public RoomLabel(string roomId, string text, Node3D parent, Vector3 local)
    {
        RoomId = roomId;
        Text = text;
        Parent = parent;
        Local = local;
        _line = LabelStyle.Line(text, LabelStyle.Sans, FontSize);
        var s = _line.GetSize();
        Size = new Vector2(s.X + 2 * (PadX + Border), s.Y + 2 * (PadY + Border));
    }

    public string RoomId { get; }
    public string Text { get; }
    /// <summary>The room group the label hangs in.</summary>
    public Node3D Parent { get; }
    /// <summary>The tile-local point (the room group sits at the tile origin).</summary>
    public Vector3 Local { get; }
    public Vector3 Anchor => Parent.GlobalTransform * Local;
    public Vector2 Size { get; }

    public static StyleBoxFlat Box => _box ??= new StyleBoxFlat
    {
        BgColor = new Color(30 / 255f, 34 / 255f, 40 / 255f, 0.75f),
        BorderColor = new Color(242 / 255f, 205 / 255f, 110 / 255f, 0.5f),
        BorderWidthLeft = (int)Border, BorderWidthTop = (int)Border, BorderWidthRight = (int)Border, BorderWidthBottom = (int)Border,
        CornerRadiusTopLeft = (int)Radius, CornerRadiusTopRight = (int)Radius,
        CornerRadiusBottomLeft = (int)Radius, CornerRadiusBottomRight = (int)Radius,
        AntiAliasing = true,
    };

    public void Draw(CanvasItem canvas, Vector2 topLeft)
    {
        canvas.DrawStyleBox(Box, new Rect2(topLeft, Size));
        _line.Draw(canvas.GetCanvasItem(), topLeft + new Vector2(Border + PadX, Border + PadY), TextColor);
    }
}
