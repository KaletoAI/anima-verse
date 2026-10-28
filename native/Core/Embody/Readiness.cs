using System.Threading.Tasks;

namespace AnimaNative.Embody;

/// <summary>Task 47: renderer-free place readiness with independent approach/teleport/entry pin owners, readiness.ts.</summary>
public interface IReadinessDeps
{
    string? PlaceAt(double x, double z);
    bool IsReady(string id);
    void Pin(string id, string owner);
    void Release(string id, string owner);
}
public sealed record PendingSnap(double X, double Z, string Id);
public sealed record ResidentReadiness(string Ring, bool Ready);
public sealed class ReadinessState
{
    public string? ApproachPin { get; set; }
    public PendingSnap? PendingSnap { get; set; }
}
public interface IEntryDeps
{
    void RequestNear(string id);
    void Release(string id, string owner);
    Task Settled(string id);
    Task Sleep(int ms);
    bool IsReady(string id);
    bool StillValid(string key);
    bool Exists(string id);
    bool CanProgress(string id);
}

/// <summary>Task 47 (E7-T2): readiness.ts; no engine, clock or residency implementation, embody.json and lifecycle tests.</summary>
public static class Readiness
{
    public static bool HoldFor(IReadinessDeps deps, ReadinessState state, double x, double z)
    {
        string? id = deps.PlaceAt(x, z);
        string? held = id is not null && !deps.IsReady(id) ? id : null;
        if (!string.IsNullOrEmpty(state.ApproachPin) && state.ApproachPin != held) deps.Release(state.ApproachPin, "approach");
        state.ApproachPin = held;
        if (!string.IsNullOrEmpty(held)) deps.Pin(held, "approach");
        return held is not null;
    }
    public static void ClearApproach(IReadinessDeps deps, ReadinessState state)
    {
        if (!string.IsNullOrEmpty(state.ApproachPin)) deps.Release(state.ApproachPin, "approach");
        state.ApproachPin = null;
    }
    public static void ClearSnap(IReadinessDeps deps, ReadinessState state)
    {
        if (state.PendingSnap is { } snap) deps.Release(snap.Id, "teleport");
        state.PendingSnap = null;
    }
    public static void HoldSnap(IReadinessDeps deps, ReadinessState state, PendingSnap snap)
    {
        ClearApproach(deps, state);
        ClearSnap(deps, state);
        state.PendingSnap = snap;
        deps.Pin(snap.Id, "teleport");
    }
    public static bool TrySnap(IReadinessDeps deps, PendingSnap snap) => deps.IsReady(snap.Id);

    /// <summary>Request near geometry; race each settlement with a 1s retry, and always release only the entry pin.</summary>
    public static async Task<bool> EnterWhenReady(IEntryDeps deps, string id, string key)
    {
        try
        {
            deps.RequestNear(id);
            for (;;)
            {
                await await Task.WhenAny(deps.Settled(id), deps.Sleep(1000));
                if (!deps.Exists(id) || !deps.StillValid(key)) return false;
                if (deps.IsReady(id)) return true;
                if (!deps.CanProgress(id)) return false;
            }
        }
        finally { deps.Release(id, "entry"); }
    }
    public static bool AvatarWaitsForPlace(bool isAvatar, string locationId, ResidentReadiness? resident)
        => isAvatar && locationId.Length > 0 && (resident?.Ring != "near" || resident.Ready != true);
}
