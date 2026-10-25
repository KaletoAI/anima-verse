using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using Godot;

namespace AnimaNative.World;

/// <summary>The look of one recipe primitive, decided like <c>plateMaterial</c>/<c>wallMaterial</c>/<c>extraMaterial</c>.</summary>
public readonly record struct RecipeLook(
    string Color, string TextureKind, bool FloorChain, double Opacity, bool DoubleSided,
    double Roughness, double Metalness, bool WallCull)
{
    public string Key => string.Create(CultureInfo.InvariantCulture,
        $"{Color}|{TextureKind}|{FloorChain}|{Opacity:0.###}|{DoubleSided}|{Roughness:0.###}|{Metalness:0.###}|{WallCull}");
}

/// <summary>
/// The materials of the scene-recipe primitives (client3d/src/scene/sceneRecipe.ts, "Materials for the shared
/// primitive builders"), as ONE spatial shader in four variants (opaque/translucent × one/both sides):
///
///   • a texture kind the library has LOADED → the tiled image (white × map, three's <c>map</c> branch of
///     <c>surfaceMaterial</c>); UVs are in tile units already (plates: outline metres / size_m, walls and
///     extras: the face's own metres / size_m, <c>applyWorldScaleWallUVs</c>);
///   • else the payload's style colour (<c>hex()</c>, unusable → white);
///   • roughness/metalness from the kind's <c>material</c> declaration, else matte 0.85 / 0.02; glass 0.3,
///     door leaf 0.75 (<c>std()</c>);
///   • translucent = <c>opacity &lt; 1</c> (glass, ghosted upper storeys, the lift cabin);
///   • <c>wall_cull</c>: the open location's outline walls (<c>applyWallCulling</c>) — every vertex carries its
///     wall's midpoint and outward normal (location frame) in <c>CUSTOM0</c>; with the camera on the outer side
///     all of them collapse to one point, which drops the whole wall exactly like <c>mesh.visible = false</c>
///     without a node per wall.
/// </summary>
public sealed class RecipeMaterials
{
    private static readonly Dictionary<string, Shader> Shaders = new();
    private readonly Dictionary<string, Material> _cache = new();
    private readonly SurfaceLibrary? _library;

    public RecipeMaterials(SurfaceLibrary? library) => _library = library;

    public int Count => _cache.Count;

    public static string Code(bool translucent, bool doubleSided) => $@"shader_type spatial;
render_mode blend_mix, {(translucent ? "depth_draw_always" : "depth_draw_opaque")}, {(doubleSided ? "cull_disabled" : "cull_back")}, diffuse_lambert, specular_schlick_ggx;
uniform vec4 albedo_color : source_color = vec4(1.0);
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float has_tex = 0.0;
uniform float roughness_v = 0.85;
uniform float metallic_v = 0.02;
uniform float opacity = 1.0;
uniform float wall_cull = 0.0;
void vertex() {{
	// CUSTOM0 = (mid.x, mid.z, normal.x, normal.z) in the location frame; (0, 0, 0, 0) on everything that
	// is not an outline wall, which can never pass the test below.
	if (wall_cull > 0.5) {{
		vec3 cam = (inverse(MODEL_MATRIX) * vec4(CAMERA_POSITION_WORLD, 1.0)).xyz;
		if ((cam.x - CUSTOM0.x) * CUSTOM0.z + (cam.z - CUSTOM0.y) * CUSTOM0.w > 0.0) VERTEX = vec3(0.0);
	}}
}}
void fragment() {{
	vec4 c = has_tex > 0.5 ? texture(albedo_tex, UV) : albedo_color;
	ALBEDO = c.rgb;
	ROUGHNESS = roughness_v;
	METALLIC = metallic_v;
{(translucent ? "	ALPHA = opacity;" : "")}
}}
";

    public static Shader ShaderFor(bool translucent, bool doubleSided)
    {
        string key = $"{translucent}|{doubleSided}";
        if (!Shaders.TryGetValue(key, out var s)) Shaders[key] = s = new Shader { Code = Code(translucent, doubleSided) };
        return s;
    }

    public Material Get(RecipeLook look)
    {
        if (_cache.TryGetValue(look.Key, out var m)) return m;
        bool translucent = look.Opacity < 1;
        var shader = ShaderFor(translucent, look.DoubleSided);
        var surf = look.TextureKind.Length > 0 ? _library?.SurfaceFor(look.TextureKind, look.FloorChain) : null;
        if (ShaderSafety.Ok(shader, $"recipe[{(translucent ? "translucent" : "opaque")}{(look.DoubleSided ? ",both-sides" : "")}]"))
        {
            var sm = new ShaderMaterial { Shader = shader };
            sm.SetShaderParameter("albedo_color", Hex(look.Color));
            if (surf is { } t)
            {
                sm.SetShaderParameter("albedo_tex", t.Texture);
                sm.SetShaderParameter("has_tex", 1f);
            }
            sm.SetShaderParameter("roughness_v", (float)look.Roughness);
            sm.SetShaderParameter("metallic_v", (float)look.Metalness);
            sm.SetShaderParameter("opacity", (float)look.Opacity);
            sm.SetShaderParameter("wall_cull", look.WallCull ? 1f : 0f);
            m = sm;
        }
        else
        {
            // Fallback: the plain standard material (no wall culling — a culled wall then stays standing).
            m = new StandardMaterial3D
            {
                AlbedoColor = surf is null ? Hex(look.Color) : Colors.White,
                AlbedoTexture = surf?.Texture,
                Roughness = (float)look.Roughness,
                Metallic = (float)look.Metalness,
                Transparency = translucent ? BaseMaterial3D.TransparencyEnum.Alpha : BaseMaterial3D.TransparencyEnum.Disabled,
                CullMode = look.DoubleSided ? BaseMaterial3D.CullModeEnum.Disabled : BaseMaterial3D.CullModeEnum.Back,
            };
            if (translucent) ((StandardMaterial3D)m).AlbedoColor = ((StandardMaterial3D)m).AlbedoColor with { A = (float)look.Opacity };
        }
        _cache[look.Key] = m;
        return m;
    }

    /// <summary>The world tile size of the look's LOADED texture (<c>surfaceFor(...).sizeM</c>), 0 when it wears its colour.</summary>
    public double TileM(RecipeLook look)
        => look.TextureKind.Length > 0 && _library?.SurfaceFor(look.TextureKind, look.FloorChain) is { } t ? t.SizeM : 0;

    /// <summary><c>hex()</c> of sceneRecipe.ts: '#rrggbb' → colour, unusable/missing → white.</summary>
    public static Color Hex(string? css)
    {
        var s = (css ?? "").Replace("#", "");
        return int.TryParse(s, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out int v)
            ? new Color(((v >> 16) & 255) / 255f, ((v >> 8) & 255) / 255f, (v & 255) / 255f)
            : Colors.White;
    }

    // ── The decisions of the three material functions ────────────────────────

    private double SpecNum(string kind, string field, double fallback)
    {
        if (_library?.MaterialSpec(kind) is not { } spec) return fallback;
        return spec.TryGetProperty(field, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : fallback;
    }

    private string SpecClass(string kind)
        => _library?.MaterialSpec(kind) is { } spec && spec.TryGetProperty("class", out var c)
           && c.ValueKind == JsonValueKind.String ? c.GetString() ?? "matte" : "matte";

    /// <summary><c>surfaceMaterial</c>'s roughness/metalness defaults per class.</summary>
    private (double R, double M) Finish(string kind)
    {
        var cls = SpecClass(kind);
        bool rippled = cls is "water" or "ice";
        return (SpecNum(kind, "roughness", rippled ? 0.08 : cls == "gloss" ? 0.25 : 0.85),
                SpecNum(kind, "metalness", rippled ? 0.15 : 0.02));
    }

    private static double StyleNum(ScenePayload s, string key, double fallback)
        => s.StyleNumbers.TryGetValue(key, out var v) ? v : fallback;

    private static string StyleStr(ScenePayload s, string key, string fallback = "")
        => s.Style.TryGetValue(key, out var v) ? v : fallback;

    /// <summary><c>plateMaterial</c>: floor texture chain, else <c>floor_color</c>; upper storeys ghosted; a bare surface both ways.</summary>
    public RecipeLook Plate(ScenePlate p, ScenePayload s, double? opacityOverride = null)
    {
        bool upper = p.OpacityRole == "upper";
        double opacity = opacityOverride ?? (upper ? StyleNum(s, "upper_floor_opacity", 1) : 1);
        var (r, m) = Finish(p.TextureKind);
        return new RecipeLook(StyleStr(s, "floor_color"), p.TextureKind, true, opacity, !(p.Thickness > 0), r, m, false);
    }

    /// <summary><c>wallMaterial</c>: glass pane, door leaf, else the wall texture or <c>wall_color</c>.</summary>
    public RecipeLook Wall(SceneWall w, ScenePayload s, bool wallCull, double? opacityOverride = null)
    {
        if (w.Glass)
            return new RecipeLook(StyleStr(s, "glass_color"), "", false, StyleNum(s, "glass_opacity", 0.25), false, 0.3, 0.02, wallCull);
        if (w.Leaf)
            return new RecipeLook(StyleStr(s, "door_color", "#4a3a2e"), "", false, opacityOverride ?? 1, false, 0.75, 0.02, wallCull);
        bool upper = w.OpacityRole == "upper";
        double opacity = opacityOverride ?? (upper ? StyleNum(s, "upper_wall_opacity", 1) : 1);
        var (r, m) = Finish(w.TextureKind);
        return new RecipeLook(StyleStr(s, "wall_color"), w.TextureKind, false, opacity, false, r, m, wallCull);
    }

    /// <summary><c>extraMaterial</c>: glass / stair / pad / cabin / frame colours and opacities; a textured extra tiles like a wall.</summary>
    public RecipeLook Extra(SceneExtra e, ScenePayload s)
    {
        bool glass = e.Kind.EndsWith("_glass", StringComparison.Ordinal);
        bool cabin = e.Kind == "elevator_cabin";
        bool stair = e.Kind.StartsWith("stair_", StringComparison.Ordinal);
        string color = glass ? StyleStr(s, "glass_color")
            : stair ? StyleStr(s, "stair_color", "#8a7a66")
            : e.Kind == "elevator_pad" ? StyleStr(s, "elevator_pad_color")
            : cabin ? StyleStr(s, "elevator_cabin_color") : StyleStr(s, "elevator_frame_color");
        double opacity = glass ? StyleNum(s, "elevator_glass_opacity", StyleNum(s, "glass_opacity", 0.22))
            : cabin ? StyleNum(s, "elevator_cabin_opacity", 1) : 1;
        string kind = glass ? "" : e.TextureKind;
        var (r, m) = kind.Length > 0 && _library?.SurfaceFor(kind, false) is not null ? Finish(kind) : (glass ? 0.3 : 0.85, 0.02);
        return new RecipeLook(color, kind, false, opacity, false, r, m, false);
    }

    /// <summary><c>placeholderMaterial</c>: matte, half translucent grey.</summary>
    public static RecipeLook Placeholder => new("#9a9a9a", "", false, 0.5, false, 0.9, 0.02, false);
}
