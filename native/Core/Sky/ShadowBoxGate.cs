using System;

namespace AnimaNative.Sky;

/// <summary>
/// The browser's shadow-caster set, as a test on bounds (Task 26c). three renders into the sun's shadow map only what
/// its orthographic shadow camera sees (WebGLShadowMap: <c>frustum.intersectsObject</c>; engine.ts: ±<see cref="ShadowSnap.HalfM"/>
/// in the light plane around the snapped centre, near 0.5 m — three's default — and far 300 m along the light from the
/// sun, which stands at centre + offset). A caster outside that prism cannot darken any texel of the box, and a
/// receiver outside it gets no shadow at all. Godot's directional shadow instead culls casters against the light-space
/// box of the camera frustum slice [near, max distance] — at aspect 3.7 several times the browser's box. The native
/// gate puts one render layer on the casters whose bounds meet the browser's prism (grown by <see cref="MarginM"/>) and
/// the sun's <c>shadow_caster_mask</c> is that layer: inside the box the shadow is the browser's, outside there is
/// (almost) none, like the browser's.
///
/// The prism is re-evaluated when its centre has moved <see cref="MoveM"/> in the light plane since the last pass (the
/// margin keeps the true box inside the gated one in between), when the light turns, when casters come or go, and every
/// <see cref="RefreshS"/> for moving casters (figures walk at ~1.5 m/s: 0.75 m per refresh, inside the margin's slack).
/// </summary>
public static class ShadowBoxGate
{
    /// <summary>three's <c>OrthographicCamera</c> default near and engine.ts <c>shadowCam.far</c>.</summary>
    public const double NearM = 0.5, FarM = 300;
    /// <summary>The gate's growth beyond the browser's box on every side (m).</summary>
    public const double MarginM = 8;
    /// <summary>A centre move in the light plane that re-evaluates the gate (m); ≤ margin/2 keeps the box inside it.</summary>
    public const double MoveM = 4;
    /// <summary>The periodic re-evaluation for casters that move by themselves (s).</summary>
    public const double RefreshS = 0.5;

    /// <summary>The gated prism: centre, light basis, half width in the light plane, and the light-space z range.</summary>
    public readonly record struct Box((double X, double Y, double Z) Centre, LightBasis Basis, double Half, double ZLo, double ZHi);

    private static double Dot((double X, double Y, double Z) a, (double X, double Y, double Z) b)
        => a.X * b.X + a.Y * b.Y + a.Z * b.Z;

    /// <summary>
    /// The browser's prism for the snapped <paramref name="centre"/> and the sun <paramref name="offset"/>, grown by
    /// <paramref name="margin"/>: half = 70 + margin; z (along the basis z, towards the sun, from the centre) from
    /// |offset| − 300 − margin to |offset| − 0.5 + margin (the camera sits at z = |offset| and looks down −z).
    /// </summary>
    public static Box Of((double X, double Y, double Z) centre, (double X, double Y, double Z) offset, double margin = MarginM)
    {
        var b = ShadowSnap.Basis(offset);
        double len = Math.Sqrt(Dot(offset, offset));
        return new Box(centre, b, ShadowSnap.HalfM + margin, len - FarM - margin, len - NearM + margin);
    }

    /// <summary>
    /// Does an oriented box — world centre <paramref name="c"/> and its three half-axis vectors <paramref name="a0"/>,
    /// <paramref name="a1"/>, <paramref name="a2"/> (basis column × half extent) — meet the prism? Separating-axis test on
    /// the prism's three axes: the box's projection radius on an axis u is |u·a0| + |u·a1| + |u·a2|.
    /// </summary>
    public static bool Overlaps(Box box, (double X, double Y, double Z) c,
                                (double X, double Y, double Z) a0, (double X, double Y, double Z) a1, (double X, double Y, double Z) a2)
    {
        var d = (c.X - box.Centre.X, c.Y - box.Centre.Y, c.Z - box.Centre.Z);
        double R((double X, double Y, double Z) u) => Math.Abs(Dot(u, a0)) + Math.Abs(Dot(u, a1)) + Math.Abs(Dot(u, a2));
        double px = Dot(d, box.Basis.X), py = Dot(d, box.Basis.Y), pz = Dot(d, box.Basis.Z);
        double rx = R(box.Basis.X), ry = R(box.Basis.Y), rz = R(box.Basis.Z);
        return Math.Abs(px) - rx <= box.Half && Math.Abs(py) - ry <= box.Half && pz + rz >= box.ZLo && pz - rz <= box.ZHi;
    }

    /// <summary>Has the centre moved more than <see cref="MoveM"/> along either light-plane axis since <paramref name="last"/>?</summary>
    public static bool Moved(Box last, (double X, double Y, double Z) centre)
    {
        var d = (centre.X - last.Centre.X, centre.Y - last.Centre.Y, centre.Z - last.Centre.Z);
        return Math.Abs(Dot(d, last.Basis.X)) > MoveM || Math.Abs(Dot(d, last.Basis.Y)) > MoveM;
    }
}
