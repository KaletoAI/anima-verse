using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Tests.Vectors;

/// <summary>
/// The comparison of format <c>anima-test-vectors/1</c> (shared/test-vectors/README.md,
/// § Comparison) — the C# twin of <c>near()</c> in shared/test-vectors/vectors.mjs:
/// numbers within eps (an actual NaN/Infinity never matches), null only equals null,
/// -0 == 0, arrays elementwise with equal length, objects only on the expectation's keys.
/// Also the number readers the dispatch adapters use, because a <see cref="JsonValue"/>
/// may hold a parsed <see cref="JsonElement"/> or any CLR number type.
/// </summary>
public static class VectorCompare
{
    /// <summary>Compare <paramref name="actual"/> against <paramref name="expect"/>; <paramref name="diff"/> is "" when equal.</summary>
    public static bool Near(JsonNode? expect, JsonNode? actual, double eps, out string diff)
        => NearAt(expect, actual, actualPresent: true, eps, "", out diff);

    private static bool NearAt(JsonNode? expect, JsonNode? actual, bool actualPresent, double eps, string path, out string diff)
    {
        string at = path.Length > 0 ? path : "<value>";
        string actualText = actualPresent ? Show(actual) : "<missing>";
        bool Bad(string why, out string d) { d = $"{at}: {why}"; return false; }
        diff = "";

        if (expect is null)
            return actualPresent && actual is null || Bad($"expected null, got {actualText}", out diff);

        switch (expect)
        {
            case JsonArray ea:
            {
                if (!actualPresent || actual is not JsonArray aa) return Bad($"expected an array, got {actualText}", out diff);
                if (aa.Count != ea.Count) return Bad($"expected length {ea.Count}, got {aa.Count}", out diff);
                for (int i = 0; i < ea.Count; i++)
                    if (!NearAt(ea[i], aa[i], true, eps, $"{path}[{i}]", out diff)) return false;
                return true;
            }
            case JsonObject eo:
            {
                if (!actualPresent || actual is not JsonObject ao) return Bad($"expected an object, got {actualText}", out diff);
                foreach (var (key, ev) in eo)
                {
                    bool has = ao.TryGetPropertyValue(key, out var av);
                    if (!NearAt(ev, av, has, eps, $"{path}.{key}", out diff)) return false;
                }
                return true;
            }
        }

        if (TryNum(expect, out double e))
        {
            if (!actualPresent || !TryNum(actual, out double a) || !double.IsFinite(a))
                return Bad($"expected {Fmt(e)}, got {actualText}", out diff);
            double d = Math.Abs(e - a);
            return d <= eps || Bad($"expected {Fmt(e)}, got {Fmt(a)} (|diff| {Fmt(d)} > eps {Fmt(eps)})", out diff);
        }
        if (TryStr(expect, out var es))
            return actualPresent && TryStr(actual, out var s) && s == es || Bad($"expected {Show(expect)}, got {actualText}", out diff);
        if (TryBool(expect, out bool eb))
            return actualPresent && TryBool(actual, out bool b) && b == eb || Bad($"expected {Show(expect)}, got {actualText}", out diff);
        return Bad($"unsupported expectation {Show(expect)}", out diff);
    }

    // ---- readers ------------------------------------------------------------------------------

    /// <summary>A JSON number as double, whatever CLR type the <see cref="JsonValue"/> holds (NaN/Infinity included).</summary>
    public static bool TryNum(JsonNode? node, out double d)
    {
        d = 0;
        if (node is not JsonValue v) return false;
        if (v.TryGetValue(out JsonElement el))
        {
            if (el.ValueKind != JsonValueKind.Number) return false;
            d = el.GetDouble();
            return true;
        }
        if (v.TryGetValue(out double x)) { d = x; return true; }
        if (v.TryGetValue(out float f)) { d = f; return true; }
        if (v.TryGetValue(out int i)) { d = i; return true; }
        if (v.TryGetValue(out long l)) { d = l; return true; }
        if (v.TryGetValue(out decimal m)) { d = (double)m; return true; }
        if (v.TryGetValue(out short s)) { d = s; return true; }
        if (v.TryGetValue(out uint ui)) { d = ui; return true; }
        if (v.TryGetValue(out ulong ul)) { d = ul; return true; }
        if (v.TryGetValue(out ushort us)) { d = us; return true; }
        if (v.TryGetValue(out byte by)) { d = by; return true; }
        if (v.TryGetValue(out sbyte sb)) { d = sb; return true; }
        return false;
    }

    private static bool TryStr(JsonNode? node, out string s)
    {
        s = "";
        if (node is not JsonValue v) return false;
        if (v.TryGetValue(out JsonElement el))
        {
            if (el.ValueKind != JsonValueKind.String) return false;
            s = el.GetString()!;
            return true;
        }
        if (v.TryGetValue(out string? x) && x is not null) { s = x; return true; }
        return false;
    }

    private static bool TryBool(JsonNode? node, out bool b)
    {
        b = false;
        if (node is not JsonValue v) return false;
        if (v.TryGetValue(out JsonElement el))
        {
            if (el.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return false;
            b = el.ValueKind == JsonValueKind.True;
            return true;
        }
        return v.TryGetValue(out b);
    }

    /// <summary>A required number argument; throws (failing the case) when it is not one.</summary>
    public static double Num(JsonNode? node)
        => TryNum(node, out double d) ? d : throw new ArgumentException($"expected a number, got {Show(node)}");

    /// <summary>A number or JSON null (the TS <c>number | null</c>).</summary>
    public static double? NumOrNull(JsonNode? node) => node is null ? null : Num(node);

    /// <summary>A JSON array of numbers.</summary>
    public static List<double> NumList(JsonNode? node)
        => node is JsonArray a ? a.Select(Num).ToList() : throw new ArgumentException($"expected an array, got {Show(node)}");

    // ---- display ------------------------------------------------------------------------------

    private static string Fmt(double d) => d.ToString("R", CultureInfo.InvariantCulture);

    /// <summary>Compact JSON-like text of a node for failure messages; never throws (NaN shows as NaN).</summary>
    public static string Show(JsonNode? node)
    {
        var sb = new StringBuilder();
        Write(node, sb);
        return sb.ToString();
    }

    private static void Write(JsonNode? node, StringBuilder sb)
    {
        switch (node)
        {
            case null:
                sb.Append("null");
                return;
            case JsonArray a:
                sb.Append('[');
                for (int i = 0; i < a.Count; i++) { if (i > 0) sb.Append(", "); Write(a[i], sb); }
                sb.Append(']');
                return;
            case JsonObject o:
                sb.Append('{');
                bool first = true;
                foreach (var (k, v) in o)
                {
                    if (!first) sb.Append(", ");
                    first = false;
                    sb.Append(JsonSerializer.Serialize(k)).Append(": ");
                    Write(v, sb);
                }
                sb.Append('}');
                return;
        }
        if (TryNum(node, out double d)) sb.Append(Fmt(d));
        else if (TryStr(node, out var s)) sb.Append(JsonSerializer.Serialize(s));
        else if (TryBool(node, out bool b)) sb.Append(b ? "true" : "false");
        else sb.Append(node.ToString());
    }
}
