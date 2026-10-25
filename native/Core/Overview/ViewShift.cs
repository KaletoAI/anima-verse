using AnimaNative.Hud;

namespace AnimaNative.Overview;

/// <summary>
/// Port of client3d/src/scene/viewShift.ts — where in the window the camera's aim point lands
/// when the chat panel covers a corner: the area-weighted centre of the four free strips around
/// the panel, capped at <see cref="MaxShiftFraction"/> of the half axis. The scene applies it as
/// a frustum shift, not a camera turn. <see cref="Dx"/> is to the right, <see cref="Dy"/> DOWN
/// (screen axes), both in CSS pixels. Vectors: shared/test-vectors/view_shift.json (hand
/// derivations in client3d/scripts/smoke_view_shift.mjs).
/// </summary>
public readonly record struct ViewShift(double Dx, double Dy)
{
    /// <summary>How far the aim point may leave the middle, as a fraction of the half axis.</summary>
    public const double MaxShiftFraction = 0.35;

    /// <summary>No panel, no shift.</summary>
    public static readonly ViewShift None = new(0, 0);

    /// <summary>The viewShift.ts clamp, <c>v &lt; lo ? lo : v &gt; hi ? hi : v</c>.</summary>
    private static double Clamp(double v, double lo, double hi) => v < lo ? lo : v > hi ? hi : v;

    /// <summary>
    /// Where the aim point belongs when <paramref name="panel"/> (the TS <c>ScreenBox</c>, i.e. the
    /// HUD's <see cref="HudRect"/>) covers part of a <paramref name="w"/> × <paramref name="h"/>
    /// canvas. The panel is clipped to the canvas first; a panel covering everything, an empty
    /// panel, no panel or no canvas answer <see cref="None"/>.
    /// </summary>
    public static ViewShift For(double w, double h, HudRect? panel)
    {
        if (!(w > 0) || !(h > 0) || panel is not HudRect p) return None;
        double px = Clamp(p.X, 0, w);
        double py = Clamp(p.Y, 0, h);
        double pr = Clamp(p.X + p.W, 0, w);
        double pb = Clamp(p.Y + p.H, 0, h);
        if (!(pr > px) || !(pb > py)) return None;

        // The four strips: area, centre x, centre y — left, right, above, below the panel.
        double area = 0, cx = 0, cy = 0;
        void Add(double a, double x, double y)
        {
            if (a <= 0) return;
            area += a;
            cx += a * x;
            cy += a * y;
        }
        Add(px * h, px / 2, h / 2);
        Add((w - pr) * h, (pr + w) / 2, h / 2);
        Add(w * py, w / 2, py / 2);
        Add(w * (h - pb), w / 2, (pb + h) / 2);
        if (area <= 0) return None;
        cx /= area;
        cy /= area;

        double maxX = MaxShiftFraction * w / 2;
        double maxY = MaxShiftFraction * h / 2;
        return new ViewShift(Clamp(cx - w / 2, -maxX, maxX), Clamp(cy - h / 2, -maxY, maxY));
    }
}
