using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using AnimaNative.Nav;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The navigation of the near mounts (plan 2026-11-25-client-ausfuehrung-e2, Task 4; decisions 3–6, 8). A location is
/// baked when it turns near and after every <see cref="DeriveStands"/> while it stays near; the source fingerprint
/// decides whether anything is baked at all, a 16-entry memory cache keeps the storey meshes of recent fingerprints.
/// A finished bake becomes a PENDING map; the navigation server's <c>MapChanged</c> arms it (the current locks are
/// applied) and swaps it in once it answers with its current state — so a location never has a frame without a path.
/// The signal is subscribed only while a map is pending (review N-W1). Hand derivations and the check sections
/// N9–N13: native/fixtures/README.md, section "Nav world"; check: <c>--check nav</c>.
/// </summary>
public sealed partial class WorldBuilder
{
    private const int NavCacheSize = 16;

    /// <summary>The bake mode (decision 1; Task 5 keeps one mode and removes this property).</summary>
    public NavBakeMode NavMode { get; set; } = NavBakeMode.Polygon;

    /// <summary>A navigation was swapped in or released for the slot.</summary>
    public event Action<LocationSlot>? NavChanged;

    /// <summary>One running bake of a slot: the slot generation and fingerprint it started for; Stale = a newer source waits.</summary>
    private sealed class NavJob
    {
        public required int Generation { get; init; }
        public required string Fingerprint { get; init; }
        public bool Stale { get; set; }
    }

    /// <summary>A created map waiting for the server's sync; Armed = the current locks were applied at its first MapChanged.</summary>
    private sealed class PendingNav
    {
        public required LocationSlot Slot { get; init; }
        public required LocationNav Nav { get; init; }
        public bool Armed { get; set; }
    }

    private readonly Dictionary<LocationSlot, NavJob> _navJobs = new();
    private readonly Dictionary<LocationSlot, PendingNav> _navPending = new();
    private readonly Dictionary<string, NavigationMesh[]> _navCache = new();
    private readonly LinkedList<string> _navCacheOrder = new();
    private bool _navSubscribed;

    /// <summary>The MapChanged handler is subscribed (exactly while a map is pending; checks N11/N13).</summary>
    internal bool NavMapChangedSubscribed => _navSubscribed;
    /// <summary>How often the handler saw a pending map (check N13 counts the swap of a fresh map at its first MapChanged).</summary>
    internal int NavArmCalls { get; private set; }
    /// <summary>Bakes whose result was thrown away (released, stopped, remounted or superseded; checks N11/N13).</summary>
    internal int NavBakesDropped { get; private set; }
    /// <summary>A bake of the slot is running.</summary>
    internal bool NavBaking(LocationSlot slot) => _navJobs.ContainsKey(slot);

    /// <summary>
    /// The swapped navigation of the slot (never a pending one). It stays the same through <see cref="SetLocks"/>, even
    /// while it reports <c>Ready == false</c> until its next iteration (review N-W4).
    /// </summary>
    public LocationNav? NavFor(LocationSlot? slot) => slot?.Nav;

    /// <summary>
    /// Decision 8: the measured world boxes of the slot's furniture (role prop, no door, not walkable), from the one
    /// measurement of the last <see cref="DeriveStands"/>; <c>Level</c> = the spec's storey.
    /// </summary>
    public IReadOnlyList<NavPropBox> NavPropBoxes(LocationSlot slot)
        => slot.PropBoxes.Where(b => b.Spec.Role == "prop" && b.Spec.Door is null && !b.Spec.Walkable)
                         .Select(b => new NavPropBox(b.Spec.Level, b.Min, b.Max)).ToList();

    /// <summary>
    /// Decision 5: bake the slot's navigation if its source changed. Not near or nothing walkable → released; the same
    /// fingerprint as the active (or pending) map → nothing; a bake running → it is marked stale when the source differs
    /// from its own; else a cache hit or a new bake, which ends as a pending map (<see cref="OnNavMapChanged"/>).
    /// </summary>
    internal void RequestNavBake(LocationSlot slot)
    {
        if (_residencyStopped || slot.Ring != Ring.Near || slot.Scene is not { } scene || Height is null)
        {
            ReleaseNav(slot);
            return;
        }
        var p = NavBakeParams.For(NavMode);
        var src = NavSource.Build(scene, slot.Stands.Frame, slot.Places, NavPropBoxes(slot), slot.IsBuilding, p);
        if (src.IsEmpty)
        {
            ReleaseNav(slot);
            return;
        }
        if (_navJobs.TryGetValue(slot, out var job))
        {
            job.Stale = job.Fingerprint != src.Fingerprint;
            return;
        }
        if (slot.Nav?.Fingerprint == src.Fingerprint)
        {
            DropPending(slot);   // a newer source came back to the active one
            return;
        }
        if (_navPending.TryGetValue(slot, out var pending) && pending.Nav.Fingerprint == src.Fingerprint) return;

        var watch = Stopwatch.StartNew();
        if (CachedNav(src.Fingerprint) is { } meshes)
        {
            LogBake(slot, src, watch, hit: true);
            AddPending(slot, src, meshes, p);
            return;
        }
        var started = new NavJob { Generation = slot.Generation, Fingerprint = src.Fingerprint };
        _navJobs[slot] = started;
        _ = BakeAsync(slot, src, p, started, watch);
    }

    private async System.Threading.Tasks.Task BakeAsync(LocationSlot slot, NavSourceData src, NavBakeParams p, NavJob job, Stopwatch watch)
    {
        NavigationMesh[] meshes;
        try
        {
            var ground = Height;
            meshes = await NavBake.BakeStoreysAsync(src, p, ground is null ? null : ground.GroundAt);
        }
        catch (Exception e)
        {
            if (_navJobs.TryGetValue(slot, out var cur) && cur == job) _navJobs.Remove(slot);
            _log($"[nav] bake loc={slot.Loc.Id} failed: {e.Message}");
            return;
        }
        RememberNav(src.Fingerprint, meshes);
        LogBake(slot, src, watch, hit: false);
        // Only the job still registered for the slot may publish; a release or a newer job replaced it otherwise.
        if (!_navJobs.TryGetValue(slot, out var current) || current != job)
        {
            NavBakesDropped++;
            return;
        }
        _navJobs.Remove(slot);
        if (_residencyStopped || slot.Generation != job.Generation || slot.Ring != Ring.Near
            || !_slots.TryGetValue(slot.Loc.Id, out var live) || live != slot)
        {
            NavBakesDropped++;
            return;
        }
        if (job.Stale)
        {
            NavBakesDropped++;
            RequestNavBake(slot);   // the source changed while this bake ran: bake the newest one
            return;
        }
        AddPending(slot, src, meshes, p);
    }

    /// <summary>Releases the slot's active and pending navigation and forgets a running bake (its result is dropped).</summary>
    internal void ReleaseNav(LocationSlot slot)
    {
        _navJobs.Remove(slot);
        DropPending(slot);
        if (slot.Nav is { } nav)
        {
            slot.Nav = null;
            nav.Free();
            NavChanged?.Invoke(slot);
        }
    }

    /// <summary>
    /// The navigation server synced a map (decision 4). A pending map is armed at its first MapChanged — the current
    /// locks applied — and swapped in as soon as it is ready: at once when the locks changed nothing, else at the next
    /// MapChanged after the change. The old map is freed; with nothing pending the handler unsubscribes.
    /// </summary>
    private void OnNavMapChanged(Rid map)
    {
        var entry = _navPending.Values.FirstOrDefault(e => e.Nav.Map == map);
        if (entry is null) return;
        NavArmCalls++;
        var slot = entry.Slot;
        if (!entry.Armed)
        {
            entry.Armed = true;
            entry.Nav.ApplyLocks(_locks.RoomsFor(slot.Loc.Id), _locks.AvatarRoom);
        }
        if (!entry.Nav.Ready) return;
        _navPending.Remove(slot);
        var old = slot.Nav;
        slot.Nav = entry.Nav;
        old?.Free();
        NavChanged?.Invoke(slot);
        SyncNavSubscription();
    }

    /// <summary>The locks of <see cref="SetLocks"/> on every active and pending map (decision 3: the one lock path).</summary>
    private void ApplyNavLocks(LocationSlot slot)
    {
        var rooms = _locks.RoomsFor(slot.Loc.Id);
        slot.Nav?.ApplyLocks(rooms, _locks.AvatarRoom);
        if (_navPending.TryGetValue(slot, out var pending)) pending.Nav.ApplyLocks(rooms, _locks.AvatarRoom);
    }

    /// <summary>Review N-W1: StopResidency drops every bake, pending and active map, the subscription and the cache.</summary>
    private void StopNav()
    {
        _navJobs.Clear();
        foreach (var slot in _slots.Values.ToArray()) ReleaseNav(slot);
        foreach (var slot in _navPending.Keys.ToArray()) DropPending(slot);
        SyncNavSubscription();
        _navCache.Clear();
        _navCacheOrder.Clear();
    }

    private void AddPending(LocationSlot slot, NavSourceData src, NavigationMesh[] meshes, NavBakeParams p)
    {
        DropPending(slot);
        _navPending[slot] = new PendingNav { Slot = slot, Nav = LocationNav.Create(src, meshes, p) };
        SyncNavSubscription();
    }

    private void DropPending(LocationSlot slot)
    {
        if (!_navPending.Remove(slot, out var pending)) return;
        pending.Nav.Free();
        SyncNavSubscription();
    }

    /// <summary>Subscribed exactly while a map is pending.</summary>
    private void SyncNavSubscription()
    {
        bool want = _navPending.Count > 0;
        if (want == _navSubscribed) return;
        if (want) NavigationServer3D.MapChanged += OnNavMapChanged;
        else NavigationServer3D.MapChanged -= OnNavMapChanged;
        _navSubscribed = want;
    }

    private NavigationMesh[]? CachedNav(string fingerprint)
    {
        if (!_navCache.TryGetValue(fingerprint, out var meshes)) return null;
        _navCacheOrder.Remove(fingerprint);
        _navCacheOrder.AddFirst(fingerprint);
        return meshes;
    }

    private void RememberNav(string fingerprint, NavigationMesh[] meshes)
    {
        if (_navCache.ContainsKey(fingerprint)) _navCacheOrder.Remove(fingerprint);
        _navCache[fingerprint] = meshes;
        _navCacheOrder.AddFirst(fingerprint);
        while (_navCacheOrder.Count > NavCacheSize)
        {
            _navCache.Remove(_navCacheOrder.Last!.Value);
            _navCacheOrder.RemoveLast();
        }
    }

    private void LogBake(LocationSlot slot, NavSourceData src, Stopwatch watch, bool hit)
        => _log($"[nav] bake loc={slot.Loc.Id} mode={NavMode.ToString().ToLowerInvariant()} storeys={src.Storeys.Count} "
                + $"thresholds={src.Thresholds.Count} links={src.Links.Count} ms={watch.Elapsed.TotalMilliseconds:0.#} "
                + $"cache={(hit ? "hit" : "miss")}");
}
