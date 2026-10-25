using System;

namespace AnimaNative.Overview;

/// <summary>
/// Port of client3d/src/game/bubble.ts — the two rules behind a speech bubble: how much of a
/// line is shown and how long it hangs over the head. Whitespace and lengths follow JS
/// (<see cref="JsSemantics"/>: the ECMA-262 whitespace set, UTF-16 code units). Vectors:
/// shared/test-vectors/overview_hud.json [B1..B15] (hand derivations in
/// client3d/scripts/smoke_walk_math.mjs).
/// </summary>
public static class Bubble
{
    /// <summary>The most characters a bubble shows, the ellipsis included.</summary>
    public const int MaxChars = 140;
    /// <summary>Even "Yes." needs this long to be noticed (ms).</summary>
    public const int BaseMs = 3500;
    /// <summary>Reading pace on top of the base (ms per character).</summary>
    public const int MsPerChar = 55;
    /// <summary>Nobody stares at one bubble longer than this (ms).</summary>
    public const int MaxMs = 12000;

    /// <summary>
    /// What the bubble shows: whitespace collapsed to single spaces, cut to <see cref="MaxChars"/>
    /// INCLUDING the ellipsis (no space left hanging before it); "" for whitespace only.
    /// </summary>
    public static string Text(string text)
    {
        string words = JsSemantics.CollapseWhitespace(text);
        if (words.Length <= MaxChars) return words;
        return JsSemantics.TrimEnd(words.Substring(0, MaxChars - 1)) + "…";
    }

    /// <summary>
    /// How long the bubble stays, in ms, measured on the UNCUT (collapsed) line:
    /// <c>clamp(3500 + 55 · n, 3500, 12000)</c>.
    /// </summary>
    public static int Ms(string text)
    {
        long n = JsSemantics.CollapseWhitespace(text).Length;
        long ms = BaseMs + n * MsPerChar;
        return (int)Math.Min(Math.Max(ms, BaseMs), MaxMs);
    }
}
