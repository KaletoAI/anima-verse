using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Scene;
using AnimaNative.Sync;
using Godot;

namespace AnimaNative.World;

/// <summary>Task 44: live stream probes and pins, the queued up/down adapter, and mount ownership.</summary>
public sealed partial class WorldBuilder
{
    private readonly Dictionary<string, LocationInfo> _residentPlaces = new();
    private readonly Dictionary<string, Func<bool>> _revealValidity = new();
    private readonly Dictionary<string, Func<bool>> _rebuildValidity = new();
    private Func<bool>? _sweepValidity;
    private readonly Dictionary<string, int> _storeyMemory = new();
    private readonly Dictionary<string, LocationSlot> _rebuilding = new();
    private readonly Dictionary<string, string?> _streamPins = new();
    private SceneLibrary<ScenePayload> _scenes = null!;
    private TimerQueue? _residencyTimers;
    private WorldStats _residencyStats = new();
    private JsonElement _streamMap;
    private string? _bootPin, _openPin;
    private bool _residencyBootDone, _residencyStopped;

    /// <summary>Task 44 / RS: achieved rings, target wishes and settlement (including retry waits).</summary>
    public ResidencyDriver<LocationInfo> Residency { get; private set; } = null!;
    /// <summary>Called at the 1 Hz tick before reading probes; the Main partial supplies the rendered avatar and camera target.</summary>
    public Action? RefreshStreamView { get; set; }
    /// <summary>Committed upward/downward stages, useful for a streaming probe; ready is published only after near commits.</summary>
    public event Action<string, Ring>? ResidencyChanged;
    public event Action<LocationSlot>? Ready;
    public IReadOnlyDictionary<string, string?> StreamPins => _streamPins;
    /// <summary>Keep an existing open view while its driver-owned replacement is awaiting assets.</summary>
    public bool IsRebuilding(string id) => _rebuilding.ContainsKey(id);

    private void InitResidency(JsonElement map, string? bootPin)
    {
        _streamMap = map.Clone(); _bootPin = bootPin;
        _openPin = AvatarOf(map, _residentPlaces.Values.ToList()).LocationId;
        _residencyTimers = new TimerQueue(() => Time.GetTicksMsec());
        _scenes = new SceneLibrary<ScenePayload>(async id =>
        {
            using var doc = await _source.GetLocationSceneAsync(id);
            return doc is null ? null : ScenePayload.Parse(doc.RootElement);
        }, scene => scene.Signature);
        _scenes.OnScene += (id, scene) =>
        {
            if (!_residencyStopped && _slots.TryGetValue(id, out var slot)
                && LocationView.SceneChanged(slot.Signature, scene?.Signature)
                && _residentPlaces.TryGetValue(id, out var loc))
            {
                if (_sweepValidity is { } validity)
                {
                    if (!validity()) { _scenes.Forget(id); return; }
                    _rebuildValidity[id] = validity;
                }
                _rebuilding[id] = slot;
                Residency.Rebuild(id, loc);
            }
        };
        Residency = new ResidencyDriver<LocationInfo>(UpResident, DownResident, new FocusQueue(2), _residencyTimers);
    }

    /// <summary>
    /// Task 44 / main.ts streamPoints: one snapshot with rendered-avatar XZ and camera-target XZ (never the eye).
    /// The boot pin survives until figures are ready; current/travel come from the avatar's latest accepted map.
    /// </summary>
    public void SetStreamView(JsonElement map, IEnumerable<(double X, double Z)> points, bool bootDone = true)
    {
        _streamMap = map.Clone(); _points = points.ToList(); _residencyBootDone = bootDone;
    }

    private void SyncStreamPins()
    {
        string? current = null, travel = null;
        var avatar = Json.Str(_streamMap, "avatar");
        foreach (var row in Json.Arr(_streamMap, "characters"))
            if (avatar.Length > 0 && Json.Str(row, "name") == avatar)
            {
                current = Json.Str(row, "location_id");
                if (row.TryGetProperty("travel", out var t) && t.ValueKind == JsonValueKind.Object)
                    travel = Json.Str(t, "target_id");
                break;
            }
        _streamPins["current"] = current; _streamPins["travel"] = travel;
        _streamPins["open"] = _openPin; _streamPins["boot"] = _residencyBootDone ? null : _bootPin;
    }
    private bool IsPinned(string id) => _streamPins.Values.Any(p => !string.IsNullOrEmpty(p) && p == id);
    private double DistanceOf(string id) => _residentPlaces.TryGetValue(id, out var loc)
        ? LocationView.PlaceDistance(loc, _points) : double.PositiveInfinity;

    /// <summary>
    /// Task 44 / tickStreamRings: at boot, reveal, and 1 Hz with full 150/180, 560/672 m hysteresis.
    /// Compare against the driver's TARGET, as the browser does; unchanged wishes must not invalidate an await.
    /// Queue distance callbacks read the latest probes when a slot frees, not at submission time.
    /// </summary>
    public void TickStreamRings()
    {
        if (_residencyStopped || Residency is null) return;
        RefreshStreamView?.Invoke();
        SyncStreamPins();
        foreach (var (id, loc) in _residentPlaces)
        {
            var ring = SceneView.RingFor(DistanceOf(id), Residency.Target(id), IsPinned(id), 520);
            if (ring != Residency.Target(id)) Residency.Want(id, loc, ring, () => DistanceOf(id));
        }
    }

    /// <summary>Wait for current queue passes, including immediate follow-up teardown, but not a timed retry.</summary>
    public Task WhenResidencyIdle() => Residency.WhenIdle();

    /// <summary>Task 44: cancel retries and invalidate in-flight awaits before templates/world nodes leave the scene.</summary>
    public void StopResidency()
    {
        if (_residencyStopped || Residency is null) return;
        _residencyStopped = true; RefreshStreamView = null;
        _rebuilding.Clear(); _rebuildValidity.Clear();
        foreach (var id in _known.ToArray()) { Residency.Drop(id); _scenes.Forget(id); }
    }

    private async Task<ResidencyStep> UpResident(string id, LocationInfo loc, Ring from, Func<bool> driverAlive)
    {
        bool Alive() => !_residencyStopped && driverAlive()
            && (!_revealValidity.TryGetValue(id, out var valid) || valid())
            && (!_rebuildValidity.TryGetValue(id, out var rebuildValid) || rebuildValid())
            && _places is not null && GodotObject.IsInstanceValid(_places) && !_places.IsQueuedForDeletion();
        if (from == Ring.Gone)
        {
            LocationSlot? built = null;
            try
            {
                var scene = await _scenes.Request(id);
                if (!Alive()) return Abort();
                if (scene is null)
                {
                    // A 404 is a valid empty tile, not a transient fetch failure. No invented recipe or verify rows.
                    var group = new Node3D { Name = "Loc_" + NodeName(id),
                        Position = new Vector3((float)loc.PosX!.Value, (float)Height!.GroundAt(loc.PosX.Value, loc.PosZ!.Value), (float)loc.PosZ.Value),
                        Rotation = new Vector3(0, (float)(loc.YawDeg * Math.PI / 180), 0) };
                    group.SetMeta("location_id", id);
                    var (building, nature) = LocationView.Kind(loc);
                    built = new LocationSlot { Loc = loc, Group = group, Ring = Ring.Far, Width = LocationView.FootprintWidth(loc),
                        IsBuilding = building, Height = Overview.EventPinRule.DefaultPlaceHeight(building, nature, LocationView.DetectStyle(loc)) };
                }
                else built = await BuildShellAsync(loc, scene, Height!, _residencyStats, _openPin == id, Alive);
                if (!Alive()) { FreeSlot(built); return Abort(); }
                built.Open = built.Openable && _openPin == id; // Opening can change while the shell awaits assets.
                if (_storeyMemory.TryGetValue(id, out var level)
                    && (built.Storeys.Buttons.Count == 0 ? level == 0 : built.Storeys.Buttons.Any(b => b.Level == level)))
                    built.LevelFilter = level;
                _places!.AddChild(built.Group);
                if (built.Storeys.BoundaryMarks is { } bm) _places.AddChild(bm);
                _slots[id] = built;
                ResidencyChanged?.Invoke(id, Ring.Far);
                if (Residency.Target(id) == Ring.Far) FinishRebuild(id, built);
                return ResidencyStep.Ok;
            }
            catch (Exception e)
            {
                if (built is not null) FreeSlot(built);
                _log($"location {id} shell failed: {e.Message}");
                return Alive() ? ResidencyStep.Failed : Abort();
            }
        }
        if (!_slots.TryGetValue(id, out var slot)) return ResidencyStep.Aborted;
        slot.Promoting = true;
        try
        {
            await MountDetailAsync(slot, _residencyStats, Alive);
            if (!Alive()) { UnmountDetail(slot); return Abort(); }
            var buildingTier = LocationView.BuildingTier(Ring.Near, _viewCamera.DistanceTo(slot.Group.Position), slot.Width, slot.BuildingTier);
            var interiorTier = LocationView.InteriorTier(Ring.Near, slot.AreaDetail, slot.Open);
            await SwapTierAsync(slot, true, buildingTier);
            slot.BuildingTier = buildingTier;
            if (!Alive()) { UnmountDetail(slot); return Abort(); }
            await SwapTierAsync(slot, false, interiorTier);
            slot.InteriorTier = interiorTier;
            if (!Alive()) { UnmountDetail(slot); return Abort(); }
            slot.BuildingTier = buildingTier; slot.InteriorTier = interiorTier;
            if (slot.Scene is { } scene && slot.IsBuilding) slot.Storeys.BuildDoorMarks(slot.Group, scene);
            slot.Storeys.ApplyLocks(_locks, id);
            slot.Fade.Collect(slot.Group);
            slot.Storeys.Apply(slot.LevelFilter, slot.Fade.Fade, slot.Openable, slot.Fade);
            RefreshVerify(slot, _residencyStats);
            slot.Ring = Ring.Near; slot.Ready = true; slot.MeshVersion++;
            ResidencyChanged?.Invoke(id, Ring.Near); Ready?.Invoke(slot);
            FinishRebuild(id, slot);
            return ResidencyStep.Ok;
        }
        catch (Exception e)
        {
            UnmountDetail(slot);
            _log($"location {id} detail failed: {e.Message}");
            return Alive() ? ResidencyStep.Failed : Abort();
        }
        finally { slot.Promoting = false; }
        ResidencyStep Abort()
        {
            if (Residency.Target(id) == Ring.Gone) _scenes.Forget(id);
            if (_rebuildValidity.TryGetValue(id, out var rebuildValid) && !rebuildValid())
            {
                Residency.Drop(id); _scenes.Forget(id); _rebuildValidity.Remove(id); _rebuilding.Remove(id);
            }
            if (_revealValidity.TryGetValue(id, out var valid) && !valid())
            {
                Residency.Drop(id); _scenes.Forget(id);
                _known.Remove(id); _residentPlaces.Remove(id); _revealValidity.Remove(id);
            }
            return ResidencyStep.Aborted;
        }
    }

    private void FinishRebuild(string id, LocationSlot slot)
    {
        _rebuildValidity.Remove(id);
        if (_rebuilding.Remove(id, out var previous)) Remounted?.Invoke(previous, slot);
    }

    /// <summary>Near owns indoor model records and door marks; primitives and room groups belong to the shell.</summary>
    private async Task MountDetailAsync(LocationSlot slot, WorldStats stats, Func<bool> alive)
    {
        if (slot.Scene is not { } scene || slot.Fade.Interior is null) return;
        var models = new ModelStats();
        string tier = LocationView.InteriorTier(Ring.Near, slot.AreaDetail, slot.Open);
        foreach (var spec in scene.Models.Where(m => m.Role != "building" && !LocationView.IsOutdoor(scene, m.RoomId)))
        {
            Node3D parent = slot.Storeys.Rooms.TryGetValue(spec.RoomId, out var rg) ? rg.Node : slot.Fade.Interior;
            var rec = new PlacedModel { Spec = spec, Parent = parent, Url = ModelVariants.PickModelVariant(spec, tier),
                Lift = GroundLift(slot.Group, spec, Height!, slot.Group.Position.Y) };
            slot.Placements.Add(rec); // Ownership precedes every await and every registration.
            rec.Node = await SceneModels.PlaceAsync(_models, spec, tier, SceneModels.KindOf(spec), parent, rec.Lift, models, _materials, alive);
            rec.Placeholder = rec.Node is not null && SceneModels.IsPlaceholder(rec.Node);
            if (rec.Node is { } node)
            {
                if (!rec.Placeholder) { rec.Slots = FillSlots(node, spec); rec.Door = DoorProps.Register(scene, spec, node); }
                rec.Cut = CutPlacement(slot.Group, rec);
            }
            if (spec.Light is { } light && PropLights is { } pool)
                rec.LightId = pool.Register(light, LightPosition(slot.Group, rec), spec.RoomId.Length > 0 ? $"{slot.Loc.Id}:{spec.RoomId}" : "");
            RefreshPlacementWater(slot.Group, rec, Height!.WaterRaster());
            if (rg is not null && !SceneView.RoomVisible(false, rg.Level, slot.LevelFilter)) models.Storey++;
            if (rec.Cut is { } h) { stats.CutPlacements++; stats.CutSurfaces += h.Entries.Count; stats.CutFallbacks += h.Fallbacks; }
        }
        Merge(stats.Models, models);
        DeriveStands(slot);
    }

    private void RefreshVerify(LocationSlot slot, WorldStats stats)
    {
        if (slot.Scene is null) return;
        var verify = new SceneVerifier { Total = slot.Placements.Count };
        var g = slot.Group;
        var origin = new Overview.Vec3(g.Position.X, g.Position.Y, g.Position.Z);
        foreach (var m in slot.Measured) verify.Primitive(m.Name, WorldBox(m.Local, g.Transform), origin, g.Rotation.Y, m.Targets);
        foreach (var rec in slot.Placements) VerifyPlacement(verify, rec.Spec, rec.Node, rec.Lift, g, origin, g.Rotation.Y);
        var report = verify.Report(slot.Loc.Id);
        stats.VerifyChecked += report.Checked - (slot.Verify?.Checked ?? 0);
        stats.VerifyRows += report.Rows.Count - (slot.Verify?.Rows.Count ?? 0);
        slot.Verify = report; LogVerify(report);
    }

    /// <summary>
    /// Task 44: boot stats describe the final committed mounts, not the low-shell work preceding promotion.
    /// Count the current template for every real placement; placeholders/missing records and unmounted indoor
    /// specs retain their original meanings. This keeps S3c/verify/fidelity's numerical oracles meaningful.
    /// </summary>
    private async Task SnapshotLocationModels(WorldStats stats)
    {
        stats.Models = new ModelStats();
        stats.Buildings = stats.BuildingsCompressed = stats.BuildingVertices = stats.BuildingIndices = 0;
        stats.CutPlacements = stats.CutSurfaces = stats.CutFallbacks = 0;
        foreach (var slot in _slots.Values)
        {
            if (slot.Scene is not { } scene) continue;
            var models = stats.Models;
            if (slot.Ring == Ring.Far)
                models.Interior += scene.Models.Count(m => m.Role != "building" && !LocationView.IsOutdoor(scene, m.RoomId));
            foreach (var rec in slot.Placements)
            {
                if (rec.Placeholder) models.Placeholders++;
                else if (rec.Node is null) models.Missing++;
                else
                {
                    models.Placed[SceneModels.KindOf(rec.Spec)]++;
                    var template = await _models.GetAsync(rec.Url);
                    if (template is not null)
                    {
                        models.Vertices += template.Counts.Vertices; models.Indices += template.Counts.Indices;
                        if (template.Compressed) models.Compressed++;
                        if (rec.IsBuilding)
                        {
                            stats.Buildings++; if (template.Compressed) stats.BuildingsCompressed++;
                            stats.BuildingVertices += template.Counts.Vertices; stats.BuildingIndices += template.Counts.Indices;
                        }
                    }
                    if ((rec.IsBuilding ? slot.BuildingTier : slot.InteriorTier) == "low") models.Low++;
                    else models.Full++;
                    if (rec.IsBuilding && rec.Spec.Display != "ground" && !rec.Spec.PlanHull && slot.Open) models.Faded++;
                }
                if (!rec.IsBuilding && !LocationView.IsOutdoor(scene, rec.Spec.RoomId)
                    && slot.Storeys.Rooms.TryGetValue(rec.Spec.RoomId, out var room)
                    && !SceneView.RoomVisible(false, room.Level, slot.LevelFilter)) models.Storey++;
                if (rec.Cut is { } h) { stats.CutPlacements++; stats.CutSurfaces += h.Entries.Count; stats.CutFallbacks += h.Fallbacks; }
            }
        }
    }

    private void DownResident(string id, LocationInfo loc, Ring from)
    {
        if (!_slots.TryGetValue(id, out var slot)) return;
        _storeyMemory[id] = slot.LevelFilter;
        if (from == Ring.Near) UnmountDetail(slot);
        else
        {
            _slots.Remove(id); FreeSlot(slot); _scenes.Forget(id);
            Dropped?.Invoke(slot);
        }
        ResidencyChanged?.Invoke(id, from == Ring.Near ? Ring.Far : Ring.Gone);
    }

    private void UnmountDetail(LocationSlot slot)
    {
        slot.Generation++; slot.Ready = false; slot.Ring = Ring.Far;
        slot.Storeys.DropDoorMarks();
        if (slot.Scene is { } scene)
            foreach (var rec in slot.Placements.Where(r => !r.IsBuilding && !LocationView.IsOutdoor(scene, r.Spec.RoomId)).ToArray())
            { ReleasePlacement(rec); slot.Placements.Remove(rec); }
        foreach (var rec in slot.Placements) rec.WantUrl = null;
        slot.Stands.SitSpots.Clear(); slot.Stands.LieSpots.Clear();
        if (GodotObject.IsInstanceValid(slot.Group) && !slot.Group.IsQueuedForDeletion())
        {
            slot.Fade.Collect(slot.Group); slot.MeshVersion++;
            DeriveStands(slot);
        }
    }

    private void FreeSlot(LocationSlot slot)
    {
        slot.Generation++; slot.Ready = false;
        foreach (var rec in slot.Placements) ReleasePlacement(rec);
        slot.Placements.Clear();
        if (GodotObject.IsInstanceValid(slot.Group))
        {
            if (Mirrors is { } mirrors && GodotObject.IsInstanceValid(mirrors)) mirrors.DetachUnder(slot.Group);
            slot.Group.GetParent()?.RemoveChild(slot.Group); slot.Group.Free();
        }
        if (slot.Storeys.BoundaryMarks is { } bm && GodotObject.IsInstanceValid(bm)) { bm.GetParent()?.RemoveChild(bm); bm.Free(); }
    }

    /// <summary>Task 44 ownership ledger: placement registrations, ghosts, sheets and cloned nodes only; never cached meshes/materials/shaders.</summary>
    private void ReleasePlacement(PlacedModel rec)
    {
        rec.WantUrl = null;
        if (rec.LightId is { } id)
        {
            if (PropLights is { } pool && GodotObject.IsInstanceValid(pool)) pool.Remove(id);
            rec.LightId = null;
        }
        DropPlacementGhost(rec);
        if (rec.WaterSheets is { } sheets)
        {
            foreach (var sheet in sheets) if (GodotObject.IsInstanceValid(sheet)) { sheet.GetParent()?.RemoveChild(sheet); sheet.Free(); }
            sheets.Clear(); rec.WaterSheets = null;
        }
        if (rec.Node is { } node && GodotObject.IsInstanceValid(node))
        {
            if (Mirrors is { } mirrors && GodotObject.IsInstanceValid(mirrors)) mirrors.DetachUnder(node);
            node.GetParent()?.RemoveChild(node); node.Free();
        }
        rec.Node = null; rec.Cut = null; rec.Slots = null; rec.Door = null;
    }
}
