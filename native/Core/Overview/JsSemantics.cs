using System;
using System.Text;

namespace AnimaNative.Overview;

/// <summary>
/// The few JavaScript number and string rules the overview ports must mirror bit for bit,
/// because .NET's defaults differ: <c>Math.round</c> (half UP towards +∞, .NET rounds half to
/// even) and the whitespace set of <c>String.prototype.trim</c> / regex <c>\s</c> (WhiteSpace +
/// LineTerminator of ECMA-262 — U+FEFF is in it, U+0085 is not; <see cref="char.IsWhiteSpace(char)"/>
/// has it the other way round). Strings are measured in UTF-16 code units, which is what both
/// JS <c>length</c> and .NET <see cref="string.Length"/> count.
/// </summary>
internal static class JsSemantics
{
    /// <summary>JS <c>Math.round</c>: the nearest integer, a tie goes towards +∞.</summary>
    public static double Round(double x)
    {
        if (!double.IsFinite(x)) return x;
        double f = Math.Floor(x);
        // x − floor(x) is exact for every double, so the tie test is exact too
        // (Math.Floor(x + 0.5) would round 0.49999999999999994 up).
        double r = x - f >= 0.5 ? f + 1 : f;
        // JS keeps the sign of a zero result for −0.5 ≤ x < 0 (−0); a JSON consumer sees 0.
        return r == 0 && x < 0 ? -0.0 : r;
    }

    /// <summary>ECMA-262 WhiteSpace ∪ LineTerminator — the set of <c>trim()</c> and <c>\s</c>.</summary>
    public static bool IsWhiteSpace(char c) => c switch
    {
        '\u0009' or '\u000A' or '\u000B' or '\u000C' or '\u000D' or ' ' or '\u00A0' or '\u1680'
            or '\u2028' or '\u2029' or '\u202F' or '\u205F' or '\u3000' or '\uFEFF' => true,
        >= '\u2000' and <= '\u200A' => true,
        _ => false,
    };

    /// <summary>JS <c>s.trimEnd()</c>.</summary>
    public static string TrimEnd(string s)
    {
        int end = s.Length;
        while (end > 0 && IsWhiteSpace(s[end - 1])) end--;
        return end == s.Length ? s : s.Substring(0, end);
    }

    /// <summary>JS <c>s.trim().replace(/\s+/g, ' ')</c>.</summary>
    public static string CollapseWhitespace(string s)
    {
        int start = 0, end = s.Length;
        while (start < end && IsWhiteSpace(s[start])) start++;
        while (end > start && IsWhiteSpace(s[end - 1])) end--;
        var sb = new StringBuilder(end - start);
        bool inRun = false;
        for (int i = start; i < end; i++)
        {
            if (IsWhiteSpace(s[i]))
            {
                if (!inRun) sb.Append(' ');
                inRun = true;
            }
            else
            {
                sb.Append(s[i]);
                inRun = false;
            }
        }
        return sb.ToString();
    }
}
