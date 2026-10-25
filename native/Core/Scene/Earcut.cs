using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Scene;

/// <summary>
/// A line-for-line port of the earcut polygon triangulation three.js ships
/// (node_modules/three/src/extras/lib/earcut.js, mapbox/earcut, ISC licence, © Mapbox) — the triangulation
/// behind <c>ShapeGeometry</c>/<c>ExtrudeGeometry</c>. Ported, not re-implemented: which diagonal a plate's
/// top face is cut along decides which probe point lies on an edge, so the native plate must be cut exactly
/// like the browser's (scene_primitives.json [3], <c>smoke_plate_hole</c>). JS number semantics are kept
/// where they matter: <c>| 0</c> truncation to int32 and a stable sort.
/// </summary>
public static class Earcut
{
    private sealed class Node
    {
        public int I;
        public double X, Y;
        public Node Prev = null!, Next = null!;
        public double Z;
        public Node? PrevZ, NextZ;
        public bool Steiner;

        public Node(int i, double x, double y) { I = i; X = x; Y = y; }
    }

    /// <summary><c>earcut(data, holeIndices, dim)</c>: flat coordinates, hole start indices, triangle vertex indices.</summary>
    public static List<int> Triangulate(IReadOnlyList<double> data, IReadOnlyList<int>? holeIndices, int dim = 2)
    {
        bool hasHoles = holeIndices is { Count: > 0 };
        int outerLen = hasHoles ? holeIndices![0] * dim : data.Count;
        var outerNode = LinkedList(data, 0, outerLen, dim, true);
        var triangles = new List<int>();
        if (outerNode is null || outerNode.Next == outerNode.Prev) return triangles;
        double minX = 0, minY = 0, invSize = 0;
        if (hasHoles) outerNode = EliminateHoles(data, holeIndices!, outerNode, dim);
        if (data.Count > 80 * dim)
        {
            minX = data[0];
            minY = data[1];
            double maxX = minX, maxY = minY;
            for (int i = dim; i < outerLen; i += dim)
            {
                double x = data[i], y = data[i + 1];
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
            }
            invSize = Math.Max(maxX - minX, maxY - minY);
            invSize = invSize != 0 ? 32767 / invSize : 0;
        }
        EarcutLinked(outerNode, triangles, dim, minX, minY, invSize, 0);
        return triangles;
    }

    private static Node? LinkedList(IReadOnlyList<double> data, int start, int end, int dim, bool clockwise)
    {
        Node? last = null;
        if (clockwise == (SignedArea(data, start, end, dim) > 0))
            for (int i = start; i < end; i += dim) last = InsertNode(i / dim, data[i], data[i + 1], last);
        else
            for (int i = end - dim; i >= start; i -= dim) last = InsertNode(i / dim, data[i], data[i + 1], last);
        if (last is not null && EqualsPt(last, last.Next))
        {
            RemoveNode(last);
            last = last.Next;
        }
        return last;
    }

    private static Node? FilterPoints(Node? start, Node? end = null)
    {
        if (start is null) return start;
        end ??= start;
        var p = start;
        bool again;
        do
        {
            again = false;
            if (!p.Steiner && (EqualsPt(p, p.Next) || Area(p.Prev, p, p.Next) == 0))
            {
                RemoveNode(p);
                p = end = p.Prev;
                if (p == p.Next) break;
                again = true;
            }
            else p = p.Next;
        } while (again || p != end);
        return end;
    }

    private static void EarcutLinked(Node? ear, List<int> triangles, int dim, double minX, double minY, double invSize, int pass)
    {
        if (ear is null) return;
        if (pass == 0 && invSize != 0) IndexCurve(ear, minX, minY, invSize);
        var stop = ear;
        while (ear.Prev != ear.Next)
        {
            var prev = ear.Prev;
            var next = ear.Next;
            if (invSize != 0 ? IsEarHashed(ear, minX, minY, invSize) : IsEar(ear))
            {
                triangles.Add(prev.I); triangles.Add(ear.I); triangles.Add(next.I);
                RemoveNode(ear);
                ear = next.Next;
                stop = next.Next;
                continue;
            }
            ear = next;
            if (ear == stop)
            {
                if (pass == 0) EarcutLinked(FilterPoints(ear), triangles, dim, minX, minY, invSize, 1);
                else if (pass == 1)
                {
                    var cured = CureLocalIntersections(FilterPoints(ear)!, triangles);
                    EarcutLinked(cured, triangles, dim, minX, minY, invSize, 2);
                }
                else if (pass == 2) SplitEarcut(ear, triangles, dim, minX, minY, invSize);
                break;
            }
        }
    }

    private static bool IsEar(Node ear)
    {
        Node a = ear.Prev, b = ear, c = ear.Next;
        if (Area(a, b, c) >= 0) return false;
        double ax = a.X, bx = b.X, cx = c.X, ay = a.Y, by = b.Y, cy = c.Y;
        double x0 = Math.Min(ax, Math.Min(bx, cx)), y0 = Math.Min(ay, Math.Min(by, cy));
        double x1 = Math.Max(ax, Math.Max(bx, cx)), y1 = Math.Max(ay, Math.Max(by, cy));
        var p = c.Next;
        while (p != a)
        {
            if (p.X >= x0 && p.X <= x1 && p.Y >= y0 && p.Y <= y1
                && PointInTriangleExceptFirst(ax, ay, bx, by, cx, cy, p.X, p.Y) && Area(p.Prev, p, p.Next) >= 0) return false;
            p = p.Next;
        }
        return true;
    }

    private static bool IsEarHashed(Node ear, double minX, double minY, double invSize)
    {
        Node a = ear.Prev, b = ear, c = ear.Next;
        if (Area(a, b, c) >= 0) return false;
        double ax = a.X, bx = b.X, cx = c.X, ay = a.Y, by = b.Y, cy = c.Y;
        double x0 = Math.Min(ax, Math.Min(bx, cx)), y0 = Math.Min(ay, Math.Min(by, cy));
        double x1 = Math.Max(ax, Math.Max(bx, cx)), y1 = Math.Max(ay, Math.Max(by, cy));
        double minZ = ZOrder(x0, y0, minX, minY, invSize), maxZ = ZOrder(x1, y1, minX, minY, invSize);
        Node? p = ear.PrevZ, n = ear.NextZ;
        bool Blocks(Node q) => q.X >= x0 && q.X <= x1 && q.Y >= y0 && q.Y <= y1 && q != a && q != c
                               && PointInTriangleExceptFirst(ax, ay, bx, by, cx, cy, q.X, q.Y) && Area(q.Prev, q, q.Next) >= 0;
        while (p is not null && p.Z >= minZ && n is not null && n.Z <= maxZ)
        {
            if (Blocks(p)) return false;
            p = p.PrevZ;
            if (Blocks(n)) return false;
            n = n.NextZ;
        }
        while (p is not null && p.Z >= minZ)
        {
            if (Blocks(p)) return false;
            p = p.PrevZ;
        }
        while (n is not null && n.Z <= maxZ)
        {
            if (Blocks(n)) return false;
            n = n.NextZ;
        }
        return true;
    }

    private static Node? CureLocalIntersections(Node start, List<int> triangles)
    {
        var p = start;
        do
        {
            Node a = p.Prev, b = p.Next.Next;
            if (!EqualsPt(a, b) && Intersects(a, p, p.Next, b) && LocallyInside(a, b) && LocallyInside(b, a))
            {
                triangles.Add(a.I); triangles.Add(p.I); triangles.Add(b.I);
                RemoveNode(p);
                RemoveNode(p.Next);
                p = start = b;
            }
            p = p.Next;
        } while (p != start);
        return FilterPoints(p);
    }

    private static void SplitEarcut(Node start, List<int> triangles, int dim, double minX, double minY, double invSize)
    {
        var a = start;
        do
        {
            var b = a.Next.Next;
            while (b != a.Prev)
            {
                if (a.I != b.I && IsValidDiagonal(a, b))
                {
                    var c = SplitPolygon(a, b);
                    var fa = FilterPoints(a, a.Next);
                    var fc = FilterPoints(c, c.Next);
                    EarcutLinked(fa, triangles, dim, minX, minY, invSize, 0);
                    EarcutLinked(fc, triangles, dim, minX, minY, invSize, 0);
                    return;
                }
                b = b.Next;
            }
            a = a.Next;
        } while (a != start);
    }

    private static Node EliminateHoles(IReadOnlyList<double> data, IReadOnlyList<int> holeIndices, Node outerNode, int dim)
    {
        var queue = new List<Node>();
        for (int i = 0, len = holeIndices.Count; i < len; i++)
        {
            int start = holeIndices[i] * dim;
            int end = i < len - 1 ? holeIndices[i + 1] * dim : data.Count;
            var list = LinkedList(data, start, end, dim, false);
            if (list is null) continue; // JS would throw on an empty ring; three never hands one in
            if (list == list.Next) list.Steiner = true;
            queue.Add(GetLeftmost(list));
        }
        // Array.prototype.sort is stable; OrderBy is too.
        queue = queue.OrderBy(n => n, Comparer<Node>.Create(CompareXYSlope)).ToList();
        foreach (var hole in queue) outerNode = EliminateHole(hole, outerNode);
        return outerNode;
    }

    private static int CompareXYSlope(Node a, Node b)
    {
        double result = a.X - b.X;
        if (result == 0)
        {
            result = a.Y - b.Y;
            if (result == 0)
            {
                double aSlope = (a.Next.Y - a.Y) / (a.Next.X - a.X);
                double bSlope = (b.Next.Y - b.Y) / (b.Next.X - b.X);
                result = aSlope - bSlope;
            }
        }
        return result > 0 ? 1 : result < 0 ? -1 : 0; // a NaN comparator result counts as 0 in JS
    }

    private static Node EliminateHole(Node hole, Node outerNode)
    {
        var bridge = FindHoleBridge(hole, outerNode);
        if (bridge is null) return outerNode;
        var bridgeReverse = SplitPolygon(bridge, hole);
        FilterPoints(bridgeReverse, bridgeReverse.Next);
        return FilterPoints(bridge, bridge.Next)!;
    }

    private static Node? FindHoleBridge(Node hole, Node outerNode)
    {
        var p = outerNode;
        double hx = hole.X, hy = hole.Y;
        double qx = double.NegativeInfinity;
        Node? m = null;
        if (EqualsPt(hole, p)) return p;
        do
        {
            if (EqualsPt(hole, p.Next)) return p.Next;
            if (hy <= p.Y && hy >= p.Next.Y && p.Next.Y != p.Y)
            {
                double x = p.X + (hy - p.Y) * (p.Next.X - p.X) / (p.Next.Y - p.Y);
                if (x <= hx && x > qx)
                {
                    qx = x;
                    m = p.X < p.Next.X ? p : p.Next;
                    if (x == hx) return m;
                }
            }
            p = p.Next;
        } while (p != outerNode);
        if (m is null) return null;
        var stop = m;
        double mx = m.X, my = m.Y;
        double tanMin = double.PositiveInfinity;
        p = m;
        do
        {
            if (hx >= p.X && p.X >= mx && hx != p.X
                && PointInTriangle(hy < my ? hx : qx, hy, mx, my, hy < my ? qx : hx, hy, p.X, p.Y))
            {
                double tan = Math.Abs(hy - p.Y) / (hx - p.X);
                if (LocallyInside(p, hole)
                    && (tan < tanMin || (tan == tanMin && (p.X > m.X || (p.X == m.X && SectorContainsSector(m, p))))))
                {
                    m = p;
                    tanMin = tan;
                }
            }
            p = p.Next;
        } while (p != stop);
        return m;
    }

    private static bool SectorContainsSector(Node m, Node p)
        => Area(m.Prev, m, p.Prev) < 0 && Area(p.Next, m, m.Next) < 0;

    private static void IndexCurve(Node start, double minX, double minY, double invSize)
    {
        var p = start;
        do
        {
            if (p.Z == 0) p.Z = ZOrder(p.X, p.Y, minX, minY, invSize);
            p.PrevZ = p.Prev;
            p.NextZ = p.Next;
            p = p.Next;
        } while (p != start);
        p.PrevZ!.NextZ = null;
        p.PrevZ = null;
        SortLinked(p);
    }

    private static Node? SortLinked(Node? list)
    {
        int numMerges;
        int inSize = 1;
        do
        {
            var p = list;
            Node? e;
            list = null;
            Node? tail = null;
            numMerges = 0;
            while (p is not null)
            {
                numMerges++;
                var q = p;
                int pSize = 0;
                for (int i = 0; i < inSize; i++)
                {
                    pSize++;
                    q = q!.NextZ;
                    if (q is null) break;
                }
                int qSize = inSize;
                while (pSize > 0 || (qSize > 0 && q is not null))
                {
                    if (pSize != 0 && (qSize == 0 || q is null || p!.Z <= q.Z))
                    {
                        e = p;
                        p = p!.NextZ;
                        pSize--;
                    }
                    else
                    {
                        e = q;
                        q = q!.NextZ;
                        qSize--;
                    }
                    if (tail is not null) tail.NextZ = e;
                    else list = e;
                    e!.PrevZ = tail;
                    tail = e;
                }
                p = q;
            }
            tail!.NextZ = null;
            inSize *= 2;
        } while (numMerges > 1);
        return list;
    }

    /// <summary>JS <c>v | 0</c>: ToInt32 (truncate, wrap modulo 2^32).</summary>
    private static int ToInt32(double v)
    {
        if (!double.IsFinite(v)) return 0;
        double t = Math.Truncate(v);
        double m = t % 4294967296.0;
        if (m < 0) m += 4294967296.0;
        return unchecked((int)(uint)m);
    }

    private static double ZOrder(double xd, double yd, double minX, double minY, double invSize)
    {
        int x = ToInt32((xd - minX) * invSize);
        int y = ToInt32((yd - minY) * invSize);
        x = (x | (x << 8)) & 0x00FF00FF;
        x = (x | (x << 4)) & 0x0F0F0F0F;
        x = (x | (x << 2)) & 0x33333333;
        x = (x | (x << 1)) & 0x55555555;
        y = (y | (y << 8)) & 0x00FF00FF;
        y = (y | (y << 4)) & 0x0F0F0F0F;
        y = (y | (y << 2)) & 0x33333333;
        y = (y | (y << 1)) & 0x55555555;
        return x | (y << 1);
    }

    private static Node GetLeftmost(Node start)
    {
        Node p = start, leftmost = start;
        do
        {
            if (p.X < leftmost.X || (p.X == leftmost.X && p.Y < leftmost.Y)) leftmost = p;
            p = p.Next;
        } while (p != start);
        return leftmost;
    }

    private static bool PointInTriangle(double ax, double ay, double bx, double by, double cx, double cy, double px, double py)
        => (cx - px) * (ay - py) >= (ax - px) * (cy - py)
           && (ax - px) * (by - py) >= (bx - px) * (ay - py)
           && (bx - px) * (cy - py) >= (cx - px) * (by - py);

    private static bool PointInTriangleExceptFirst(double ax, double ay, double bx, double by, double cx, double cy, double px, double py)
        => !(ax == px && ay == py) && PointInTriangle(ax, ay, bx, by, cx, cy, px, py);

    private static bool IsValidDiagonal(Node a, Node b)
        => a.Next.I != b.I && a.Prev.I != b.I && !IntersectsPolygon(a, b)
           && ((LocallyInside(a, b) && LocallyInside(b, a) && MiddleInside(a, b)
                && (Area(a.Prev, a, b.Prev) != 0 || Area(a, b.Prev, b) != 0))
               || (EqualsPt(a, b) && Area(a.Prev, a, a.Next) > 0 && Area(b.Prev, b, b.Next) > 0));

    private static double Area(Node p, Node q, Node r) => (q.Y - p.Y) * (r.X - q.X) - (q.X - p.X) * (r.Y - q.Y);

    private static bool EqualsPt(Node p1, Node p2) => p1.X == p2.X && p1.Y == p2.Y;

    private static bool Intersects(Node p1, Node q1, Node p2, Node q2)
    {
        int o1 = Sign(Area(p1, q1, p2)), o2 = Sign(Area(p1, q1, q2)), o3 = Sign(Area(p2, q2, p1)), o4 = Sign(Area(p2, q2, q1));
        if (o1 != o2 && o3 != o4) return true;
        if (o1 == 0 && OnSegment(p1, p2, q1)) return true;
        if (o2 == 0 && OnSegment(p1, q2, q1)) return true;
        if (o3 == 0 && OnSegment(p2, p1, q2)) return true;
        if (o4 == 0 && OnSegment(p2, q1, q2)) return true;
        return false;
    }

    private static bool OnSegment(Node p, Node q, Node r)
        => q.X <= Math.Max(p.X, r.X) && q.X >= Math.Min(p.X, r.X) && q.Y <= Math.Max(p.Y, r.Y) && q.Y >= Math.Min(p.Y, r.Y);

    private static int Sign(double num) => num > 0 ? 1 : num < 0 ? -1 : 0;

    private static bool IntersectsPolygon(Node a, Node b)
    {
        var p = a;
        do
        {
            if (p.I != a.I && p.Next.I != a.I && p.I != b.I && p.Next.I != b.I && Intersects(p, p.Next, a, b)) return true;
            p = p.Next;
        } while (p != a);
        return false;
    }

    private static bool LocallyInside(Node a, Node b)
        => Area(a.Prev, a, a.Next) < 0
            ? Area(a, b, a.Next) >= 0 && Area(a, a.Prev, b) >= 0
            : Area(a, b, a.Prev) < 0 || Area(a, a.Next, b) < 0;

    private static bool MiddleInside(Node a, Node b)
    {
        var p = a;
        bool inside = false;
        double px = (a.X + b.X) / 2, py = (a.Y + b.Y) / 2;
        do
        {
            if (((p.Y > py) != (p.Next.Y > py)) && p.Next.Y != p.Y
                && (px < (p.Next.X - p.X) * (py - p.Y) / (p.Next.Y - p.Y) + p.X))
                inside = !inside;
            p = p.Next;
        } while (p != a);
        return inside;
    }

    private static Node SplitPolygon(Node a, Node b)
    {
        Node a2 = new(a.I, a.X, a.Y), b2 = new(b.I, b.X, b.Y), an = a.Next, bp = b.Prev;
        a.Next = b; b.Prev = a;
        a2.Next = an; an.Prev = a2;
        b2.Next = a2; a2.Prev = b2;
        bp.Next = b2; b2.Prev = bp;
        return b2;
    }

    private static Node InsertNode(int i, double x, double y, Node? last)
    {
        var p = new Node(i, x, y);
        if (last is null)
        {
            p.Prev = p;
            p.Next = p;
        }
        else
        {
            p.Next = last.Next;
            p.Prev = last;
            last.Next.Prev = p;
            last.Next = p;
        }
        return p;
    }

    private static void RemoveNode(Node p)
    {
        p.Next.Prev = p.Prev;
        p.Prev.Next = p.Next;
        if (p.PrevZ is not null) p.PrevZ.NextZ = p.NextZ;
        if (p.NextZ is not null) p.NextZ.PrevZ = p.PrevZ;
    }

    private static double SignedArea(IReadOnlyList<double> data, int start, int end, int dim)
    {
        double sum = 0;
        for (int i = start, j = end - dim; i < end; i += dim)
        {
            sum += (data[j] - data[i]) * (data[i + 1] + data[j + 1]);
            j = i;
        }
        return sum;
    }
}
