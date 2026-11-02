using System;

namespace AnimaNative.Figures;

/// <summary>The worldmap's optional closing clip of one participant (§ A8c).</summary>
public sealed record FinaleBlock(string Id, string Kind, string? Role, double ElapsedS, double DurationS);
/// <summary>A locally played finale, timed in real frame seconds, independently of the action underneath.</summary>
public sealed record FinalePlay(string Id, string Kind, string? Role, double T, double Duration);

/// <summary>Pure port of client3d/game/finaleClip.ts; elapsed_s is deliberately never used to seek.</summary>
public static class FinaleClip
{
    /// <summary>Consume a new id once, starting at zero; losing the action ends any current finale.</summary>
    public static (FinalePlay? Play, string Seen) Adopt(FinalePlay? current, string seen, FinaleBlock? block, bool inAction)
    {
        var play = inAction ? current : null;
        if (block is null || string.IsNullOrEmpty(block.Id) || block.Id == seen) return (play, seen);
        if (inAction && !string.IsNullOrEmpty(block.Kind) && double.IsFinite(block.DurationS) && block.DurationS > 0)
            play = new FinalePlay(block.Id, block.Kind, block.Role is "a" or "b" ? block.Role : null, 0, block.DurationS);
        return (play, block.Id);
    }

    /// <summary>Advance unless frozen, end at duration, and cap the sampled time one millisecond before the end.</summary>
    public static (FinalePlay? Play, string? Clip, double T) Step(FinalePlay? play, double dt, bool frozen)
    {
        if (play is null) return (null, null, 0);
        double t = play.T + (frozen || !(dt > 0) ? 0 : dt);
        if (t >= play.Duration) return (null, null, 0);
        return (play with { T = t }, play.Role is { } role ? $"{play.Kind}__{role}" : play.Kind,
                Math.Min(t, play.Duration - 1e-3));
    }
}
