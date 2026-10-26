using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Hud;

/// <summary>One HUD surface in the HUD page's CSS pixels (<c>HudRect</c> of client3d/src/hud/bus.ts).</summary>
public readonly record struct HudRect(double X, double Y, double W, double H);

/// <summary>
/// The scene's copy of <c>HudUiState</c> (bus.ts) — written ONLY by the HUD
/// (<c>{v:2, kind:'hud', patch}</c>), read by the input routing.
/// </summary>
public sealed class HudUi
{
    public bool MenuOpen { get; private set; }
    public bool Typing { get; private set; }
    public bool OverlayOpen { get; private set; }
    public bool PerfOn { get; private set; }
    public IReadOnlyList<HudRect> HitRects { get; private set; } = Array.Empty<HudRect>();

    /// <summary><c>setHudUiState(patch)</c>: a shallow merge; keys with a wrong type are ignored.</summary>
    public void Apply(JsonObject patch)
    {
        if (Bool(patch, "menuOpen") is { } m) MenuOpen = m;
        if (Bool(patch, "typing") is { } t) Typing = t;
        if (Bool(patch, "overlayOpen") is { } o) OverlayOpen = o;
        if (Bool(patch, "perfOn") is { } p) PerfOn = p;
        if (patch["hitRects"] is JsonArray rects)
        {
            var list = new List<HudRect>();
            foreach (var r in rects)
            {
                if (r is not JsonObject o2) continue;
                if (Num(o2, "x") is { } x && Num(o2, "y") is { } y && Num(o2, "w") is { } w && Num(o2, "h") is { } h)
                    list.Add(new HudRect(x, y, w, h));
            }
            HitRects = list;
        }
    }

    /// <summary>Back to the HUD's initial state (a new page, or no page).</summary>
    public void Reset()
    {
        MenuOpen = Typing = OverlayOpen = PerfOn = false;
        HitRects = Array.Empty<HudRect>();
    }

    private static bool? Bool(JsonObject o, string key)
        => o[key] is JsonValue v && v.TryGetValue<bool>(out var b) ? b : null;

    internal static double? Num(JsonObject o, string key)
        => o[key] is JsonValue v && v.GetValueKind() == JsonValueKind.Number ? v.GetValue<double>() : null;
}

/// <summary>A message from the HUD that passed validation.</summary>
public sealed record HudInbound(string Kind, JsonObject? Patch, string? Name, JsonArray? Args);

/// <summary>
/// Protocol v2 of client3d/src/hud/bridge.ts (<c>HUD_BRIDGE_VERSION</c>), scene side, as pure functions:
/// the same validation (<c>valid()</c>: an object, <c>v === 2</c>, a <c>kind</c>),
/// the same name lists (<c>gameNames</c>, <c>uiNames</c>) and the same field
/// ownership (<c>HUD_OWNED_FIELDS</c>). On the gdCEF wire each message is ONE
/// JSON string. Keep the lists in step with bridge.ts/bus.ts — <c>--check</c>
/// pins them by hand.
///
/// Version history (bridge.ts): both hosts must speak the SAME number; a message with
/// another <c>v</c> is dropped with a reason (no negotiation, no fallback reader).
///   - v1: the first wire (native spike S4).
///   - v2 (Task 26d): game action <c>applyGraphicsPrefs(prefs)</c>, the menu's Graphics tab.
/// </summary>
public static class HudProtocol
{
    public const int Version = 2;

    /// <summary><c>gameNames</c> of bridge.ts — actions HUD → scene.</summary>
    public static readonly string[] GameActions =
    {
        "infoAction", "closeInfo", "closeOpenView", "pickPlacePose", "clearSelection", "setVolumes", "speak", "stopSpeech",
        "markResume", "zoomTo", "sayBubble", "enterEmbodied", "takeControl", "exitEmbodied", "rideElevator", "rideStairs",
        "enterLocation", "backToTitle", "setShowAll", "applyAudioPrefs", "applyScatterPrefs", "applyGraphicsPrefs", "setChatBox",
    };

    /// <summary><c>uiNames</c> of bridge.ts — actions scene → HUD.</summary>
    public static readonly string[] UiActions = { "openChat", "toast", "toggleMenu", "closeMenu" };

    /// <summary><c>HUD_OWNED_FIELDS</c> of bus.ts — the HUD writes these game-state fields, the scene only reads them.</summary>
    public static readonly string[] HudOwnedFields =
        { "movementLocked", "partyLeader", "groundRoomId", "floorRoomIds", "lockedRooms", "lockedLoc", "lockedLocations" };

    /// <summary>The scene-owned <c>HudGameState</c> fields (bus.ts, every field that is not HUD-owned).</summary>
    public static readonly string[] SceneFields =
    {
        "clock", "connection", "info", "openView", "placeMenu", "mode", "selected", "talkTarget",
        "elevator", "elevatorOpen", "stairs", "enterOffer",
    };

    /// <summary>
    /// Parse + validate one inbound wire string. Returns null and a reason for
    /// everything bridge.ts would <c>reject()</c>: not JSON, not an object,
    /// <c>v !== </c><see cref="Version"/>, no <c>kind</c>, an unknown kind, an action whose name is not
    /// declared or whose <c>args</c> is not an array, a patch that is not an object.
    /// </summary>
    public static HudInbound? Parse(string raw, out string? reason)
    {
        JsonNode? node;
        try { node = JsonNode.Parse(raw); }
        catch (JsonException e) { reason = "not JSON: " + e.Message; return null; }
        return Validate(node, out reason);
    }

    public static HudInbound? Validate(JsonNode? node, out string? reason)
    {
        reason = null;
        if (node is not JsonObject msg) { reason = "not an object"; return null; }
        if (msg["v"] is not JsonValue v || v.GetValueKind() != JsonValueKind.Number || v.GetValue<double>() != Version)
        { reason = $"v is not {Version}"; return null; }
        if (!msg.ContainsKey("kind")) { reason = "no kind"; return null; }
        var kind = msg["kind"] is JsonValue k && k.GetValueKind() == JsonValueKind.String ? k.GetValue<string>() : "";
        switch (kind)
        {
            case "state":
            case "hud":
                if (msg["patch"] is not JsonObject patch) { reason = $"{kind} without an object patch"; return null; }
                return new HudInbound(kind, patch, null, null);
            case "action":
                var name = msg["name"] is JsonValue n && n.GetValueKind() == JsonValueKind.String ? n.GetValue<string>() : "";
                if (!GameActions.Contains(name)) { reason = $"undeclared action '{name}'"; return null; }
                if (msg["args"] is not JsonArray args) { reason = $"action '{name}' without an args array"; return null; }
                return new HudInbound(kind, null, name, args);
            default:
                reason = $"unknown kind '{kind}'";
                return null;
        }
    }

    /// <summary>
    /// <c>receiveState(patch, HUD_OWNED_FIELDS)</c>: the keys the HUD may write, and the
    /// ones it may not (dropped, one warning per patch in the caller).
    /// </summary>
    public static (JsonObject Accepted, List<string> Dropped) SplitOwned(JsonObject patch)
    {
        var accepted = new JsonObject();
        var dropped = new List<string>();
        foreach (var (key, value) in patch)
        {
            if (HudOwnedFields.Contains(key)) accepted[key] = value?.DeepClone();
            else dropped.Add(key);
        }
        return (accepted, dropped);
    }

    /// <summary><c>{v:2, kind:'state', patch}</c></summary>
    public static string State(JsonObject patch)
        => new JsonObject { ["v"] = Version, ["kind"] = "state", ["patch"] = patch.DeepClone() }.ToJsonString();

    /// <summary><c>{v:2, kind:'boot', value}</c></summary>
    public static string Boot(JsonObject value)
        => new JsonObject { ["v"] = Version, ["kind"] = "boot", ["value"] = value.DeepClone() }.ToJsonString();

    /// <summary><c>{v:2, kind:'perf', value}</c> — the performance readout (<c>PerfStats</c> of bus.ts) or null.</summary>
    public static string Perf(JsonObject? value)
        => new JsonObject { ["v"] = Version, ["kind"] = "perf", ["value"] = value?.DeepClone() }.ToJsonString();

    /// <summary><c>{v:2, kind:'ui', name, args}</c>; only the declared ui actions.</summary>
    public static string Ui(string name, params JsonNode?[] args)
    {
        if (!UiActions.Contains(name)) throw new ArgumentException($"undeclared ui action '{name}'");
        var arr = new JsonArray();
        foreach (var a in args) arr.Add(a?.DeepClone());
        return new JsonObject { ["v"] = Version, ["kind"] = "ui", ["name"] = name, ["args"] = arr }.ToJsonString();
    }

    /// <summary>
    /// <c>HudBoot</c> for a world that is up: every boot stage done (game/boot.ts
    /// <c>BOOT_STAGES</c>), label <c>ready</c>, no note, no measurement report.
    /// </summary>
    public static JsonObject BootReady()
    {
        var stages = new JsonArray();
        foreach (var s in new[] { "world", "scenes", "tiles", "visible", "figures", "arrival" }) stages.Add(s);
        return new JsonObject
        {
            ["state"] = new JsonObject { ["percent"] = 100, ["label"] = "ready", ["note"] = null, ["stages"] = stages },
            ["report"] = null,
        };
    }
}

/// <summary>
/// <c>statePublisher</c> of bridge.ts for the scene side: remembers each field's
/// serialized value and hands out only what changed since the last publication
/// (<paramref name="force"/>: everything set so far — the answer to a HUD that
/// has just (re)connected). Only scene-owned fields can be set.
/// </summary>
public sealed class ScenePublisher
{
    private readonly Dictionary<string, JsonNode?> _values = new();
    private readonly Dictionary<string, string> _published = new();

    public void Set(string field, JsonNode? value)
    {
        if (!HudProtocol.SceneFields.Contains(field))
            throw new ArgumentException($"'{field}' is not a scene-owned HUD field");
        _values[field] = value?.DeepClone();
    }

    public JsonNode? Get(string field) => _values.TryGetValue(field, out var v) ? v : null;

    /// <summary>The patch to send, or null when nothing changed.</summary>
    public JsonObject? TakePatch(bool force = false)
    {
        var patch = new JsonObject();
        foreach (var (field, value) in _values)
        {
            var text = value?.ToJsonString() ?? "null";
            if (!force && _published.TryGetValue(field, out var prev) && prev == text) continue;
            _published[field] = text;
            patch[field] = value?.DeepClone();
        }
        return patch.Count > 0 ? patch : null;
    }
}
