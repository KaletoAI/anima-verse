using System;
using System.Globalization;
using System.Text.Json;

namespace AnimaNative.Scene;

/// <summary>
/// The few JavaScript value rules the scene ports must mirror because C# reads them differently:
/// <c>v || fallback</c> on a number (0 and NaN fall back, a negative number does not), <c>Number(x)</c>
/// of a JSON value, and <c>parseInt(s, 16)</c>.
/// </summary>
public static class Js
{
    /// <summary>JS <c>v || fallback</c> for a number: 0 and NaN take the fallback.</summary>
    public static double Or(double v, double fallback) => v == 0 || double.IsNaN(v) ? fallback : v;

    /// <summary>JS <c>Number(v)</c> of a JSON value; an absent value (<c>undefined</c>) is NaN.</summary>
    public static double Number(JsonElement? v)
    {
        if (v is not { } e) return double.NaN;
        switch (e.ValueKind)
        {
            case JsonValueKind.Number: return e.GetDouble();
            case JsonValueKind.True: return 1;
            case JsonValueKind.False:
            case JsonValueKind.Null: return 0;
            case JsonValueKind.String:
            {
                var s = e.GetString()!.Trim();
                if (s.Length == 0) return 0;
                return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : double.NaN;
            }
            default: return double.NaN;
        }
    }

    /// <summary>JS <c>parseInt(s, 16)</c>: leading white space, an optional sign and <c>0x</c>, then the longest hex prefix; none = NaN.</summary>
    public static double ParseIntHex(string s)
    {
        int i = 0;
        while (i < s.Length && Overview.JsSemantics.IsWhiteSpace(s[i])) i++;
        double sign = 1;
        if (i < s.Length && (s[i] == '+' || s[i] == '-')) { if (s[i] == '-') sign = -1; i++; }
        if (i + 1 < s.Length && s[i] == '0' && (s[i + 1] == 'x' || s[i + 1] == 'X')) i += 2;
        double value = 0;
        int digits = 0;
        for (; i < s.Length; i++)
        {
            int d = s[i] switch
            {
                >= '0' and <= '9' => s[i] - '0',
                >= 'a' and <= 'f' => s[i] - 'a' + 10,
                >= 'A' and <= 'F' => s[i] - 'A' + 10,
                _ => -1,
            };
            if (d < 0) break;
            value = value * 16 + d;
            digits++;
        }
        return digits == 0 ? double.NaN : sign * value;
    }
}
