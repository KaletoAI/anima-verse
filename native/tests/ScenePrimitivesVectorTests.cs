using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/scene_primitives.json against <see cref="PrimitiveMath"/> and the native mesh
/// builders of <see cref="RecipeGeometry"/> (hand derivations: client3d/scripts/smoke_scene_primitives.mjs;
/// TS sources: packages/scene-render/src/primitiveMath.ts + primitives.ts).
///
/// <code>
///   TS fn                    C#
///   wallTransform            PrimitiveMath.WallTransform        wall → ScenePayload walls[0]
///   boxFaceUVs               PrimitiveMath.BoxFaceUVs
///   extraCorners             PrimitiveMath.ExtraCorners         extra → ScenePayload extras[0]
///   placeholderBox           PrimitiveMath.PlaceholderBox
///   plateShape               PrimitiveMath.PlateShape           plate → ScenePayload plates[0]
///   wallMeshMeasurements     the 31 smoke_wall_uv measurements on RecipeGeometry.Wall
///   extraMeshMeasurements    the 12 smoke_extra_box measurements on RecipeGeometry.Extra / ExtraTransform
///   plateMeshMeasurements    the 34 smoke_plate_hole measurements on RecipeGeometry.Plate
/// </code>
///
/// The three measurement functions are the smokes' own measuring code, re-stated here over the NATIVE
/// mesh (positions, normals, uvs, triangles in three's front-face winding) instead of three's buffers: the
/// expectation list is the same hand-derived one, so the native builders answer the browser's numbers.
/// </summary>
public class ScenePrimitivesVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scene_primitives"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["wallTransform"] = a =>
        {
            var t = PrimitiveMath.WallTransform(Wall(Arity(a, 1, 1)[0]));
            return new JsonObject { ["size"] = Arr(t.Size), ["position"] = Arr(t.Position), ["yaw"] = t.Yaw };
        },
        ["boxFaceUVs"] = a => new JsonArray(PrimitiveMath.BoxFaceUVs(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3]))
            .Select(f => (JsonNode?)new JsonArray(f.U, f.V)).ToArray()),
        ["extraCorners"] = a =>
        {
            Arity(a, 1, 2);
            var pts = Arg(a, 1) is JsonArray p ? p.Select(V3).ToList() : null;
            return new JsonArray(PrimitiveMath.ExtraCorners(Extra(a[0]), pts).Select(v => (JsonNode?)Arr(v)).ToArray());
        },
        ["placeholderBox"] = a =>
        {
            var d = Arity(a, 1, 1)[0];
            var b = PrimitiveMath.PlaceholderBox(Num(Key(d, "w")), Num(Key(d, "d")), Num(Key(d, "h")));
            return new JsonObject { ["size"] = Arr(b.Size), ["offset"] = Arr(b.Offset), ["min"] = Arr(b.Min), ["max"] = Arr(b.Max) };
        },
        ["plateShape"] = a =>
        {
            var s = PrimitiveMath.PlateShape(Plate(Arity(a, 1, 1)[0]));
            return new JsonObject
            {
                ["solid"] = s.Solid, ["rotationX"] = s.RotationX, ["outline"] = RingJson(s.Outline),
                ["holes"] = new JsonArray(s.Holes.Select(h => (JsonNode?)RingJson(h)).ToArray()),
            };
        },
        ["wallMeshMeasurements"] = a => WallMeasurements(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3])),
        ["extraMeshMeasurements"] = a => ExtraMeasurements(Arity(a, 1, 1)[0]),
        ["plateMeshMeasurements"] = a => PlateMeasurements(Arity(a, 1, 1)[0]),
    };

    private static SceneWall Wall(JsonNode? n) => SceneOf("walls", n).Walls.Single();
    private static SceneExtra Extra(JsonNode? n) => SceneOf("extras", n).Extras.Single();
    private static ScenePlate Plate(JsonNode? n) => SceneOf("plates", n).Plates.Single();

    // ---- [1] smoke_wall_uv --------------------------------------------------------------------

    /// <summary>uv spans per face, keyed by the face's own normal ('+x', '-y', ...) — smoke_wall_uv faceSpans.</summary>
    private static Dictionary<string, (double U, double V)> FaceSpans(MeshData m)
    {
        if (m.Uvs.Count != 24) throw new InvalidOperationException($"expected 24 box vertices, got {m.Uvs.Count}");
        var o = new Dictionary<string, (double, double)>();
        for (int f = 0; f < 6; f++)
        {
            var n = m.Normals[f * 4];
            char axis = Math.Abs(n.X) > 0.5 ? 'x' : Math.Abs(n.Y) > 0.5 ? 'y' : 'z';
            double comp = axis == 'x' ? n.X : axis == 'y' ? n.Y : n.Z;
            var uvs = m.Uvs.Skip(f * 4).Take(4).ToList();
            o[(comp > 0 ? "+" : "-") + axis] = (uvs.Max(u => u.U) - uvs.Min(u => u.U), uvs.Max(u => u.V) - uvs.Min(u => u.V));
        }
        if (o.Count != 6) throw new InvalidOperationException("two box faces share a normal — layout changed");
        return o;
    }

    private static MeshData BuiltWall(double len, double height, double thickness, double tileM)
        => RecipeGeometry.Wall(Wall(JsonNode.Parse(
            $"{{\"room_id\":\"r\",\"level\":0,\"from\":[0,0],\"to\":[{J(len)},0],\"height\":{J(height)},"
            + $"\"thickness\":{J(thickness)},\"base_y\":0,\"outward_normal\":[0,-1],\"texture_kind\":\"brick\",\"glass\":false}}")), tileM);

    private static string J(double v) => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);

    private static JsonArray WallMeasurements(double len, double high, double thick, double tile)
    {
        var o = new List<double>();
        var s = FaceSpans(BuiltWall(len, high, thick, tile));
        foreach (var f in new[] { "+z", "-z", "+x", "-x", "+y", "-y" }) { o.Add(s[f].U); o.Add(s[f].V); }
        var sill = FaceSpans(BuiltWall(1.2, 0.9, thick, tile));
        o.Add(sill["+y"].U); o.Add(sill["+y"].V); o.Add(sill["+z"].U); o.Add(sill["+z"].V);
        double oldU = len / tile;
        o.Add(oldU);
        o.Add(oldU / s["+x"].U);
        o.Add((0.9 / tile) / sill["+y"].V);
        var plain = FaceSpans(BuiltWall(len, high, thick, 0));
        foreach (var f in new[] { "+x", "+y", "+z" }) { o.Add(plain[f].U); o.Add(plain[f].V); }
        var box = BuiltWall(len, high, thick, tile).Bounds();
        o.Add(box.Min.Y); o.Add(box.Max.Y);
        o.Add((box.Min.X + box.Max.X) / 2); o.Add((box.Min.Z + box.Max.Z) / 2);
        o.Add(box.Max.X - box.Min.X); o.Add(box.Max.Z - box.Min.Z);
        return Nums(o);
    }

    // ---- [2] smoke_extra_box ------------------------------------------------------------------

    private static JsonArray ExtraMeasurements(JsonNode? input)
    {
        var east = Extra(Key(input, "east"));
        var south = Extra(Key(input, "south"));
        var treadSpec = Extra(Key(input, "tread"));
        double tileM = Num(Key(input, "tileM"));
        double L = east.Size[0], d = east.Size[1];
        JsonArray Corner(SceneExtra e, Vec3 local) => Arr(RecipeGeometry.ExtraTransform(e).Apply(local));
        JsonArray FaceMax(MeshData m, int f)
        {
            double mu = 0, mv = 0;
            for (int i = f * 4; i < f * 4 + 4; i++) { mu = Math.Max(mu, m.Uvs[i].U); mv = Math.Max(mv, m.Uvs[i].V); }
            return new JsonArray(mu, mv);
        }
        var er = PrimitiveMath.ExtraRotation(east);
        var tread = RecipeGeometry.Extra(treadSpec, tileM);
        var plain = RecipeGeometry.Extra(treadSpec, 0);
        var pr = PrimitiveMath.ExtraRotation(treadSpec);
        var pos = RecipeGeometry.ExtraTransform(treadSpec).Position;
        return new JsonArray(
            er.Z,
            new JsonArray(er.X, er.Y),
            Corner(east, new Vec3(-L / 2, d / 2, 0)),
            Corner(east, new Vec3(L / 2, d / 2, 0)),
            Corner(south, new Vec3(0, d / 2, -L / 2)),
            Corner(south, new Vec3(0, d / 2, L / 2)),
            FaceMax(tread, 0), FaceMax(tread, 2), FaceMax(tread, 4),
            new JsonArray(FaceMax(plain, 0), FaceMax(plain, 2), FaceMax(plain, 4)),
            new JsonArray(pr.X, pr.Y, pr.Z),
            Arr(pos));
    }

    // ---- [3] smoke_plate_hole -----------------------------------------------------------------

    private static List<Vec3[]> Triangles(MeshData m)
    {
        var o = new List<Vec3[]>();
        for (int i = 0; i + 2 < m.Indices.Count; i += 3)
            o.Add(new[] { m.Positions[m.Indices[i]], m.Positions[m.Indices[i + 1]], m.Positions[m.Indices[i + 2]] });
        return o;
    }

    private static List<Vec3[]> TopFace(List<Vec3[]> tris, double topY)
        => tris.Where(t => t.All(p => Math.Abs(p.Y - topY) < 1e-6)).ToList();

    private static List<Vec3[]> SideFaces(List<Vec3[]> tris, double topY, double bottomY)
        => tris.Where(t => t.Any(p => Math.Abs(p.Y - topY) < 1e-6) && t.Any(p => Math.Abs(p.Y - bottomY) < 1e-6)).ToList();

    private static Vec3 TriNormal(Vec3[] t)
    {
        double ux = t[1].X - t[0].X, uy = t[1].Y - t[0].Y, uz = t[1].Z - t[0].Z;
        double vx = t[2].X - t[0].X, vy = t[2].Y - t[0].Y, vz = t[2].Z - t[0].Z;
        double nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
        double l = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        return l > 0 ? new Vec3(nx / l, ny / l, nz / l) : new Vec3(0, 0, 0);
    }

    private static P2 CentroidXZ(List<P2> pts) => new(pts.Average(p => p.X), pts.Average(p => p.Z));

    private static int Facing(List<Vec3[]> tris, P2 c, int sign)
        => tris.Count(t =>
        {
            var n = TriNormal(t);
            double mx = t.Sum(p => p.X / 3), mz = t.Sum(p => p.Z / 3);
            return sign * (n.X * (mx - c.X) + n.Z * (mz - c.Z)) > 1e-9;
        });

    private static List<Vec3[]> WallsOfRect(List<Vec3[]> tris, List<P2> ring)
    {
        double x0 = ring.Min(p => p.X), x1 = ring.Max(p => p.X), z0 = ring.Min(p => p.Z), z1 = ring.Max(p => p.Z);
        return tris.Where(t => t.All(p => p.X >= x0 - 1e-6 && p.X <= x1 + 1e-6 && p.Z >= z0 - 1e-6 && p.Z <= z1 + 1e-6)).ToList();
    }

    private static double AreaXZ(Vec3[] t)
        => Math.Abs((t[1].X - t[0].X) * (t[2].Z - t[0].Z) - (t[2].X - t[0].X) * (t[1].Z - t[0].Z)) / 2;

    private static bool InsideXZ(Vec3[] t, double x, double z)
    {
        double D(Vec3 p, Vec3 q) => (q.X - p.X) * (z - p.Z) - (x - p.X) * (q.Z - p.Z);
        double s1 = D(t[0], t[1]), s2 = D(t[1], t[2]), s3 = D(t[2], t[0]);
        bool neg = s1 < -1e-12 || s2 < -1e-12 || s3 < -1e-12;
        bool pos = s1 > 1e-12 || s2 > 1e-12 || s3 > 1e-12;
        return !(neg && pos);
    }

    private static int Covers(List<Vec3[]> tris, double x, double z) => tris.Count(t => InsideXZ(t, x, z));

    private static JsonArray PlateMeasurements(JsonNode? input)
    {
        var outline = Key(input, "outline")!;
        var hole = Key(input, "hole")!;
        var hole2 = Key(input, "hole2")!;
        ScenePlate Spec(JsonArray holes, double thickness, double topY) => Plate(new JsonObject
        {
            ["level"] = 1, ["outline"] = outline.DeepClone(), ["holes"] = holes, ["top_y"] = topY,
            ["thickness"] = thickness, ["opacity_role"] = "upper", ["room_id"] = "hall",
        });
        var o = new JsonArray();
        void Add(JsonNode? v) => o.Add(v);
        JsonArray Targets(ScenePlate p, VBox box)
            => Nums(SceneVerify.PlateTargets(p).Select(t => t.Actual(box) - t.Target));

        {
            var spec = Spec(new JsonArray(hole.DeepClone()), 0.10, 3.08);
            var mesh = RecipeGeometry.Plate(spec);
            var tris = Triangles(mesh);
            var top = TopFace(tris, 3.08);
            Add(top.Sum(AreaXZ));
            Add(top.Count);
            Add(Covers(top, 3.5, 1.5)); Add(Covers(top, 3.5, -1.5)); Add(Covers(top, 1.0, 1.5));
            Add(Covers(top, 6.5, 1.5)); Add(Covers(top, 3.5, 2.9)); Add(Covers(top, 3.5, 0.1));
            var side = SideFaces(tris, 3.08, 2.98);
            Add(side.Count);
            var holeWalls = WallsOfRect(side, Ring(hole));
            var outerWalls = side.Where(t => !holeWalls.Contains(t)).ToList();
            Add(new JsonArray(holeWalls.Count, outerWalls.Count));
            Add(Facing(outerWalls, CentroidXZ(Ring(outline)), +1));
            Add(Facing(holeWalls, CentroidXZ(Ring(hole)), -1));
            var box = mesh.Bounds();
            Add(new JsonArray(box.Min.X, box.Max.X));
            Add(new JsonArray(box.Min.Z, box.Max.Z));
            Add(Targets(spec, box));
        }
        {
            var spec = Spec(new JsonArray(), 0.10, 3.08);
            var tris = Triangles(RecipeGeometry.Plate(spec));
            var top = TopFace(tris, 3.08);
            Add(top.Sum(AreaXZ)); Add(top.Count); Add(Covers(top, 3.5, 1.5));
            Add(SideFaces(tris, 3.08, 2.98).Count);
        }
        {
            var spec = Spec(new JsonArray(hole.DeepClone()), 0, 0);
            var mesh = RecipeGeometry.Plate(spec);
            var top = TopFace(Triangles(mesh), 0);
            Add(top.Sum(AreaXZ)); Add(top.Count);
            Add(Covers(top, 3.5, 1.5)); Add(Covers(top, 3.5, -1.5));
            Add(new JsonArray(Covers(top, 1.0, 1.5), Covers(top, 6.5, 1.5)));
            var box = mesh.Bounds();
            Add(new JsonArray(box.Min.X, box.Max.X, box.Min.Z, box.Max.Z));
            Add(Targets(spec, box));
        }
        {
            var spec = Spec(new JsonArray(JsonNode.Parse("[[2, 0.5], [5, 0.5]]"), hole.DeepClone(), new JsonArray()), 0.10, 3.08);
            var top = TopFace(Triangles(RecipeGeometry.Plate(spec)), 3.08);
            Add(top.Sum(AreaXZ)); Add(top.Count);
        }
        {
            var spec = Spec(new JsonArray(hole.DeepClone(), hole2.DeepClone()), 0.10, 3.08);
            var tris = Triangles(RecipeGeometry.Plate(spec));
            var top = TopFace(tris, 3.08);
            Add(top.Sum(AreaXZ)); Add(top.Count);
            Add(new JsonArray(Covers(top, 3.5, 1.5), Covers(top, 6.5, -1.5)));
            Add(Covers(top, 5.5, -1.5));
            var side = SideFaces(tris, 3.08, 2.98);
            Add(side.Count);
            Add(Facing(WallsOfRect(side, Ring(hole2)), CentroidXZ(Ring(hole2)), -1));
        }
        return o;
    }

    public static TheoryData<string> Cases => VectorFile.Labels("scene_primitives");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>The native wall box keeps three's BoxGeometry layout: 24 vertices, 36 indices, 4 per face.</summary>
    [Fact]
    public void WallBoxLayout()
    {
        var m = BuiltWall(10, 3, 0.1, 2);
        Assert.Equal(24, m.Positions.Count);
        Assert.Equal(36, m.Indices.Count);
    }
}
