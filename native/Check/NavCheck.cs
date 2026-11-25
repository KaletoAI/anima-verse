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
/// (100, 0), yaw 0, plus the three hand boxes (armchair, bed, rug). Every number is derived by hand in
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
///
/// Task 4 then builds the same scene as a world through <see cref="WorldBuilder"/> (<c>fixtures/nav/</c>, goto "Navhaus")
/// and lets the real residency path bake it (the check never requests a bake itself):
///
///   N9  the swapped navigation: three measured furniture boxes (± 0.01), the Task 1 fingerprint, P1 8.410 again;
///   N10 an unchanged DeriveStands bakes nothing; the armchair moved 0.5 m → a new map, the old one freed;
///   N11 a bake in flight while the detail unmounts → no navigation, no subscription, active maps back to the start;
///   N12 a lock on r-b keeps NavFor in its frame, closes T0, survives a rebake (T0 of the new map off), unlock opens it;
///   N13 no MapChanged subscription before the first bake or once nothing is pending, the first map swapped on its
///       first MapChanged, StopResidency during a bake unsubscribes and leaves no map.
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
        var p = NavBakeParams.Current;
        var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), Boxes, true, p);

        // An earlier check's world may have released its location maps in its last frame; the server counts them until
        // its next sync, so the baseline is taken two physics frames later.
        await PhysicsFrames(host, 2);
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
            Expect("N0 fingerprint", nav.Fingerprint == src.Fingerprint, nav.Fingerprint);
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
            foreach (var (w, c, off, along, err) in WallErrors(nav))
            {
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

            var (p1, p2, p3) = await PathSectionsAsync(host, nav);

            // ---- N8 free ----
            nav.Free();
            freed = true;
            for (int i = 0; i < 2; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
            int mapsAfter = NavigationServer3D.GetProcessInfo(NavigationServer3D.ProcessInfo.ActiveMaps);
            Eq("N8 active maps back", mapsAfter, mapsBefore);

            var worldPart = await WorldAsync(host, fixtures);
            return $"nav regions={nav.Storeys.Count} thresholds={nav.Thresholds.Count} links={nav.Links.Count} p1={p1.Length:0.###} "
                   + $"p2={p2.Length:0.###} p3={p3.Length:0.###} edge_error={edgeError:0.###} maps={mapsAfter}; {worldPart}";
        }
        finally
        {
            if (!freed) nav.Free();
        }
    }

    /// <summary>
    /// N4–N7b on a ready map of the nav world (shared by <c>--check nav</c> and <c>--check navcompare</c>); throws at the
    /// first failed expectation and leaves the map with the stairs on and no lock.
    /// </summary>
    private static async Task<(NavPath P1, NavPath P2, NavPath P3)> PathSectionsAsync(Node host, LocationNav nav)
    {
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
        return (p1, p2, p3);
    }

    /// <summary>N2 wall probes: the closest point, its offset from the face, its drift along it, |offset − r|.</summary>
    private static IEnumerable<(WallProbe W, Vec3 C, double Off, double Along, double Err)> WallErrors(LocationNav nav)
    {
        foreach (var w in WallProbes)
        {
            var c = nav.Closest(w.Probe);
            double off = w.Axis == 'x' ? (c.X - w.Face) * w.Inward : (c.Z - w.Face) * w.Inward;
            double along = w.Axis == 'x' ? c.Z - w.Probe.Z : c.X - w.Probe.X;
            yield return (w, c, off, along, Math.Abs(off - 0.25));
        }
    }

// ---- navcompare: the bake measured (plan E2 Task 5, decision 9) --------------------------------------------

    /// <summary>
    /// <c>--check navcompare</c> (never part of the full <c>--check</c>; plan E2 Task 5 measured the polygon bake against the
    /// voxel bake with it, docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md, and it stays as the
    /// measurement of the winner for E7): per fixture the median of five SYNCHRONOUS bakes — the time inside Godot's bake
    /// calls only, never "request to callback" of the async bake, whose callback arrives with the server sync on the main
    /// thread (review W7) — the polygon count over all storeys, the largest N2 wall-probe edge error and N4–N7 passed (nav
    /// world only), and the connection count of the first threshold region on the ready map. The other fixtures are
    /// placed at (0, 0, 0), yaw 0, without furniture boxes: they are time and polygon probes, not path evidence. One line
    /// per fixture: <c>[navcompare] fixture=… mode=polygon ms=… polys=… edge_err=… paths=ok|fail thresholds_welded=…</c>.
    /// </summary>
    public static async Task<string> RunCompareAsync(Node3D host, string fixtures)
    {
        var rows = new (string Fixture, string File, TileFrame Frame, NavPropBox[] Boxes)[]
        {
            ("nav", "nav/scene_loc-nav.json", new TileFrame(new Vec3(100, 0, 0), 0), Boxes),
            ("walk", "walk/scene_loc-hall.json", new TileFrame(new Vec3(0, 0, 0), 0), Array.Empty<NavPropBox>()),
            ("embody", "embody/scene_loc-hall.json", new TileFrame(new Vec3(0, 0, 0), 0), Array.Empty<NavPropBox>()),
            ("storeys", "storeys/scene_loc-tower.json", new TileFrame(new Vec3(0, 0, 0), 0), Array.Empty<NavPropBox>()),
        };
        var p = NavBakeParams.Current;
        double total = 0;
        string edgeNav = "-", pathsNav = "-";
        foreach (var (name, path, frame, boxes) in rows)
        {
            ScenePayload scene;
            using (var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, path))))
                scene = ScenePayload.Parse(doc.RootElement);
            var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), boxes, true, p);
            var times = new double[5];
            NavigationMesh[] meshes = Array.Empty<NavigationMesh>();
            for (int i = 0; i < times.Length; i++) meshes = NavBake.BakeStoreys(src, p, null, out times[i]);
            Array.Sort(times);
            double ms = times[times.Length / 2];
            total += ms;
            int polys = meshes.Sum(m => m.GetPolygonCount());

            var nav = LocationNav.Create(src, meshes, p);
            try
            {
                await AwaitReady(host, nav, $"navcompare {name}");
                int welded = nav.Thresholds.Count == 0 ? 0
                    : NavigationServer3D.RegionGetConnectionsCount(nav.Thresholds[nav.Thresholds.Keys.Min()]);
                string edge = "-", paths = "-";
                if (name == "nav")
                {
                    edge = WallErrors(nav).Max(e => e.Err).ToString("0.####", System.Globalization.CultureInfo.InvariantCulture);
                    try
                    {
                        await PathSectionsAsync(host, nav);
                        paths = "ok";
                    }
                    catch (InvalidOperationException e)
                    {
                        paths = "fail";
                        GD.Print($"[navcompare] fixture={name} paths failed: {e.Message}");
                    }
                    (edgeNav, pathsNav) = (edge, paths);
                }
                GD.Print(FormattableString.Invariant(
                    $"[navcompare] fixture={name} mode=polygon ms={ms:0.###} polys={polys} edge_err={edge} paths={paths} thresholds_welded={welded}"));
            }
            finally
            {
                nav.Free();
            }
        }
        await PhysicsFrames(host, 2);
        return FormattableString.Invariant($"navcompare fixtures={rows.Length} ms_total={total:0.###} edge_err={edgeNav} paths={pathsNav}");
    }

    // ---- N9–N13: the bake on the real mount path (Task 4) ------------------------------------------------------

    /// <summary>
    /// The nav world built through <see cref="WorldBuilder"/> (as <c>WalkCheck</c> does): the slot turns near on the real
    /// residency path, which is where the bake is requested — the check never calls <c>RequestNavBake</c> itself. Every
    /// expected number is the hand derivation of native/fixtures/README.md, section "Nav world" (N9–N13 there).
    /// </summary>
    private static async Task<string> WorldAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "nav");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "NavWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-nav] " + line), strict: true);
        int mapsBefore = ActiveMaps();
        try
        {
            // ---- N13 (first half) no subscription before the first bake ----
            Expect("N13 not subscribed to MapChanged before the first bake", !builder.NavMapChangedSubscribed, "");
            await builder.BuildAsync(world, "Navhaus");
            var slot = builder.Slots["loc-nav"];
            Expect("N9 the slot is near after the build", slot.Ring == Ring.Near, $"{slot.Ring}");
            slot.Fade.Snap(1);
            var nav = await AwaitNav(host, builder, slot, null, "N9");
            Eq("N13 swapped on the first MapChanged of the new map", builder.NavArmCalls, 1);
            Expect("N13 unsubscribed once no map is pending", !builder.NavMapChangedSubscribed, "");

            // ---- N9 the baked navigation of the mount ----
            var boxes = builder.NavPropBoxes(slot);
            Eq("N9 three furniture boxes", boxes.Count, 3);
            foreach (var want in Boxes)
                Expect($"N9 box {Fmt(want.Min)}…{Fmt(want.Max)} measured",
                       boxes.Any(b => b.Level == want.Level && Dist(b.Min, want.Min) <= 0.01 && Dist(b.Max, want.Max) <= 0.01),
                       string.Join(" ", boxes.Select(b => $"{b.Level}:{Fmt(b.Min)}…{Fmt(b.Max)}")));
            var scene = slot.Scene!;
            var frame = new TileFrame(new Vec3(100, 0, 0), 0);
            var p = NavBakeParams.Current;
            // The same boxes = the measured ones: they match the table within 0.01 but are float measurements, and the
            // fingerprint hashes the exact numbers ("R" format).
            var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), boxes, true, p);
            Expect("N9 fingerprint = the Task 1 source with the same boxes", nav.Fingerprint == src.Fingerprint,
                   $"{nav.Fingerprint} vs {src.Fingerprint}");
            Near("N9 P1 over NavFor", nav.Query(Start, P1End).Length, P1Len, Tol);

            // ---- N10 unchanged → same map; the armchair moved → a new map, the old one freed ----
            var map0 = nav.Map;
            builder.DeriveStands(slot);
            Expect("N10 unchanged source → nothing baked, nothing pending", !builder.NavBaking(slot) && !builder.NavMapChangedSubscribed, "");
            await PhysicsFrames(host, 3);
            Expect("N10 unchanged source → the same map", builder.NavFor(slot)?.Map == map0, "");
            var chair = Armchair(slot);
            int mapsMid = ActiveMaps();
            chair.Node!.Position += new Vector3(0.5f, 0, 0);
            builder.DeriveStands(slot);
            var moved = builder.NavPropBoxes(slot).Where(b => b.Max.Y > 0.8).ToList();
            Expect("N10 the armchair box moved by 0.5", moved.Count == 1 && Math.Abs(moved[0].Min.X - 97.1) <= 0.01 && Math.Abs(moved[0].Max.X - 97.9) <= 0.01,
                   string.Join(" ", moved.Select(b => $"{Fmt(b.Min)}…{Fmt(b.Max)}")));
            var nav2 = await AwaitNav(host, builder, slot, map0, "N10");
            Expect("N10 a new fingerprint", nav2.Fingerprint != nav.Fingerprint, "");
            await PhysicsFrames(host, 2);
            Eq("N10 the old map freed (active maps unchanged)", ActiveMaps(), mapsMid);

            // ---- N12 locks survive a rebake ----
            var lockB = new LockState(new Dictionary<string, string> { ["r-b"] = "" }, "loc-nav", new Dictionary<string, string>(), "r-a");
            builder.SetLocks(lockB);
            Expect("N12 NavFor keeps the same map in the frame of SetLocks", ReferenceEquals(builder.NavFor(slot), nav2), "");
            await AwaitReady(host, nav2, "N12 locked");
            Expect("N12 T0 off", !NavigationServer3D.RegionGetEnabled(nav2.Thresholds[0]), "");
            chair.Node!.Position -= new Vector3(0.5f, 0, 0);
            builder.DeriveStands(slot);
            var nav3 = await AwaitNav(host, builder, slot, nav2.Map, "N12 rebake");
            Expect("N12 the rebake is the first source again (cache)", nav3.Fingerprint == src.Fingerprint, "");
            Expect("N12 T0 of the new map still off", !NavigationServer3D.RegionGetEnabled(nav3.Thresholds[0])
                   && NavigationServer3D.RegionGetEnabled(nav3.Thresholds[1]), "");
            var locked = nav3.Query(Start, P1End);
            Expect("N12 P1 ends ≥ 0.5 short of the target", locked.Points.Count == 0 || Dist(locked.Points[^1], P1End) >= 0.5, Pts(locked));
            builder.SetLocks(LockState.None);
            await AwaitReady(host, nav3, "N12 unlocked");
            Expect("N12 no lock → T0 on", NavigationServer3D.RegionGetEnabled(nav3.Thresholds[0]), "");
            Near("N12 P1 again", nav3.Query(Start, P1End).Length, P1Len, Tol);

            // ---- N11 a bake in flight while the detail unmounts (the residency way down) ----
            // The way down is queued first (the driver steps in a continuation), then the armchair moves and a bake starts
            // while the slot is still near; the unmount runs before that bake's result arrives.
            int dropped = builder.NavBakesDropped;
            builder.SetOpen("loc-nav", false);
            using (var away = StreamMap(dir, avatar: false))
            {
                builder.SetStreamView(away.RootElement, new[] { (400.0, 0.0) });
                builder.TickStreamRings();
                Expect("N11 still near in the frame of the request", slot.Ring == Ring.Near, $"{slot.Ring}");
                chair.Node!.Position += new Vector3(0.25f, 0, 0);
                builder.DeriveStands(slot);
                Expect("N11 a bake is running", builder.NavBaking(slot), "");
                await builder.WhenResidencyIdle();
            }
            Expect("N11 the slot went far", slot.Ring == Ring.Far, $"{slot.Ring}");
            await PhysicsFrames(host, 60);
            Expect("N11 no navigation after the unmount", slot.Nav is null && builder.NavFor(slot) is null && !builder.NavBaking(slot), "");
            Expect("N11 unsubscribed", !builder.NavMapChangedSubscribed, "");
            Eq("N11 the running bake's result was dropped", builder.NavBakesDropped, dropped + 1);
            Eq("N11 active maps back to the start", ActiveMaps(), mapsBefore);

            // ---- N13 (second half) StopResidency during a running bake ----
            using (var home = StreamMap(dir, avatar: true))
            {
                builder.SetStreamView(home.RootElement, new[] { (97.0, -1.0) });
                builder.TickStreamRings();
                await builder.WhenResidencyIdle();
            }
            Expect("N13 the slot is near again", slot.Ring == Ring.Near, $"{slot.Ring}");
            var chair2 = Armchair(slot);
            chair2.Node!.Position += new Vector3(0.35f, 0, 0);
            builder.DeriveStands(slot);
            Expect("N13 a bake is running", builder.NavBaking(slot), "");
            builder.StopResidency();
            Expect("N13 StopResidency unsubscribes and drops the navigation", !builder.NavMapChangedSubscribed && slot.Nav is null, "");
            await PhysicsFrames(host, 60);
            Expect("N13 the stopped bake left nothing", !builder.NavMapChangedSubscribed && builder.NavFor(slot) is null, "");
            Eq("N13 the running bake's result was dropped", builder.NavBakesDropped, dropped + 2);
            Eq("N13 active maps back to the start", ActiveMaps(), mapsBefore);

            return $"world arms={builder.NavArmCalls} maps={ActiveMaps()}";
        }
        finally
        {
            builder.StopResidency();
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    /// <summary>Physics frames until <c>NavFor(slot)</c> is a map other than <paramref name="old"/>, at most 240.</summary>
    private static async Task<LocationNav> AwaitNav(Node host, WorldBuilder builder, LocationSlot slot, Rid? old, string what)
    {
        for (int i = 0; i < 240; i++)
        {
            if (builder.NavFor(slot) is { } n && (old is null || n.Map != old.Value)) return n;
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
        }
        throw new InvalidOperationException($"nav {what}: no (new) navigation within 240 physics frames");
    }

    private static async Task PhysicsFrames(Node host, int n)
    {
        for (int i = 0; i < n; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
    }

    private static int ActiveMaps() => NavigationServer3D.GetProcessInfo(NavigationServer3D.ProcessInfo.ActiveMaps);

    /// <summary>The armchair placement: room r-a, anchor (−3, −2) (README table).</summary>
    private static PlacedModel Armchair(LocationSlot slot)
        => slot.Placements.Single(r => r.Spec.Role == "prop" && r.Spec.RoomId == "r-a" && r.Node is not null
                                       && Math.Abs(r.Spec.AnchorX + 3) < 1e-6 && Math.Abs(r.Spec.AnchorZ + 2) < 1e-6);

    /// <summary>worldmap.json as the stream view; without the avatar no location is pinned by it.</summary>
    private static JsonDocument StreamMap(string dir, bool avatar)
    {
        var node = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "worldmap.json")))!;
        if (!avatar) node["avatar"] = "";
        return JsonDocument.Parse(node.ToJsonString());
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
