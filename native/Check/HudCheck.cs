using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AnimaNative.Hud;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>, HUD part (Task S4): the pure parts of the native HUD with
/// hand-derived cases — <c>pointInRects</c> incl. the CSS/window scale, the
/// routing decision table, message validation, the outgoing message strings,
/// figure picking, the cookie handoff script — plus two drift guards: the name
/// lists against the TypeScript sources, and (when gdCEF is linked) every
/// method this client calls against the loaded library.
/// </summary>
public static class HudCheck
{
    public static string Run(FixtureSource source)
    {
        int rects = CheckRects();
        int routes = CheckRouting();
        int keys = CheckKeys();
        int messages = CheckMessages();
        int picks = CheckPick();
        CheckCookieScript();
        CheckNameLists(source);
        var gdcef = CheckBinding();
        return $"rect_cases={rects} route_cases={routes} key_cases={keys} message_cases={messages} pick_cases={picks} "
               + $"name_lists=4 gdcef={gdcef}";
    }

    // Two surfaces: A = chat panel x∈[10,310) y∈[20,220); B = rail x∈[1500,1600) y∈[0,900).
    private static readonly HudRect A = new(10, 20, 300, 200), B = new(1500, 0, 100, 900);

    private static int CheckRects()
    {
        var r = new[] { A, B };
        var cases = new (double X, double Y, bool In, string Why)[]
        {
            (10, 20, true, "top-left corner is inside"),
            (309.9, 219.9, true, "just before the right/bottom edge"),
            (310, 100, false, "right edge x = 10 + 300 is outside"),
            (100, 220, false, "bottom edge y = 20 + 200 is outside"),
            (5, 5, false, "left of and above A"),
            (1599, 899, true, "last pixel of B"),
            (1600, 10, false, "right edge of B"),
        };
        foreach (var c in cases)
            Expect($"pointInRects ({c.X},{c.Y}) — {c.Why}", HudRouting.PointInRects(r, c.X, c.Y) == c.In, $"got {!c.In}");
        Expect("no rects → nothing inside", !HudRouting.PointInRects(Array.Empty<HudRect>(), 0, 0), "inside");

        // CSS px = window px × cssPerWindowPx. A page laid out at DPR 2 on a 3200 px wide
        // window has 1600 CSS px: window (619, 439) → CSS (309.5, 219.5) inside A;
        // window (620, 100) → CSS (310, 50) outside A; window (3100, 10) → CSS (1550, 5) inside B.
        var ui = Ui(rects: r);
        Expect("scale 0.5: (619,439) → (309.5,219.5) in A", HudRouting.OverHud(ui, 619, 439, 0.5), "outside");
        Expect("scale 0.5: (620,100) → (310,50) outside", !HudRouting.OverHud(ui, 620, 100, 0.5), "inside");
        Expect("scale 0.5: (3100,10) → (1550,5) in B", HudRouting.OverHud(ui, 3100, 10, 0.5), "outside");
        Expect("scale 1: (620,100) outside A, left of B", !HudRouting.OverHud(ui, 620, 100, 1), "inside");
        // An open overlay owns the whole window, rects or not.
        Expect("overlayOpen: (5,5) belongs to the HUD", HudRouting.OverHud(Ui(overlay: true), 5, 5, 1), "scene");
        return cases.Length + 6;
    }

    private static int CheckRouting()
    {
        int n = 0;
        void Is<T>(string what, T got, T want) { n++; Expect(what, Equals(got, want), $"got {got}, want {want}"); }

        // 1. Press on a panel: CEF captures until release, the scene sees nothing of it.
        var m = new MouseRouter();
        Is("hover inside, no button → CEF only", m.Motion(true), (true, false));
        Is("hover outside, no button → both (hover + camera)", m.Motion(false), (true, true));
        Is("press inside → HUD", m.Press(true), InputTarget.Hud);
        Is("drag leaves the panel → still CEF only", m.Motion(false), (true, false));
        Is("release outside → HUD (captured)", m.Release(false), InputTarget.Hud);
        Is("after release: outside → both again", m.Motion(false), (true, true));

        // 2. Camera drag that crosses a panel: the scene keeps it.
        Is("press outside → scene", m.Press(false), InputTarget.Scene);
        Is("drag over the panel → scene keeps orbiting (CEF hovers)", m.Motion(true), (true, true));
        Is("second button inside while dragging → still scene", m.Press(true), InputTarget.Scene);
        Is("first release inside → scene", m.Release(true), InputTarget.Scene);
        Is("one button still down → captured", m.Capture, (InputTarget?)InputTarget.Scene);
        Is("last release inside → scene", m.Release(true), InputTarget.Scene);
        Is("capture cleared", m.Capture, (InputTarget?)null);

        // 3. Wheel by position, no capture.
        Is("wheel inside → HUD", MouseRouter.Wheel(true), InputTarget.Hud);
        Is("wheel outside → scene", MouseRouter.Wheel(false), InputTarget.Scene);

        // 4. The table of the plan: inside rect / outside / overlayOpen / typing.
        var plain = Ui(rects: new[] { A });
        Is("inside rect → HUD", MouseRouter.Wheel(HudRouting.OverHud(plain, 50, 50, 1)), InputTarget.Hud);
        Is("outside → scene", MouseRouter.Wheel(HudRouting.OverHud(plain, 800, 500, 1)), InputTarget.Scene);
        Is("overlayOpen, outside rect → HUD", MouseRouter.Wheel(HudRouting.OverHud(Ui(rects: new[] { A }, overlay: true), 800, 500, 1)),
           InputTarget.Hud);
        Is("typing does not move the pointer rule (outside → scene)",
           MouseRouter.Wheel(HudRouting.OverHud(Ui(rects: new[] { A }, typing: true), 800, 500, 1)), InputTarget.Scene);
        return n;
    }

    private static int CheckKeys()
    {
        int n = 0;
        void Is<T>(string what, T got, T want) { n++; Expect(what, Equals(got, want), $"got {got}, want {want}"); }
        Is("typing → keys to CEF", HudRouting.KeysToHud(Ui(typing: true)), true);
        Is("overlay open → keys to CEF", HudRouting.KeysToHud(Ui(overlay: true)), true);
        Is("menu open alone → keys to the scene (M/Esc close it)", HudRouting.KeysToHud(Ui(menu: true)), false);
        Is("nothing → keys to the scene", HudRouting.KeysToHud(Ui()), false);
        Is("F → openChat", HudRouting.SceneKeyAction(Key.F, false, false), "openChat");
        Is("Enter → openChat", HudRouting.SceneKeyAction(Key.Enter, false, false), "openChat");
        Is("keypad Enter → openChat", HudRouting.SceneKeyAction(Key.KpEnter, false, false), "openChat");
        Is("M → toggleMenu", HudRouting.SceneKeyAction(Key.M, false, false), "toggleMenu");
        Is("M with the menu open → toggleMenu (closes it)", HudRouting.SceneKeyAction(Key.M, true, false), "toggleMenu");
        Is("Esc, menu open → closeMenu", HudRouting.SceneKeyAction(Key.Escape, true, false), "closeMenu");
        Is("Esc, menu closed → nothing", HudRouting.SceneKeyAction(Key.Escape, false, false), (string?)null);
        Is("Ctrl+M → nothing (system)", HudRouting.SceneKeyAction(Key.M, false, true), (string?)null);
        Is("W → nothing (camera)", HudRouting.SceneKeyAction(Key.W, false, false), (string?)null);
        return n;
    }

    private static int CheckMessages()
    {
        int n = 0;
        void Rejects(string raw, string why)
        {
            n++;
            Expect($"rejects {why}", HudProtocol.Parse(raw, out var reason) is null && reason is not null, raw);
        }
        Rejects("{not json", "invalid JSON");
        Rejects("[1]", "an array");
        Rejects("\"hud\"", "a string");
        Rejects("{\"kind\":\"hud\",\"patch\":{}}", "a missing v");
        Rejects("{\"v\":2,\"kind\":\"hud\",\"patch\":{}}", "v = 2");
        Rejects("{\"v\":\"1\",\"kind\":\"hud\",\"patch\":{}}", "v = \"1\" (bridge.ts compares with ===)");
        Rejects("{\"v\":1,\"patch\":{}}", "a missing kind");
        Rejects("{\"v\":1,\"kind\":\"nope\"}", "an unknown kind");
        Rejects("{\"v\":1,\"kind\":\"hud\",\"patch\":[1]}", "a non-object patch");
        Rejects("{\"v\":1,\"kind\":\"action\",\"name\":\"nope\",\"args\":[]}", "an undeclared action");
        Rejects("{\"v\":1,\"kind\":\"action\",\"name\":\"toString\",\"args\":[]}", "an inherited property name");
        Rejects("{\"v\":1,\"kind\":\"action\",\"name\":\"zoomTo\",\"args\":\"Kira\"}", "args that are not an array");
        Rejects("{\"v\":1,\"kind\":\"ui\",\"name\":\"openChat\",\"args\":[]}", "a scene → HUD kind sent by the HUD");

        // Accepted: v as 1.0 is still === 1 in JS.
        var action = HudProtocol.Parse("{\"v\":1.0,\"kind\":\"action\",\"name\":\"zoomTo\",\"args\":[\"Kira\"]}", out _);
        n++;
        Expect("zoomTo accepted", action is { Kind: "action", Name: "zoomTo" } && action.Args!.Count == 1
                                  && action.Args[0]!.GetValue<string>() == "Kira", "rejected");

        // The HUD patch updates the routing state (hand: one rect, typing on, menu untouched).
        var hud = HudProtocol.Parse("{\"v\":1,\"kind\":\"hud\",\"patch\":{\"typing\":true,\"overlayOpen\":false,"
                                    + "\"hitRects\":[{\"x\":10,\"y\":20,\"w\":300,\"h\":200},{\"x\":\"bad\"}]}}", out _);
        var ui = new HudUi();
        ui.Apply(hud!.Patch!);
        n++;
        Expect("hud patch applied", ui.Typing && !ui.OverlayOpen && !ui.MenuOpen && ui.HitRects.Count == 1 && ui.HitRects[0] == A,
               $"typing={ui.Typing} rects={ui.HitRects.Count}");
        ui.Apply(JsonNode.Parse("{\"menuOpen\":true,\"typing\":\"yes\"}")!.AsObject());
        n++;
        Expect("shallow merge, wrong types ignored", ui.MenuOpen && ui.Typing && ui.HitRects.Count == 1, "merge broke");

        // receiveState(patch, HUD_OWNED_FIELDS): a mixed patch keeps the owned key, drops the rest.
        var state = HudProtocol.Parse("{\"v\":1,\"kind\":\"state\",\"patch\":{\"movementLocked\":true,\"mode\":\"embodied\"}}", out _);
        var (accepted, dropped) = HudProtocol.SplitOwned(state!.Patch!);
        n++;
        Expect("owned field kept, scene field dropped",
               accepted.Count == 1 && accepted["movementLocked"]!.GetValue<bool>() && dropped.SequenceEqual(new[] { "mode" }),
               accepted.ToJsonString());

        // Outgoing wire strings, written out by hand.
        n += 3;
        Expect("ui openChat", HudProtocol.Ui("openChat") == "{\"v\":1,\"kind\":\"ui\",\"name\":\"openChat\",\"args\":[]}",
               HudProtocol.Ui("openChat"));
        Expect("ui toast", HudProtocol.Ui("toast", JsonValue.Create("Hi"), JsonValue.Create(false))
                           == "{\"v\":1,\"kind\":\"ui\",\"name\":\"toast\",\"args\":[\"Hi\",false]}", "toast differs");
        bool threw = false;
        try { HudProtocol.Ui("zoomTo"); } catch (ArgumentException) { threw = true; }
        Expect("ui refuses a game action name", threw, "sent");

        // statePublisher: deltas only, force repeats everything, HUD-owned fields cannot be set.
        var pub = new ScenePublisher();
        pub.Set("clock", "Day 1, 08:00");
        pub.Set("selected", null);
        n += 5;
        Expect("first patch carries both", pub.TakePatch()?.ToJsonString() == "{\"clock\":\"Day 1, 08:00\",\"selected\":null}",
               pub.TakePatch()?.ToJsonString() ?? "null");
        pub.Set("clock", "Day 1, 08:00");
        Expect("unchanged → no patch", pub.TakePatch() is null, "patch sent");
        pub.Set("clock", "Day 1, 08:01");
        Expect("changed clock only", pub.TakePatch()?.ToJsonString() == "{\"clock\":\"Day 1, 08:01\"}", "differs");
        Expect("force repeats all", pub.TakePatch(force: true)?.ToJsonString() == "{\"clock\":\"Day 1, 08:01\",\"selected\":null}",
               "differs");
        threw = false;
        try { pub.Set("partyLeader", "x"); } catch (ArgumentException) { threw = true; }
        Expect("HUD-owned field refused on the scene side", threw, "accepted");

        n++;
        Expect("state message", HudProtocol.State(JsonNode.Parse("{\"mode\":\"overview\"}")!.AsObject())
                                == "{\"v\":1,\"kind\":\"state\",\"patch\":{\"mode\":\"overview\"}}", "differs");
        var boot = HudProtocol.BootReady();
        n++;
        Expect("boot ready: 100 %, 6 stages incl. visible",
               boot["state"]!["percent"]!.GetValue<int>() == 100 && boot["state"]!["stages"]!.AsArray().Count == 6
               && boot["state"]!["stages"]!.AsArray().Any(s => s!.GetValue<string>() == "visible"), boot.ToJsonString());
        return n;
    }

    private static int CheckPick()
    {
        // Figure P: feet (100,400) → head (100,300), 100 px tall → tolerance max(10, 30) = 30 px.
        // Figure Q: feet (130,400) → head (130,380), 20 px tall (far) → tolerance 10 px.
        var p = new FigurePick.Candidate("P", new Vector2(100, 400), new Vector2(100, 300), 10);
        var q = new FigurePick.Candidate("Q", new Vector2(130, 400), new Vector2(130, 380), 50);
        var both = new[] { p, q };
        int n = 0;
        void Is(string what, string? got, string? want) { n++; Expect(what, got == want, $"got {got ?? "null"}"); }
        Is("on P's body", FigurePick.Pick(both, new Vector2(100, 350)), "P");
        Is("29 px beside P, 1 px beside Q → Q (nearer)", FigurePick.Pick(both, new Vector2(129, 390)), "Q");
        Is("25 px left of P → P", FigurePick.Pick(both, new Vector2(75, 350)), "P");
        Is("31 px left of P → nothing", FigurePick.Pick(both, new Vector2(69, 350)), null);
        Is("above P's head by 20 px → P (distance to the end point 20 ≤ 30)", FigurePick.Pick(both, new Vector2(100, 280)), "P");
        // Equal distance 5 px to both: the nearer figure (depth 10) wins.
        var r = new FigurePick.Candidate("R", new Vector2(110, 400), new Vector2(110, 300), 40);
        Is("tie → nearer to the camera", FigurePick.Pick(new[] { r, p }, new Vector2(105, 350)), "P");
        Is("nothing to pick", FigurePick.Pick(Array.Empty<FigurePick.Candidate>(), new Vector2(0, 0)), null);
        return n;
    }

    private static void CheckCookieScript()
    {
        var got = HudOverlay.CookieScript("tok-EN_1", false, "http://h:8000/static/client3d/hud.html?bridge=gdcef");
        Expect("cookie script (http)",
               got == "document.cookie = \"av_session=tok-EN_1; path=/; samesite=lax\"; "
                      + "location.replace(\"http://h:8000/static/client3d/hud.html?bridge=gdcef\");", got);
        var secure = HudOverlay.CookieScript("t", true, "https://h/static/client3d/hud.html?bridge=gdcef");
        Expect("cookie script (https) carries Secure", secure.StartsWith("document.cookie = \"av_session=t; path=/; samesite=lax; secure\";"),
               secure);
        // A hostile value cannot leave the string literal (JSON escaping).
        var hostile = HudOverlay.CookieScript("a\";alert(1);//", false, "http://h/");
        Expect("token is escaped", hostile.Contains("av_session=a\\u0022;alert(1);//"), hostile);

        // Back to the title / the next handoff: the browser logs out only a session it really holds.
        var end = HudOverlay.EndSessionScript;
        int status = end.IndexOf("fetch('/auth/status'", StringComparison.Ordinal);
        int guard = end.IndexOf("s.authenticated === true", StringComparison.Ordinal);
        int logout = end.IndexOf("fetch('/auth/logout', {method: 'POST'", StringComparison.Ordinal);
        Expect("end-session order: status, authenticated guard, logout", status == 0 && guard > status && logout > guard,
               $"{status}/{guard}/{logout}: {end}");
        var handoff = HudOverlay.HandoffScript("tok-EN_1", false, "http://h:8000/static/client3d/hud.html?bridge=gdcef");
        Expect("handoff = end session, then the cookie script",
               handoff == end + ".catch(() => 'unreachable').then(() => { " + got + " });", handoff);
        Expect("leave = end session, then a blank page naming the outcome",
               HudOverlay.LeaveScript == end + ".catch(() => 'unreachable').then(o => location.replace('about:blank#' + o));",
               HudOverlay.LeaveScript);
    }

    /// <summary>The C# lists equal the TypeScript ones (bridge.ts gameNames/uiNames, bus.ts HUD_OWNED_FIELDS + the state fields).</summary>
    private static void CheckNameLists(FixtureSource source)
    {
        var bridge = File.ReadAllText(source.Resolve("repo:client3d/src/hud/bridge.ts"));
        var bus = File.ReadAllText(source.Resolve("repo:client3d/src/hud/bus.ts"));
        SameSet("gameNames", Quoted(Between(bridge, "const gameNames = [", "] as const")), HudProtocol.GameActions);
        SameSet("uiNames", Quoted(Between(bridge, "const uiNames = [", "] as const")), HudProtocol.UiActions);
        SameSet("HUD_OWNED_FIELDS", Quoted(Between(bus, "export const HUD_OWNED_FIELDS = [", "] as const")), HudProtocol.HudOwnedFields);
        var stateKeys = Regex.Matches(Between(bus, "const state: HudGameState = {", "};"), @"(\w+)\s*:")
            .Select(m => m.Groups[1].Value).ToList();
        SameSet("scene fields = state fields − HUD_OWNED_FIELDS",
                stateKeys.Except(HudProtocol.HudOwnedFields).ToList(), HudProtocol.SceneFields);
    }

    /// <summary>Every method of <see cref="GdCef"/> exists in the loaded library — or the extension is not linked.</summary>
    private static string CheckBinding()
    {
        // gdCEF registers Callable(overlay, "hud_bridge"); it is valid only if the
        // C# method is exposed to the engine under exactly that name.
        var overlay = new HudOverlay();
        bool exposed = overlay.HasMethod(HudOverlay.Channel);
        overlay.Free();
        Expect("HudOverlay exposes hud_bridge to the engine", exposed, "no method 'hud_bridge' — gdCEF could not call it");
        if (!GdCef.Available) return "not-linked";
        var missing = GdCef.MissingMethods();
        Expect("gdCEF binds every method and signal this client uses", missing.Count == 0, string.Join(", ", missing));
        Expect("gdCEF has no emit_js (its API.md is wrong; js_emit is bound)", !ClassDB.ClassHasMethod(GdCef.BrowserClass, "emit_js"),
               "emit_js exists — check which one GdCef.Emit should call");
        return $"bound({GdCef.CefMethods.Length}+{GdCef.BrowserMethods.Length} methods, {GdCef.BrowserSignals.Length} signals)";
    }

    private static HudUi Ui(HudRect[]? rects = null, bool overlay = false, bool typing = false, bool menu = false)
    {
        var ui = new HudUi();
        var arr = new JsonArray();
        foreach (var r in rects ?? Array.Empty<HudRect>())
            arr.Add(new JsonObject { ["x"] = r.X, ["y"] = r.Y, ["w"] = r.W, ["h"] = r.H });
        ui.Apply(new JsonObject { ["hitRects"] = arr, ["overlayOpen"] = overlay, ["typing"] = typing, ["menuOpen"] = menu });
        return ui;
    }

    private static string Between(string text, string start, string end)
    {
        int a = text.IndexOf(start, StringComparison.Ordinal);
        Expect($"source contains '{start}'", a >= 0, "not found");
        int b = text.IndexOf(end, a + start.Length, StringComparison.Ordinal);
        Expect($"source closes '{start}'", b > a, "not found");
        return text[(a + start.Length)..b];
    }

    private static List<string> Quoted(string text)
        => Regex.Matches(text, @"'([^']*)'").Select(m => m.Groups[1].Value).ToList();

    private static void SameSet(string what, IReadOnlyCollection<string> ts, IReadOnlyCollection<string> cs)
        => Expect($"{what} matches TypeScript", ts.Count == cs.Count && ts.ToHashSet().SetEquals(cs),
                  $"TS [{string.Join(",", ts)}] vs C# [{string.Join(",", cs)}]");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"hud: {what}: {detail}");
    }
}
