using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.Json.Nodes;
using AnimaNative.Hud;
using Godot;

namespace AnimaNative.Check;

/// <summary>Drive HudOverlay._Input against the gdCEF method boundary without starting Chromium.</summary>
public partial class HudInputProbe : HudOverlay
{
    public override void _Ready() { SetProcess(false); SetProcessInput(false); }

    public partial class Browser : Node
    {
        public readonly List<string> Messages = new();
        public readonly List<(int Code, bool Pressed)> Keys = new();
        public bool js_emit(string channel, string data)
        {
            if (channel != Channel) throw new InvalidOperationException("wrong HUD channel");
            Messages.Add(data); return true;
        }
        public void set_key_pressed(int code, bool pressed, bool shift, bool alt, bool ctrl)
            => Keys.Add((code, pressed));
    }

    public static int Run()
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var hud = new HudInputProbe();
        var browser = new Browser();
        var rect = new TextureRect();
        var cef = (GdCef)Activator.CreateInstance(typeof(GdCef), flags, null, new object[] { browser }, null)!;
        typeof(GdCef).GetField("_browser", flags)!.SetValue(cef, browser);
        var tree = (SceneTree)Engine.GetMainLoop();
        tree.Root.AddChild(hud);
        void Set(string name, object value) => typeof(HudOverlay).GetField(name, flags)!.SetValue(hud, value);
        Set("_cef", cef); Set("_rect", rect); Set("_loaded", true);
        var phase = typeof(HudOverlay).GetField("_phase", flags)!;
        phase.SetValue(hud, Enum.Parse(phase.FieldType, "Hud"));
        int n = 0;
        void Is(string label, bool ok) { n++; if (!ok) throw new InvalidOperationException("hud text: " + label); }
        void KeyEvent(Key key, uint unicode, bool pressed, bool ctrl = false, bool alt = false, bool meta = false, bool echo = false)
        {
            using var e = new InputEventKey { Keycode = key, PhysicalKeycode = key, Unicode = unicode,
                Pressed = pressed, CtrlPressed = ctrl, AltPressed = alt, MetaPressed = meta, Echo = echo };
            hud._Input(e);
        }
        try
        {
            hud.Ui.Apply(new JsonObject { ["typing"] = true });
            KeyEvent(Key.Period, '.', true); KeyEvent(Key.Period, 0, false);
            Is("older v4 page keeps CEF keys without text capability", browser.Keys.Count == 2 && browser.Messages.Count == 0);
            browser.Keys.Clear();
            hud.Ui.Apply(new JsonObject { ["textInput"] = true });
            KeyEvent(Key.Period, '.', true);
            Is("typing period emits text", browser.Messages.Count == 1
                && JsonNode.Parse(browser.Messages[0])!["value"]!.GetValue<string>() == "."
                && JsonNode.Parse(browser.Messages[0])!["kind"]!.GetValue<string>() == "text");
            Is("typing period bypasses set_key_pressed", browser.Keys.Count == 0);
            KeyEvent(Key.Period, '.', true, echo: true);
            Is("key repeat inserts again", browser.Messages.Count == 2);
            hud.Ui.Apply(new JsonObject { ["typing"] = false, ["overlayOpen"] = true });
            KeyEvent(Key.Period, 0, false);
            Is("release stays suppressed after typing ends and loses Unicode", browser.Keys.Count == 0);
            KeyEvent(Key.Period, '.', true); KeyEvent(Key.Period, 0, false);
            Is("not typing keeps old CEF path", browser.Keys.Count == 2 && browser.Messages.Count == 2
                && browser.Keys[0] == (46, true));
            hud.Ui.Apply(new JsonObject { ["typing"] = true });
            browser.Keys.Clear();
            foreach (var key in new[] { Key.Enter, Key.Backspace, Key.Delete, Key.Tab, Key.Left, Key.Home, Key.End, Key.Escape, Key.F2 })
            { KeyEvent(key, 0, true); KeyEvent(key, 0, false); }
            Is("editing and navigation remain on CEF", browser.Keys.Count == 18);
            foreach (var key in new[] { Key.A, Key.C, Key.V, Key.X, Key.Z })
            { KeyEvent(key, (uint)key, true, ctrl: true); KeyEvent(key, 0, false, ctrl: true); }
            Is("Ctrl shortcuts remain on CEF", browser.Keys.Count == 28);
            KeyEvent(Key.Q, '@', true, ctrl: true, alt: true);
            KeyEvent(Key.Q, 0, false);
            Is("AltGr text and release bypass CEF", browser.Keys.Count == 28 && browser.Messages.Count == 3);
            KeyEvent(Key.F11, 0, true);
            Is("F11 stays with window", browser.Keys.Count == 28);
            hud.Ui.Apply(new JsonObject { ["textInput"] = false });
            KeyEvent(Key.Space, ' ', true); KeyEvent(Key.Space, 0, false);
            Is("typing in a checkbox or select keeps CEF keys", browser.Keys.Count == 30 && browser.Messages.Count == 3);
            hud.Ui.Apply(new JsonObject { ["typing"] = false, ["overlayOpen"] = false });
            KeyEvent(Key.Period, '.', true);
            Is("scene retains keys without HUD ownership", browser.Keys.Count == 30 && browser.Messages.Count == 3);
            return n;
        }
        finally { hud.Free(); browser.Free(); rect.Free(); }
    }
}
