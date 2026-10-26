using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Bench;

/// <summary>
/// What the directional shadow pass draws, counted on the CPU (Task 26c): every visible <see cref="GeometryInstance3D"/>
/// that casts (<c>cast_shadow</c> not off, its layers inside the sun's <c>shadow_caster_mask</c>) and lies in the caster
/// volume Godot 4.7.2 culls against (renderer_scene_cull.cpp <c>_light_instance_setup_directional_shadow</c>: the
/// light-space x/y box of the camera frustum slice [near, max distance] and everything from its far side towards the
/// light). Draws = mesh surfaces (a Label3D/Sprite3D counts one quad), triangles = indices / 3 (× visible instances for
/// a multimesh). Godot's tighter light culler can only drop more, so the counts are an upper bound of the real pass; the
/// headless dummy renderer reports no draw numbers at all, which is why this exists. The aspect is passed in (headless
/// viewports read 64 × 64).
/// </summary>
public static class ShadowCensus
{
    public readonly record struct Row(string Class, int Instances, int Draws, long Tris);

    public static List<Row> Count(Node root, Camera3D camera, DirectionalLight3D sun, double aspect)
    {
        var rows = new Dictionary<string, (int I, int D, long T)>();
        if (!sun.ShadowEnabled) return new List<Row>();
        double maxD = sun.DirectionalShadowMaxDistance > 0 ? Math.Min(sun.DirectionalShadowMaxDistance, camera.Far) : camera.Far;
        var cam = camera.GlobalTransform;
        double th = Math.Tan(camera.Fov * Math.PI / 360);
        var ends = new List<Vector3>();
        foreach (double z in new[] { (double)camera.Near, maxD })
            for (int sx = -1; sx <= 1; sx += 2)
                for (int sy = -1; sy <= 1; sy += 2)
                    ends.Add(cam * new Vector3((float)(sx * z * th * aspect), (float)(sy * z * th), (float)-z));
        var lb = sun.GlobalTransform.Basis.Orthonormalized();
        Vector3 lx = lb.Column0, ly = lb.Column1, lz = lb.Column2;
        double xMin = ends.Min(e => (double)lx.Dot(e)), xMax = ends.Max(e => (double)lx.Dot(e));
        double yMin = ends.Min(e => (double)ly.Dot(e)), yMax = ends.Max(e => (double)ly.Dot(e));
        double zMin = ends.Min(e => (double)lz.Dot(e));
        uint mask = sun.ShadowCasterMask;
        var stack = new Stack<Node>();
        stack.Push(root);
        while (stack.Count > 0)
        {
            var n = stack.Pop();
            if (n is SubViewport || n is CanvasLayer) continue;
            if (n is Node3D n3 && !n3.Visible) continue;
            foreach (var c in n.GetChildren()) stack.Push(c);
            if (n is not GeometryInstance3D g || g.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off) continue;
            if ((g.Layers & mask) == 0) continue;
            var (draws, tris) = Geometry(g);
            if (draws == 0) continue;
            var box = g.GetAabb();
            var xf = g.GlobalTransform;
            var c0 = xf * box.GetCenter();
            var e = box.Size * 0.5f;
            Vector3 a0 = xf.Basis.Column0 * e.X, a1 = xf.Basis.Column1 * e.Y, a2 = xf.Basis.Column2 * e.Z;
            double R(Vector3 axis) => Math.Abs(axis.Dot(a0)) + Math.Abs(axis.Dot(a1)) + Math.Abs(axis.Dot(a2));
            double cx = lx.Dot(c0), cy = ly.Dot(c0), cz = lz.Dot(c0);
            double rx = R(lx), ry = R(ly), rz = R(lz);
            if (cx + rx < xMin || cx - rx > xMax || cy + ry < yMin || cy - ry > yMax || cz + rz < zMin) continue;
            string key = ClassOf(g);
            rows.TryGetValue(key, out var r);
            rows[key] = (r.I + 1, r.D + draws, r.T + tris);
        }
        return rows.Select(kv => new Row(kv.Key, kv.Value.I, kv.Value.D, kv.Value.T)).OrderByDescending(r => r.Tris).ToList();
    }

    /// <summary>One line: the totals, then every class (draws / triangles in thousands).</summary>
    public static string Summary(List<Row> rows)
        => $"shadow-casters[draws={rows.Sum(r => r.Draws)} tris={rows.Sum(r => r.Tris)} instances={rows.Sum(r => r.Instances)}"
           + string.Concat(rows.Select(r => $" {r.Class}={r.Instances}/{r.Draws}/{r.Tris / 1000.0:0.#}k")) + "]";

    private static (int Draws, long Tris) Geometry(GeometryInstance3D g)
    {
        switch (g)
        {
            case MeshInstance3D { Mesh: { } m }:
                return (m.GetSurfaceCount(), Tris(m));
            case MultiMeshInstance3D { Multimesh: { Mesh: { } mm } multi }:
                int n = multi.VisibleInstanceCount >= 0 ? multi.VisibleInstanceCount : multi.InstanceCount;
                return n > 0 ? (mm.GetSurfaceCount(), Tris(mm) * n) : (0, 0);
            case SpriteBase3D or Label3D:
                return (1, 2);
            default:
                return (0, 0);
        }
    }

    private static long Tris(Mesh m)
    {
        long t = 0;
        for (int s = 0; s < m.GetSurfaceCount(); s++)
        {
            if (m is ArrayMesh am)
            {
                int idx = am.SurfaceGetArrayIndexLen(s);
                t += (idx > 0 ? idx : am.SurfaceGetArrayLen(s)) / 3;
            }
            else
            {
                var arrays = m.SurfaceGetArrays(s);
                var ix = arrays[(int)Mesh.ArrayType.Index];
                t += ix.VariantType != Variant.Type.Nil ? ix.AsInt32Array().Length / 3
                     : arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array().Length / 3;
            }
        }
        return t;
    }

    /// <summary>The class of a caster: its branch under the world (a location's interior apart), recipe or model, placeholder.</summary>
    private static string ClassOf(Node g)
    {
        string branch = "other";
        bool interior = false;
        for (Node? p = g.GetParent(); p is not null; p = p.GetParent())
        {
            string name = p.Name.ToString();
            if (name == "Interior") interior = true;
            if (p.GetParent() is { } pp && pp.Name.ToString() == "World") { branch = name; break; }
            if (name.StartsWith("Loc_", StringComparison.Ordinal) && p.GetParent()?.Name.ToString() == "Locations")
            {
                branch = "loc";
                break;
            }
        }
        string own = g.Name.ToString();
        string kind = own.StartsWith("Recipe", StringComparison.Ordinal) ? "recipe"
                      : own.StartsWith("Placeholder", StringComparison.Ordinal) || g.GetParent()?.Name.ToString() == "Placeholder" ? "placeholder"
                      : g is Label3D or SpriteBase3D ? "sprite" : "mesh";
        return branch == "loc" ? $"loc{(interior ? "-interior" : "")}:{kind}" : $"{branch}:{kind}";
    }
}
