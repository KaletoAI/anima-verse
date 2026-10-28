using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// The HUD performance readout, Godot side (client3d main.ts "Performance readout"): what the native client can
/// measure for <see cref="PerfReadout"/>, with main.ts' cadences — the frame rate and the worst frame every frame,
/// the vertex walk on the 1 s beat, the readout every 300 ms — and nothing at all while the HUD's <c>perfOn</c> is off.
///
/// Sources:
///   • fps / worst frame — <see cref="FpsMeter"/> on the frame's delta, <see cref="WorstFrame"/> on the raw
///     monotonic clock (µs → ms);
///   • triangles / draw calls — Godot's <c>render/total_primitives_in_frame</c> and
///     <c>render/total_draw_calls_in_frame</c> (all viewports and passes, shadows included, as three's
///     <c>renderer.info.render</c> counts its shadow passes too), the same monitors the bench reads;
///   • vertices — <see cref="VisibleVertices"/>, the walk of perfstats.ts <c>visibleVertices</c>: per VISIBLE node
///     (an invisible node drops its subtree) the vertex count of its mesh, once per node (a MultiMesh counts its
///     mesh once, like three's <c>InstancedMesh</c>).
/// Not known natively, sent as 0: <c>geometries</c>/<c>textures</c> (Godot reports bytes, not counts), the model tier
/// split. Task 40 measures scatter costs; Task 42 reads sync counters from the world's figure manager.
/// </summary>
public sealed class PerfProbe
{
    private FpsMeter _fps = new();
    private WorstFrame _worst = new();
    private bool _measuring;
    private double _sinceHeavyMs = double.PositiveInfinity, _sincePublishMs;
    private long _vertices;
    private ScatterCost _mesh, _impostor;

    /// <summary>
    /// One frame. Returns the readout to publish (every <see cref="PerfReadout.PublishMs"/>) or null.
    /// <paramref name="root"/> is the world the vertex walk counts.
    /// </summary>
    public JsonObject? Frame(bool perfOn, double delta, Node? root)
    {
        if (!perfOn)
        {
            // Switched off: throw the window away once, so switching on starts measuring now.
            if (_measuring)
            {
                _fps = new FpsMeter();
                _worst = new WorstFrame();
                _measuring = false;
                _sinceHeavyMs = double.PositiveInfinity;
            }
            return null;
        }
        _measuring = true;
        _fps.Push(delta);
        _worst.Push(Time.GetTicksUsec() / 1000.0);
        _sinceHeavyMs += delta * 1000;
        _sincePublishMs += delta * 1000;
        if (_sinceHeavyMs >= PerfReadout.HeavyMs)
        {
            _sinceHeavyMs = 0;
            _vertices = root is not null && GodotObject.IsInstanceValid(root) ? VisibleVertices(root) : 0;
            (_mesh, _impostor) = root is not null && GodotObject.IsInstanceValid(root) ? ScatterSnapshot(root) : default;
        }
        if (_sincePublishMs < PerfReadout.PublishMs) return null;
        _sincePublishMs = 0;
        return PerfReadout.ToJson(new PerfSample(
            _fps.Fps, _worst.WorstFrameMs,
            (long)Performance.GetMonitor(Performance.Monitor.RenderTotalPrimitivesInFrame),
            (long)Performance.GetMonitor(Performance.Monitor.RenderTotalDrawCallsInFrame),
            _vertices, 0, 0, 0, 0, root is not null ? LodTime(root) : 0, _mesh, _impostor, root is not null ? SyncSnapshot(root) : default));
    }

    /// <summary>Task 42: the world's manager owns lifetime counters; reading includes hidden figures and expires errors.</summary>
    public static TravelCounters SyncSnapshot(Node root)
    {
        if (root is FigureManager manager) return manager.SyncCounters;
        TravelCounters total = default;
        foreach (var child in root.GetChildren())
        {
            var c = SyncSnapshot(child);
            total = new TravelCounters(total.TravBack + c.TravBack, total.TravFwd + c.TravFwd,
                System.Math.Max(total.TravErrMaxM, c.TravErrMaxM), total.Arrive + c.Arrive, total.Place + c.Place);
        }
        return total;
    }

    /// <summary>Task 40 D13: perfstats.ts scatterCosts over debugParts.scatter (authored scatter only); hidden ancestors
    /// suppress a stage, zero instances suppress a draw, indexed and nonindexed meshes use their actual geometry.</summary>
    public static (ScatterCost Mesh, ScatterCost Impostor) ScatterSnapshot(Node root)
    {
        ScatterCost mesh = default, impostor = default;
        void Walk(Node n, bool scatter)
        {
            if (n is Node3D { Visible: false }) return;
            if (n is UndergrowthField) return;
            scatter |= n is ScatterField;
            if (scatter && n is MultiMeshInstance3D { Multimesh: { Mesh: { } geometry } mm })
            {
                int count = mm.VisibleInstanceCount < 0 ? mm.InstanceCount : mm.VisibleInstanceCount;
                if (count > 0)
                {
                    long triangles = 0;
                    for (int i = 0; i < geometry.GetSurfaceCount(); i++)
                    {
                        var arrays = geometry.SurfaceGetArrays(i);
                        var indexArray = arrays[(int)Mesh.ArrayType.Index];
                        var indices = indexArray.VariantType == Variant.Type.Nil ? System.Array.Empty<int>() : indexArray.AsInt32Array();
                        triangles += (indices.Length > 0 ? indices.Length : arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array().Length) / 3;
                    }
                    bool billboard = n.Name.ToString().StartsWith("ScatterImpostor_", System.StringComparison.Ordinal);
                    var c = billboard ? impostor : mesh;
                    c = new ScatterCost(c.Calls + 1, c.Instances + count, c.Triangles + triangles * count);
                    if (billboard) impostor = c; else mesh = c;
                }
            }
            foreach (var child in n.GetChildren()) Walk(child, scatter);
        }
        Walk(root, false);
        return (mesh, impostor);
    }
    private static double LodTime(Node root)
    {
        if (root is ScatterLayer layer) return layer.LastLodMs;
        double ms = 0;
        foreach (var child in root.GetChildren()) ms += LodTime(child);
        return ms;
    }

    /// <summary><c>visibleVertices(root)</c>: vertices of every visible mesh node under <paramref name="node"/>, itself included.</summary>
    public static long VisibleVertices(Node node)
    {
        if (node is Node3D n3 && !n3.Visible) return 0;
        if (node is CanvasItem) return 0;
        long total = node switch
        {
            MeshInstance3D mi when mi.Mesh is { } mesh => MeshVertices(mesh),
            MultiMeshInstance3D mm when mm.Multimesh?.Mesh is { } mesh => MeshVertices(mesh),
            _ => 0,
        };
        foreach (var child in node.GetChildren()) total += VisibleVertices(child);
        return total;
    }

    /// <summary>Primitive meshes build their arrays on every request: counted once per mesh resource.</summary>
    private static readonly ConditionalWeakTable<Mesh, StrongBox<long>> PrimitiveCounts = new();

    private static long MeshVertices(Mesh mesh)
    {
        if (mesh is PrimitiveMesh && PrimitiveCounts.TryGetValue(mesh, out var known)) return known.Value;
        long sum = 0;
        for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            sum += mesh is ArrayMesh am ? am.SurfaceGetArrayLen(s) : mesh.SurfaceGetArrays(s)[(int)Mesh.ArrayType.Vertex].AsVector3Array().Length;
        if (mesh is PrimitiveMesh) PrimitiveCounts.AddOrUpdate(mesh, new StrongBox<long>(sum));
        return sum;
    }
}
