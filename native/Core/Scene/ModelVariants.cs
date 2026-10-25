using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// Which mesh a placement shows — <c>pickVariant</c> / <c>pickModelVariant</c> of
/// packages/scene-render/src/types.ts, checked against shared/test-vectors/scene_models.json [M].
/// </summary>
public static class ModelVariants
{
    /// <summary>The tiers in fallback order (<c>MODEL_TIERS</c>).</summary>
    public static readonly string[] Tiers = { "full", "low" };

    /// <summary><c>pickVariant</c>: the wanted tier, then full, low, then any key; the first non-empty URL, else "".</summary>
    public static string PickVariant(IReadOnlyDictionary<string, string>? variants, string tier = "full")
    {
        if (variants is null) return "";
        foreach (var t in new[] { tier }.Concat(Tiers).Concat(variants.Keys))
            if (variants.TryGetValue(t, out var url) && !string.IsNullOrEmpty(url)) return url;
        return "";
    }

    /// <summary>
    /// <c>pickModelVariant</c>: the model variant first (index MODULO the count; a non-finite index is 0), then
    /// the tier. <c>list[i] || spec.variants</c>: only a MISSING entry (null, or an index that is not a whole
    /// number) falls back to the plain variants — an empty map is truthy in JS and answers "".
    /// </summary>
    public static string PickModelVariant(SceneModelSpec spec, string tier = "full")
    {
        var list = spec.ModelVariants;
        if (list is not { Count: > 0 }) return PickVariant(spec.Variants, tier);
        int n = list.Count;
        double raw = spec.Variant;
        double i = double.IsFinite(raw) ? ((raw % n) + n) % n : 0;
        var entry = i == Math.Floor(i) ? list[(int)i] : null;
        return PickVariant(entry ?? spec.Variants, tier);
    }
}
