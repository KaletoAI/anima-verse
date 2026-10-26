using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The figure ground and stands of a mounted location (Task 29) — the browser's tile fields that sceneRecipe.ts
/// <c>mountShell</c> / <c>mountDetail</c> / <c>reliftScene</c> / <c>setSceneModelTier</c> keep for the figures:
/// <c>tile.surfaces</c>, <c>walkPlates</c>, <c>declaredFloors</c>, <c>modelWalkY</c>, <c>roomFloors</c>,
/// <c>roomLevels</c>, <c>alwaysVisibleRooms</c>, then <c>deriveRoomSpots</c> per room and <c>deriveCorridorCentres</c>.
/// </summary>
public sealed partial class WorldBuilder
{
    /// <summary>
    /// Fill <see cref="LocationSlot.Stands"/> from the slot's scene, its placements and its frame as they stand now, and
    /// derive every room and corridor stand (<see cref="FigureStands.DeriveAll"/>). Called after the mount, after every
    /// re-lift (<see cref="Redatum"/>) and after an interior tier swap. The derived sit / lie lists are kept across calls
    /// (the browser's <c>put</c> never clears them while the detail stays mounted).
    /// </summary>
    public void DeriveStands(LocationSlot slot)
    {
        if (slot.Scene is not { } scene) return;
        var st = slot.Stands;
        var g = slot.Group.Position;
        st.Frame = new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y);
        st.WorldGround = Height is { } h ? h.GroundAt : null;

        // Room names (an entry is also keyed by the room's name), levels and the always-visible set (mountShell's rooms
        // loop: outdoor or always_visible → always visible, under its name too); the corridors' levels.
        st.RoomNames.Clear();
        st.RoomLevels.Clear();
        st.AlwaysVisible.Clear();
        var names = DetailRooms(slot.Loc.Id);
        var outdoor = new HashSet<string>(scene.OutdoorRooms);
        foreach (var room in scene.Rooms)
        {
            var id = room.RoomId;
            if (outdoor.Contains(id) || room.AlwaysVisible)
            {
                st.AlwaysVisible.Add(id);
                outdoor.Add(id);
            }
            st.RoomLevels[id] = room.Level;
            if (names.TryGetValue(id, out var name) && name.Length > 0)
            {
                st.RoomNames[id] = name;
                st.RoomLevels[name] = room.Level;
                if (outdoor.Contains(id)) st.AlwaysVisible.Add(name);
            }
        }
        foreach (var c in scene.Corridors) if (c.RoomId.Length > 0) st.RoomLevels[c.RoomId] = c.Level;

        // The baked lattices of every MOUNTED spec (the building, the outdoor specs and — in the near ring, where the
        // detail is mounted — the indoor ones), each with the lift its placement carries; a spec whose mesh never stood
        // keeps 0, the composed height.
        st.Surfaces.Clear();
        foreach (var rec in slot.Placements)
        {
            var spec = rec.Spec;
            if (spec.Surface is not { } surface) continue;
            st.Surfaces.Add(new PlacedSurface($"{spec.Role}:{spec.Id}:{spec.RoomId}",
                new SurfacePlacement(new P2(spec.AnchorX, spec.AnchorZ), spec.YawDeg, spec.BottomY, spec.MaxM, spec.Measure),
                surface, rec.Node is not null && !rec.IsBuilding ? rec.Lift : 0, spec.Level, spec.RoomId));
        }

        // The plates (declared storeys) with their openings; the building model's declared standing height.
        st.WalkPlates.Clear();
        var roomPlateTop = new Dictionary<string, double>();
        foreach (var plate in scene.Plates)
        {
            st.WalkPlates.Add(new WalkPlate(plate.TopY, plate.Outline.Select(p => new P2(p.X, p.Z)).ToList(),
                                            plate.Holes.Select(r => (IReadOnlyList<P2>)r.Select(p => new P2(p.X, p.Z)).ToList()).ToList()));
            if (plate.RoomId.Length > 0) roomPlateTop[plate.RoomId] = plate.TopY;
        }
        st.ModelWalkY = null;
        foreach (var rec in slot.Placements)
            if (rec.IsBuilding && rec.Node is not null) st.ModelWalkY = rec.Spec.WalkYWorld;

        // A diorama's declared floor moves with its mesh: walk_y_world + its lift (mountModels' walkY map).
        var walkY = new Dictionary<string, double>();
        foreach (var rec in slot.Placements)
            if (rec.Spec.Role == "room" && rec.Spec.WalkYWorld is { } wy && rec.Spec.RoomId.Length > 0
                && rec.Node is not null && !rec.Placeholder)
                walkY[rec.Spec.RoomId] = wy + rec.Lift;
        st.DeclaredFloors.Clear();
        foreach (var room in scene.Rooms)
            if (walkY.TryGetValue(room.RoomId, out var top)) st.DeclaredFloors.Add(new DeclaredFloor(room.RoomId, top, room.Outline));

        // The floors of the rooms: storey 0 from floor_plan, a declared storey from its room outline; the declaration is a
        // room plate, else the overlay's y, outranked by the diorama's walk_y (Map.set keeps the first position).
        var overlayOf = new Dictionary<string, SceneRoomOverlay?>();
        foreach (var r in scene.Rooms) overlayOf[r.RoomId] = r.Overlay;
        var floors = new List<KeyValuePair<string, RoomFloor>>();
        void Set(string id, RoomFloor floor)
        {
            int at = floors.FindIndex(kv => kv.Key == id);
            if (at >= 0) floors[at] = new(id, floor);
            else floors.Add(new(id, floor));
        }
        foreach (var f in scene.FloorPlan)
        {
            if (f.RoomId.Length == 0 || f.PolygonWorld.Length < 3) continue;
            Set(f.RoomId, new RoomFloor { Hull = f.PolygonWorld, Declared = overlayOf.GetValueOrDefault(f.RoomId)?.Y });
        }
        foreach (var r in scene.Rooms)
        {
            if (r.RoomId.Length == 0 || r.Level == 0 || r.Outline.Length < 3) continue;
            Set(r.RoomId, new RoomFloor
            {
                Hull = r.Outline,
                Declared = roomPlateTop.TryGetValue(r.RoomId, out var pt) ? pt : overlayOf.GetValueOrDefault(r.RoomId)?.Y,
            });
        }
        foreach (var (id, floor) in floors)
            if (walkY.TryGetValue(id, out var declared)) floor.Declared = declared;
        st.RoomFloors.Clear();
        st.RoomFloors.AddRange(floors);

        var group = slot.Group;
        st.DeriveAll(roomId => RoomPropBoxes(group, slot.Placements, roomId), slot.Places);
    }

    /// <summary>
    /// <c>roomProps</c> + the box measure of <c>deriveRoomSpots</c>: the WORLD bounding box of every placed prop of the room
    /// (a stand-in box too; an object without a mesh has none).
    /// </summary>
    private static List<SpotBox> RoomPropBoxes(Node3D group, IReadOnlyList<PlacedModel> placements, string roomId)
    {
        var boxes = new List<SpotBox>();
        foreach (var rec in placements)
        {
            if (rec.Spec.Role != "prop" || rec.Spec.RoomId != roomId || rec.Node is not { } node || !GodotObject.IsInstanceValid(node)) continue;
            var frame = group.Transform * ChainTo(node.GetParent(), group);
            var box = ModelPlacement.Measure(node, frame);
            if (box.Size == Vector3.Zero && box.Position == Vector3.Zero) continue;   // no mesh measured
            var end = box.End;
            boxes.Add(new SpotBox(new Overview.Vec3(box.Position.X, box.Position.Y, box.Position.Z), new Overview.Vec3(end.X, end.Y, end.Z)));
        }
        return boxes;
    }
}
