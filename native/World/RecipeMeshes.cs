using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.World;

/// <summary>What one location's recipe primitives turned into.</summary>
public sealed class RecipeStats
{
    public int Plates, Walls, Extras;
    public int Skipped;
    public int DoorPropLeaves;
    public int Primitives => Plates + Walls + Extras;
}

/// <summary>
/// The § B primitives of a scene recipe as untextured geometry, merged into ONE
/// mesh per location (vertex colours from the payload <c>style</c>):
///
///   plates — polygon top face at <c>top_y</c>, holes cut out, plus underside
///            and rims when <c>thickness</c> &gt; 0 (three: ExtrudeGeometry
///            down by the thickness; thickness 0 = a bare top face);
///   walls  — one box per piece, centred on the from→to midpoint, from
///            <c>base_y</c> up by <c>height</c> (<c>buildWall</c>);
///   extras — one box per entry, centre + own size, optional XYZ Euler in
///            degrees (<c>buildExtra</c>).
///
/// A wall piece flagged <c>door_prop</c> is not drawn (the contract hands that
/// opening to a door prop in <c>models[]</c>); it is counted separately, not as
/// skipped. Degenerate entries (outline &lt; 3 points, zero-length wall, empty
/// box) are skipped and counted. <c>floor_plan</c>, <c>stairs</c>, markers and
/// doorways are data, not geometry, and are not read here.
/// </summary>
public static class RecipeMeshes
{
    public static (MeshInstance3D? Node, RecipeStats Stats) Build(ScenePayload scene, string name)
    {
        var stats = new RecipeStats();
        var st = new SurfaceTool();
        st.Begin(Mesh.PrimitiveType.Triangles);
        var b = new Builder(st);

        var floor = StyleColor(scene, "floor_color", new Color(0.72f, 0.69f, 0.63f));
        var wall = StyleColor(scene, "wall_color", new Color(0.85f, 0.81f, 0.75f));
        var glass = StyleColor(scene, "glass_color", new Color(0.61f, 0.76f, 0.88f));
        var door = StyleColor(scene, "door_color", new Color(0.35f, 0.27f, 0.20f));
        var stair = StyleColor(scene, "stair_color", new Color(0.62f, 0.58f, 0.52f));
        var extra = StyleColor(scene, "elevator_frame_color", new Color(0.60f, 0.60f, 0.60f));

        foreach (var p in scene.Plates)
        {
            if (p.Outline.Length < 3 || !b.Plate(p, floor)) { stats.Skipped++; continue; }
            stats.Plates++;
        }
        foreach (var w in scene.Walls)
        {
            if (w.DoorProp) { stats.DoorPropLeaves++; continue; }
            double dx = w.To.X - w.From.X, dz = w.To.Z - w.From.Z;
            double len = Math.Sqrt(dx * dx + dz * dz);
            if (!(len > 1e-6) || !(w.Height > 0)) { stats.Skipped++; continue; }
            var dir = new Vector3((float)(dx / len), 0, (float)(dz / len));
            var side = new Vector3(-dir.Z, 0, dir.X);
            var center = new Vector3((float)((w.From.X + w.To.X) / 2), (float)(w.BaseY + w.Height / 2),
                                     (float)((w.From.Z + w.To.Z) / 2));
            var basis = new Basis(dir * (float)len, Vector3.Up * (float)w.Height,
                                  side * (float)Math.Max(w.Thickness, 0.001));
            b.Box(new Transform3D(basis, center), w.Glass ? glass : w.Leaf ? door : wall);
            stats.Walls++;
        }
        foreach (var e in scene.Extras)
        {
            if (e.Center.Length < 3 || e.Size.Length < 3 || !(e.Size[0] > 0 && e.Size[1] > 0 && e.Size[2] > 0))
            {
                stats.Skipped++;
                continue;
            }
            var rot = e.Rotation is { Length: >= 3 } r
                ? Basis.FromEuler(new Vector3((float)Deg(r[0]), (float)Deg(r[1]), (float)Deg(r[2])), EulerOrder.Xyz)
                : Basis.Identity;
            var basis = rot * Basis.FromScale(new Vector3((float)e.Size[0], (float)e.Size[1], (float)e.Size[2]));
            var center = new Vector3((float)e.Center[0], (float)e.Center[1], (float)e.Center[2]);
            var color = e.Kind.StartsWith("stair", StringComparison.Ordinal) ? stair
                      : e.Kind.Contains("glass", StringComparison.Ordinal) ? glass : extra;
            b.Box(new Transform3D(basis, center), color);
            stats.Extras++;
        }
        if (b.Triangles == 0) return (null, stats);
        st.SetMaterial(Materials.VertexColor);
        var mesh = st.Commit();
        return (new MeshInstance3D { Name = name, Mesh = mesh }, stats);
    }

    private static double Deg(double d) => d * Math.PI / 180.0;

    private static Color StyleColor(ScenePayload scene, string key, Color fallback)
        => scene.Style.TryGetValue(key, out var s) && Color.HtmlIsValid(s) ? Color.FromHtml(s) : fallback;

    /// <summary>Triangle sink that orients every triangle to its intended normal.</summary>
    private sealed class Builder
    {
        private readonly SurfaceTool _st;
        public int Triangles { get; private set; }

        public Builder(SurfaceTool st) => _st = st;

        /// <summary>
        /// Godot's front faces wind clockwise as seen by the viewer, i.e.
        /// <c>cross(b−a, c−a)</c> points AWAY from the side the face is seen
        /// from. Swap b and c when the winding does not match <paramref name="n"/>.
        /// </summary>
        public void Tri(Vector3 a, Vector3 b, Vector3 c, Vector3 n, Color color)
        {
            if ((b - a).Cross(c - a).Dot(n) > 0) (b, c) = (c, b);
            foreach (var v in new[] { a, b, c })
            {
                _st.SetNormal(n);
                _st.SetColor(color);
                _st.AddVertex(v);
            }
            Triangles++;
        }

        /// <summary>Unit cube [−½, ½]³ mapped through <paramref name="xf"/>, six faces.</summary>
        public void Box(Transform3D xf, Color color)
        {
            Vector3 P(float x, float y, float z) => xf * new Vector3(x, y, z);
            var axes = new[] { Vector3.Right, Vector3.Up, Vector3.Back };
            foreach (var axis in axes)
            foreach (var sign in new[] { 1f, -1f })
            {
                // Two in-plane axes of this face.
                var u = axis == Vector3.Right ? Vector3.Up : Vector3.Right;
                var v = axis.Cross(u);
                var c = axis * (0.5f * sign);
                var q = new[]
                {
                    P(c.X - u.X / 2 - v.X / 2, c.Y - u.Y / 2 - v.Y / 2, c.Z - u.Z / 2 - v.Z / 2),
                    P(c.X + u.X / 2 - v.X / 2, c.Y + u.Y / 2 - v.Y / 2, c.Z + u.Z / 2 - v.Z / 2),
                    P(c.X + u.X / 2 + v.X / 2, c.Y + u.Y / 2 + v.Y / 2, c.Z + u.Z / 2 + v.Z / 2),
                    P(c.X - u.X / 2 + v.X / 2, c.Y - u.Y / 2 + v.Y / 2, c.Z - u.Z / 2 + v.Z / 2),
                };
                // The face normal is the transformed axis (inverse-transpose for scale).
                var n = (xf.Basis.Inverse().Transposed() * (axis * sign)).Normalized();
                Tri(q[0], q[1], q[2], n, color);
                Tri(q[0], q[2], q[3], n, color);
            }
        }

        /// <summary>One plate; false when its polygon cannot be triangulated.</summary>
        public bool Plate(ScenePlate p, Color color)
        {
            var outline = p.Outline.Select(v => new Vector2((float)v.X, (float)v.Z)).ToArray();
            var holes = p.Holes.Where(h => h.Length >= 3)
                               .Select(h => h.Select(v => new Vector2((float)v.X, (float)v.Z)).ToArray()).ToArray();
            var pieces = PolygonsWithoutHoles(outline, holes);
            float top = (float)p.TopY, bottom = (float)(p.TopY - Math.Max(p.Thickness, 0));
            bool solid = p.Thickness > 0;
            int before = Triangles;
            foreach (var poly in pieces)
            {
                var idx = Geometry2D.TriangulatePolygon(poly);
                for (int i = 0; i + 2 < idx.Length; i += 3)
                {
                    var a = poly[idx[i]]; var bb = poly[idx[i + 1]]; var c = poly[idx[i + 2]];
                    Tri(new Vector3(a.X, top, a.Y), new Vector3(bb.X, top, bb.Y), new Vector3(c.X, top, c.Y), Vector3.Up, color);
                    if (solid)
                        Tri(new Vector3(a.X, bottom, a.Y), new Vector3(bb.X, bottom, bb.Y), new Vector3(c.X, bottom, c.Y), Vector3.Down, color);
                }
            }
            if (Triangles == before) return false;
            if (!solid) return true;
            // Rims: every edge of the outline and of every hole, facing away
            // from the solid side.
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
                    var a0 = new Vector3(a.X, bottom, a.Y); var a1 = new Vector3(a.X, top, a.Y);
                    var c0 = new Vector3(c.X, bottom, c.Y); var c1 = new Vector3(c.X, top, c.Y);
                    Tri(a0, c0, c1, n, color);
                    Tri(a0, c1, a1, n, color);
                }
            return true;
        }
    }

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
