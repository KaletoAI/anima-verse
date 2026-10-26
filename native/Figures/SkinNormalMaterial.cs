using System;
using System.Collections.Generic;
using System.Text;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The skinned-normal correction as a material (packages/scene-render/src/skinnedNormals.ts, <see cref="SkinNormals"/>):
/// a figure whose secondary motion scales bones non-uniformly wears, per skinned surface, a <see cref="ShaderMaterial"/>
/// that draws the imported <see cref="BaseMaterial3D"/>'s look and turns Godot's stock skinned normal normalize(M n)
/// into the browser's normalize(M⁻ᵀ n) — (M Mᵀ)⁻¹ n' in <c>vertex()</c>, M blended from the per-bind linear parts in
/// <c>skin_linear</c> by the vertex's BONE_INDICES / BONE_WEIGHTS (the same four influences Godot skinned with).
///
/// Only the look the figure GLBs use is carried (verified on the demo figures: base colour texture, metallic-roughness
/// texture with metalness 0 after <c>Dielectric</c>, double sided): albedo colour × texture (× vertex colour), roughness
/// factor × texture channel, metallic factor × texture channel, specular, normal map, UV1 scale/offset, the cull mode,
/// Lambert diffuse and no received shadows (<see cref="Gltf.GlbLoader.BrowserLook"/>). A material with anything else
/// (transparency, emission, unshaded, triplanar, …) is left as it is — its normals stay stock (<see cref="TryConvert"/>
/// returns null) — and so is an 8-weight surface or a skin with more than <see cref="MaxBinds"/> binds.
/// </summary>
public static class SkinNormalMaterial
{
    /// <summary>The uniform array's length (std140: 48 bytes per mat3 → 6 KiB per material).</summary>
    public const int MaxBinds = 128;
    public const string SkinParam = "skin_linear";

    private static readonly Dictionary<string, Shader> Shaders = new();

    /// <summary>The shader text for one cull mode / vertex-colour / normal-map combination (also the check parses it).</summary>
    public static string Code(BaseMaterial3D.CullModeEnum cull, bool vertexColor, bool normalMap)
    {
        string cullMode = cull switch
        {
            BaseMaterial3D.CullModeEnum.Disabled => "cull_disabled",
            BaseMaterial3D.CullModeEnum.Front => "cull_front",
            _ => "cull_back",
        };
        var sb = new StringBuilder();
        sb.Append("// Anima native: a figure surface with the browser's inverse-transpose skinned normals (skinnedNormals.ts).\n");
        sb.Append("shader_type spatial;\n");
        sb.Append($"render_mode blend_mix, depth_draw_opaque, {cullMode}, diffuse_lambert, specular_schlick_ggx, shadows_disabled;\n");
        sb.Append("uniform vec4 albedo : source_color = vec4(1.0);\n");
        sb.Append("uniform sampler2D texture_albedo : source_color, filter_linear_mipmap, repeat_enable;\n");
        sb.Append("uniform float roughness : hint_range(0.0, 1.0) = 1.0;\n");
        sb.Append("uniform sampler2D texture_roughness : hint_default_white, filter_linear_mipmap, repeat_enable;\n");
        sb.Append("uniform vec4 roughness_channel = vec4(0.0, 1.0, 0.0, 0.0);\n");
        sb.Append("uniform float metallic : hint_range(0.0, 1.0) = 0.0;\n");
        sb.Append("uniform sampler2D texture_metallic : hint_default_white, filter_linear_mipmap, repeat_enable;\n");
        sb.Append("uniform vec4 metallic_channel = vec4(0.0, 0.0, 1.0, 0.0);\n");
        sb.Append("uniform float specular : hint_range(0.0, 1.0) = 0.5;\n");
        if (normalMap)
        {
            sb.Append("uniform sampler2D texture_normal : hint_normal, filter_linear_mipmap, repeat_enable;\n");
            sb.Append("uniform float normal_scale = 1.0;\n");
        }
        sb.Append("uniform vec3 uv1_scale = vec3(1.0);\n");
        sb.Append("uniform vec3 uv1_offset = vec3(0.0);\n");
        sb.Append($"uniform mat3 {SkinParam}[{MaxBinds}];\n");
        sb.Append("void vertex() {\n");
        sb.Append("\tUV = UV * uv1_scale.xy + uv1_offset.xy;\n");
        // Godot skinned with m = Σ w·B (skeleton.glsl) and wrote normalize(m n); n ∝ m⁻¹ n', so m⁻ᵀ n ∝ (m mᵀ)⁻¹ n'.
        sb.Append($"\tmat3 m = {SkinParam}[BONE_INDICES.x] * BONE_WEIGHTS.x + {SkinParam}[BONE_INDICES.y] * BONE_WEIGHTS.y\n");
        sb.Append($"\t\t+ {SkinParam}[BONE_INDICES.z] * BONE_WEIGHTS.z + {SkinParam}[BONE_INDICES.w] * BONE_WEIGHTS.w;\n");
        sb.Append("\tif (abs(determinant(m)) > 1e-12) {\n");
        sb.Append("\t\tNORMAL = normalize(inverse(m * transpose(m)) * NORMAL);\n");
        sb.Append("\t}\n");
        sb.Append("}\n");
        sb.Append("void fragment() {\n");
        sb.Append("\tvec4 albedo_tex = texture(texture_albedo, UV);\n");
        sb.Append(vertexColor ? "\tALBEDO = albedo.rgb * albedo_tex.rgb * COLOR.rgb;\n" : "\tALBEDO = albedo.rgb * albedo_tex.rgb;\n");
        sb.Append("\tMETALLIC = dot(texture(texture_metallic, UV), metallic_channel) * metallic;\n");
        sb.Append("\tROUGHNESS = dot(texture(texture_roughness, UV), roughness_channel) * roughness;\n");
        sb.Append("\tSPECULAR = specular;\n");
        if (normalMap)
        {
            sb.Append("\tNORMAL_MAP = texture(texture_normal, UV).rgb;\n");
            sb.Append("\tNORMAL_MAP_DEPTH = normal_scale;\n");
        }
        sb.Append("}\n");
        return sb.ToString();
    }

    private static Shader ShaderFor(BaseMaterial3D.CullModeEnum cull, bool vertexColor, bool normalMap)
    {
        string key = $"{cull}|{vertexColor}|{normalMap}";
        if (!Shaders.TryGetValue(key, out var shader))
            Shaders[key] = shader = new Shader { Code = Code(cull, vertexColor, normalMap) };
        return shader;
    }

    /// <summary>Why <paramref name="m"/> cannot be carried (null = it can).</summary>
    public static string? Unsupported(BaseMaterial3D m)
    {
        if (m.Transparency != BaseMaterial3D.TransparencyEnum.Disabled) return "transparency";
        if (m.ShadingMode != BaseMaterial3D.ShadingModeEnum.PerPixel) return "shading mode";
        if (m.EmissionEnabled) return "emission";
        if (m.Uv1Triplanar) return "triplanar";
        if (m.RimEnabled || m.ClearcoatEnabled || m.AnisotropyEnabled || m.AOEnabled || m.HeightmapEnabled
            || m.SubsurfScatterEnabled || m.BacklightEnabled || m.RefractionEnabled || m.DetailEnabled)
            return "extra feature";
        if (m.BillboardMode != BaseMaterial3D.BillboardModeEnum.Disabled) return "billboard";
        return null;
    }

    private static Vector4 Channel(BaseMaterial3D.TextureChannel c) => c switch
    {
        BaseMaterial3D.TextureChannel.Red => new Vector4(1, 0, 0, 0),
        BaseMaterial3D.TextureChannel.Green => new Vector4(0, 1, 0, 0),
        BaseMaterial3D.TextureChannel.Blue => new Vector4(0, 0, 1, 0),
        BaseMaterial3D.TextureChannel.Alpha => new Vector4(0, 0, 0, 1),
        _ => new Vector4(0.333333f, 0.333333f, 0.333333f, 0),
    };

    /// <summary>The correcting twin of an imported material, or null when its look is not carried (see the class remarks).</summary>
    public static ShaderMaterial? TryConvert(BaseMaterial3D m)
    {
        if (Unsupported(m) is not null) return null;
        bool normalMap = m.NormalEnabled && m.NormalTexture is not null;
        var s = new ShaderMaterial { Shader = ShaderFor(m.CullMode, m.VertexColorUseAsAlbedo, normalMap) };
        s.SetShaderParameter("albedo", m.AlbedoColor);
        if (m.AlbedoTexture is { } at) s.SetShaderParameter("texture_albedo", at);
        s.SetShaderParameter("roughness", m.Roughness);
        if (m.RoughnessTexture is { } rt) s.SetShaderParameter("texture_roughness", rt);
        s.SetShaderParameter("roughness_channel", Channel(m.RoughnessTextureChannel));
        s.SetShaderParameter("metallic", m.Metallic);
        if (m.MetallicTexture is { } mt) s.SetShaderParameter("texture_metallic", mt);
        s.SetShaderParameter("metallic_channel", Channel(m.MetallicTextureChannel));
        s.SetShaderParameter("specular", m.MetallicSpecular);
        if (normalMap)
        {
            s.SetShaderParameter("texture_normal", m.NormalTexture!);
            s.SetShaderParameter("normal_scale", m.NormalScale);
        }
        s.SetShaderParameter("uv1_scale", m.Uv1Scale);
        s.SetShaderParameter("uv1_offset", m.Uv1Offset);
        s.RenderPriority = m.RenderPriority;
        return s;
    }

    /// <summary>Write the per-bind linear parts (column-major, <see cref="SkinNormals.PackColumns"/>).</summary>
    public static void SetSkin(ShaderMaterial material, Overview.Affine[] skin)
        => material.SetShaderParameter(SkinParam, SkinNormals.PackColumns(skin, MaxBinds));
}
