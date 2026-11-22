using System;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>The worldmap's optional closing clip of one participant (§ A8c).</summary>
public sealed record FinaleBlock(string Id, string Kind, string? Role, double ElapsedS, double DurationS)
{
    public string Alt { get; init; } = "";
    /// <summary><c>tempo</c>: clip seconds per real second, 0.2..1 (null when the row lacks it = 1).</summary>
    public double? Tempo { get; init; }
}
/// <summary>A locally played finale: <c>T</c> CLIP seconds into a finale of <c>Duration</c> REAL seconds played at
/// <c>Tempo</c> (the whole finale is <c>Duration · Tempo</c> clip seconds), independently of the action underneath.</summary>
public sealed record FinalePlay(string Id, string Kind, string? Role, double T, double Duration)
{
    public string Alt { get; init; } = "";
    /// <summary>Clip seconds per real second, 0.2..1.</summary>
    public double Tempo { get; init; } = 1;
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
                Tempo = PairClip.ClipTempo(block.Tempo),
            };
        return (play, block.Id);
    }

    /// <summary>Advance by <c>dt · tempo</c> clip seconds unless frozen, end at the whole finale's clip length
    /// (<c>Duration · Tempo</c>: its real length at that tempo), and cap the sampled time one millisecond before it.</summary>
    public static (FinalePlay? Play, string? Clip, string? Base, double T) Step(FinalePlay? play, double dt, bool frozen)
    {
        if (play is null) return (null, null, null, 0);
        double tempo = play.Tempo > 0 ? play.Tempo : 1;
        double t = play.T + (frozen || !(dt > 0) ? 0 : dt * tempo);
        double total = play.Duration * tempo;
        if (t >= total) return (null, null, null, 0);
        return (play with { T = t }, play.Clip, play.Base,
                Math.Min(t, total - 1e-3));
    }
}
