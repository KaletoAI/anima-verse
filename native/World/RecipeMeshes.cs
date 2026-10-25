using System;
using System.Collections.Generic;
using System.Linq;
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
/// <c>applyWallCulling</c>), geometry by the shared builders (packages/scene-render/src/primitives.ts):
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
///     walls only on it and only where the camera is not on their outer side (per frame, in the shader);
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
        // applyRoomVisibility: a room group shows on its own storey, an outdoor one always.
        bool RoomShown(string roomId) => outdoor.Contains(roomId)
            || (view.Open && (!roomLevel.TryGetValue(roomId, out var lv) || lv == view.LevelFilter));
        // parentFor(room): its room group when the room is declared, else the interior group.
        bool ParentShown(string roomId) => roomLevel.ContainsKey(roomId) ? RoomShown(roomId) : view.Open;

        foreach (var p in scene.Plates)
        {
            if (p.Outline.Length < 3 || !b.CanTriangulate(p)) { stats.Degenerate++; continue; }
            bool shown;
            double? opacity = null;
            if (p.RoomId.Length > 0)
            {
                shown = ParentShown(p.RoomId);
                // storeyPieceOpacity: the shown storey is solid, the others keep the composed ghost.
                if (view.Open && p.Level == view.LevelFilter) opacity = 1;
            }
            else
            {
                // A storey plate (levelSlabs): only its own storey, at full opacity.
                shown = view.Open && p.Level == view.LevelFilter;
                if (shown) opacity = 1;
            }
            if (shown)
            {
                b.Plate(p, materials.Plate(p, scene, opacity));
                stats.Plates++;
            }
            else if (view.FarShell && !view.Open && p.RoomId.Length == 0 && p.Level >= 0)
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
            double dx = w.To.X - w.From.X, dz = w.To.Z - w.From.Z;
            double len = Math.Sqrt(dx * dx + dz * dz);
            if (len < 1e-4 || !(w.Height > 0) || !(w.Thickness > 0)) { stats.Degenerate++; continue; }
            bool outline = !w.Glass && !w.Leaf;
            bool hiddenPane = w.DoorProp || w.WindowModel;
            bool parent = ParentShown(w.RoomId);
            bool shown = parent && !hiddenPane && (!outline || !view.Open || w.Level == view.LevelFilter);
            if (shown)
            {
                bool cull = outline && view.Open;
                double? opacity = view.Open && w.Level == view.LevelFilter ? 1 : null;
                b.Wall(w, len, materials.Wall(w, scene, cull, opacity), cull);
                stats.Walls++;
                if (cull) stats.CulledWalls++;
            }
            else if (view.FarShell && !view.Open && !w.Glass && w.Level >= 0)
            {
                b.Wall(w, len, materials.Wall(w, scene, false, 1), false);
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
        /// One triangle. Godot's front faces wind clockwise as seen by the viewer, i.e. <c>cross(b−a, c−a)</c>
        /// points AWAY from the side the face is seen from; b and c are swapped when the winding does not match
        /// <paramref name="n"/>.
        /// </summary>
        private void Tri(SurfaceTool st, (Vector3 P, Vector2 Uv) a, (Vector3 P, Vector2 Uv) b, (Vector3 P, Vector2 Uv) c,
                         Vector3 n, Color custom)
        {
            if ((b.P - a.P).Cross(c.P - a.P).Dot(n) > 0) (b, c) = (c, b);
            foreach (var v in new[] { a, b, c })
            {
                st.SetNormal(n);
                st.SetUV(v.Uv);
                st.SetCustom(0, custom);
                st.AddVertex(v.P);
            }
            Triangles++;
        }

        /// <summary>
        /// A box of size <paramref name="size"/> under <paramref name="xf"/> (rotation + centre), six faces, UVs
        /// in tile units per face the way <c>applyWorldScaleWallUVs</c> scales three's <c>BoxGeometry</c>:
        /// ±x faces u = depth, v = height; ±y faces u = width, v = depth; ±z faces u = width, v = height.
        /// </summary>
        private void Box(SurfaceTool st, Transform3D xf, Vector3 size, double tileM, Color custom)
        {
            float t = tileM > 0 ? (float)tileM : 0;
            var axes = new[] { Vector3.Right, Vector3.Up, Vector3.Back };
            foreach (var axis in axes)
            foreach (var sign in new[] { 1f, -1f })
            {
                Vector3 u, v;
                float su, sv;
                if (axis == Vector3.Right) { u = Vector3.Back; v = Vector3.Up; su = size.Z; sv = size.Y; }
                else if (axis == Vector3.Up) { u = Vector3.Right; v = Vector3.Back; su = size.X; sv = size.Z; }
                else { u = Vector3.Right; v = Vector3.Up; su = size.X; sv = size.Y; }
                Vector3 P(float a, float bb) => xf * ((axis * (0.5f * sign) + u * a + v * bb) * size);
                Vector2 Uv(float a, float bb) => t > 0 ? new Vector2((a + 0.5f) * su / t, (0.5f - bb) * sv / t)
                                                       : new Vector2(a + 0.5f, 0.5f - bb);
                var q = new[] { (P(-0.5f, -0.5f), Uv(-0.5f, -0.5f)), (P(0.5f, -0.5f), Uv(0.5f, -0.5f)),
                                (P(0.5f, 0.5f), Uv(0.5f, 0.5f)), (P(-0.5f, 0.5f), Uv(-0.5f, 0.5f)) };
                var n = (xf.Basis * (axis * sign)).Normalized();
                Tri(st, q[0], q[1], q[2], n, custom);
                Tri(st, q[0], q[2], q[3], n, custom);
            }
        }

        public void Wall(SceneWall w, double len, RecipeLook look, bool cull)
        {
            double dx = w.To.X - w.From.X, dz = w.To.Z - w.From.Z;
            var dir = new Vector3((float)(dx / len), 0, (float)(dz / len));
            var side = new Vector3(-dir.Z, 0, dir.X);
            var center = new Vector3((float)((w.From.X + w.To.X) / 2), (float)(w.BaseY + w.Height / 2),
                                     (float)((w.From.Z + w.To.Z) / 2));
            var xf = new Transform3D(new Basis(dir, Vector3.Up, side), center);
            var custom = cull ? new Color(center.X, center.Z, (float)w.OutwardNormal.X, (float)w.OutwardNormal.Z)
                              : new Color(0, 0, 0, 0);
            var tile = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            Box(For(look), xf, new Vector3((float)len, (float)w.Height, (float)w.Thickness), tile, custom);
        }

        public void Extra(SceneExtra e, RecipeLook look)
        {
            var rot = e.Rotation is { Length: >= 3 } r
                ? Basis.FromEuler(new Vector3((float)Deg(r[0]), (float)Deg(r[1]), (float)Deg(r[2])), EulerOrder.Xyz)
                : Basis.Identity;
            var center = new Vector3((float)e.Center[0], (float)e.Center[1], (float)e.Center[2]);
            var tile = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            Box(For(look), new Transform3D(rot, center), new Vector3((float)e.Size[0], (float)e.Size[1], (float)e.Size[2]),
                tile, new Color(0, 0, 0, 0));
        }

        /// <summary>The world size of one texture tile of this look; 0 = untextured (style colour).</summary>
        private double TileOf(RecipeLook look) => _materials.TileM(look);

        public bool CanTriangulate(ScenePlate p)
        {
            var (outline, holes) = Rings(p);
            return PolygonsWithoutHoles(outline, holes).Any(poly => Geometry2D.TriangulatePolygon(poly).Length >= 3);
        }

        private static (Vector2[] Outline, Vector2[][] Holes) Rings(ScenePlate p)
            => (p.Outline.Select(v => new Vector2((float)v.X, (float)v.Z)).ToArray(),
                p.Holes.Where(h => h.Length >= 3)
                       .Select(h => h.Select(v => new Vector2((float)v.X, (float)v.Z)).ToArray()).ToArray());

        public void Plate(ScenePlate p, RecipeLook look)
        {
            var st = For(look);
            var (outline, holes) = Rings(p);
            var pieces = PolygonsWithoutHoles(outline, holes);
            float top = (float)p.TopY, bottom = (float)(p.TopY - Math.Max(p.Thickness, 0));
            bool solid = p.Thickness > 0;
            double tileM = look.TextureKind.Length > 0 ? TileOf(look) : 0;
            float t = tileM > 0 ? (float)tileM : 1;
            // The shape plane: (x, z) for a body, (x, −z) for a bare face (buildPlate), one repeat per tile.
            Vector2 Uv(Vector2 q) => new(q.X / t, (solid ? q.Y : -q.Y) / t);
            var none = new Color(0, 0, 0, 0);
            foreach (var poly in pieces)
            {
                var idx = Geometry2D.TriangulatePolygon(poly);
                for (int i = 0; i + 2 < idx.Length; i += 3)
                {
                    var a = poly[idx[i]]; var bb = poly[idx[i + 1]]; var c = poly[idx[i + 2]];
                    Tri(st, (new Vector3(a.X, top, a.Y), Uv(a)), (new Vector3(bb.X, top, bb.Y), Uv(bb)),
                        (new Vector3(c.X, top, c.Y), Uv(c)), Vector3.Up, none);
                    if (solid)
                        Tri(st, (new Vector3(a.X, bottom, a.Y), Uv(a)), (new Vector3(bb.X, bottom, bb.Y), Uv(bb)),
                            (new Vector3(c.X, bottom, c.Y), Uv(c)), Vector3.Down, none);
                }
            }
            if (!solid) return;
            // Rims: every edge of the outline and of every hole, facing away from the solid side.
            bool Solid(Vector2 q) => Geometry2D.IsPointInPolygon(q, outline)
                                     && !holes.Any(h => Geometry2D.IsPointInPolygon(q, h));
            foreach (var ring in holes.Prepend(outline))
                for (int i = 0; i < ring.Length; i++)
                {
                    var a = ring[i]; var c = ring[(i + 1) % ring.Length];
                    var e = c - a;
                    if (e.LengthSquared() < 1e-12f) continue;
                    var n2 = new Vector2(-e.Y, e.X).Normalized();
                    if (Solid((a + c) / 2 + n2 * 0.01f)) n2 = -n2;
                    var n = new Vector3(n2.X, 0, n2.Y);
                    float l = e.Length() / t, h = (top - bottom) / t;
                    var a0 = (new Vector3(a.X, bottom, a.Y), new Vector2(0, h)); var a1 = (new Vector3(a.X, top, a.Y), new Vector2(0, 0));
                    var c0 = (new Vector3(c.X, bottom, c.Y), new Vector2(l, h)); var c1 = (new Vector3(c.X, top, c.Y), new Vector2(l, 0));
                    Tri(st, a0, c0, c1, n, none);
                    Tri(st, a0, c1, a1, n, none);
                }
        }
    }

    private static double Deg(double d) => d * Math.PI / 180.0;

    /// <summary>
    /// Cut holes out of a polygon so that only hole-free simple polygons remain
    /// (Godot's <c>TriangulatePolygon</c> knows no holes). A hole that lies
    /// inside a piece would come back from the clipper as a separate ring, so
    /// the piece is first split by the vertical line through the middle of the
    /// hole's x range — the hole then touches both halves' cut edge and each
    /// half minus the hole is a simple notched polygon. Exact: no rectangle
    /// ever stands in for a polygon, and no hole is silently filled.
    /// </summary>
    public static List<Vector2[]> PolygonsWithoutHoles(Vector2[] outline, Vector2[][] holes)
    {
        var pieces = new List<Vector2[]> { outline };
        foreach (var hole in holes)
        {
            float minX = hole.Min(v => v.X), maxX = hole.Max(v => v.X);
            float cut = (minX + maxX) / 2;
            var next = new List<Vector2[]>();
            foreach (var piece in pieces)
            {
                if (Geometry2D.IntersectPolygons(piece, hole).Count == 0) { next.Add(piece); continue; }
                float pMinX = piece.Min(v => v.X) - 1, pMaxX = piece.Max(v => v.X) + 1;
                float pMinZ = piece.Min(v => v.Y) - 1, pMaxZ = piece.Max(v => v.Y) + 1;
                var halves = new[]
                {
                    new[] { new Vector2(pMinX, pMinZ), new Vector2(cut, pMinZ), new Vector2(cut, pMaxZ), new Vector2(pMinX, pMaxZ) },
                    new[] { new Vector2(cut, pMinZ), new Vector2(pMaxX, pMinZ), new Vector2(pMaxX, pMaxZ), new Vector2(cut, pMaxZ) },
                };
                foreach (var half in halves)
                foreach (var part in Geometry2D.IntersectPolygons(piece, half))
                foreach (var rest in Geometry2D.ClipPolygons(part, hole))
                    if (Math.Abs(Area(rest)) > 1e-6f) next.Add(rest);
            }
            pieces = next;
        }
        return pieces;
    }

    public static float Area(Vector2[] poly)
    {
        double a = 0;
        for (int i = 0; i < poly.Length; i++)
        {
            var p = poly[i]; var q = poly[(i + 1) % poly.Length];
            a += (double)p.X * q.Y - (double)q.X * p.Y;
        }
        return (float)(a / 2);
    }
}
