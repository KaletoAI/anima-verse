using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check placement</c> (part of every <c>--check</c>, Task 29): figures in their rooms on the hand-written world
/// <c>fixtures/placement/</c> (README "Placement world"), every number derived there by hand:
///
///   P1 the open inn at storey 0: who sits on the bench (marker facing + lean), lies on the bed marker, takes the cot or
///      the stool by its activity's family, stands on the server's point at the room floor, the room derivations
///      (centres, sit / lie surfaces, the room marker's re-derived height), the huddle on the TILE ground (D6), the
///      movement-target facing; the loft and corridor figures hidden (storey 1); the closed shed hides its room figure;
///      the wilderness figure on the terrain;
///   P2 storey 1 shown: the loft and corridor figures appear, the storey-0 room figures hide;
///   P3 the inn closed: every room figure snaps to the huddle and hides (the doorstep stays empty), reopened they snap
///      back onto their seats;
///   P4 the fallback pool (ruling P3-R10): no character has a model → the browser's manifest models, the seeded pick
///      over the rigs the library fits (Soldier / Xbot; the Robot's own bones do not take the library).
/// </summary>
public static class PlacementCheck
{
    private const float Tol = 2e-3f;   // Godot's float boxes and transforms

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "placement");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "PlacementWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-placement] " + line), strict: true);
        FigureManager? mgr = null;
        try
        {
            await builder.BuildAsync(world, "Inn");
            var inn = builder.Slots["loc-inn"];
            var shed = builder.Slots["loc-shed"];
            Expect("P0 inn near and open, shed near and closed", inn.Ring == Ring.Near && inn.Open && shed.Ring == Ring.Near && !shed.Open, "");
            inn.Fade.Snap(1);
            shed.Fade.Snap(0);

            // ---- the stands the mount derived (README "Placement world", stands) ----
            var st = inn.Stands;
            NearV("P0 hall centre", st.RoomCenters["r-hall"], 64, 4.056875, 131);
            Expect("P0 hall centre under its name", st.RoomCenters["Hall"] == st.RoomCenters["r-hall"], "");
            NearV("P0 bedroom centre", st.RoomCenters["r-bed"], 64, 3.963125, 125);
            NearV("P0 loft centre", st.RoomCenters["r-loft"], 64, 7.03, 128);
            NearV("P0 corridor stand", st.RoomCenters["__floor__1"], 67, 7.01, 125);
            NearV("P0 stool = the hall's sit surface", st.SitSpots["r-hall"].Single(), 66, 4.585, 132);
            NearV("P0 cot = the bedroom's lie surface", st.LieSpots["r-bed"].Single(), 67, 4.556875, 125);
            Expect("P0 table too high to sit on", !st.LieSpots.ContainsKey("r-hall"), "");
            var bench = inn.Places.Markers["r-hall"]["bench1"].Slots;
            Expect("P0 bench re-derived from the hall floor", bench.All(s => Math.Abs(s.Y - 4.096875) < 1e-6), $"{bench[0].Y}");
            NearV("P0 bed marker (prop, composed)", inn.Places.Markers["r-bed"]["bed1"].Slots[0], 64, 4.503125, 125);

            mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-placement] " + line), strict: true)
            {
                ClipFit = ClipFitMode.OnDemandSync,
                AutoTick = false, Slots = () => builder.Slots,
            };
            world.AddChild(mgr);
            await mgr.InitAsync();
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap.json"))))
                await mgr.Apply(map.RootElement);
            await mgr.EnsurePool();
            // One frame of 0.1 s (Task 30): the facing is EASED ×10/s like the browser's (min(1, 0.1·10) = the whole turn);
            // every figure was snapped onto its point, so nobody steps.
            mgr.Tick(0.1);

            // ---- P1 the open inn, storey 0 ----
            Fig(mgr, "Ada Ash", "seat", 65, 4.096875, 131, visible: true);
            Facing(mgr, "Ada Ash", Mathf.Pi, 5, 0);                       // marker 90° → world (0, −1); tilt 5
            Fig(mgr, "Bea Birch", "seat", 64, 4.503125, 125, visible: true);
            Facing(mgr, "Bea Birch", -Mathf.Pi / 2, 0, 0);               // marker 180° → world (−1, 0)
            Fig(mgr, "Cy Cole", "pool", 67, 4.556875, 125, visible: true);  // lie-down → the cot
            Fig(mgr, "Ivo Isle", "pool", 66, 4.585, 132, visible: true);    // sit → the stool
            Fig(mgr, "Dov Dunn", "pos", 61, 3.963125, 131, visible: true);
            Fig(mgr, "Tess Vale", "pos", 63, 3.994375, 129, visible: true);
            Fig(mgr, "Eli Elm", "centre", 64, 7.03, 128, visible: false);
            Fig(mgr, "Fay Fern", "corridor", 67, 7.01, 125, visible: false);
            Fig(mgr, "Gus Gale", "tile", 68.32, 4.063125, 123.4, visible: true);
            Facing(mgr, "Gus Gale", Mathf.Atan2(31.68f, 36.6f), 0, 0);   // towards the shed's pin (100, 160)
            Fig(mgr, "Hal Hart", "tile", 98.85, 5.625, 162.16, visible: false);   // closed shed: hidden, TILE datum (D6)
            Fig(mgr, "Ivy Ink", "tile", 101.15, 5.6946875, 162.16, visible: true);
            Fig(mgr, "Kai Kerr", "free", 20, 1.25, 40, visible: true);
            var s = mgr.Stats;
            Expect("P1 counts", s.Figures == 12 && s.Hidden == 3 && s.Seated == 4 && s.Offmap == 0, s.Summary());

            // ---- P2 storey 1 ----
            Expect("P2 storey 1", builder.SetLevel("loc-inn", 1), "");
            mgr.TickPlacement();
            foreach (var n in new[] { "Eli Elm", "Fay Fern", "Gus Gale" }) Visible(mgr, n, true);
            foreach (var n in new[] { "Ada Ash", "Bea Birch", "Cy Cole", "Dov Dunn", "Ivo Isle", "Tess Vale" }) Visible(mgr, n, false);
            builder.SetLevel("loc-inn", 0);
            mgr.TickPlacement();
            Visible(mgr, "Eli Elm", false);
            Visible(mgr, "Ada Ash", true);

            // ---- P3 closed, then open again ----
            inn.Fade.Snap(0);
            mgr.TickPlacement();
            Fig(mgr, "Ada Ash", "tile", 68.32, 4.27875, 137.2, visible: false);   // huddle i 0 of 9, snapped
            Fig(mgr, "Tess Vale", "tile", 68.32, 4.0, 118.8, visible: false);     // i 8: the tile datum 4 > world 3.99125
            Fig(mgr, "Gus Gale", "tile", 68.32, 4.063125, 123.4, visible: true);  // never in a room: stays
            Expect("P3 nobody visible on the doorstep but Gus",
                   mgr.Figures.Values.Count(f => f.Visible && f.CharacterName != "Kai Kerr" && f.CharacterName != "Ivy Ink") == 1, "");
            Expect("P3 lean dropped with the seat", mgr.Figures["Ada Ash"].Rotation.X == 0, $"{mgr.Figures["Ada Ash"].Rotation}");
            inn.Fade.Snap(1);
            mgr.TickPlacement();
            Fig(mgr, "Ada Ash", "seat", 65, 4.096875, 131, visible: true);
            Fig(mgr, "Cy Cole", "pool", 67, 4.556875, 125, visible: true);

            // ---- P4 the fallback pool ----
            Expect("P4 pool ready", mgr.PoolState == "ready", mgr.PoolState);
            var fits = string.Join(",", mgr.PoolModels.Select(p => $"{p.Name}:{(p.LibraryFits ? "fits" : "own")}"));
            Expect("P4 pool models", fits == "Soldier:fits,Xbot:fits,Robot:own", fits);
            var picks = string.Join(",", new[] { "Ada Ash", "Bea Birch", "Fay Fern", "Kai Kerr", "Tess Vale" }.Select(n => mgr.Figures[n].PoolModel));
            Expect("P4 seeded picks", picks == "Soldier,Xbot,Xbot,Xbot,Soldier", picks);
            Expect("P4 every figure a pool model", mgr.Figures.Values.All(f => f.PoolModel is not null && f.Portrait is null && f.IsGlb), "");
            var ada = mgr.Figures["Ada Ash"];
            Near("P4 pool body height (manifest default 1.7)", ModelPlacement.Measure(ada.Body!, Transform3D.Identity).Size.Y, 1.7, 0.02);
            Expect("P4 own takes first, library after", ada.ClipKinds.Take(3).SequenceEqual(new[] { "idle", "run", "tpose" })
                   && ada.ClipKinds.Contains("stand-relaxed"), string.Join(",", ada.ClipKinds));
            Expect("P4 tag over the pool height", ada.TagHeight is { } th && Math.Abs(th - 1.7) < 1e-9, $"{ada.TagHeight}");

            return $"placement P1..P4 ok (seated {s.Seated}, hidden {s.Hidden}, pool {mgr.Stats.PoolFigures}, picks {picks})";
        }
        finally
        {
            if (mgr is not null && GodotObject.IsInstanceValid(mgr)) mgr.QueueFree();
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static void Fig(FigureManager mgr, string name, string rule, double x, double y, double z, bool visible)
    {
        var f = mgr.Figures[name];
        Expect($"{name} rule", f.Rule == rule, $"got {f.Rule}, expected {rule}");
        Expect($"{name} position", f.Position.DistanceTo(new Vector3((float)x, (float)y, (float)z)) < Tol,
               $"got {f.Position}, expected ({x}, {y}, {z})");
        Visible(mgr, name, visible);
    }

    private static void Visible(FigureManager mgr, string name, bool visible)
        => Expect($"{name} visible={visible}", mgr.Figures[name].Visible == visible, $"got {mgr.Figures[name].Visible}");

    private static void Facing(FigureManager mgr, string name, float yaw, double tiltDeg, double rollDeg)
    {
        var r = mgr.Figures[name].Rotation;
        float dy = Mathf.Wrap(r.Y - yaw, -Mathf.Pi, Mathf.Pi);
        Expect($"{name} facing", Math.Abs(dy) < 1e-3f && Math.Abs(r.X - Mathf.DegToRad((float)tiltDeg)) < 1e-4f
                                 && Math.Abs(r.Z - Mathf.DegToRad((float)rollDeg)) < 1e-4f,
               $"got {r}, expected yaw {yaw} tilt {tiltDeg} roll {rollDeg}");
    }

    private static void NearV(string what, Overview.Vec3 got, double x, double y, double z)
        => Expect(what, Math.Abs(got.X - x) < Tol && Math.Abs(got.Y - y) < Tol && Math.Abs(got.Z - z) < Tol,
                  $"got ({got.X}, {got.Y}, {got.Z}), expected ({x}, {y}, {z})");

    private static void Near(string what, double got, double want, double tol)
        => Expect(what, Math.Abs(got - want) < tol, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"placement {what}: {detail}");
    }
}
