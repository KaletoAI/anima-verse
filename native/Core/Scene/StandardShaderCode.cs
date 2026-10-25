using System.Collections.Generic;
using System.Text;

namespace AnimaNative.Scene;

/// <summary>
/// What a StandardMaterial3D decides about its generated shader — the inputs of Godot 4.7.2's
/// <c>BaseMaterial3D::_update_shader</c> (scene/resources/material.cpp) that a glTF import can set. Enum values are
/// Godot's own (<c>BaseMaterial3D.TransparencyEnum</c> etc.); the Godot side maps them by name.
/// <see cref="Unsupported"/> lists every feature of the material this port does NOT generate (triplanar, detail,
/// refraction, clearcoat, …) — a material with any of them is not converted (<see cref="StandardShaderCode.Generate"/>
/// returns null) and keeps its own look, uncut.
/// </summary>
public sealed record StandardShaderSpec
{
    public enum TransparencyMode { Disabled = 0, Alpha = 1, AlphaScissor = 2, AlphaHash = 3, AlphaDepthPrePass = 4 }
    public enum BlendModeKind { Mix = 0, Add = 1, Sub = 2, Mul = 3, PremultAlpha = 4 }
    public enum DepthDrawKind { OpaqueOnly = 0, Always = 1, Disabled = 2 }
    public enum CullKind { Back = 0, Front = 1, Disabled = 2 }
    public enum DiffuseKind { Burley = 0, Lambert = 1, LambertWrap = 2, Toon = 3 }
    public enum SpecularKind { SchlickGgx = 0, Toon = 1, Disabled = 2 }
    public enum ShadingKind { Unshaded = 0, PerPixel = 1, PerVertex = 2 }
    public enum FilterKind { Nearest = 0, Linear = 1, NearestWithMipmaps = 2, LinearWithMipmaps = 3,
                             NearestWithMipmapsAnisotropic = 4, LinearWithMipmapsAnisotropic = 5 }
    public enum Channel { Red = 0, Green = 1, Blue = 2, Alpha = 3, Grayscale = 4 }
    public enum DepthTestKind { Default = 0, Inverted = 1 }

    public TransparencyMode Transparency { get; init; }
    public BlendModeKind BlendMode { get; init; }
    public DepthDrawKind DepthDraw { get; init; }
    public CullKind Cull { get; init; }
    public DiffuseKind Diffuse { get; init; }
    public SpecularKind Specular { get; init; }
    public ShadingKind Shading { get; init; } = ShadingKind.PerPixel;
    public FilterKind Filter { get; init; } = FilterKind.LinearWithMipmaps;
    public bool Repeat { get; init; } = true;
    public DepthTestKind DepthTest { get; init; }
    public bool DisableDepthTest { get; init; }
    public bool AlbedoFromVertexColor { get; init; }
    public bool SrgbVertexColor { get; init; }
    public bool AlbedoForceSrgb { get; init; }
    public bool DontReceiveShadows { get; init; }
    public bool DisableAmbientLight { get; init; }
    public bool ShadowToOpacity { get; init; }
    public bool DisableFog { get; init; }
    public bool DisableSpecularOcclusion { get; init; }
    public Channel RoughnessChannel { get; init; } = Channel.Red;
    public bool NormalMap { get; init; }
    public bool Emission { get; init; }
    /// <summary><c>EMISSION_OP_ADD</c> (true) or <c>EMISSION_OP_MULTIPLY</c>.</summary>
    public bool EmissionAdd { get; init; } = true;
    public bool EmissionOnUv2 { get; init; }
    public bool AmbientOcclusion { get; init; }
    public bool AoOnUv2 { get; init; }
    public IReadOnlyList<string> Unsupported { get; init; } = new List<string>();
}

/// <summary>
/// A port of Godot 4.7.2's <c>BaseMaterial3D::_update_shader</c> for the features a glTF import sets
/// (modules/gltf/gltf_document.cpp <c>_parse_materials</c> + the vertex-colour flag of <c>_parse_meshes</c>): albedo
/// (factor, texture, vertex colour), metallic/roughness (factors, textures, channels), normal map, emission (add or
/// multiply, UV1/UV2), ambient occlusion (UV1/UV2), the alpha modes (blend with/without depth pre-pass, scissor, hash),
/// culling, unshaded, KHR_texture_transform (uv1 scale/offset) and the sampler's filter/repeat. Every emitted line is
/// the engine's own, in the engine's order, with the engine's UNIFORM NAMES — so a ShaderMaterial built from it and
/// fed the material's own values draws the same pixels; the native client needs it only to append the room clip,
/// the cutouts and the depth cut (<see cref="CutShader.Inject"/>), which Godot cannot patch into a
/// StandardMaterial3D (there is no onBeforeCompile, and its generated code is not readable at runtime).
/// </summary>
public static class StandardShaderCode
{
    /// <summary>The engine's code for <paramref name="s"/>, or null when the material uses a feature this port lacks.</summary>
    public static string? Generate(StandardShaderSpec s)
    {
        if (s.Unsupported.Count > 0) return null;
        var tf = s.Filter switch
        {
            StandardShaderSpec.FilterKind.Nearest => "filter_nearest",
            StandardShaderSpec.FilterKind.Linear => "filter_linear",
            StandardShaderSpec.FilterKind.NearestWithMipmaps => "filter_nearest_mipmap",
            StandardShaderSpec.FilterKind.LinearWithMipmaps => "filter_linear_mipmap",
            StandardShaderSpec.FilterKind.NearestWithMipmapsAnisotropic => "filter_nearest_mipmap_anisotropic",
            _ => "filter_linear_mipmap_anisotropic",
        } + (s.Repeat ? ", repeat_enable" : ", repeat_disable");

        var c = new StringBuilder();
        c.Append("// Anima native: Godot 4.7.2 StandardMaterial3D shader (material.cpp generator, glTF subset).\n\n");
        c.Append("shader_type spatial;\nrender_mode ");
        c.Append(s.BlendMode switch
        {
            StandardShaderSpec.BlendModeKind.Add => "blend_add",
            StandardShaderSpec.BlendModeKind.Sub => "blend_sub",
            StandardShaderSpec.BlendModeKind.Mul => "blend_mul",
            StandardShaderSpec.BlendModeKind.PremultAlpha => "blend_premul_alpha",
            _ => "blend_mix",
        });
        c.Append(s.DepthDraw switch
        {
            StandardShaderSpec.DepthDrawKind.Always => ", depth_draw_always",
            StandardShaderSpec.DepthDrawKind.Disabled => ", depth_draw_never",
            _ => ", depth_draw_opaque",
        });
        c.Append(s.Cull switch
        {
            StandardShaderSpec.CullKind.Front => ", cull_front",
            StandardShaderSpec.CullKind.Disabled => ", cull_disabled",
            _ => ", cull_back",
        });
        c.Append(s.Diffuse switch
        {
            StandardShaderSpec.DiffuseKind.Lambert => ", diffuse_lambert",
            StandardShaderSpec.DiffuseKind.LambertWrap => ", diffuse_lambert_wrap",
            StandardShaderSpec.DiffuseKind.Toon => ", diffuse_toon",
            _ => ", diffuse_burley",
        });
        c.Append(s.Specular switch
        {
            StandardShaderSpec.SpecularKind.Toon => ", specular_toon",
            StandardShaderSpec.SpecularKind.Disabled => ", specular_disabled",
            _ => ", specular_schlick_ggx",
        });
        if (s.Shading == StandardShaderSpec.ShadingKind.Unshaded) c.Append(", unshaded");
        if (s.DisableDepthTest) c.Append(", depth_test_disabled");
        else if (s.DepthTest == StandardShaderSpec.DepthTestKind.Inverted) c.Append(", depth_test_inverted");
        if (s.Shading == StandardShaderSpec.ShadingKind.PerVertex) c.Append(", vertex_lighting");
        if (s.DontReceiveShadows) c.Append(", shadows_disabled");
        if (s.DisableAmbientLight) c.Append(", ambient_light_disabled");
        if (s.ShadowToOpacity) c.Append(", shadow_to_opacity");
        if (s.DisableFog) c.Append(", fog_disabled");
        if (s.DisableSpecularOcclusion) c.Append(", specular_occlusion_disabled");
        if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaDepthPrePass) c.Append(", depth_prepass_alpha");
        c.Append(";\n");

        c.Append($"\nuniform vec4 albedo : source_color;\nuniform sampler2D texture_albedo : source_color, {tf};\n");
        if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor)
            c.Append("uniform float alpha_scissor_threshold : hint_range(0.0, 1.0, 0.001);\n");
        else if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaHash)
            c.Append("uniform float alpha_hash_scale : hint_range(0.0, 2.0, 0.01);\n");
        c.Append("uniform ivec2 albedo_texture_size;\n");
        c.Append("uniform float point_size : hint_range(0.1, 128.0, 0.1);\n");
        c.Append($"\nuniform float roughness : hint_range(0.0, 1.0);\nuniform sampler2D texture_metallic : hint_default_white, {tf};\nuniform vec4 metallic_texture_channel;\n");
        var hint = s.RoughnessChannel switch
        {
            StandardShaderSpec.Channel.Red => "hint_roughness_r",
            StandardShaderSpec.Channel.Green => "hint_roughness_g",
            StandardShaderSpec.Channel.Blue => "hint_roughness_b",
            StandardShaderSpec.Channel.Alpha => "hint_roughness_a",
            _ => "hint_roughness_gray",
        };
        c.Append($"uniform sampler2D texture_roughness : {hint}, {tf};\n");
        c.Append("\nuniform float specular : hint_range(0.0, 1.0, 0.01);\nuniform float metallic : hint_range(0.0, 1.0, 0.01);\n");
        if (s.Emission)
            c.Append($"\nuniform sampler2D texture_emission : source_color, hint_default_black, {tf};\nuniform vec4 emission : source_color;\nuniform float emission_energy : hint_range(0.0, 100.0, 0.01);\n");
        if (s.NormalMap)
            c.Append($"\nuniform sampler2D texture_normal : hint_roughness_normal, {tf};\nuniform float normal_scale : hint_range(-16.0, 16.0);\n");
        if (s.AmbientOcclusion)
            c.Append($"\nuniform sampler2D texture_ambient_occlusion : hint_default_white, {tf};\nuniform vec4 ao_texture_channel;\nuniform float ao_light_affect : hint_range(0.0, 1.0, 0.01);\n");
        c.Append("\nuniform vec3 uv1_scale;\nuniform vec3 uv1_offset;\nuniform vec3 uv2_scale;\nuniform vec3 uv2_offset;\n");

        c.Append("\nvoid vertex() {");
        if (s.SrgbVertexColor)
            c.Append(@"
	// Vertex Color is sRGB: Enabled
	if (!OUTPUT_IS_SRGB) {
		COLOR.rgb = mix(
				pow((COLOR.rgb + vec3(0.055)) * (1.0 / (1.0 + 0.055)), vec3(2.4)),
				COLOR.rgb * (1.0 / 12.92),
				lessThan(COLOR.rgb, vec3(0.04045)));
	}
");
        if (s.Shading == StandardShaderSpec.ShadingKind.PerVertex)
            c.Append("\n	// Shading Mode: Per Vertex\n	ROUGHNESS = roughness;\n");
        c.Append("\n	UV = UV * uv1_scale.xy + uv1_offset.xy;\n");
        c.Append("}\n");

        c.Append("\nvoid fragment() {");
        c.Append("\n	vec2 base_uv = UV;\n");
        if ((s.AmbientOcclusion && s.AoOnUv2) || (s.Emission && s.EmissionOnUv2)) c.Append("	vec2 base_uv2 = UV2;\n");
        c.Append("\n	vec4 albedo_tex = texture(texture_albedo, base_uv);\n");
        if (s.AlbedoForceSrgb)
            c.Append(@"
	// Albedo Texture Force sRGB: Enabled
	albedo_tex.rgb = mix(
			pow((albedo_tex.rgb + vec3(0.055)) * (1.0 / (1.0 + 0.055)), vec3(2.4)),
			albedo_tex.rgb.rgb * (1.0 / 12.92),
			lessThan(albedo_tex.rgb, vec3(0.04045)));
");
        if (s.AlbedoFromVertexColor) c.Append("\n	// Vertex Color Use as Albedo: Enabled\n	albedo_tex *= COLOR;\n\n");
        c.Append("	ALBEDO = albedo.rgb * albedo_tex.rgb;\n");
        c.Append("\n	float metallic_tex = dot(texture(texture_metallic, base_uv), metallic_texture_channel);\n");
        c.Append("	METALLIC = metallic_tex * metallic;\n	SPECULAR = specular;\n");
        c.Append("\n	vec4 roughness_texture_channel = " + ChannelMask(s.RoughnessChannel) + ";\n");
        c.Append("	float roughness_tex = dot(texture(texture_roughness, base_uv), roughness_texture_channel);\n");
        c.Append("	ROUGHNESS = roughness_tex * roughness;\n");
        if (s.NormalMap)
            c.Append("\n	// Normal Map: Enabled\n	NORMAL_MAP = texture(texture_normal, base_uv).rgb;\n	NORMAL_MAP_DEPTH = normal_scale;\n");
        if (s.Emission)
        {
            c.Append("\n	// Emission: Enabled\n");
            c.Append(s.EmissionOnUv2 ? "	vec3 emission_tex = texture(texture_emission, base_uv2).rgb;\n"
                                     : "	vec3 emission_tex = texture(texture_emission, base_uv).rgb;\n");
            c.Append(s.EmissionAdd ? "	// Emission Operator: Add\n	EMISSION = (emission.rgb + emission_tex) * emission_energy;\n"
                                   : "	// Emission Operator: Multiply\n	EMISSION = (emission.rgb * emission_tex) * emission_energy;\n");
        }
        if (s.Transparency != StandardShaderSpec.TransparencyMode.Disabled || s.ShadowToOpacity)
            c.Append("	ALPHA *= albedo.a * albedo_tex.a;\n");
        if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaHash) c.Append("	ALPHA_HASH_SCALE = alpha_hash_scale;\n");
        else if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor)
            c.Append("	ALPHA_SCISSOR_THRESHOLD = alpha_scissor_threshold;\n");
        if (s.AmbientOcclusion)
        {
            c.Append("\n	// Ambient Occlusion: Enabled\n");
            c.Append(s.AoOnUv2 ? "	AO = dot(texture(texture_ambient_occlusion, base_uv2), ao_texture_channel);\n"
                               : "	AO = dot(texture(texture_ambient_occlusion, base_uv), ao_texture_channel);\n");
            c.Append("	AO_LIGHT_AFFECT = ao_light_affect;\n");
        }
        c.Append("}\n");
        return c.ToString();
    }

    /// <summary><c>_get_texture_mask</c>: the channel as the vec4 a texel is dotted with.</summary>
    public static string ChannelMask(StandardShaderSpec.Channel ch) => ch switch
    {
        StandardShaderSpec.Channel.Red => "vec4(1.0, 0.0, 0.0, 0.0)",
        StandardShaderSpec.Channel.Green => "vec4(0.0, 1.0, 0.0, 0.0)",
        StandardShaderSpec.Channel.Blue => "vec4(0.0, 0.0, 1.0, 0.0)",
        StandardShaderSpec.Channel.Alpha => "vec4(0.0, 0.0, 0.0, 1.0)",
        _ => "vec4(0.333333, 0.333333, 0.333333, 0.0)",
    };

    /// <summary>The channel mask as numbers (the engine's <c>_get_texture_mask</c>, for <c>metallic/ao_texture_channel</c>).</summary>
    public static (double X, double Y, double Z, double W) ChannelVector(StandardShaderSpec.Channel ch) => ch switch
    {
        StandardShaderSpec.Channel.Red => (1, 0, 0, 0),
        StandardShaderSpec.Channel.Green => (0, 1, 0, 0),
        StandardShaderSpec.Channel.Blue => (0, 0, 1, 0),
        StandardShaderSpec.Channel.Alpha => (0, 0, 0, 1),
        _ => (0.3333333, 0.3333333, 0.3333333, 0),
    };

    /// <summary>
    /// The uniform names <see cref="Generate"/> declares for <paramref name="s"/>, in order — what the Godot side
    /// feeds and the check counts (<c>Shader.GetShaderUniformList</c>).
    /// </summary>
    public static List<string> Uniforms(StandardShaderSpec s)
    {
        var u = new List<string> { "albedo", "texture_albedo" };
        if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor) u.Add("alpha_scissor_threshold");
        else if (s.Transparency == StandardShaderSpec.TransparencyMode.AlphaHash) u.Add("alpha_hash_scale");
        u.AddRange(new[] { "albedo_texture_size", "point_size", "roughness", "texture_metallic", "metallic_texture_channel",
                           "texture_roughness", "specular", "metallic" });
        if (s.Emission) u.AddRange(new[] { "texture_emission", "emission", "emission_energy" });
        if (s.NormalMap) u.AddRange(new[] { "texture_normal", "normal_scale" });
        if (s.AmbientOcclusion) u.AddRange(new[] { "texture_ambient_occlusion", "ao_texture_channel", "ao_light_affect" });
        u.AddRange(new[] { "uv1_scale", "uv1_offset", "uv2_scale", "uv2_offset" });
        return u;
    }
}
