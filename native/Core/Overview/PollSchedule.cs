using System;

namespace AnimaNative.Overview;

/// <summary>
/// Port of the schedule of packages/player-ui/src/pollCore.ts — how often one polled entry is
/// fetched and how failures stretch that. The poll state machine itself (subscribers, refresh
/// waiters, push topics) is not ported here; this is the arithmetic both clients must agree on.
/// Vectors: shared/test-vectors/poll_schedule.json (hand derivations in scripts/smoke_sync_client.mjs).
/// </summary>
public static class PollSchedule
{
    /// <summary>The poll core's tick (ms).</summary>
    public const double TickMs = 1000;
    /// <summary>Retries back off to a minute at most — unless the base interval is slower (ms).</summary>
    public const double MaxBackoffMs = 60_000;
    /// <summary>Highest error multiplier: 1, 2, 4 … 64.</summary>
    public const double MaxErrorFactor = 64;

    /// <summary>
    /// The time between two polls of one entry, in ms: the base stretched by the error factor,
    /// never past <c>max(base, MaxBackoffMs)</c> and never below the minimum spacing.
    /// </summary>
    public static double IntervalMs(double baseMs, double minSpacingMs, double errorFactor)
        => Math.Max(minSpacingMs, Math.Min(baseMs * errorFactor, Math.Max(baseMs, MaxBackoffMs)));

    /// <summary>The error factor after a request: 1 on success, doubled on failure up to <see cref="MaxErrorFactor"/>.</summary>
    public static double NextErrorFactor(double factor, bool ok) => ok ? 1 : Math.Min(factor * 2, MaxErrorFactor);
}
