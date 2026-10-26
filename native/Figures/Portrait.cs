using System;
using System.Linq;
using System.Text.RegularExpressions;
using AnimaNative.Scatter;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// THE PORTRAIT SPRITE of a figure without any model (npcs.ts <c>makePortraitTexture</c> + the sprite branch of
/// <c>addNpc</c>/<c>tick</c>): a 144 px picture — a coloured pointer (the seeded ring colour, the avatar's gold) under
/// the character's cut-out portrait, or a dark disc with the initials while the picture has not arrived — on a
/// camera-facing sprite anchored at 2 % above its bottom edge, 0.15 m over the root, sized
/// <c>clamp(camDist·0.055, 1.7, 3.4)</c> m every frame and bobbing <c>0.35·|sin φ|</c> (φ += 14·dt) while it moves;
/// a black disc (r 0.7 m, opacity 0.28) at 0.08 m is its shadow.
///
/// Native differences (view state): the initials are a <see cref="Label3D"/> over the sprite (an <see cref="Image"/>
/// cannot draw text); the sprite turns about its centre (Godot's billboard), three's about the anchor.
/// </summary>
public sealed class Portrait
{
    public const int Size = 144;
    public const double BaseY = 0.15, BobM = 0.35, BobRate = 14, Anchor = 0.02;

    public Node3D Root { get; }
    public Sprite3D Sprite { get; }
    public Label3D Initials { get; }
    /// <summary>The portrait picture arrived (the initials are gone).</summary>
    public bool HasPicture { get; private set; }
    /// <summary>The sprite's size in metres last frame.</summary>
    public double Scale { get; private set; } = 2.6;

    private readonly Color _ring;
    private double _bob;
    private double _lift = BaseY;
    /// <summary>The anchor's height over the figure's root this frame (0.15 m, more while bobbing).</summary>
    public double Lift => _lift;

    public Portrait(string name, bool isAvatar)
    {
        _ring = isAvatar ? new Color("#e8b83a") : RingColor(name);
        Root = new Node3D { Name = "Body" };
        Sprite = new Sprite3D
        {
            Name = "Portrait", Billboard = BaseMaterial3D.BillboardModeEnum.Enabled, Shaded = false,
            AlphaCut = SpriteBase3D.AlphaCutMode.Disabled, Texture = ImageTexture.CreateFromImage(Draw(null)),
        };
        Root.AddChild(Sprite);
        Initials = new Label3D
        {
            Name = "Initials", Text = InitialsOf(name), Billboard = BaseMaterial3D.BillboardModeEnum.Enabled,
            FontSize = Size / 3, Modulate = new Color("#e8e2d5"), OutlineSize = 0, RenderPriority = 1,
        };
        Root.AddChild(Initials);
        var blob = new MeshInstance3D
        {
            Name = "Blob",
            Mesh = new CylinderMesh { TopRadius = 0.7f, BottomRadius = 0.7f, Height = 0.001f, RadialSegments = 18, Rings = 1 },
            Position = new Vector3(0, 0.08f, 0),
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            MaterialOverride = new StandardMaterial3D
            {
                AlbedoColor = new Color(0, 0, 0, 0.28f), Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
                ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
            },
        };
        Root.AddChild(blob);
        Layout();
    }

    /// <summary>npcs.ts <c>ringColor</c>: <c>hsl(floor(rnd()·360), 65 %, 55 %)</c> with <c>seededRandom(name)</c>.</summary>
    public static Color RingColor(string name)
    {
        double hue = Math.Floor(ScatterMath.SeededRandom(name)() * 360);
        return Hsl(hue, 0.65, 0.55);
    }

    /// <summary>CSS <c>hsl()</c> → sRGB.</summary>
    public static Color Hsl(double hDeg, double s, double l)
    {
        double c = (1 - Math.Abs(2 * l - 1)) * s;
        double hp = (hDeg % 360) / 60.0;
        double x = c * (1 - Math.Abs(hp % 2 - 1));
        (double r, double g, double b) = hp switch
        {
            < 1 => (c, x, 0.0), < 2 => (x, c, 0.0), < 3 => (0.0, c, x), < 4 => (0.0, x, c), < 5 => (x, 0.0, c), _ => (c, 0.0, x),
        };
        double m = l - c / 2;
        return new Color((float)(r + m), (float)(g + m), (float)(b + m));
    }

    /// <summary><c>name.split(/\s+/).map(p =&gt; p[0] ?? '').join('').slice(0, 2).toUpperCase()</c>.</summary>
    public static string InitialsOf(string name)
    {
        var s = string.Concat(Regex.Split(name, @"\s+").Select(p => p.Length > 0 ? p[..1] : ""));
        return (s.Length > 2 ? s[..2] : s).ToUpperInvariant();
    }

    /// <summary>The 144 px picture: the pointer, then the portrait scaled into the disc's box, or the dark disc.</summary>
    private Image Draw(Image? picture)
    {
        var img = Image.CreateEmpty(Size, Size, false, Image.Format.Rgba8);
        img.Fill(new Color(0, 0, 0, 0));
        // The pointer: (S/2 − 10, S − 26) → (S/2 + 10, S − 26) → (S/2, S), canvas y down.
        for (int y = Size - 26; y < Size; y++)
        {
            double half = 10.0 * (Size - y) / 26.0;
            for (int x = 0; x < Size; x++)
                if (Math.Abs(x + 0.5 - Size / 2.0) <= half) img.SetPixel(x, y, _ring);
        }
        double r = Size / 2.0 - 6;
        if (picture is not null && picture.GetWidth() > 0 && picture.GetHeight() > 0)
        {
            double s = Math.Min(2 * (r - 8) / picture.GetWidth(), 2 * (r - 8) / picture.GetHeight());
            int w = Math.Max(1, (int)Math.Round(picture.GetWidth() * s)), h = Math.Max(1, (int)Math.Round(picture.GetHeight() * s));
            var scaled = (Image)picture.Duplicate();
            if (scaled.IsCompressed()) scaled.Decompress();
            scaled.Convert(Image.Format.Rgba8);
            scaled.Resize(w, h, Image.Interpolation.Bilinear);
            img.BlendRect(scaled, new Rect2I(0, 0, w, h), new Vector2I((int)Math.Round(Size / 2.0 - w / 2.0), (int)Math.Round(Size / 2.0 - 8 - h / 2.0)));
        }
        else
        {
            var disc = new Color("#2b3440");
            double cx = Size / 2.0, cy = Size / 2.0 - 8, rr = r - 8;
            for (int y = 0; y < Size; y++)
            for (int x = 0; x < Size; x++)
            {
                double dx = x + 0.5 - cx, dy = y + 0.5 - cy;
                if (dx * dx + dy * dy <= rr * rr) img.SetPixel(x, y, disc);
            }
        }
        return img;
    }

    /// <summary>The portrait picture arrived (<c>img.onload = () =&gt; draw(img)</c>): drawn into the sprite, initials gone.</summary>
    public void SetPicture(Image picture)
    {
        if (!GodotObject.IsInstanceValid(Sprite)) return;
        Sprite.Texture = ImageTexture.CreateFromImage(Draw(picture));
        Initials.Visible = false;
        HasPicture = true;
    }

    /// <summary>
    /// One frame of npcs.ts' sprite branch: the size from the camera distance, the bob while moving (else back to
    /// 0.15 m).
    /// </summary>
    public void Tick(double dt, double camDist, bool moving)
    {
        Scale = Math.Clamp(camDist * 0.055, 1.7, 3.4);
        if (moving)
        {
            _bob += dt * BobRate;
            _lift = BaseY + Math.Abs(Math.Sin(_bob)) * BobM;
        }
        else _lift = BaseY;
        Layout();
    }

    /// <summary>The sprite's centre sits (0.5 − 0.02)·size above its anchor; the initials at the disc's centre.</summary>
    private void Layout()
    {
        if (!GodotObject.IsInstanceValid(Sprite)) return;
        float px = (float)(Scale / Size);
        Sprite.PixelSize = px;
        Sprite.Position = new Vector3(0, (float)(_lift + (0.5 - Anchor) * Scale), 0);
        Initials.PixelSize = px;
        // The disc's centre is 8 px above the picture's centre (canvas y down), the text 6 px above it.
        Initials.Position = new Vector3(0, (float)(_lift + (0.5 - Anchor) * Scale + 6 * Scale / Size), 0);
    }

    /// <summary>Decode a portrait picture (PNG / JPEG / WebP by magic bytes); null when it is none of them.</summary>
    public static Image? Decode(byte[] bytes)
    {
        var img = new Image();
        Error err;
        if (bytes.Length >= 8 && bytes[0] == 0x89 && bytes[1] == 0x50) err = img.LoadPngFromBuffer(bytes);
        else if (bytes.Length >= 3 && bytes[0] == 0xFF && bytes[1] == 0xD8) err = img.LoadJpgFromBuffer(bytes);
        else if (bytes.Length >= 12 && bytes[8] == (byte)'W' && bytes[9] == (byte)'E' && bytes[10] == (byte)'B') err = img.LoadWebpFromBuffer(bytes);
        else return null;
        return err == Error.Ok ? img : null;
    }

    /// <summary>
    /// packages/player-ui/src/thumbs.ts <c>transparentPortraitUrl</c>: a character identity image
    /// (<c>/characters/{name}/images/{file}</c>) gets <c>transparent=1</c> in its query; any other URL is kept.
    /// </summary>
    public static string TransparentPortraitUrl(string url)
    {
        int hashAt = url.IndexOf('#');
        string hash = hashAt < 0 ? "" : url[hashAt..];
        string bas = hashAt < 0 ? url : url[..hashAt];
        int queryAt = bas.IndexOf('?');
        string path = queryAt < 0 ? bas : bas[..queryAt];
        if (!Regex.IsMatch(path, "^/characters/[^/]+/images/[^/]+$")) return url;
        var query = queryAt < 0 ? "" : bas[(queryAt + 1)..];
        var parts = query.Split('&', StringSplitOptions.RemoveEmptyEntries)
                         .Where(p => !(p == "transparent" || p.StartsWith("transparent=", StringComparison.Ordinal))).ToList();
        parts.Add("transparent=1");
        return $"{path}?{string.Join("&", parts)}{hash}";
    }
}
