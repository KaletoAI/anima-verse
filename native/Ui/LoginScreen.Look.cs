using System;
using Godot;

namespace AnimaNative.Ui;

/// <summary>Theme-fantasy's title tokens and layout, in 900p logical pixels. No downloaded fonts or artwork.</summary>
public partial class LoginScreen
{
    private static readonly Color Gold = new("f2d98c"), BrassGold = new("f2cd6e"), Muted = new("a99f8a"), Ink = new("1a140a");
    private readonly Control _layout = new() { MouseFilter = MouseFilterEnum.Ignore };
    private readonly PanelContainer _plate = new() { Name = "TitlePlate", CustomMinimumSize = new Vector2(430, 0) };
    private readonly FontVariation _caps = Serif(12, smallCaps: true);
    private readonly FontVariation _italic = Serif(14, italic: true);
    private Tween? _entrance;

    private void BuildPlate()
    {
        Theme = new Theme { DefaultFontSize = 14 };
        Theme.SetColor("font_color", "Label", new Color("e8e2d5"));
        var backdrop = new ColorRect
        {
            Name = "TitleBackdrop", MouseFilter = MouseFilterEnum.Ignore,
            Material = _backdropWash = new ShaderMaterial { Shader = GD.Load<Shader>("res://Ui/LoginBackdrop.gdshader") },
        };
        AddChild(backdrop);
        backdrop.SetAnchorsAndOffsetsPreset(LayoutPreset.FullRect);
        AddChild(_layout);
        var center = new CenterContainer { MouseFilter = MouseFilterEnum.Ignore };
        _layout.AddChild(center);
        center.SetAnchorsAndOffsetsPreset(LayoutPreset.FullRect);
        center.AddChild(_plate);

        var frame = Frame(new Color(0, 0, 0, 0), 4, new Color(0, 0, 0, 0));
        frame.ShadowColor = new Color(0, 0, 0, 0.7f);
        frame.ShadowSize = 48;
        frame.ShadowOffset = new Vector2(0, 18);
        _plate.AddThemeStyleboxOverride("panel", frame);
        var vellum = new ShaderMaterial { Shader = GD.Load<Shader>("res://Ui/LoginVellum.gdshader") };
        _plate.AddChild(new ColorRect { MouseFilter = MouseFilterEnum.Ignore, Material = vellum });
        _plate.Resized += () => vellum.SetShaderParameter("surface_size", _plate.Size);
        var padding = new MarginContainer();
        padding.AddThemeConstantOverride("margin_left", 34);
        padding.AddThemeConstantOverride("margin_right", 34);
        padding.AddThemeConstantOverride("margin_top", 40);
        padding.AddThemeConstantOverride("margin_bottom", 34);
        _plate.AddChild(padding);
        var box = new VBoxContainer();
        box.AddThemeConstantOverride("separation", 0);
        padding.AddChild(box);

        var titleFont = Serif(40, smallCaps: true);
        var title = new PanelContainer();
        title.AddThemeStyleboxOverride("panel", new StyleBoxEmpty());
        box.AddChild(title);
        // Concentric translucent outlines approximate the browser's soft 26 px text glow.
        foreach (var (radius, alpha) in new[] { (26, 0.012f), (18, 0.022f), (10, 0.04f), (4, 0.065f) })
            title.AddChild(new Label
            {
                Text = "Anima Verse", HorizontalAlignment = HorizontalAlignment.Center, MouseFilter = MouseFilterEnum.Ignore,
                LabelSettings = new LabelSettings
                {
                    Font = titleFont, FontSize = 40, FontColor = Colors.Transparent,
                    OutlineSize = radius, OutlineColor = new Color(BrassGold, alpha),
                },
            });
        title.AddChild(new Label
        {
            Text = "Anima Verse", HorizontalAlignment = HorizontalAlignment.Center,
            LabelSettings = new LabelSettings
            {
                Font = titleFont, FontSize = 40, FontColor = Gold,
                ShadowColor = new Color(0, 0, 0, 0.8f), ShadowSize = 1, ShadowOffset = new Vector2(0, 1),
            },
        });
        Gap(box, 8);
        var rule = new TextureRect
        {
            MouseFilter = MouseFilterEnum.Ignore, CustomMinimumSize = new Vector2(0, 1),
            ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
            Texture = new GradientTexture2D
            {
                Width = 512, Height = 1, FillFrom = Vector2.Zero, FillTo = Vector2.Right,
                Gradient = new Gradient
                {
                    Offsets = new[] { 0f, 0.16f, 0.5f, 0.84f, 1f },
                    Colors = new[] { new Color(BrassGold, 0), new Color(BrassGold, 0.5f), new Color(BrassGold, 0.78f), new Color(BrassGold, 0.5f), new Color(BrassGold, 0) },
                },
            },
        };
        box.AddChild(rule);
        Gap(box, 14);
        var subtitle = new Label { Text = "A world that lives on without you", HorizontalAlignment = HorizontalAlignment.Center, AutowrapMode = TextServer.AutowrapMode.WordSmart };
        TextStyle(subtitle, _italic, 13, Muted);
        box.AddChild(subtitle);
        Gap(box, 26);

        _fields.AddThemeConstantOverride("separation", 12);
        box.AddChild(_fields);
        _serverField = Field("Server", _server);
        _credentials.AddThemeConstantOverride("separation", 12);
        _fields.AddChild(_credentials);
        _credentials.AddChild(_serverField);
        _credentials.AddChild(Field("Name", _user));
        _credentials.AddChild(Field("Passphrase", _password));
        TextStyle(_remember, _caps, 12, Gold);
        _remember.AddThemeColorOverride("font_focus_color", Gold);
        _remember.AddThemeColorOverride("font_hover_color", Gold);
        _remember.AddThemeStyleboxOverride("focus", FocusFrame());
        _remember.AddThemeIconOverride("checked", CheckIcon(true));
        _remember.AddThemeIconOverride("unchecked", CheckIcon(false));
        _credentials.AddChild(_remember);
        TextStyle(_gateUser, _italic, 13, Muted);
        _fields.AddChild(_gateUser);
        StyleButton(_button);
        _fields.AddChild(_button);
        Link(_signOut);
        _fields.AddChild(_signOut);

        _serverLine.AddThemeConstantOverride("separation", 5);
        TextStyle(_serverSummary, ThemeDB.FallbackFont, 12, Muted);
        Link(_changeServer);
        _serverLine.AddChild(_serverSummary);
        _serverLine.AddChild(_changeServer);
        var serverMargin = new MarginContainer();
        serverMargin.AddThemeConstantOverride("margin_top", 10);
        // The margin is part of the line, so hiding it leaves no empty row during loading.
        serverMargin.AddChild(_serverLine);
        box.AddChild(serverMargin);

        StyleBar(_bar);
        box.AddChild(_bar);
        TextStyle(_stage, _italic, 14, Muted);
        var stageMargin = new MarginContainer();
        stageMargin.AddThemeConstantOverride("margin_top", 10);
        stageMargin.AddChild(_stage);
        box.AddChild(stageMargin);
        // Hide wrappers with their content; Container minimum sizes must collapse with the state.
        _stage.VisibilityChanged += () => stageMargin.Visible = _stage.Visible;
        stageMargin.Visible = _stage.Visible;
        _serverLine.VisibilityChanged += () => serverMargin.Visible = _serverLine.Visible;

        _status.AddThemeFontSizeOverride("font_size", 13);
        var statusMargin = new MarginContainer();
        statusMargin.AddThemeConstantOverride("margin_top", 16);
        statusMargin.AddChild(_status);
        box.AddChild(statusMargin);
        _status.VisibilityChanged += () => statusMargin.Visible = _status.Visible;
        statusMargin.Visible = false;
        StyleButton(_back, secondary: true);
        var backMargin = new MarginContainer();
        backMargin.AddThemeConstantOverride("margin_top", 20);
        backMargin.AddChild(_back);
        box.AddChild(backMargin);
        _back.VisibilityChanged += () => backMargin.Visible = _back.Visible;
        backMargin.Visible = false;
        BuildUpdateNote(box);
    }

    private void ResizePlate()
    {
        // Keep the browser's 430 px plate at 900p, scale proportionally at 4K, and fit short/narrow windows.
        var scale = Math.Max(0.1f, Size.Y / 900f);
        scale = Math.Min(scale, Size.X / 478f);
        var minimum = _plate.GetCombinedMinimumSize();
        if (minimum.Y > 0) scale = Math.Min(scale, Size.Y / (minimum.Y + 48));
        _layout.Scale = Vector2.One * scale;
        _layout.Size = Size / scale;
    }

    private Control Field(string caption, LineEdit input)
    {
        var field = new VBoxContainer();
        field.AddThemeConstantOverride("separation", 4);
        var label = new Label { Text = caption };
        TextStyle(label, _caps, 12, new Color(BrassGold, 0.62f));
        field.AddChild(label);
        var normal = Frame(new Color(0, 0, 0, 0.32f), 3, new Color(BrassGold, 0.26f));
        normal.ContentMarginLeft = normal.ContentMarginRight = 11;
        normal.ContentMarginTop = normal.ContentMarginBottom = 9;
        input.AddThemeStyleboxOverride("normal", normal);
        input.AddThemeStyleboxOverride("read_only", normal);
        input.AddThemeStyleboxOverride("focus", FocusFrame());
        input.AddThemeColorOverride("font_color", new Color("e8e2d5"));
        input.AddThemeColorOverride("caret_color", Gold);
        input.AddThemeColorOverride("selection_color", new Color(BrassGold, 0.22f));
        input.CustomMinimumSize = new Vector2(0, 38);
        input.ExpandToTextLength = false;
        field.AddChild(input);
        return field;
    }

    private void BuildUpdateNote(VBoxContainer box)
    {
        var frame = Frame(new Color("30271c"), 3, new Color(BrassGold, 0.38f));
        frame.ContentMarginLeft = frame.ContentMarginRight = 14;
        frame.ContentMarginTop = frame.ContentMarginBottom = 14;
        _updatePanel.AddThemeStyleboxOverride("panel", frame);
        _updatePanel.AddChild(_updateBox);
        _updateBox.AddThemeConstantOverride("separation", 10);
        _updateBox.AddChild(_updateNotice);
        _updateBox.AddChild(_updateNow);
        _updateBox.AddChild(_updateLater);
        _updateBox.AddChild(_updateBar);
        TextStyle(_updateNotice, ThemeDB.FallbackFont, 13, new Color("e8e2d5"));
        _updateNotice.CustomMinimumSize = Vector2.Zero;
        StyleButton(_updateNow);
        Link(_updateLater);
        StyleBar(_updateBar);
        var margin = new MarginContainer { Visible = false };
        margin.AddThemeConstantOverride("margin_top", 20);
        margin.AddChild(_updatePanel);
        box.AddChild(margin);
        _updateBox.VisibilityChanged += () => margin.Visible = _updateBox.Visible;
    }

    private static Texture2D CheckIcon(bool check)
    {
        using var image = Image.CreateEmpty(18, 18, false, Image.Format.Rgba8);
        image.Fill(Colors.Transparent);
        for (var y = 2; y < 16; y++)
        for (var x = 2; x < 16; x++)
        {
            if (x == 2 || x == 15 || y == 2 || y == 15) image.SetPixel(x, y, new Color(BrassGold, 0.55f));
            if (check && ((x >= 5 && x <= 8 && Math.Abs(y - x - 4) <= 1)
                || (x >= 8 && x <= 13 && Math.Abs(y + x - 20) <= 1))) image.SetPixel(x, y, Gold);
        }
        return ImageTexture.CreateFromImage(image);
    }

    private static FontVariation Serif(int size, bool italic = false, bool smallCaps = false) => new()
    {
        BaseFont = new SystemFont { FontNames = new[] { "Georgia", "DejaVu Serif", "Liberation Serif", "serif" }, FontItalic = italic },
        SpacingGlyph = smallCaps ? (int)Math.Round(size * 0.09) : 0,
        OpentypeFeatures = smallCaps ? new Godot.Collections.Dictionary { ["smcp"] = 1 } : new Godot.Collections.Dictionary(),
    };

    private static void TextStyle(Control control, Font font, int size, Color color)
    {
        control.AddThemeFontOverride("font", font);
        control.AddThemeFontSizeOverride("font_size", size);
        control.AddThemeColorOverride("font_color", color);
    }

    private void StyleButton(Button button, bool secondary = false)
    {
        TextStyle(button, Serif(15, smallCaps: true), 15, secondary ? Gold : Ink);
        foreach (var state in new[] { "normal", "hover", "pressed", "disabled" })
        {
            button.AddThemeColorOverride("font_" + state + "_color", secondary ? Gold : Ink);
            button.AddThemeStyleboxOverride(state, secondary
                ? Frame(new Color(BrassGold, state == "hover" ? 0.08f : 0), 3, new Color(BrassGold, 0.48f))
                : Brass(state));
        }
        button.AddThemeColorOverride("font_focus_color", secondary ? Gold : Ink);
        button.AddThemeStyleboxOverride("focus", FocusFrame());
        button.CustomMinimumSize = new Vector2(0, 42);
    }

    private void Link(Button button)
    {
        button.Flat = true;
        TextStyle(button, _caps, 12, Gold);
        foreach (var state in new[] { "normal", "hover", "pressed", "disabled" })
        {
            button.AddThemeStyleboxOverride(state, new StyleBoxEmpty());
            button.AddThemeColorOverride("font_" + state + "_color", state == "disabled" ? Muted : Gold);
        }
        button.AddThemeColorOverride("font_focus_color", Gold);
        button.AddThemeStyleboxOverride("focus", FocusFrame());
        button.MouseDefaultCursorShape = CursorShape.PointingHand;
    }

    private static void StyleBar(ProgressBar bar)
    {
        bar.ShowPercentage = false;
        bar.CustomMinimumSize = new Vector2(0, 8);
        bar.AddThemeStyleboxOverride("background", Frame(new Color(0, 0, 0, 0.42f), 2, new Color(BrassGold, 0.26f)));
        // Nine-patch keeps the two-pixel corners when the progress fill is very short.
        bar.AddThemeStyleboxOverride("fill", Brass("normal", bar: true));
    }

    private static StyleBoxFlat Frame(Color fill, int radius, Color border) => new()
    {
        BgColor = fill, BorderColor = border,
        BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
        CornerRadiusTopLeft = radius, CornerRadiusTopRight = radius, CornerRadiusBottomLeft = radius, CornerRadiusBottomRight = radius,
        ContentMarginLeft = 0, ContentMarginRight = 0, ContentMarginTop = 0, ContentMarginBottom = 0,
        AntiAliasing = true,
    };

    private static StyleBoxFlat FocusFrame()
    {
        var focus = Frame(Colors.Transparent, 3, new Color(BrassGold, 0.6f));
        focus.ShadowColor = new Color(BrassGold, 0.22f);
        focus.ShadowSize = 1;
        return focus;
    }

    private static StyleBoxTexture Brass(string state, bool bar = false)
    {
        var hover = state == "hover";
        var top = new Color(hover ? "f4dd9c" : "e6cb84");
        var mid = new Color(hover ? "d9b45c" : "c9a34f");
        var bottom = new Color(hover ? "b28c3c" : "a37e33");
        var height = bar ? 8 : 44;
        const int width = 64;
        const int glow = 12;
        var pad = bar ? glow : 0;
        var image = Image.CreateEmpty(width + pad * 2, height + pad * 2, false, Image.Format.Rgba8);
        for (var y = -pad; y < height + pad; y++)
        for (var x = -pad; x < width + pad; x++)
        {
            var p = new Vector2(x + 0.5f - width / 2f, y + 0.5f - height / 2f).Abs() - new Vector2(width / 2f - 3, height / 2f - 3);
            var distance = p.Max(Vector2.Zero).Length() + Math.Min(Math.Max(p.X, p.Y), 0) - 3;
            var t = Mathf.Clamp((float)y / (height - 1), 0, 1);
            var color = t < 0.48f ? top.Lerp(mid, t / 0.48f) : mid.Lerp(bottom, (t - 0.48f) / 0.52f);
            if (distance > -1 && !bar) color = new Color(120 / 255f, 88 / 255f, 34 / 255f, 0.9f);
            if (state == "disabled")
            {
                var gray = (color.R + color.G + color.B) / 3;
                color = color.Lerp(new Color(gray, gray, gray), 0.45f);
            }
            color.A *= Mathf.Clamp(0.5f - distance, 0, 1);
            if (bar && distance > 0) color = new Color(BrassGold, 0.35f * MathF.Exp(-distance * distance / 32));
            image.SetPixel(x + pad, y + pad, color);
        }
        var style = new StyleBoxTexture
        {
            Texture = ImageTexture.CreateFromImage(image),
            TextureMarginLeft = pad + 3, TextureMarginRight = pad + 3,
            TextureMarginTop = pad + 2, TextureMarginBottom = pad + 2,
            ExpandMarginLeft = pad, ExpandMarginRight = pad, ExpandMarginTop = pad, ExpandMarginBottom = pad,
            ContentMarginLeft = bar ? 0 : 18, ContentMarginRight = bar ? 0 : 18,
            ContentMarginTop = bar ? 0 : 11, ContentMarginBottom = bar ? 0 : 11,
        };
        image.Dispose();
        return style;
    }

    private static void Gap(VBoxContainer box, int height) => box.AddChild(new Control { CustomMinimumSize = new Vector2(0, height), MouseFilter = MouseFilterEnum.Ignore });
}
