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
/// <c>--check walk</c> (part of every <c>--check</c>, Task 30): the browser's NPC walk on the hand-written, FLAT world
/// <c>fixtures/walk/</c> (README "Walk world"), every number derived there by hand:
///
///   W1 poll 1, one 0.1 s frame then one 0.25 s frame: the neighbour facing (Dora and Sam face each other, the loners
///      turn south), the swimmer in the lake treads water — root eased ×4/s to the mirror (0.6, then 1.5), the body
///      dropped by the idle sink, the underwater ghost cut at the mirror;
///   W2 poll 2, frames of 0.25 s: Dora walks from room A to room B THROUGH the party-wall door (she heads for the door,
///      not the straight line, and retires it at 1.5 m); Rex runs over 10 m of open grass (×1.8 beyond 6 m, then
///      walks); Sam leaves room A by its door, walks to the stair foot, rides the flight (the ramp answers the height:
///      1.246 m a third of the way up), ends the ride on the head landing and walks into the loft; Lia swims.
/// </summary>
public static class WalkCheck
{
    private const float Tol = 2e-3f;
    private const double Frame = 0.25;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "walk");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "WalkWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-walk] " + line), strict: true);
        FigureManager? mgr = null;
        try
        {
            await builder.BuildAsync(world, "Hall");
            var hall = builder.Slots["loc-hall"];
            Expect("W0 hall near and open", hall.Ring == Ring.Near && hall.Open, "");
            hall.Fade.Snap(1);
            var st = hall.Stands;
            NearV("W0 front centre", st.RoomCenters["r-a"], 97, 0.01, 0);
            NearV("W0 loft centre", st.RoomCenters["r-up"], 100, 3.03, 0);
            Expect("W0 one flight", hall.Places.Stairs.Count == 1, $"{hall.Places.Stairs.Count}");

            mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-walk] " + line), strict: true)
            {
                AutoTick = false, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
            };
            world.AddChild(mgr);
            await mgr.InitAsync();
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap.json"))))
                await mgr.Apply(map.RootElement);
            await mgr.EnsurePool();
            var dora = mgr.Figures["Dora Door"];
            var sam = mgr.Figures["Sam Stair"];
            var rex = mgr.Figures["Rex Run"];
            var lia = mgr.Figures["Lia Lake"];
            Expect("W0 every figure a pool body", new[] { dora, sam, rex, lia }.All(f => f.Player is not null),
                   string.Join(", ", new[] { dora, sam, rex, lia }.Select(f => $"{f.CharacterName}: pool {f.PoolModel} portrait {f.Portrait is not null} player {f.Player is not null}")));

            // ---- W1 poll 1 ----
            At("W1 Dora on her point", dora, 97, 0.01, 1);
            At("W1 Sam on his point", sam, 97, 0.01, 2);
            At("W1 Lia on the lake bed (the snap)", lia, 40, 0, 0);
            mgr.Tick(0.1);
            Near("W1 Dora faces Sam (+z)", dora.Rotation.Y, 0, 1e-4);
            Near("W1 Sam faces Dora (−z: π)", Math.Abs(sam.Rotation.Y), Math.PI, 1e-4);
            Near("W1 Rex turns south (π)", Math.Abs(rex.Rotation.Y), Math.PI, 1e-4);
            Near("W1 Lia's root eased ×4/s towards the mirror", lia.Position.Y, 0.6, 1e-4);
            Expect("W1 Lia treads water", lia.CurrentKind == "treading-water" && Math.Abs(lia.Drop - 1.3) < 1e-9 && !lia.Moving,
                   $"kind {lia.CurrentKind} drop {lia.Drop}");
            Expect("W1 Lia's body hangs the idle sink under the root", Math.Abs(lia.Body!.Position.Y + 1.3) < 1e-5, $"{lia.Body.Position}");
            Expect("W1 Lia's ghost cut at the mirror", lia.Ghost is { Visible: true } g && Math.Abs(g.CutY - 1.5) < 1e-9,
                   $"ghost {lia.Ghost?.Visible} cut {lia.Ghost?.CutY}");
            Expect("W1 Dora stands dry", dora.CurrentKind == "stand-relaxed" && dora.Drop == 0 && dora.Ghost is not { Visible: true },
                   $"kind {dora.CurrentKind} drop {dora.Drop}");
            mgr.Tick(Frame);
            Near("W1 Lia floats at the mirror", lia.Position.Y, 1.5, 1e-4);

            // ---- W2 poll 2 ----
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap_poll2.json"))))
                await mgr.Apply(map.RootElement);
            Expect("W2 Dora routed through the party wall", dora.Waypoints.Count == 1 && Near3(dora.Waypoints[0], 100, 0, 2) && dora.Ride is null,
                   string.Join(" ", dora.Waypoints));
            Expect("W2 Sam's stations: door, stair foot, stair head",
                   sam.Waypoints.Count == 3 && Near3(sam.Waypoints[0], 100, 0, 2) && Near3(sam.Waypoints[1], 100, 0.01, -2)
                   && Near3(sam.Waypoints[2], 103.5, 3.01, -2), string.Join(" ", sam.Waypoints));
            Expect("W2 Sam's ride: one leg, unarmed", sam.Ride is { Legs.Count: 1, Leg: 0, Armed: false }, $"{sam.Ride?.Legs.Count}");
            Expect("W2 Sam hidden (storey 1), still walking", !sam.Visible, "");
            Expect("W2 nobody moved yet", Near3(dora.Position, 97, 0.01, 1) && Near3(rex.Position, -80, 0, 60), "");

            mgr.Tick(Frame);                                                                          // F1
            At("F1 Dora runs towards the door", dora, 98.451485, 0, 1.483828);
            Expect("F1 Dora runs (√10 + 10 > 6)", dora.Running && dora.CurrentKind == "run", $"{dora.Running} {dora.CurrentKind}");
            At("F1 Rex runs 1.53 m", rex, -78.47, 0, 60);
            At("F1 Sam runs to the door", sam, 98.53, 0, 2);
            At("F1 Lia swims 0.85 m", lia, 40.85, 1.5, 0);
            Expect("F1 Lia swims (no run on water)", lia.CurrentKind == "breast-stroke" && !lia.Running && Math.Abs(lia.Drop - 0.35) < 1e-9,
                   $"kind {lia.CurrentKind} drop {lia.Drop}");
            Expect("F1 Lia's ghost still at the mirror", lia.Ghost is { Visible: true } g1 && Math.Abs(g1.CutY - 1.5) < 1e-9, "");

            mgr.Tick(Frame);                                                                          // F2
            At("F2 Dora 0.10 m short of the door (z 1.97, not the straight z 1)", dora, 99.902971, 0, 1.967657);
            Expect("F2 the door still ahead", dora.Waypoints.Count == 1, "");
            At("F2 Sam at the door", sam, 100, 0, 2);

            mgr.Tick(Frame);                                                                          // F3
            Expect("F3 Dora retired the door (0.10 < 1.5)", dora.Waypoints.Count == 0, "");
            At("F3 Dora walks on to her point", dora, 100.714291, 0.01, 1.714163);
            Expect("F3 Dora walks (3.24 ≤ 6)", dora.Moving && !dora.Running && dora.CurrentKind == "mob1-walk", dora.CurrentKind);
            At("F3 Rex still runs (6.94 > 6)", rex, -75.41, 0, 60);
            Expect("F3 Sam retired the door at the ride's 0.4 m", sam.Waypoints.Count == 2, $"{sam.Waypoints.Count}");
            At("F3 Sam heads for the stair foot", sam, 100, 0.01, 0.47);

            mgr.Tick(Frame);                                                                          // F4
            At("F4 Rex walks (5.41 ≤ 6)", rex, -74.56, 0, 60);
            Expect("F4 Rex's clip is the walk", !rex.Running && rex.CurrentKind == "mob1-walk", rex.CurrentKind);

            mgr.Tick(Frame);                                                                          // F5
            At("F5 Sam on the stair foot", sam, 100, 0.01, -2);
            Expect("F5 the ride armed", sam.Ride is { Leg: 0, Armed: true }, $"{sam.Ride?.Armed}");

            mgr.Tick(Frame);                                                                          // F6
            At("F6 Dora arrived", dora, 103, 0.01, 1);
            At("F6 Sam on the ramp: 0.01 + 1.03/2.5·3", sam, 101.53, 1.246, -2);

            mgr.Tick(Frame);                                                                          // F7
            At("F7 Sam past the run: the head height", sam, 103.06, 3.01, -2);
            At("F7 Lia 7 × 0.85 m out", lia, 45.95, 1.5, 0);

            mgr.Tick(Frame);                                                                          // F8
            At("F8 Sam on the head landing", sam, 103.5, 3.01, -2);
            Expect("F8 the ride is over", sam.Ride is null, "");
            At("F8 Lia arrived", lia, 46.8, 1.5, 0);

            mgr.Tick(Frame);                                                                          // F9
            Expect("F9 Sam retired the head landing", sam.Waypoints.Count == 0, "");
            At("F9 Sam walks into the loft", sam, 102.761993, 3.03, -1.578282);
            Expect("F9 Sam walks (4.03 ≤ 6)", !sam.Running && sam.CurrentKind == "mob1-walk", sam.CurrentKind);

            mgr.Tick(Frame);                                                                          // F10
            At("F10 Rex arrived", rex, -70, 0, 60);
            for (int i = 0; i < 3; i++) mgr.Tick(Frame);                                             // F11..F13
            At("F13 Sam at the loft's centre", sam, 100, 3.03, 0);
            mgr.Tick(Frame);                                                                          // F14
            Expect("F14 everyone stands", !dora.Moving && !sam.Moving && !rex.Moving && !lia.Moving, "");
            Expect("F14 Lia treads water again", lia.CurrentKind == "treading-water" && Math.Abs(lia.Drop - 1.3) < 1e-9, lia.CurrentKind);
            Near("F14 Lia's root stays on the mirror (max(0 + 1.3, 1.5))", lia.Position.Y, 1.5, 1e-4);
            Expect("F14 Sam's clip: the standing pose", sam.CurrentKind == "stand-relaxed", sam.CurrentKind);

            return $"walk W1..W2 ok (door route 1 station, stair route 3 stations + ride, run 3 frames, swim ghost cut {lia.Ghost!.CutY})";
        }
        finally
        {
            if (mgr is not null && GodotObject.IsInstanceValid(mgr)) mgr.QueueFree();
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static bool Near3(Vector3 v, double x, double y, double z)
        => v.DistanceTo(new Vector3((float)x, (float)y, (float)z)) < Tol;

    private static void At(string what, Figure f, double x, double y, double z)
        => Expect(what, Near3(f.Position, x, y, z), $"got {f.Position}, expected ({x}, {y}, {z})");

    private static void NearV(string what, Overview.Vec3 got, double x, double y, double z)
        => Expect(what, Math.Abs(got.X - x) < Tol && Math.Abs(got.Y - y) < Tol && Math.Abs(got.Z - z) < Tol,
                  $"got ({got.X}, {got.Y}, {got.Z}), expected ({x}, {y}, {z})");

    private static void Near(string what, double got, double want, double tol)
        => Expect(what, Math.Abs(got - want) < tol, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"walk {what}: {detail}");
    }
}
