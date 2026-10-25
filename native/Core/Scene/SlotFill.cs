using System.Collections.Generic;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>What a texture slot does to one material: <c>image</c> hangs a picture, <c>glass</c> / <c>mirror</c> apply that preset.</summary>
public sealed record SlotFillResult(string Slot, string Kind, string Image);

/// <summary>
/// The decision half of the texture slots (§ B2 v5), a port of packages/scene-render/src/slotMaterials.ts
/// (<c>slotNameOf</c>, <c>slotFill</c>, <c>GLASS_PRESET</c>, <c>MATERIAL_PRESETS</c>), checked against
/// shared/test-vectors/slot_materials.json (hand derivations in scripts/smoke_slot_materials.mjs).
/// </summary>
public static class SlotFill
{
    /// <summary><c>MATERIAL_PRESETS</c>: the looks a material slot can be set to.</summary>
    public static readonly string[] MaterialPresets = { "glass", "mirror" };

    /// <summary><c>GLASS_PRESET</c>: what "glass" MEANS (transmission only on a material that has the field).</summary>
    public const double GlassOpacity = 0.3, GlassRoughness = 0.06, GlassMetalness = 0, GlassTransmission = 0.85;

    /// <summary>JS <c>trim()</c>'s white space (the same set as <c>String.prototype.trim</c>).</summary>
    private static string Trim(string s)
    {
        int a = 0, b = s.Length;
        while (a < b && Overview.JsSemantics.IsWhiteSpace(s[a])) a++;
        while (b > a && Overview.JsSemantics.IsWhiteSpace(s[b - 1])) b--;
        return s.Substring(a, b - a);
    }

    /// <summary><c>slotNameOf</c>: the name trimmed and lower-cased, ONE leading <c>slot_</c> taken off and trimmed again.</summary>
    public static string SlotNameOf(string? raw)
    {
        var key = Trim(raw ?? "").ToLowerInvariant();
        return key.StartsWith("slot_", System.StringComparison.Ordinal) ? Trim(key.Substring(5)) : key;
    }

    /// <summary>
    /// <c>slotFill</c>: the fill (if any) the payload's <c>slots</c> give the material named <paramref name="materialName"/>;
    /// keys match trimmed and case-insensitively (the last equal key wins, as the browser's Map does), an image wins
    /// over a preset, a preset must be one of <see cref="MaterialPresets"/>.
    /// </summary>
    public static SlotFillResult? Fill(string? materialName, IReadOnlyDictionary<string, SceneSlotValue>? slots)
    {
        var slot = SlotNameOf(materialName);
        SceneSlotValue? value = null;
        if (slots is not null)
            foreach (var (name, v) in slots)
            {
                var key = Trim(name ?? "").ToLowerInvariant();
                if (key.Length > 0 && v is not null && key == slot) value = v;
            }
        if (value is null) return null;
        var image = Trim(value.Image ?? "");
        if (image.Length > 0) return new SlotFillResult(slot, "image", image);
        var preset = Trim(value.Preset ?? "").ToLowerInvariant();
        if (System.Array.IndexOf(MaterialPresets, preset) < 0) return null;
        return new SlotFillResult(slot, preset, "");
    }
}
