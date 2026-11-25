using System.Collections.Generic;
using System.Linq;
using AnimaNative.Embody;
using AnimaNative.Nav;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The navigation map of ONE location (plan 2026-11-25-client-ausfuehrung-e2, decisions 3, 4, 13): one region per
/// storey, one region per door threshold, one link per stair flight and lift hop, all on a map of its own with
/// synchronous iterations. A lock switches threshold regions off and on — never a rebake. Ready = the map has
/// iterated since the last change that really switched something (<see cref="ChangedAtIteration"/>).
/// </summary>
public sealed class LocationNav : IPathProvider
{
    public Rid Map { get; }
    public IReadOnlyList<Rid> Storeys { get; }
    /// <summary>The baked storey meshes, parallel to <see cref="Storeys"/> (the server has no getter; the F9 overlay draws them).</summary>
    public IReadOnlyList<NavigationMesh> StoreyMeshes { get; }
    /// <summary>Threshold regions keyed by doorway index.</summary>
    public IReadOnlyDictionary<int, Rid> Thresholds { get; }
    /// <summary>Link rids keyed by owner id (decision 13).</summary>
    public IReadOnlyDictionary<ulong, Rid> Links { get; }
    public string Fingerprint { get; }
    public NavSourceData Source { get; }
    /// <summary>The map iteration at the last effective change; 0 for a fresh map.</summary>
    public ulong ChangedAtIteration { get; private set; }

    // The enabled state last written per threshold region / link. Measured with 4.7.2: RegionGetEnabled and
    // LinkGetEnabled answer the OLD value until the server's next sync, so comparing with them would let a second
    // change in the same frame (lock, then unlock) look like "no change" and leave the pending first write in place.
    // The written state is what the server holds after its sync — the comparison of decision 3 / review N-B1.
    private readonly Dictionary<Rid, bool> _enabled = new();

    /// <summary>The map answers with its current state (decision 4: iterated since the last effective change).</summary>
    public bool Ready => NavigationServer3D.MapGetIterationId(Map) > ChangedAtIteration;

    private LocationNav(Rid map, IReadOnlyList<Rid> storeys, IReadOnlyList<NavigationMesh> storeyMeshes,
                        IReadOnlyDictionary<int, Rid> thresholds, IReadOnlyDictionary<ulong, Rid> links, NavSourceData src)
    {
        Map = map;
        Storeys = storeys;
        StoreyMeshes = storeyMeshes;
        Thresholds = thresholds;
        Links = links;
        Source = src;
        Fingerprint = src.Fingerprint;
    }

    /// <summary>
    /// A new active map for the baked storeys (parallel to <c>src.Storeys</c>), the thresholds and the links. Every
    /// threshold starts enabled; the caller applies the current locks.
    /// </summary>
    public static LocationNav Create(NavSourceData src, NavigationMesh[] storeys, NavBakeParams p)
    {
        var map = NavigationServer3D.MapCreate();
        NavigationServer3D.MapSetCellSize(map, (float)p.CellSize);
        NavigationServer3D.MapSetCellHeight(map, (float)p.CellHeight);
        NavigationServer3D.MapSetEdgeConnectionMargin(map, (float)p.EdgeConnectionMargin);
        NavigationServer3D.MapSetLinkConnectionRadius(map, (float)p.LinkConnectionRadius);
        NavigationServer3D.MapSetUseEdgeConnections(map, true);
        NavigationServer3D.MapSetUseAsyncIterations(map, false);
        NavigationServer3D.MapSetActive(map, true);

        var storeyRids = new List<Rid>();
        var storeyMeshes = new List<NavigationMesh>();
        for (int i = 0; i < src.Storeys.Count && i < storeys.Length; i++)
        {
            storeyRids.Add(Region(map, storeys[i], NavLayers.ForLevel(src.Storeys[i].Level)));
            storeyMeshes.Add(storeys[i]);
        }

        var thresholds = new Dictionary<int, Rid>();
        foreach (var t in src.Thresholds)
            thresholds[t.Doorway] = Region(map, NavBake.ThresholdMesh(t, p), NavLayers.ForLevel(t.Level));

        var links = new Dictionary<ulong, Rid>();
        foreach (var l in src.Links)
        {
            var rid = NavigationServer3D.LinkCreate();
            NavigationServer3D.LinkSetMap(rid, map);
            NavigationServer3D.LinkSetStartPosition(rid, ToGodot(l.Start));
            NavigationServer3D.LinkSetEndPosition(rid, ToGodot(l.End));
            NavigationServer3D.LinkSetBidirectional(rid, true);
            NavigationServer3D.LinkSetEnterCost(rid, (float)l.EnterCost);
            NavigationServer3D.LinkSetTravelCost(rid, l.Kind == "elevator" ? (float)NavBakeParams.ElevatorTravelCost : 1f);
            NavigationServer3D.LinkSetNavigationLayers(rid, NavLayers.Links);
            NavigationServer3D.LinkSetOwnerId(rid, l.Owner);
            links[l.Owner] = rid;
        }
        return new LocationNav(map, storeyRids, storeyMeshes, thresholds, links, src);
    }

    /// <summary>
    /// Decision 3: every threshold is on exactly when <see cref="Locks.DoorwayLock"/> finds no locked far-side room
    /// (the avatar's own room never counts). Only a real difference is written; true = at least one threshold changed.
    /// </summary>
    public bool ApplyLocks(IReadOnlyDictionary<string, string>? locks, string avatarRoom)
    {
        bool changed = false;
        foreach (var t in Source.Thresholds)
        {
            if (!Thresholds.TryGetValue(t.Doorway, out var rid)) continue;
            bool on = Locks.DoorwayLock(t.Rooms, locks, avatarRoom) is null;
            if (EnabledOf(rid, NavigationServer3D.RegionGetEnabled) == on) continue;
            NavigationServer3D.RegionSetEnabled(rid, on);
            _enabled[rid] = on;
            changed = true;
        }
        if (changed) ChangedAtIteration = NavigationServer3D.MapGetIterationId(Map);
        return changed;
    }

    /// <summary>Switches one link; true only when its state really changed (an unknown owner changes nothing).</summary>
    public bool SetLinkEnabled(ulong owner, bool on)
    {
        if (!Links.TryGetValue(owner, out var rid) || EnabledOf(rid, NavigationServer3D.LinkGetEnabled) == on) return false;
        NavigationServer3D.LinkSetEnabled(rid, on);
        _enabled[rid] = on;
        ChangedAtIteration = NavigationServer3D.MapGetIterationId(Map);
        return true;
    }

    /// <summary>
    /// The threshold region of the doorway is on — the state last written (what the server holds after its next sync),
    /// so the F9 overlay shows a lock in the frame of <see cref="ApplyLocks"/>, not one sync later. Unknown doorway: false.
    /// </summary>
    public bool ThresholdEnabled(int doorway)
        => Thresholds.TryGetValue(doorway, out var rid) && EnabledOf(rid, NavigationServer3D.RegionGetEnabled);

    /// <summary>Releases links, regions and the map; the server drops the map at its next sync.</summary>
    public void Free()
    {
        foreach (var rid in Links.Values) NavigationServer3D.FreeRid(rid);
        foreach (var rid in Thresholds.Values) NavigationServer3D.FreeRid(rid);
        foreach (var rid in Storeys) NavigationServer3D.FreeRid(rid);
        NavigationServer3D.FreeRid(Map);
    }

    /// <summary>
    /// The shortest path over all storeys, thresholds and links (query mask all layers). Contract of
    /// <see cref="NavPath"/>: only a link's entry point carries its owner, every other point 0.
    /// </summary>
    public NavPath Query(Vec3 from, Vec3 to)
    {
        var query = new NavigationPathQueryParameters3D
        {
            Map = Map,
            StartPosition = ToGodot(from),
            TargetPosition = ToGodot(to),
            NavigationLayers = NavLayers.All,
            MetadataFlags = NavigationPathQueryParameters3D.PathMetadataFlags.All,
        };
        var result = new NavigationPathQueryResult3D();
        NavigationServer3D.QueryPath(query, result);
        var path = result.Path;
        var types = result.PathTypes;
        var ids = result.PathOwnerIds;
        var points = new Vec3[path.Length];
        var owners = new ulong[path.Length];
        for (int i = 0; i < path.Length; i++)
        {
            points[i] = new Vec3(path[i].X, path[i].Y, path[i].Z);
            bool link = i < types.Length && types[i] == (int)NavigationPathQueryResult3D.PathSegmentType.Link;
            owners[i] = link && i < ids.Length ? (ulong)ids[i] : 0;
        }
        return new NavPath(points, owners, result.PathLength);
    }

    public Vec3 Closest(Vec3 p)
    {
        var c = NavigationServer3D.MapGetClosestPoint(Map, ToGodot(p));
        return new Vec3(c.X, c.Y, c.Z);
    }

    public Vec3 ClosestOnVertical(Vec3 p, double halfHeight) => ClosestOnVertical(Map, p, halfHeight);

    /// <summary>
    /// <see cref="IPathProvider.ClosestOnVertical"/> on any map: <c>MapGetClosestPointToSegment</c> from the top of the band
    /// down to its bottom, without collision mode. Godot 4.7.2 prefers a polygon the segment pierces (the piercing point,
    /// the highest one first) over every edge point, so over the mesh the answer lies straight below/above
    /// <paramref name="p"/> (check N14).
    /// </summary>
    public static Vec3 ClosestOnVertical(Rid map, Vec3 p, double halfHeight)
    {
        var top = new Vector3((float)p.X, (float)(p.Y + halfHeight), (float)p.Z);
        var bottom = new Vector3((float)p.X, (float)(p.Y - halfHeight), (float)p.Z);
        var c = NavigationServer3D.MapGetClosestPointToSegment(map, top, bottom, false);
        return new Vec3(c.X, c.Y, c.Z);
    }

    /// <summary>The state last written, else what the server reports (nothing written yet: its synced state).</summary>
    private bool EnabledOf(Rid rid, System.Func<Rid, bool> server) => _enabled.TryGetValue(rid, out var on) ? on : server(rid);

    private static Rid Region(Rid map, NavigationMesh mesh, uint layers)
    {
        var rid = NavigationServer3D.RegionCreate();
        NavigationServer3D.RegionSetUseAsyncIterations(rid, false);
        NavigationServer3D.RegionSetMap(rid, map);
        NavigationServer3D.RegionSetNavigationLayers(rid, layers);
        NavigationServer3D.RegionSetOwnerId(rid, 0);   // only links carry owners in a path (decision 13)
        NavigationServer3D.RegionSetNavigationMesh(rid, mesh);
        return rid;
    }

    private static Vector3 ToGodot(Vec3 v) => new((float)v.X, (float)v.Y, (float)v.Z);
}
