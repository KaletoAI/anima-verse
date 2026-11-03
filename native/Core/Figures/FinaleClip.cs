using System;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>The worldmap's optional closing clip of one participant (§ A8c).</summary>
public sealed record FinaleBlock(string Id, string Kind, string? Role, double ElapsedS, double DurationS)
{
    public string Alt { get; init; } = "";
}
/// <summary>A locally played finale, timed in real frame seconds, independently of the action underneath.</summary>
public sealed record FinalePlay(string Id, string Kind, string? Role, double T, double Duration)
{
    public string Alt { get; init; } = "";
    public string Base => ClipLibraryRules.IndexName(Kind, Role);
    public string Clip => ClipLibraryRules.IndexName(Kind, Role, Alt);
    public string? ResolveClip(Func<string, bool> usable) => ClipLibraryRules.SelectClip(Clip, Base, usable);
}

/// <summary>Pure port of client3d/game/finaleClip.ts; elapsed_s is deliberately never used to seek.</summary>
public static class FinaleClip
{
    /// <summary>§ A8a/A8c: a clip role of a pair or group is <c>a</c>..<c>e</c> (G3); anything else is no role.</summary>
    public static bool IsRole(string? role) => role is "a" or "b" or "c" or "d" or "e";

    private static readonly Regex AltName = new("\\A[a-z0-9][a-z0-9-]*\\z", RegexOptions.CultureInvariant);

    /// <summary>Consume a new id once, starting at zero; losing the action ends any current finale.</summary>
    public static (FinalePlay? Play, string Seen) Adopt(FinalePlay? current, string seen, FinaleBlock? block, bool inAction)
    {
        var play = inAction ? current : null;
        if (block is null || string.IsNullOrEmpty(block.Id) || block.Id == seen) return (play, seen);
        if (inAction && !string.IsNullOrEmpty(block.Kind) && double.IsFinite(block.DurationS) && block.DurationS > 0)
            play = new FinalePlay(block.Id, block.Kind, IsRole(block.Role) ? block.Role : null, 0, block.DurationS)
            {
                Alt = IsRole(block.Role) && AltName.IsMatch(block.Alt) ? block.Alt : "",
            };
        return (play, block.Id);
    }

    /// <summary>Advance unless frozen, end at duration, and cap the sampled time one millisecond before the end.</summary>
    public static (FinalePlay? Play, string? Clip, string? Base, double T) Step(FinalePlay? play, double dt, bool frozen)
    {
        if (play is null) return (null, null, null, 0);
        double t = play.T + (frozen || !(dt > 0) ? 0 : dt);
        if (t >= play.Duration) return (null, null, null, 0);
        return (play with { T = t }, play.Clip, play.Base,
                Math.Min(t, play.Duration - 1e-3));
    }
}
