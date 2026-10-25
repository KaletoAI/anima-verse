using System.Collections.Generic;
using Godot;

namespace AnimaNative.Hud;

/// <summary>Who gets an input event: the HUD (CEF) or the 3D scene (Godot).</summary>
public enum InputTarget { Hud, Scene }

/// <summary>
/// The input rules of the native HUD as pure functions — the port of main.ts
/// <c>mountHudFrame</c>'s pointer rule (<c>overlayOpen || pointInRects(hitRects, x, y)</c>)
/// and of bus.ts <c>keyForScene</c>/<c>escTarget</c>, plus the drag capture an
/// iframe gets from the browser for free.
///
/// UNITS. <c>hitRects</c> are the HUD page's CSS pixels (<c>getBoundingClientRect</c>).
/// gdCEF paints at device scale factor 1 (it does not override CEF's
/// <c>GetScreenInfo</c>) into a view the size of the overlay, so one CSS px is
/// one browser-view px; Godot reports the pointer in viewport px. The bridge
/// carries no devicePixelRatio, so the scale comes from the scene side:
/// <c>css = window × cssPerWindowPx</c>, with <c>cssPerWindowPx = viewWidth /
/// overlayWidth</c> (1 while the view is sized to the overlay, 0.5 for a page
/// laid out at DPR 2 on a window twice as wide).
/// </summary>
public static class HudRouting
{
    /// <summary><c>pointInRects</c> of bridge.ts: left/top edges inside, right/bottom edges outside.</summary>
    public static bool PointInRects(IReadOnlyList<HudRect> rects, double x, double y)
    {
        foreach (var r in rects)
            if (x >= r.X && y >= r.Y && x < r.X + r.W && y < r.Y + r.H) return true;
        return false;
    }

    /// <summary>A pointer at window position (<paramref name="wx"/>, <paramref name="wy"/>) belongs to the HUD.</summary>
    public static bool OverHud(HudUi ui, double wx, double wy, double cssPerWindowPx)
        => ui.OverlayOpen || PointInRects(ui.HitRects, wx * cssPerWindowPx, wy * cssPerWindowPx);

    /// <summary>Keys go to CEF while the HUD owns the keyboard (<c>!keyForScene(ui)</c>: typing, or a modal overlay).</summary>
    public static bool KeysToHud(HudUi ui) => ui.Typing || ui.OverlayOpen;

    /// <summary>
    /// The ui action the SCENE answers a key with when the HUD does not own the
    /// keyboard (main.ts: F opens the chat via <c>triggerOffer('talk')</c>, M
    /// <c>toggleMenu</c>, Esc <c>closeMenu</c> while the menu is open; the native
    /// spike adds Enter → chat). Modifier combinations belong to the system.
    /// null = not a HUD key.
    /// </summary>
    public static string? SceneKeyAction(Key key, bool menuOpen, bool modifier)
    {
        if (modifier) return null;
        return key switch
        {
            Key.Enter or Key.KpEnter or Key.F => "openChat",
            Key.M => "toggleMenu",
            Key.Escape => menuOpen ? "closeMenu" : null,
            _ => null,
        };
    }
}

/// <summary>
/// Pointer capture across the HUD/scene border. A press goes where the pointer
/// is (<see cref="HudRouting.OverHud"/>) and that side keeps the pointer until
/// every button is up again — a camera drag that crosses a panel keeps
/// orbiting, a text selection that leaves the chat keeps selecting. Without a
/// button down: CEF always gets the motion (hover states), the scene only
/// outside the HUD surfaces.
/// </summary>
public sealed class MouseRouter
{
    private InputTarget? _capture;
    private int _down;

    public InputTarget? Capture => _capture;

    public InputTarget Press(bool overHud)
    {
        if (_down == 0) _capture = overHud ? InputTarget.Hud : InputTarget.Scene;
        _down++;
        return _capture!.Value;
    }

    public InputTarget Release(bool overHud)
    {
        var target = _capture ?? (overHud ? InputTarget.Hud : InputTarget.Scene);
        if (_down > 0) _down--;
        if (_down == 0) _capture = null;
        return target;
    }

    /// <summary>(to CEF, to the scene) for a pointer motion.</summary>
    public (bool Hud, bool Scene) Motion(bool overHud)
        => _capture switch
        {
            InputTarget.Hud => (true, false),
            InputTarget.Scene => (true, true),
            _ => (true, !overHud),
        };

    public static InputTarget Wheel(bool overHud) => overHud ? InputTarget.Hud : InputTarget.Scene;

    public void Reset()
    {
        _capture = null;
        _down = 0;
    }
}

/// <summary>
/// Figure picking for the plaque: a click selects the figure whose screen-space
/// body (the segment feet → head) passes nearest to the pointer, within a
/// tolerance of max(<see cref="MinTolerancePx"/>, 0.3 × the segment's length) —
/// a far figure stays clickable, a near one is as wide as it looks. Ties in
/// distance go to the figure nearer to the camera.
/// </summary>
public static class FigurePick
{
    public const double MinTolerancePx = 10;

    public readonly record struct Candidate(string Name, Vector2 Feet, Vector2 Head, double Depth);

    public static string? Pick(IEnumerable<Candidate> candidates, Vector2 click)
    {
        string? best = null;
        double bestDist = double.MaxValue, bestDepth = double.MaxValue;
        foreach (var c in candidates)
        {
            double len = c.Feet.DistanceTo(c.Head);
            double dist = SegmentDistance(click, c.Feet, c.Head);
            if (dist > System.Math.Max(MinTolerancePx, 0.3 * len)) continue;
            if (dist < bestDist - 1e-9 || (System.Math.Abs(dist - bestDist) <= 1e-9 && c.Depth < bestDepth))
            {
                best = c.Name;
                bestDist = dist;
                bestDepth = c.Depth;
            }
        }
        return best;
    }

    public static double SegmentDistance(Vector2 p, Vector2 a, Vector2 b)
    {
        var ab = b - a;
        double len2 = ab.LengthSquared();
        double t = len2 < 1e-12 ? 0 : System.Math.Clamp((p - a).Dot(ab) / len2, 0, 1);
        return p.DistanceTo(a + ab * (float)t);
    }
}
