using System;
using System.Collections.Generic;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// Task 43 / E6-T3: npcs.ts LineDashedMaterial drawn as a one-pixel line strip. UV.x holds computeLineDistances'
/// cumulative three-dimensional metres, including the sampled relief; the fragment shader cuts .9 m dashes and
/// .6 m gaps. Every line shares ONE material (one shader, compiled once — a shader per node compiled on every
/// bucket roll); each node owns only its mesh, released when the line leaves the tree.
/// Points are manager-local world-map coordinates, so a figure's root translation and yaw never transform them.
/// </summary>
public partial class TravelLine : MeshInstance3D
{
    private ArrayMesh? _geometry;
    private static ShaderMaterial? _shared;

    private static ShaderMaterial Material()
    {
        if (_shared is not null) return _shared;
        var shader = new Shader { Code = """
            shader_type spatial;
            render_mode unshaded, cull_disabled, depth_draw_always, shadows_disabled;
            uniform vec4 line_color : source_color;
            uniform float dash_size;
            uniform float gap_size;
            void fragment() {
                if (mod(UV.x, dash_size + gap_size) > dash_size) { discard; }
                ALBEDO = line_color.rgb;
                ALPHA = line_color.a;
            }
            """ };
        _shared = new ShaderMaterial { Shader = shader };
        _shared.SetShaderParameter("line_color", new Color(242f / 255, 205f / 255, 110f / 255, .9f));
        _shared.SetShaderParameter("dash_size", .9f);
        _shared.SetShaderParameter("gap_size", .6f);
        return _shared;
    }

    public TravelLine(IReadOnlyList<(double X, double Z)> points, Func<double, double, double> groundY)
    {
        Name = "TravelLine";
        CastShadow = ShadowCastingSetting.Off;
        var vertices = new Vector3[points.Count];
        var uv = new Vector2[points.Count];
        double distance = 0;
        for (int i = 0; i < points.Count; i++)
        {
            var p = points[i];
            vertices[i] = new Vector3((float)p.X, (float)(groundY(p.X, p.Z) + .3), (float)p.Z);
            if (i > 0) distance += vertices[i - 1].DistanceTo(vertices[i]);
            uv[i] = new Vector2((float)distance, 0);
        }
        using var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = vertices;
        arrays[(int)Mesh.ArrayType.TexUV] = uv;
        _geometry = new ArrayMesh();
        _geometry.AddSurfaceFromArrays(Mesh.PrimitiveType.LineStrip, arrays);
        Mesh = _geometry;
        MaterialOverride = Material();
    }

    /// <summary>Task 43: detach renderer references, then release the owned mesh (the shared material stays).</summary>
    public override void _ExitTree()
    {
        Mesh = null;
        MaterialOverride = null;
        _geometry?.Dispose(); _geometry = null;
    }
}

public partial class FigureManager
{
    /// <summary>
    /// Task 43: browser updateTravelLine. The server's route knowledge is the visibility gate: the avatar's route
    /// survives fog, show-all reveals every route, and withheld strangers have none. Clamp once for bucket AND trim;
    /// cache empty terminal tails too. Rebuild only for route identity, five-metre bucket or WorldHeight.Revision.
    /// </summary>
    private void UpdateTravelLine(Figure fig)
    {
        var route = fig.Route;
        double walked = route is null ? 0 : TravelPath.ClampProgress(route.ShownM, route.TotalM);
        string key = route is null ? "" : $"{route.Key}#{TravelPath.TrimBucket(walked)}#{_height.Revision}";
        if (key == fig.TravelKey) return;
        fig.DropTravelLine();
        fig.TravelKey = key;
        var ahead = route is null ? new List<(double X, double Z)>() : TravelPath.RemainingPoints(route.Points, walked);
        if (ahead.Count < 2) return;
        var line = new TravelLine(TravelPath.DensifyPolyline(ahead), GroundY);
        fig.TravelLine = line;
        fig.TravelLineBuilds++;
        AddChild(line);
    }
}
