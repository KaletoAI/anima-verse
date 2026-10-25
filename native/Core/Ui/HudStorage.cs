using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Ui;

/// <summary>One mirrored <c>localStorage</c> call of the HUD page: <c>set</c> (key + value), <c>remove</c> (key) or <c>clear</c>.</summary>
public sealed record HudStorageOp(string Op, string? Key, string? Value)
{
    public const string Set = "set", Remove = "remove", Clear = "clear";
}

/// <summary>What <see cref="HudStorage.Apply"/> did.</summary>
public enum HudStorageResult
{
    /// <summary>The store changed (the file is due for a write).</summary>
    Changed,
    /// <summary>Nothing to do: the same value, a key that was not there, a clear of nothing.</summary>
    Unchanged,
    /// <summary>Dropped: the store would grow past <see cref="HudStorage.MaxBytes"/>.</summary>
    TooLarge,
    /// <summary>Dropped: the key or value contains the session token (it never goes to disk).</summary>
    Secret,
}

/// <summary>
/// The HUD's local settings, kept across starts. The HUD browser runs with an in-memory profile (the session cookie
/// must never reach a disk cache), so its <c>localStorage</c> — "show all", scatter distances, volumes, dock and chat
/// sizes, … — is gone at every start. In gdCEF mode the page mirrors every <c>localStorage</c> write to Godot
/// (<c>window.godotMethods.hud_storage</c>, NOT the bridge protocol); Godot keeps the entries per server ORIGIN in
/// <c>user://hud_storage.json</c> and seeds them into the page's <c>localStorage</c> during the handoff on
/// <c>/health</c>, before <c>hud.html</c> loads (<see cref="SeedScript"/>).
///
/// This class is the file's model and never touches a file: <see cref="Parse"/> (a missing, broken or foreign file
/// reads as empty), <see cref="Serialize"/> (compact, keys sorted), <see cref="Apply"/>. The whole serialised store is
/// capped at <see cref="MaxBytes"/>: a write that would grow it past the cap is dropped (the caller logs it), so a
/// runaway page cannot fill the disk; removals always pass. Only what the page puts into <c>localStorage</c> is ever
/// stored — the session lives in an HttpOnly cookie, never in <c>localStorage</c>, and a write that carries the session
/// token anyway is refused (<see cref="HudStorageResult.Secret"/>).
///
/// File: <c>{"version":1,"servers":{"http://192.168.8.244:8000":{"av3d.showAllLocations":"1", …}}}</c>.
/// </summary>
public sealed class HudStorage
{
    public const int Version = 1;
    /// <summary>The cap on the serialised store: 256 KB.</summary>
    public const int MaxBytes = 256 * 1024;

    /// <summary><c>SHOW_ALL_KEY</c> of client3d/src/game/prefs.ts.</summary>
    public const string ShowAllKey = "av3d.showAllLocations";
    /// <summary><c>SCATTER_PREFS_KEY</c> of client3d/src/game/prefs.ts.</summary>
    public const string ScatterPrefsKey = "av3d.view.scatter.v1";

    private readonly SortedDictionary<string, SortedDictionary<string, string>> _servers = new(StringComparer.Ordinal);

    /// <summary>
    /// The storage partition of a server address: its origin <c>scheme://host[:port]</c> (lower-case host, default
    /// port dropped) — what <c>localStorage</c> itself is partitioned by. The address is first normalised like the
    /// launcher's (<see cref="LauncherSettings.NormalizeServer"/>); null for an unusable address.
    /// </summary>
    public static string? ServerKey(string? server)
    {
        var normalized = LauncherSettings.NormalizeServer(server ?? "");
        if (normalized is null || !Uri.TryCreate(normalized, UriKind.Absolute, out var uri)) return null;
        return uri.GetLeftPart(UriPartial.Authority);
    }

    /// <summary>
    /// The file's text → the store. Not JSON, not an object, another <c>version</c>, no <c>servers</c> object: empty.
    /// A server whose address does not normalise and an entry whose value is not a string are dropped one by one.
    /// </summary>
    public static HudStorage Parse(string? fileText)
    {
        var store = new HudStorage();
        if (string.IsNullOrWhiteSpace(fileText)) return store;
        JsonNode? root;
        try
        {
            root = JsonNode.Parse(fileText);
        }
        catch (JsonException)
        {
            return store;
        }
        if (root is not JsonObject obj
            || obj["version"] is not JsonValue v || !v.TryGetValue<int>(out var version) || version != Version
            || obj["servers"] is not JsonObject servers) return store;
        foreach (var (address, entries) in servers)
        {
            if (ServerKey(address) is not { } key || entries is not JsonObject list) continue;
            var target = store.Entries(key, create: true)!;
            foreach (var (name, value) in list)
                if (value is JsonValue s && s.GetValueKind() == JsonValueKind.String) target[name] = s.GetValue<string>();
            if (target.Count == 0) store._servers.Remove(key);
        }
        return store;
    }

    /// <summary>The file's text: compact, servers and keys in ordinal order.</summary>
    public string Serialize()
    {
        var servers = new JsonObject();
        foreach (var (server, entries) in _servers)
        {
            var list = new JsonObject();
            foreach (var (k, value) in entries) list[k] = value;
            servers[server] = list;
        }
        return new JsonObject { ["version"] = Version, ["servers"] = servers }.ToJsonString();
    }

    /// <summary>The serialised size in UTF-8 bytes (what the cap counts).</summary>
    public int ByteSize => Encoding.UTF8.GetByteCount(Serialize());

    /// <summary>The entries kept for <paramref name="server"/> (any address form), empty when none.</summary>
    public IReadOnlyDictionary<string, string> EntriesFor(string? server)
        => ServerKey(server) is { } key && _servers.TryGetValue(key, out var entries)
            ? new SortedDictionary<string, string>(entries, StringComparer.Ordinal)
            : new SortedDictionary<string, string>(StringComparer.Ordinal);

    /// <summary>
    /// One mirrored call for <paramref name="server"/>. <paramref name="secret"/> is the live session token: a key
    /// or value that contains it is refused. A change that would leave the store larger than <see cref="MaxBytes"/>
    /// AND larger than before is dropped, the store stays as it was.
    /// </summary>
    public HudStorageResult Apply(string? server, HudStorageOp op, string? secret = null)
    {
        if (ServerKey(server) is not { } key) return HudStorageResult.Unchanged;
        if (!string.IsNullOrEmpty(secret)
            && ((op.Key?.Contains(secret, StringComparison.Ordinal) ?? false)
                || (op.Value?.Contains(secret, StringComparison.Ordinal) ?? false)))
            return HudStorageResult.Secret;
        var entries = Entries(key, create: false);
        switch (op.Op)
        {
            case HudStorageOp.Set when op.Key is not null && op.Value is not null:
            {
                if (entries is not null && entries.TryGetValue(op.Key, out var old) && old == op.Value)
                    return HudStorageResult.Unchanged;
                int before = ByteSize;
                var target = Entries(key, create: true)!;
                bool had = target.TryGetValue(op.Key, out var previous);
                target[op.Key] = op.Value;
                int after = ByteSize;
                if (after > MaxBytes && after > before)
                {
                    if (had) target[op.Key] = previous!;
                    else target.Remove(op.Key);
                    if (target.Count == 0) _servers.Remove(key);
                    return HudStorageResult.TooLarge;
                }
                return HudStorageResult.Changed;
            }
            case HudStorageOp.Remove when op.Key is not null:
                if (entries is null || !entries.Remove(op.Key)) return HudStorageResult.Unchanged;
                if (entries.Count == 0) _servers.Remove(key);
                return HudStorageResult.Changed;
            case HudStorageOp.Clear:
                return _servers.Remove(key) ? HudStorageResult.Changed : HudStorageResult.Unchanged;
            default:
                return HudStorageResult.Unchanged;
        }
    }

    /// <summary>
    /// The page's message (a JSON string: <c>{"op":"set","key":…,"value":…}</c>, <c>{"op":"remove","key":…}</c>,
    /// <c>{"op":"clear"}</c>) → the op; null with the <paramref name="reason"/> for anything else.
    /// </summary>
    public static HudStorageOp? ParseOp(string? raw, out string reason)
    {
        reason = "";
        JsonNode? root;
        try
        {
            root = JsonNode.Parse(raw ?? "");
        }
        catch (JsonException)
        {
            reason = "not JSON";
            return null;
        }
        if (root is not JsonObject obj)
        {
            reason = "not an object";
            return null;
        }
        string? Str(string k) => obj[k] is JsonValue v && v.GetValueKind() == JsonValueKind.String ? v.GetValue<string>() : null;
        var op = Str("op");
        var key = Str("key");
        var value = Str("value");
        switch (op)
        {
            case HudStorageOp.Set when key is not null && value is not null:
                return new HudStorageOp(op, key, value);
            case HudStorageOp.Set:
                reason = "set needs a string key and a string value";
                return null;
            case HudStorageOp.Remove when key is not null:
                return new HudStorageOp(op, key, null);
            case HudStorageOp.Remove:
                reason = "remove needs a string key";
                return null;
            case HudStorageOp.Clear:
                return new HudStorageOp(op, null, null);
            default:
                reason = $"unknown op '{op ?? "(none)"}'";
                return null;
        }
    }

    /// <summary>
    /// A page-script statement that writes <paramref name="entries"/> into <c>localStorage</c> (part of the handoff,
    /// run on <c>/health</c> before <c>hud.html</c> loads, so the HUD's first read finds them). The entries travel as
    /// ONE JSON object literal from <see cref="JsonSerializer"/> with its default encoder: quotes, backslashes,
    /// control characters (newlines), <c>&lt;</c>/<c>&gt;</c>/<c>&amp;</c>/<c>'</c> and every non-ASCII character
    /// (U+2028/U+2029 included) are <c>\uXXXX</c> escapes, so nothing a value holds can end the literal or the
    /// script. A failing write (quota, a blocked storage) never stops the handoff. Empty for no entries.
    /// </summary>
    public static string SeedScript(IReadOnlyDictionary<string, string> entries)
    {
        if (entries.Count == 0) return "";
        var literal = JsonSerializer.Serialize(entries.OrderBy(e => e.Key, StringComparer.Ordinal)
                                                      .ToDictionary(e => e.Key, e => e.Value));
        return "try { const e = " + literal + "; for (const k of Object.keys(e)) localStorage.setItem(k, e[k]); } "
               + "catch (err) { console.warn('[hud storage] seeding localStorage failed', err); } ";
    }

    /// <summary>
    /// The start view the scene reads from the stored HUD settings, like main.ts at boot: "show all locations" only
    /// for an admin (a value left behind by a demoted account must not ask for a view the server refuses).
    /// </summary>
    public static bool StartShowAll(IReadOnlyDictionary<string, string> entries, bool isAdmin)
        => isAdmin && entries.TryGetValue(ShowAllKey, out var v) && v == "1";

    private SortedDictionary<string, string>? Entries(string key, bool create)
    {
        if (_servers.TryGetValue(key, out var entries)) return entries;
        if (!create) return null;
        entries = new SortedDictionary<string, string>(StringComparer.Ordinal);
        _servers[key] = entries;
        return entries;
    }
}
