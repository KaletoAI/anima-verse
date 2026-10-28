using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Scatter;

/// <summary>Task 39 (E4-T4): scatterAxis.ts, in double precision with the browser's strict tie rules,
/// inward axis convention, candidate ordinals and independent jitter stream. Covered by scatter_rows.json.</summary>
public static class ScatterRows
{
    private const double Eps = 1e-9, InsideEps = 1e-4;
    public static double Norm(double a) => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    public static double Distance(double x, double z, P2 a, P2 b)
    {
        double dx = b.X - a.X, dz = b.Z - a.Z, len2 = dx * dx + dz * dz;
        double t = len2 < 1e-18 ? 0 : Math.Clamp(((x - a.X) * dx + (z - a.Z) * dz) / len2, 0, 1);
        return Math.Sqrt(Math.Pow(x - (a.X + t * dx), 2) + Math.Pow(z - (a.Z + t * dz), 2));
    }
    private static double Length(P2 a, P2 b) => Math.Sqrt(Math.Pow(b.X - a.X, 2) + Math.Pow(b.Z - a.Z, 2));
    private static double EdgeAxis(IReadOnlyList<P2> ring, P2 a, P2 b)
    {
        double dx = b.X - a.X, dz = b.Z - a.Z, len = Length(a, b);
        if (!(len > 0)) return 0;
        double heading = Math.Atan2(dx, dz);
        return Norm(ScatterMath.PointInRing((a.X + b.X) / 2 + dz / len * InsideEps,
            (a.Z + b.Z) / 2 - dx / len * InsideEps, ring) ? heading : heading + Math.PI);
    }
    public static List<int> RingSelectedEdges(IReadOnlyList<P2> ring, string? sides = null)
    {
        int n = ring.Count;
        if (n < 3) return new();
        var all = Enumerable.Range(0, n).ToList();
        if (sides is not ("longest" or "opposite")) return all;
        var sorted = all.OrderByDescending(i => { double l = Length(ring[i], ring[(i + 1) % n]); return double.IsFinite(l) ? l : 0; }).ToList();
        return sorted.Take(sides == "longest" ? 1 : 2).OrderBy(i => i).ToList();
    }
    public static List<int> RibbonSelectedEdges(IReadOnlyList<P2> ring, string? sides = null)
    {
        int len = ring.Count;
        if (len < 3) return new();
        if (sides is not ("longest" or "opposite") || len % 2 != 0) return Enumerable.Range(0, len).ToList();
        int n = len / 2;
        var a = Enumerable.Range(0, n - 1).ToList();
        var b = Enumerable.Range(n, n - 1).ToList();
        double Sum(List<int> indices) => indices.Sum(i => { double l = Length(ring[i], ring[(i + 1) % len]); return double.IsFinite(l) ? l : 0; });
        return sides == "opposite" ? a.Concat(b).ToList() : Sum(b) > Sum(a) ? b : a;
    }
    public static double RingEdgeAxis(IReadOnlyList<P2> ring, double x, double z, IReadOnlyList<int>? edges = null)
    {
        if (ring.Count < 3) return 0;
        double best = double.PositiveInfinity, axis = 0;
        for (int i = 0, j = ring.Count - 1; i < ring.Count; j = i++)
        {
            if (edges is not null && !edges.Contains(j)) continue;
            double d = Distance(x, z, ring[j], ring[i]);
            if (d < best) { best = d; axis = EdgeAxis(ring, ring[j], ring[i]); }
        }
        return axis;
    }
    public static double LineAxis(IReadOnlyList<P2> line, double x, double z)
    {
        double best = double.PositiveInfinity, axis = 0;
        for (int i = 1; i < line.Count; i++)
        {
            var a = line[i - 1]; var b = line[i];
            if (Math.Pow(b.X - a.X, 2) + Math.Pow(b.Z - a.Z, 2) < 1e-18) continue;
            double d = Distance(x, z, a, b);
            if (d < best) { best = d; axis = Norm(Math.Atan2(b.X - a.X, b.Z - a.Z)); }
        }
        return axis;
    }
    public static Func<double, double, double> AreaAxis(IReadOnlyList<P2>? line, IReadOnlyList<P2> ring, string? sides = null)
    {
        if (line is not null) return (x, z) => LineAxis(line, x, z);
        var edges = sides is "longest" or "opposite" ? RingSelectedEdges(ring, sides) : null;
        return (x, z) => RingEdgeAxis(ring, x, z, edges);
    }
    public readonly record struct Pole(double X, double Z, double D);
    private readonly record struct PoleCell(double X, double Z, double H, double D, double Max);
    public static Pole Polylabel(IReadOnlyList<P2> ring, double precision = 0.5)
    {
        if (ring.Count < 3 || ring.Any(p => !double.IsFinite(p.X) || !double.IsFinite(p.Z))) return new(0, 0, 0);
        double minX = ring.Min(p => p.X), maxX = ring.Max(p => p.X), minZ = ring.Min(p => p.Z), maxZ = ring.Max(p => p.Z);
        double width = maxX - minX, height = maxZ - minZ, size = Math.Min(width, height);
        if (!(size > 0)) return new(minX + width / 2, minZ + height / 2, 0);
        double tolerance = double.IsFinite(precision) && precision > 0 ? precision : 0.5;
        PoleCell Cell(double x, double z, double h)
        {
            double d = double.PositiveInfinity;
            for (int i = 0, j = ring.Count - 1; i < ring.Count; j = i++) d = Math.Min(d, Distance(x, z, ring[j], ring[i]));
            if (!ScatterMath.PointInRing(x, z, ring)) d = -d;
            return new(x, z, h, d, d + h * Math.Sqrt(2));
        }
        double area = 0, cx = 0, cz = 0;
        for (int i = 0, j = ring.Count - 1; i < ring.Count; j = i++)
        {
            double f = ring[i].X * ring[j].Z - ring[j].X * ring[i].Z;
            area += f; cx += (ring[i].X + ring[j].X) * f; cz += (ring[i].Z + ring[j].Z) * f;
        }
        var box = Cell(minX + width / 2, minZ + height / 2, 0);
        var best = Math.Abs(area) > 1e-12 ? Cell(cx / (3 * area), cz / (3 * area), 0) : box;
        if (box.D > best.D) best = box;
        // Match the TS binary max heap, including equal-priority ordering.
        var heap = new List<PoleCell>();
        void Push(PoleCell c)
        {
            heap.Add(c); int i = heap.Count - 1;
            while (i > 0) { int p = (i - 1) >> 1; if (heap[p].Max >= heap[i].Max) break; (heap[p], heap[i]) = (heap[i], heap[p]); i = p; }
        }
        PoleCell Pop()
        {
            var top = heap[0]; var last = heap[^1]; heap.RemoveAt(heap.Count - 1);
            if (heap.Count == 0) return top;
            heap[0] = last; int i = 0;
            while (true)
            {
                int l = i * 2 + 1, r = l + 1, m = i;
                if (l < heap.Count && heap[l].Max > heap[m].Max) m = l;
                if (r < heap.Count && heap[r].Max > heap[m].Max) m = r;
                if (m == i) break; (heap[m], heap[i]) = (heap[i], heap[m]); i = m;
            }
            return top;
        }
        for (double x = minX; x < maxX; x += size)
            for (double z = minZ; z < maxZ; z += size) Push(Cell(x + size / 2, z + size / 2, size / 2));
        int opened = heap.Count;
        while (heap.Count > 0 && opened < 100000)
        {
            var c = Pop(); if (c.D > best.D) best = c;
            if (c.Max - best.D <= tolerance) continue;
            double h = c.H / 2;
            Push(Cell(c.X - h, c.Z - h, h)); Push(Cell(c.X + h, c.Z - h, h));
            Push(Cell(c.X - h, c.Z + h, h)); Push(Cell(c.X + h, c.Z + h, h)); opened += 4;
        }
        return new(best.X, best.Z, best.D);
    }
    /// <summary>Task 39: the TS outline/stroke options; absent numeric options retain undefined semantics.</summary>
    public sealed class Options
    {
        public double SpacingM = double.NaN;
        public double? OffsetM, StartM, JitterM, VariantCount, Variant, ClearM, OccupyR, YawDeg;
        public int? MaxPoints;
        public string Seed = "";
        public string? Sides, Side, YawMode, OccupyTag;
        public IReadOnlyList<int>? Edges;
        public IReadOnlyList<P2> Line = Array.Empty<P2>();
        public IReadOnlyList<IReadOnlyList<P2>>? Footprints, Occluders;
        public IScatterOccupancy? Occupied;
        public Func<double>? Rng, JitterRng;
        public Func<double, double, double>? AxisAt;
    }
    public readonly record struct Station(double X, double Z, double Axis, int Ordinal);
    private sealed record Edge(P2 A, P2 B, double Len, double Start, double End, int Index);
    public static List<Station> RingStations(IReadOnlyList<P2> ring, Options o)
    {
        var output = new List<Station>(); double spacing = o.SpacingM, offset = o.OffsetM ?? 0;
        if (!double.IsFinite(spacing) || spacing <= 0 || !double.IsFinite(offset) || offset < 0) return output;
        var pts = new List<(P2 P, int I)>();
        for (int i = 0; i < ring.Count; i++)
        {
            var p = ring[i]; if (!double.IsFinite(p.X) || !double.IsFinite(p.Z)) return output;
            if (pts.Count > 0 && Near(pts[^1].P, p)) pts[^1] = (pts[^1].P, i); else pts.Add((p, i));
        }
        if (pts.Count > 1 && Near(pts[0].P, pts[^1].P)) pts.RemoveAt(pts.Count - 1);
        if (pts.Count < 3) return output;
        var edges = new List<Edge>(); double cum = 0;
        for (int i = 0; i < pts.Count; i++)
        {
            var a = pts[i]; var b = pts[(i + 1) % pts.Count]; double len = Length(a.P, b.P);
            if (!(len > Eps)) continue; edges.Add(new(a.P, b.P, len, cum, cum + len, a.I)); cum += len;
        }
        if (edges.Count < 3) return output;
        double start = Start(o), jitter = o.JitterM ?? double.NaN;
        var rnd = jitter > 0 ? o.JitterRng ?? ScatterMath.SeededRandom(o.Seed + ":jitter") : null;
        var axes = new Dictionary<int, double>();
        void Walk(List<Edge> run)
        {
            int e = 0; double s = 0, total = run[^1].End;
            for (int k = 0; ; k++)
            {
                s = rnd is null ? start + k * spacing : Math.Max(0, (k == 0 ? start : s + spacing) + (2 * rnd() - 1) * jitter);
                if (!(s < total - Eps) || output.Count >= (o.MaxPoints ?? ScatterMath.MaxPerEntry)) break;
                while (e < run.Count - 1 && s >= run[e].End) e++;
                var edge = run[e]; double t = Math.Clamp((s - edge.Start) / edge.Len, 0, 1);
                if (!axes.TryGetValue(edge.Index, out double axis)) axes[edge.Index] = axis = EdgeAxis(ring, edge.A, edge.B);
                output.Add(new(edge.A.X + t * (edge.B.X - edge.A.X) + Math.Sin(axis + Math.PI / 2) * offset,
                    edge.A.Z + t * (edge.B.Z - edge.A.Z) + Math.Cos(axis + Math.PI / 2) * offset, axis, output.Count));
            }
        }
        void Chains(IEnumerable<List<Edge>> chains)
        {
            foreach (var chain in chains)
            {
                double c = 0; var run = new List<Edge>();
                foreach (var e in chain) { run.Add(e with { Start = c, End = c + e.Len }); c += e.Len; }
                if (c > Eps) Walk(run);
                if (output.Count >= (o.MaxPoints ?? ScatterMath.MaxPerEntry)) break;
            }
        }
        if (o.Edges is not null)
        {
            var chains = new List<List<Edge>>(); List<Edge>? open = null;
            foreach (var e in edges)
            {
                if (!o.Edges.Contains(e.Index)) { open = null; continue; }
                if (open is null) { open = new(); chains.Add(open); } open.Add(e);
            }
            Chains(chains);
        }
        else if (o.Sides is "longest" or "opposite") Chains(RingSelectedEdges(ring, o.Sides).Select(i => edges.Where(e => e.Index == i).ToList()));
        else Walk(edges);
        return output;
    }
    internal static bool Near(P2 a, P2 b) => Math.Abs(a.X - b.X) < Eps && Math.Abs(a.Z - b.Z) < Eps;
    internal static double Start(Options o) => o.StartM is double s && double.IsFinite(s) && s >= 0 ? Math.Min(s, o.SpacingM) : o.SpacingM / 2;
    internal static bool Rejected(Options o, double x, double z)
        => (o.Occluders?.Any(r => r.Count >= 3 && ScatterMath.PointInRing(x, z, r)) ?? false)
        || (o.Footprints?.Any(r => ScatterMath.FootprintBlocks(r, x, z, o.ClearM)) ?? false)
        || (o.Occupied?.Blocks(x, z, ScatterMath.OccupyR(o.OccupyR, o.ClearM), o.OccupyTag ?? o.Seed) ?? false);
    internal static ScatterInstance Accepted(Options o, double x, double z, double yaw, int ordinal, bool along = false)
    {
        o.Occupied?.Add(x, z, ScatterMath.OccupyR(o.OccupyR, o.ClearM), o.OccupyTag ?? o.Seed);
        double n = Math.Floor(o.VariantCount ?? double.NaN); int? variant = null;
        if (double.IsFinite(n) && n > 1)
        {
            int pin = along && o.Variant is < 0 ? -1 : ScatterMath.PinnedVariant(o.Variant, n);
            variant = pin >= 0 ? pin : ScatterMath.VariantIndex(o.Seed, ordinal, n);
        }
        return new(x, z, yaw, variant);
    }
    public static List<ScatterInstance> EdgeInstances(IReadOnlyList<P2> ring, Options o)
    {
        var output = new List<ScatterInstance>(); var rnd = o.Rng ?? ScatterMath.SeededRandom(o.Seed);
        foreach (var s in RingStations(ring, o))
        {
            double turn = rnd(), inward = s.Axis + Math.PI / 2;
            if (!ScatterMath.PointInRing(s.X + Math.Sin(inward) * InsideEps, s.Z + Math.Cos(inward) * InsideEps, ring) || Rejected(o, s.X, s.Z)) continue;
            output.Add(Accepted(o, s.X, s.Z, ScatterMath.Yaw(turn, o.YawMode, o.YawDeg, s.Axis), s.Ordinal));
        }
        return output;
    }
    public static List<ScatterInstance> CenterInstance(IReadOnlyList<P2> ring, Options o)
    {
        var p = Polylabel(ring); if (!(p.D > 0)) return new();
        double turn = (o.Rng ?? ScatterMath.SeededRandom(o.Seed))();
        if (Rejected(o, p.X, p.Z)) return new();
        double axis = o.YawMode == "aligned" ? o.AxisAt?.Invoke(p.X, p.Z) ?? RingEdgeAxis(ring, p.X, p.Z) : 0;
        return new() { Accepted(o, p.X, p.Z, ScatterMath.Yaw(turn, o.YawMode, o.YawDeg, axis), 0) };
    }
}
