using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// One built primitive in the location frame, laid out like three's buffers: positions, normals and uvs per
/// vertex, triangles as index triples wound COUNTER-CLOCKWISE seen from the front (three's rule —
/// <c>cross(b − a, c − a)</c> points out of the front face). A renderer with the other rule (Godot) reverses
/// each triple when it emits it. UVs are three's uvs: v grows upward on the image (three uploads with flipY).
/// </summary>
public sealed class MeshData
{
    public readonly List<Vec3> Positions = new();
    public readonly List<Vec3> Normals = new();
    public readonly List<(double U, double V)> Uvs = new();
    public readonly List<int> Indices = new();

    public int Triangles => Indices.Count / 3;

    /// <summary>The axis-aligned bounds of every vertex (three's <c>Box3.setFromObject</c> on this mesh).</summary>
    public VBox Bounds()
    {
        if (Positions.Count == 0) return new VBox(new Vec3(double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity),
                                                   new Vec3(double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity));
        return new VBox(new Vec3(Positions.Min(p => p.X), Positions.Min(p => p.Y), Positions.Min(p => p.Z)),
                        new Vec3(Positions.Max(p => p.X), Positions.Max(p => p.Y), Positions.Max(p => p.Z)));
    }
}

/// <summary>A rotation followed by a translation (three's <c>mesh.rotation</c> + <c>mesh.position</c>).</summary>
public readonly record struct RigidXf(Mat3 Rotation, Vec3 Position)
{
    public Vec3 Apply(Vec3 v)
    {
        var r = Rotation.Apply(v);
        return new Vec3(r.X + Position.X, r.Y + Position.Y, r.Z + Position.Z);
    }
}

/// <summary>
/// The native twins of the shared primitive builders (packages/scene-render/src/primitives.ts
/// <c>buildWall</c>/<c>buildExtra</c>/<c>buildPlate</c>/<c>buildPlaceholder</c>) — not approximations but ports of
/// the three.js geometry they hand the GPU:
///
///   • a box is <c>BoxGeometry</c> (faces px, nx, py, ny, pz, nz, four vertices each, uv 0..1 per face) with the
///     uvs rescaled to world metres per tile by <c>applyWorldScaleWallUVs</c>;
///   • a plate is <c>ShapeGeometry</c> (bare face) or <c>ExtrudeGeometry</c> (body, no bevel, one step) over the
///     <see cref="PrimitiveMath.PlateShape"/> rings, triangulated by the same earcut with the same point order
///     (three's <c>getPoints</c>, winding normalisation and, for the body, <c>mergeOverlappingPoints</c>), its
///     uvs from <c>WorldUVGenerator</c>; then turned by ±90° about x and lifted to <c>top_y</c>.
///
/// Checked by the wall/extra/plate measurements of shared/test-vectors/scene_primitives.json.
/// </summary>
public static class RecipeGeometry
{
    // ---- boxes --------------------------------------------------------------------------------

    /// <summary>three's <c>BoxGeometry(width, height, depth)</c> at one segment per side, around the origin.</summary>
    public static MeshData Box(double width, double height, double depth)
    {
        var m = new MeshData();
        // buildPlane(u, v, w, udir, vdir, width, height, depth) — the six calls of BoxGeometry, in order.
        Plane(m, 'z', 'y', 'x', -1, -1, depth, height, width);   // px
        Plane(m, 'z', 'y', 'x', 1, -1, depth, height, -width);   // nx
        Plane(m, 'x', 'z', 'y', 1, 1, width, depth, height);     // py
        Plane(m, 'x', 'z', 'y', 1, -1, width, depth, -height);   // ny
        Plane(m, 'x', 'y', 'z', 1, -1, width, height, depth);    // pz
        Plane(m, 'x', 'y', 'z', -1, -1, width, height, -depth);  // nz
        return m;
    }

    private static void Plane(MeshData m, char u, char v, char w, double udir, double vdir,
                              double width, double height, double depth)
    {
        int start = m.Positions.Count;
        double widthHalf = width / 2, heightHalf = height / 2, depthHalf = depth / 2;
        static Vec3 Set(char a, double va, char b, double vb, char c, double vc)
        {
            double x = 0, y = 0, z = 0;
            void Put(char k, double val) { if (k == 'x') x = val; else if (k == 'y') y = val; else z = val; }
            Put(a, va); Put(b, vb); Put(c, vc);
            return new Vec3(x, y, z);
        }
        for (int iy = 0; iy < 2; iy++)
        {
            double y = iy * height - heightHalf;
            for (int ix = 0; ix < 2; ix++)
            {
                double x = ix * width - widthHalf;
                m.Positions.Add(Set(u, x * udir, v, y * vdir, w, depthHalf));
                m.Normals.Add(Set(u, 0, v, 0, w, depth > 0 ? 1 : -1));
                m.Uvs.Add((ix, 1 - iy));
            }
        }
        int a = start, b = start + 2, c = start + 3, d = start + 1;
        m.Indices.AddRange(new[] { a, b, d, b, c, d });
    }

    /// <summary><c>applyWorldScaleWallUVs</c>: every face's uvs times its own extent over the tile; tileM 0 leaves 0..1.</summary>
    public static void WorldScaleUVs(MeshData box, double width, double height, double depth, double tileM)
    {
        if (!(tileM > 0) || box.Uvs.Count != 24) return;
        var faces = PrimitiveMath.BoxFaceUVs(width, height, depth, tileM);
        for (int f = 0; f < 6; f++)
            for (int i = f * 4; i < f * 4 + 4; i++)
                box.Uvs[i] = (box.Uvs[i].U * faces[f].U, box.Uvs[i].V * faces[f].V);
    }

    /// <summary>A copy of <paramref name="m"/> under <paramref name="xf"/> (normals turned, not translated).</summary>
    public static MeshData Transform(MeshData m, RigidXf xf)
    {
        var o = new MeshData();
        o.Positions.AddRange(m.Positions.Select(xf.Apply));
        o.Normals.AddRange(m.Normals.Select(xf.Rotation.Apply));
        o.Uvs.AddRange(m.Uvs);
        o.Indices.AddRange(m.Indices);
        return o;
    }

    /// <summary>Where <c>buildWall</c> puts its box: the segment midpoint, rotation.y = −atan2(dz, dx).</summary>
    public static RigidXf WallXf(SceneWall wall)
    {
        var t = PrimitiveMath.WallTransform(wall);
        return new RigidXf(Mat3.RotY(t.Yaw), t.Position);
    }

    /// <summary><c>buildWall</c>: a box length × height × thickness with world-scale uvs, in the location frame.</summary>
    public static MeshData Wall(SceneWall wall, double tileM)
    {
        var t = PrimitiveMath.WallTransform(wall);
        var box = Box(t.Size.X, wall.Height, wall.Thickness);
        WorldScaleUVs(box, t.Size.X, wall.Height, wall.Thickness, tileM);
        return Transform(box, WallXf(wall));
    }

    /// <summary>Where <c>buildExtra</c> puts its box: its centre, the XYZ Euler of <see cref="PrimitiveMath.ExtraMatrix"/>.</summary>
    public static RigidXf ExtraTransform(SceneExtra extra)
        => new(PrimitiveMath.ExtraMatrix(extra), new Vec3(extra.Center[0], extra.Center[1], extra.Center[2]));

    /// <summary><c>buildExtra</c>: a box of the extra's own size, world-scale uvs, turned and centred.</summary>
    public static MeshData Extra(SceneExtra extra, double tileM)
    {
        var box = Box(extra.Size[0], extra.Size[1], extra.Size[2]);
        WorldScaleUVs(box, extra.Size[0], extra.Size[1], extra.Size[2], tileM);
        return Transform(box, ExtraTransform(extra));
    }

    /// <summary><c>buildPlaceholder</c>: the clamped box with its origin at the bottom face's centre (local frame).</summary>
    public static MeshData Placeholder(double w, double d, double h)
    {
        var b = PrimitiveMath.PlaceholderBox(w, d, h);
        return Transform(Box(b.Size.X, b.Size.Y, b.Size.Z), new RigidXf(Mat3.Identity, b.Offset));
    }

    // ---- plates -------------------------------------------------------------------------------

    /// <summary>
    /// The points three's <c>Path.getPoints()</c> yields for <c>moveTo(p0)</c>, <c>lineTo(p1 … pn−1)</c>,
    /// <c>closePath()</c>: every line's end points, consecutive duplicates skipped, so the ring comes back closed
    /// (p0 again at the end) unless pn−1 already was p0.
    /// </summary>
    internal static List<P2> PathPoints(IReadOnlyList<P2> ring)
    {
        var pts = new List<P2>();
        if (ring.Count < 2) return pts;
        var curves = new List<(P2 A, P2 B)>();
        for (int i = 1; i < ring.Count; i++) curves.Add((ring[i - 1], ring[i]));
        if (!ring[0].Equals(ring[^1])) curves.Add((ring[^1], ring[0]));
        P2? last = null;
        foreach (var (a, b) in curves)
            foreach (var p in new[] { a, b })
            {
                if (last is { } l && l.Equals(p)) continue;
                pts.Add(p);
                last = p;
            }
        return pts;
    }

    /// <summary><c>ShapeUtils.area</c>.</summary>
    private static double ShapeArea(List<P2> c)
    {
        int n = c.Count;
        double a = 0;
        for (int p = n - 1, q = 0; q < n; p = q++) a += c[p].X * c[q].Z - c[q].X * c[p].Z;
        return a * 0.5;
    }

    private static bool IsClockWise(List<P2> pts) => ShapeArea(pts) < 0;

    private static void RemoveDupEndPts(List<P2> points)
    {
        int l = points.Count;
        if (l > 2 && points[l - 1].Equals(points[0])) points.RemoveAt(l - 1);
    }

    /// <summary><c>ShapeUtils.triangulateShape</c>: faces as index triples into contour ++ holes (mutates like three).</summary>
    private static List<int> TriangulateShape(List<P2> contour, List<List<P2>> holes)
    {
        var vertices = new List<double>();
        var holeIndices = new List<int>();
        RemoveDupEndPts(contour);
        foreach (var p in contour) { vertices.Add(p.X); vertices.Add(p.Z); }
        int holeIndex = contour.Count;
        holes.ForEach(RemoveDupEndPts);
        foreach (var h in holes)
        {
            holeIndices.Add(holeIndex);
            holeIndex += h.Count;
            foreach (var p in h) { vertices.Add(p.X); vertices.Add(p.Z); }
        }
        return Earcut.Triangulate(vertices, holeIndices);
    }

    /// <summary><c>ExtrudeGeometry</c>'s <c>mergeOverlappingPoints</c> (in place; wraps around, may drop the first point).</summary>
    private static void MergeOverlappingPoints(List<P2> points)
    {
        const double threshold = 1e-10, thresholdSq = threshold * threshold;
        if (points.Count == 0) return;
        var prevPos = points[0];
        for (int i = 1; i <= points.Count; i++)
        {
            int currentIndex = i % points.Count;
            var currentPos = points[currentIndex];
            double dx = currentPos.X - prevPos.X, dy = currentPos.Z - prevPos.Z;
            double distSq = dx * dx + dy * dy;
            double s = Math.Max(Math.Max(Math.Abs(currentPos.X), Math.Abs(currentPos.Z)), Math.Max(Math.Abs(prevPos.X), Math.Abs(prevPos.Z)));
            if (distSq <= thresholdSq * s * s)
            {
                points.RemoveAt(currentIndex);
                i--;
                if (points.Count == 0) return;
                continue;
            }
            prevPos = currentPos;
        }
    }

    /// <summary>
    /// <c>buildPlate</c>: a body (<c>thickness</c> &gt; 0) extruded DOWN from <c>top_y</c>, or a bare face at
    /// <c>top_y</c>; holes taken out. Empty when the outline does not triangulate.
    /// </summary>
    public static MeshData Plate(ScenePlate plate)
    {
        var shape = PrimitiveMath.PlateShape(plate);
        var shapeMesh = shape.Solid ? Extrude(shape, plate.Thickness) : Flat(shape);
        return Transform(shapeMesh, new RigidXf(Mat3.RotX(shape.RotationX), new Vec3(0, plate.TopY, 0)));
    }

    /// <summary>The top face's triangle count — 0 = nothing to draw (a degenerate plate).</summary>
    public static int TopTriangles(ScenePlate plate)
        => Flat(PrimitiveMath.PlateShape(plate)).Triangles;

    /// <summary><c>ShapeGeometry</c> in its own plane (z = 0, normal +z, uv = the shape point).</summary>
    private static MeshData Flat(PlateShapeResult shape)
    {
        var m = new MeshData();
        if (shape.Outline.Length < 3) return m;
        var shapeVertices = PathPoints(shape.Outline);
        var shapeHoles = shape.Holes.Select(h => PathPoints(h)).ToList();
        if (!IsClockWise(shapeVertices)) shapeVertices.Reverse();
        foreach (var h in shapeHoles) if (IsClockWise(h)) h.Reverse();
        var faces = TriangulateShape(shapeVertices, shapeHoles);
        foreach (var p in shapeVertices.Concat(shapeHoles.SelectMany(h => h)))
        {
            m.Positions.Add(new Vec3(p.X, p.Z, 0));
            m.Normals.Add(new Vec3(0, 0, 1));
            m.Uvs.Add((p.X, p.Z));
        }
        m.Indices.AddRange(faces);
        return m;
    }

    /// <summary><c>ExtrudeGeometry(shape, { depth, bevelEnabled: false })</c>: non-indexed, flat normals, world uvs.</summary>
    private static MeshData Extrude(PlateShapeResult shape, double depth)
    {
        var m = new MeshData();
        if (shape.Outline.Length < 3) return m;
        var contour = PathPoints(shape.Outline);
        var holes = shape.Holes.Select(h => PathPoints(h)).ToList();
        if (!IsClockWise(contour))
        {
            contour.Reverse();
            foreach (var h in holes) if (IsClockWise(h)) h.Reverse();
        }
        MergeOverlappingPoints(contour);
        holes.ForEach(MergeOverlappingPoints);
        var vertices = contour.Concat(holes.SelectMany(h => h)).ToList();
        var faces = TriangulateShape(contour, holes);
        int vlen = vertices.Count;
        // Layer 0 at z = 0, layer 1 (steps = 1) at z = depth.
        var placeholder = new List<Vec3>(vlen * 2);
        foreach (var v in vertices) placeholder.Add(new Vec3(v.X, v.Z, 0));
        foreach (var v in vertices) placeholder.Add(new Vec3(v.X, v.Z, depth));

        void F3(int a, int b, int c)
        {
            foreach (var i in new[] { a, b, c })
            {
                var p = placeholder[i];
                m.Indices.Add(m.Positions.Count);
                m.Positions.Add(p);
                m.Uvs.Add((p.X, p.Y)); // generateTopUV
            }
        }
        void F4(int a, int b, int c, int d)
        {
            var pa = placeholder[a]; var pb = placeholder[b]; var pc = placeholder[c]; var pd = placeholder[d];
            // generateSideWallUV
            bool alongX = Math.Abs(pa.Y - pb.Y) < Math.Abs(pa.X - pb.X);
            (double, double) Uv(Vec3 p) => (alongX ? p.X : p.Y, 1 - p.Z);
            foreach (var (p, uv) in new[] { (pa, Uv(pa)), (pb, Uv(pb)), (pd, Uv(pd)), (pb, Uv(pb)), (pc, Uv(pc)), (pd, Uv(pd)) })
            {
                m.Indices.Add(m.Positions.Count);
                m.Positions.Add(p);
                m.Uvs.Add(uv);
            }
        }
        for (int i = 0; i + 2 < faces.Count; i += 3) F3(faces[i + 2], faces[i + 1], faces[i]);            // layer 0
        for (int i = 0; i + 2 < faces.Count; i += 3) F3(faces[i] + vlen, faces[i + 1] + vlen, faces[i + 2] + vlen); // layer 1
        void Sidewalls(List<P2> ring, int layerOffset)
        {
            int i = ring.Count;
            while (--i >= 0)
            {
                int j = i, k = i - 1;
                if (k < 0) k = ring.Count - 1;
                F4(layerOffset + j, layerOffset + k, layerOffset + k + vlen, layerOffset + j + vlen);
            }
        }
        int offset = 0;
        Sidewalls(contour, offset);
        offset += contour.Count;
        foreach (var h in holes) { Sidewalls(h, offset); offset += h.Count; }
        // computeVertexNormals on a non-indexed geometry: every triangle's own face normal.
        for (int t = 0; t < m.Positions.Count; t += 3)
        {
            var n = FaceNormal(m.Positions[t], m.Positions[t + 1], m.Positions[t + 2]);
            m.Normals.Add(n); m.Normals.Add(n); m.Normals.Add(n);
        }
        return m;
    }

    /// <summary>The unit normal of a counter-clockwise front face (three's <c>computeVertexNormals</c>: (c − b) × (a − b)).</summary>
    public static Vec3 FaceNormal(Vec3 a, Vec3 b, Vec3 c)
    {
        double cbx = c.X - b.X, cby = c.Y - b.Y, cbz = c.Z - b.Z;
        double abx = a.X - b.X, aby = a.Y - b.Y, abz = a.Z - b.Z;
        double nx = cby * abz - cbz * aby, ny = cbz * abx - cbx * abz, nz = cbx * aby - cby * abx;
        double l = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        return l > 0 ? new Vec3(nx / l, ny / l, nz / l) : new Vec3(0, 0, 0);
    }
}
