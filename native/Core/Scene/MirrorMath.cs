using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using AnimaNative.Overview;

namespace AnimaNative.Scene;

/// <summary>A mirror pane's plane in the geometry's own space: area-weighted centroid and unit normal (by winding).</summary>
public readonly record struct MirrorPlane(Vec3 Point, Vec3 Normal);

/// <summary>
/// The pure half of the mirror panes, a port of packages/scene-render/src/mirrorSurface.ts part 1
/// (<c>planeOfFaces</c> with its reasons, <c>MirrorBudget</c>, <c>mirrorRefreshes</c>, <c>MIRROR_PRESET</c>), checked
/// against shared/test-vectors/mirror_plane.json (hand derivations in scripts/smoke_mirror_plane.mjs); plus the
/// native client's own reflection view (<see cref="ReflectionView"/>), which replaces three's oblique near plane.
/// </summary>
public static class MirrorMath
{
    /// <summary><c>FACE_COHERENCE_MIN</c>: |Σ face vectors| / Σ |face vectors| must reach 0.9 for a plane.</summary>
    public const double FaceCoherenceMin = 0.9;
    /// <summary><c>MIRROR_PRESET.tint</c> 0x777777 (sRGB) — the silver overlay on the reflection.</summary>
    public const int PresetTint = 0x777777;
    /// <summary><c>MIRROR_PRESET.textureSize</c>.</summary>
    public const int PresetTextureSize = 512;
    /// <summary><c>MIRROR_PRESET.clipBias</c> (three's oblique near plane; the native frustum's near plane is the pane itself).</summary>
    public const double PresetClipBias = 0.003;

    // The 3D client's cost policy (sceneRecipe.ts MIRROR_OPTS) — view state, the native client adopts it as is.
    public const int ClientTextureSize = 512;
    public const int ClientMaxPerFrame = 2;
    public const double ClientMaxDistanceM = 12;

    /// <summary>
    /// <c>measureFaces</c>: the plane through the triangles of <paramref name="ranges"/> (<c>[start, count]</c>, index units
    /// with an index buffer, vertex units without; a count past the end is clamped), or null with the reason.
    /// </summary>
    public static (MirrorPlane? Plane, string Why) MeasureFaces(IReadOnlyList<double> positions, IReadOnlyList<int>? index,
                                                                IReadOnlyList<(int Start, int Count)> ranges)
    {
        int total = index is not null ? index.Count : positions.Count / 3;
        (double, double, double) Vert(int i)
        {
            int v = index is not null ? index[i] : i;
            double At(int k) => k >= 0 && k < positions.Count ? positions[k] : double.NaN;   // JS reads undefined → NaN
            return (At(v * 3), At(v * 3 + 1), At(v * 3 + 2));
        }
        double nx = 0, ny = 0, nz = 0, cx = 0, cy = 0, cz = 0, weight = 0;
        int faces = 0;
        foreach (var (start, count) in ranges)
        {
            int s = Math.Max(0, start);
            long endL = Math.Min((long)total, (long)s + Math.Max(0, count));
            int end = (int)endL;
            for (int i = s; i + 2 < end; i += 3)
            {
                var (ax, ay, az) = Vert(i);
                var (bx, by, bz) = Vert(i + 1);
                var (qx, qy, qz) = Vert(i + 2);
                double ux = bx - ax, uy = by - ay, uz = bz - az;
                double vx = qx - ax, vy = qy - ay, vz = qz - az;
                double fx = uy * vz - uz * vy;
                double fy = uz * vx - ux * vz;
                double fz = ux * vy - uy * vx;
                double twiceArea = Math.Sqrt(fx * fx + fy * fy + fz * fz);
                if (twiceArea <= 0) continue;   // a NaN face is NOT skipped (as in JS): it poisons the sums, caught below
                nx += fx; ny += fy; nz += fz;
                cx += (ax + bx + qx) / 3 * twiceArea;
                cy += (ay + by + qy) / 3 * twiceArea;
                cz += (az + bz + qz) / 3 * twiceArea;
                weight += twiceArea;
                faces += 1;
            }
        }
        double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        if (!double.IsFinite(len) || !double.IsFinite(weight) || !double.IsFinite(cx) || !double.IsFinite(cy) || !double.IsFinite(cz))
            return (null, "a vertex index reaches past the position buffer");
        if (faces == 0 || weight <= 1e-12) return (null, "no face of the group has any area");
        if (len <= 1e-12) return (null, $"its {faces} faces cancel out exactly (two opposite skins in one material group)");
        double ratio = len / weight;
        if (ratio < FaceCoherenceMin)
            return (null, string.Create(CultureInfo.InvariantCulture,
                $"its {faces} faces have no coherent plane (ratio {ratio:0.0000} < {FaceCoherenceMin}, {weight / 2:0.000000} m² of surface)"));
        return (new MirrorPlane(new Vec3(cx / weight, cy / weight, cz / weight), new Vec3(nx / len, ny / len, nz / len)), "");
    }

    /// <summary><c>planeOfFaces</c>: <see cref="MeasureFaces"/> without the reason.</summary>
    public static MirrorPlane? PlaneOfFaces(IReadOnlyList<double> positions, IReadOnlyList<int>? index,
                                            IReadOnlyList<(int Start, int Count)> ranges)
        => MeasureFaces(positions, index, ranges).Plane;

    /// <summary><c>mirrorRefreshes</c>: a pane refreshes unless it has rendered once and stands farther than the cap.</summary>
    public static bool MirrorRefreshes(bool rendered, double distanceM, double maxDistanceM) => !(rendered && distanceM > maxDistanceM);

    // ---- the native reflection view ---------------------------------------------------------------------------

    /// <summary>
    /// The reflection camera of one pane for one viewer (native only — the browser's Reflector.js uses a mirrored
    /// camera with an oblique near plane, which Godot 4.7's Camera3D cannot take). Instead the camera stands at the
    /// viewer's mirror image behind the pane and looks straight THROUGH it along the pane normal, with an off-axis
    /// frustum whose near plane IS the pane plane and whose window frames the pane: everything behind the mirror lies
    /// before the near plane and is clipped, exactly what the oblique plane achieved. Right, Up, Back are the camera basis
    /// columns (Godot's camera looks along −Back); Size / OffsetX, OffsetY / Near
    /// are <c>Camera3D.set_frustum</c>'s arguments for a square target (keep height); <c>TexU/TexV/TexW</c> map a world
    /// point to (u·w, v·w, w) — the projective texture lookup, top-left origin like a viewport texture.
    /// </summary>
    public readonly record struct View(Vec3 Eye, Vec3 Right, Vec3 Up, Vec3 Back, double Near, double Size, double OffsetX,
                                       double OffsetY, double Distance, double[] TexU, double[] TexV, double[] TexW);

    private static Vec3 Sub(Vec3 a, Vec3 b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
    private static Vec3 Add(Vec3 a, Vec3 b) => new(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
    private static Vec3 Mul(Vec3 a, double k) => new(a.X * k, a.Y * k, a.Z * k);
    private static double Dot(Vec3 a, Vec3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    private static Vec3 Cross(Vec3 a, Vec3 b) => new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
    private static Vec3 Norm(Vec3 a) { double l = Math.Sqrt(Dot(a, a)); return l > 0 ? Mul(a, 1 / l) : a; }

    /// <summary>The smallest near distance the reflection camera takes; a viewer closer to the pane keeps the same window angles.</summary>
    public const double MinNear = 0.01;

    /// <summary>
    /// The reflection view for a pane (world plane point and normal, the pane's world vertices) seen from
    /// <paramref name="eye"/>; null when the viewer stands on the plane (nothing to reflect) or the pane has no extent.
    /// The normal is turned towards the viewer first (both sides of a pane mirror, like the browser).
    /// </summary>
    public static View? ReflectionView(Vec3 planePoint, Vec3 planeNormal, IReadOnlyList<Vec3> paneVertices, Vec3 eye)
    {
        var n = Norm(planeNormal);
        if (Dot(Sub(planePoint, eye), n) > 0) n = Mul(n, -1);
        double d = Dot(Sub(eye, planePoint), n);
        if (!(d > 1e-6) || paneVertices.Count == 0) return null;
        var mirrored = Sub(eye, Mul(n, 2 * d));
        // n faces the viewer and the scene the mirror shows lies on the viewer's side, so the camera behind the pane
        // looks along +n: its back axis is −n.
        var back = Mul(n, -1);
        var worldUp = new Vec3(0, 1, 0);
        var up = Sub(worldUp, Mul(back, Dot(worldUp, back)));
        if (Dot(up, up) < 1e-8) up = Sub(new Vec3(0, 0, -1), Mul(back, Dot(new Vec3(0, 0, -1), back)));   // a floor/ceiling pane
        up = Norm(up);
        var right = Cross(up, back);
        double minX = double.PositiveInfinity, maxX = double.NegativeInfinity, minY = double.PositiveInfinity, maxY = double.NegativeInfinity;
        foreach (var v in paneVertices)
        {
            var r = Sub(v, mirrored);
            double depth = Dot(r, n);
            if (!(depth > 1e-9)) continue;
            // Onto the plane at distance d along the view axis (a pane measured from faces may be slightly uneven).
            double x = Dot(r, right) * d / depth, y = Dot(r, up) * d / depth;
            minX = Math.Min(minX, x); maxX = Math.Max(maxX, x); minY = Math.Min(minY, y); maxY = Math.Max(maxY, y);
        }
        if (!double.IsFinite(minX) || maxX - minX <= 1e-9 || maxY - minY <= 1e-9) return null;
        double near = Math.Max(d, MinNear);
        double k = near / d;   // the window moved to the near distance keeps its angles
        double size = Math.Max(maxX - minX, maxY - minY) * k;
        double offX = (minX + maxX) / 2 * k, offY = (minY + maxY) / 2 * k;
        double left = offX - size / 2, rightE = offX + size / 2, bottom = offY - size / 2, top = offY + size / 2;
        // u·w = (near·x_c − left·z_c)/(R − L), v·w = (top·z_c − near·y_c)/(T − B), w = z_c with x_c = r·right,
        // y_c = r·up, z_c = r·n and r = p − eye′.
        double[] Row(Vec3 coeff) => new[] { coeff.X, coeff.Y, coeff.Z, -Dot(coeff, mirrored) };
        var cu = Mul(Sub(Mul(right, near), Mul(n, left)), 1 / (rightE - left));
        var cv = Mul(Sub(Mul(n, top), Mul(up, near)), 1 / (top - bottom));
        return new View(mirrored, right, up, back, near, size, offX, offY, d, Row(cu), Row(cv), Row(n));
    }

    /// <summary>The projective lookup of <c>TexU/TexV/TexW</c>: a world point → (u, v), top-left origin.</summary>
    public static (double U, double V) TexCoord(View view, Vec3 p)
    {
        double w = view.TexW[0] * p.X + view.TexW[1] * p.Y + view.TexW[2] * p.Z + view.TexW[3];
        double u = view.TexU[0] * p.X + view.TexU[1] * p.Y + view.TexU[2] * p.Z + view.TexU[3];
        double v = view.TexV[0] * p.X + view.TexV[1] * p.Y + view.TexV[2] * p.Z + view.TexV[3];
        return (u / w, v / w);
    }
}

/// <summary>
/// <c>MirrorBudget</c>: how many reflections a frame may render — ONE counter for every pane sharing the instance, and a
/// rotation over the panes that ask (a window of <c>maxPerFrame</c> out of last frame's askers, advanced by
/// <c>maxPerFrame</c> each frame), so no pane stays black. "The same frame" is <c>frame == expected</c>, where every
/// grant bumps the expected number by one (a nested render). <see cref="double.PositiveInfinity"/> grants everyone.
/// </summary>
public sealed class MirrorBudget
{
    private readonly double _maxPerFrame;
    private int _used;
    private double _expected = double.NaN;
    private List<object> _order = new();
    private HashSet<object> _orderSet = new(ReferenceEqualityComparer.Instance);
    private List<object> _asking = new();
    private int _cursor;
    private HashSet<object> _window = new(ReferenceEqualityComparer.Instance);

    public MirrorBudget(double maxPerFrame) => _maxPerFrame = maxPerFrame;

    public double MaxPerFrame => _maxPerFrame;

    /// <summary>May <paramref name="key"/> (a pane, stable across frames) render its reflection in this frame?</summary>
    public bool Allow(double frame, object key)
    {
        if (double.IsPositiveInfinity(_maxPerFrame)) return true;
        if (!(frame == _expected)) StartFrame();
        _expected = frame;
        _asking.Add(key);
        bool granted = _used < _maxPerFrame && (!_orderSet.Contains(key) || _window.Contains(key));
        if (!granted) return false;
        _used += 1;
        _expected = frame + 1;
        return true;
    }

    /// <summary>Take a pane out of the rotation.</summary>
    public void Forget(object key)
    {
        _orderSet.Remove(key);
        _window.Remove(key);
        _order = _order.Where(k => !ReferenceEquals(k, key)).ToList();
        _asking = _asking.Where(k => !ReferenceEquals(k, key)).ToList();
    }

    private void StartFrame()
    {
        _order = _asking;
        _orderSet = new HashSet<object>(_order, ReferenceEqualityComparer.Instance);
        _asking = new List<object>();
        _used = 0;
        _window = new HashSet<object>(ReferenceEqualityComparer.Instance);
        int n = _order.Count;
        if (n == 0) return;
        _cursor = (int)((_cursor + _maxPerFrame) % n);
        int take = (int)Math.Min(_maxPerFrame, n);
        for (int i = 0; i < take; i++) _window.Add(_order[(_cursor + i) % n]);
    }
}
