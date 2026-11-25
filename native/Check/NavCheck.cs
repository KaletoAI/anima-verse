using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check nav</c> (part of every <c>--check</c>, plan 2026-11-25-client-ausfuehrung-e2 Task 3): the Godot bake and
/// navigation map of the nav world, built straight from its source — <c>fixtures/nav/scene_loc-nav.json</c> at world
/// (100, 0), yaw 0, plus the three hand boxes (armchair, bed, rug) — in polygon mode. Every number is derived by hand in
/// native/fixtures/README.md, section "Nav world" (the derived values and the check sections N0–N8 there); positions
/// are checked within 0.05 m, path lengths within ±0.05 (a navmesh is never compared bit for bit):
///
///   N0 two storey regions, two thresholds, two links, link connection radius 0.6; right after the first Ready the map
///      is not empty: Closest((97, 0, −1)) = (97, 0, −1);
///   N1 each threshold is welded on both sides (two edge connections each);
///   N2 the six closest-point probes, plus one probe 0.05 m inside every wall face: it lands 0.25 m (the agent radius)
///      off that face — the largest deviation is logged as the edge error;
///   N3 both ends of every link lie within the link connection radius of the mesh; the armchair access point is 0.10
///      off the mesh and the last straight piece to it crosses no wall;
///   N4 P1 through the door threshold T0 (8.410); N5 P2 up the stairs (19.630, one link point, owner 65536) and back;
///   N6 stairs off → P3 over the lift (14.279, owner 131200, entry (105.2, 0, 3.2)); N7 a lock on r-b closes T0, the
///      avatar's own room is never closed; N7b an unchanged lock or link state changes nothing and keeps Ready;
///   N8 Free() releases the map (the active map count is back to where it was after two physics frames).
/// </summary>
public static class NavCheck
{
    private const double Tol = 0.05;
    private const int MaxReadyFrames = 120;
    private const ulong Stairs = 65536, Lift = 131200;
    private const double P1Len = 8.410382, P2Len = 19.629751, P3Len = 14.279062;
    private static readonly Vec3 Start = new(97, 0, -1), P1End = new(103, 0, -1), Loft = new(104, 3, 2);

    // The three measured furniture boxes of the README table (world metres).
    private static readonly NavPropBox[] Boxes =
    {
        new(0, new Vec3(96.6, 0, -2.4), new Vec3(97.4, 0.9, -1.6)),     // armchair
        new(0, new Vec3(103.3, 0, 0.5), new Vec3(104.7, 0.5, 2.5)),     // bed
        new(0, new Vec3(96, 0, 1.25), new Vec3(98, 0.02, 2.75)),        // rug (no obstacle: 0.02 ≤ climb)
    };

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "nav");
        ScenePayload scene;
        using (var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "scene_loc-nav.json"))))
            scene = ScenePayload.Parse(doc.RootElement);
        var frame = new TileFrame(new Vec3(100, 0, 0), 0);
        var p = NavBakeParams.For(NavBakeMode.Polygon);
        var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), Boxes, true, p);

        int mapsBefore = NavigationServer3D.GetProcessInfo(NavigationServer3D.ProcessInfo.ActiveMaps);

        var storeys = await NavBake.BakeStoreysAsync(src, p, (_, _) => 0);
        var nav = LocationNav.Create(src, storeys, p);
        bool freed = false;
        try
        {
            Expect("N0 not ready before the first iteration", !nav.Ready && nav.ChangedAtIteration == 0, $"{nav.ChangedAtIteration}");
            await AwaitReady(host, nav, "N0");

            // ---- N0 the map ----
            Eq("N0 storey regions", nav.Storeys.Count, 2);
            Eq("N0 thresholds", nav.Thresholds.Count, 2);
            Eq("N0 links", nav.Links.Count, 2);
            Eq("N0 one more active map", NavigationServer3D.GetProcessInfo(NavigationServer3D.ProcessInfo.ActiveMaps), mapsBefore + 1);
            Expect("N0 fingerprint and mode", nav.Fingerprint == src.Fingerprint && nav.Mode == NavBakeMode.Polygon, nav.Fingerprint);
            Near("N0 link connection radius", NavigationServer3D.MapGetLinkConnectionRadius(nav.Map), 0.6, 1e-6);
            NearV("N0 closest on the first ready map", nav.Closest(Start), Start);

            // ---- N1 thresholds welded ----
            Eq("N1 T0 connections (r-a, r-b)", NavigationServer3D.RegionGetConnectionsCount(nav.Thresholds[0]), 2);
            Eq("N1 T1 connections (r-a, yard)", NavigationServer3D.RegionGetConnectionsCount(nav.Thresholds[1]), 2);

            // ---- N2 probes ----
            NearV("N2 in W5 → r-b", nav.Closest(new Vec3(100.05, 0, 0)), new Vec3(100.35, 0, 0));
            NearV("N2 armchair edge", nav.Closest(new Vec3(97, 0, -1.5)), new Vec3(97, 0, -1.35));
            NearV("N2 on the rug", nav.Closest(new Vec3(97, 0, 2)), new Vec3(97, 0, 2));
            NearV("N2 in the door", nav.Closest(new Vec3(100, 0, 2)), new Vec3(100, 0, 2));
            NearV("N2 in the yard", nav.Closest(new Vec3(97, 0, -5.5)), new Vec3(97, 0, -5.5));
            NearV("N2 beyond the yard", nav.Closest(new Vec3(97, 0, -7.2)), new Vec3(97, 0, -7.05));
            double edgeError = 0;
            foreach (var w in WallProbes)
            {
                var c = nav.Closest(w.Probe);
                double off = w.Axis == 'x' ? (c.X - w.Face) * w.Inward : (c.Z - w.Face) * w.Inward;
                double along = w.Axis == 'x' ? c.Z - w.Probe.Z : c.X - w.Probe.X;
                double err = Math.Abs(off - 0.25);
                edgeError = Math.Max(edgeError, err);
                Expect($"N2 wall {w.Name} probe lands r off the face", err <= Tol && Math.Abs(along) <= Tol && Math.Abs(c.Y - w.Probe.Y) <= Tol,
                       $"closest {Fmt(c)}, off the face {off:0.####}");
            }
            GD.Print($"[check-nav] edge_error max={edgeError:0.####}");

            // ---- N3 links on the mesh, armchair access ----
            foreach (var (owner, rid) in nav.Links)
            {
                var a = V(NavigationServer3D.LinkGetStartPosition(rid));
                var b = V(NavigationServer3D.LinkGetEndPosition(rid));
                Expect($"N3 link {owner} start on the mesh", Dist(a, nav.Closest(a)) <= 0.6, $"{Fmt(a)} → {Fmt(nav.Closest(a))}");
                Expect($"N3 link {owner} end on the mesh", Dist(b, nav.Closest(b)) <= 0.6, $"{Fmt(b)} → {Fmt(nav.Closest(b))}");
            }
            var access = new Vec3(97, 0, -1.45);
            var onMesh = nav.Closest(access);
            double gap = Dist(access, onMesh);
            Expect("N3 armchair access gap 0.10 ≤ 0.4", Math.Abs(gap - 0.10) <= Tol && gap <= 0.4, $"{gap:0.####} from {Fmt(onMesh)}");
            var walls = Collide.WallSegments(scene, 0, new P2(100, 0));
            Expect("N3 last piece crosses no wall", !walls.Any(s => Crosses(onMesh.X, onMesh.Z, access.X, access.Z, s)), Fmt(onMesh));

            // ---- N4 P1 ----
            var p1 = nav.Query(Start, P1End);
            Near("N4 P1 length", p1.Length, P1Len, Tol);
            Expect("N4 P1 through T0's corners", Has(p1, new Vec3(99.65, 0, 1.8)) && Has(p1, new Vec3(100.35, 0, 1.8)), Pts(p1));
            Expect("N4 P1 no link", p1.Owners.All(o => o == 0), Pts(p1));

            // ---- N5 P2 and back ----
            var p2 = nav.Query(Start, Loft);
            Near("N5 P2 length", p2.Length, P2Len, Tol);
            Expect("N5 P2 one link point, the stairs", p2.Owners.Count(o => o != 0) == 1 && p2.Owners.Single(o => o != 0) == Stairs, Pts(p2));
            NearV("N5 P2 ends in the loft", p2.Points[^1], Loft);
            var back = nav.Query(Loft, Start);
            Near("N5 way back length", back.Length, P2Len, Tol);
            Expect("N5 way back over the stairs", back.Owners.Count(o => o != 0) == 1 && back.Owners.Single(o => o != 0) == Stairs, Pts(back));

            // ---- N6 stairs off → the lift ----
            Expect("N6 stairs off changes the map", nav.SetLinkEnabled(Stairs, false), "");
            await AwaitReady(host, nav, "N6 off");
            var p3 = nav.Query(Start, Loft);
            Near("N6 P3 length", p3.Length, P3Len, Tol);
            Expect("N6 P3 over the lift", p3.Owners.Count(o => o != 0) == 1 && p3.Owners.Single(o => o != 0) == Lift, Pts(p3));
            int entry = p3.Owners.ToList().FindIndex(o => o == Lift);
            NearV("N6 lift entry point", p3.Points[entry], new Vec3(105.2, 0.0, 3.2));
            Expect("N6 stairs on again", nav.SetLinkEnabled(Stairs, true), "");
            await AwaitReady(host, nav, "N6 on");

            // ---- N7 locks ----
            var lockB = new Dictionary<string, string> { ["r-b"] = "" };
            Expect("N7 lock r-b from r-a closes T0", nav.ApplyLocks(lockB, "r-a"), "");
            await AwaitReady(host, nav, "N7 locked");
            Expect("N7 T0 off, T1 on", !NavigationServer3D.RegionGetEnabled(nav.Thresholds[0]) && NavigationServer3D.RegionGetEnabled(nav.Thresholds[1]), $"T0 {NavigationServer3D.RegionGetEnabled(nav.Thresholds[0])} T1 {NavigationServer3D.RegionGetEnabled(nav.Thresholds[1])} ");
            var locked = nav.Query(Start, P1End);
            Expect("N7 P1 ends ≥ 0.5 short of the target", locked.Points.Count == 0 || Dist(locked.Points[^1], P1End) >= 0.5, Pts(locked));
            Expect("N7 unlock opens T0", nav.ApplyLocks(null, "r-a"), "");
            await AwaitReady(host, nav, "N7 unlocked");
            Near("N7 P1 length again", nav.Query(Start, P1End).Length, P1Len, Tol);
            Expect("N7 own room stays open", !nav.ApplyLocks(lockB, "r-b") && NavigationServer3D.RegionGetEnabled(nav.Thresholds[0]), "");
            // Lock and unlock within one frame (the server's getters still answer the old state): both are changes,
            // and the region ends up on.
            Expect("N7 lock + unlock in one frame", nav.ApplyLocks(lockB, "r-a") && nav.ApplyLocks(null, "r-a"), "");
            await AwaitReady(host, nav, "N7 lock + unlock");
            Expect("N7 T0 on after lock + unlock", NavigationServer3D.RegionGetEnabled(nav.Thresholds[0]), "");
            Near("N7 P1 length after lock + unlock", nav.Query(Start, P1End).Length, P1Len, Tol);

            // ---- N7b no change, no wait ----
            nav.ApplyLocks(null, "r-a");
            ulong changedAt = nav.ChangedAtIteration;
            Expect("N7b same locks twice → false", !nav.ApplyLocks(null, "r-a"), "");
            Expect("N7b ChangedAtIteration kept, Ready stays", nav.ChangedAtIteration == changedAt && nav.Ready, $"{nav.ChangedAtIteration} vs {changedAt}");
            Expect("N7b enabled link on again → false", !nav.SetLinkEnabled(Stairs, true) && nav.Ready, "");

            // ---- N8 free ----
            nav.Free();
            freed = true;
            for (int i = 0; i < 2; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
            int mapsAfter = NavigationServer3D.GetProcessInfo(NavigationServer3D.ProcessInfo.ActiveMaps);
            Eq("N8 active maps back", mapsAfter, mapsBefore);

            return $"nav regions={nav.Storeys.Count} thresholds={nav.Thresholds.Count} links={nav.Links.Count} p1={p1.Length:0.###} "
                   + $"p2={p2.Length:0.###} p3={p3.Length:0.###} edge_error={edgeError:0.###} maps={mapsAfter}";
        }
        finally
        {
            if (!freed) nav.Free();
        }
    }

    /// <summary>Waits physics frames until the map answers with its current state (decision 4), at most 120.</summary>
    private static async Task AwaitReady(Node host, LocationNav nav, string what)
    {
        for (int i = 0; i < MaxReadyFrames && !nav.Ready; i++)
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
        Expect($"{what} map ready within {MaxReadyFrames} physics frames", nav.Ready,
               $"iteration {NavigationServer3D.MapGetIterationId(nav.Map)}, changed at {nav.ChangedAtIteration}");
    }

    /// <summary>
    /// One probe 0.05 m inside each wall face (in the wall body, on the room side): the closest walkable point lies on
    /// the eroded edge, 0.25 m from the face along <c>Inward</c>; the other horizontal coordinate stays.
    /// </summary>
    private sealed record WallProbe(string Name, Vec3 Probe, char Axis, double Face, int Inward);

    private static readonly WallProbe[] WallProbes =
    {
        new("W1a", new Vec3(95, 0, -3.95), 'z', -3.9, 1),
        new("W1b", new Vec3(98.5, 0, -3.95), 'z', -3.9, 1),
        new("W2", new Vec3(95, 0, 3.95), 'z', 3.9, -1),
        new("W3", new Vec3(94.05, 0, 0), 'x', 94.1, 1),
        new("W4", new Vec3(105.95, 0, 0), 'x', 105.9, -1),
        new("W5", new Vec3(99.95, 0, -1), 'x', 99.9, -1),
        new("W6", new Vec3(100.05, 0, 3.2), 'x', 100.1, 1),
        new("U-south", new Vec3(105, 3, -3.95), 'z', -3.9, 1),
        new("U-east", new Vec3(105.95, 3, 0), 'x', 105.9, -1),
        new("U-north", new Vec3(103, 3, 3.95), 'z', 3.9, -1),
        new("U-west", new Vec3(100.05, 3, 0), 'x', 100.1, 1),
    };

    private static bool Crosses(double ax, double az, double bx, double bz, WallSegment s)
    {
        double rx = bx - ax, rz = bz - az, sx = s.Bx - s.Ax, sz = s.Bz - s.Az;
        double denom = rx * sz - rz * sx;
        if (Math.Abs(denom) < 1e-12) return false;
        double qx = s.Ax - ax, qz = s.Az - az;
        double t = (qx * sz - qz * sx) / denom, u = (qx * rz - qz * rx) / denom;
        return t >= 0 && t <= 1 && u >= 0 && u <= 1;
    }

    private static bool Has(NavPath path, Vec3 p) => path.Points.Any(q => Dist(q, p) <= Tol);
    private static double Dist(Vec3 a, Vec3 b) => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y) + (a.Z - b.Z) * (a.Z - b.Z));
    private static Vec3 V(Vector3 v) => new(v.X, v.Y, v.Z);
    private static string Fmt(Vec3 v) => $"({v.X:0.###}, {v.Y:0.###}, {v.Z:0.###})";
    private static string Pts(NavPath p)
        => $"len {p.Length:0.####}: " + string.Join(" ", p.Points.Select((q, i) => Fmt(q) + (p.Owners[i] != 0 ? $"[{p.Owners[i]}]" : "")));

    private static void NearV(string what, Vec3 got, Vec3 want)
        => Expect(what, Dist(got, want) <= Tol, $"got {Fmt(got)}, want {Fmt(want)}");

    private static void Near(string what, double got, double want, double tol)
        => Expect(what, Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");

    private static void Eq(string what, long got, long want) => Expect(what, got == want, $"got {got}, want {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"nav {what}: {detail}");
    }
}
