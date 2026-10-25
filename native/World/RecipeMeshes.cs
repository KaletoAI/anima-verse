using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scene;
using Godot;

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
    /// <summary>Not drawn: inside the interior group of a CLOSED location (the crossfade keeps it invisible) and not part of a far shell.</summary>
    public int Interior;
    /// <summary>Not drawn: in the OPEN location, but on another storey (<c>applyLevelDisplay</c>/<c>applyRoomVisibility</c>/the wall filter).</summary>
    public int Storey;
    /// <summary>Not drawn: a door leaf / window pane whose opening a model in <c>models[]</c> fills (<c>door_prop</c>, <c>window_model</c>).</summary>
    public int Panes;
    /// <summary>Of the drawn walls: outline walls of the open location that take part in the per-frame camera cull.</summary>
    public int CulledWalls;
    public int Primitives => Plates + Walls + Extras;
    public int Skipped => Degenerate + Interior + Storey + Panes;

    public void Add(RecipeStats o)
    {
        Plates += o.Plates; Walls += o.Walls; Extras += o.Extras; ShellCopies += o.ShellCopies;
        Degenerate += o.Degenerate; Interior += o.Interior; Storey += o.Storey; Panes += o.Panes;
        CulledWalls += o.CulledWalls;
    }

    public string SkipSummary()
        => $"degenerate={Degenerate} interior={Interior} storey={Storey} panes={Panes}";
}

/// <summary>How the browser shows ONE location right now (see <see cref="LocationView"/>).</summary>
public sealed record RecipeView(bool Open, int LevelFilter, bool FarShell)
{
    public static readonly RecipeView Closed = new(false, 0, false);
}

/// <summary>
/// The § B primitives of a scene recipe as the BROWSER'S VIEW of them (client3d/src/scene/sceneRecipe.ts
/// <c>mountShell</c> + tiles.ts <c>applyTileFade</c>/<c>applyLevelDisplay</c>/<c>applyRoomVisibility</c>/
/// <c>applyWallCulling</c>). Geometry is the Core's <see cref="RecipeGeometry"/> — the ports of the shared builders
/// (packages/scene-render/src/primitives.ts) and of the three geometry they make, checked against
/// shared/test-vectors/scene_primitives.json; the visibility decisions are <see cref="SceneView"/>'s
/// (RoomVisible, StoreyPieceOpacity, FarShellPiece, scene_view.json):
///
///   plates — polygon top face at <c>top_y</c>, holes cut out, plus underside and rims when <c>thickness</c>
///            &gt; 0 (ExtrudeGeometry down by the thickness; 0 = a bare face seen from both sides);
///   walls  — one box per piece, centred on the from→to midpoint, from <c>base_y</c> up by <c>height</c>;
///   extras — one box per entry, centre + own size, optional XYZ Euler in degrees.
///
/// WHICH of them stand (all of this is the browser's, nothing is a native choice):
///   • a primitive of an OUTDOOR room (<c>outdoor_rooms</c> ∪ <c>always_visible</c>) hangs off the tile and is
///     always there;
///   • everything else hangs in the interior group, which only the OPEN location shows (the avatar's, fade 1);
///     there the storey filter applies — storey plates only on the shown storey, room groups only on it, outline
///     walls only on it and only where the camera is not on their outer side (per frame, in the shader — the GPU
///     twin of <see cref="SceneView.WallVisible"/>, a shader cannot call the Core);
///     a door leaf / window pane that a model fills stays hidden;
///   • a CLOSED location without a building model shows its far-view shell (<c>shellPlan</c> 'recipe'): copies
///     of the level plates at or above ground and of every non-glass wall at or above ground, leaves included.
/// Materials: <see cref="RecipeMaterials"/>; one mesh per material per location (the browser draws one mesh
/// per primitive — merging them is the one native liberty here, it saves draw calls and favours Godot).
/// </summary>
public static class RecipeMeshes
{
    public static (List<MeshInstance3D> Nodes, RecipeStats Stats) Build(
        ScenePayload scene, RecipeView view, RecipeMaterials materials, string name)
    {
        var stats = new RecipeStats();
        var b = new Builder(materials);
        var outdoor = LocationView.OutdoorRoomIds(scene);
        var roomLevel = scene.Rooms.GroupBy(r => r.RoomId).ToDictionary(g => g.Key, g => g.First().Level);
        // applyRoomVisibility: an outdoor room hangs off the tile; a declared room shows with the open
        // interior when SceneView.RoomVisible puts it on the shown storey.
        bool RoomShown(string roomId) => outdoor.Contains(roomId)
            || (view.Open && SceneView.RoomVisible(false, roomLevel.TryGetValue(roomId, out var lv) ? lv : null, view.LevelFilter));
        // parentFor(room): its room group when the room is declared, else the interior group.
        bool ParentShown(string roomId) => roomLevel.ContainsKey(roomId) ? RoomShown(roomId) : view.Open;

        foreach (var p in scene.Plates)
        {
            if (p.Outline.Length < 3 || RecipeGeometry.TopTriangles(p) == 0) { stats.Degenerate++; continue; }
            var ghost = MaterialLooks.PlateLook(p, scene).Opacity;
            bool shown;
            double? opacity = null;
            if (p.RoomId.Length > 0)
            {
                shown = ParentShown(p.RoomId);
                // storeyPieceOpacity: the shown storey is solid, the others keep the composed ghost.
                if (view.Open) opacity = SceneView.StoreyPieceOpacity(p.Level, view.LevelFilter, ghost);
            }
            else
            {
                // A storey plate (levelSlabs): only its own storey, at full opacity.
                shown = view.Open && p.Level == view.LevelFilter;
                if (shown) opacity = SceneView.StoreyPieceOpacity(p.Level, view.LevelFilter, ghost);
            }
            if (shown)
            {
                b.Plate(p, materials.Plate(p, scene, opacity));
                stats.Plates++;
            }
            else if (view.FarShell && !view.Open && SceneView.FarShellPiece("plate", p.Level, p.RoomId, false))
            {
                b.Plate(p, materials.Plate(p, scene, 1));
                stats.Plates++;
                stats.ShellCopies++;
            }
            else if (view.Open) stats.Storey++;
            else stats.Interior++;
        }

        foreach (var w in scene.Walls)
        {
            double len = PrimitiveMath.WallTransform(w).Size.X;
            if (len < 1e-4 || !(w.Height > 0) || !(w.Thickness > 0)) { stats.Degenerate++; continue; }
            bool outline = !w.Glass && !w.Leaf;
            bool hiddenPane = w.DoorProp || w.WindowModel;
            bool parent = ParentShown(w.RoomId);
            bool shown = parent && !hiddenPane && (!outline || !view.Open || w.Level == view.LevelFilter);
            if (shown)
            {
                bool cull = outline && view.Open;
                double? opacity = view.Open ? SceneView.StoreyPieceOpacity(w.Level, view.LevelFilter, MaterialLooks.WallLook(w, scene).Opacity) : null;
                b.Wall(w, materials.Wall(w, scene, cull, opacity), cull);
                stats.Walls++;
                if (cull) stats.CulledWalls++;
            }
            else if (view.FarShell && !view.Open && SceneView.FarShellPiece("wall", w.Level, w.RoomId, w.Glass))
            {
                b.Wall(w, materials.Wall(w, scene, false, 1), false);
                stats.Walls++;
                stats.ShellCopies++;
            }
            else if (parent && hiddenPane) stats.Panes++;
            else if (view.Open) stats.Storey++;
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
            if (!view.Open) { stats.Interior++; continue; }
            b.Extra(e, materials.Extra(e, scene));
            stats.Extras++;
        }

        var nodes = b.Commit(materials, name);
        return (nodes, stats);
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
        public void Wall(SceneWall w, RecipeLook look, bool cull)
        {
            var t = PrimitiveMath.WallTransform(w);
            var custom = cull ? new Color((float)t.Position.X, (float)t.Position.Z, (float)w.OutwardNormal.X, (float)w.OutwardNormal.Z)
                              : new Color(0, 0, 0, 0);
            Emit(For(look), RecipeGeometry.Wall(w, look.TextureKind.Length > 0 ? TileOf(look) : 0), 1, custom);
        }

        /// <summary><c>buildExtra</c> (<see cref="RecipeGeometry.Extra"/>): its own size, XYZ Euler, world-scale uvs.</summary>
        public void Extra(SceneExtra e, RecipeLook look)
            => Emit(For(look), RecipeGeometry.Extra(e, look.TextureKind.Length > 0 ? TileOf(look) : 0), 1, new Color(0, 0, 0, 0));

        /// <summary><c>buildPlate</c> (<see cref="RecipeGeometry.Plate"/>); its uvs are shape metres, tiled by 1 / tile size.</summary>
        public void Plate(ScenePlate p, RecipeLook look)
        {
            double tileM = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            Emit(For(look), RecipeGeometry.Plate(p), tileM > 0 ? 1 / tileM : 1, new Color(0, 0, 0, 0));
        }

        /// <summary>The world size of one texture tile of this look; 0 = untextured (style colour).</summary>
        private double TileOf(RecipeLook look) => _materials.TileM(look);
    }
}
