using System;
using System.Collections.Generic;
using System.Globalization;
using AnimaNative.Ground;
using AnimaNative.Scatter;
using AnimaNative.Water;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// THE WATERFALLS (W5, <c>client3d/src/scene/waterfall.ts</c> <c>buildWaterfall</c>, built in ground.ts
/// <c>rebuildAreas</c> per terrain payload): where a painted water's own flow axis drops faster than water runs
/// (<see cref="Waterfalls.From"/>, vector-checked), a curtain quad (<see cref="Waterfalls.Quad"/>) hangs from the lip to
/// the leaning foot and a foam disc lies at the foot. Two draws per fall, no per-frame CPU: the scroll rides Godot's
/// <c>TIME</c> (the browser's <c>surfaceTimeUniform</c>, both wrap at 3600 s) and the map is THE wave normal map
/// (<see cref="GroundSurfaces.WaveTexture"/>). Only an area whose ring encloses something (<c>buildAreaGeometry</c> ≠
/// null) is asked; falls live as long as the terrain payload they came from (<see cref="Rebuild"/> replaces them).
/// </summary>
public partial class WaterfallLayer : Node3D
{
    private static Shader? _curtain, _foam;

    /// <summary>The falls drawn now, in payload order (area order, then axis order).</summary>
    public List<Waterfall> Falls { get; } = new();
    /// <summary>The curtain and foam meshes, two per fall, in the same order.</summary>
    public List<MeshInstance3D> Meshes { get; } = new();

    public WaterfallLayer() { Name = "Waterfalls"; }

    /// <summary>Every fall of the payload's areas (<c>rebuildAreas</c>): the old ones go, the new ones are built.</summary>
    public int Rebuild(TerrainPayload terrain)
    {
        foreach (var m in Meshes)
            if (IsInstanceValid(m)) { RemoveChild(m); m.QueueFree(); }
        Meshes.Clear();
        Falls.Clear();
        foreach (var area in terrain.Areas)
        {
            if (area.Falls.Count == 0 || ScatterMath.AreaRing(area.Polygon) is null) continue;
            foreach (var fall in area.Falls) Add(fall);
        }
        return Falls.Count;
    }

    private void Add(Waterfall fall)
    {
        if (Waterfalls.Quad(fall) is not { } q || Waterfalls.FoamDisc(fall) is not { } disc) return;
        Falls.Add(fall);
        var (speed, tilesX, tilesY) = Waterfalls.Curtain(fall);
        var curtainMat = new ShaderMaterial { Shader = CurtainShader() };
        curtainMat.SetShaderParameter("wf_map", GroundSurfaces.WaveTexture);
        curtainMat.SetShaderParameter("wf_speed", (float)speed);
        curtainMat.SetShaderParameter("wf_tiles", new Vector2((float)tilesX, (float)tilesY));
        var curtain = new MeshInstance3D
        {
            Name = "Curtain",
            Mesh = CurtainMesh(q),
            MaterialOverride = curtainMat,
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
        };
        var foam = new MeshInstance3D
        {
            Name = "Foam",
            Mesh = FoamMesh(disc.Vertices, disc.Index),
            MaterialOverride = new ShaderMaterial { Shader = FoamShader() },
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
        };
        AddChild(curtain);
        AddChild(foam);
        Meshes.Add(curtain);
        Meshes.Add(foam);
    }

    /// <summary>The four corners in world metres (mesh at the origin), three's uvs, the two triangles (drawn double-sided).</summary>
    public static ArrayMesh CurtainMesh(WaterfallQuad q)
    {
        var pos = new Vector3[4];
        var uv = new Vector2[4];
        for (int i = 0; i < 4; i++)
        {
            pos[i] = new Vector3((float)q.Positions[3 * i], (float)q.Positions[3 * i + 1], (float)q.Positions[3 * i + 2]);
            uv[i] = new Vector2((float)Waterfalls.CurtainUv[2 * i], (float)Waterfalls.CurtainUv[2 * i + 1]);
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = pos;
        arrays[(int)Mesh.ArrayType.TexUV] = uv;
        arrays[(int)Mesh.ArrayType.Index] = (int[])Waterfalls.CurtainIndex.Clone();
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return mesh;
    }

    /// <summary>The disc: alpha in the vertex colours (centre 0.6, rim 0), three's counter-clockwise triples emitted
    /// reversed (Godot's front faces wind clockwise; the disc is seen from above only, like the browser's FrontSide).</summary>
    public static ArrayMesh FoamMesh(double[] v, int[] index)
    {
        int n = v.Length / 4;
        var pos = new Vector3[n];
        var col = new Color[n];
        for (int i = 0; i < n; i++)
        {
            pos[i] = new Vector3((float)v[4 * i], (float)v[4 * i + 1], (float)v[4 * i + 2]);
            col[i] = new Color(1, 1, 1, (float)v[4 * i + 3]);
        }
        var idx = new int[index.Length];
        for (int i = 0; i + 2 < idx.Length; i += 3)
        {
            idx[i] = index[i];
            idx[i + 1] = index[i + 2];
            idx[i + 2] = index[i + 1];
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = pos;
        arrays[(int)Mesh.ArrayType.Color] = col;
        arrays[(int)Mesh.ArrayType.Index] = idx;
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return mesh;
    }

    private static string L(double v) => v.ToString("0.0###", CultureInfo.InvariantCulture);

    public static Shader CurtainShader()
    {
        if (_curtain is not null) return _curtain;
        _curtain = new Shader { Code = CurtainCode() };
        ShaderSafety.Ok(_curtain, "waterfall-curtain");
        return _curtain;
    }

    public static Shader FoamShader()
    {
        if (_foam is not null) return _foam;
        _foam = new Shader { Code = FoamCode() };
        ShaderSafety.Ok(_foam, "waterfall-foam");
        return _foam;
    }

    /// <summary>
    /// <c>patchCurtain</c> on a <c>MeshBasicMaterial</c> (tint #c2dcea, opacity 0.8, double-sided, no depth write): two
    /// scrolling samples of the wave map, the break where the slopes are steep, whiter as the water falls, the edge fade.
    /// The map is three's <c>CanvasTexture</c> (flipY): its sample coordinate s is Godot's (s.x, −s.y) on the periodic map.
    /// </summary>
    public static string CurtainCode()
    {
        var tint = WaterShade.TintRgb(Waterfalls.Tint);
        return $@"shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, shadows_disabled;

uniform sampler2D wf_map : filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec3 wf_tint : source_color = vec3({L(tint.R)}, {L(tint.G)}, {L(tint.B)});
uniform float wf_speed = 1.0;
uniform vec2 wf_tiles = vec2(1.0);

vec2 wf_xy(vec2 s) {{
	return texture(wf_map, vec2(s.x, -s.y)).xy * 2.0 - 1.0;
}}

void fragment() {{
	vec2 uv = UV * wf_tiles;
	float t = mod(TIME, 3600.0) * wf_speed;
	vec2 a = wf_xy(uv + vec2(0.0, t));
	vec2 b = wf_xy(uv * 0.5 + vec2(0.17, t * 0.6));
	float brk = clamp((abs(a.x + b.x) + abs(a.y + b.y)) * 1.6, 0.0, 1.0);
	float down = 1.0 - UV.y;
	float white = clamp({L(Waterfalls.WhiteTop)} + (1.0 - {L(Waterfalls.WhiteTop)}) * down * 0.7 + brk * 0.4, 0.0, 1.0);
	ALBEDO = mix(wf_tint, vec3(1.0), white);
	float edge = smoothstep(0.0, 0.12, UV.x) * smoothstep(0.0, 0.12, 1.0 - UV.x) * (1.0 - smoothstep(0.94, 1.0, UV.y));
	ALPHA = {L(Waterfalls.Opacity)} * edge * (0.6 + 0.4 * brk);
}}
";
    }

    /// <summary>The foam disc: white, its alpha the vertex colour's (<c>vertexColors</c>), no depth write, front side.</summary>
    public static string FoamCode() => @"shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_back, shadows_disabled;

uniform vec3 foam_color : source_color = vec3(1.0);

void fragment() {
	ALBEDO = foam_color * COLOR.rgb;
	ALPHA = COLOR.a;
}
";
}
