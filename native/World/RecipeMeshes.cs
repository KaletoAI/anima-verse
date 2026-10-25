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
    /// <summary>Not drawn: in the OPEN location, but on another storey (<c>applyLevelDisplay</c>/<c>applyRoomVisibility</c>/the wall filter).</summary>
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
/// closed), <see cref="LevelFilter"/> = the storey the interior is mounted for, <see cref="FarShell"/> = it shows a
/// far-view shell (<c>shellPlan</c> 'recipe').
/// </summary>
public sealed record RecipeView(bool Open, int LevelFilter, bool FarShell)
{
    public static readonly RecipeView Closed = new(false, 0, false);
}

/// <summary>One plate or wall the § B5a verify measures: its verify name, its targets and its box in the location frame.</summary>
public sealed record MeasuredPrimitive(string Name, List<PrimitiveTarget> Targets, VBox Local);

/// <summary>
/// The recipe meshes of one location, by the layer they hang in (sceneRecipe.ts <c>mountShell</c>):
///   <see cref="Outdoor"/>      — pieces of outdoor / always-visible rooms, off the tile group, always shown;
///   <see cref="OutdoorClosed"/> — outdoor OUTLINE walls of another storey than the mounted one: shown while the
///                                location is closed, hidden by the storey filter once its interior is up;
///   <see cref="Interior"/>     — everything else on the mounted storey (the browser's interior group <c>g</c>);
///   <see cref="Shell"/>        — the far-view shell copies (<c>buildFarShell</c>), which fade like a roof.
/// </summary>
public sealed class RecipeLayers
{
    public List<MeshInstance3D> Outdoor { get; init; } = new();
    public List<MeshInstance3D> OutdoorClosed { get; init; } = new();
    public List<MeshInstance3D> Interior { get; init; } = new();
    public List<MeshInstance3D> Shell { get; init; } = new();
    /// <summary>Every plate and wall the browser's verify measures that is mounted here (see <see cref="RecipeMeshes"/>).</summary>
    public List<MeasuredPrimitive> Measured { get; init; } = new();
}

/// <summary>
/// The § B primitives of a scene recipe, mounted ONCE per location the way the browser mounts them
/// (client3d/src/scene/sceneRecipe.ts <c>mountShell</c>): outdoor pieces off the tile, the interior in its own
/// group that the crossfade shows (<see cref="LocationFade"/>), the far-view shell as copies that fade like a
/// roof. Geometry is the Core's <see cref="RecipeGeometry"/> — the ports of the shared builders
/// (packages/scene-render/src/primitives.ts) and of the three geometry they make, checked against
/// shared/test-vectors/scene_primitives.json; the visibility decisions are <see cref="SceneView"/>'s
/// (RoomVisible, StoreyPieceOpacity, FarShellPiece, scene_view.json):
///
///   plates — polygon top face at <c>top_y</c>, holes cut out, plus underside and rims when <c>thickness</c>
///            &gt; 0 (ExtrudeGeometry down by the thickness; 0 = a bare face seen from both sides);
///   walls  — one box per piece, centred on the from→to midpoint, from <c>base_y</c> up by <c>height</c>;
///   extras — one box per entry, centre + own size, optional XYZ Euler in degrees.
///
/// WHERE each piece goes (the browser's, nothing is a native choice):
///   • a primitive of an OUTDOOR room (<c>outdoor_rooms</c> ∪ <c>always_visible</c>) hangs off the tile;
///   • everything else is the interior, mounted for ONE storey (<see cref="RecipeView.LevelFilter"/> — the runtime
///     storey switch is Task 16): storey plates of that storey, room groups on it, outline walls on it, which the
///     shader drops where the camera is on their outer side (the GPU twin of <see cref="SceneView.WallVisible"/>);
///     a door leaf / window pane that a model fills is not drawn;
///   • a location without a building model also gets its far-view shell (<c>shellPlan</c> 'recipe'): copies of
///     the level plates at or above ground and of every non-glass wall at or above ground, leaves included.
/// Stats count what the browser SHOWS at the fade target (<see cref="RecipeView.Open"/>), unchanged from the
/// static spike; <see cref="RecipeStats.InteriorMounted"/> counts what stands in the interior group.
/// Materials: <see cref="RecipeMaterials"/>; one mesh per material per layer (the browser draws one mesh per
/// primitive — merging them is the one native liberty here, it saves draw calls and favours Godot).
///
/// VERIFY (§ B5a): <see cref="RecipeLayers.Measured"/> carries every plate and wall the browser's
/// <c>builtPlates</c>/<c>builtWalls</c> holds AND this client mounts — its box from the very vertices emitted (as
/// floats), or for a pane a model fills (the browser builds it invisible) from the geometry it would emit. Not
/// measured: degenerate pieces (not built here) and pieces of other storeys (not mounted until Task 16).
/// </summary>
public static class RecipeMeshes
{
    public static (RecipeLayers Layers, RecipeStats Stats) Build(
        ScenePayload scene, RecipeView view, RecipeMaterials materials, string name)
    {
        var stats = new RecipeStats();
        var outdoorB = new Builder(materials);
        var closedB = new Builder(materials);
        var interiorB = new Builder(materials);
        var shellB = new Builder(materials);
        var measured = new List<MeasuredPrimitive>();
        var outdoor = LocationView.OutdoorRoomIds(scene);
        var roomLevel = scene.Rooms.GroupBy(r => r.RoomId).ToDictionary(g => g.Key, g => g.First().Level);
        int filter = view.LevelFilter;
        bool IsOutdoor(string roomId) => roomId.Length > 0 && outdoor.Contains(roomId);
        // parentFor(room) with the interior up: an outdoor room is always there; a declared room shows when
        // SceneView.RoomVisible puts it on the mounted storey; anything else hangs in the interior group itself.
        bool ParentShownOpen(string roomId) => IsOutdoor(roomId)
            || !roomLevel.TryGetValue(roomId, out var lv) || SceneView.RoomVisible(false, lv, filter);

        foreach (var p in scene.Plates)
        {
            if (p.Outline.Length < 3 || RecipeGeometry.TopTriangles(p) == 0) { stats.Degenerate++; continue; }
            var ghost = MaterialLooks.PlateLook(p, scene).Opacity;
            bool outdoorPiece = IsOutdoor(p.RoomId);
            // Room plates follow their room group, a storey plate (levelSlabs) only its own storey.
            bool shownOpen = p.RoomId.Length > 0 ? ParentShownOpen(p.RoomId) : p.Level == filter;
            bool shellCopy = view.FarShell && !outdoorPiece && SceneView.FarShellPiece("plate", p.Level, p.RoomId, false);
            MeshData? emitted = null;
            if (shownOpen && outdoorPiece)
                emitted = outdoorB.Plate(p, materials.Plate(p, scene));
            else if (shownOpen)
            {
                // storeyPieceOpacity: the shown storey is solid, the others keep the composed ghost.
                emitted = interiorB.Plate(p, materials.Plate(p, scene, SceneView.StoreyPieceOpacity(p.Level, filter, ghost)));
                stats.InteriorMounted++;
            }
            if (shellCopy)
            {
                var copy = shellB.Plate(p, materials.Plate(p, scene, 1));
                emitted ??= copy;
            }
            if (emitted is not null)
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
            bool outdoorPiece = IsOutdoor(w.RoomId);
            bool parentOpen = ParentShownOpen(w.RoomId);
            bool shownOpen = parentOpen && !hiddenPane && (!outline || w.Level == filter);
            bool shellCopy = view.FarShell && !outdoorPiece && SceneView.FarShellPiece("wall", w.Level, w.RoomId, w.Glass);
            MeshData? emitted = null;
            if (outdoorPiece && !hiddenPane)
            {
                // Off the tile: culled per frame only while the interior is up (applyWallCulling runs at fade > 0.03,
                // LocationFade switches the instance's cull_active), and an outline wall of another storey is only
                // there while the location is closed.
                var look = materials.Wall(w, scene, outline);
                emitted = shownOpen ? outdoorB.Wall(w, look, outline) : closedB.Wall(w, look, outline);
            }
            else if (shownOpen)
            {
                double opacity = SceneView.StoreyPieceOpacity(w.Level, filter, MaterialLooks.WallLook(w, scene).Opacity);
                emitted = interiorB.Wall(w, materials.Wall(w, scene, outline, opacity), outline);
                stats.InteriorMounted++;
            }
            if (shellCopy)
            {
                var copy = shellB.Wall(w, materials.Wall(w, scene, false, 1), false);
                emitted ??= copy;
            }
            // A pane a model fills: the browser builds it invisible and measures it; here it is measured from the
            // geometry it would be (its box, through the same location frame) without drawing it.
            if (emitted is null && hiddenPane && parentOpen)
                emitted = RecipeGeometry.Wall(w, 0);
            if (emitted is not null)
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
            interiorB.Extra(e, materials.Extra(e, scene));
            stats.InteriorMounted++;
            if (view.Open) stats.Extras++;
            else stats.Interior++;
        }

        var layers = new RecipeLayers
        {
            Outdoor = outdoorB.Commit(materials, name),
            OutdoorClosed = closedB.Commit(materials, name + "Closed"),
            Interior = interiorB.Commit(materials, name),
            Shell = shellB.Commit(materials, name + "Shell"),
            Measured = measured,
        };
        return (layers, stats);
    }

    /// <summary>Triangles per material, written into one mesh each.</summary>
    private sealed class Builder
    {
        private readonly Dictionary<string, (RecipeLook Look, SurfaceTool St)> _surfaces = new();
        private readonly RecipeMaterials _materials;
        public int Triangles { get; private set; }

        public Builder(RecipeMaterials materials) => _materials = materials;

        private SurfaceTool For(RecipeLook look)
        {
            if (_surfaces.TryGetValue(look.Key, out var s)) return s.St;
            var st = new SurfaceTool();
            st.Begin(Mesh.PrimitiveType.Triangles);
            st.SetCustomFormat(0, SurfaceTool.CustomFormat.RgbaFloat);
            _surfaces[look.Key] = (look, st);
            return st;
        }

        public List<MeshInstance3D> Commit(RecipeMaterials materials, string name)
        {
            var list = new List<MeshInstance3D>();
            int i = 0;
            foreach (var (look, st) in _surfaces.Values)
            {
                st.SetMaterial(materials.Get(look));
                list.Add(new MeshInstance3D { Name = $"{name}_{i++}", Mesh = st.Commit() });
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
        public MeshData Wall(SceneWall w, RecipeLook look, bool cull)
        {
            var t = PrimitiveMath.WallTransform(w);
            var custom = cull ? new Color((float)t.Position.X, (float)t.Position.Z, (float)w.OutwardNormal.X, (float)w.OutwardNormal.Z)
                              : new Color(0, 0, 0, 0);
            var m = RecipeGeometry.Wall(w, look.TextureKind.Length > 0 ? TileOf(look) : 0);
            Emit(For(look), m, 1, custom);
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
        public void Extra(SceneExtra e, RecipeLook look)
            => Emit(For(look), RecipeGeometry.Extra(e, look.TextureKind.Length > 0 ? TileOf(look) : 0), 1, new Color(0, 0, 0, 0));

        /// <summary><c>buildPlate</c> (<see cref="RecipeGeometry.Plate"/>); its uvs are shape metres, tiled by 1 / tile size.</summary>
        public MeshData Plate(ScenePlate p, RecipeLook look)
        {
            double tileM = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            var m = RecipeGeometry.Plate(p);
            Emit(For(look), m, tileM > 0 ? 1 / tileM : 1, new Color(0, 0, 0, 0));
            return m;
        }

        /// <summary>The world size of one texture tile of this look; 0 = untextured (style colour).</summary>
        private double TileOf(RecipeLook look) => _materials.TileM(look);
    }
}
