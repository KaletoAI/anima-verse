using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using AnimaNative.Embody;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;

namespace AnimaNative.Nav;

/// <summary>
/// Builds the navigation source of one mounted location (plan 2026-11-25-client-ausfuehrung-e2, decisions 2, 7, 8, 13)
/// from its scene recipe, its tile frame, its places and the measured furniture boxes — everything in WORLD metres.
/// Hand derivations: native/fixtures/README.md, section "Nav world"; tests: tests/NavSourceTests.cs.
/// </summary>
public static class NavSource
{
    /// <summary>Storey 0's boundary is pushed out by agent radius + this (decision 7).</summary>
    public const double BoundaryMarginM = 0.05;
    /// <summary>A wall borders a doorway when its centre line is at most this far from <c>at_world</c> …</summary>
    public const double DoorWallLineM = 0.05;
    /// <summary>… and one of its ends at most <c>width/2</c> + this from <c>at_world</c> (decision 2).</summary>
    public const double DoorWallEndM = 0.05;
    /// <summary>The thinnest wall rectangle (decision 8: half depth <c>max(t, 0.02)/2</c>).</summary>
    public const double MinWallThicknessM = 0.02;
    /// <summary>Two unit directions are parallel when their cross product is below this.</summary>
    private const double ParallelTol = 1e-3;
    /// <summary>Neighbouring offset edges this close to parallel drop their shared corner.</summary>
    private const double CornerTol = 1e-9;
    private const double Eps = 1e-12;

    private sealed record WallPiece(P2 From, P2 To, double Thickness, double BottomY, double TopY);

    /// <summary>
    /// The source. Storey 0 = the boundary pushed out (<see cref="OffsetRing"/>), the <c>floor_plan</c> rooms, the
    /// storey-0 plates and corridors; every other storey = each plate as its own floor plus its corridors, a plate hole
    /// kept only where no other plate of the storey covers it. Obstacles = walls (the <see cref="Collide.WallSegments"/>
    /// filter: no lintel, no leaf, glass blocks), door seals and furniture boxes, minus everything whose top is within the
    /// climb of the floor or whose bottom is at or above the agent height. <paramref name="building"/> changes nothing
    /// yet: decision 7 gives buildings and open locations the same storey 0.
    /// </summary>
    public static NavSourceData Build(ScenePayload scene, TileFrame frame, PlaceInventory places,
                                      IReadOnlyList<NavPropBox> props, bool building, NavBakeParams p)
    {
        double datum = frame.Center.Y;
        var problems = new List<NavProblem>();
        P2 ToWorld(P2 local)
        {
            var v = SceneView.TileToWorld(frame, local.X, local.Z);
            return new P2(v.X, v.Z);
        }
        P2[] WorldRing(IEnumerable<P2> ring) => Ccw(ring.Select(ToWorld).ToArray());

        // ---- floors -------------------------------------------------------------------------------------------
        var floors = new SortedDictionary<int, List<NavFloor>>();
        List<NavFloor> FloorsOf(int level)
        {
            if (!floors.TryGetValue(level, out var list)) floors[level] = list = new List<NavFloor>();
            return list;
        }
        var hulls0 = new List<P2[]>();
        if (SceneView.SanitizePolygon(scene.Boundary) is { } boundary)
        {
            var (ring, ok) = OffsetRing(WorldRing(boundary), p.AgentRadius + BoundaryMarginM);
            if (!ok) problems.Add(new NavProblem("boundary_offset", -1));
            FloorsOf(0).Add(new NavFloor(ring, Array.Empty<P2[]>()));
        }
        foreach (var room in scene.FloorPlan)
        {
            if (SceneView.SanitizePolygon(room.PolygonWorld) is not { } poly) continue;
            var hull = WorldRing(poly);
            hulls0.Add(hull);
            FloorsOf(0).Add(new NavFloor(hull, Array.Empty<P2[]>()));
        }
        var plates = scene.Plates
            .Select(pl => (Plate: pl, Outline: SceneView.SanitizePolygon(pl.Outline.Select(q => new P2(q.X, q.Z)).ToArray())))
            .Where(x => x.Outline is not null)
            .Select(x => (x.Plate, Outline: WorldRing(x.Outline!),
                          Holes: x.Plate.Holes.Select(h => SceneView.SanitizePolygon(h.Select(q => new P2(q.X, q.Z)).ToArray()))
                                              .Where(h => h is not null).Select(h => WorldRing(h!)).ToArray()))
            .ToList();
        for (int i = 0; i < plates.Count; i++)
        {
            var (plate, outline, holes) = plates[i];
            var open = holes.Where(h =>
            {
                var c = Centre(h);
                for (int j = 0; j < plates.Count; j++)
                {
                    if (j == i || plates[j].Plate.Level != plate.Level) continue;
                    if (SceneView.PointInPolygon(c.X, c.Z, plates[j].Outline)
                        && !plates[j].Holes.Any(o => SceneView.PointInPolygon(c.X, c.Z, o))) return false;
                }
                return true;
            }).ToArray();
            FloorsOf(plate.Level).Add(new NavFloor(outline, open));
        }
        foreach (var corridor in scene.Corridors)
            if (SceneView.SanitizePolygon(corridor.Outline) is { } poly)
                FloorsOf(corridor.Level).Add(new NavFloor(WorldRing(poly), Array.Empty<P2[]>()));

        var floorY = new Dictionary<int, double>();
        foreach (var level in floors.Keys)
        {
            var tops = scene.Plates.Where(pl => pl.Level == level).Select(pl => pl.TopY).ToList();
            floorY[level] = datum + (level == 0 || tops.Count == 0 ? scene.FloorY(level) : tops.Max());
        }
        double StoreyY(int level) => floorY.TryGetValue(level, out var y) ? y : datum + scene.FloorY(level);
        bool Blocks(int level, double bottom, double top)
            => !(top <= StoreyY(level) + p.AgentMaxClimb) && !(bottom >= StoreyY(level) + p.AgentHeight);

        // ---- obstacles ----------------------------------------------------------------------------------------
        var obstacles = floors.Keys.ToDictionary(l => l, _ => new List<NavObstacle>());
        var walls = floors.Keys.ToDictionary(l => l, _ => new List<WallPiece>());
        foreach (var w in scene.Walls)
        {
            if (!obstacles.ContainsKey(w.Level) || w.Lintel || w.Leaf) continue;
            var a = new P2(w.From.X, w.From.Z);
            var b = new P2(w.To.X, w.To.Z);
            if (!Finite(a) || !Finite(b) || Length(Sub(b, a)) < 1e-9) continue;
            double bottom = datum + w.BaseY, top = bottom + w.Height;
            if (!Blocks(w.Level, bottom, top)) continue;
            double t = Math.Max(w.Thickness, MinWallThicknessM);
            walls[w.Level].Add(new WallPiece(a, b, t, bottom, top));
            var u = Unit(Sub(b, a));
            var mid = Scale(Add(a, b), 0.5);
            obstacles[w.Level].Add(new NavObstacle(Rect(mid, u, Length(Sub(b, a)) / 2, t / 2, ToWorld), bottom, top, "wall"));
        }

        var thresholds = new List<NavThreshold>();
        for (int i = 0; i < scene.Doorways.Count; i++)
        {
            var d = scene.Doorways[i];
            if (!d.Usable || !obstacles.ContainsKey(d.Level) || Length(d.Along) < 1e-9) continue;
            var u = Unit(d.Along);
            double half = d.WidthM / 2;
            var adjacent = walls[d.Level].Where(w =>
            {
                var wu = Unit(Sub(w.To, w.From));
                if (Math.Abs(Cross(wu, u)) > ParallelTol) return false;
                if (Math.Abs(Cross(Sub(d.AtWorld, w.From), wu)) > DoorWallLineM) return false;
                return Math.Min(Length(Sub(w.From, d.AtWorld)), Length(Sub(w.To, d.AtWorld))) <= half + DoorWallEndM;
            }).ToList();
            if (adjacent.Count == 0) continue;   // no wall beside it: open floor, neither seal nor threshold
            double t = adjacent.Max(w => w.Thickness);
            obstacles[d.Level].Add(new NavObstacle(Rect(d.AtWorld, u, half, t / 2, ToWorld),
                                                   adjacent.Min(w => w.BottomY), adjacent.Max(w => w.TopY), "seal"));
            double along = half - p.AgentRadius;
            if (along <= 0)
            {
                problems.Add(new NavProblem("door_too_narrow", i));
                continue;
            }
            double depth = t / 2 + p.AgentRadius;
            P2? outer = null;
            if (d.Outside)
            {
                var n = d.OutwardNormal is { } on && Length(on) > 1e-9 ? Unit(on) : new P2(u.Z, -u.X);
                var nw = SceneView.TileDirToWorld(frame.Yaw, n.X, n.Z);
                var c = ToWorld(d.AtWorld);
                outer = new P2(c.X + nw.X * depth, c.Z + nw.Z * depth);
            }
            thresholds.Add(new NavThreshold(i, d.Level, Rect(d.AtWorld, u, along, depth, ToWorld), StoreyY(d.Level),
                                            d.Rooms.ToArray(), d.Outside, outer));
        }

        foreach (var box in props)
        {
            if (!obstacles.ContainsKey(box.Level) || !Blocks(box.Level, box.Min.Y, box.Max.Y)) continue;
            var outline = new[]
            {
                new P2(box.Min.X, box.Min.Z), new P2(box.Max.X, box.Min.Z), new P2(box.Max.X, box.Max.Z), new P2(box.Min.X, box.Max.Z),
            };
            obstacles[box.Level].Add(new NavObstacle(outline, box.Min.Y, box.Max.Y, "prop"));
        }

        // ---- links --------------------------------------------------------------------------------------------
        var links = new List<NavLinkSpec>();
        for (int i = 0; i < places.Stairs.Count; i++)
        {
            var s = places.Stairs[i];
            links.Add(new NavLinkSpec(NavLinkOwner.Stairs(i), "stairs", s.Foot.Pos, s.Head.Pos, s.Foot.Level, s.Head.Level, 0));
        }
        var stops = places.ElevatorStops.ToList();
        for (int i = 0; i + 1 < stops.Count; i++)
            links.Add(new NavLinkSpec(NavLinkOwner.Elevator(stops[i].Key), "elevator", stops[i].Value, stops[i + 1].Value,
                                      stops[i].Key, stops[i + 1].Key, NavBakeParams.ElevatorEnterCost));

        var storeys = floors.Keys.Select(level => new NavStoreySource(
            level, floorY[level], level == 0, level == 0 ? hulls0 : new List<P2[]>(), floors[level], obstacles[level])).ToList();
        return new NavSourceData(storeys, thresholds, links, problems, Fingerprint(storeys, thresholds, links, problems, p));
    }

    /// <summary>
    /// Pushes a ring outwards by <paramref name="d"/> (decision 7): the winding is first made counter-clockwise in (x, z)
    /// (positive shoelace), every edge moves d along its outer normal, each new corner is where the two moved neighbours
    /// meet (a mitre, at concave corners too); nearly parallel neighbours drop their corner; a sharp convex corner whose
    /// mitre would reach farther than 4·d is bevelled (two points, each d off the corner along one normal). A result that
    /// crosses itself (a notch narrower than 2·d) is refused: the input comes back unchanged with <c>Ok = false</c>.
    /// </summary>
    public static (P2[] Ring, bool Ok) OffsetRing(IReadOnlyList<P2> ring, double d)
    {
        var input = ring.ToArray();
        var clean = SceneView.SanitizePolygon(ring);
        if (clean is null) return (input, false);
        var pts = new List<P2>();
        foreach (var q in clean)
            if (pts.Count == 0 || Length(Sub(q, pts[^1])) > Eps) pts.Add(q);
        if (pts.Count > 1 && Length(Sub(pts[0], pts[^1])) <= Eps) pts.RemoveAt(pts.Count - 1);
        if (pts.Count < 3) return (input, false);
        var ccw = Ccw(pts.ToArray());
        int n = ccw.Length;
        var result = new List<P2>();
        for (int i = 0; i < n; i++)
        {
            var prev = ccw[(i - 1 + n) % n];
            var cur = ccw[i];
            var next = ccw[(i + 1) % n];
            var e1 = Unit(Sub(cur, prev));
            var e2 = Unit(Sub(next, cur));
            var n1 = new P2(e1.Z, -e1.X);
            var n2 = new P2(e2.Z, -e2.X);
            double cr = Cross(e1, e2);
            if (Math.Abs(cr) < CornerTol) continue;
            var p1 = Add(cur, Scale(n1, d));
            var p2 = Add(cur, Scale(n2, d));
            var mitre = Add(p1, Scale(e1, Cross(Sub(p2, p1), e2) / cr));
            if (cr > 0 && Length(Sub(mitre, cur)) > 4 * d)
            {
                result.Add(p1);
                result.Add(p2);
            }
            else result.Add(mitre);
        }
        if (result.Count < 3 || SelfIntersects(result)) return (input, false);
        return (result.ToArray(), true);
    }

    // ---- geometry helpers ---------------------------------------------------------------------------------------

    /// <summary>
    /// A rectangle in the tile frame (centre, unit direction, half length along it, half depth across it) turned into
    /// world xz and put into the canonical order (<see cref="Canonical"/>).
    /// </summary>
    private static P2[] Rect(P2 centre, P2 u, double halfLength, double halfDepth, Func<P2, P2> toWorld)
    {
        var n = new P2(u.Z, -u.X);
        var a = Scale(u, halfLength);
        var b = Scale(n, halfDepth);
        return Canonical(new[]
        {
            toWorld(Sub(Sub(centre, a), b)), toWorld(Sub(Add(centre, a), b)),
            toWorld(Add(Add(centre, a), b)), toWorld(Add(Sub(centre, a), b)),
        });
    }

    /// <summary>
    /// Counter-clockwise in (x, z), starting at the corner with the smallest x + z (then x): for an axis-aligned rectangle
    /// exactly (x0, z0) → (x1, z0) → (x1, z1) → (x0, z1).
    /// </summary>
    private static P2[] Canonical(P2[] quad)
    {
        var ring = Ccw(quad);
        int start = 0;
        for (int i = 1; i < ring.Length; i++)
        {
            double si = ring[i].X + ring[i].Z, ss = ring[start].X + ring[start].Z;
            if (si < ss - 1e-9 || (Math.Abs(si - ss) <= 1e-9 && ring[i].X < ring[start].X)) start = i;
        }
        return ring.Skip(start).Concat(ring.Take(start)).ToArray();
    }

    /// <summary>The ring with a positive shoelace area in (x, z) (reversed when it had a negative one).</summary>
    private static P2[] Ccw(P2[] ring)
    {
        var copy = ring.ToArray();
        if (Shoelace(copy) < 0) Array.Reverse(copy);
        return copy;
    }

    private static double Shoelace(IReadOnlyList<P2> ring)
    {
        double a = 0;
        for (int i = 0; i < ring.Count; i++)
        {
            var p = ring[i];
            var q = ring[(i + 1) % ring.Count];
            a += p.X * q.Z - q.X * p.Z;
        }
        return a / 2;
    }

    /// <summary>The O(n²) test of every pair of non-neighbouring edges; touching and collinear overlap count.</summary>
    private static bool SelfIntersects(IReadOnlyList<P2> ring)
    {
        int n = ring.Count;
        for (int i = 0; i < n; i++)
            for (int j = i + 1; j < n; j++)
            {
                if (j == i + 1 || (i == 0 && j == n - 1)) continue;
                if (SegmentsTouch(ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n])) return true;
            }
        return false;
    }

    private static bool SegmentsTouch(P2 a, P2 b, P2 c, P2 d)
    {
        double d1 = Orient(c, d, a), d2 = Orient(c, d, b), d3 = Orient(a, b, c), d4 = Orient(a, b, d);
        if (((d1 > Eps && d2 < -Eps) || (d1 < -Eps && d2 > Eps)) && ((d3 > Eps && d4 < -Eps) || (d3 < -Eps && d4 > Eps)))
            return true;
        return (Math.Abs(d1) <= Eps && OnSegment(c, d, a)) || (Math.Abs(d2) <= Eps && OnSegment(c, d, b))
            || (Math.Abs(d3) <= Eps && OnSegment(a, b, c)) || (Math.Abs(d4) <= Eps && OnSegment(a, b, d));
    }

    private static double Orient(P2 a, P2 b, P2 c) => Cross(Sub(b, a), Sub(c, a));

    private static bool OnSegment(P2 a, P2 b, P2 p)
        => p.X >= Math.Min(a.X, b.X) - Eps && p.X <= Math.Max(a.X, b.X) + Eps
        && p.Z >= Math.Min(a.Z, b.Z) - Eps && p.Z <= Math.Max(a.Z, b.Z) + Eps;

    private static P2 Centre(IReadOnlyList<P2> ring) => new(ring.Average(q => q.X), ring.Average(q => q.Z));
    private static bool Finite(P2 a) => double.IsFinite(a.X) && double.IsFinite(a.Z);
    private static P2 Add(P2 a, P2 b) => new(a.X + b.X, a.Z + b.Z);
    private static P2 Sub(P2 a, P2 b) => new(a.X - b.X, a.Z - b.Z);
    private static P2 Scale(P2 a, double k) => new(a.X * k, a.Z * k);
    private static double Cross(P2 a, P2 b) => a.X * b.Z - a.Z * b.X;
    private static double Length(P2 a) => Math.Sqrt(a.X * a.X + a.Z * a.Z);
    private static P2 Unit(P2 a)
    {
        double l = Length(a);
        return l > 0 ? new P2(a.X / l, a.Z / l) : a;
    }

    // ---- fingerprint --------------------------------------------------------------------------------------------

    /// <summary>
    /// SHA-256 (lowercase hex) over the canonical text of the whole source: every number written with
    /// <c>ToString("R", InvariantCulture)</c> in a fixed order, plus the bake mode, its parameters and
    /// <see cref="NavBakeParams.Version"/> — the cache key of a bake (decision 6).
    /// </summary>
    private static string Fingerprint(IReadOnlyList<NavStoreySource> storeys, IReadOnlyList<NavThreshold> thresholds,
                                      IReadOnlyList<NavLinkSpec> links, IReadOnlyList<NavProblem> problems, NavBakeParams p)
    {
        var sb = new StringBuilder();
        void N(double v) => sb.Append(v.ToString("R", CultureInfo.InvariantCulture)).Append(',');
        void S(string s) => sb.Append(s.Length).Append(':').Append(s).Append(',');
        void Ring(IReadOnlyList<P2> ring)
        {
            sb.Append('[');
            foreach (var q in ring) { N(q.X); N(q.Z); }
            sb.Append(']');
        }
        void V(Vec3 v) { N(v.X); N(v.Y); N(v.Z); }

        sb.Append("nav/v").Append(NavBakeParams.Version).Append('|').Append(p.Mode).Append('|');
        N(p.AgentRadius); N(p.AgentHeight); N(p.AgentMaxClimb); N(p.AgentMaxSlopeDeg); N(p.CellSize); N(p.CellHeight);
        N(p.EdgeConnectionMargin); N(p.LinkConnectionRadius); N(NavBakeParams.ElevatorTravelCost);
        foreach (var s in storeys)
        {
            sb.Append("|storey,");
            N(s.Level); N(s.FloorY); sb.Append(s.FollowGround ? "ground," : "flat,");
            sb.Append("hulls");
            foreach (var h in s.Hulls) Ring(h);
            foreach (var f in s.Floors)
            {
                sb.Append(";floor");
                Ring(f.Outline);
                foreach (var h in f.Holes) Ring(h);
            }
            foreach (var o in s.Obstacles)
            {
                sb.Append(";obstacle,");
                S(o.Kind); N(o.BottomY); N(o.TopY);
                Ring(o.Outline);
            }
        }
        foreach (var t in thresholds)
        {
            sb.Append("|threshold,");
            N(t.Doorway); N(t.Level); N(t.Y); sb.Append(t.Outside ? "out," : "in,");
            Ring(t.Quad);
            foreach (var r in t.Rooms) S(r);
            if (t.OuterPoint is { } op) { N(op.X); N(op.Z); }
        }
        foreach (var l in links)
        {
            sb.Append("|link,");
            sb.Append(l.Owner.ToString(CultureInfo.InvariantCulture)).Append(',');
            S(l.Kind); V(l.Start); V(l.End); N(l.FromLevel); N(l.ToLevel); N(l.EnterCost);
        }
        foreach (var pr in problems)
        {
            sb.Append("|problem,");
            S(pr.Kind); N(pr.Doorway);
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(sb.ToString()))).ToLowerInvariant();
    }
}
