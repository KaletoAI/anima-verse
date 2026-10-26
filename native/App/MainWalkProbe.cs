using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// The <c>--offline</c> walk probe (Task 30): synthetic polls on the latest world map, so a dump shows the browser's NPC
/// walk on real data — a figure put on the open ground and then moved 12 m (it runs, then walks), and a room figure sent
/// to a room on another storey of its open location (its stations: doors, stair landings or lift stops, and the ride).
/// The figures are stepped by hand in 60 fps frames and logged every 0.5 s; the real map is applied again afterwards.
/// </summary>
public partial class Main
{
    private void OfflineWalkProbe(WorldBuilder builder)
    {
        var figures = _figures!;
        if (figures.LatestMap is not { } real) return;
        bool auto = figures.AutoTick;
        var fit = figures.ClipFit;
        figures.AutoTick = false;
        // The probe steps its frames synchronously, so a lazy fit (Task 35b) could never finish inside it: clips are fitted
        // at once while it runs.
        figures.ClipFit = ClipFitMode.OnDemandSync;
        try
        {
            var rows = JsonNode.Parse(real.GetRawText())!["characters"]!.AsArray()
                .Where(c => c?["pos"] is JsonObject).Select(c => c!).ToList();
            var walker = rows.Select(c => (string)c["name"]!).OrderBy(n => n, StringComparer.Ordinal).FirstOrDefault();
            if (walker is not null)
            {
                // Two polls: the walker free on the open ground at its own point, then 12 m east of it.
                var first = WithRow(real, walker, c => { c["location_id"] = ""; c["room_id"] = ""; c["place"] = null; });
                var second = WithRow(real, walker, c =>
                {
                    c["location_id"] = ""; c["room_id"] = ""; c["place"] = null;
                    c["pos"]!["x"] = (double)c["pos"]!["x"]! + 12;
                });
                figures.Apply(first);
                figures.Apply(second);
                Trace(figures, walker, "open ground +12 m");

                // The same walker into the first painted water whose centre lies in it, then 6 m on: it swims (or wades).
                foreach (var area in builder.Ground?.Catalog.Areas.Where(a => a.Profile is not null) ?? Enumerable.Empty<Scatter.TerrainAreaInfo>())
                {
                    var pts = area.Polygon.Where(q => double.IsFinite(q.X) && double.IsFinite(q.Z)).ToList();
                    if (pts.Count < 3) continue;
                    double cx = pts.Average(q => q.X), cz = pts.Average(q => q.Z);
                    if (builder.FigureGroundMove(cx, cz).Water is not { } level) continue;
                    Log($"offline walk {walker} into the water '{area.Id}' ({area.Kind}) at ({cx:0.##}, {cz:0.##}), mirror {level:0.##}, "
                        + $"bed {builder.FigureGroundY(cx, cz):0.##}");
                    figures.Apply(WithRow(real, walker, c =>
                    {
                        c["location_id"] = ""; c["room_id"] = ""; c["place"] = null;
                        c["pos"] = new JsonObject { ["x"] = cx, ["z"] = cz };
                    }));
                    // A jump into the lake (the probe's own teleport): the walk there is not what it measures.
                    figures.Figures[walker].SnapTo(figures.Figures[walker].Target);
                    Trace(figures, walker, "in the water");
                    figures.Apply(WithRow(real, walker, c =>
                    {
                        c["location_id"] = ""; c["room_id"] = ""; c["place"] = null;
                        c["pos"] = new JsonObject { ["x"] = cx + 6, ["z"] = cz };
                    }));
                    Trace(figures, walker, "water +6 m");
                    break;
                }
            }

            // A room figure of an open location sent into a room on another storey (else another room): the locations with a
            // storey change first.
            var slots = builder.Slots.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToList();
            foreach (var (id, slot) in slots.Where(kv => kv.Value.Stands.RoomLevels.Values.Distinct().Count() > 1)
                                            .Concat(slots.Where(kv => kv.Value.Stands.RoomLevels.Values.Distinct().Count() <= 1)))
            {
                var levels = slot.Stands.RoomLevels;
                var mover = rows.Where(c => (string?)c["location_id"] == id && levels.ContainsKey((string?)c["room_id"] ?? "")
                                            && (string?)c["name"] != figures.AvatarName)
                                .Select(c => (Name: (string)c["name"]!, Room: (string)c["room_id"]!))
                                .OrderBy(c => c.Name, StringComparer.Ordinal).FirstOrDefault();
                if (mover.Name is null) continue;
                int from = levels[mover.Room];
                var rooms = slot.DetailRooms.Keys.Where(r => r != mover.Room && slot.Stands.RoomCenters.ContainsKey(r)).ToList();
                var target = rooms.FirstOrDefault(r => levels.TryGetValue(r, out var l) && l != from) ?? rooms.FirstOrDefault();
                if (target is null) continue;
                double was = slot.Fade.Fade;
                slot.Fade.Snap(1);
                figures.Apply(real);   // the room as shown: the start of the route
                var moved = WithRow(real, mover.Name, c => { c["room_id"] = target; c["pos"] = null; c["place"] = null; });
                figures.Apply(moved);
                var fig = figures.Figures[mover.Name];
                Log($"offline walk {mover.Name} {id} ({slot.Loc.Name}): room {mover.Room} (storey {from}) → {target} "
                    + $"(storey {(levels.TryGetValue(target, out var lt) ? lt : 0)}), stations "
                    + $"[{string.Join(" ", fig.Waypoints.Select(P))}], ride {(fig.Ride is { } r ? $"{r.Legs.Count} leg(s)" : "none")}");
                Trace(figures, mover.Name, "room change");
                slot.Fade.Snap(was);
                break;
            }
        }
        finally
        {
            figures.Apply(real);
            figures.TickPlacement();
            figures.AutoTick = auto;
            figures.ClipFit = fit;
        }
    }

    /// <summary>Step the figures in 60 fps frames for up to 12 s, logging one figure every 0.5 s until it stands.</summary>
    private void Trace(FigureManager figures, string name, string what)
    {
        var fig = figures.Figures[name];
        for (int frame = 1; frame <= 720; frame++)
        {
            figures.Tick(1.0 / 60);
            if (frame % 30 != 0 && fig.Moving) continue;
            var ghost = fig.Ghost is { Visible: true } g ? $" ghost {g.CutY:0.##}" : "";
            Log($"offline walk {name} [{what}] t={frame / 60.0:0.00}s at {P(fig.Position)} "
                + $"{(fig.Moving ? fig.Running ? "runs" : "walks" : "stands")} on {fig.Movement}, asks '{fig.WantedClip.Kind}' "
                + $"drop {fig.Drop:0.##}, stations {fig.Waypoints.Count}, ride {(fig.Ride is { } r ? $"leg {r.Leg} armed {r.Armed}" : "none")}, "
                + $"yaw {fig.Rotation.Y:0.##}{ghost}");
            if (!fig.Moving) return;
        }
    }

    private static string P(Vector3 v) => $"({v.X:0.##}, {v.Y:0.##}, {v.Z:0.##})";

    /// <summary>The map with one character row changed.</summary>
    private static JsonElement WithRow(JsonElement map, string name, Action<JsonObject> change)
    {
        var node = JsonNode.Parse(map.GetRawText())!;
        foreach (var c in node["characters"]!.AsArray())
            if (c is JsonObject o && (string?)o["name"] == name) change(o);
        return JsonDocument.Parse(node.ToJsonString()).RootElement.Clone();
    }
}
