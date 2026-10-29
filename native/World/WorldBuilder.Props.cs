using System;
using AnimaNative.Api;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Scene;
using AnimaNative.Embody;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The view-side extras of the mounted placements (Task 18): texture slots (pictures, glass, mirror panes), door props,
/// prop lights and the room ambience under the light focus — sceneRecipe.ts <c>fillSlots</c> / <c>registerDoorProp</c> /
/// <c>reliftPlacement</c>'s light and main.ts' frame hook (<c>engine.lightPool.update</c>, the ambience lines).
/// </summary>
public sealed partial class WorldBuilder
{
    /// <summary>The one prop light pool of the world (null before the build).</summary>
    public PropLightPool? PropLights { get; private set; }
    /// <summary>The mirror passes of the world (null before the build).</summary>
    public MirrorPanes? Mirrors { get; private set; }
    /// <summary>Seed of the flicker phases (the check pins it; the browser uses Math.random).</summary>
    public int? LightSeed { get; init; }

    /// <summary>Every picture load started (the check awaits them).</summary>
    public List<Task> SlotLoads { get; } = new();

    /// <summary><c>fillSlots</c>: the placement's texture slots, its picture loads remembered.</summary>
    private SlotHandle? FillSlots(Node3D placed, SceneModelSpec spec)
    {
        var h = SlotMaterials.Apply(placed, spec, LoadPictureAsync, Mirrors, _log);
        if (h is not null) lock (SlotLoads) SlotLoads.AddRange(h.Loads);
        return h;
    }

    /// <summary>
    /// <c>slotTexture</c>: a slot picture by its payload URL — fetched and decoded per placement (not cached by URL,
    /// like the browser: a texture belongs to the placement that holds it). Null on any failure.
    /// </summary>
    public async Task<ImageTexture?> LoadPictureAsync(string url)
    {
        try
        {
            var bytes = await _source.GetBytesAsync(url);
            var img = await Task.Run(() =>
                {
                    using var parse = (_source as AnimaApi)?.Measurements.Time("texture", "parse");
                    return SurfaceLibrary.Decode(bytes);
                });
            return ImageTexture.CreateFromImage(img);
        }
        catch (Exception e)
        {
            _log($"slot picture {url} failed ({e.Message}) — the surface stays as modelled");
            return null;
        }
    }

    /// <summary>
    /// <c>placementLightPosition(rec.parent ?? tile.group, anchor, bottom_y + lift, light)</c>: the base anchor through the
    /// parent's frame (the location group's transform times the chain under it), plus the light's world offset.
    /// </summary>
    public static Vector3 LightPosition(Node3D group, PlacedModel rec)
    {
        var light = rec.Spec.Light!;
        var frame = group.Transform * ChainTo(rec.Parent, group);
        var p = Scene.PropLights.LightPositionInFrame(CutMaterials.ColumnMajor(frame), rec.Spec.AnchorX, rec.Spec.AnchorZ,
                                                rec.Spec.BottomY + rec.Lift, light.Offset.X, light.Offset.Z, light.HeightM);
        return new Vector3((float)p.X, (float)p.Y, (float)p.Z);
    }

    /// <summary>A location leaves (dropped or remounted): its lights, mirror passes and picture work go with it.</summary>
    private void ReleaseProps(LocationSlot slot)
    {
        foreach (var rec in slot.Placements)
            if (rec.LightId is { } id)
            {
                PropLights?.Remove(id);
                rec.LightId = null;
            }
        if (GodotObject.IsInstanceValid(slot.Group)) Mirrors?.DetachUnder(slot.Group);
    }

    /// <summary>
    /// The visible rooms the lights read (main.ts <c>visibleLightRooms</c>): every room group whose own flag is on —
    /// the storey filter's verdict, not the crossfade (a lamp in a closed house still lights, like in the browser).
    /// </summary>
    public HashSet<string> VisibleLightRooms()
    {
        var rooms = new HashSet<string>();
        foreach (var slot in _slots.Values)
        {
            if (!GodotObject.IsInstanceValid(slot.Group)) continue;
            foreach (var rg in slot.Storeys.Rooms.Values)
                if (GodotObject.IsInstanceValid(rg.Node) && rg.Node.Visible) rooms.Add($"{slot.Loc.Id}:{rg.Id}");
        }
        return rooms;
    }

    /// <summary>
    /// The prop half of main.ts' frame hook: <c>engine.lightPool.update(dt, lightFocus, nightFactor, visibleLightRooms)</c>,
    /// the mirror passes of this frame (three's render hooks) and avatar-distance door swing in every mode (Task 51).
    /// </summary>
    public void TickProps(double dt, Camera3D? camera, Vector3 focus, double night, Vector3? avatar = null, string avatarRoom = "", string groundRoom = "")
    {
        PropLights?.Tick(dt, focus, night, VisibleLightRooms());
        if (camera is not null) Mirrors?.Tick(camera);
        // Task 51 / E7-T6 §0.9: avatar proximity in ALL modes; light/camera focus never stands for the avatar.
        foreach (var slot in _slots.Values)
        {
            var room = slot.RouteView()?.RoomIdOf(avatarRoom) ?? (avatarRoom == groundRoom ? groundRoom : "");
            int level = slot.Stands.RoomLevels.TryGetValue(room, out int own) ? own
                : room.Length > 0 && room != groundRoom ? slot.LevelFilter : 0;
            var local = avatar is { } p ? SceneView.WorldToTile(slot.Stands.Frame, p.X, p.Z) : (AnimaNative.Scatter.P2?)null;
            var locks = slot.Loc.Id == _locks.Loc ? _locks.Rooms : null;
            foreach (var rec in slot.Placements)
                if (rec.Door is { } door)
                {
                    double distance = local is { } at ? double.Hypot(at.X-door.At.X, at.Z-door.At.Z) : double.PositiveInfinity;
                    DoorProps.Tick(door, dt, DoorSwing.DoorDistance(door.Level, level, distance), Locks.DoorwayLock(door.Rooms, locks, room) is null);
                }
        }
    }

    /// <summary>
    /// The room ambience under the light focus (main.ts): in the OPEN location only, the smallest room rectangle under
    /// the focus (<c>roomAt</c>), else the storey corridor (<c>corridorAt</c>); that room's <c>ambience</c>, null = neutral.
    /// </summary>
    public SceneAmbience? AmbienceAt(string? openId, Vector3 focus)
    {
        if (openId is null || !_slots.TryGetValue(openId, out var slot) || !GodotObject.IsInstanceValid(slot.Group)) return null;
        var g = slot.Group.Position;
        var frame = new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y);
        var p = SceneView.WorldToTile(frame, focus.X, focus.Z);
        var room = Ambience.RoomAtRects(slot.RoomRects, p.X, p.Z) ?? Ambience.CorridorAtOutline(slot.Corridors, p.X, p.Z);
        return room is not null && slot.RoomAmbience.TryGetValue(room, out var a) ? a : null;
    }
}
