using System;
using System.Collections.Generic;
using System.Diagnostics;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Ui;

/// <summary>One label of the overlay: a block of a given size, centred on the screen point of a world anchor.</summary>
public interface IOverlayLabel
{
    /// <summary>The world point the block is centred on.</summary>
    Vector3 Anchor { get; }
    /// <summary>The block's border-box size in px.</summary>
    Vector2 Size { get; }
    /// <summary>Draw the block with its top-left corner at <paramref name="topLeft"/>.</summary>
    void Draw(CanvasItem canvas, Vector2 topLeft);
}

/// <summary>A label placed for this frame: where its block goes and how far its anchor is from the lens.</summary>
public readonly record struct PlacedLabel(IOverlayLabel Label, Vector2 Screen, Vector2 TopLeft, float DistSq);

/// <summary>
/// The browser's CSS2D label layer (client3d engine.ts <c>labelRenderer</c>, three's <c>CSS2DRenderer</c> r185) as a
/// screen-space <see cref="Control"/> over the world — name tags, speech bubbles and location names drawn with
/// fonts at CSS pixel sizes, not as <c>Label3D</c> (which would scale with distance).
///
///   • PROJECTION — the camera's OWN projection (<see cref="Camera3D.GetCameraProjection"/>, which carries the
///     view shift's <c>frustum_offset</c>), the inverse of <see cref="OverviewCamera.RayAt"/>; three projects with
///     <c>camera.projectionMatrix</c>, which carries <c>setViewOffset</c> the same way. A label shows while its
///     anchor lies between the near and the far plane (CSS2D: <c>z ∈ [−1, 1]</c> in NDC); it is not depth-tested
///     against the scene and not clipped to the screen (only skipped when wholly outside, which looks the same).
///   • PLACEMENT — CSS2D writes the element's inline <c>transform: translate(−50%, −50%) translate(x px, y px)</c>,
///     which overrides the <c>.npc-label</c> classes' <c>translateY(…)</c>: every block is CENTRED on its anchor.
///   • ORDER — CSS2D's <c>sortObjects</c>: the nearer anchor gets the higher z-index, so blocks are drawn far → near
///     across name tags and location names alike.
///   • INPUT — <see cref="Control.MouseFilterEnum.Ignore"/>: the labels never take the pointer (CSS
///     <c>pointer-events: none</c>), so picking and the HUD routing see through them.
/// </summary>
public partial class LabelOverlay : Control
{
    /// <summary>The lens the labels follow.</summary>
    public Camera3D? Camera { get; set; }

    /// <summary>Where the labels come from (name tags, location names); asked once per frame.</summary>
    public List<Func<IEnumerable<IOverlayLabel>>> Sources { get; } = new();

    /// <summary>How many blocks the last frame drew, and what collecting and drawing them cost (ms).</summary>
    public int LastShown { get; private set; }
    public double LastCollectMs { get; private set; }
    public double LastDrawMs { get; private set; }

    public LabelOverlay()
    {
        Name = "LabelOverlay";
        MouseFilter = MouseFilterEnum.Ignore;
        FocusMode = FocusModeEnum.None;
    }

    public override void _Ready() => SetAnchorsPreset(LayoutPreset.FullRect);

    public override void _Process(double delta) => QueueRedraw();

    /// <summary>
    /// The screen point (viewport px of <paramref name="size"/>) of a world point through the camera's own
    /// projection, or null when it lies in front of the near or behind the far plane (or behind the lens).
    /// </summary>
    public static Vector2? Project(Camera3D camera, Vector3 world, Vector2 size)
    {
        var local = camera.GlobalTransform.AffineInverse() * world;
        float depth = -local.Z;
        if (depth < camera.Near || depth > camera.Far) return null;
        var clip = camera.GetCameraProjection() * new Vector4(local.X, local.Y, local.Z, 1f);
        if (clip.W <= 0) return null;
        return new Vector2((clip.X / clip.W * 0.5f + 0.5f) * size.X, (-clip.Y / clip.W * 0.5f + 0.5f) * size.Y);
    }

    /// <summary>
    /// This frame's blocks: projected, centred on their anchors, those wholly off screen left out, sorted far → near
    /// (the drawing order). <paramref name="size"/> = the viewport the camera renders into.
    /// <paramref name="cullOffscreen"/> false keeps the off-screen blocks too: what CSS2D "shows" (it only hides by
    /// depth; the page clips the rest).
    /// </summary>
    public List<PlacedLabel> Collect(Vector2 size, bool cullOffscreen = true)
    {
        var placed = new List<PlacedLabel>();
        if (Camera is not { } cam || !IsInstanceValid(cam) || !cam.IsInsideTree()) return placed;
        var eye = cam.GlobalPosition;
        foreach (var source in Sources)
        {
            foreach (var label in source())
            {
                var anchor = label.Anchor;
                if (Project(cam, anchor, size) is not { } screen) continue;
                var s = label.Size;
                // Whole pixels, so the text stays crisp (CSS2D translates by fractions; the browser's text is
                // positioned with subpixel precision, Godot snaps glyphs anyway).
                var topLeft = new Vector2(Mathf.Round(screen.X - s.X / 2), Mathf.Round(screen.Y - s.Y / 2));
                if (cullOffscreen && (topLeft.X > size.X || topLeft.Y > size.Y || topLeft.X + s.X < 0 || topLeft.Y + s.Y < 0)) continue;
                placed.Add(new PlacedLabel(label, screen, topLeft, eye.DistanceSquaredTo(anchor)));
            }
        }
        placed.Sort((a, b) => b.DistSq.CompareTo(a.DistSq));
        return placed;
    }

    public override void _Draw()
    {
        var t0 = Stopwatch.GetTimestamp();
        var size = Camera is { } cam && IsInstanceValid(cam) ? cam.GetViewport().GetVisibleRect().Size : GetViewportRect().Size;
        var placed = Collect(size);
        var t1 = Stopwatch.GetTimestamp();
        foreach (var p in placed) p.Label.Draw(this, p.TopLeft);
        var t2 = Stopwatch.GetTimestamp();
        LastShown = placed.Count;
        LastCollectMs = (t1 - t0) * 1000.0 / Stopwatch.Frequency;
        LastDrawMs = (t2 - t1) * 1000.0 / Stopwatch.Frequency;
    }
}

/// <summary>
/// The label CSS of client3d/src/style.css in Godot terms: sizes in px, the colours, the fonts — and the two drawing
/// helpers (a shadowed text line, the bubble box). The browser's fonts are CSS families: <c>system-ui</c> for the
/// name tags and bubbles, <c>Georgia, 'Times New Roman', serif</c> for the location names; here the same family
/// lists go to <see cref="SystemFont"/> (fontconfig on Linux picks what the desktop maps them to), with the
/// system's colour emoji font as an explicit fallback (the 🚶 of a travelling name) on top of Godot's own system
/// fallback.
/// </summary>
public static class LabelStyle
{
    // .npc-name / .npc-activity / .npc-avatar
    public const int NameSize = 12, NameWeight = 600, ActivitySize = 10;
    public static readonly Color NameColor = new(1, 1, 1);
    public static readonly Color AvatarColor = new("f2d98c");
    public static readonly Color ActivityColor = new("d8d2c2");
    // .npc-bubble
    public const int BubbleSize = 11;
    public const float BubbleLineHeight = 11 * 1.35f, BubblePadX = 9, BubblePadY = 5, BubbleBorder = 1, BubbleRadius = 10;
    public const float BubbleMarginBottom = 4;
    /// <summary><c>max-width: 22ch</c> on a <c>box-sizing: border-box</c> element: padding and border are inside it.</summary>
    public const int BubbleMaxCh = 22;
    public static readonly Color BubbleText = new("f0ece1");
    public static readonly Color BubbleBg = new(16 / 255f, 19 / 255f, 24 / 255f, 0.88f);
    public static readonly Color BubbleBorderColor = new(242 / 255f, 205 / 255f, 110 / 255f, 0.45f);
    // .loc-label
    public const int LocSize = 15;
    /// <summary>Synthesised <c>font-variant: small-caps</c> (no smcp in Georgia/DejaVu Serif): lower case drawn as capitals at 70 %.</summary>
    public const float LocSmallCapsScale = 0.7f;
    public const float LocLetterSpacingEm = 0.06f;
    public static readonly Color LocColor = new("f2d98c");

    /// <summary>A CSS <c>text-shadow</c> entry: offset (px), blur radius (px), colour.</summary>
    public readonly record struct Shadow(float Dx, float Dy, float Blur, Color Color);

    /// <summary><c>0 1px 3px #000, 0 0 4px rgba(0,0,0,.8)</c></summary>
    public static readonly Shadow[] NameShadow = { new(0, 1, 3, new Color(0, 0, 0, 1)), new(0, 0, 4, new Color(0, 0, 0, 0.8f)) };
    /// <summary><c>0 1px 2px #000</c></summary>
    public static readonly Shadow[] ActivityShadow = { new(0, 1, 2, new Color(0, 0, 0, 1)) };
    /// <summary><c>0 1px 2px #000, 0 0 6px rgba(0,0,0,.9)</c></summary>
    public static readonly Shadow[] LocShadow = { new(0, 1, 2, new Color(0, 0, 0, 1)), new(0, 0, 6, new Color(0, 0, 0, 0.9f)) };

    private static Font? _sans, _sansSemi, _serif;
    private static StyleBoxFlat? _bubbleBox;

    /// <summary><c>system-ui</c> (bubble text).</summary>
    public static Font Sans => _sans ??= SystemFamily(new[] { "system-ui", "sans-serif" }, 400);
    /// <summary><c>system-ui</c> at weight 600 (the name line).</summary>
    public static Font SansSemiBold => _sansSemi ??= SystemFamily(new[] { "system-ui", "sans-serif" }, NameWeight);
    /// <summary><c>Georgia, 'Times New Roman', serif</c> with <c>letter-spacing: 0.06em</c> (0.9 px → 1 px at 15 px).</summary>
    public static Font Serif => _serif ??= new FontVariation
    {
        BaseFont = SystemFamily(new[] { "Georgia", "Times New Roman", "serif" }, 400),
        SpacingGlyph = (int)Math.Round(LocLetterSpacingEm * LocSize),
    };

    private static Font SystemFamily(string[] names, int weight)
    {
        var font = new SystemFont { FontNames = names, FontWeight = weight, AllowSystemFallback = true };
        if (EventPins.SharedEmojiFont is { } emoji) font.Fallbacks = new Godot.Collections.Array<Font> { emoji };
        return font;
    }

    /// <summary>The bubble's box: background, 1 px border, radius 10, <c>box-shadow: 0 2px 8px rgba(0,0,0,.55)</c>.</summary>
    public static StyleBoxFlat BubbleBox => _bubbleBox ??= new StyleBoxFlat
    {
        BgColor = BubbleBg,
        BorderColor = BubbleBorderColor,
        BorderWidthLeft = (int)BubbleBorder, BorderWidthTop = (int)BubbleBorder,
        BorderWidthRight = (int)BubbleBorder, BorderWidthBottom = (int)BubbleBorder,
        CornerRadiusTopLeft = (int)BubbleRadius, CornerRadiusTopRight = (int)BubbleRadius,
        CornerRadiusBottomLeft = (int)BubbleRadius, CornerRadiusBottomRight = (int)BubbleRadius,
        ShadowColor = new Color(0, 0, 0, 0.55f),
        ShadowSize = 8,
        ShadowOffset = new Vector2(0, 2),
        AntiAliasing = true,
    };

    /// <summary>
    /// A text line with its CSS shadows. Godot has no blurred text shadow, so a shadow is approximated by an outline of
    /// its blur radius at a fraction of its alpha (the soft halo) plus, for an offset shadow, the glyphs themselves at
    /// the offset (the hard core).
    /// </summary>
    public static void DrawText(CanvasItem canvas, TextLine line, Vector2 topLeft, Color color, Shadow[] shadows)
    {
        var rid = canvas.GetCanvasItem();
        foreach (var s in shadows)
        {
            var at = topLeft + new Vector2(s.Dx, s.Dy);
            if (s.Blur > 0)
                line.DrawOutline(rid, at, (int)Math.Ceiling(s.Blur), new Color(s.Color, s.Color.A * 0.45f));
            if (s.Dx != 0 || s.Dy != 0) line.Draw(rid, at, new Color(s.Color, s.Color.A * 0.8f));
        }
        line.Draw(rid, topLeft, color);
    }

    /// <summary>One shaped line of a single font and size.</summary>
    public static TextLine Line(string text, Font font, int size)
    {
        var line = new TextLine();
        if (text.Length > 0) line.AddString(text, font, size);
        return line;
    }
}
