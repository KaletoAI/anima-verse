using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Godot;

namespace AnimaNative.Hud;

/// <summary>
/// The React HUD (<c>client3d/hud.html</c>, served by the Anima server) over the
/// Godot world — Task S4 of plan-native-client.md.
///
///   • VIEW — gdCEF renders the page off-screen into a full-window TextureRect
///     on canvas layer 5 (above the status line, below the login screen) at up
///     to 60 fps. gdCEF never sets <c>CefBrowserSettings.background_color</c>, so
///     CEF paints windowless pages TRANSPARENTLY; its BGRA buffer is copied to
///     RGBA8 with the alpha kept. Chromium's alpha is PREMULTIPLIED, hence the
///     premultiplied blend mode of the rect (straight blending would darken every
///     half-transparent panel edge). Nearest filtering: one view px = one screen px.
///   • BRIDGE — protocol v1 of bridge.ts over gdCEF's JS binding: the page calls
///     <c>window.godotMethods.hud_bridge(json)</c> (→ <see cref="hud_bridge"/>),
///     Godot answers with <c>js_emit("hud_bridge", json)</c> (→ <c>godotEvents</c>);
///     the page side is <c>gdcefTransport</c>, chosen by <c>?bridge=gdcef</c>.
///   • INPUT — <see cref="HudRouting"/>/<see cref="MouseRouter"/>: pointer events go
///     to CEF over a HUD surface (or anywhere while an overlay is open) and to the
///     scene elsewhere; keys go to CEF while the HUD types, else the scene answers
///     Enter/F/M/Esc with ui actions like main.ts.
///   • LOGIN — ONE login: Godot logs in, then hands its session to CEF (see
///     <see cref="Start"/>): gdCEF exposes no cookie manager, so the cookie is
///     written by a script on a page of the server's origin.
///
/// The node lives under the scene-tree ROOT, not under Main, and survives a scene
/// reload (back to the title): CEF can be initialised once per process only.
/// </summary>
public partial class HudOverlay : CanvasLayer
{
    public const string Channel = "hud_bridge";
    public const string HudPath = "static/client3d/hud.html?bridge=gdcef";
    private const int Fps = 60;

    /// <summary>Declared game actions that are background chatter of the HUD (logged once, no toast).</summary>
    private static readonly HashSet<string> QuietActions = new()
        { "closeInfo", "speak", "stopSpeech", "markResume", "sayBubble", "applyAudioPrefs", "applyScatterPrefs", "setChatBox" };

    public static HudOverlay? Instance { get; private set; }

    private GdCef? _cef;
    private TextureRect? _rect;
    private readonly MouseRouter _router = new();
    private readonly ScenePublisher _state = new();
    private readonly JsonObject _hudOwned = new();
    private readonly HashSet<string> _unimplemented = new();
    private JsonObject? _boot;
    private Uri? _server;
    private string? _token;
    private enum Phase { Idle, Cookie, Hud, Leaving }
    private Phase _phase = Phase.Idle;
    private bool _failed, _loaded, _hello;
    private TaskCompletionSource? _left;
    private Input.CursorShape _cursor = Input.CursorShape.Arrow;

    /// <summary>The HUD's ui state (hit rectangles, typing, overlay, menu) as last reported.</summary>
    public HudUi Ui { get; } = new();

    /// <summary>The HUD page is up and routes input.</summary>
    public bool Active => _loaded;

    /// <summary>The HUD owns the keyboard right now (the camera must ignore W/A/S/D).</summary>
    public bool KeysToHud => _loaded && HudRouting.KeysToHud(Ui);

    /// <summary>Scene handlers for game actions by name (Main fills them, and clears them when it leaves).</summary>
    public Dictionary<string, Action<JsonArray>> Handlers { get; } = new();

    /// <summary>
    /// The overlay, created once per process; null when gdCEF is not linked
    /// (native/link_cef.sh) or binds other method names than this client calls.
    /// </summary>
    public static HudOverlay? Ensure(SceneTree tree, Action<string> log)
    {
        if (Instance is not null && IsInstanceValid(Instance)) return Instance;
        if (!GdCef.Available)
        {
            log("hud: gdCEF is not linked (native/link_cef.sh) — running without the HUD");
            return null;
        }
        var missing = GdCef.MissingMethods();
        if (missing.Count > 0)
        {
            log("hud: the loaded gdCEF lacks " + string.Join(", ", missing) + " — running without the HUD");
            return null;
        }
        var overlay = new HudOverlay { Name = "HudOverlay", Layer = 5 };
        Instance = overlay;
        // Main is still being set up as a child of the root: add after this frame.
        tree.Root.CallDeferred(Node.MethodName.AddChild, overlay);
        return overlay;
    }

    public override void _Ready()
    {
        _rect = new TextureRect
        {
            Name = "HudView",
            MouseFilter = Control.MouseFilterEnum.Ignore,   // routing happens in _Input, never by GUI picking
            ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
            StretchMode = TextureRect.StretchModeEnum.Scale,
            TextureFilter = CanvasItem.TextureFilterEnum.Nearest,
            Material = new CanvasItemMaterial { BlendMode = CanvasItemMaterial.BlendModeEnum.PremultAlpha },
            Visible = false,
        };
        _rect.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        AddChild(_rect);

        _cef = GdCef.Create();
        _cef.Runtime.Name = "GdCEF";
        AddChild(_cef.Runtime);
        var dir = ProjectSettings.GlobalizePath("user://cef");
        var config = new Godot.Collections.Dictionary
        {
            // In-memory profile: the session cookie never reaches a disk cache (the
            // HUD's localStorage prefs do not persist either). root_cache_path still
            // takes CEF's lock files — under user://, not next to the binary.
            ["incognito"] = true,
            ["root_cache_path"] = dir,
            // Console messages of the page (the bridge's own warnings) land here at "info";
            // next to the exported binary (run.sh's logs/) so the build host can read them.
            ["log_file"] = CefLogFile(dir),
            ["log_severity"] = "info",
            ["locale"] = "en-US",
            // No DevTools port: it would let any local process read the session.
            ["remote_debugging_port"] = 0,
            ["enable_ad_block"] = false,
        };
        if (!_cef.Initialize(config))
        {
            _failed = true;
            Log($"hud: CEF failed to initialise ({_cef.RuntimeError.Trim()}) — running without the HUD; CEF log {dir}/debug.log");
            return;
        }
        Log($"hud: CEF initialised (log {dir}/debug.log)");
    }

    public override void _ExitTree()
    {
        if (Instance == this) Instance = null;
    }

    private string HudUrl => new Uri(_server!, HudPath).ToString();
    private string CookiePageUrl => new Uri(_server!, "health").ToString();

    /// <summary>
    /// Show the HUD for this server. With a session <paramref name="token"/> (Godot
    /// has logged in) CEF first opens <c>/health</c> — the smallest anonymous page of
    /// the server's ORIGIN — where a script writes the same <c>av_session</c> cookie
    /// and replaces the page with the HUD, which then boots already signed in: one
    /// login, one session for both channels. Without a token the HUD shows its own
    /// title screen.
    /// </summary>
    public void Start(Uri server, string? token)
    {
        if (_failed || _cef is null || _rect is null) return;
        _server = server;
        _token = token;
        _loaded = _hello = false;
        Ui.Reset();
        _router.Reset();
        _phase = token is null ? Phase.Hud : Phase.Cookie;
        var first = token is null ? HudUrl : CookiePageUrl;
        if (_cef.HasBrowser)
        {
            _cef.LoadUrl(first);
            return;
        }
        _rect.Size = GetViewport().GetVisibleRect().Size;   // the browser sizes its view from the rect
        var settings = new Godot.Collections.Dictionary
        {
            ["frame_rate"] = Fps,
            ["enable_ad_block"] = false,
            ["allow_downloads"] = false,
        };
        if (!_cef.CreateBrowser(first, _rect, settings))
        {
            _failed = true;
            Log($"hud: create_browser failed ({_cef.RuntimeError.Trim()}) — running without the HUD");
            return;
        }
        // Before the first page runs a script: messages to an unregistered method are dropped.
        if (!_cef.RegisterMethod(this, Channel)) Log("hud: register_method failed — the HUD cannot reach the scene");
        // gdCEF emits on_page_loaded(http_status, browser) — gdbrowser.cpp, emit_signal("on_page_loaded", httpStatusCode, this).
        _cef.ConnectBrowser(GdCef.SignalPageLoaded, Callable.From<int, GodotObject>((_, browser) => OnPageLoaded(browser)));
        _cef.ConnectBrowser(GdCef.SignalPageFailed, Callable.From<int, string, GodotObject>(OnPageFailed));
        // gdCEF puts the page's cursor on the rect, which ignores the mouse here; apply it globally instead.
        _cef.ConnectBrowser(GdCef.SignalCursorChanged, Callable.From<int, GodotObject>((shape, _) => _cursor = (Input.CursorShape)shape));
        _rect.Resized += () => { if (_cef.HasBrowser) _cef.Resize(_rect.Size); };
        Log($"hud: browser created ({_rect.Size.X}x{_rect.Size.Y}) → {first.Split('?')[0]}");
    }

    /// <summary>
    /// The cookie handoff: a NON-HttpOnly copy of the session cookie (page scripts
    /// cannot set HttpOnly), same name/path/SameSite as the server's, Secure on
    /// https, without an expiry (the browser is incognito anyway). The server's
    /// next Set-Cookie for it (sliding refresh) replaces it with an HttpOnly one.
    /// </summary>
    public static string CookieScript(string token, bool secure, string hudUrl)
    {
        var cookie = $"{Api.AnimaApi.SessionCookieName}={token}; path=/; samesite=lax" + (secure ? "; secure" : "");
        return $"document.cookie = {JsonSerializer.Serialize(cookie)}; location.replace({JsonSerializer.Serialize(hudUrl)});";
    }

    private void OnPageLoaded(GodotObject browser)
    {
        if (_cef is null || _rect is null) return;
        var url = _cef.Url;
        if (_phase == Phase.Cookie && url.StartsWith(CookiePageUrl, StringComparison.Ordinal))
        {
            _phase = Phase.Hud;
            _cef.ExecuteJavaScript(CookieScript(_token!, _server!.Scheme == Uri.UriSchemeHttps, HudUrl));
            Log("hud: session handed to CEF, opening the HUD");
            return;
        }
        if (_phase == Phase.Hud && url.Contains("/static/client3d/hud.html", StringComparison.Ordinal))
        {
            _loaded = true;
            _rect.Visible = true;
            _cef.Resize(_rect.Size);
            Log($"hud: page loaded ({url.Split('?')[0]}, view {_rect.Size.X}x{_rect.Size.Y})");
            PublishAll();
            _ = ProbeTransparencyLater();
            return;
        }
        if (_phase == Phase.Leaving && url.StartsWith("about:blank", StringComparison.Ordinal))
            _left?.TrySetResult();
    }

    private void OnPageFailed(int code, string message, GodotObject browser)
        => Log($"hud: page failed to load ({code} {message}) in phase {_phase}");

    /// <summary>
    /// Back to the title: the HUD page logs out through ITS cookie jar (so CEF drops
    /// the session cookie even after the server re-issued it HttpOnly — a later
    /// script could not overwrite that), then the view goes blank. At most 3 s.
    /// </summary>
    public async Task LeaveAsync()
    {
        _loaded = false;
        _hello = false;
        Ui.Reset();
        _router.Reset();
        if (_rect is not null) _rect.Visible = false;
        if (_cef is null || !_cef.HasBrowser) return;
        _phase = Phase.Leaving;
        _left = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        _cef.ExecuteJavaScript("fetch('/auth/logout', {method: 'POST', credentials: 'include'})"
                               + ".catch(() => {}).finally(() => location.replace('about:blank'));");
        await Task.WhenAny(_left.Task, Task.Delay(3000));
        _phase = Phase.Idle;
    }

    // ---- scene → HUD ------------------------------------------------------------

    /// <summary>Set a scene-owned game-state field; sent at once when it changed.</summary>
    public void SetState(string field, JsonNode? value)
    {
        _state.Set(field, value);
        if (_state.TakePatch() is { } patch) Send(HudProtocol.State(patch));
    }

    public void SetBoot(JsonObject boot)
    {
        _boot = (JsonObject)boot.DeepClone();
        Send(HudProtocol.Boot(_boot));
    }

    public void SendUi(string name, params JsonNode?[] args) => Send(HudProtocol.Ui(name, args));

    /// <summary>Everything the scene owns, unconditionally — for a HUD that has just (re)connected.</summary>
    private void PublishAll()
    {
        if (_boot is not null) Send(HudProtocol.Boot(_boot));
        if (_state.TakePatch(force: true) is { } patch) Send(HudProtocol.State(patch));
    }

    private void Send(string json)
    {
        if (_cef is null || !_cef.HasBrowser || _phase != Phase.Hud) return;
        _cef.Emit(Channel, json);
    }

    // ---- HUD → scene --------------------------------------------------------------

    /// <summary>
    /// gdCEF calls this for <c>window.godotMethods.hud_bridge(data)</c> (registered by
    /// name, hence the snake_case). <paramref name="data"/> is the page's JSON string.
    /// </summary>
    public void hud_bridge(Variant data)
    {
        var raw = data.VariantType == Variant.Type.String ? data.AsString() : Json.Stringify(data);
        var msg = HudProtocol.Parse(raw, out var reason);
        if (msg is null)
        {
            Log($"hud bridge: dropped invalid message ({reason}): {(raw.Length > 200 ? raw[..200] + "…" : raw)}");
            return;
        }
        if (!_hello)
        {
            // The page listens now (its first message proves it): repeat what it may have missed.
            _hello = true;
            PublishAll();
        }
        switch (msg.Kind)
        {
            case "hud":
                Ui.Apply(msg.Patch!);
                break;
            case "state":
                var (accepted, dropped) = HudProtocol.SplitOwned(msg.Patch!);
                if (dropped.Count > 0) Log("hud bridge: dropped state fields not owned by the HUD: " + string.Join(", ", dropped));
                foreach (var (key, value) in accepted) _hudOwned[key] = value?.DeepClone();
                break;
            case "action":
                Dispatch(msg.Name!, msg.Args!);
                break;
        }
    }

    private void Dispatch(string name, JsonArray args)
    {
        if (Handlers.TryGetValue(name, out var handler))
        {
            try { handler(args); }
            catch (Exception e) { Log($"hud: action {name} failed: {e.Message}"); }
            return;
        }
        if (!_unimplemented.Add(name)) return;
        Log($"hud: action '{name}' is not implemented in the native spike");
        if (!QuietActions.Contains(name))
            SendUi("toast", JsonValue.Create($"Not available in the native client yet: {name}"), JsonValue.Create(false));
    }

    // ---- input --------------------------------------------------------------------

    /// <summary>View px per viewport px (CSS px per window px, see <see cref="HudRouting"/>).</summary>
    private double CssPerWindowPx
    {
        get
        {
            // Before the first full paint the texture is a 2x2 placeholder: assume 1.
            var tex = _cef!.TextureSize;
            return tex.X > 2 && _rect!.Size.X > 0 ? tex.X / (double)_rect.Size.X : 1.0;
        }
    }

    private bool Over(Vector2 pos) => HudRouting.OverHud(Ui, pos.X - _rect!.GlobalPosition.X, pos.Y - _rect.GlobalPosition.Y, CssPerWindowPx);

    private void MoveTo(Vector2 pos)
    {
        double s = CssPerWindowPx;
        _cef!.MouseMoved((int)Math.Floor((pos.X - _rect!.GlobalPosition.X) * s), (int)Math.Floor((pos.Y - _rect.GlobalPosition.Y) * s));
    }

    public override void _Input(InputEvent e)
    {
        if (!_loaded || _cef is null || _rect is null) return;
        switch (e)
        {
            case InputEventMouseMotion mm:
            {
                MoveTo(mm.Position);   // CEF always sees the pointer (hover)
                bool over = Over(mm.Position);
                Input.SetDefaultCursorShape(over ? _cursor : Input.CursorShape.Arrow);
                if (!_router.Motion(over).Scene) Handled();
                break;
            }
            case InputEventMouseButton mb when mb.ButtonIndex is MouseButton.WheelUp or MouseButton.WheelDown
                                                                 or MouseButton.WheelLeft or MouseButton.WheelRight:
            {
                if (MouseRouter.Wheel(Over(mb.Position)) != InputTarget.Hud) break;
                if (mb.Pressed)
                {
                    MoveTo(mb.Position);
                    int notches = (int)Math.Max(1, Math.Round(5 * (mb.Factor > 0 ? mb.Factor : 1)));
                    int v = mb.ButtonIndex == MouseButton.WheelUp ? notches : mb.ButtonIndex == MouseButton.WheelDown ? -notches : 0;
                    int h = mb.ButtonIndex == MouseButton.WheelLeft ? notches : mb.ButtonIndex == MouseButton.WheelRight ? -notches : 0;
                    _cef.Wheel(v, h, mb.ShiftPressed, mb.CtrlPressed, mb.AltPressed);
                }
                Handled();
                break;
            }
            case InputEventMouseButton mb:
            {
                bool over = Over(mb.Position);
                var target = mb.Pressed ? _router.Press(over) : _router.Release(over);
                if (target != InputTarget.Hud) break;
                MoveTo(mb.Position);
                _cef.MouseButton(mb.ButtonIndex, mb.Pressed);
                Handled();
                break;
            }
            case InputEventKey k:
            {
                if (HudRouting.KeysToHud(Ui))
                {
                    int code = k.Unicode != 0 ? (int)k.Unicode : (int)k.Keycode;
                    _cef.Key(code, k.Pressed, k.ShiftPressed, k.AltPressed, k.CtrlPressed || k.MetaPressed);
                    Handled();
                }
                else if (k.Pressed && !k.Echo
                         && HudRouting.SceneKeyAction(k.Keycode, Ui.MenuOpen, k.CtrlPressed || k.AltPressed || k.MetaPressed) is { } action)
                {
                    SendUi(action);
                    Handled();
                }
                break;
            }
        }
    }

    private void Handled() => GetViewport().SetInputAsHandled();

    // ---- transparency probe ---------------------------------------------------------

    /// <summary>
    /// 3 s after the page loaded: the painted alpha at a point outside every HUD
    /// surface (expected 0 = the page background is transparent) and in the middle
    /// of the first surface — one log line the user can quote.
    /// </summary>
    private async Task ProbeTransparencyLater()
    {
        await ToSignal(GetTree().CreateTimer(3.0), SceneTreeTimer.SignalName.Timeout);
        if (!_loaded || _cef is null) return;
        var size = _cef.TextureSize;
        if (size.X <= 0 || size.Y <= 0)
        {
            Log("hud: transparency probe: nothing painted yet");
            return;
        }
        var rects = Ui.HitRects;
        (int X, int Y)? outside = null;
        for (int y = size.Y / 2; outside is null && y < size.Y; y += 23)
            for (int x = size.X / 2; x < size.X; x += 23)
                if (!HudRouting.PointInRects(rects, x, y)) { outside = (x, y); break; }
        var line = "hud: transparency probe:";
        if (outside is { } o)
        {
            var c = _cef.PixelAt(o.X, o.Y);
            line += $" ({o.X},{o.Y}) outside every surface alpha={c.A:0.###}";
            if (c.A > 0.99f) line += " — OPAQUE page background (see the S4 report: background_color patch)";
        }
        if (rects.Count > 0)
        {
            var r = rects[0];
            int cx = (int)(r.X + r.W / 2), cy = (int)(r.Y + r.H / 2);
            if (cx >= 0 && cy >= 0 && cx < size.X && cy < size.Y)
                line += $"; ({cx},{cy}) inside the first surface alpha={_cef.PixelAt(cx, cy).A:0.###}";
        }
        Log(line + $"; {rects.Count} surfaces, view {size.X}x{size.Y}");
    }

    private static void Log(string line) => GD.Print("[native] " + line);

    /// <summary>
    /// <c>&lt;binary dir&gt;/logs/cef-debug.log</c> in an export (the folder run.sh logs into, on the
    /// shared build output), <c>user://cef/debug.log</c> when started from the editor.
    /// </summary>
    private static string CefLogFile(string userDir)
    {
        if (OS.HasFeature("editor")) return userDir + "/debug.log";
        var logs = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(OS.GetExecutablePath()) ?? ".", "logs");
        try { System.IO.Directory.CreateDirectory(logs); }
        catch (System.Exception) { return userDir + "/debug.log"; }
        return System.IO.Path.Combine(logs, "cef-debug.log");
    }
}
