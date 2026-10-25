using System;
using System.Text.Json;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// The look parameters of a recipe primitive. Fields the TS look leaves out take three's
/// <c>MeshStandardMaterial</c> defaults as <c>std()</c> sets them (opacity 1, opaque, front side, roughness 0.85,
/// metalness 0.02). <see cref="Side"/>: 0 front, 2 double (three's FrontSide / DoubleSide).
/// </summary>
public readonly record struct RecipeLookParams(int Color, bool Transparent, double Opacity, int Side, double Roughness, double Metalness);

/// <summary>A material class finish (<c>surfaceFinish</c>); <see cref="EmissiveIntensity"/> only for <c>glow</c>.</summary>
public readonly record struct SurfaceFinishResult(double Roughness, double Metalness, double? EmissiveIntensity);

/// <summary>The metalness neutralisation of a GLB material (<c>neutralizeLook</c>).</summary>
public readonly record struct NeutralizedLook(double Metalness, double? EnvMapIntensity);

/// <summary>
/// The pure look decisions of the recipe primitives (client3d/src/scene/materialLooks.ts) and the class finish
/// of the surface library (<c>surfaceFinish</c>, packages/scene-render/src/materials.ts), checked against
/// shared/test-vectors/scene_models.json [P]/[W]/[E]/[X]/[F]/[N]. Textures and renderer objects stay with the caller.
/// </summary>
public static class MaterialLooks
{
    private const double StdRoughness = 0.85, StdMetalness = 0.02;

    /// <summary><c>recipeHex</c>: <c>parseInt(value.replace('#', ''), 16)</c>, unusable → white (0xffffff).</summary>
    public static int RecipeHex(string? value)
    {
        var s = value ?? "";
        int hash = s.IndexOf('#');
        if (hash >= 0) s = s.Remove(hash, 1); // String.replace with a string pattern replaces the FIRST match
        double n = Js.ParseIntHex(s);
        return double.IsFinite(n) ? unchecked((int)(long)n) : 0xffffff;
    }

    private static string? Str(ScenePayload s, string key) => s.Style.TryGetValue(key, out var v) ? v : null;

    private static double? Num(ScenePayload s, string key) => s.StyleNumbers.TryGetValue(key, out var v) ? v : null;

    /// <summary><c>plateLook</c>: the floor colour; an upper storey translucent at its ghost; a body front side, a bare face both.</summary>
    public static RecipeLookParams PlateLook(ScenePlate plate, ScenePayload style)
    {
        bool upper = plate.OpacityRole == "upper";
        return new RecipeLookParams(RecipeHex(Str(style, "floor_color")), upper,
            upper ? Num(style, "upper_floor_opacity") ?? 1 : 1, plate.Thickness > 0 ? 0 : 2, StdRoughness, StdMetalness);
    }

    /// <summary><c>wallLook</c>: a glass pane, a door leaf, else the wall colour (an upper storey translucent).</summary>
    public static RecipeLookParams WallLook(SceneWall wall, ScenePayload style)
    {
        if (wall.Glass)
            return new RecipeLookParams(RecipeHex(Str(style, "glass_color")), true, Num(style, "glass_opacity") ?? 0.25, 0, 0.3, 0.02);
        if (wall.Leaf)
            return new RecipeLookParams(RecipeHex(Str(style, "door_color") ?? "#4a3a2e"), false, 1, 0, 0.75, 0.02);
        bool upper = wall.OpacityRole == "upper";
        return new RecipeLookParams(RecipeHex(Str(style, "wall_color")), upper,
            upper ? Num(style, "upper_wall_opacity") ?? 1 : 1, 0, StdRoughness, StdMetalness);
    }

    /// <summary><c>extraLook</c>: glass / stair / pad / cabin / frame colours and opacities; translucent below 1.</summary>
    public static RecipeLookParams ExtraLook(SceneExtra extra, ScenePayload style)
    {
        bool glass = extra.Kind.EndsWith("_glass", StringComparison.Ordinal);
        bool cabin = extra.Kind == "elevator_cabin";
        string? color = glass ? Str(style, "glass_color")
            : extra.Kind.StartsWith("stair_", StringComparison.Ordinal) ? Str(style, "stair_color") ?? "#8a7a66"
            : extra.Kind == "elevator_pad" ? Str(style, "elevator_pad_color")
            : cabin ? Str(style, "elevator_cabin_color") : Str(style, "elevator_frame_color");
        double opacity = glass ? Num(style, "elevator_glass_opacity") ?? Num(style, "glass_opacity") ?? 0.22
            : cabin ? Num(style, "elevator_cabin_opacity") ?? 1 : 1;
        return new RecipeLookParams(RecipeHex(color), opacity < 1, opacity, 0, glass ? 0.3 : 0.85, 0.02);
    }

    /// <summary><c>placeholderLook</c>: matte, half translucent grey.</summary>
    public static RecipeLookParams PlaceholderLook() => new(0x9a9a9a, true, 0.5, 0, 0.9, 0.02);

    /// <summary><c>neutralizeLook</c>: untextured metal above 0.5 goes to 0; textured metal keeps it (env 0.7 when one is set).</summary>
    public static NeutralizedLook NeutralizeLook(double metalness, bool hasMetalnessMap, bool hasEnvironment)
        => hasMetalnessMap
            ? hasEnvironment ? new NeutralizedLook(metalness, 0.7) : new NeutralizedLook(metalness, null)
            : new NeutralizedLook(metalness > 0.5 ? 0 : metalness, null);

    /// <summary><c>surfaceFinish</c> of a <c>material</c> declaration: class defaults (matte / gloss / water / ice / glow), declared numbers win.</summary>
    public static SurfaceFinishResult SurfaceFinish(string? cls, double? roughness, double? metalness, double? glow)
    {
        var c = string.IsNullOrEmpty(cls) ? "matte" : cls;
        bool rippled = c is "water" or "ice";
        return new SurfaceFinishResult(roughness ?? (rippled ? 0.08 : c == "gloss" ? 0.25 : 0.85),
                                       metalness ?? (rippled ? 0.15 : 0.02),
                                       c == "glow" ? glow ?? 1 : null);
    }

    /// <summary><see cref="SurfaceFinish(string?, double?, double?, double?)"/> of the library's JSON declaration (null = matte).</summary>
    public static SurfaceFinishResult SurfaceFinish(JsonElement? spec)
    {
        if (spec is not { ValueKind: JsonValueKind.Object } s) return SurfaceFinish(null, null, null, null);
        string? Cls() => s.TryGetProperty("class", out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
        double? N(string k) => s.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;
        return SurfaceFinish(Cls(), N("roughness"), N("metalness"), N("glow"));
    }
}
