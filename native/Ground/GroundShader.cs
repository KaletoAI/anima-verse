using System.Globalization;
using Godot;

namespace AnimaNative.Ground;

/// <summary>
/// The ground material of the browser's open world as ONE Godot spatial shader — the chain
/// <c>scene/ground.ts</c> <c>rebuildBase</c> builds on the CDLOD terrain, minus what the spike does not draw:
///
///   1. <c>lcCompose</c> (<c>packages/scene-render/src/layerCut.ts</c> <c>terrainLayerGlsl</c>) — the layer cut:
///      the pair from the id mask (near window, else the coarse overview, else bare ground), the distance
///      rebuilt from the four sd texels of the own id texel (<c>lcSdAt</c>), the edge-noise push, the cut
///      (<c>lcWeight</c>: smoothstep of layer A's width, or the pixel-wide step at width 0), two
///      <c>textureGrad</c> samples per layer out of ONE texture array (the narrow one and the broad anti-tile
///      one), mixed by noise; albedo = that × the material colour (white).
///   2. <c>applyNaturalGround</c> (<c>scene/naturalGround.ts</c>) stages (2) colour patches and (3) height AO
///      on the composited albedo, then the clamp. Stage (1) is <c>USE_MAP</c>-guarded and the terrain has no map.
///   3. the shading normal of <c>patchTerrainLod</c> (<c>tlodNormalAt</c>, see <see cref="TerrainNormal"/>).
///   4. three's <c>MeshStandardMaterial</c> lighting with <c>surfaceMaterial</c>'s matte defaults:
///      roughness 0.85, metalness 0.02, Lambert diffuse + GGX specular (Godot <c>diffuse_lambert</c>).
///
/// Not ported (both are per-fragment work the browser does and Godot does not — favours Godot): the fog
/// veil (<c>applyFogVeil</c>, the fog-of-war haze) and the basement hole discard (<c>patchHole</c>); the
/// water branch of the terrain (bench runs use <c>&amp;water=0</c>).
///
/// Differences that are cost-neutral: the id masks are RG8 UNORM textures read with <c>texelFetch</c> and
/// decoded <c>round(v·255)</c> (Godot's <see cref="Image"/> has no RG8UI format; the browser reads RG8UI
/// through a <c>usampler2D</c> — one fetch either way, exact bytes either way).
/// The literals come out of <see cref="NaturalGround"/> / <see cref="LayerCut"/>, like the browser prints
/// its shader out of the TS constants.
/// </summary>
public static class GroundShader
{
    private static Shader? _shader;

    public static Shader Get() => _shader ??= new Shader { Code = Code() };

    /// <summary>A GLSL literal with two decimals — and, like the browser's <c>ngLit</c>, refused when the number does
    /// not survive them (the shader would spend a different number than the maths).</summary>
    public static string L(double v)
    {
        var s = v.ToString("0.00", CultureInfo.InvariantCulture);
        if (double.Parse(s, CultureInfo.InvariantCulture) != v)
            throw new System.InvalidOperationException($"ground shader: {v} does not survive two decimals as \"{s}\"");
        return s;
    }

    public static string Code()
    {
        var taps = NaturalGround.AoTaps();
        var tapReads = string.Join("\n\t\t\t+ ", System.Array.ConvertAll(taps,
            t => $"ng_height_at(p + vec2({L(t.Dx)}, {L(t.Dz)}))"));
        return $@"shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_lambert, specular_schlick_ggx;

// ---- layer cut (layerCut.ts terrainLayerGlsl) ----
uniform sampler2DArray lc_surf : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D lc_near_id : filter_nearest, repeat_disable;
uniform sampler2D lc_near_sd : filter_nearest, repeat_disable;
uniform sampler2D lc_far_id : filter_nearest, repeat_disable;
uniform vec4 lc_near = vec4(0.0, 0.0, 1.0, 0.0);          // originX, originZ, idStep, idSize (0 = no window)
uniform vec4 lc_near_sd_geom = vec4(0.0, 0.0, 1.0, 1.0);  // originX, originZ, sdStep, sdSize
uniform vec4 lc_far = vec4(0.0, 0.0, 1.0, 0.0);           // originX, originZ, step, 0
uniform vec2 lc_far_size = vec2(0.0);                     // cols, rows
uniform vec2 lc_sd_code = vec2(128.0, 1.0);               // zero, codes per metre
uniform float lc_band_m = 8.0;
uniform vec4 lc_layer[{LayerCut.MaxLayers}];              // edge_blend_m, metres per texture tile, 0, 0

// ---- natural ground (naturalGround.ts) ----
uniform sampler2D ng_height : filter_linear, repeat_disable;
uniform vec4 ng_field = vec4(0.0, 0.0, 1.0, 0.0);
uniform vec2 ng_field_size = vec2(1.0);
uniform float ng_strength = 0.0;

// ---- shading normal (terrainLod.ts tlodNormalAt on level 0) ----
uniform sampler2D tl_near : filter_nearest, repeat_disable;
uniform sampler2D tl_far : filter_nearest, repeat_disable;
uniform vec4 tl_near_geom = vec4(0.0);    // originX, originZ, step, present (> 0)
uniform vec4 tl_near_level = vec4(0.0);   // cols, rows, step, 0
uniform vec4 tl_near_rect = vec4(0.0);    // x0, z0, x1, z1
uniform vec4 tl_far_geom = vec4(0.0);
uniform vec4 tl_far_level = vec4(0.0);
uniform float tl_normal_span = 2.0;

uniform float ground_roughness = 0.85;
uniform float ground_metallic = 0.02;

varying vec2 v_world;

void vertex() {{
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
}}

float lc_hash(vec2 p) {{
	return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}}
float lc_noise(vec2 p) {{
	vec2 i = floor(p);
	vec2 f = fract(p);
	vec2 w = f * f * (3.0 - 2.0 * f);
	return mix(mix(lc_hash(i), lc_hash(i + vec2(1.0, 0.0)), w.x),
	           mix(lc_hash(i + vec2(0.0, 1.0)), lc_hash(i + vec2(1.0, 1.0)), w.x), w.y);
}}

float lc_sd_texel(ivec2 t) {{
	int last = int(lc_near_sd_geom.w) - 1;
	return (texelFetch(lc_near_sd, clamp(t, ivec2(0), ivec2(last)), 0).r * 255.0 - lc_sd_code.x) / lc_sd_code.y;
}}

float lc_sd_at(vec2 p, vec2 id_idx) {{
	float ratio = max(floor(lc_near.z / lc_near_sd_geom.z + 0.5), 1.0);
	vec2 t0 = id_idx * ratio;
	vec2 t1 = t0 + (ratio - 1.0);
	vec2 c0 = lc_near_sd_geom.xy + (t0 + 0.5) * lc_near_sd_geom.z;
	float span_m = (ratio - 1.0) * lc_near_sd_geom.z;
	vec2 f = span_m > 0.0 ? (p - c0) / span_m : vec2(0.0);
	float s00 = lc_sd_texel(ivec2(t0));
	float s10 = lc_sd_texel(ivec2(int(t1.x), int(t0.y)));
	float s01 = lc_sd_texel(ivec2(int(t0.x), int(t1.y)));
	float s11 = lc_sd_texel(ivec2(t1));
	return mix(mix(s00, s10, f.x), mix(s01, s11, f.x), f.y);
}}

float lc_weight(float sd, float blend_m, float pixel_m) {{
	float b = max(blend_m, 1e-4);
	float soft = smoothstep(-0.5 * b, 0.5 * b, sd);
	float hard = clamp(sd / max(pixel_m, 1e-6) + 0.5, 0.0, 1.0);
	return blend_m > 0.0 ? soft : hard;
}}

vec3 lc_surface(int layer, vec2 p, vec2 dpdx, vec2 dpdy, float wide) {{
	float size_m = max(lc_layer[layer].y, 0.01);
	vec2 gx = dpdx / size_m;
	vec2 gy = dpdy / size_m;
	vec3 narrow = textureGrad(lc_surf, vec3(p / size_m, float(layer)), gx, gy).rgb;
	vec3 broad = textureGrad(lc_surf,
		vec3(p / size_m * {L(NaturalGround.DetailScale)} + {L(NaturalGround.DetailOffset)}, float(layer)),
		gx * {L(NaturalGround.DetailScale)}, gy * {L(NaturalGround.DetailScale)}).rgb;
	return mix(narrow, broad, wide);
}}

vec3 lc_compose(vec2 p, vec2 dpdx, vec2 dpdy) {{
	ivec2 pair;
	float sd = lc_band_m;
	float near_n = lc_near.w;
	vec2 near_idx = (p - lc_near.xy) / lc_near.z;
	if (near_n > 0.5 && near_idx.x >= 0.0 && near_idx.y >= 0.0 && near_idx.x < near_n && near_idx.y < near_n) {{
		vec2 id_idx = floor(near_idx);
		pair = ivec2(round(texelFetch(lc_near_id, ivec2(id_idx), 0).rg * 255.0));
		sd = lc_sd_at(p, id_idx);
	}} else if (lc_far_size.x > 1.5) {{
		vec2 far_idx = floor((p - lc_far.xy) / lc_far.z);
		far_idx = clamp(far_idx, vec2(0.0), lc_far_size - 1.0);
		pair = ivec2(round(texelFetch(lc_far_id, ivec2(far_idx), 0).rg * 255.0));
	}} else {{
		pair = ivec2(0);
	}}
	int a = pair.x;
	int b = pair.y;
	float blend_m = lc_layer[a].x;
	float cap = min({L(LayerCut.EdgeNoiseM)}, 0.5 * max(blend_m, 0.0));
	float sd_n = sd + (lc_noise(p / {L(LayerCut.EdgeWaveM)} + vec2(5.0, 23.0)) * 2.0 - 1.0) * cap;
	float pixel_m = max(length(dpdx), length(dpdy));
	float w = lc_weight(sd_n, blend_m, pixel_m);
	float wide = lc_noise(p / {L(NaturalGround.MixM)}) * {L(NaturalGround.MixMax)};
	return a == b
		? lc_surface(a, p, dpdx, dpdy, wide)
		: mix(lc_surface(b, p, dpdx, dpdy, wide), lc_surface(a, p, dpdx, dpdy, wide), w);
}}

vec2 ng_field_uv_of(vec2 p) {{
	return ((p - ng_field.xy) / ng_field.z + 0.5) / ng_field_size;
}}
float ng_height_at(vec2 p) {{
	return texture(ng_height, ng_field_uv_of(p)).r;
}}

float tl_grid(sampler2D tex, vec2 origin, vec4 lv, vec2 p) {{
	float cols = lv.x;
	float rows = lv.y;
	float stp = lv.z;
	if (cols < 2.0 || rows < 2.0 || stp <= 0.0) return 0.0;
	float fx = clamp((p.x - origin.x) / stp, 0.0, cols - 1.0);
	float fz = clamp((p.y - origin.y) / stp, 0.0, rows - 1.0);
	float fi = min(floor(fx), cols - 2.0);
	float fj = min(floor(fz), rows - 2.0);
	float tx = fx - fi;
	float tz = fz - fj;
	int i = int(fi);
	int j = int(fj);
	float h00 = texelFetch(tex, ivec2(i, j), 0).r;
	float h10 = texelFetch(tex, ivec2(i + 1, j), 0).r;
	float h01 = texelFetch(tex, ivec2(i, j + 1), 0).r;
	float h11 = texelFetch(tex, ivec2(i + 1, j + 1), 0).r;
	float north = h00 * (1.0 - tx) + h10 * tx;
	float south = h01 * (1.0 - tx) + h11 * tx;
	return north * (1.0 - tz) + south * tz;
}}
float tl_height(vec2 p) {{
	if (tl_near_geom.w > 0.0 && p.x >= tl_near_rect.x && p.x <= tl_near_rect.z
	    && p.y >= tl_near_rect.y && p.y <= tl_near_rect.w) {{
		return tl_grid(tl_near, tl_near_geom.xy, tl_near_level, p);
	}}
	return tl_grid(tl_far, tl_far_geom.xy, tl_far_level, p);
}}
vec3 tl_normal_at(vec2 p) {{
	float s = max(tl_normal_span, 1e-3);
	float hx = tl_height(vec2(p.x + s, p.y)) - tl_height(vec2(p.x - s, p.y));
	float hz = tl_height(vec2(p.x, p.y + s)) - tl_height(vec2(p.x, p.y - s));
	return normalize(vec3(-hx, 2.0 * s, -hz));
}}

void fragment() {{
	vec2 p = v_world;
	// The two derivatives, ONCE and at uniform control flow (layerCut.ts lcCompose).
	vec2 dpdx = dFdx(p);
	vec2 dpdy = dFdy(p);
	vec3 alb = lc_compose(p, dpdx, dpdy) * vec3(1.0);
	// (2) colour patches — brightness, then saturation through the own luminance; hue untouched.
	float ng_tint = lc_noise(p / {L(NaturalGround.TintM)}) * 2.0 - 1.0;
	float ng_sat = lc_noise(p / {L(NaturalGround.TintM)} + vec2(37.0, 11.0)) * 2.0 - 1.0;
	alb *= 1.0 + {L(NaturalGround.TintAmp)} * ng_tint;
	float ng_lum = dot(alb, vec3(0.2126, 0.7152, 0.0722));
	alb = mix(vec3(ng_lum), alb, 1.0 + {L(NaturalGround.TintAmp)} * ng_sat);
	// (3) height AO — the ring of four taps against the own height of the overview field.
	if (ng_strength > 0.0) {{
		float ng_own = ng_height_at(p);
		float ng_around = (1.0 / {taps.Length}.0) * (
			{tapReads});
		float ng_t = clamp((ng_around - ng_own) / {L(NaturalGround.AoSpanM)}, -1.0, 1.0);
		float ng_shade = ng_t > 0.0 ? -{L(NaturalGround.AoDown)} * ng_t : -{L(NaturalGround.AoUp)} * ng_t;
		vec2 ng_uv = ng_field_uv_of(p);
		float ng_in = step(0.0, ng_uv.x) * step(ng_uv.x, 1.0) * step(0.0, ng_uv.y) * step(ng_uv.y, 1.0);
		alb *= 1.0 + ng_shade * ng_strength * ng_in;
	}}
	ALBEDO = clamp(alb, 0.0, 1.0);
	ROUGHNESS = ground_roughness;
	METALLIC = ground_metallic;
	NORMAL = normalize((VIEW_MATRIX * vec4(tl_normal_at(p), 0.0)).xyz);
}}
";
    }
}
