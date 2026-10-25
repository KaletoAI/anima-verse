using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The event pins of the overview (client3d/src/main.ts <c>updatePins</c> / <c>makePinTexture</c>, the bob in
/// the frame hook; the rule in <see cref="EventPinRule"/>): one billboard per location with events, 🔥 when
/// one of them is <c>danger</c>, else ❗, 3 m tall, never hidden by geometry, bobbing; 3.5 m above the top of its
/// place, measured from the place's ground datum (client3d/src/game/eventPins.ts, vector-checked).
///
/// THE GLYPH. The browser draws the emoji with the canvas font <c>72px serif</c>, i.e. the system's colour
/// emoji font (Noto Color Emoji on a Linux desktop). Godot renders colour glyphs (CBDT/COLR via FreeType) when
/// it is given such a font, but its default font has no emoji. So the pin looks for a colour emoji font of
/// the system (<see cref="OS.GetSystemFontPath"/>, Noto first) and draws the glyph with a
/// <see cref="Label3D"/> in it — 72 px at 3 m per 96 px, the canvas's (48, 54) anchor as a 6 px offset
/// down from the centre. Without such a font it draws a look-alike instead (<see cref="Fallback"/>): an
/// orange-yellow flame or a red exclamation mark on a 96 px image, the same size and anchor.
/// </summary>
public partial class EventPins : Node3D
{
    /// <summary>Colour emoji families, in the order a Linux/Windows/macOS desktop would have them.</summary>
    private static readonly string[] EmojiFamilies = { "Noto Color Emoji", "Twemoji", "Apple Color Emoji", "Segoe UI Emoji", "EmojiOne Color" };
    private const float PixelSize = (float)(EventPinRule.ScaleM / EventPinRule.CanvasPx);

    private static FontFile? _emojiFont;
    private static bool _fontProbed;
    private static string _fontSource = "";

    private readonly Dictionary<string, Node3D> _pins = new();
    private double _bob;

    /// <summary>The pins by location id (for the check).</summary>
    public IReadOnlyDictionary<string, Node3D> Pins => _pins;

    /// <summary>Which glyph source draws the pins: the font path, or "drawn fallback".</summary>
    public static string GlyphSource
    {
        get
        {
            EmojiFont();
            return _fontSource;
        }
    }

    public EventPins() => Name = "EventPins";

    /// <summary>
    /// One poll (<c>updatePins(map)</c>): pins for <c>events_by_location</c>. A pin whose glyph changed is rebuilt,
    /// and every wanted pin is placed again at the place's centre and <see cref="EventPinRule.PinY"/> — the ground
    /// datum can settle after the pin was made. <paramref name="placeOf"/> answers a known place's centre (x, ground
    /// datum, z) and height, null for an unknown id (<c>places.has</c>).
    /// </summary>
    public void Update(JsonElement map, Func<string, (double X, double GroundY, double Z, double Height)?> placeOf)
    {
        var events = new List<KeyValuePair<string, IReadOnlyCollection<string?>>>();
        if (map.ValueKind == JsonValueKind.Object && map.TryGetProperty("events_by_location", out var byLoc)
            && byLoc.ValueKind == JsonValueKind.Object)
        {
            foreach (var p in byLoc.EnumerateObject())
            {
                if (p.Value.ValueKind != JsonValueKind.Array) continue;
                var cats = p.Value.EnumerateArray()
                    .Select(e => e.ValueKind == JsonValueKind.Object && e.TryGetProperty("category", out var c)
                                 && c.ValueKind == JsonValueKind.String ? c.GetString() : null)
                    .ToList();
                events.Add(new(p.Name, cats));
            }
        }
        var wanted = EventPinRule.Wanted(events, id => placeOf(id) is not null);
        var existing = _pins.ToDictionary(kv => kv.Key, kv => kv.Value.GetMeta("glyph").AsString());
        var (remove, add) = EventPinRule.Diff(existing, wanted);
        foreach (var id in remove)
        {
            // Out of the tree at once, so a rebuilt pin can take the same node name this frame.
            RemoveChild(_pins[id]);
            _pins[id].QueueFree();
            _pins.Remove(id);
        }
        foreach (var (id, glyph) in add)
        {
            var pin = MakePin(glyph);
            pin.Name = ("Pin_" + id).ValidateNodeName();
            pin.SetMeta("glyph", glyph);
            AddChild(pin);
            _pins[id] = pin;
        }
        foreach (var id in wanted.Keys)
        {
            var place = placeOf(id)!.Value;
            _pins[id].Position = new Vector3((float)place.X, (float)EventPinRule.PinY(place.GroundY, place.Height), (float)place.Z);
        }
    }

    public override void _Process(double delta) => Bob(delta);

    /// <summary>One frame of the bob (public for the check).</summary>
    public void Bob(double dt)
    {
        (_bob, double dy) = EventPinRule.BobStep(_bob, dt);
        foreach (var pin in _pins.Values) pin.Position += new Vector3(0, (float)dy, 0);
    }

    private static Node3D MakePin(string glyph)
    {
        if (EmojiFont() is { } font)
        {
            return new Label3D
            {
                Text = glyph,
                Font = font,
                FontSize = EventPinRule.FontPx,
                PixelSize = PixelSize,
                // textBaseline 'middle' at y = 54 of 96: 6 px below the sprite's centre (Label3D: +y is up).
                Offset = new Vector2(0, (float)(EventPinRule.CanvasPx / 2.0 - EventPinRule.TextY)),
                Billboard = BaseMaterial3D.BillboardModeEnum.Enabled,
                NoDepthTest = true,
                Shaded = false,
                DoubleSided = true,
                OutlineSize = 0,
                RenderPriority = 10,
                Modulate = Colors.White,
            };
        }
        return new Sprite3D
        {
            Texture = Fallback(glyph),
            PixelSize = PixelSize,
            Billboard = BaseMaterial3D.BillboardModeEnum.Enabled,
            NoDepthTest = true,
            Shaded = false,
            DoubleSided = true,
            RenderPriority = 10,
            TextureFilter = BaseMaterial3D.TextureFilterEnum.LinearWithMipmaps,
        };
    }

    /// <summary>The system's colour emoji font (probed once), for other text that shows emoji (name tags); null without one.</summary>
    public static FontFile? SharedEmojiFont => EmojiFont();

    /// <summary>The system's colour emoji font when it has both glyphs, else null (probed once).</summary>
    private static FontFile? EmojiFont()
    {
        if (_fontProbed) return _emojiFont;
        _fontProbed = true;
        _fontSource = "drawn fallback";
        foreach (var family in EmojiFamilies)
        {
            string path;
            try { path = OS.GetSystemFontPath(family); }
            catch (Exception) { continue; }
            if (string.IsNullOrEmpty(path) || !System.IO.File.Exists(path)) continue;
            var font = new FontFile();
            if (font.LoadDynamicFont(path) != Error.Ok) continue;
            // Bitmap colour fonts (Noto's CBDT strikes are 109 px) are scaled to the requested size.
            font.FixedSizeScaleMode = TextServer.FixedSizeScaleMode.Enabled;
            if (!font.HasChar(0x1F525) || !font.HasChar(0x2757)) continue;
            _emojiFont = font;
            _fontSource = $"{family} ({path})";
            break;
        }
        GD.Print($"[native] event pins: glyphs from {_fontSource}");
        return _emojiFont;
    }

    // ---- the drawn fallback ------------------------------------------------------------------------

    private static readonly Dictionary<string, ImageTexture> _fallbacks = new();

    /// <summary>
    /// A 96 × 96 look-alike of the emoji, drawn on the CPU (4 × 4 supersampled), the shape centred where
    /// the canvas puts the glyph (x 48, 6 px below the middle) and about 72 px tall like the font's glyph:
    /// 🔥 = an orange flame with a yellow core, ❗ = a red bar over a red dot (Noto's colours).
    /// </summary>
    public static ImageTexture Fallback(string glyph)
    {
        if (_fallbacks.TryGetValue(glyph, out var tex)) return tex;
        var img = FallbackImage(glyph);
        img.GenerateMipmaps();
        return _fallbacks[glyph] = ImageTexture.CreateFromImage(img);
    }

    public static Image FallbackImage(string glyph)
    {
        const int n = EventPinRule.CanvasPx, ss = 4;
        var img = Image.CreateEmpty(n, n, false, Image.Format.Rgba8);
        bool fire = glyph == EventPinRule.Danger;
        var outer = fire ? new Color("f4511e") : new Color("e53935");
        var inner = new Color("ffca28");
        for (int py = 0; py < n; py++)
        for (int px = 0; px < n; px++)
        {
            float r = 0, g = 0, b = 0, a = 0;
            for (int sy = 0; sy < ss; sy++)
            for (int sx = 0; sx < ss; sx++)
            {
                // Glyph space: origin at the canvas anchor (48, 54), y up, 1 unit = 1 px.
                double x = px + (sx + 0.5) / ss - EventPinRule.TextX;
                double y = EventPinRule.TextY - (py + (sy + 0.5) / ss);
                Color? c = fire ? Flame(x, y, outer, inner) : Bang(x, y, outer);
                if (c is not { } cc) continue;
                r += cc.R; g += cc.G; b += cc.B; a += 1;
            }
            if (a == 0) continue;
            float k = 1f / (ss * ss);
            // Straight alpha: the colour is the mean over the covered samples.
            img.SetPixel(px, py, new Color(r / a, g / a, b / a, a * k));
        }
        return img;
    }

    /// <summary>A flame: a teardrop (round bottom r 24 at y −14, tip at y +36) with a yellow inner drop.</summary>
    private static Color? Flame(double x, double y, Color outer, Color inner)
    {
        if (InDrop(x, y, cy: -14, r: 24, tip: 36, lean: 6)) return InDrop(x, y + 6, cy: -14, r: 12, tip: 14, lean: 2) ? inner : outer;
        return null;
    }

    /// <summary>A teardrop: the circle (0, cy, r) plus the region tapering to (lean, tip) above it.</summary>
    private static bool InDrop(double x, double y, double cy, double r, double tip, double lean)
    {
        if (x * x + (y - cy) * (y - cy) <= r * r) return true;
        if (y < cy || y > tip) return false;
        double f = (y - cy) / (tip - cy);                  // 0 at the circle's centre line, 1 at the tip
        double half = r * Math.Cos(f * Math.PI / 2);         // the width closes in a smooth arc
        double mid = lean * f * f;                           // the tip leans a little to the right
        return Math.Abs(x - mid) <= half;
    }

    /// <summary>An exclamation mark: a bar tapering downwards (y −8 … 36) and a dot (r 7.5 at y −24).</summary>
    private static Color? Bang(double x, double y, Color red)
    {
        if (x * x + (y + 24) * (y + 24) <= 7.5 * 7.5) return red;
        if (y < -8 || y > 36) return null;
        double half = 6 + (y + 8) / 44 * 4;                  // 6 px at the foot, 10 px at the top
        double top = 36 - half;                              // a round top
        if (y > top) return x * x + (y - top) * (y - top) <= half * half ? red : null;
        return Math.Abs(x) <= half ? red : null;
    }
}
