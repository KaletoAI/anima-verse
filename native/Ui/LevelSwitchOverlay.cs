using System;
using System.Collections.Generic;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// The in-world storey switch of an open location (client3d/src/scene/sceneRecipe.ts mountShell step 17, the
/// <c>.level-switch</c> CSS) — scene-owned like the browser's (ruling P3-R8: no bridge message), drawn in screen space
/// over the world like the CSS2D labels, but taking the pointer:
///
///   • WHICH: every built location with more than one declared storey whose interior group is shown in the tree
///     (the browser hangs the widget in <c>g</c>: it comes with the crossfade at 0.03, goes with the neighbour
///     occlusion);
///   • WHERE: centred (CSS2D) on the tile-local point <see cref="StoreyView.SwitchPosition"/> — the first lift box's
///     (x, z), else (2.2, 0), ⅔ of a storey above the SHOWN storey's floor — turned into the world by the location
///     group, projected through the camera's own projection (<see cref="LabelOverlay.Project"/>);
///   • LOOK: a row of buttons sorted ascending (<c>EG</c> / <c>n.</c>), 4 px gap, padding 4 × 6 px, radius 8,
///     <c>rgba(20, 24, 32, .82)</c>; a button 12 px system-ui, padding 2 × 8, radius 5, <c>#2c3442</c> /
///     <c>#dde3ea</c>, the shown storey <c>#e0b64a</c> / <c>#22201a</c>;
///   • INPUT: the browser's widget has <c>pointer-events: auto</c> over a pointer-transparent label layer, so a press
///     on it never reaches the canvas — no pick, no orbit, no drag, no zoom. Here <see cref="_HasPoint"/> is true only
///     over a switch box: Godot's GUI pass then gives that press (and its release) to this control, before the
///     camera's <c>_UnhandledInput</c>; everywhere else the pointer passes through. The HUD routes first
///     (<c>HudOverlay._Input</c>), as its DOM lies over the label layer. A click (press and release on the same
///     button) sets that storey (<see cref="WorldBuilder.SetLevel"/>); the widget then marks it and floats to it.
/// </summary>
public partial class LevelSwitchOverlay : Control
{
    public const int FontSize = 12;
    public const float Gap = 4, PadX = 6, PadY = 4, Radius = 8, ButtonPadX = 8, ButtonPadY = 2, ButtonRadius = 5;
    public static readonly Color BoxColor = new(20 / 255f, 24 / 255f, 32 / 255f, 0.82f);
    public static readonly Color ButtonColor = new("2c3442"), ButtonText = new("dde3ea");
    public static readonly Color ActiveColor = new("e0b64a"), ActiveText = new("22201a");

    /// <summary>One shown switch: its location, where its box and buttons are on screen this frame.</summary>
    public sealed record Placed(string LocationId, Rect2 Box, List<(int Level, string Label, Rect2 Rect, bool Active)> Buttons);

    public Camera3D? Camera { get; set; }
    public WorldBuilder? Builder { get; set; }

    private List<Placed> _placed = new();
    private (string Loc, int Level)? _pressed;
    private static Font? _font;
    private static StyleBoxFlat? _box, _button, _active;

    public LevelSwitchOverlay()
    {
        Name = "LevelSwitchOverlay";
        MouseFilter = MouseFilterEnum.Pass;
        FocusMode = FocusModeEnum.None;
    }

    public override void _Ready() => SetAnchorsPreset(LayoutPreset.FullRect);

    public override void _Process(double delta)
    {
        _placed = Layout(ViewSize());
        QueueRedraw();
        // cursor: pointer over a button (the box itself keeps the arrow, as the CSS has it).
        var at = GetLocalMousePosition();
        var shape = ButtonAt(at) is not null ? CursorShape.PointingHand : CursorShape.Arrow;
        if (MouseDefaultCursorShape != shape) MouseDefaultCursorShape = shape;
    }

    private Vector2 ViewSize()
        => Camera is { } cam && IsInstanceValid(cam) && cam.IsInsideTree() ? cam.GetViewport().GetVisibleRect().Size : GetViewportRect().Size;

    /// <summary><c>system-ui</c> (the button font; <c>font: 12px system-ui</c>).</summary>
    public static Font ButtonFont => _font ??= LabelStyle.Sans;

    /// <summary>The switches of this frame, laid out in viewport px (also the check's entry point).</summary>
    public List<Placed> Layout(Vector2 size)
    {
        var list = new List<Placed>();
        if (Builder is null || Camera is not { } cam || !IsInstanceValid(cam) || !cam.IsInsideTree()) return list;
        foreach (var (id, slot) in Builder.Slots)
        {
            var st = slot.Storeys;
            if (st.Buttons.Count == 0 || !IsInstanceValid(slot.Group)) continue;
            if (slot.Fade.Interior is not { } interior || !interior.IsVisibleInTree()) continue;
            var local = StoreyView.SwitchPosition(st.Elevator, st.FloorY(slot.LevelFilter), slot.LevelFilter, st.StoreyM);
            var world = slot.Group.GlobalTransform * new Vector3((float)local.X, (float)local.Y, (float)local.Z);
            if (LabelOverlay.Project(cam, world, size) is not { } screen) continue;
            list.Add(Arrange(id, st.Buttons, slot.LevelFilter, screen));
        }
        return list;
    }

    /// <summary>The flex row centred on <paramref name="screen"/> (whole pixels, like the labels).</summary>
    public static Placed Arrange(string id, IReadOnlyList<LevelButton> buttons, int shown, Vector2 screen)
    {
        var font = ButtonFont;
        float lineH = font.GetHeight(FontSize);
        float bh = lineH + 2 * ButtonPadY;
        var widths = new List<float>();
        float w = 2 * PadX;
        for (int i = 0; i < buttons.Count; i++)
        {
            float bw = font.GetStringSize(buttons[i].Label, HorizontalAlignment.Left, -1, FontSize).X + 2 * ButtonPadX;
            widths.Add(bw);
            w += bw + (i > 0 ? Gap : 0);
        }
        float h = bh + 2 * PadY;
        var topLeft = new Vector2(Mathf.Round(screen.X - w / 2), Mathf.Round(screen.Y - h / 2));
        var rects = new List<(int, string, Rect2, bool)>();
        float x = topLeft.X + PadX;
        for (int i = 0; i < buttons.Count; i++)
        {
            rects.Add((buttons[i].Level, buttons[i].Label, new Rect2(x, topLeft.Y + PadY, widths[i], bh), buttons[i].Level == shown));
            x += widths[i] + Gap;
        }
        return new Placed(id, new Rect2(topLeft, new Vector2(w, h)), rects);
    }

    /// <summary>The switch box under a point (later boxes are drawn on top, so they win).</summary>
    private Placed? BoxAt(Vector2 p)
    {
        for (int i = _placed.Count - 1; i >= 0; i--)
            if (_placed[i].Box.HasPoint(p)) return _placed[i];
        return null;
    }

    private (string Loc, int Level)? ButtonAt(Vector2 p)
    {
        if (BoxAt(p) is not { } box) return null;
        foreach (var b in box.Buttons)
            if (b.Rect.HasPoint(p)) return (box.LocationId, b.Level);
        return null;
    }

    /// <summary>Only a switch box takes the pointer; everything else passes through to the world.</summary>
    public override bool _HasPoint(Vector2 point) => BoxAt(point) is not null;

    public override void _GuiInput(InputEvent e)
    {
        switch (e)
        {
            case InputEventMouseButton mb:
            {
                // Every button of the mouse, and the wheel, ends on the widget (no orbit, no zoom through it).
                if (mb.Pressed && BoxAt(mb.Position) is null) return;
                AcceptEvent();
                if (mb.ButtonIndex != MouseButton.Left) return;
                if (mb.Pressed) _pressed = ButtonAt(mb.Position);
                else
                {
                    var hit = ButtonAt(mb.Position);
                    if (hit is { } h && _pressed == h) Builder?.SetLevel(h.Loc, h.Level);
                    _pressed = null;
                }
                break;
            }
            case InputEventMouseMotion mm when mm.ButtonMask == 0 && BoxAt(mm.Position) is not null:
                // A bare move over the widget is the widget's (no hover pick behind it); a drag that crosses it
                // stays the camera's (the canvas holds the pointer capture in the browser).
                AcceptEvent();
                break;
        }
    }

    /// <summary>Lay the switches out now (the check, between frames).</summary>
    public void Refresh() => _placed = Layout(ViewSize());

    public IReadOnlyList<Placed> Shown => _placed;

    private static StyleBoxFlat Rounded(Color c, float r) => new()
    {
        BgColor = c,
        CornerRadiusTopLeft = (int)r, CornerRadiusTopRight = (int)r,
        CornerRadiusBottomLeft = (int)r, CornerRadiusBottomRight = (int)r,
        AntiAliasing = true,
    };

    public override void _Draw()
    {
        _box ??= Rounded(BoxColor, Radius);
        _button ??= Rounded(ButtonColor, ButtonRadius);
        _active ??= Rounded(ActiveColor, ButtonRadius);
        var font = ButtonFont;
        float ascent = font.GetAscent(FontSize);
        foreach (var p in _placed)
        {
            DrawStyleBox(_box, p.Box);
            foreach (var (_, label, rect, active) in p.Buttons)
            {
                DrawStyleBox(active ? _active : _button, rect);
                float tw = font.GetStringSize(label, HorizontalAlignment.Left, -1, FontSize).X;
                // text-align centre (the button's own default), baseline one ascent below the content top.
                var at = new Vector2(rect.Position.X + (rect.Size.X - tw) / 2, rect.Position.Y + ButtonPadY + ascent);
                DrawString(font, at, label, HorizontalAlignment.Left, -1, FontSize, active ? ActiveText : ButtonText);
            }
        }
    }
}
