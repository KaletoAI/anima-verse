using System;
using System.Globalization;
using AnimaNative.Water;

namespace AnimaNative.Terrain;

/// <summary>
/// The CDLOD terrain's GPU half as Godot shading language — a port of the browser's GLSL generators in
/// <c>client3d/src/scene/terrainLod.ts</c>: <c>terrainLodSampleGlsl</c> (the pyramid sampler both stages read),
/// <c>terrainLodWaterGlsl</c> (the water level, the outline gate and the lift of the wet program,
/// <c>waterShade.ts waterSdGlsl/waterGateGlsl</c>), <c>terrainLodGlsl</c> (λ, the water mip cap, the block-descent
/// morph of <c>tlodCompute</c>) and <c>terrainLodNormalGlsl</c> (the fragment's shading normal).
///
/// Godot differences, all mechanism: built-ins live only in the processor functions, so the node
/// (<c>INSTANCE_CUSTOM</c> = (x, z, size, level), the browser's <c>iNode</c>), the patch point (<c>VERTEX.xz</c> in
/// [0, 1]², the browser's <c>position.xz</c>) and the eye (<c>INV_VIEW_MATRIX[3].xyz</c>, the browser's
/// <c>cameraPosition</c>) are passed in; the isolation toggles (freeze, no-morph, flat normal, no-water) are not ported.
/// Every constant is printed from the C# one (<see cref="TerrainLod"/>, <see cref="WaterShade"/>), and the
/// statement-for-statement CPU twin of this text is <see cref="TerrainShaderTwin"/>.
/// </summary>
public static class TerrainLodGlsl
{
    /// <summary>A float literal as GLSL reads it (shortest round-trip, always with a decimal point or exponent).</summary>
    public static string Lit(double v)
    {
        var s = v.ToString("R", CultureInfo.InvariantCulture);
        return s.Contains('.') || s.Contains('E') ? s.Replace("E", "e") : s + ".0";
    }

    /// <summary>The constants the twin reads from C# — the check compares these lines with the twin's numbers.</summary>
    public static string Constants() => $@"
const float TL_PATCH_N = {Lit(TerrainLod.PatchN)};
const float TL_MORPH_START = {Lit(TerrainLod.MorphStart)};
const float TL_CAP_NONE = {Lit(TerrainLod.LodCapNone)};
";

    /// <summary>
    /// The uniforms (14 dry, 18 with the water lift). Geometry (originX, originZ, step, level count — 0 = none), level
    /// rows (cols, rows, step, first texture row), the near rectangle, the world frame, the rings, the base step, the
    /// normal span, and the water mip cap's grid (x0, z0, step, cols) + (rows, relax, 0, 0).
    /// </summary>
    public static string Uniforms(bool water)
    {
        int n = TerrainLod.MaxLodLevels;
        var u = $@"
// ---- CDLOD terrain (terrainLod.ts) ----
uniform sampler2D tl_near : filter_nearest, repeat_disable;
uniform sampler2D tl_far : filter_nearest, repeat_disable;
uniform vec4 tl_near_geom = vec4(0.0, 0.0, 1.0, 0.0);
uniform vec4 tl_far_geom = vec4(0.0, 0.0, 1.0, 0.0);
uniform vec4 tl_near_levels[{n}];
uniform vec4 tl_far_levels[{n}];
uniform vec4 tl_near_rect = vec4(0.0, 0.0, -1.0, -1.0);
uniform vec4 tl_extent = vec4(-1.0e6, -1.0e6, 1.0e6, 1.0e6);
uniform float tl_range[{n}];
uniform float tl_base_step = {Lit(TerrainField.FallbackBaseStepM)};
uniform float tl_normal_span = {Lit(TerrainField.FallbackBaseStepM)};
uniform sampler2D tl_cap : filter_nearest, repeat_disable;
uniform vec4 tl_cap_geom = vec4(0.0, 0.0, 1.0, 0.0);
uniform vec4 tl_cap_fit = vec4(0.0);
";
        if (water)
            u += $@"uniform sampler2D tl_water : filter_nearest, repeat_disable;
uniform sampler2D tl_water_sd : filter_nearest, repeat_disable;
uniform vec4 tl_water_geom = vec4(0.0, 0.0, 1.0, 0.0);
uniform vec4 tl_water_levels[{n}];
";
        return u;
    }

    /// <summary>The sampler (<c>tlodGrid</c>, <c>tlodLevel</c>, <c>tlodHeight</c>) and the shading normal (<c>tlodNormalAt</c>).</summary>
    public const string Sampler = @"
float tl_grid(sampler2D tex, vec2 origin, vec4 lv, vec2 p) {
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
	int j = int(fj + lv.w);
	float h00 = texelFetch(tex, ivec2(i, j), 0).r;
	float h10 = texelFetch(tex, ivec2(i + 1, j), 0).r;
	float h01 = texelFetch(tex, ivec2(i, j + 1), 0).r;
	float h11 = texelFetch(tex, ivec2(i + 1, j + 1), 0).r;
	float north = h00 * (1.0 - tx) + h10 * tx;
	float south = h01 * (1.0 - tx) + h11 * tx;
	return north * (1.0 - tz) + south * tz;
}
int tl_level(float base_step, float count, float node_step) {
	if (base_step <= 0.0) return 0;
	float k = floor(log2(max(node_step / base_step, 1.0)) + 0.5);
	return int(clamp(k, 0.0, count - 1.0));
}
float tl_height(vec2 p, float node_step) {
	if (tl_near_geom.w > 0.0 && p.x >= tl_near_rect.x && p.x <= tl_near_rect.z
	    && p.y >= tl_near_rect.y && p.y <= tl_near_rect.w) {
		int k = tl_level(tl_near_geom.z, tl_near_geom.w, node_step);
		return tl_grid(tl_near, tl_near_geom.xy, tl_near_levels[k], p);
	}
	// No far pyramid (an overview under 2 × 2): the flat world. The browser leaves this to clamp(k, 0, −1) and an
	// out-of-range uniform index, which GLSL does not define; the guard keeps the read inside the array.
	if (tl_far_geom.w <= 0.0) return 0.0;
	int k = tl_level(tl_far_geom.z, tl_far_geom.w, node_step);
	return tl_grid(tl_far, tl_far_geom.xy, tl_far_levels[k], p);
}
vec3 tl_normal_at(vec2 p) {
	float s = max(tl_normal_span, 1e-3);
	float hx = tl_height(vec2(p.x + s, p.y), 0.0) - tl_height(vec2(p.x - s, p.y), 0.0);
	float hz = tl_height(vec2(p.x, p.y + s), 0.0) - tl_height(vec2(p.x, p.y - s), 0.0);
	return normalize(vec3(-hx, 2.0 * s, -hz));
}
";

    /// <summary>The water level pyramid (masked bilinear, <c>TLOD_DRY</c> outside the near window), the outline's signed
    /// distance on the same lattice, the gate (<c>twInside</c>) and the per-tap lift (<c>tlodLift</c>).</summary>
    public static string WaterLift() => $@"
const float TL_DRY = -1.0e30;
const float TL_SD_DRY = {Lit(Ground.WaterTileField.SdDry)};
float tl_water_grid(vec4 lv, vec2 p) {{
	float cols = lv.x;
	float rows = lv.y;
	float stp = lv.z;
	if (cols < 2.0 || rows < 2.0 || stp <= 0.0) return TL_DRY;
	float fx = clamp((p.x - tl_water_geom.x) / stp, 0.0, cols - 1.0);
	float fz = clamp((p.y - tl_water_geom.y) / stp, 0.0, rows - 1.0);
	float fi = min(floor(fx), cols - 2.0);
	float fj = min(floor(fz), rows - 2.0);
	float tx = fx - fi;
	float tz = fz - fj;
	int i = int(fi);
	int j = int(fj + lv.w);
	float w00 = (1.0 - tx) * (1.0 - tz);
	float w10 = tx * (1.0 - tz);
	float w01 = (1.0 - tx) * tz;
	float w11 = tx * tz;
	float sum = 0.0;
	if (w00 != 0.0) sum += texelFetch(tl_water, ivec2(i, j), 0).r * w00;
	if (w10 != 0.0) sum += texelFetch(tl_water, ivec2(i + 1, j), 0).r * w10;
	if (w01 != 0.0) sum += texelFetch(tl_water, ivec2(i, j + 1), 0).r * w01;
	if (w11 != 0.0) sum += texelFetch(tl_water, ivec2(i + 1, j + 1), 0).r * w11;
	return sum;
}}
float tl_water_at(vec2 p, float node_step) {{
	if (tl_water_geom.w <= 0.0
	    || p.x < tl_near_rect.x || p.x > tl_near_rect.z
	    || p.y < tl_near_rect.y || p.y > tl_near_rect.w) return TL_DRY;
	int k = tl_level(tl_water_geom.z, tl_water_geom.w, node_step);
	return tl_water_grid(tl_water_levels[k], p);
}}
float tl_sd_at(vec2 p) {{
	if (tl_water_geom.w <= 0.0) return TL_SD_DRY;
	ivec2 sz = textureSize(tl_water_sd, 0);
	float cols = float(sz.x);
	float rows = float(sz.y);
	float stp = tl_water_geom.z;
	if (cols < 2.0 || rows < 2.0 || stp <= 0.0) return TL_SD_DRY;
	float fx = (p.x - tl_water_geom.x) / stp;
	float fz = (p.y - tl_water_geom.y) / stp;
	if (fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0) return TL_SD_DRY;
	float fi = min(floor(fx), cols - 2.0);
	float fj = min(floor(fz), rows - 2.0);
	float tx = fx - fi;
	float tz = fz - fj;
	int i = int(fi);
	int j = int(fj);
	float s00 = texelFetch(tl_water_sd, ivec2(i, j), 0).r;
	float s10 = texelFetch(tl_water_sd, ivec2(i + 1, j), 0).r;
	float s01 = texelFetch(tl_water_sd, ivec2(i, j + 1), 0).r;
	float s11 = texelFetch(tl_water_sd, ivec2(i + 1, j + 1), 0).r;
	return mix(mix(s00, s10, tx), mix(s01, s11, tx), tz);
}}
float tl_inside(float sd) {{
	float c = clamp(sd / {Lit(WaterShade.SdBandM)}, 0.0, 1.0);
	return c * c * (3.0 - 2.0 * c);
}}
// The lift of ONE tap of the morph pair: only inside the authored outline (the gate rides the fragment's own
// curve), and the dry test is `>` — a NaN (dry) level fails it, so the ground keeps its own height.
float tl_lift(float h, vec2 p, float node_step, float sd) {{
	float g = tl_inside(sd);
	if (g <= 0.0) return h;
	float w = tl_water_at(p, node_step);
	return (w > h) ? h + (w - h) * g : h;
}}
";

    /// <summary><c>tlodLambda</c>, <c>tlodCapAt</c>, <c>tlodMorphAt</c> and <c>tlodCompute</c>; the wet program lifts
    /// each tap of the morph pair at its own footprint and hands the depth out (<c>vTlodWet</c>).</summary>
    public static string Compute(bool water)
    {
        int n = TerrainLod.MaxLodLevels;
        string height = water
            ? @"float sdw = tl_sd_at(p);
	float h1 = tl_height(p, node_step * m1);
	float h2 = tl_height(p, node_step * m2);
	float l1 = tl_lift(h1, p, node_step * m1, sdw);
	float l2 = tl_lift(h2, p, node_step * m2, sdw);
	float h = mix(l1, l2, f);
	wet = mix(l1 - h1, l2 - h2, f);"
            : "float h = mix(tl_height(p, node_step * m1), tl_height(p, node_step * m2), f);";
        return $@"
float tl_lambda(float d) {{
	float lam = 0.0;
	float prev = 0.0;
	for (int i = 0; i < {n}; i++) {{
		float r = tl_range[i];
		if (r > 0.0) {{
			float s = prev + TL_MORPH_START * (r - prev);
			prev = r;
			lam += (r > s) ? clamp((d - s) / (r - s), 0.0, 1.0) : step(r, d);
		}}
	}}
	return lam;
}}
float tl_cap_at(vec2 p) {{
	float cols = tl_cap_geom.w;
	float rows = tl_cap_fit.x;
	float stp = tl_cap_geom.z;
	if (cols < 2.0 || rows < 2.0 || stp <= 0.0) return TL_CAP_NONE;
	float fx = (p.x - tl_cap_geom.x) / stp;
	float fz = (p.y - tl_cap_geom.y) / stp;
	if (fx <= 0.0 || fz <= 0.0 || fx >= cols - 1.0 || fz >= rows - 1.0) return TL_CAP_NONE;
	float fi = floor(fx);
	float fj = floor(fz);
	float tx = fx - fi;
	float tz = fz - fj;
	int i = int(fi);
	int j = int(fj);
	float c00 = texelFetch(tl_cap, ivec2(i, j), 0).r;
	float c10 = texelFetch(tl_cap, ivec2(i + 1, j), 0).r;
	float c01 = texelFetch(tl_cap, ivec2(i, j + 1), 0).r;
	float c11 = texelFetch(tl_cap, ivec2(i + 1, j + 1), 0).r;
	float north = c00 * (1.0 - tx) + c10 * tx;
	float south = c01 * (1.0 - tx) + c11 * tx;
	return north * (1.0 - tz) + south * tz + tl_cap_fit.y;
}}
// The morph coordinate at one lattice point of the piece: λ at the point clamped into the world frame, measured
// from the eye to the FINEST ground there, capped by the water, minus the piece's own level.
float tl_morph_at(vec4 node, vec2 gi, float node_step, vec3 eye) {{
	vec2 p = clamp(node.xy + gi * node_step, tl_extent.xy, tl_extent.zw);
	float d = distance(vec3(p.x, tl_height(p, 0.0), p.y), eye);
	return max(min(tl_lambda(d), tl_cap_at(p)) - node.w, 0.0);
}}
// tlodCompute: node = (x, z, size, level); the vertex spacing comes from the LEVEL (a parent quadrant carries the
// parent's spacing over a child-sized square), the indices past the piece's cells collapse onto its last row and
// column; the morph is read at the block owner (the coarsest j whose anchor reports λ ≥ level + j), snaps between
// the 2^k and 2^(k+1) lattices and mixes the two mips' heights.
vec3 tl_compute(vec4 node, vec2 patch_xz, vec3 eye, out float wet) {{
	wet = 0.0;
	float node_step = tl_base_step * exp2(node.w);
	float cells = floor(node.z / node_step + 0.5);
	vec2 gi = min(patch_xz * TL_PATCH_N, vec2(cells));
	float k = 0.0;
	float t = tl_morph_at(node, gi, node_step, eye);
	for (int j = {n - 1}; j >= 1; j--) {{
		float m = exp2(float(j));
		float tj = tl_morph_at(node, gi - mod(gi, m), node_step, eye);
		if (floor(tj) >= float(j)) {{
			k = float(j);
			t = tj;
			break;
		}}
	}}
	float f = clamp(t - k, 0.0, 1.0);
	float m1 = exp2(k);
	float m2 = m1 * 2.0;
	vec2 gm = mix(gi - mod(gi, m1), gi - mod(gi, m2), f);
	vec2 p = clamp(node.xy + gm * node_step, tl_extent.xy, tl_extent.zw);
	{height}
	return vec3(p.x, h, p.y);
}}
";
    }

    /// <summary>Everything above in declaration order: constants, uniforms, sampler + normal, the water lift (wet only), the morph.</summary>
    public static string Chunk(bool water) => Constants() + Uniforms(water) + Sampler + (water ? WaterLift() : "") + Compute(water);

    /// <summary>
    /// The vertex body: the node out of <c>INSTANCE_CUSTOM</c>, the patch point out of <c>VERTEX.xz</c>, the eye out of
    /// the inverse view. The mesh sits at the origin with an identity transform, so the world position IS the model
    /// position; the vertex normal is straight up (the shading normal is the fragment's).
    /// </summary>
    public const string VertexBody = @"	float tl_wet = 0.0;
	vec3 tl_world = tl_compute(INSTANCE_CUSTOM, VERTEX.xz, INV_VIEW_MATRIX[3].xyz, tl_wet);
	VERTEX = tl_world;
	NORMAL = vec3(0.0, 1.0, 0.0);";
}
