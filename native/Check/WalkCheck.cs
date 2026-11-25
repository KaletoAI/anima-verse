using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Nav;
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
///   W2 poll 2, frames of 0.25 s: Rex runs over 10 m of open grass (×1.8 beyond 6 m, then walks); Lia swims. The two
///      room changes (Dora room A → room B, Sam room A → the loft) carry no server order, so each walks a client-local
///      `walk` (plan E3 Task 9, `local:<n>`) over the hall's navmesh (which bakes no party wall: Dora's path is the
///      straight 6 m, the door gap is OrderCheck R7's case) and rides no link, Sam's path has exactly one link section
///      (the flight); both
///      end on their row's point (103, 0.01, 1) and the loft centre (100, 3.03, 0), no station or stair ride of the
///      old room routing is left on the figure.
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
                ClipFit = ClipFitMode.OnDemandSync,
                AutoTick = false, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
                NavOf = loc => builder.Slots.TryGetValue(loc, out var s) ? builder.NavFor(s) : null,
            };
            LocationNav? nav = null;
            for (int i = 0; i < 240 && (nav = builder.NavFor(hall)) is null; i++)
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
            if (nav is null) throw new InvalidOperationException("walk: no navigation within 240 physics frames");
            for (int i = 0; i < 120 && !nav.Ready; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
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
            // The sink hangs the body under its bind anchoring (groundY: the mesh's lowest point on the root, Task 32).
            Expect("W1 Lia's body hangs the idle sink under the root", Math.Abs(lia.Body!.Position.Y - lia.BindOffset.Y + 1.3) < 1e-5,
                   $"{lia.Body.Position} bind {lia.BindOffset}");
            Expect("W1 Lia's ghost cut at the mirror", lia.Ghost is { Visible: true } g && Math.Abs(g.CutY - 1.5) < 1e-9,
                   $"ghost {lia.Ghost?.Visible} cut {lia.Ghost?.CutY}");
            Expect("W1 Dora stands dry", dora.CurrentKind == "stand-relaxed" && dora.Drop == 0 && dora.Ghost is not { Visible: true },
                   $"kind {dora.CurrentKind} drop {dora.Drop}");
            mgr.Tick(Frame);
            Near("W1 Lia floats at the mirror", lia.Position.Y, 1.5, 1e-4);

            // ---- W2 poll 2 ----
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap_poll2.json"))))
                await mgr.Apply(map.RootElement);
            // Plan E3 Task 9: the room changes without an order are client-local walks over the navmesh.
            foreach (var (fig, label) in new[] { (dora, "Dora"), (sam, "Sam") })
                Expect($"W2 {label} walks a local order, no station or ride", mgr.OrderPlayerOf(fig.CharacterName)?.Current is { IsLocal: true, Kind: "walk" }
                       && fig.Waypoints.Count == 0 && fig.Ride is null, $"{mgr.OrderPlayerOf(fig.CharacterName)?.Current?.Id} {fig.Waypoints.Count}");
            Expect("W2 nobody moved yet", Near3(dora.Position, 97, 0.01, 1) && Near3(rex.Position, -80, 0, 60), "");

            mgr.Tick(Frame);                                                                          // F1
            At("F1 Rex runs 1.53 m", rex, -78.47, 0, 60);
            At("F1 Lia swims 0.85 m", lia, 40.85, 1.5, 0);
            Expect("F1 Lia swims (no run on water)", lia.CurrentKind == "breast-stroke" && !lia.Running && Math.Abs(lia.Drop - 0.35) < 1e-9,
                   $"kind {lia.CurrentKind} drop {lia.Drop}");
            Expect("F1 Lia's ghost still at the mirror", lia.Ghost is { Visible: true } g1 && Math.Abs(g1.CutY - 1.5) < 1e-9, "");
            var doraPlan = mgr.OrderPlayerOf(dora.CharacterName)?.WalkPlan;
            var samPlan = mgr.OrderPlayerOf(sam.CharacterName)?.WalkPlan;
            Expect("F1 both walks planned", doraPlan is not null && samPlan is not null, "");
            Expect("F1 Dora's path rides no link", !doraPlan!.Steps.OfType<NavLink>().Any(), "");
            // The walk world's navmesh carries no party wall (its scene bakes the floors only; the door gap is the orders
            // world's case, OrderCheck R7): the path is the mesh's own, straight across, 6 m.
            Expect("F1 Dora's path is the mesh's 6 m", Math.Abs(doraPlan.Length - 6) <= 0.05, $"{doraPlan.Length}");
            Expect("F1 Sam's path has exactly one link section (the flight)", samPlan!.Steps.OfType<NavLink>().Count() == 1,
                   $"{samPlan.Steps.OfType<NavLink>().Count()}");

            mgr.Tick(Frame); mgr.Tick(Frame);                                                         // F2, F3
            At("F3 Rex still runs (6.94 > 6)", rex, -75.41, 0, 60);
            mgr.Tick(Frame);                                                                          // F4
            At("F4 Rex walks (5.41 ≤ 6)", rex, -74.56, 0, 60);
            Expect("F4 Rex's clip is the walk", !rex.Running && rex.CurrentKind == "mob1-walk", rex.CurrentKind);
            for (int i = 0; i < 3; i++) mgr.Tick(Frame);                                             // F5..F7
            At("F7 Lia 7 × 0.85 m out", lia, 45.95, 1.5, 0);
            mgr.Tick(Frame);                                                                          // F8
            At("F8 Lia arrived", lia, 46.8, 1.5, 0);
            mgr.Tick(Frame); mgr.Tick(Frame);                                                         // F9, F10
            At("F10 Rex arrived", rex, -70, 0, 60);
            // The walks: at 1.4 m/s (LocalOrders.DefaultSpeedMS) both are over within 30 s, plus the 0.3 s end blend.
            for (int i = 0; i < 120 && (mgr.HasLiveOrder(dora.CharacterName) || mgr.HasLiveOrder(sam.CharacterName)); i++) mgr.Tick(Frame);
            for (int i = 0; i < 4; i++) mgr.Tick(Frame);
            At("W2 Dora arrived on her point", dora, 103, 0.01, 1);
            At("W2 Sam at the loft's centre", sam, 100, 3.03, 0);
            mgr.Tick(Frame);
            Expect("W2 everyone stands", !dora.Moving && !sam.Moving && !rex.Moving && !lia.Moving, "");
            Expect("W2 Lia treads water again", lia.CurrentKind == "treading-water" && Math.Abs(lia.Drop - 1.3) < 1e-9, lia.CurrentKind);
            Near("W2 Lia's root stays on the mirror (max(0 + 1.3, 1.5))", lia.Position.Y, 1.5, 1e-4);

            return $"walk W1..W2 ok (local room walks {doraPlan.Length:0.##} m / {samPlan.Length:0.##} m, run 3 frames, swim ghost cut {lia.Ghost!.CutY})";
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
