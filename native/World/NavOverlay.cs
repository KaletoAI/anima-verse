using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// F9: the navigation of the open location drawn over the scene (plan 2026-11-25-client-ausfuehrung-e2, Task 7). One
/// <see cref="ArrayMesh"/> with three surfaces, every vertex <see cref="Lift"/> above its source:
///   0 the storeys — every polygon of every storey region mesh as a triangle fan (corners − 2 triangles), #3a7bd5, alpha 0.35;
///   1 the thresholds — the same fans of each threshold part (neck and two funnels), #3ad57b while the region is on, #d53a3a while a lock has it off
///     (<see cref="LocationNav.ThresholdEnabled"/>: the state last written, so a lock shows in the frame it is set);
///   2 the links — one line from start to end per stair flight / lift hop, #e0c040.
/// Vertices are world metres (the regions carry no transform), so the node sits at the origin of the locations root.
/// An empty part leaves its surface out. Check O1 of <c>--check nav</c>; hand derivation in native/fixtures/README.md,
/// section "Nav world".
/// </summary>
public sealed partial class NavOverlay : MeshInstance3D
{
    public const float Lift = 0.03f;
    public static readonly Color StoreyColor = new("#3a7bd5", 0.35f);
    public static readonly Color OpenColor = new("#3ad57b", 0.5f);
    public static readonly Color LockedColor = new("#d53a3a", 0.5f);
    public static readonly Color LinkColor = new("#e0c040", 1f);

    public NavOverlay()
    {
        Name = "NavOverlay";
        CastShadow = ShadowCastingSetting.Off;
        MaterialOverride = new StandardMaterial3D
        {
            ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
            Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
            NoDepthTest = false,
            VertexColorUseAsAlbedo = true,
            CullMode = BaseMaterial3D.CullModeEnum.Disabled,   // the fans' winding follows the baker's polygons
        };
    }

    /// <summary>Draws <paramref name="nav"/>; null (no open location or no navigation) clears the mesh.</summary>
    public void Rebuild(LocationNav? nav)
    {
        if (nav is null)
        {
            Mesh = null;
            return;
        }
        var mesh = new ArrayMesh();

        var storeyV = new List<Vector3>();
        var storeyC = new List<Color>();
        foreach (var m in nav.StoreyMeshes) Fans(m, StoreyColor, storeyV, storeyC);
        Add(mesh, Mesh.PrimitiveType.Triangles, storeyV, storeyC, "storeys");

        var doorV = new List<Vector3>();
        var doorC = new List<Color>();
        foreach (var t in nav.Source.Thresholds.OrderBy(t => t.Doorway))
        {
            var color = nav.ThresholdEnabled(t.Doorway) ? OpenColor : LockedColor;
            foreach (var q in t.Parts)
                for (int k = 1; k + 1 < q.Length; k++)
                    foreach (var p in new[] { q[0], q[k], q[k + 1] })
                    {
                        doorV.Add(new Vector3((float)p.X, (float)t.Y + Lift, (float)p.Z));
                        doorC.Add(color);
                    }
        }
        Add(mesh, Mesh.PrimitiveType.Triangles, doorV, doorC, "thresholds");

        var linkV = new List<Vector3>();
        var linkC = new List<Color>();
        foreach (var l in nav.Source.Links)
        {
            linkV.Add(Up(l.Start));
            linkV.Add(Up(l.End));
            linkC.Add(LinkColor);
            linkC.Add(LinkColor);
        }
        Add(mesh, Mesh.PrimitiveType.Lines, linkV, linkC, "links");

        Mesh = mesh.GetSurfaceCount() > 0 ? mesh : null;
    }

    private static void Fans(NavigationMesh m, Color color, List<Vector3> verts, List<Color> colors)
    {
        var v = m.GetVertices();
        for (int i = 0; i < m.GetPolygonCount(); i++)
        {
            var poly = m.GetPolygon(i);
            for (int k = 1; k + 1 < poly.Length; k++)
                foreach (int idx in new[] { poly[0], poly[k], poly[k + 1] })
                {
                    verts.Add(v[idx] + new Vector3(0, Lift, 0));
                    colors.Add(color);
                }
        }
    }

    private static void Add(ArrayMesh mesh, Mesh.PrimitiveType kind, List<Vector3> verts, List<Color> colors, string name)
    {
        if (verts.Count == 0) return;
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = verts.ToArray();
        arrays[(int)Mesh.ArrayType.Color] = colors.ToArray();
        mesh.AddSurfaceFromArrays(kind, arrays);
        mesh.SurfaceSetName(mesh.GetSurfaceCount() - 1, name);
    }

    private static Vector3 Up(Vec3 p) => new((float)p.X, (float)p.Y + Lift, (float)p.Z);
}
