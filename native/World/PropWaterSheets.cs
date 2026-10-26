using System;
using System.Collections.Generic;
using System.Globalization;
using AnimaNative.Ground;
using AnimaNative.Water;
using AnimaNative.World;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// Water surfaces inside props and dioramas (scene payload v18, <c>packages/scene-render/src/propWater.ts</c>
/// <c>buildPropWater</c>, client3d 7d5ff11e): one flat transparent sheet per region, in the frame of the node the
/// placement hangs in (a scene placement: its parent, tile-local metres; a world prop: the world), standing at
/// <c>region.y + lift</c> — the placement's § A16.9 lift, or the ground under a world prop's anchor — and moved with every
/// re-lift. The look is the shared surface water of <c>surfaceMaterial({ class: 'water', tint })</c>: still water (a
/// sheet carries no flow), two counter-scrolling sheets of THE wave normal map (<see cref="GroundSurfaces.WaveTexture"/>),
/// the detail fade, roughness 0.08 / metalness 0.15, the fresnel share of the hour's sky, the region's opacity, no depth
/// write. Materials are cached per tint|opacity (module-owned like the browser's); the meshes belong to the placement.
/// </summary>
public static class PropWaterSheets
{
    /// <summary>Meta on every sheet (the ghost and the passes that walk a placement leave it alone).</summary>
    public const string Meta = "prop_water";

    private static readonly Dictionary<string, ShaderMaterial> Cache = new(StringComparer.Ordinal);
    private static Shader? _shader;
    private static Vector3 _sky = new((float)WaterShade.Sky.R, (float)WaterShade.Sky.G, (float)WaterShade.Sky.B);

    /// <summary>Sheets made so far (the check and the log).</summary>
    public static int Built { get; private set; }

    /// <summary><c>surfaceSkyUniform</c>: the hour's sky every sheet reflects (the stage writes it with the terrain's).</summary>
    public static void SetSky(Vector3 sky)
    {
        if (sky == _sky) return;
        _sky = sky;
        foreach (var m in Cache.Values) m.SetShaderParameter("pw_sky", sky);
    }

    /// <summary>
    /// The sheets of a spec's regions under <paramref name="parent"/> at <c>y + lift</c> (empty when the spec has none or
    /// no region triangulates).
    /// </summary>
    public static List<MeshInstance3D> Build(IReadOnlyList<SceneWaterRegion> regions, Node3D parent, double lift)
    {
        var list = new List<MeshInstance3D>();
        foreach (var region in regions)
        {
            var data = PropWater.Sheet(region);
            var mi = new MeshInstance3D
            {
                Name = "PropWater",
                Mesh = MeshOf(data),
                MaterialOverride = MaterialFor(region.Tint, region.Opacity),
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                Position = new Vector3(0, (float)(region.Y + lift), 0),
            };
            mi.SetMeta(Meta, true);
            parent.AddChild(mi);
            list.Add(mi);
            Built++;
        }
        return list;
    }

    /// <summary>A re-lift: every sheet back to <c>region.y + lift</c> (the order of <see cref="Build"/>).</summary>
    public static void Relift(IReadOnlyList<MeshInstance3D> sheets, IReadOnlyList<SceneWaterRegion> regions, double lift)
    {
        for (int i = 0; i < sheets.Count && i < regions.Count; i++)
            if (GodotObject.IsInstanceValid(sheets[i]))
                sheets[i].Position = new Vector3(0, (float)(regions[i].Y + lift), 0);
    }

    public static void Drop(IEnumerable<MeshInstance3D>? sheets)
    {
        if (sheets is null) return;
        foreach (var m in sheets)
            if (GodotObject.IsInstanceValid(m)) { m.GetParent()?.RemoveChild(m); m.QueueFree(); }
    }

    /// <summary>The Core sheet as a Godot mesh: three's counter-clockwise triples emitted reversed (Godot's front faces wind
    /// clockwise), normal +y.</summary>
    public static ArrayMesh MeshOf(Scene.MeshData m)
    {
        var mesh = new ArrayMesh();
        if (m.Indices.Count < 3) return mesh;
        var pos = new Vector3[m.Positions.Count];
        var nrm = new Vector3[m.Positions.Count];
        for (int i = 0; i < pos.Length; i++)
        {
            var p = m.Positions[i];
            pos[i] = new Vector3((float)p.X, (float)p.Y, (float)p.Z);
            nrm[i] = Vector3.Up;
        }
        var idx = new int[m.Indices.Count];
        for (int i = 0; i + 2 < idx.Length; i += 3)
        {
            idx[i] = m.Indices[i];
            idx[i + 1] = m.Indices[i + 2];
            idx[i + 2] = m.Indices[i + 1];
        }
        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = pos;
        arrays[(int)Mesh.ArrayType.Normal] = nrm;
        arrays[(int)Mesh.ArrayType.Index] = idx;
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        return mesh;
    }

    /// <summary>The cached material of a tint|opacity pair (the browser's key).</summary>
    public static ShaderMaterial MaterialFor(string tint, double opacity)
    {
        var key = $"{tint}|{opacity.ToString("R", CultureInfo.InvariantCulture)}";
        if (Cache.TryGetValue(key, out var m)) return m;
        m = new ShaderMaterial { Shader = Shader() };
        var a = PropWater.Albedo(tint);
        m.SetShaderParameter("pw_albedo", new Vector3((float)a.R, (float)a.G, (float)a.B));
        m.SetShaderParameter("pw_opacity", (float)opacity);
        m.SetShaderParameter("pw_wave", GroundSurfaces.WaveTexture);
        m.SetShaderParameter("pw_sky", _sky);
        return Cache[key] = m;
    }

    public static Shader Shader()
    {
        if (_shader is not null) return _shader;
        _shader = new Shader { Code = Code() };
        ShaderSafety.Ok(_shader, "prop-water");
        return _shader;
    }

    private static string L(double v) => v.ToString("0.0###", CultureInfo.InvariantCulture);

    /// <summary>
    /// <c>applyWaterShader</c> on a still sheet (materials.ts), Godot spelling: the ripple's two sheets in WORLD metres per
    /// second (drift / λ), sign +1, cross 0.6 / 1.3, no squeeze, the third sheet weightless; the tangent frame of
    /// <c>ShapeGeometry</c> (u along the parent's +x, v along its −z — the shape is (x, −z)); the fresnel share of sky on the
    /// finished light, here <c>ALBEDO·(1 − k) + EMISSION = sky·k</c> like the terrain's water. The map is three's
    /// <c>CanvasTexture</c> (flipY): its (u, v) is Godot's (u, −v) on the periodic map.
    /// </summary>
    public static string Code() => $@"shader_type spatial;
render_mode blend_mix, depth_draw_never, cull_back, diffuse_lambert, specular_schlick_ggx;

uniform vec3 pw_albedo = vec3(0.1, 0.25, 0.45);
uniform float pw_opacity = 1.0;
uniform sampler2D pw_wave : filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec3 pw_sky = vec3(0.62, 0.78, 0.91);
varying vec2 v_world;
varying vec3 v_t;
varying vec3 v_b;

void vertex() {{
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
	v_t = normalize((MODEL_MATRIX * vec4(1.0, 0.0, 0.0, 0.0)).xyz);
	v_b = normalize((MODEL_MATRIX * vec4(0.0, 0.0, -1.0, 0.0)).xyz);
}}

vec3 pw_n(vec2 uv) {{
	return texture(pw_wave, vec2(uv.x, -uv.y)).xyz * 2.0 - 1.0;
}}

void fragment() {{
	float wave = {L(PropWater.WaveM)};
	float px = max(length(dFdx(v_world)), length(dFdy(v_world)));
	float detail = clamp(1.0 - px / wave, 0.0, 1.0);
	float t = mod(TIME, 3600.0);
	float drift_a = t * {L(PropWater.Speed)} / wave;
	float drift_b = t * {L(PropWater.Speed)} / (wave * 0.63);
	vec2 dir_a = vec2(1.0, 0.6);
	vec2 dir_b = -vec2(0.8, 1.3);
	vec3 n = normalize(pw_n(v_world / wave + dir_a * drift_a) + pw_n(v_world / (wave * 0.63) + dir_b * drift_b));
	n = mix(vec3(0.0, 0.0, 1.0), n, detail);
	vec3 nw = normalize(v_t * n.x + v_b * n.y + vec3(0.0, 1.0, 0.0) * n.z);
	NORMAL = normalize((VIEW_MATRIX * vec4(nw, 0.0)).xyz);
	float fres = pow(1.0 - clamp(dot(VIEW, NORMAL), 0.0, 1.0), 3.0);
	float k = clamp(fres * {L(PropWater.SkyMix)}, 0.0, 1.0);
	ALBEDO = pw_albedo * (1.0 - k);
	EMISSION = pw_sky * k;
	ROUGHNESS = {L(PropWater.Roughness)};
	METALLIC = {L(PropWater.Metalness)};
	ALPHA = pw_opacity;
}}
";
}
