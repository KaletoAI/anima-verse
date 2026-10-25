using System;
using System.Collections.Generic;
using System.Globalization;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>
/// The scatter and undergrowth materials, with the browser's wind (<c>applySway</c> in
/// <c>client3d/src/scene/ground.ts</c>) as a Godot spatial vertex shader:
///
///   swayDir   = normalize(instanceMatrixᵀ · (0.8, 0, 0.6)) / |instanceMatrix col 0|   (world-fixed, metres)
///   swayPhase = fract(sin(dot(instance translation xz, (12.9898, 78.233))) · 43758.5453) · 2π
///   swayUp    = (max(y, 0) / uSwayRef)²
///   xz       += amp · swayUp · sin(t · 1.7 + swayPhase) · swayDir.xz
///
/// The amplitude is a LITERAL like in the browser (one program per amplitude, two decimals), so an
/// amplitude below 0.01 compiles no wind at all (the browser does not patch it). In Godot the multimesh
/// instance transform is already folded into <c>MODEL_MATRIX</c> inside <c>vertex()</c>, and the scatter
/// node sits at the origin, so <c>MODEL_MATRIX</c> is three's <c>instanceMatrix</c>.
///
/// Fragment side, kept to what three's MeshStandardMaterial does with these inputs: albedo map × colour
/// (× instance colour for the undergrowth), roughness/metallic, alpha cut. Not ported: the camera-avatar
/// corridor fade (<c>applyOcclusionFade</c>) and the ground hole patch.
/// </summary>
public static class ScatterShaders
{
    public const double SwaySpeed = 1.7;
    public const double SwayMinM = TerrainTypeInfo.SwayMinM, SwayMaxM = TerrainTypeInfo.SwayMaxM;
    private static readonly Dictionary<string, Shader> Cache = new();

    /// <summary>The literal the browser compiles (<c>applySway</c>): clamped to 0.5, two decimals; 0 = none.</summary>
    public static double Amp(double swayM)
    {
        double amp = Js.Round(Math.Min(Math.Max(swayM, 0), SwayMaxM) * 100) / 100;
        return amp >= SwayMinM ? amp : 0;
    }

    public static Shader Get(double amp, bool textured, bool instanceColor, bool alphaCut, bool cullDisabled)
    {
        string key = $"{amp:0.00}|{textured}|{instanceColor}|{alphaCut}|{cullDisabled}";
        if (Cache.TryGetValue(key, out var s)) return s;
        s = new Shader { Code = Code(amp, textured, instanceColor, alphaCut, cullDisabled) };
        // Shader safety (Task S3c): a sway shader that does not compile falls back to the same material without
        // the wind (same uniform names, so every SetShaderParameter still lands) instead of the error colour.
        if (!World.ShaderSafety.Ok(s, $"scatter[sway={amp:0.00}{(textured ? ",tex" : "")}{(instanceColor ? ",inst" : "")}{(alphaCut ? ",cut" : "")}{(cullDisabled ? ",both" : "")}]"))
            s = new Shader { Code = Code(0, textured, instanceColor, alphaCut, cullDisabled) };
        Cache[key] = s;
        return s;
    }

    public static string Code(double amp, bool textured, bool instanceColor, bool alphaCut, bool cullDisabled)
    {
        var inv = CultureInfo.InvariantCulture;
        string bend = amp > 0
            ? $@"
	vec3 sway_dir = normalize(transpose(mat3(MODEL_MATRIX)) * vec3(0.8, 0.0, 0.6)) / max(length(MODEL_MATRIX[0].xyz), 1e-6);
	float sway_phase = fract(sin(dot(MODEL_MATRIX[3].xz, vec2(12.9898, 78.233))) * 43758.5453) * 6.2831853;
	float sway_up = pow(max(VERTEX.y, 0.0) / sway_ref, 2.0);
	VERTEX.xz += {amp.ToString("0.00", inv)} * sway_up * sin(TIME * {SwaySpeed.ToString("0.00", inv)} + sway_phase) * sway_dir.xz;"
            : "";
        string albedo = textured ? "texture(albedo_tex, UV) * albedo_color" : "albedo_color";
        if (instanceColor) albedo = $"({albedo}) * COLOR";
        return $@"shader_type spatial;
render_mode {(cullDisabled ? "cull_disabled" : "cull_back")}, depth_draw_opaque, diffuse_burley, specular_schlick_ggx;
uniform vec4 albedo_color : source_color = vec4(1.0);
{(textured ? "uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;" : "")}
uniform float roughness_v = 0.95;
uniform float metallic_v = 0.0;
uniform float sway_ref = 1.0;
{(alphaCut ? "uniform float alpha_cut = 0.5;" : "")}
void vertex() {{{bend}
}}
void fragment() {{
	vec4 c = {albedo};
	ALBEDO = c.rgb;
	ROUGHNESS = roughness_v;
	METALLIC = metallic_v;
{(alphaCut ? "	ALPHA = c.a;\n	ALPHA_SCISSOR_THRESHOLD = alpha_cut;" : "")}
}}
";
    }

    /// <summary>three's <c>new Color(hex).multiplyScalar(k)</c> (linear working space) as the sRGB colour a
    /// <c>source_color</c> uniform expects.</summary>
    public static Color ScaledColor(string hex, double k)
    {
        Color c;
        try { c = Color.FromHtml(hex); } catch (Exception) { c = new Color(0.533f, 0.533f, 0.533f); }
        var lin = c.SrgbToLinear();
        var scaled = new Color((float)(lin.R * k), (float)(lin.G * k), (float)(lin.B * k), 1f);
        return scaled.LinearToSrgb();
    }

    /// <summary>The tuft stand-in of a scatter entry (<c>buildScatter</c>): kind colour × 0.75, roughness 0.95.</summary>
    public static ShaderMaterial Tuft(string kindColor, double sway, double refH)
    {
        var m = new ShaderMaterial { Shader = Get(Amp(sway), false, false, false, false) };
        m.SetShaderParameter("albedo_color", ScaledColor(kindColor, 0.75));
        m.SetShaderParameter("roughness_v", 0.95f);
        m.SetShaderParameter("sway_ref", (float)(refH > 0 ? refH : 1));
        return m;
    }

    /// <summary>A loaded prop's own material (a CLONE in the browser) with the wind on top.</summary>
    public static ShaderMaterial FromGltf(Material? src, double sway, double refH)
    {
        var std = src as BaseMaterial3D;
        bool alphaCut = std is { Transparency: BaseMaterial3D.TransparencyEnum.AlphaScissor };
        bool cullOff = std is { CullMode: BaseMaterial3D.CullModeEnum.Disabled };
        var tex = std?.AlbedoTexture;
        var m = new ShaderMaterial { Shader = Get(Amp(sway), tex is not null, false, alphaCut, cullOff) };
        m.SetShaderParameter("albedo_color", std?.AlbedoColor ?? Colors.White);
        if (tex is not null) m.SetShaderParameter("albedo_tex", tex);
        m.SetShaderParameter("roughness_v", std?.Roughness ?? 1f);
        m.SetShaderParameter("metallic_v", std?.Metallic ?? 0f);
        m.SetShaderParameter("sway_ref", (float)(refH > 0 ? refH : 1));
        if (alphaCut) m.SetShaderParameter("alpha_cut", std!.AlphaScissorThreshold);
        return m;
    }

    /// <summary><c>undergrowthMaterial</c>: blade texture, colour × 0.75 × the tint maximum, alpha cut 0.35,
    /// front side, per-instance colour, wind referenced to the mean tuft height.</summary>
    public static ShaderMaterial Undergrowth(Texture2D tex, string kindColor, double swayM)
    {
        var m = new ShaderMaterial { Shader = Get(Amp(swayM), true, true, true, false) };
        m.SetShaderParameter("albedo_color", ScaledColor(kindColor, UndergrowthMath.Albedo * UndergrowthMath.BladeTintMax));
        m.SetShaderParameter("albedo_tex", tex);
        m.SetShaderParameter("roughness_v", 0.95f);
        m.SetShaderParameter("sway_ref", (float)UndergrowthMath.HRefM);
        m.SetShaderParameter("alpha_cut", (float)UndergrowthMath.AlphaTest);
        return m;
    }
}
