using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>What one model tick did (<see cref="WorldBuilder.TickModels"/>), for the log and the check.</summary>
public sealed class ModelTickResult
{
    /// <summary>The tier swaps started this tick (await them to see their outcome).</summary>
    public List<Task<int>> Swaps { get; } = new();
    /// <summary>Locations whose datum moved, placements whose lift moved, places whose seats moved (a height revision).</summary>
    public int Redatumed, Relifted, SeatsMoved;
}

/// <summary>
/// The mounted models after the mount — main.ts <c>tickModelTiers</c> (once a second: the height revision's re-datum and
/// re-lift, then the building and interior tiers) and the 60 s scene sweep (<c>requestServerModels</c> →
/// <c>SceneLibrary.sweep</c> → <c>driver.rebuild</c>).
/// </summary>
public sealed partial class WorldBuilder
{
    /// <summary><c>LOD_TICK_MS</c> (main.ts): the tier and re-datum tick, in seconds.</summary>
    public const double ModelTickS = 1.0;
    /// <summary>The scene sweep interval (main.ts <c>setInterval(requestServerModels, 60_000)</c>), in seconds.</summary>
    public const double SweepIntervalS = 60.0;

    private double _modelClock;
    private int _heightRevision;
    private Vector3 _viewCamera;
    private bool _sweeping;

    /// <summary>A location was mounted again from a changed scene (<see cref="SweepAsync"/>): the old slot is gone.</summary>
    public event Action<LocationSlot, LocationSlot>? Remounted;

    /// <summary>The model half of the per-frame pass: once a second, <see cref="TickModels"/>.</summary>
    private void StepModelClock(double dt, Vector3 camera)
    {
        _viewCamera = camera;
        _modelClock += dt;
        if (_modelClock < ModelTickS) return;
        _modelClock = 0;
        TickModels(camera);
    }

    /// <summary>
    /// <c>tickModelTiers</c>: when the height field has a new revision, every location is put back on the ground under
    /// its pin (<c>redatumTile</c>) and its placements re-lifted (<c>reliftScene</c>); then every location asks for its
    /// building tier (far ring → low, near → the 45/60 m hysteresis on the camera distance minus the footprint's half
    /// diagonal) and its interior tier (far → low, a closed area-detail scene → low, else full) and swaps the models of a
    /// group whose tier moved, in place (<see cref="SwapTierAsync"/>).
    /// </summary>
    public ModelTickResult TickModels(Vector3 camera)
    {
        var result = new ModelTickResult();
        bool heightMoved = Height is not null && Height.Revision != _heightRevision;
        if (heightMoved) _heightRevision = Height!.Revision;
        foreach (var slot in _slots.Values.ToList())
        {
            if (!GodotObject.IsInstanceValid(slot.Group)) continue;
            if (heightMoved)
            {
                var (datumMoved, relifted, seats) = Redatum(slot);
                if (datumMoved) result.Redatumed++;
                result.Relifted += relifted;
                if (seats) result.SeatsMoved++;
            }
            var b = LocationView.BuildingTier(slot.Ring, camera.DistanceTo(slot.Group.Position), slot.Width, slot.BuildingTier);
            if (b != slot.BuildingTier)
            {
                slot.BuildingTier = b;
                result.Swaps.Add(SwapTierAsync(slot, true, b));
            }
            var i = LocationView.InteriorTier(slot.Ring, slot.AreaDetail, slot.Open);
            if (i != slot.InteriorTier)
            {
                slot.InteriorTier = i;
                result.Swaps.Add(SwapTierAsync(slot, false, i));
            }
        }
        if (result.Redatumed > 0 || result.Relifted > 0)
            _log($"height revision {_heightRevision}: {result.Redatumed} location datum(s) moved, {result.Relifted} placement(s) re-lifted, "
                 + $"seats moved in {result.SeatsMoved} location(s)");
        return result;
    }

    /// <summary>
    /// <c>setSceneModelTier(tile, group, tier)</c>: every record of the group (<paramref name="building"/> = role building,
    /// else every other role) resolves its URL for the tier; the same URL is a no-op, a new one is loaded while the old
    /// mesh keeps standing, and only the newest wish of a record that is still mounted is installed. A load that fails
    /// keeps what stands. Returns how many records changed their mesh.
    /// </summary>
    public async Task<int> SwapTierAsync(LocationSlot slot, bool building, string tier)
    {
        int generation = slot.Generation;
        int swapped = 0;
        var jobs = slot.Placements.Where(r => r.IsBuilding == building).Select(async rec =>
        {
            var url = ModelVariants.PickModelVariant(rec.Spec, tier);
            if (url.Length == 0) return;
            if (url == rec.Url) { rec.WantUrl = url; return; }
            if (rec.WantUrl == url) return;
            rec.WantUrl = url;
            var template = await _models.GetAsync(url);
            if (rec.WantUrl != url || slot.Generation != generation || !IsMounted(slot)) return;
            rec.WantUrl = null;
            if (template is null) return;   // keep what stands
            var placed = ModelPlacement.Place(ModelCache.Instance(template), rec.Spec);
            if (!rec.IsBuilding) SceneModels.CastNone(placed);
            var old = rec.Node;
            // A real mesh from here on (a stand-in box takes no cutouts and no clip, a mesh does).
            rec.Placeholder = false;
            rec.Url = url;
            if (rec.IsBuilding) InstallBuilding(slot, rec, placed);
            else InstallPlacement(slot, rec, placed);
            if (old is not null && GodotObject.IsInstanceValid(old))
            {
                old.GetParent()?.RemoveChild(old);
                old.QueueFree();
            }
            swapped++;
        }).ToList();
        await Task.WhenAll(jobs);
        if (swapped > 0 && IsMounted(slot) && slot.Generation == generation)
        {
            slot.Fade.Collect(slot.Group);
            slot.MeshVersion++;
            _log($"location {slot.Loc.Id} ({slot.Loc.Name}): {(building ? "building" : "interior")} models → {tier} ({swapped} swapped)");
        }
        return swapped;
    }

    private bool IsMounted(LocationSlot slot)
        => _slots.TryGetValue(slot.Loc.Id, out var s) && ReferenceEquals(s, slot) && GodotObject.IsInstanceValid(slot.Group);

    /// <summary>
    /// The tier swap of a non-building record: the fresh mesh sits on its composed <c>bottom_y</c>, takes the lift the
    /// height field says NOW (§ A16.9, from lift 0 — the same funnel as the mount), hangs in the record's parent and gets
    /// the record's cuts again (they belong to the placement, not to the mesh).
    /// </summary>
    private void InstallPlacement(LocationSlot slot, PlacedModel rec, Node3D placed)
    {
        double lift = Height is null ? rec.Lift : GroundLift(slot.Group, rec.Spec, Height, slot.Group.Position.Y);
        if (lift != 0) placed.Position += new Vector3(0, (float)lift, 0);
        rec.Parent.AddChild(placed);
        var old = rec.Node;
        // The ghost belongs to the mesh that is going away (tier swap) — a new one is asked for below.
        DropPlacementGhost(rec);
        rec.Node = placed;
        rec.Lift = lift;
        // The slots and the door follow the fresh mesh (fillSlots / retargetDoorProp), before its cuts; the light its lift.
        if (old is not null) Mirrors?.DetachUnder(old);
        rec.Slots = rec.Placeholder ? null : FillSlots(placed, rec.Spec);
        if (rec.Door is { } door) DoorProps.Retarget(door, placed);
        rec.Cut = CutPlacement(slot.Group, rec);
        if (rec.LightId is { } id) PropLights?.Move(id, LightPosition(slot.Group, rec));
        RefreshPlacementWater(slot.Group, rec, Height?.WaterRaster());
    }

    /// <summary>
    /// The tier swap of a building record (<c>applyBuildingModel</c> on the fresh mesh): the old mesh leaves the fade
    /// lists, the new one joins them with its cutouts; a model arriving where none stood drops the far-view shell (not a
    /// roof-only one, which keeps it); <c>tile.height</c> is measured again.
    /// </summary>
    private void InstallBuilding(LocationSlot slot, PlacedModel rec, Node3D placed)
    {
        var fade = slot.Fade;
        if (rec.Node is { } old)
        {
            fade.RoofParts.Remove(old);
            fade.GroundModels.Remove(old);
        }
        if (rec.Cut is { } h) fade.Cutouts.Remove(h);
        rec.Cut = null;
        if (!rec.Spec.RoofOnly && slot.FarShell.Count > 0)
        {
            foreach (var m in slot.FarShell)
            {
                fade.RoofParts.Remove(m);
                if (GodotObject.IsInstanceValid(m)) m.QueueFree();
            }
            slot.FarShell.Clear();
        }
        slot.Group.AddChild(placed);
        rec.Node = placed;
        ApplyBuildingModel(slot.Group, fade, rec);
        if (MeasureBuildings(slot) is { } height)
        {
            slot.Height = height;
            slot.HeightMeasured = true;
        }
    }

    /// <summary><c>tile.height</c>: the building models' box (a roof-only one together with the far shell).</summary>
    private static double? MeasureBuildings(LocationSlot slot)
    {
        Aabb? box = null;
        foreach (var rec in slot.Placements)
            if (rec.IsBuilding && rec.Node is { } n && GodotObject.IsInstanceValid(n))
            {
                var b = ModelPlacement.Measure(n, Transform3D.Identity);
                box = box is { } a ? a.Merge(b) : b;
            }
        foreach (var m in slot.FarShell)
            if (GodotObject.IsInstanceValid(m) && m.Mesh is { } mesh)
            {
                var b = m.Transform * mesh.GetAabb();
                box = box is { } a ? a.Merge(b) : b;
            }
        return box is { } r && r.Size.Y > 0 ? r.Size.Y : null;
    }

    /// <summary>
    /// <c>applySceneBuilding</c> + <c>applyBuildingModel</c> for a placed building record: display <c>ground</c> and
    /// <c>plan_hull</c> stay (the cutouts reveal the interior), every other display (<c>shell</c>, <c>shell_area</c>,
    /// a roof-only lid) is a roof part the crossfade takes away; a ground model hides in a basement view; the spec's
    /// <c>cutouts</c> go on the model whatever its display (the browser's rule — the shell-area flag only keeps them shut).
    /// </summary>
    private static void ApplyBuildingModel(Node3D group, LocationFade fade, PlacedModel rec)
    {
        var spec = rec.Spec;
        var node = rec.Node!;
        bool keep = spec.Display == "ground" || spec.PlanHull;
        if (!keep) fade.RoofParts.Add(node);
        if (spec.Display == "ground") fade.GroundModels.Add(node);
        if (!rec.Placeholder && spec.Cutouts.Length > 0)
        {
            rec.Cut = CutPlacement(group, rec);
            if (rec.Cut is { } h) fade.Cutouts.Add(h);
        }
    }

    /// <summary>
    /// The cuts of one placed record, in WORLD terms (sceneRecipe.ts): a building's <c>cutouts</c> and a room model's
    /// <c>clip_outline</c> through <c>tileToWorld</c> (x/z only — a later re-datum moves the frame in y, which these never
    /// read), a prop's <c>cut_plane</c> through the parent's frame (<c>cutPlaneFor</c>, also on a placeholder box).
    /// </summary>
    public static CutHandle? CutPlacement(Node3D group, PlacedModel rec)
    {
        var spec = rec.Spec;
        var node = rec.Node;
        if (node is null) return null;
        var frame = new TileFrame(new Overview.Vec3(group.Position.X, group.Position.Y, group.Position.Z), group.Rotation.Y);
        P2 W(double x, double z) { var w = SceneView.TileToWorld(frame, x, z); return new P2(w.X, w.Z); }
        List<P2>? clip = null;
        List<IReadOnlyList<P2>>? cutouts = null;
        CutPlaneData? plane = null;
        if (spec.Role == "building")
        {
            if (!rec.Placeholder && spec.Cutouts.Length > 0)
                cutouts = spec.Cutouts.Select(poly => (IReadOnlyList<P2>)poly.Select(p => W(p.X, p.Z)).ToList()).ToList();
        }
        else
        {
            plane = PlaneOf(group, rec);
            if (!rec.Placeholder && spec.ClipOutline.Length >= 3)
                clip = spec.ClipOutline.Take(ClipMath.ClipPointLimit).Select(p => W(p.X, p.Z)).ToList();
        }
        return CutMaterials.Apply(node, clip, cutouts, plane, n => group.Transform * ChainTo(n, group));
    }

    /// <summary><c>cutPlaneFor</c>: the payload plane through the frame of the node the placement hangs in.</summary>
    private static CutPlaneData? PlaneOf(Node3D group, PlacedModel rec)
    {
        if (rec.Spec.CutPlane is not { } cp || rec.Node is null) return null;
        var parentFrame = group.Transform * ChainTo(rec.Node.GetParent(), group);
        return DepthCutMath.CutPlane(cp.Normal, cp.Constant, CutMaterials.ColumnMajor(parentFrame));
    }

    /// <summary>
    /// <c>redatumTile</c> + <c>reliftScene</c>: the location's datum is read again under its pin (<c>tileDatumStep</c>) and
    /// the frame moves by the step; every non-building placement then takes the lift the field says now
    /// (<c>storeyGroundRelift</c>), so it ends at <c>ground(anchor) + bottom_y</c> again; a depth-cut plane follows its
    /// frame; the places data rides along (<see cref="PlaceInventory.Relift"/>: world-composed points carried by the datum
    /// step, prop-marker seats re-lifted at their lift point, corridor stands derived again). Returns whether the datum
    /// moved, how many lifts changed and whether a seat moved.
    /// </summary>
    public (bool DatumMoved, int Relifted, bool SeatsMoved) Redatum(LocationSlot slot)
    {
        if (Height is null) return (false, 0, false);
        var g = slot.Group.Position;
        var step = StoreyGround.TileDatumStep(g.Y, g.X, g.Z, Height.GroundAt);
        bool moved = step.Delta != 0;
        if (moved) slot.Group.Position = new Vector3(g.X, (float)step.Datum, g.Z);
        double datum = slot.Group.Position.Y;
        var frame = new TileFrame(new Overview.Vec3(g.X, datum, g.Z), slot.Group.Rotation.Y);
        int relifted = 0;
        var raster = Height.WaterRaster();
        foreach (var rec in slot.Placements)
        {
            if (rec.IsBuilding) continue;
            var w = SceneView.TileToWorld(frame, rec.Spec.AnchorX, rec.Spec.AnchorZ);
            var r = StoreyGround.Relift(rec.Lift, rec.Spec.Level, w.X, w.Z, datum, Height.GroundAt);
            if (r.Delta != 0)
            {
                if (rec.Node is { } n && GodotObject.IsInstanceValid(n)) n.Position += new Vector3(0, (float)r.Delta, 0);
                relifted++;
            }
            rec.Lift = r.Lift;
            if (moved && rec.Cut is { HasPlane: true } h && PlaneOf(slot.Group, rec) is { } plane) h.SetPlane(plane);
            if ((moved || r.Delta != 0) && rec.LightId is { } lid) PropLights?.Move(lid, LightPosition(slot.Group, rec));
            // reliftPlacement's water + refreshPlacementGhost: the sheets follow the lift, the ghost the new base and raster.
            RefreshPlacementWater(slot.Group, rec, raster);
        }
        if (moved || relifted > 0) slot.MeshVersion++;
        bool seats = slot.Places.Relift(frame, moved ? step.Delta : 0, Height.GroundAt);
        return (moved, relifted, seats);
    }

    /// <summary>
    /// <c>SceneLibrary.sweep</c> over the mounted locations, then <c>driver.rebuild</c> for each whose scene signature
    /// moved: the location is mounted again from the fresh payload (same ring, the open target and the shown storey
    /// carried over — main.ts keeps the storey across a rebuild through <c>storeyByPlace</c>), the new group replaces the
    /// old one, and the old slot's late work is thrown away (its generation). A failed request, a 404, an unchanged
    /// signature or a sweep still running from the last interval change nothing. Returns the remounted ids.
    /// </summary>
    public async Task<List<string>> SweepAsync(Func<bool>? stillValid = null)
    {
        var remounted = new List<string>();
        if (_sweeping || _places is null || Height is null || _library is null) return remounted;
        _sweeping = true;
        try
        {
            foreach (var slot in _slots.Values.ToList())
            {
                if (!IsMounted(slot)) continue;
                JsonDocument? doc;
                try { doc = await _source.GetLocationSceneAsync(slot.Loc.Id); }
                catch (Exception e) when (!_strict)
                {
                    _log($"scene sweep {slot.Loc.Id}: {e.Message}");
                    continue;
                }
                using (doc)
                {
                    var fresh = doc is null ? null : Json.Str(doc.RootElement, "signature");
                    if (!LocationView.SceneChanged(slot.Signature, fresh)) continue;
                    if (doc is null)
                    {
                        // A deleted layout: the browser keeps only its procedural tile; this client has none to fall
                        // back to, so the mounted scene stays until the place itself goes (dropVanished).
                        _log($"location {slot.Loc.Id} ({slot.Loc.Name}): scene gone (404) — the mounted one stays");
                        continue;
                    }
                    if (stillValid is not null && !stillValid()) return remounted;
                    if (!IsMounted(slot)) continue;
                    var stats = new WorldStats();
                    var built = await BuildFromScene(slot.Loc, doc.RootElement, Height, stats, slot.Ring, slot.Open, _viewCamera);
                    if ((stillValid is not null && !stillValid()) || !IsMounted(slot) || !GodotObject.IsInstanceValid(_places))
                    {
                        built.Group.Free();
                        built.Storeys.BoundaryMarks?.Free();
                        return remounted;
                    }
                    if (built.Storeys.Buttons.Count == 0 ? slot.LevelFilter == 0 : built.Storeys.Buttons.Any(b => b.Level == slot.LevelFilter))
                        built.LevelFilter = slot.LevelFilter;
                    Replace(slot, built);
                    remounted.Add(slot.Loc.Id);
                    _log($"location {slot.Loc.Id} ({slot.Loc.Name}): scene signature {slot.Signature} → {fresh}, remounted");
                }
            }
        }
        finally { _sweeping = false; }
        return remounted;
    }

    /// <summary>The remount's hand-over: the new group in, the old group and its boundary marks out.</summary>
    private void Replace(LocationSlot old, LocationSlot built)
    {
        old.Generation++;
        ReleaseProps(old);
        _places!.AddChild(built.Group);
        if (built.Storeys.BoundaryMarks is { } bm) _places.AddChild(bm);
        built.Storeys.ApplyLocks(_locks, built.Loc.Id);
        _slots[old.Loc.Id] = built;
        if (GodotObject.IsInstanceValid(old.Group)) old.Group.QueueFree();
        if (old.Storeys.BoundaryMarks is { } obm && GodotObject.IsInstanceValid(obm)) obm.QueueFree();
        Remounted?.Invoke(old, built);
    }
}
