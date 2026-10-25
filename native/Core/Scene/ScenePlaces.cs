using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// ONE PLACE of a mounted scene (client3d/src/scene/placeSlot.ts <c>PlaceEntry</c>), its slots finished in WORLD metres
/// at the figure-root height. <see cref="Slots"/> is re-lifted IN PLACE (<see cref="PlaceInventory.Relift"/>): a consumer
/// that keeps the array follows the ground, as a seated figure keeps its slot vector in the browser.
/// </summary>
public sealed class PlaceEntry
{
    /// <summary><c>markers[].id</c>.</summary>
    public required string Id { get; init; }
    /// <summary><c>markers[].room_id</c> (the map the entry hangs in is keyed by the room's id AND its name).</summary>
    public required string RoomId { get; init; }
    /// <summary>The place type (<c>markers[].group</c>: seat, lie, ground, stand …).</summary>
    public required string Group { get; init; }
    /// <summary>The slot points in world metres (surface − <see cref="Drop"/> + <see cref="Lift"/>).</summary>
    public required Vec3[] Slots { get; init; }
    /// <summary><c>facing</c> / <c>tilt</c> / <c>roll</c> in degrees, tile-local like every payload angle.</summary>
    public double? Rotation { get; init; }
    public double? Tilt { get; init; }
    public double? Roll { get; init; }
    /// <summary><c>root_offset ?? 0</c>: how far the figure root sits below the marked surface.</summary>
    public double Drop { get; init; }
    /// <summary><c>y_world − floor_y(level)</c> for a room marker, 0 for a prop marker.</summary>
    public double OffsetY { get; init; }
    /// <summary>A prop marker (<c>source: "prop"</c>): composed and finished, only the terrain re-lift moves it.</summary>
    public bool Fixed { get; init; }
    /// <summary><c>markers[].diorama</c>: the furniture under this place is part of the room's diorama mesh.</summary>
    public bool Diorama { get; init; }
    /// <summary>The storey of the place's room (<c>roomLevel.get(id) ?? 0</c>).</summary>
    public int Level { get; init; }
    /// <summary>The storey-0 terrain lift baked into the slot heights (moved by the re-lift).</summary>
    public double Lift { get; set; }
    /// <summary>Where that lift is sampled, world xz (<c>markerLiftPoint</c> through the tile frame at the mount).</summary>
    public P2 LiftAt { get; init; }
    /// <summary>A prop marker's placement anchor as the payload states it (tile-local); null for a room marker.</summary>
    public P2? Anchor { get; init; }

    /// <summary>What the glyph rule reads of this entry (<see cref="PlaceSlots.GlyphRows"/>).</summary>
    public PlaceEntryView View() => new(Slots, RoomId, Fixed, Anchor is not null, Diorama);
}

/// <summary>A stair landing (<c>StairWorldLink.foot/head</c>): its storey and the world point one stands on.</summary>
public sealed class StairLanding
{
    public required int Level { get; init; }
    public required Vec3 Pos { get; set; }
}

/// <summary>
/// ONE FLIGHT in world coordinates (tiles.ts <c>StairWorldLink</c>): the payload's own <c>stairs[]</c> block turned
/// into the tile frame, never measured back out of the <c>stair_*</c> boxes.
/// </summary>
public sealed class StairLink
{
    /// <summary><c>stairs[].id</c> — what <c>extras[].stair</c> names.</summary>
    public required int Id { get; init; }
    public required StairLanding Foot { get; init; }
    public required StairLanding Head { get; init; }
    /// <summary>The foot of the RUN (where the first tread begins), world xz.</summary>
    public required P2 At { get; init; }
    /// <summary>The unit climb direction in world xz, read off the payload's own points (head − at).</summary>
    public required P2 Dir { get; init; }
    public double RunM { get; init; }
    public double WidthM { get; init; }
    public int Steps { get; init; }
    /// <summary>The <c>width × run</c> rectangle the flight covers, world xz.</summary>
    public required P2[] Footprint { get; init; }
}

/// <summary>
/// ONE STOREY CORRIDOR (tiles.ts <c>TileCorridor</c> + its <c>roomCenters</c> stand, § A13b): the payload's anchor and
/// outline as delivered (tile-local), the top of the storey's own plate, and the stand derived from them.
/// </summary>
public sealed class CorridorStand
{
    public required string RoomId { get; init; }
    public required int Level { get; init; }
    /// <summary><c>corridors[].anchor</c>, tile-local.</summary>
    public required P2 Anchor { get; init; }
    /// <summary><c>corridors[].outline</c>, tile-local, exactly as delivered (inside the building on this storey?).</summary>
    public required P2[] Outline { get; init; }
    /// <summary><c>top_y</c> of the storey's OWN plate (tile-local); null exactly on storey 0 (no plate since E5a).</summary>
    public double? PlateTop { get; init; }
    /// <summary>
    /// The stand in world metres (<c>deriveCorridorCentres</c>): the anchor turned into the world, at datum + plate top +
    /// <see cref="PlaceInventory.WalkClearanceM"/> on a declared storey. NULL on storey 0: there the browser asks the
    /// tile's ground ladder (<c>tileGroundY</c> — baked surfaces, declared floors, plates, terrain), which has no shared
    /// vector yet; its first consumer (E5 figures / E7 walking) ports it.
    /// </summary>
    public Vec3? Stand { get; set; }
}

/// <summary>
/// A vertical connection as a click target (tiles.ts <c>VerticalTarget</c>): the lift (flight −1) or one flight
/// (its index in <see cref="PlaceInventory.Stairs"/>). The browser groups the boxes per target; native draws extras
/// merged per material, so E7 builds its pick groups from this list.
/// </summary>
public readonly record struct VerticalTarget(string Kind, int Flight);

/// <summary>
/// THE PLACES DATA OF ONE MOUNTED SCENE — what client3d/src/scene/sceneRecipe.ts <c>mountShell</c> files on the tile for
/// the figures (E5) and the embodied mode (E7): the place markers (<c>tile.roomMarkers</c>, keyed by room id AND name),
/// the lift stops (<c>tile.elevatorStops</c>), the stair flights (<c>tile.stairs</c>), the vertical targets
/// (<c>tile.verticalTargets</c>) and the storey corridors' stands (<c>tile.corridors</c> → <c>roomCenters</c>); plus the
/// re-lift of <c>reliftScene</c> for those of them it moves. Every point goes through the vector-checked
/// <see cref="SceneView.TileToWorld"/> / <see cref="StoreyGround"/>; hand cases: tests/ScenePlacesTests.cs.
/// </summary>
public sealed class PlaceInventory
{
    /// <summary><c>WALK_CLEARANCE_M</c> (game/ground.ts) = the server's <c>PROP_CLEARANCE</c>.</summary>
    public const double WalkClearanceM = 0.01;

    /// <summary>room id (and room name) → marker id → entry; one inner map hangs under both keys.</summary>
    public Dictionary<string, Dictionary<string, PlaceEntry>> Markers { get; } = new();
    /// <summary>storey → the lift pad's top face in world metres (the stop one stands on).</summary>
    public SortedDictionary<int, Vec3> ElevatorStops { get; } = new();
    public List<StairLink> Stairs { get; } = new();
    public List<VerticalTarget> VerticalTargets { get; } = new();
    public List<CorridorStand> Corridors { get; } = new();

    /// <summary>Every entry once (the maps hang under id and name).</summary>
    public IEnumerable<PlaceEntry> Entries()
    {
        var seen = new HashSet<Dictionary<string, PlaceEntry>>(ReferenceEqualityComparer.Instance);
        foreach (var byId in Markers.Values)
        {
            if (!seen.Add(byId)) continue;
            foreach (var e in byId.Values) yield return e;
        }
    }

    /// <summary>
    /// <c>mountShell</c>'s places part, in the browser's order: the lift stops off the <c>elevator_pad</c> extras (top
    /// face, the last pad of a storey wins), the flights from <c>stairs[]</c>, the vertical targets (the lift when any
    /// <c>elevator_*</c> box exists, then each flight a <c>stair_*</c> box names by id), the corridors (stand on the
    /// storey's own plate — the plate without a room id, else the first of that storey), and the markers (a prop marker
    /// lifted at its anchor, a room marker at its own point, <c>root_offset</c> taken off). <paramref name="roomNames"/>
    /// is the view=3d row's id → name (an entry is also keyed by its room's name); <paramref name="sampler"/> answers the
    /// world ground (NaN / null = nothing to say: no lift).
    /// </summary>
    public static PlaceInventory Compose(ScenePayload scene, TileFrame frame, IReadOnlyDictionary<string, string>? roomNames,
                                         Func<double, double, double>? sampler)
    {
        var inv = new PlaceInventory();
        bool lift = false;
        var stairIds = new HashSet<int>();
        foreach (var e in scene.Extras)
        {
            if (e.Kind.StartsWith("elevator_", StringComparison.Ordinal)) lift = true;
            else if (e.Kind.StartsWith("stair_", StringComparison.Ordinal) && e.Stair is { } st) stairIds.Add(st);
            if (e.Kind != "elevator_pad" || e.Level is not { } level) continue;
            double cy = At(e.Center, 1), sy = At(e.Size, 1);
            inv.ElevatorStops[level] = SceneView.TileToWorld(frame, At(e.Center, 0), At(e.Center, 2), cy + sy / 2);
        }
        foreach (var s in scene.Stairs)
        {
            var foot = SceneView.TileToWorld(frame, s.Foot.X, s.Foot.Z, s.Foot.Y);
            var head = SceneView.TileToWorld(frame, s.Head.X, s.Head.Z, s.Head.Y);
            var at = SceneView.TileToWorld(frame, s.At.X, s.At.Z);
            inv.Stairs.Add(new StairLink
            {
                Id = s.Id,
                Foot = new StairLanding { Level = s.FromLevel, Pos = foot },
                Head = new StairLanding { Level = s.ToLevel, Pos = head },
                At = new P2(at.X, at.Z),
                Dir = Normalize(head.X - at.X, head.Z - at.Z),
                RunM = s.RunM, WidthM = s.WidthM, Steps = s.Steps,
                Footprint = s.Footprint.Select(p => { var w = SceneView.TileToWorld(frame, p.X, p.Z); return new P2(w.X, w.Z); }).ToArray(),
            });
        }
        if (lift) inv.VerticalTargets.Add(new VerticalTarget("elevator", -1));
        for (int i = 0; i < scene.Stairs.Count; i++)
            if (stairIds.Contains(scene.Stairs[i].Id)) inv.VerticalTargets.Add(new VerticalTarget("stairs", i));

        var storeyPlate = new Dictionary<int, ScenePlate>();
        foreach (var plate in scene.Plates)
            if (!storeyPlate.TryGetValue(plate.Level, out var seen) || (seen.RoomId.Length > 0 && plate.RoomId.Length == 0))
                storeyPlate[plate.Level] = plate;
        foreach (var c in scene.Corridors)
        {
            if (c.RoomId.Length == 0) continue;
            inv.Corridors.Add(new CorridorStand
            {
                RoomId = c.RoomId, Level = c.Level, Anchor = c.Anchor, Outline = c.Outline,
                PlateTop = storeyPlate.TryGetValue(c.Level, out var p) ? p.TopY : null,
            });
        }
        inv.DeriveCorridorStands(frame);

        // roomLevel: the LAST rooms[] block of an id wins (Map.set), as in mountShell.
        var roomLevel = new Dictionary<string, int>();
        foreach (var r in scene.Rooms) if (r.RoomId.Length > 0) roomLevel[r.RoomId] = r.Level;
        foreach (var m in scene.Markers)
        {
            if (m.RoomId.Length == 0 || m.Id.Length == 0) continue;
            if (!inv.Markers.TryGetValue(m.RoomId, out var byId))
            {
                byId = new Dictionary<string, PlaceEntry>();
                inv.Markers[m.RoomId] = byId;
                // nameOf holds only DECLARED rooms (rooms[]) that have a name in the view=3d row.
                if (roomLevel.ContainsKey(m.RoomId) && roomNames is not null
                    && roomNames.TryGetValue(m.RoomId, out var name) && name.Length > 0)
                    inv.Markers[name] = byId;
            }
            bool isFixed = m.Source == "prop";
            int level = roomLevel.TryGetValue(m.RoomId, out var lv) ? lv : 0;
            double offsetY = isFixed ? 0 : m.YWorld - scene.FloorY(level);
            var lp = StoreyGround.MarkerLiftPoint(m.AtWorld, m.Anchor);
            var liftAt = SceneView.TileToWorld(frame, lp.X, lp.Z);
            double markerLift = StoreyGround.Lift(level, liftAt.X, liftAt.Z, frame.Center.Y, sampler);
            double drop = m.RootOffset ?? 0;
            byId[m.Id] = new PlaceEntry
            {
                Id = m.Id, RoomId = m.RoomId, Group = m.Group,
                Slots = m.Slots.Select(s => SceneView.TileToWorld(frame, s.X, s.Z, m.YWorld - drop + markerLift)).ToArray(),
                Rotation = m.Facing, Tilt = m.Tilt, Roll = m.Roll, Drop = drop, OffsetY = offsetY, Fixed = isFixed,
                Diorama = m.Diorama, Level = level, Lift = markerLift, LiftAt = new P2(liftAt.X, liftAt.Z), Anchor = m.Anchor,
            };
        }
        return inv;
    }

    /// <summary>
    /// <c>deriveCorridorCentres</c>: each corridor's anchor through the CURRENT tile frame, on a declared storey at
    /// datum + plate top + clearance; storey 0 stays null (the ground ladder, see <see cref="CorridorStand.Stand"/>).
    /// </summary>
    public void DeriveCorridorStands(TileFrame frame)
    {
        foreach (var c in Corridors)
            c.Stand = c.PlateTop is { } top ? SceneView.TileToWorld(frame, c.Anchor.X, c.Anchor.Z, top + WalkClearanceM) : null;
    }

    /// <summary>
    /// <c>reliftScene</c>'s part for this data, after the tile's datum moved by <paramref name="datumDelta"/> (the frame
    /// already stands on the new datum): the points composed in WORLD coordinates ride the datum step (lift stops, stair
    /// landings, prop-marker slots); then every prop marker takes the lift the field gives at its own lift point
    /// (<c>storeyGroundRelift</c>, one number per place, every slot alike); the corridor stands are derived again.
    /// Returns whether a seat moved (<c>seatsMoved</c>).
    ///
    /// ROOM markers are where the browser differs: it re-derives them from the room's floor (<c>deriveRoomSpots</c> →
    /// <c>roomBaseFloorY</c> − drop + offsetY, also right after the mount), a ladder with no shared vector yet. Here a
    /// room marker keeps its composed height and is carried exactly like a prop marker — which equals the browser on a
    /// flat built plot (the composed height IS ground + y_world − drop there) and differs on a slope or a declared room
    /// floor. Porting <c>deriveRoomSpots</c> (with vectors) belongs to its first consumer, E5.
    /// </summary>
    public bool Relift(TileFrame frame, double datumDelta, Func<double, double, double>? sampler)
    {
        if (datumDelta != 0)
        {
            foreach (var key in ElevatorStops.Keys.ToList())
            {
                var p = ElevatorStops[key];
                ElevatorStops[key] = p with { Y = p.Y + datumDelta };
            }
            foreach (var s in Stairs)
            {
                s.Foot.Pos = s.Foot.Pos with { Y = s.Foot.Pos.Y + datumDelta };
                s.Head.Pos = s.Head.Pos with { Y = s.Head.Pos.Y + datumDelta };
            }
            foreach (var e in Entries())
                for (int i = 0; i < e.Slots.Length; i++) e.Slots[i] = e.Slots[i] with { Y = e.Slots[i].Y + datumDelta };
        }
        bool seatsMoved = false;
        foreach (var e in Entries())
        {
            if (e.Slots.Length == 0) continue;
            var step = StoreyGround.Relift(e.Lift, e.Level, e.LiftAt.X, e.LiftAt.Z, frame.Center.Y, sampler);
            if (step.Delta != 0)
            {
                for (int i = 0; i < e.Slots.Length; i++) e.Slots[i] = e.Slots[i] with { Y = e.Slots[i].Y + step.Delta };
                seatsMoved = true;
            }
            e.Lift = step.Lift;
        }
        DeriveCorridorStands(frame);
        return seatsMoved;
    }

    /// <summary><c>tile.roomMarkers.get(room)?.get(id)</c> then <see cref="PlaceSlots.SlotFor"/> (slot null = the pair centre).</summary>
    public Vec3? SlotFor(string room, string placeId, int? slot)
        => Markers.TryGetValue(room, out var byId) && byId.TryGetValue(placeId, out var e) ? PlaceSlots.SlotFor(e.Slots, slot) : null;

    /// <summary>
    /// The rings of <c>rebuildPlaceGlyphs</c> for one room of this scene (<see cref="PlaceSlots.GlyphRows"/>, vector-checked
    /// <c>buildGlyphs</c>): the free slots of <c>GET /play/places</c>, minus the avatar's own place, a prop with an anchor
    /// and a diorama place whose room's diorama is mounted. The browser draws them ONLY embodied (ruling P3-R7: shown in E7).
    /// </summary>
    public List<GlyphRow> GlyphRows(string room, IReadOnlyList<PlaceOffer> offers, string skipPlaceId = "",
                                    IReadOnlySet<string>? mountedDioramaRooms = null)
    {
        if (!Markers.TryGetValue(room, out var byId)) return new List<GlyphRow>();
        var views = byId.ToDictionary(kv => kv.Key, kv => kv.Value.View());
        return PlaceSlots.GlyphRows(views, offers, skipPlaceId, mountedDioramaRooms);
    }

    private static double At(double[] v, int i) => i < v.Length ? v[i] : 0;

    /// <summary>three's <c>Vector2.normalize</c>: divide by the length, a zero vector stays zero (<c>/ (length || 1)</c>).</summary>
    private static P2 Normalize(double x, double z)
    {
        double l = Math.Sqrt(x * x + z * z);
        if (l == 0) l = 1;
        return new P2(x / l, z / l);
    }
}

/// <summary>A composer finding to toast (main.ts <c>announceSceneProblems</c>).</summary>
public readonly record struct ProblemToast(string Key, string Message, string Log);

/// <summary>
/// main.ts <c>announceSceneProblems</c>: on every world-map poll, the scene problems of the AVATAR's location are toasted
/// once per (location, kind, room) — never one with <c>scope: "editor"</c> (furnishing findings belong to the floor-plan
/// editor, not a greeting at the door). The set of announced keys lives as long as the client session.
/// </summary>
public static class SceneProblems
{
    /// <summary>
    /// The toasts this poll adds: <paramref name="announced"/> is updated (a key is spent as it is returned). No avatar
    /// location or no scene for it → nothing.
    /// </summary>
    public static List<ProblemToast> Announce(string? avatarLocationId, IReadOnlyList<SceneProblem>? problems, ISet<string> announced)
    {
        var toasts = new List<ProblemToast>();
        if (string.IsNullOrEmpty(avatarLocationId) || problems is null) return toasts;
        foreach (var p in problems)
        {
            if (p.Scope == "editor") continue;
            var key = $"{avatarLocationId}|{p.Kind}|{p.RoomId}";
            if (!announced.Add(key)) continue;
            toasts.Add(new ProblemToast(key, p.Message, $"[scene] {avatarLocationId}: {p.Kind} — {p.Message}"));
        }
        return toasts;
    }
}
