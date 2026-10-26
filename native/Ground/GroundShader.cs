using System.Globalization;
using AnimaNative.Sky;
using AnimaNative.Terrain;
using AnimaNative.Water;
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
///   0. the CDLOD vertex stage of <c>patchTerrainLod</c> (<see cref="TerrainLodGlsl"/>: one instanced 33 × 33 patch per
///      piece, <c>INSTANCE_CUSTOM</c> = (x, z, size, level), heights out of the R32F pyramids, the block-descent morph;
///      the water variant lifts each tap onto the mirror and hands its depth to the fragment as <c>v_wet</c>).
///   3. the shading normal of <c>patchTerrainLod</c> (<c>tlodNormalAt</c>, see <see cref="TerrainNormal"/>).
///   4. three's <c>MeshStandardMaterial</c> lighting with <c>surfaceMaterial</c>'s matte defaults:
///      roughness 0.85, metalness 0.02, Lambert diffuse + GGX specular (Godot <c>diffuse_lambert</c>).
///
/// 5. the basement hole (<c>patchHole</c>, Task 16): while <c>hole_on</c>, a fragment whose world xz lies strictly
///    inside <c>hole_rect</c> (minX, minZ, maxX, maxZ) is discarded — the open view looks down into a cellar.
///
/// 6. the exploration veil (<c>applyFogVeil</c>, <c>scene/fogVeil.ts</c>, Task 26) on every variant, plain included: the
///    explored-cells textures A/B (one R8 texel per 64 m cell, linear filter = the 32 m soft edge, clamp to the zero
///    ring), crossfaded by <c>fv_mix</c>; the haze takes <c>fv_alpha · (1 − explored)</c> of the FINISHED colour
///    (<c>mix(outgoingLight, uFogColor, a)</c> at three's <c>opaque_fragment</c>). Godot has no hook after the lighting,
///    so the mix goes in as <c>ALBEDO · (1 − a)</c> plus <c>EMISSION = colour · a</c> — exact for the diffuse and
///    ambient share, the matte specular is not scaled (the water variant's trade, see there). On the wet pieces the
///    browser's veil runs BEFORE the water's sky/foam mixes (its body is inserted first), so the haze sits under them.
///    <c>fv_alpha</c> = 0 reads no texture (the uniform branch of the browser).
///
/// Differences that are cost-neutral: the id masks are RG8 UNORM textures read with <c>texelFetch</c> and
/// decoded <c>round(v·255)</c> (Godot's <see cref="Image"/> has no RG8UI format; the browser reads RG8UI
/// through a <c>usampler2D</c> — one fetch either way, exact bytes either way).
/// The literals come out of <see cref="NaturalGround"/> / <see cref="LayerCut"/>, like the browser prints
/// its shader out of the TS constants.
/// </summary>
public static class GroundShader
{
    private static Shader? _shader, _waterShader, _plainShader;

    /// <summary>The dry ground, or (<paramref name="water"/>) the water variant every wet piece wears (Task S3c / 23).</summary>
    public static Shader Get(bool water = false)
        => water ? _waterShader ??= new Shader { Code = Code(true) } : _shader ??= new Shader { Code = Code() };

    /// <summary>The plain terrain (<c>--plain-ground</c>, or the ground surfaces failed): the CDLOD stage under one matte colour.</summary>
    public static Shader Plain() => _plainShader ??= new Shader { Code = PlainCode() };

    /// <summary>The plain terrain's colour (sRGB, the S1a tile colour) and roughness.</summary>
    public static readonly Color PlainColor = new(0.50f, 0.58f, 0.40f);
    public const double PlainRoughness = 0.95;

    /// <summary>
    /// The plain terrain: the same vertex stage (dry, no lift) and the same shading normal, one matte colour, Lambert —
    /// what the S1a vertex-colour material was on the fixed meshes, and the veil. 22 uniforms: the 14 of the stage + the
    /// colour + the veil's 7.
    /// </summary>
    public static string PlainCode() => $@"shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_lambert, specular_schlick_ggx;

uniform vec3 plain_albedo : source_color = vec3({PlainColor.R.ToString("0.00", CultureInfo.InvariantCulture)}, {PlainColor.G.ToString("0.00", CultureInfo.InvariantCulture)}, {PlainColor.B.ToString("0.00", CultureInfo.InvariantCulture)});
{VeilUniformBlock}{HemiUniformBlock}{TerrainLodGlsl.Chunk(false)}
varying vec2 v_world;
{VeilFunctions()}
void vertex() {{
{TerrainLodGlsl.VertexBody}
	v_world = tl_world.xz;
}}

void fragment() {{
	float fv_a = fv_amount(v_world);
	vec3 av_alb = plain_albedo * (1.0 - fv_a);
	vec3 av_n = tl_normal_at(v_world);
	ALBEDO = av_alb;
	EMISSION = fv_color * fv_a{HemiTerm("av_alb", "0.0", "av_n")};
	ROUGHNESS = {L(PlainRoughness)};
	METALLIC = 0.0;
	NORMAL = normalize((VIEW_MATRIX * vec4(av_n, 0.0)).xyz);
}}
";

    /// <summary>A GLSL literal with two decimals — and, like the browser's <c>ngLit</c>, refused when the number does
    /// not survive them (the shader would spend a different number than the maths).</summary>
    public static string L(double v)
    {
        var s = v.ToString("0.00", CultureInfo.InvariantCulture);
        if (double.Parse(s, CultureInfo.InvariantCulture) != v)
            throw new System.InvalidOperationException($"ground shader: {v} does not survive two decimals as \"{s}\"");
        return s;
    }

    public static string Code(bool water = false)
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

uniform float ground_roughness = 0.85;
uniform float ground_metallic = 0.02;

// ---- basement hole (ground.ts patchHole) ----
uniform vec4 hole_rect = vec4(0.0);   // minX, minZ, maxX, maxZ (world)
uniform float hole_on = 0.0;
{VeilUniformBlock}{HemiUniformBlock}{(water ? WaterUniforms : "")}{TerrainLodGlsl.Chunk(water)}
varying vec2 v_world;
{VeilFunctions()}
void vertex() {{
{TerrainLodGlsl.VertexBody}
	v_world = tl_world.xz;{(water ? "\n\tv_wet = tl_wet;" : "")}
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

{(water ? WaterFunctions() : "")}
void fragment() {{
	vec2 p = v_world;
	// The two derivatives, ONCE and at uniform control flow (layerCut.ts lcCompose).
	vec2 dpdx = dFdx(p);
	vec2 dpdy = dFdy(p);
	// patchHole: the strict test of the browser, after the derivatives so they stay in uniform control flow.
	if (hole_on > 0.5 && p.x > hole_rect.x && p.x < hole_rect.z && p.y > hole_rect.y && p.y < hole_rect.w) discard;
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
	alb = clamp(alb, 0.0, 1.0);
{(water ? WaterFragment() : DryFragment)}
}}
";
    }

    private static readonly string DryFragment = $@"	float fv_a = fv_amount(p);
	vec3 av_alb = alb * (1.0 - fv_a);
	vec3 av_n = tl_normal_at(p);
	ALBEDO = av_alb;
	EMISSION = fv_color * fv_a{HemiTerm("av_alb", "ground_metallic", "av_n")};
	ROUGHNESS = ground_roughness;
	METALLIC = ground_metallic;
	NORMAL = normalize((VIEW_MATRIX * vec4(av_n, 0.0)).xyz);";

    // ── The hemisphere term (Task 26b, World/HemiUniforms.cs) ──────────────────────────────────────────────────────────
    // The pair of shadowless directional lights that emulates three's HemisphereLight adds pair·n.y to a Lambert surface;
    // the terrain instances sit on a render layer those two lights skip, and the term is added here instead — the exact
    // sum Godot forms for them: colour·energy·max(N·L, 0) per light, × albedo × (1 − metallic) (ao is 1).

    public const string HemiUniformBlock = @"
// ---- hemisphere pair as a shader term (HemiUniforms.cs) ----
uniform vec3 av_hemi = vec3(0.0);                     // the pair's linear colour × energy, 0 = off
";

    /// <summary>The term added to EMISSION: <c>albedo · (1 − metallic) · av_hemi · n.y</c> of the world shading normal.</summary>
    public static string HemiTerm(string albedo, string metallic, string worldNormal)
        => $" + {albedo} * (1.0 - {metallic}) * av_hemi * normalize({worldNormal}).y";

    // ── The exploration veil (fogVeil.ts, Task 26) ─────────────────────────────────────────────────────────────────────
    // Seven uniforms, bound and pushed by VeilUniforms (World/VeilUniforms.cs) — the browser's shared uniform objects.

    /// <summary>The veil's uniform names, in declaration order (the binding and the check use this list).</summary>
    public static readonly string[] VeilUniformNames =
        { "fv_cells_a", "fv_cells_b", "fv_geom_a", "fv_geom_b", "fv_mix", "fv_alpha", "fv_color" };

    public const string VeilUniformBlock = @"
// ---- exploration veil (fogVeil.ts) ----
uniform sampler2D fv_cells_a : hint_default_black, filter_linear, repeat_disable;
uniform sampler2D fv_cells_b : hint_default_black, filter_linear, repeat_disable;
uniform vec4 fv_geom_a = vec4(0.0, 0.0, 1.0, 1.0);   // cx0, cz0, cols, rows (cells)
uniform vec4 fv_geom_b = vec4(0.0, 0.0, 1.0, 1.0);
uniform float fv_mix = 1.0;                           // 0 = A, 1 = B
uniform float fv_alpha = 0.0;                         // 0.72 · height ramp, 0 = off
uniform vec3 fv_color = vec3(0.0);                    // the sky, linear
";

    /// <summary>
    /// <c>fogExploredAt</c> (texel centres on cell centres, so the linear filter ramps over the 64 m between two and
    /// crosses 0.5 on the shared boundary) and the amount of haze at a plan point.
    /// </summary>
    public static string VeilFunctions() => $@"
float fv_explored_at(sampler2D cells, vec4 geom, vec2 p) {{
	vec2 uv = (p / {L(FogVeil.CellM)} - geom.xy) / geom.zw;
	return texture(cells, uv).r;
}}
float fv_amount(vec2 p) {{
	if (fv_alpha <= 0.0) return 0.0;
	float seen = mix(fv_explored_at(fv_cells_a, fv_geom_a, p), fv_explored_at(fv_cells_b, fv_geom_b, p), fv_mix);
	return fv_alpha * (1.0 - clamp(seen, 0.0, 1.0));
}}
";

    // ── The water variant (Wasser v2 K-A: client3d/src/scene/waterShade.ts terrainWaterFragmentGlsl) ──────────
    // The wet pieces' vertices are LIFTED onto the mirror by the vertex stage (TerrainLodGlsl tl_lift, per tap of the
    // morph pair) and hand the depth over the drawn bed out as v_wet (vTlodWet). Every water field is sampled HERE at
    // the pixel's own xz, on the water pyramid's BASE lattice (tl_water_geom, the browser's uTlodWaterGeom): the signed
    // distance through the very function and texture the vertex stage gates its lift by (tl_sd_at + tl_inside — ONE
    // field, so the drawn surface and the drawn look ride the same shore ramp, finding G1), the kind row (look table)
    // and the flow (ripple drift).

    private const string WaterUniforms = @"
// ---- water variant (waterShade.ts) ----
uniform sampler2D tw_wave : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D tw_kind : filter_nearest, repeat_disable;
uniform sampler2D tw_flow : filter_nearest, repeat_disable;
uniform sampler2D tw_look : filter_nearest, repeat_disable;
uniform vec3 tw_sky = vec3(0.62, 0.78, 0.91);
varying float v_wet;
";

    private static string WaterFunctions() => $@"
int tw_kind_row(vec2 p) {{
	if (tl_water_geom.w <= 0.0) return 0;
	ivec2 sz = textureSize(tw_kind, 0);
	float kcols = float(sz.x);
	float krows = float(sz.y);
	float stp = tl_water_geom.z;
	if (kcols < 1.0 || krows < 1.0 || stp <= 0.0) return 0;
	float fx = (p.x - tl_water_geom.x) / stp;
	float fz = (p.y - tl_water_geom.y) / stp;
	int i = int(clamp(floor(fx + 0.5), 0.0, kcols - 1.0));
	int j = int(clamp(floor(fz + 0.5), 0.0, krows - 1.0));
	return int(texelFetch(tw_kind, ivec2(i, j), 0).r + 0.5);
}}
vec2 tw_flow_at(vec2 p) {{
	if (tl_water_geom.w <= 0.0) return vec2(0.0);
	ivec2 sz = textureSize(tw_flow, 0);
	float cols = float(sz.x);
	float rows = float(sz.y);
	float stp = tl_water_geom.z;
	if (cols < 2.0 || rows < 2.0 || stp <= 0.0) return vec2(0.0);
	float fx = (p.x - tl_water_geom.x) / stp;
	float fz = (p.y - tl_water_geom.y) / stp;
	if (fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0) return vec2(0.0);
	float fi = min(floor(fx), cols - 2.0);
	float fj = min(floor(fz), rows - 2.0);
	float tx = fx - fi;
	float tz = fz - fj;
	int i = int(fi);
	int j = int(fj);
	vec2 f00 = texelFetch(tw_flow, ivec2(i, j), 0).rg;
	vec2 f10 = texelFetch(tw_flow, ivec2(i + 1, j), 0).rg;
	vec2 f01 = texelFetch(tw_flow, ivec2(i, j + 1), 0).rg;
	vec2 f11 = texelFetch(tw_flow, ivec2(i + 1, j + 1), 0).rg;
	return mix(mix(f00, f10, tx), mix(f01, f11, tx), tz);
}}
float tw_smooth(float t) {{
	float c = clamp(t, 0.0, 1.0);
	return c * c * (3.0 - 2.0 * c);
}}
// THE map is three's CanvasTexture, uploaded with flipY: its sample coordinate (u, v) reads the canvas row (1 − v)·N, i.e.
// Godot's (u, −v) on the periodic map — and the y gradients flip with it.
vec3 tw_wave_at(vec2 uv, vec2 gx, vec2 gy) {{
	vec2 f = vec2(1.0, -1.0);
	return textureGrad(tw_wave, uv * f, gx * f, gy * f).xyz;
}}
vec2 tw_frame(vec2 v, vec2 ax, vec2 ay, float aniso) {{
	return ax * (dot(v, ax) / aniso) + ay * dot(v, ay);
}}
vec3 tw_ripple(vec2 p, vec2 gx, vec2 gy, float wave_m, float speed, float flow_speed, float t) {{
	float px = max(length(gx), length(gy));
	float detail = clamp(1.0 - px / wave_m, 0.0, 1.0);
	vec2 flow = tw_flow_at(p);
	float len = length(flow);
	bool still = len < 1e-4;
	vec2 ax = still ? vec2(1.0, 0.0) : flow / max(len, 1e-4);
	vec2 ay = vec2(-ax.y, ax.x);
	float sp = still ? speed : flow_speed * len;
	float sgn = still ? 1.0 : -1.0;
	float aniso = 1.0;
	float cross_a = still ? 0.6 : 0.15;
	float cross_b = still ? 1.3 : 0.3;
	vec2 dir_a = ax + ay * cross_a;
	vec2 dir_b = still ? -(ax * 0.8 + ay * cross_b) : ax * 0.8 - ay * cross_b;
	float lam_a = wave_m;
	float lam_b = wave_m * 0.63;
	float lam_c = wave_m * 2.0;
	vec2 uv_a = tw_frame(p / lam_a + dir_a * (t * sp * sgn / lam_a), ax, ay, aniso);
	vec2 uv_b = tw_frame(p / lam_b + dir_b * (t * sp * sgn / lam_b), ax, ay, aniso);
	vec2 uv_c = tw_frame((p + ax * (t * sp * sgn)) / lam_c, ax, ay, 8.0);
	vec3 n_a = tw_wave_at(uv_a, tw_frame(gx, ax, ay, aniso) / lam_a, tw_frame(gy, ax, ay, aniso) / lam_a) * 2.0 - 1.0;
	vec3 n_b = tw_wave_at(uv_b, tw_frame(gx, ax, ay, aniso) / lam_b, tw_frame(gy, ax, ay, aniso) / lam_b) * 2.0 - 1.0;
	vec3 n_c = tw_wave_at(uv_c, tw_frame(gx, ax, ay, 8.0) / lam_c, tw_frame(gy, ax, ay, 8.0) / lam_c) * 2.0 - 1.0;
	vec3 n = normalize(n_a + n_b + n_c * (still ? 0.0 : 0.35));
	n = mix(vec3(0.0, 0.0, 1.0), n, detail);
	return normalize(vec3(n.x, n.z, n.y));
}}
";

    /// <summary>
    /// <c>tlodWaterSurface</c> + <c>tlodWaterNormal</c> + <c>tlodWaterOut</c>. The last one writes on three's
    /// FINISHED light (<c>mix(light, sky, k)</c>, then <c>mix(…, white, foam)</c>); a Godot spatial shader has no
    /// post-light hook, so the same two mixes go in as <c>ALBEDO × (1 − k)(1 − f)</c> plus
    /// <c>EMISSION = sky·k·(1 − f) + f</c> — identical for the diffuse share, the specular share is not
    /// scaled down (cost-neutral; a hair brighter highlight on deep water).
    /// </summary>
    private static string WaterFragment() => $@"	float rough = ground_roughness;
	float metal = ground_metallic;
	float tw_a = 0.0;
	float tw_s = 0.0;
	float tw_foam = 0.0;
	float tw_skymix = 0.0;
	vec3 tw_n = vec3(0.0, 1.0, 0.0);
	float d = v_wet;
	float edge = max(fwidth(d), {L(WaterShade.EdgeFadeM)});
	if (d > 0.0) {{
		int rows = textureSize(tw_look, 0).y;
		float inside = tl_inside(tl_sd_at(p));
		int layer = clamp(tw_kind_row(p), 0, rows - 1);
		float rim = clamp(d / edge, 0.0, 1.0) * inside;
		if (rim > 0.0) {{
			vec4 look0 = texelFetch(tw_look, ivec2(0, layer), 0);
			vec4 look1 = texelFetch(tw_look, ivec2(1, layer), 0);
			vec4 look2 = texelFetch(tw_look, ivec2(2, layer), 0);
			float shore = tw_smooth(d / max(look1.w, 1e-3));
			tw_s = rim * mix({L(WaterShade.ShallowSurfaceMin)}, 1.0, shore);
			tw_a = shore * rim;
			float raw_foam = 1.0 - tw_smooth(d / {L(WaterShade.FoamBandM)});
			tw_foam = raw_foam * min(shore + raw_foam * {L(WaterShade.FoamMinCover)}, 1.0) * rim;
			tw_skymix = look0.w;
			tw_n = tw_ripple(p, dpdx, dpdy, max(look1.x, 0.05), look1.y, look1.z, mod(TIME, 3600.0));
			alb = mix(alb, look0.rgb, tw_a);
			rough = mix(rough, look2.x, tw_s);
			metal = mix(metal, look2.y, tw_s);
		}}
	}}
	vec3 nw;
	if (tw_s <= 0.0) nw = tl_normal_at(p);
	else if (tw_a >= 1.0) nw = tw_n;
	else nw = normalize(mix(tl_normal_at(p), vec3(0.0, 1.0, 0.0), tw_a) + (tw_n - vec3(0.0, 1.0, 0.0)) * tw_s);
	NORMAL = normalize((VIEW_MATRIX * vec4(nw, 0.0)).xyz);
	float fres = pow(1.0 - clamp(dot(VIEW, NORMAL), 0.0, 1.0), 3.0);
	float k = clamp(fres * tw_skymix, 0.0, 1.0) * tw_s;
	float f = tw_foam * {L(WaterShade.FoamStrength)};
	// The veil first, then the sky and the foam (the browser's insertion order): ((L·(1 − a) + C·a)·(1 − k) + S·k)·(1 − f) + f.
	float fv_a = fv_amount(p);
	vec3 av_alb = alb * (1.0 - k) * (1.0 - f) * (1.0 - fv_a);
	ALBEDO = av_alb;
	EMISSION = (fv_color * fv_a * (1.0 - k) + tw_sky * k) * (1.0 - f) + vec3(f){HemiTerm("av_alb", "metal", "nw")};
	ROUGHNESS = rough;
	METALLIC = metal;";
}
