using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The look of one recipe primitive, decided like <c>plateMaterial</c>/<c>wallMaterial</c>/<c>extraMaterial</c> —
/// colour, opacity, side and finish come from the Core ports (<see cref="MaterialLooks"/>), the texture choice
/// and the view overrides (storey opacity, wall cull) from here.
/// </summary>
public readonly record struct RecipeLook(
    int Color, string TextureKind, bool FloorChain, double Opacity, bool DoubleSided,
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
///   • else the payload's style colour (<see cref="MaterialLooks.RecipeHex"/>, unusable → white);
///   • roughness/metalness from the kind's <c>material</c> declaration (<see cref="MaterialLooks.SurfaceFinish(System.Text.Json.JsonElement?)"/>),
///     else the look's own (matte 0.85 / 0.02, glass 0.3, door leaf 0.75);
///   • translucent = <c>opacity &lt; 1</c> (glass, ghosted upper storeys, the lift cabin); ALPHA is MULTIPLIED
///     (<c>ALPHA *= opacity</c>, like StandardMaterial3D's own code), because Godot starts ALPHA at the instance's
///     fade (<see cref="GeometryInstance3D.Transparency"/>) — the crossfade and the neighbour occlusion ride on it;
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
// Task 51: hover materials clone this value and share this shader.
uniform float hover_light = 0.0;
// Per mesh instance: whether the wall cull runs right now. The interior's meshes keep 1 (they are only shown with
// the interior up); an outdoor mesh gets 0 while its location is closed and 1 once the crossfade passes 0.03
// (applyWallCulling runs only then) — LocationFade sets it, no material clone per location.
instance uniform float cull_active = 1.0;
void vertex() {{
	// CUSTOM0 = (mid.x, mid.z, normal.x, normal.z) in the location frame; (0, 0, 0, 0) on everything that
	// is not an outline wall, which can never pass the test below.
	if (wall_cull > 0.5 && cull_active > 0.5) {{
		vec3 cam = (inverse(MODEL_MATRIX) * vec4(CAMERA_POSITION_WORLD, 1.0)).xyz;
		// The GPU twin of SceneView.WallVisible (scene_view.json [W]): hidden when (cam - mid) . n > 0.
		if ((cam.x - CUSTOM0.x) * CUSTOM0.z + (cam.z - CUSTOM0.y) * CUSTOM0.w > 0.0) VERTEX = vec3(0.0);
	}}
}}
void fragment() {{
	vec4 c = has_tex > 0.5 ? texture(albedo_tex, UV) : albedo_color;
	ALBEDO = c.rgb;
	EMISSION = c.rgb * hover_light;
	ROUGHNESS = roughness_v;
	METALLIC = metallic_v;
{(translucent ? "	ALPHA *= opacity;" : "")}
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
                DiffuseMode = BaseMaterial3D.DiffuseModeEnum.Lambert,
            };
            if (translucent) ((StandardMaterial3D)m).AlbedoColor = ((StandardMaterial3D)m).AlbedoColor with { A = (float)look.Opacity };
        }
        _cache[look.Key] = m;
        return m;
    }

    /// <summary>The world tile size of the look's LOADED texture (<c>surfaceFor(...).sizeM</c>), 0 when it wears its colour.</summary>
    public double TileM(RecipeLook look)
        => look.TextureKind.Length > 0 && _library?.SurfaceFor(look.TextureKind, look.FloorChain) is { } t ? t.SizeM : 0;

    /// <summary>An integer RGB (<see cref="MaterialLooks.RecipeHex"/>) as a Godot colour.</summary>
    public static Color Hex(int v) => new(((v >> 16) & 255) / 255f, ((v >> 8) & 255) / 255f, (v & 255) / 255f);

    /// <summary>The finish of a textured kind: its library declaration through <see cref="MaterialLooks.SurfaceFinish(System.Text.Json.JsonElement?)"/>.</summary>
    private (double R, double M) Finish(string kind)
    {
        var f = MaterialLooks.SurfaceFinish(_library?.MaterialSpec(kind));
        return (f.Roughness, f.Metalness);
    }

    /// <summary><c>plateMaterial</c>: floor texture chain, else <c>floor_color</c>; upper storeys ghosted; a bare surface both ways.</summary>
    public RecipeLook Plate(ScenePlate p, ScenePayload s, double? opacityOverride = null)
    {
        var look = MaterialLooks.PlateLook(p, s);
        var (r, m) = Finish(p.TextureKind);
        return new RecipeLook(look.Color, p.TextureKind, true, opacityOverride ?? look.Opacity, look.Side == 2, r, m, false);
    }

    /// <summary><c>wallMaterial</c>: glass pane, door leaf (their own look, never textured), else the wall texture or <c>wall_color</c>.</summary>
    public RecipeLook Wall(SceneWall w, ScenePayload s, bool wallCull, double? opacityOverride = null)
    {
        var look = MaterialLooks.WallLook(w, s);
        if (w.Glass)
            return new RecipeLook(look.Color, "", false, look.Opacity, false, look.Roughness, look.Metalness, wallCull);
        if (w.Leaf)
            return new RecipeLook(look.Color, "", false, opacityOverride ?? look.Opacity, false, look.Roughness, look.Metalness, wallCull);
        var (r, m) = Finish(w.TextureKind);
        return new RecipeLook(look.Color, w.TextureKind, false, opacityOverride ?? look.Opacity, false, r, m, wallCull);
    }

    /// <summary><c>extraMaterial</c>: glass / stair / pad / cabin / frame colours and opacities; a textured extra tiles like a wall.</summary>
    public RecipeLook Extra(SceneExtra e, ScenePayload s)
    {
        var look = MaterialLooks.ExtraLook(e, s);
        bool glass = e.Kind.EndsWith("_glass", StringComparison.Ordinal);
        string kind = glass ? "" : e.TextureKind;
        var (r, m) = kind.Length > 0 && _library?.SurfaceFor(kind, false) is not null ? Finish(kind) : (look.Roughness, look.Metalness);
        return new RecipeLook(look.Color, kind, false, look.Opacity, false, r, m, false);
    }

    /// <summary><c>placeholderMaterial</c>: matte, half translucent grey.</summary>
    public static RecipeLook Placeholder
    {
        get
        {
            var l = MaterialLooks.PlaceholderLook();
            return new RecipeLook(l.Color, "", false, l.Opacity, false, l.Roughness, l.Metalness, false);
        }
    }
}
