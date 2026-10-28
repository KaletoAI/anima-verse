using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Embody;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.World;

/// <summary>Task 50 / E7-T5: owner-scoped readiness pins share Task 44's live residency map.</summary>
public sealed partial class WorldBuilder : IReadinessDeps
{
    private JsonElement _readinessMap;
    private JsonElement? _avatarReadinessMap;

    /// <summary>Task 50: figure polls reconcile before residency's reveal pass, so supply that very payload first.</summary>
    public void SetPlayerReadinessMap(JsonElement? map) => _avatarReadinessMap = map?.Clone();
    private readonly List<(string Id, TileFrame Frame, P2[] Boundary, double Area)> _readinessFootprints = new();

    /// <summary>
    /// Task 50 / main.ts placeAt: smallest rotated footprint, including payload-only places before discovery.
    /// A gone/unmounted destination must still hold a teleport. Rebuild geometry once per accepted avatar/stream-map snapshot.
    /// </summary>
    public string? PlaceAt(double x, double z)
    {
        var map = _avatarReadinessMap ?? _streamMap;
        if (!_readinessMap.Equals(map))
        {
            _readinessMap = map;
            _readinessFootprints.Clear();
            var payload = map.ValueKind == JsonValueKind.Object ? LocationInfo.ParseList(map) : new();
            foreach (var loc in _residentPlaces.Values.Concat(payload.Where(l => !_residentPlaces.ContainsKey(l.Id))))
            {
                if (!loc.IsPlaced || loc.Boundary is not { Length: >= 3 } boundary) continue;
                var polygon = SceneView.SanitizePolygon(boundary.Select(p => new P2(p.X,p.Z)).ToArray());
                if (polygon is null) continue;
                _readinessFootprints.Add((loc.Id, new(new Vec3(loc.PosX!.Value,0,loc.PosZ!.Value),loc.YawDeg*Math.PI/180),
                    polygon, Math.Abs(SceneView.PolygonArea(polygon))));
            }
        }
        string? best = null; double area = double.PositiveInfinity;
        foreach (var footprint in _readinessFootprints)
        {
            if (footprint.Area >= area) continue;
            var p = SceneView.WorldToTile(footprint.Frame,x,z);
            if (!SceneView.PointInPolygon(p.X,p.Z,footprint.Boundary)) continue;
            best = footprint.Id; area = footprint.Area;
        }
        return best;
    }
    public bool IsReady(string id) => _slots.TryGetValue(id, out var slot) && slot.Ring == Ring.Near && slot.Ready;

    /// <summary>Each owner holds one place; teleport, approach and entry cannot release another owner's pin.</summary>
    public void Pin(string id, string owner)
    {
        if (_streamPins.TryGetValue(owner, out var held) && held == id) return;
        _streamPins[owner] = id;
        TickStreamRings();
    }
    public void Release(string id, string owner)
    {
        if (_streamPins.TryGetValue(owner, out var held) && held == id) _streamPins.Remove(owner);
    }
}
