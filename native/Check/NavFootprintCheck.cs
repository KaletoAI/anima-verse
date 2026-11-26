using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Part of <c>--check nav</c>: the fix plan "Kollision im nativen Client" (prop footprints, door funnel), measured on baked
/// maps — never by screenshot. Every expected number is derived by hand in native/fixtures/README.md, section "Nav world"
/// ("F1–F5"); the open scene is one 16 × 16 m room without walls (boundary and floor x −8…8, z −8…8), the props are
/// prisms built here as triangles and turned into outlines by <see cref="PropFootprint"/> with the band 0.25…1.8:
///
///   F1 a box 1.6 × 0.9 × 0.75, once the prop turned 30°, once the location (frame yaw 30°): along the box's own outward
///      normals (7 samples per edge, at 1/8 … 7/8) the first mesh point is 0.24 … 0.35 m off the box face (r 0.25; the
///      0.0025 m probe step and float noise below it, + 0.05 raster + 0.05 bake cell above it);
///   F2 a one-piece L sofa (bars 2.6 × 0.9 and 0.9 × 2.0, h 0.85) at 0° and 45°: the centre of the free inner corner lies on
///      the mesh, the two seat fronts facing it are ≤ 0.35 m off the mesh;
///   F3 two 1 × 1 boxes with a 0.7 m gap, turned 30°: keys along the gap's centre line walk through (local z ≥ 1.0);
///   F4 the nav world's door T0 (0.9 m): keys straight through it at 60 Hz (wall clamp, then navmesh clamp) from 19 offsets
///      −0.45 … 0.45 in 0.05 steps: every offset with |o| ≤ 0.40 gets through (≥ 17 of 19);
///   F5 a rug (top 0.02) and a lamp (1.9 … 2.2) have no footprint.
/// </summary>
public static class NavFootprintCheck
{
    private const string OpenScene = """
        {"k": 1, "storey_m": 3, "boundary": [[-8, -8], [8, -8], [8, 8], [-8, 8]],
         "levels": [{"level": 0, "floor_y": 0}],
         "rooms": [{"room_id": "r", "level": 0, "outline": [[-8, -8], [8, -8], [8, 8], [-8, 8]]}],
         "floor_plan": [{"room_id": "r", "polygon_world": [[-8, -8], [8, -8], [8, 8], [-8, 8]], "closed": true}]}
        """;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var p = NavBakeParams.Current;
        var parts = new List<string>();
        double low = p.AgentMaxClimb, high = p.AgentHeight;

        // ---- F1 the turned box ----
        foreach (var (name, frame, yaw) in new[] { ("prop30", new TileFrame(new Vec3(0, 0, 0), 0), 30.0), ("loc30", new TileFrame(new Vec3(0, 0, 0), Math.PI / 6), 0.0) })
        {
            var box = Rect(0, 0, 1.6, 0.9);
            var fp = Footprint(frame, Prism(frame, box, 0, 0.75, yaw), yaw, low, high);
            Expect($"F1 {name} one rectangle", fp is { Outlines.Count: 1 }, $"{fp?.Outlines.Count}");
            var nav = await Bake(host, frame, Props(fp!));
            try
            {
                var d = EdgeDistances(nav, frame, box, yaw);
                Expect($"F1 {name} 28 edge samples 0.24…0.35 off the box", d.Count == 28 && d.All(x => x >= 0.24 && x <= 0.35),
                       string.Join(" ", d.Select(x => x.ToString("0.###"))));
                parts.Add($"F1 {name} edge={d.Min():0.###}…{d.Max():0.###}");
            }
            finally { nav.Free(); }
        }

        // ---- F2 the one-piece L sofa ----
        foreach (var yaw in new[] { 0.0, 45.0 })
        {
            var f = new TileFrame(new Vec3(0, 0, 0), 0);
            // local L: bars x −1.3…1.3, z −1…−0.1 and x −1.3…−0.4, z −1…1; the free inner corner x −0.4…1.3, z −0.1…1
            var l = new[] { new P2(-1.3, -1), new P2(1.3, -1), new P2(1.3, -0.1), new P2(-0.4, -0.1), new P2(-0.4, 1), new P2(-1.3, 1) };
            var fp = Footprint(f, Prism(f, l, 0, 0.85, yaw), yaw, low, high);
            Expect($"F2 L{yaw} has a footprint", fp is not null, "");
            var nav = await Bake(host, f, Props(fp!));
            try
            {
                var c = Local(f, 0.45, 0.45, yaw);
                var on = nav.Closest(new Vec3(c.X, 0, c.Z));
                double off = Math.Sqrt((on.X - c.X) * (on.X - c.X) + (on.Z - c.Z) * (on.Z - c.Z));
                Expect($"F2 L{yaw} the inner corner's centre (0.45, 0.45) is on the mesh", off <= NavClamp.OnMeshTolM, $"off {off:0.###}");
                var nz = Unit(Sub(Local(f, 0, 1, yaw), Local(f, 0, 0, yaw)));
                var nx = Unit(Sub(Local(f, 1, 0, yaw), Local(f, 0, 0, yaw)));
                var fronts = new List<double>();
                foreach (var x in new[] { 0.2, 0.45, 0.7, 0.95, 1.2 }) fronts.Add(AlongNormal(nav, Local(f, x, -0.1, yaw), nz));
                foreach (var z in new[] { 0.3, 0.45, 0.6, 0.75 }) fronts.Add(AlongNormal(nav, Local(f, -0.4, z, yaw), nx));
                Expect($"F2 L{yaw} the seat fronts ≤ 0.35 off the mesh", fronts.All(x => x <= 0.35), string.Join(" ", fronts.Select(x => x.ToString("0.###"))));
                parts.Add($"F2 L{yaw} off={off:0.###} front≤{fronts.Max():0.###}");
            }
            finally { nav.Free(); }
        }

        // ---- F3 the 0.7 m gap, turned 30° ----
        {
            var f = new TileFrame(new Vec3(0, 0, 0), 0);
            var a = Footprint(f, Prism(f, Rect(-0.85, 0, 1, 1), 0, 0.75, 30), 30, low, high)!;
            var b = Footprint(f, Prism(f, Rect(0.85, 0, 1, 1), 0, 0.75, 30), 30, low, high)!;
            var nav = await Bake(host, f, Props(a).Concat(Props(b)).ToList());
            try
            {
                var origin = Local(f, 0, 0, 30);
                var dir = Unit(Sub(Local(f, 0, 1, 30), origin));
                var end = KeyWalk(nav, Local(f, 0, -1.5, 30), dir, 120, null);
                double reached = Dot(Sub(end, origin), dir);
                Expect("F3 keys walk through the gap (local z ≥ 1.0)", reached >= 1.0, $"local z {reached:0.###}");
                parts.Add($"F3 gap z={reached:0.###}");
            }
            finally { nav.Free(); }
        }

        // ---- F4 the door funnel ----
        {
            ScenePayload scene;
            using (var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "nav", "scene_loc-nav.json"))))
                scene = ScenePayload.Parse(doc.RootElement);
            var frame = new TileFrame(new Vec3(100, 0, 0), 0);
            var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), Array.Empty<NavProp>(), true, p);
            var nav = await BakeSrc(host, src);
            try
            {
                var walls = Collide.WallSegments(scene, 0, new P2(100, 0));
                int ok = 0;
                var fails = new List<string>();
                for (int i = -9; i <= 9; i++)
                {
                    double o = i * 0.05;
                    var end = KeyWalk(nav, new P2(99.0, 2 + o), new P2(1, 0), 300, walls);
                    if (end.X > 100.6) ok++;
                    else fails.Add(o.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture));
                }
                Expect("F4 ≥ 17 of 19 key walks through the door, every |offset| ≤ 0.40", ok >= 17 && fails.All(s => Math.Abs(double.Parse(s, System.Globalization.CultureInfo.InvariantCulture)) > 0.40 + 1e-9),
                       $"{ok}/19, stuck at [{string.Join(" ", fails)}]");
                parts.Add($"F4 door {ok}/19");
            }
            finally { nav.Free(); }
        }

        // ---- F5 rug and lamp ----
        {
            var f = new TileFrame(new Vec3(0, 0, 0), 0);
            Expect("F5 a rug (top 0.02) has no footprint", Footprint(f, Prism(f, Rect(0, 0, 2, 1.5), 0, 0.02, 0), 0, low, high) is null, "");
            Expect("F5 a lamp (1.9…2.2) has no footprint", Footprint(f, Prism(f, Rect(0, 0, 0.5, 0.5), 1.9, 2.2, 0), 0, low, high) is null, "");
        }

        await PhysicsFrames(host, 2);
        var line = "footprint " + string.Join("; ", parts);
        GD.Print("[check-nav] " + line);
        return line;
    }

    private static PropFootprint.Result? Footprint(TileFrame f, List<Vec3> tris, double yawDeg, double low, double high)
        => PropFootprint.Of(tris, Sub(Local(f, 1, 0, yawDeg), Local(f, 0, 0, yawDeg)), low, high);

    private static List<NavProp> Props(PropFootprint.Result fp)
        => fp.Outlines.Select(o => new NavProp(0, fp.BottomY, fp.TopY, o)).ToList();

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"nav {what}: {detail}");
    }

    private static P2[] Rect(double cx, double cz, double w, double d)
        => new[] { new P2(cx - w / 2, cz - d / 2), new P2(cx + w / 2, cz - d / 2), new P2(cx + w / 2, cz + d / 2), new P2(cx - w / 2, cz + d / 2) };

    private static P2 Local(TileFrame f, double x, double z, double yawDeg)
    {
        double a = yawDeg * Math.PI / 180, c = Math.Cos(a), s = Math.Sin(a);
        var w = SceneView.TileToWorld(f, c * x + s * z, -s * x + c * z);
        return new P2(w.X, w.Z);
    }

    private static List<Vec3> Prism(TileFrame f, P2[] ring, double y0, double y1, double yawDeg)
    {
        var w = ring.Select(q => Local(f, q.X, q.Z, yawDeg)).ToArray();
        var tris = new List<Vec3>();
        for (int i = 0; i < w.Length; i++)
        {
            var a = w[i]; var b = w[(i + 1) % w.Length];
            tris.AddRange(new[] { new Vec3(a.X, y0, a.Z), new Vec3(b.X, y0, b.Z), new Vec3(b.X, y1, b.Z) });
            tris.AddRange(new[] { new Vec3(a.X, y0, a.Z), new Vec3(b.X, y1, b.Z), new Vec3(a.X, y1, a.Z) });
        }
        for (int i = 1; i + 1 < w.Length; i++)
            foreach (var y in new[] { y0, y1 })
                tris.AddRange(new[] { new Vec3(w[0].X, y, w[0].Z), new Vec3(w[i].X, y, w[i].Z), new Vec3(w[i + 1].X, y, w[i + 1].Z) });
        return tris;
    }

    private static async Task<LocationNav> Bake(Node host, TileFrame frame, IReadOnlyList<NavProp> props)
    {
        ScenePayload scene;
        using (var doc = JsonDocument.Parse(OpenScene)) scene = ScenePayload.Parse(doc.RootElement);
        var src = NavSource.Build(scene, frame, PlaceInventory.Compose(scene, frame, null, null), props, true, NavBakeParams.Current);
        return await BakeSrc(host, src);
    }

    private static async Task<LocationNav> BakeSrc(Node host, NavSourceData src)
    {
        var p = NavBakeParams.Current;
        var meshes = await NavBake.BakeStoreysAsync(src, p, (_, _) => 0);
        var nav = LocationNav.Create(src, meshes, p);
        for (int i = 0; i < 120 && !nav.Ready; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
        return nav;
    }

    /// <summary>Per edge of the ring (tile frame, turned by yaw), 7 samples: the distance along the outward normal to the first mesh point.</summary>
    private static List<double> EdgeDistances(LocationNav nav, TileFrame f, P2[] ring, double yawDeg)
    {
        var w = ring.Select(q => Local(f, q.X, q.Z, yawDeg)).ToArray();
        var cx = w.Average(q => q.X); var cz = w.Average(q => q.Z);
        var res = new List<double>();
        for (int i = 0; i < w.Length; i++)
        {
            var a = w[i]; var b = w[(i + 1) % w.Length];
            var u = Unit(Sub(b, a));
            var n = new P2(u.Z, -u.X);
            var mid = new P2((a.X + b.X) / 2, (a.Z + b.Z) / 2);
            if (Dot(Sub(mid, new P2(cx, cz)), n) < 0) n = new P2(-n.X, -n.Z);
            for (int k = 1; k <= 7; k++)
            {
                var s = new P2(a.X + (b.X - a.X) * k / 8, a.Z + (b.Z - a.Z) * k / 8);
                res.Add(AlongNormal(nav, s, n));
            }
        }
        return res;
    }

    /// <summary>
    /// The first point on the mesh along <paramref name="n"/> from <paramref name="s"/>, in 2.5 mm steps; "on the mesh" =
    /// its closest mesh point is within 1 mm (not <see cref="NavClamp.OnMeshTolM"/>, which would read every edge 2 cm early).
    /// </summary>
    private static double AlongNormal(LocationNav nav, P2 s, P2 n)
    {
        for (double t = 0; t <= 2.0; t += 0.0025)
        {
            var q = new Vec3(s.X + n.X * t, 0, s.Z + n.Z * t);
            var c = nav.ClosestOnVertical(q, 1.5);
            if (Math.Abs(c.Y) < 1.5 && Math.Sqrt((c.X - q.X) * (c.X - q.X) + (c.Z - q.Z) * (c.Z - q.Z)) <= 1e-3) return t;
        }
        return double.PositiveInfinity;
    }

    /// <summary>Keys held at 60 Hz: the lead max(3.4/60, 0.15) ahead, wall clamp, nav clamp, then 3.4/60 towards the target.</summary>
    private static P2 KeyWalk(LocationNav nav, P2 start, P2 dir, int frames, IReadOnlyList<WallSegment>? walls)
    {
        var u = Unit(dir);
        var pos = start;
        double lead = Math.Max(NpcWalk.WalkSpeed / 60, PlayerSteering.MinLead), step = NpcWalk.WalkSpeed / 60;
        for (int i = 0; i < frames; i++)
        {
            var target = new P2(pos.X + u.X * lead, pos.Z + u.Z * lead);
            if (walls is not null) target = Collide.ClampAgainstWalls(pos, target, walls, Collide.BodyRadiusM);
            target = PlayerSteering.ClampToNav(pos, target, 0, 3, nav);
            var d = Sub(target, pos);
            double len = Math.Sqrt(d.X * d.X + d.Z * d.Z);
            if (len < 1e-9) break;
            double k = Math.Min(1, step / len);
            pos = new P2(pos.X + d.X * k, pos.Z + d.Z * k);
        }
        return pos;
    }

    private static P2 Sub(P2 a, P2 b) => new(a.X - b.X, a.Z - b.Z);
    private static double Dot(P2 a, P2 b) => a.X * b.X + a.Z * b.Z;
    private static P2 Unit(P2 a) { double l = Math.Sqrt(Dot(a, a)); return new P2(a.X / l, a.Z / l); }

    private static async Task PhysicsFrames(Node host, int n)
    {
        for (int i = 0; i < n; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame);
    }
}
