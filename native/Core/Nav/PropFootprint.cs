using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

/// <summary>
/// The real floor outline of one piece of furniture for the navigation (fix plan "Kollision im nativen Client", step 1):
/// instead of the world AABB of the whole model — which grows with every yaw of the prop or the location and closes the
/// inner corner of an L sofa — the model's own triangles, cut to the walking band, rastered in the prop's OWN horizontal
/// frame. Hand derivations: native/fixtures/README.md, section "Nav world" ("Prop footprints"); tests:
/// tests/PropFootprintTests.cs, <c>--check nav</c> F1–F4.
/// <list type="number">
/// <item>Every triangle whose height range reaches into the band (top above <c>bandLow</c>, bottom below <c>bandHigh</c>)
/// is clipped to the band; the clipped polygon is projected onto the prop frame (a = along <c>axis</c>, b = across).</item>
/// <item>Grid of <see cref="CellM"/> cells starting at the band geometry's own minimum a / b (so a box edge is never moved);
/// a cell is MARKED when a point of a clipped edge (sampled at most half a cell apart) falls into it, or its centre lies
/// inside a clipped polygon's projection.</item>
/// <item>A cell is FILLED when it is marked, or lies between marked cells both in its row and in its column (a cabinet whose
/// band part is only its four sides gets its inside; the free inner corner of an L stays free).</item>
/// <item>Rows become runs of filled cells, equal runs of neighbouring rows merge into one rectangle; the last row and
/// column end at the geometry's own maximum, not at the cell border.</item>
/// </list>
/// The rectangles come back as world xz outlines (counter-clockwise in (x, z)).
/// </summary>
public static class PropFootprint
{
    /// <summary>The raster cell (m).</summary>
    public const double CellM = 0.05;
    /// <summary>A footprint never gets more cells than this; a larger prop gets a coarser cell.</summary>
    public const int MaxCells = 1_000_000;

    /// <summary>The band part of the prop: its rectangles (world xz) and the height range of the clipped triangles.</summary>
    public sealed record Result(double BottomY, double TopY, IReadOnlyList<P2[]> Outlines)
    {
        /// <summary>The summed area of the rectangles (m²).</summary>
        public double Area
        {
            get
            {
                double a = 0;
                foreach (var o in Outlines) a += Math.Abs(Shoelace(o));
                return a;
            }
        }
    }

    /// <summary>
    /// The footprint of the triangles <paramref name="tris"/> (world, three vertices per triangle) in the frame whose first
    /// horizontal axis is <paramref name="axis"/> (world xz, the prop's own x axis after its yaw and the location's). Null
    /// when nothing of the model reaches into the band (a rug, a ceiling lamp).
    /// </summary>
    public static Result? Of(IReadOnlyList<Vec3> tris, P2 axis, double bandLow, double bandHigh, double cell = CellM)
    {
        double al = Math.Sqrt(axis.X * axis.X + axis.Z * axis.Z);
        var e1 = al > 1e-12 && double.IsFinite(al) ? new P2(axis.X / al, axis.Z / al) : new P2(1, 0);
        var e2 = new P2(-e1.Z, e1.X);

        var polys = new List<(double A, double B)[]>();
        double bottom = double.PositiveInfinity, top = double.NegativeInfinity;
        double a0 = double.PositiveInfinity, b0 = double.PositiveInfinity, a1 = double.NegativeInfinity, b1 = double.NegativeInfinity;
        for (int t = 0; t + 2 < tris.Count; t += 3)
        {
            var v0 = tris[t];
            var v1 = tris[t + 1];
            var v2 = tris[t + 2];
            double lo = Math.Min(v0.Y, Math.Min(v1.Y, v2.Y)), hi = Math.Max(v0.Y, Math.Max(v1.Y, v2.Y));
            if (!(hi > bandLow) || !(lo < bandHigh)) continue;   // the same test as NavSource's Blocks
            var clipped = Clip(Clip(new List<Vec3> { v0, v1, v2 }, bandLow, true), bandHigh, false);
            if (clipped.Count < 2) continue;
            var proj = new (double A, double B)[clipped.Count];
            for (int i = 0; i < clipped.Count; i++)
            {
                var v = clipped[i];
                if (!double.IsFinite(v.X) || !double.IsFinite(v.Y) || !double.IsFinite(v.Z)) { proj = Array.Empty<(double, double)>(); break; }
                double a = v.X * e1.X + v.Z * e1.Z, b = v.X * e2.X + v.Z * e2.Z;
                proj[i] = (a, b);
                bottom = Math.Min(bottom, v.Y);
                top = Math.Max(top, v.Y);
                a0 = Math.Min(a0, a); a1 = Math.Max(a1, a);
                b0 = Math.Min(b0, b); b1 = Math.Max(b1, b);
            }
            if (proj.Length > 0) polys.Add(proj);
        }
        if (polys.Count == 0) return null;

        double c = cell > 0 && double.IsFinite(cell) ? cell : CellM;
        double spanA = a1 - a0, spanB = b1 - b0;
        if ((spanA / c + 1) * (spanB / c + 1) > MaxCells) c = Math.Sqrt((spanA + c) * (spanB + c) / MaxCells) * 1.01;
        int na = Math.Max(1, (int)Math.Ceiling(spanA / c - 1e-6));
        int nb = Math.Max(1, (int)Math.Ceiling(spanB / c - 1e-6));
        int Ia(double a) => Math.Clamp((int)Math.Floor((a - a0) / c), 0, na - 1);
        int Ib(double b) => Math.Clamp((int)Math.Floor((b - b0) / c), 0, nb - 1);
        var marked = new bool[na, nb];

        foreach (var poly in polys)
        {
            // the edges, sampled at most half a cell apart
            for (int i = 0; i < poly.Length; i++)
            {
                var (pa, pb) = poly[i];
                var (qa, qb) = poly[(i + 1) % poly.Length];
                double len = Math.Sqrt((qa - pa) * (qa - pa) + (qb - pb) * (qb - pb));
                int n = Math.Max(1, (int)Math.Ceiling(len / (c / 2)));
                for (int k = 0; k <= n; k++)
                {
                    double f = (double)k / n;
                    marked[Ia(pa + (qa - pa) * f), Ib(pb + (qb - pb) * f)] = true;
                }
            }
            // the projected area: every cell whose centre lies inside
            if (poly.Length < 3) continue;
            double pa0 = double.PositiveInfinity, pa1 = double.NegativeInfinity, pb0 = double.PositiveInfinity, pb1 = double.NegativeInfinity;
            foreach (var (pa, pb) in poly)
            {
                pa0 = Math.Min(pa0, pa); pa1 = Math.Max(pa1, pa);
                pb0 = Math.Min(pb0, pb); pb1 = Math.Max(pb1, pb);
            }
            for (int i = Ia(pa0); i <= Ia(pa1); i++)
                for (int j = Ib(pb0); j <= Ib(pb1); j++)
                    if (!marked[i, j] && Inside(poly, a0 + (i + 0.5) * c, b0 + (j + 0.5) * c)) marked[i, j] = true;
        }

        // filled = marked, or between marked cells in its row AND in its column
        var rowLo = new int[nb];
        var rowHi = new int[nb];
        var colLo = new int[na];
        var colHi = new int[na];
        Array.Fill(rowLo, int.MaxValue); Array.Fill(rowHi, int.MinValue);
        Array.Fill(colLo, int.MaxValue); Array.Fill(colHi, int.MinValue);
        for (int i = 0; i < na; i++)
            for (int j = 0; j < nb; j++)
                if (marked[i, j])
                {
                    rowLo[j] = Math.Min(rowLo[j], i); rowHi[j] = Math.Max(rowHi[j], i);
                    colLo[i] = Math.Min(colLo[i], j); colHi[i] = Math.Max(colHi[i], j);
                }
        bool Filled(int i, int j) => marked[i, j] || (rowLo[j] < i && i < rowHi[j] && colLo[i] < j && j < colHi[i]);

        // runs per row, equal runs of neighbouring rows merged
        var outlines = new List<P2[]>();
        var open = new List<(int I0, int I1, int J0)>();
        for (int j = 0; j <= nb; j++)
        {
            var runs = new List<(int I0, int I1)>();
            if (j < nb)
                for (int i = 0; i < na; i++)
                {
                    if (!Filled(i, j)) continue;
                    int s = i;
                    while (i + 1 < na && Filled(i + 1, j)) i++;
                    runs.Add((s, i));
                }
            var next = new List<(int I0, int I1, int J0)>();
            foreach (var o in open)
            {
                if (runs.Remove((o.I0, o.I1))) next.Add(o);
                else outlines.Add(Outline(o.I0, o.I1, o.J0, j - 1));
            }
            foreach (var r in runs) next.Add((r.I0, r.I1, j));
            open = next;
        }
        return new Result(bottom, top, outlines);

        P2[] Outline(int i0, int i1, int j0, int j1)
        {
            double xa = a0 + i0 * c, xb = Math.Min(a0 + (i1 + 1) * c, a1);
            double za = b0 + j0 * c, zb = Math.Min(b0 + (j1 + 1) * c, b1);
            if (xb - xa < 1e-9) xb = xa + Math.Min(c, 1e-3);
            if (zb - za < 1e-9) zb = za + Math.Min(c, 1e-3);
            P2 W(double a, double b) => new(a * e1.X + b * e2.X, a * e1.Z + b * e2.Z);
            var ring = new[] { W(xa, za), W(xb, za), W(xb, zb), W(xa, zb) };
            if (Shoelace(ring) < 0) Array.Reverse(ring);
            return ring;
        }
    }

    /// <summary>Sutherland–Hodgman against one horizontal plane: keeps y ≥ <paramref name="y"/> (keepAbove) or y ≤ it.</summary>
    private static List<Vec3> Clip(List<Vec3> poly, double y, bool keepAbove)
    {
        var res = new List<Vec3>(poly.Count + 2);
        for (int i = 0; i < poly.Count; i++)
        {
            var p = poly[i];
            var q = poly[(i + 1) % poly.Count];
            bool pin = keepAbove ? p.Y >= y : p.Y <= y;
            bool qin = keepAbove ? q.Y >= y : q.Y <= y;
            if (pin) res.Add(p);
            if (pin != qin)
            {
                double f = (y - p.Y) / (q.Y - p.Y);
                res.Add(new Vec3(p.X + (q.X - p.X) * f, y, p.Z + (q.Z - p.Z) * f));
            }
        }
        return res;
    }

    /// <summary>Even–odd point-in-polygon (a degenerate, edge-on projection contains no point).</summary>
    private static bool Inside((double A, double B)[] poly, double a, double b)
    {
        bool inside = false;
        for (int i = 0, k = poly.Length - 1; i < poly.Length; k = i++)
        {
            var (ia, ib) = poly[i];
            var (ka, kb) = poly[k];
            if ((ib > b) != (kb > b) && a < (ka - ia) * (b - ib) / (kb - ib) + ia) inside = !inside;
        }
        return inside;
    }

    private static double Shoelace(IReadOnlyList<P2> ring)
    {
        double s = 0;
        for (int i = 0; i < ring.Count; i++)
        {
            var p = ring[i];
            var q = ring[(i + 1) % ring.Count];
            s += p.X * q.Z - q.X * p.Z;
        }
        return s / 2;
    }
}
