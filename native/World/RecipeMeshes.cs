using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scene;
using Godot;
using Vec3 = AnimaNative.Overview.Vec3;

namespace AnimaNative.World;

/// <summary>What one location's recipe primitives turned into (Task S3c: drawn vs. skipped BY REASON).</summary>
public sealed class RecipeStats
{
    /// <summary>Primitives the browser shows in this view: originals that stand visible + far-shell copies.</summary>
    public int Plates, Walls, Extras;
    /// <summary>Of the above: copies in the far-view shell (<c>buildFarShell</c>).</summary>
    public int ShellCopies;
    /// <summary>Not drawn: no area/length/volume (outline &lt; 3, zero-length wall, empty box) — the browser skips or builds nothing visible.</summary>
    public int Degenerate;
    /// <summary>Not shown: inside the interior group of a CLOSED location (mounted, the crossfade keeps it invisible) and not part of a far shell.</summary>
    public int Interior;
    /// <summary>
    /// Not shown at the build: in the OPEN location, but on another storey than the build's (<c>applyLevelDisplay</c> /
    /// <c>applyRoomVisibility</c> / the wall filter) — mounted all the same since Task 16, the switch shows it.
    /// </summary>
    public int Storey;
    /// <summary>Not drawn: a door leaf / window pane whose opening a model in <c>models[]</c> fills (<c>door_prop</c>, <c>window_model</c>).</summary>
    public int Panes;
    /// <summary>Of the drawn walls: outline walls of the open location that take part in the per-frame camera cull.</summary>
    public int CulledWalls;
    /// <summary>Primitives mounted in the interior group (shown only by the crossfade; the browser's <c>g</c>).</summary>
    public int InteriorMounted;
    public int Primitives => Plates + Walls + Extras;
    public int Skipped => Degenerate + Interior + Storey + Panes;

    public void Add(RecipeStats o)
    {
        Plates += o.Plates; Walls += o.Walls; Extras += o.Extras; ShellCopies += o.ShellCopies;
        Degenerate += o.Degenerate; Interior += o.Interior; Storey += o.Storey; Panes += o.Panes;
        CulledWalls += o.CulledWalls; InteriorMounted += o.InteriorMounted;
    }

    public string SkipSummary()
        => $"degenerate={Degenerate} interior={Interior} storey={Storey} panes={Panes}";
}

/// <summary>
/// The view state the stats describe: <see cref="Open"/> = the location's fade TARGET at the build (open or
/// closed), <see cref="LevelFilter"/> = the storey shown at the build (the stats count what the browser SHOWS then;
/// every storey is mounted either way), <see cref="FarShell"/> = it shows a far-view shell (<c>shellPlan</c> 'recipe').
/// </summary>
public sealed record RecipeView(bool Open, int LevelFilter, bool FarShell)
{
    public static readonly RecipeView Closed = new(false, 0, false);
}

/// <summary>One plate or wall the § B5a verify measures: its verify name, its targets and its box in the location frame.</summary>
public sealed record MeasuredPrimitive(string Name, List<PrimitiveTarget> Targets, VBox Local);

/// <summary>
/// The storey rule a recipe mesh follows at runtime (tiles.ts <c>applyLevelDisplay</c> / <c>applyWallCulling</c>):
///   <see cref="Slab"/>        — a storey's contour plate (<c>levelSlabs</c>): shown on its own storey only;
///   <see cref="RoomPlate"/>   — a room's floor plate (<c>levelRoomPlateMats</c>): drawn at <c>storeyPieceOpacity</c>;
///   <see cref="OutlineWall"/> — a facade piece (<c>outlineWalls</c>): its own storey only, camera-culled in the shader;
///   <see cref="Other"/>       — panes, leaves and extras: no storey rule of their own (their parent decides).
/// </summary>
public enum StoreyRole { Slab, RoomPlate, OutlineWall, Other }

/// <summary>
/// Where a recipe mesh hangs and which storey rule drives it: <see cref="Room"/> = the declared room whose group it
/// joins ("" = the interior group <c>g</c> itself — a room-less piece, or one whose room the payload does not
/// declare: <c>parentFor</c>), <see cref="Outdoor"/> = that room hangs straight off the tile (<c>outdoor_rooms</c> ∪
/// <c>always_visible</c>), <see cref="Level"/> = the storey the rule reads (0 for <see cref="StoreyRole.Other"/>).
/// </summary>
public readonly record struct PieceUnit(string Room, bool Outdoor, StoreyRole Role, int Level)
{
    /// <summary>Task 51: preserve the connection when batching extras by look; no added storey visibility rule.</summary>
    public VerticalTarget? Vertical { get; init; }
    public string Tag => Role switch
    {
        StoreyRole.Slab => $"slab{Level}",
        StoreyRole.RoomPlate => $"plate{Level}",
        StoreyRole.OutlineWall => $"wall{Level}",
        _ => "other",
    };
}

/// <summary>
/// One mounted recipe mesh: its unit, and for a ghosted piece whose storey rule can make it solid (a room plate, an
/// outdoor outline wall) the solid twin of its material (<see cref="Solid"/>, worn as <c>MaterialOverride</c> — the
/// browser writes <c>material.opacity</c> instead); null when the piece is solid anyway. <see cref="Cast"/> is the
/// browser's construction flag (Task 26c): only an upper storey's plate with a thickness casts
/// (<c>castShadow = plate.level &gt; 0 &amp;&amp; plate.thickness &gt; 0</c>); walls and extras keep three's default false.
/// The mesh carries it as its <c>cast_shadow</c>; the crossfade overrides it outside an interior (<see cref="LocationFade"/>).
/// </summary>
public sealed record RecipePiece(MeshInstance3D Mesh, PieceUnit Unit, Material? Solid, bool Cast);

/// <summary>
/// The recipe meshes of one location (sceneRecipe.ts <c>mountShell</c>):
///   <see cref="Pieces"/> — every plate, wall and extra of EVERY storey, by unit (outdoor rooms off the tile, the
///                          rest in the interior group or its room groups); the storey switch only flips what
///                          shows (<see cref="LocationStoreys"/>), nothing is rebuilt;
///   <see cref="Shell"/>  — the far-view shell copies (<c>buildFarShell</c>), which fade like a roof.
/// </summary>
public sealed class RecipeLayers
{
    public List<RecipePiece> Pieces { get; init; } = new();
    public List<MeshInstance3D> Shell { get; init; } = new();
    /// <summary>Every plate and wall the browser's verify measures (see <see cref="RecipeMeshes"/>).</summary>
    public List<MeasuredPrimitive> Measured { get; init; } = new();
}

/// <summary>
/// The § B primitives of a scene recipe, mounted ONCE per location the way the browser mounts them
/// (client3d/src/scene/sceneRecipe.ts <c>mountShell</c>): every storey, outdoor pieces off the tile, the interior in
/// its own group that the crossfade shows (<see cref="LocationFade"/>) with one sub-group per declared room, the
/// far-view shell as copies that fade like a roof. Geometry is the Core's <see cref="RecipeGeometry"/> — the ports of
/// the shared builders (packages/scene-render/src/primitives.ts) and of the three geometry they make, checked against
/// shared/test-vectors/scene_primitives.json; the visibility decisions are <see cref="SceneView"/>'s and
/// <see cref="StoreyView"/>'s, applied per frame by <see cref="LocationStoreys"/>:
///
///   plates — polygon top face at <c>top_y</c>, holes cut out, plus underside and rims when <c>thickness</c>
///            &gt; 0 (ExtrudeGeometry down by the thickness; 0 = a bare face seen from both sides);
///   walls  — one box per piece, centred on the from→to midpoint, from <c>base_y</c> up by <c>height</c>;
///   extras — one box per entry, centre + own size, optional XYZ Euler in degrees.
///
/// WHERE each piece goes (the browser's, nothing is a native choice):
///   • a primitive of a declared OUTDOOR room (<c>outdoor_rooms</c> ∪ <c>always_visible</c>) hangs off the tile in
///     its room group; a primitive of another declared room in that room's group inside the interior; anything
///     else (no room, an undeclared room, every extra) in the interior group itself;
///   • a storey contour plate shows on its storey only and is drawn solid (<c>applyLevelDisplay</c> sets its opacity
///     to 1 whenever it shows); an interior outline wall likewise (only its storey's walls show with the interior up,
///     and those wear opacity 1); a room plate wears its composed ghost or, on the displayed storey, its solid twin;
///   • a door leaf / window pane that a model fills is not drawn;
///   • a location without a building model also gets its far-view shell (<c>shellPlan</c> 'recipe'): copies of
///     the level plates at or above ground and of every non-glass wall at or above ground, leaves included.
/// Stats count what the browser SHOWS at the fade target and the build's storey (<see cref="RecipeView"/>);
/// <see cref="RecipeStats.InteriorMounted"/> counts what stands in the interior group (every storey).
/// Materials: <see cref="RecipeMaterials"/>; one mesh per material per unit (the browser draws one mesh per
/// primitive — merging them is the one native liberty here, it saves draw calls and favours Godot).
///
/// VERIFY (§ B5a): <see cref="RecipeLayers.Measured"/> carries every plate and wall the browser's
/// <c>builtPlates</c>/<c>builtWalls</c> holds and this client mounts — its box from the very vertices emitted (as
/// floats), or for a pane a model fills (the browser builds it invisible) from the geometry it would emit. Not
/// measured: degenerate pieces (not built here).
/// </summary>
public static class RecipeMeshes
{
    public static (RecipeLayers Layers, RecipeStats Stats) Build(
        ScenePayload scene, RecipeView view, RecipeMaterials materials, string name)
    {
        var stats = new RecipeStats();
        var pieces = new Builder(materials);
        var shellB = new Builder(materials);
        var measured = new List<MeasuredPrimitive>();
        var outdoor = LocationView.OutdoorRoomIds(scene);
        var roomLevel = scene.Rooms.GroupBy(r => r.RoomId).ToDictionary(g => g.Key, g => g.First().Level);
        int filter = view.LevelFilter;
        // parentFor(room): the room's group when the payload declares the room, else the interior group itself.
        string RoomOf(string roomId) => roomId.Length > 0 && roomLevel.ContainsKey(roomId) ? roomId : "";
        bool IsOutdoor(string room) => room.Length > 0 && outdoor.Contains(room);
        // With the interior up at the build's storey: an outdoor room is always there; a declared room shows when
        // SceneView.RoomVisible puts it on that storey; anything else hangs in the interior group itself.
        bool ParentShownOpen(string room) => room.Length == 0 || IsOutdoor(room) || SceneView.RoomVisible(false, roomLevel[room], filter);

        foreach (var p in scene.Plates)
        {
            if (p.Outline.Length < 3 || RecipeGeometry.TopTriangles(p) == 0) { stats.Degenerate++; continue; }
            string room = RoomOf(p.RoomId);
            bool outdoorPiece = IsOutdoor(room);
            // A storey's contour plate (no room_id) is a level slab; any plate WITH a room_id joins the room plates.
            bool slab = p.RoomId.Length == 0;
            var unit = new PieceUnit(room, outdoorPiece, slab ? StoreyRole.Slab : StoreyRole.RoomPlate, p.Level);
            var ghost = materials.Plate(p, scene);
            // A slab only ever shows on its own storey, at opacity 1 (applyLevelDisplay); a room plate keeps its ghost
            // and gets the solid twin storeyPieceOpacity hands the displayed storey. The caster flag is part of the
            // surface key, so a casting and a non-casting plate never share one mesh.
            MeshData emitted = slab
                ? pieces.Plate(unit, p, ghost with { Opacity = 1 }, null, PlateCasts(p))
                : pieces.Plate(unit, p, ghost, ghost.Opacity < 1 ? ghost with { Opacity = 1 } : null, PlateCasts(p));
            if (!outdoorPiece) stats.InteriorMounted++;
            bool shownOpen = slab ? StoreyView.SlabVisible(p.Level, filter) : ParentShownOpen(room);
            bool shellCopy = view.FarShell && !outdoorPiece && SceneView.FarShellPiece("plate", p.Level, p.RoomId, false);
            // buildFarShell: every copy casts (copy.castShadow = true).
            if (shellCopy) shellB.Plate(default, p, materials.Plate(p, scene, 1), null, true);
            measured.Add(new MeasuredPrimitive(SceneVerifier.PlateName(p), SceneVerify.PlateTargets(p), Builder.FloatBounds(emitted)));

            if (view.Open) { if (shownOpen) stats.Plates++; else stats.Storey++; }
            else if (outdoorPiece) stats.Plates++;
            else if (shellCopy) { stats.Plates++; stats.ShellCopies++; }
            else stats.Interior++;
        }

        foreach (var w in scene.Walls)
        {
            double len = PrimitiveMath.WallTransform(w).Size.X;
            if (len < 1e-4 || !(w.Height > 0) || !(w.Thickness > 0)) { stats.Degenerate++; continue; }
            bool outline = !w.Glass && !w.Leaf;
            bool hiddenPane = w.DoorProp || w.WindowModel;
            string room = RoomOf(w.RoomId);
            bool outdoorPiece = IsOutdoor(room);
            bool parentOpen = ParentShownOpen(room);
            bool shownOpen = parentOpen && !hiddenPane && (!outline || w.Level == filter);
            bool shellCopy = view.FarShell && !outdoorPiece && SceneView.FarShellPiece("wall", w.Level, w.RoomId, w.Glass);
            var unit = new PieceUnit(room, outdoorPiece, outline ? StoreyRole.OutlineWall : StoreyRole.Other, outline ? w.Level : 0);
            MeshData? emitted = null;
            if (!hiddenPane)
            {
                if (outdoorPiece)
                {
                    // Off the tile, at the composed look; an outline wall of a ghosted storey turns solid once its
                    // storey has been displayed (levelWallMats[filter].opacity = 1 sticks).
                    var look = materials.Wall(w, scene, outline);
                    emitted = pieces.Wall(unit, w, look, outline, outline && look.Opacity < 1 ? look with { Opacity = 1 } : null);
                }
                else
                {
                    // An interior outline wall only ever shows on the displayed storey, where it is solid; a pane or a
                    // leaf keeps its own look (it is not in levelWallMats).
                    emitted = pieces.Wall(unit, w, materials.Wall(w, scene, outline, outline ? 1 : null), outline, null);
                    stats.InteriorMounted++;
                }
            }
            if (shellCopy) shellB.Wall(default, w, materials.Wall(w, scene, false, 1), false, null, true);
            // A pane a model fills: the browser builds it invisible and measures it; here it is measured from the
            // geometry it would be (its box, through the same location frame) without drawing it.
            emitted ??= RecipeGeometry.Wall(w, 0);
            measured.Add(new MeasuredPrimitive(SceneVerifier.WallName(w), SceneVerify.WallTargets(w), Builder.FloatBounds(emitted)));

            if (view.Open)
            {
                if (shownOpen) { stats.Walls++; if (outline) stats.CulledWalls++; }
                else if (parentOpen && hiddenPane) stats.Panes++;
                else stats.Storey++;
            }
            else if (outdoorPiece && !hiddenPane) stats.Walls++;
            else if (shellCopy) { stats.Walls++; stats.ShellCopies++; }
            else if (outdoorPiece && hiddenPane) stats.Panes++;
            else stats.Interior++;
        }

        foreach (var e in scene.Extras)
        {
            if (e.Center.Length < 3 || e.Size.Length < 3 || !(e.Size[0] > 0 && e.Size[1] > 0 && e.Size[2] > 0))
            {
                stats.Degenerate++;
                continue;
            }
            // Extras hang in the interior group (lift and flights alike) and are not storey-filtered.
            VerticalTarget? vertical = e.Kind.StartsWith("elevator_", StringComparison.Ordinal) ? new("elevator", -1) : null;
            if (e.Kind.StartsWith("stair_", StringComparison.Ordinal) && e.Stair is { } stairId)
            {
                int flight = scene.Stairs.FindIndex(s => s.Id == stairId);
                if (flight >= 0) vertical = new("stairs", flight);
            }
            pieces.Extra(new PieceUnit("", false, StoreyRole.Other, 0) { Vertical = vertical }, e, materials.Extra(e, scene));
            stats.InteriorMounted++;
            if (view.Open) stats.Extras++;
            else stats.Interior++;
        }

        var layers = new RecipeLayers
        {
            Pieces = pieces.Commit(materials, name),
            Shell = shellB.Commit(materials, name + "Shell").Select(x => x.Mesh).ToList(),
            Measured = measured,
        };
        return (layers, stats);
    }

    /// <summary>sceneRecipe.ts: <c>mesh.castShadow = plate.level &gt; 0 &amp;&amp; plate.thickness &gt; 0</c>.</summary>
    public static bool PlateCasts(ScenePlate p) => p.Level > 0 && p.Thickness > 0;

    /// <summary>Triangles per unit, material and caster flag, written into one mesh each.</summary>
    private sealed class Builder
    {
        private readonly Dictionary<(PieceUnit Unit, string Look, bool Cast), (RecipeLook Look, RecipeLook? Solid, SurfaceTool St)> _surfaces = new();
        private readonly RecipeMaterials _materials;
        public int Triangles { get; private set; }

        public Builder(RecipeMaterials materials) => _materials = materials;

        private SurfaceTool For(PieceUnit unit, RecipeLook look, RecipeLook? solid, bool cast)
        {
            if (_surfaces.TryGetValue((unit, look.Key, cast), out var s)) return s.St;
            var st = new SurfaceTool();
            st.Begin(Mesh.PrimitiveType.Triangles);
            st.SetCustomFormat(0, SurfaceTool.CustomFormat.RgbaFloat);
            _surfaces[(unit, look.Key, cast)] = (look, solid, st);
            return st;
        }

        public List<RecipePiece> Commit(RecipeMaterials materials, string name)
        {
            var list = new List<RecipePiece>();
            int i = 0;
            foreach (var ((unit, _, cast), (look, solid, st)) in _surfaces)
            {
                st.SetMaterial(materials.Get(look));
                var mesh = new MeshInstance3D
                {
                    Name = $"{name}_{unit.Tag}_{i++}", Mesh = st.Commit(),
                    CastShadow = cast ? GeometryInstance3D.ShadowCastingSetting.On : GeometryInstance3D.ShadowCastingSetting.Off,
                };
                if (unit.Vertical is { } target)
                {
                    mesh.SetMeta(VerticalPicking.KindMeta, target.Kind);
                    mesh.SetMeta(VerticalPicking.FlightMeta, target.Flight);
                }
                list.Add(new RecipePiece(mesh, unit, solid is { } sl ? materials.Get(sl) : null, cast));
            }
            return list;
        }

        /// <summary>
        /// Emit a Core mesh. Its triangles are wound counter-clockwise seen from the front (three's rule); Godot's
        /// front faces wind clockwise, so every triple is emitted reversed. Its uvs are three's (v up the image,
        /// three uploads with flipY); Godot samples v down the image, so v is negated — on a repeat-wrapped
        /// texture that is the same texel. <paramref name="uvScale"/> divides the uvs by the tile size where three
        /// tiles through the texture's repeat (plates) instead of the geometry (walls, extras).
        /// </summary>
        private void Emit(SurfaceTool st, MeshData m, double uvScale, Color custom)
        {
            float k = (float)uvScale;
            void Vertex(int i)
            {
                var n = m.Normals[i];
                st.SetNormal(new Vector3((float)n.X, (float)n.Y, (float)n.Z));
                st.SetUV(new Vector2((float)m.Uvs[i].U * k, -(float)m.Uvs[i].V * k));
                st.SetCustom(0, custom);
                var p = m.Positions[i];
                st.AddVertex(new Vector3((float)p.X, (float)p.Y, (float)p.Z));
            }
            for (int i = 0; i + 2 < m.Indices.Count; i += 3)
            {
                Vertex(m.Indices[i]);
                Vertex(m.Indices[i + 2]);
                Vertex(m.Indices[i + 1]);
                Triangles++;
            }
        }

        /// <summary><c>buildWall</c> (<see cref="RecipeGeometry.Wall"/>); an outline wall carries its midpoint and outward normal in CUSTOM0.</summary>
        public MeshData Wall(PieceUnit unit, SceneWall w, RecipeLook look, bool cull, RecipeLook? solid, bool cast = false)
        {
            var t = PrimitiveMath.WallTransform(w);
            var custom = cull ? new Color((float)t.Position.X, (float)t.Position.Z, (float)w.OutwardNormal.X, (float)w.OutwardNormal.Z)
                              : new Color(0, 0, 0, 0);
            var m = RecipeGeometry.Wall(w, look.TextureKind.Length > 0 ? TileOf(look) : 0);
            Emit(For(unit, look, solid, cast), m, 1, custom);
            return m;
        }

        /// <summary>The bounds of the positions AS EMITTED (single precision), three's <c>Box3.setFromObject</c> of that mesh.</summary>
        public static VBox FloatBounds(MeshData m)
        {
            double Lo(Func<Vec3, double> f) => m.Positions.Count == 0 ? double.PositiveInfinity : m.Positions.Min(p => (double)(float)f(p));
            double Hi(Func<Vec3, double> f) => m.Positions.Count == 0 ? double.NegativeInfinity : m.Positions.Max(p => (double)(float)f(p));
            return new VBox(new Vec3(Lo(p => p.X), Lo(p => p.Y), Lo(p => p.Z)), new Vec3(Hi(p => p.X), Hi(p => p.Y), Hi(p => p.Z)));
        }

        /// <summary><c>buildExtra</c> (<see cref="RecipeGeometry.Extra"/>): its own size, XYZ Euler, world-scale uvs.</summary>
        public void Extra(PieceUnit unit, SceneExtra e, RecipeLook look)
            => Emit(For(unit, look, null, false), RecipeGeometry.Extra(e, look.TextureKind.Length > 0 ? TileOf(look) : 0), 1, new Color(0, 0, 0, 0));

        /// <summary><c>buildPlate</c> (<see cref="RecipeGeometry.Plate"/>); its uvs are shape metres, tiled by 1 / tile size.</summary>
        public MeshData Plate(PieceUnit unit, ScenePlate p, RecipeLook look, RecipeLook? solid, bool cast)
        {
            double tileM = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            var m = RecipeGeometry.Plate(p);
            Emit(For(unit, look, solid, cast), m, tileM > 0 ? 1 / tileM : 1, new Color(0, 0, 0, 0));
            return m;
        }

        /// <summary>The world size of one texture tile of this look; 0 = untextured (style colour).</summary>
        private double TileOf(RecipeLook look) => _materials.TileM(look);
    }
}
