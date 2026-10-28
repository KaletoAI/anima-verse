using System.Collections.Generic;

namespace AnimaNative.Embody;

public enum DriverKind { PLAYER, SERVER, CANCELLING }
/// <summary>Task 47: posEcho.ts driver; journey can be null for a legacy server route, FirstSeq belongs to CANCELLING.</summary>
public readonly record struct DriverState(DriverKind Kind, string? Journey = null, long FirstSeq = 0);
/// <summary>Task 47: preserve the unique NO_CANCEL sentinel separately from an explicitly cancelled null journey.</summary>
public readonly record struct CancelledJourney(bool HasValue, string? Journey)
{
    public static CancelledJourney None => new(false, null);
}
public abstract record DriverEvent;
public sealed record DriverPayload(bool HasRoute, string? JourneyId, long? OriginOwnSeq) : DriverEvent;
public sealed record DriverInput(long FirstSeq) : DriverEvent;
public sealed record DriverRefused(long Seq) : DriverEvent;
public readonly record struct DriverResult(DriverState State, CancelledJourney Cancelled);
public sealed record PositionOrigin(string Session, long Seq);

/// <summary>Task 47 (E7-T2): posEcho.ts ownership, cancellation acknowledgement and origin-stamped echo ring; embody.json.</summary>
public static class PosEcho
{
    public const int EchoRingCap = 64;
    /// <summary>Remember at send time; an aborted request may still reach the server.</summary>
    public static void PushSeq(List<long> ring, long seq, int cap = EchoRingCap)
    {
        ring.Add(seq);
        while (ring.Count > cap) ring.RemoveAt(0);
    }
    public static bool IsOwnEcho(IReadOnlyCollection<long> ring, string mySession, PositionOrigin? origin)
    {
        if (origin is null || origin.Session != mySession) return false;
        foreach (var seq in ring) if (seq == origin.Seq) return true;
        return false;
    }
    private static bool IsCancelled(CancelledJourney cancelled, string? journey) => cancelled.HasValue && cancelled.Journey == journey;

    /// <summary>First input reserves a cancellation sequence; only a matching acknowledgement, route removal or replacement changes ownership.</summary>
    public static DriverResult AvatarDriver(DriverState state, DriverEvent ev, CancelledJourney cancelled)
    {
        if (ev is DriverInput input)
            return state.Kind == DriverKind.SERVER
                ? new(new(DriverKind.CANCELLING, state.Journey, input.FirstSeq), new(true, state.Journey)) : new(state, cancelled);
        if (ev is DriverRefused refused)
            return state.Kind == DriverKind.CANCELLING && refused.Seq >= state.FirstSeq
                ? new(new(DriverKind.SERVER, state.Journey), CancelledJourney.None) : new(state, cancelled);
        var p = (DriverPayload)ev;
        if (state.Kind == DriverKind.PLAYER)
            return p.HasRoute && !IsCancelled(cancelled, p.JourneyId)
                ? new(new(DriverKind.SERVER, p.JourneyId), cancelled) : new(state, cancelled);
        if (state.Kind == DriverKind.SERVER)
        {
            if (!p.HasRoute) return new(new(DriverKind.PLAYER), cancelled);
            return p.JourneyId != state.Journey ? new(new(DriverKind.SERVER, p.JourneyId), cancelled) : new(state, cancelled);
        }
        if (p.HasRoute && p.JourneyId != state.Journey) return new(new(DriverKind.SERVER, p.JourneyId), cancelled);
        if (p.OriginOwnSeq is long seq && seq >= state.FirstSeq) return new(new(DriverKind.PLAYER), cancelled);
        if (!p.HasRoute) return new(new(DriverKind.PLAYER), cancelled);
        return new(state, cancelled);
    }
    public static bool SuppressedJourney(DriverState state, CancelledJourney cancelled, string? journeyId)
        => state.Kind == DriverKind.CANCELLING && journeyId == state.Journey || journeyId is not null && IsCancelled(cancelled, journeyId);
    public static bool AnswerApplies(DriverState state, long seq, long floor)
        => state.Kind != DriverKind.SERVER && seq >= floor && (state.Kind != DriverKind.CANCELLING || seq >= state.FirstSeq);
}
