using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Hud;

/// <summary>
/// The ONE place that talks to gdCEF (github.com/Lecrapouille/gdcef, v0.21.0-godot4,
/// CEF 156). gdCEF is a GDExtension without C# bindings, so every call goes
/// through <see cref="GodotObject.Call"/> on the two engine classes it
/// registers: <c>GdCEF</c> (the CEF runtime, one per process — CEF cannot be
/// initialised a second time after shutdown) and <c>GdBrowserView</c> (one
/// off-screen browser painting into a TextureRect's texture).
///
/// Names are the BOUND ones of that release, read from its sources
/// (<c>gdbrowser.cpp</c> <c>_bind_methods</c>) and verified against the loaded
/// library by <c>--check</c> (<see cref="MissingMethods"/>). Two differ from its
/// API.md: the JS event sender is <c>js_emit</c> (not <c>emit_js</c>), and
/// <c>register_method</c> takes (object, method name), not a Callable.
/// </summary>
public sealed class GdCef
{
    public const string CefClass = "GdCEF";
    public const string BrowserClass = "GdBrowserView";

    /// <summary>Every GdCEF method this wrapper calls.</summary>
    public static readonly string[] CefMethods = { "initialize", "create_browser", "get_error", "is_alive" };

    /// <summary>Every GdBrowserView method this wrapper calls.</summary>
    public static readonly string[] BrowserMethods =
    {
        "register_method", "js_emit", "execute_javascript", "load_url", "get_url", "resize", "get_error",
        "set_mouse_moved", "set_mouse_left_down", "set_mouse_left_up", "set_mouse_right_down", "set_mouse_right_up",
        "set_mouse_middle_down", "set_mouse_middle_up", "set_mouse_wheel_vertical", "set_mouse_wheel_horizontal",
        "set_key_pressed", "get_pixel_color", "get_texture",
    };

    /// <summary>Browser signals this client connects to (gdbrowser.cpp <c>ADD_SIGNAL</c>).</summary>
    public const string SignalPageLoaded = "on_page_loaded";            // (browser)
    public const string SignalPageFailed = "on_page_failed_loading";    // (err_code, err_msg, browser)
    public const string SignalCursorChanged = "on_cursor_changed";      // (cursor_shape: DisplayServer.CursorShape, browser)

    /// <summary>The extension is loaded (native/cef_artifacts linked, see link_cef.sh).</summary>
    public static bool Available => ClassDB.ClassExists(CefClass) && ClassDB.ClassExists(BrowserClass);

    /// <summary>Every browser signal this client connects to.</summary>
    public static readonly string[] BrowserSignals = { SignalPageLoaded, SignalPageFailed, SignalCursorChanged };

    /// <summary>"Class.method" / "Class::signal" for every call or signal of this wrapper the loaded library does not bind.</summary>
    public static List<string> MissingMethods()
        => CefMethods.Where(m => !ClassDB.ClassHasMethod(CefClass, m)).Select(m => $"{CefClass}.{m}")
            .Concat(BrowserMethods.Where(m => !ClassDB.ClassHasMethod(BrowserClass, m)).Select(m => $"{BrowserClass}.{m}"))
            .Concat(BrowserSignals.Where(n => !ClassDB.ClassHasSignal(BrowserClass, n)).Select(n => $"{BrowserClass}::{n}"))
            .ToList();

    /// <summary>The <c>GdCEF</c> node. It pumps CEF in its own <c>_process</c>, so it must stay in the tree.</summary>
    public Node Runtime { get; }
    private GodotObject? _browser;

    private GdCef(Node runtime) => Runtime = runtime;

    /// <summary>A fresh <c>GdCEF</c> node, not yet initialised. Requires <see cref="Available"/>.</summary>
    public static GdCef Create() => new((Node)ClassDB.Instantiate(CefClass).AsGodotObject());

    public bool Initialize(Godot.Collections.Dictionary config) => Runtime.Call("initialize", config).AsBool();
    public string RuntimeError => Runtime.Call("get_error").AsString();
    public bool HasBrowser => _browser is not null && GodotObject.IsInstanceValid(_browser);

    /// <summary>
    /// <c>create_browser(url, texture_rect, settings)</c>: the browser sizes its view
    /// to the rect, paints into the rect's texture (RGBA8, alpha kept) and becomes a
    /// child node of the runtime. Returns false (see <see cref="RuntimeError"/>) on failure.
    /// </summary>
    public bool CreateBrowser(string url, TextureRect rect, Godot.Collections.Dictionary settings)
    {
        var b = Runtime.Call("create_browser", url, rect, settings);
        _browser = b.VariantType == Variant.Type.Object ? b.AsGodotObject() : null;
        return HasBrowser;
    }

    public void ConnectBrowser(string signal, Callable callable) => _browser!.Connect(signal, callable);

    /// <summary>JS → Godot: <c>window.godotMethods.&lt;method&gt;(data)</c> calls <paramref name="target"/>.<paramref name="method"/>(data).</summary>
    public bool RegisterMethod(GodotObject target, string method) => _browser!.Call("register_method", target, method).AsBool();

    /// <summary>Godot → JS: <c>window.godotEvents.on(event, fn)</c> receives <paramref name="data"/> (a String arrives as a JS string).</summary>
    public bool Emit(string eventName, string data) => _browser!.Call("js_emit", eventName, data).AsBool();

    public void ExecuteJavaScript(string code) => _browser!.Call("execute_javascript", code);
    public void LoadUrl(string url) => _browser!.Call("load_url", url);
    public string Url => _browser!.Call("get_url").AsString();
    public void Resize(Vector2 size) => _browser!.Call("resize", size);

    /// <summary>Pointer position in the browser's view pixels (= CSS px: gdCEF reports device scale 1).</summary>
    public void MouseMoved(int x, int y) => _browser!.Call("set_mouse_moved", x, y);

    public void MouseButton(MouseButton button, bool down)
    {
        string? method = button switch
        {
            Godot.MouseButton.Left => down ? "set_mouse_left_down" : "set_mouse_left_up",
            Godot.MouseButton.Right => down ? "set_mouse_right_down" : "set_mouse_right_up",
            Godot.MouseButton.Middle => down ? "set_mouse_middle_down" : "set_mouse_middle_up",
            _ => null,
        };
        if (method is not null) _browser!.Call(method);
    }

    /// <summary>Wheel notches (+ = up/left); gdCEF scrolls 10 px per unit.</summary>
    public void Wheel(int vertical, int horizontal, bool shift, bool ctrl, bool alt)
    {
        if (vertical != 0) _browser!.Call("set_mouse_wheel_vertical", vertical, shift, ctrl, alt);
        if (horizontal != 0) _browser!.Call("set_mouse_wheel_horizontal", horizontal, shift, ctrl, alt);
    }

    /// <summary>
    /// <c>set_key_pressed(key, pressed, shift, alt, ctrl)</c>; <paramref name="key"/> is the
    /// character when there is one, else the Godot keycode (gdCEF's demos do the same).
    /// </summary>
    public void Key(int key, bool pressed, bool shift, bool alt, bool ctrl)
        => _browser!.Call("set_key_pressed", key, pressed, shift, alt, ctrl);

    /// <summary>The painted pixel at view coordinates (gdCEF's copy of CEF's BGRA buffer as RGBA, premultiplied alpha).</summary>
    public Color PixelAt(int x, int y) => _browser!.Call("get_pixel_color", x, y).AsColor();

    public Vector2I TextureSize
    {
        get
        {
            var t = _browser!.Call("get_texture");
            return t.VariantType == Variant.Type.Object && t.AsGodotObject() is Texture2D tex
                ? new Vector2I(tex.GetWidth(), tex.GetHeight()) : Vector2I.Zero;
        }
    }
}
