using System;
using System.Linq;
using System.Collections.Immutable;
using AnimaNative.Update;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Ui;

/// <summary>
/// What the launcher remembers between starts — the server address, the user
/// name, the window mode and skipped update versions. The password is never part of it
/// (typed into the login screen, used for the one login request, gone).
///
/// The Godot side keeps it in <c>user://launcher.json</c> (Linux:
/// <c>~/.local/share/godot/app_userdata/Anima Native/launcher.json</c>) and hands
/// the file's TEXT to <see cref="Parse"/> / takes it from <see cref="Serialize"/>;
/// this class never touches a file. A missing, empty or broken file is not an
/// error: it only costs the pre-fill.
/// </summary>
public sealed record LauncherSettings
{
    /// <summary>Normalised base URL (see <see cref="NormalizeServer"/>) or <c>""</c>.</summary>
    public string Server { get; init; } = "";
    /// <summary>The last user name that logged in, or <c>""</c>.</summary>
    public string User { get; init; } = "";
    /// <summary>The window mode F11 last chose.</summary>
    public bool Fullscreen { get; init; }

    public ImmutableDictionary<string, string> SkippedUpdates { get; init; } = ImmutableDictionary<string, string>.Empty;

    public LauncherSettings SkipUpdate(string server, string version)
        => this with { SkippedUpdates = SkippedUpdates.SetItem(UpdateServerKey(server), version) };

    public bool IsUpdateSkipped(string server, string version)
        => SkippedUpdates.TryGetValue(UpdateServerKey(server), out var skipped)
           && (version == skipped || !ReleaseVersion.IsNewer(skipped, version));

    private static string UpdateServerKey(string server)
        => Uri.TryCreate(NormalizeServer(server), UriKind.Absolute, out var uri) ? uri.AbsoluteUri.TrimEnd('/') : server;

    /// <summary>
    /// The file's text → settings. Anything unreadable (not JSON, not an object,
    /// a value of the wrong type) falls back to the default of that field; keys
    /// other than <c>server</c>/<c>user</c>/<c>fullscreen</c>/<c>skipped_updates</c> are ignored — so they
    /// are also gone after the next <see cref="Serialize"/>.
    /// </summary>
    public static LauncherSettings Parse(string? fileText)
    {
        if (string.IsNullOrWhiteSpace(fileText)) return new LauncherSettings();
        JsonNode? root;
        try
        {
            root = JsonNode.Parse(fileText);
        }
        catch (JsonException)
        {
            return new LauncherSettings();
        }
        if (root is not JsonObject obj) return new LauncherSettings();
        return new LauncherSettings
        {
            Server = NormalizeServer(StringOf(obj, "server") ?? "") ?? "",
            User = (StringOf(obj, "user") ?? "").Trim(),
            Fullscreen = obj["fullscreen"] is JsonValue v && v.GetValueKind() == JsonValueKind.True,
            SkippedUpdates = ReadSkipped(obj["skipped_updates"]),
        };
    }

    /// <summary>The file's text: server, user, fullscreen, and skipped_updates when nonempty.</summary>
    public string Serialize()
    {
        var obj = new JsonObject
        {
            ["server"] = Server,
            ["user"] = User,
            ["fullscreen"] = Fullscreen,
        };
        if (!SkippedUpdates.IsEmpty)
        {
            var skipped = new JsonObject();
            foreach (var (server, version) in SkippedUpdates) skipped[server] = version;
            obj["skipped_updates"] = skipped;
        }
        return obj.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n";
    }

    /// <summary>
    /// Start values: a non-blank command-line value wins over the stored one
    /// (<c>--server</c>, <c>--user</c>); the window mode always comes from the file.
    /// </summary>
    public static LauncherSettings Merge(LauncherSettings stored, string? cliServer, string? cliUser)
    {
        var server = string.IsNullOrWhiteSpace(cliServer) ? null : NormalizeServer(cliServer);
        var user = string.IsNullOrWhiteSpace(cliUser) ? null : cliUser.Trim();
        return stored with
        {
            Server = server ?? stored.Server,
            User = user ?? stored.User,
        };
    }

    /// <summary>
    /// A server address in the form a person types it → the base URL the client
    /// uses: trimmed, <c>http://</c> added when no scheme is given, trailing
    /// slashes removed (<c>192.168.8.244:8000/</c> → <c>http://192.168.8.244:8000</c>).
    /// Null for an empty input and for one that is no usable http(s) address
    /// (another scheme, no host, blanks inside).
    /// </summary>
    public static string? NormalizeServer(string input)
    {
        var s = (input ?? "").Trim();
        if (s.Length == 0 || s.Any(char.IsWhiteSpace)) return null;
        if (!s.Contains("://", StringComparison.Ordinal)) s = "http://" + s;
        s = s.TrimEnd('/');
        if (!Uri.TryCreate(s, UriKind.Absolute, out var uri)) return null;
        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) return null;
        if (uri.Host.Length == 0) return null;
        return s;
    }

    private static ImmutableDictionary<string, string> ReadSkipped(JsonNode? node)
    {
        var result = ImmutableDictionary<string, string>.Empty;
        if (node is not JsonObject obj) return result;
        foreach (var (key, value) in obj)
            if (NormalizeServer(key) is not null && value is JsonValue v && v.GetValueKind() == JsonValueKind.String
                && v.GetValue<string>() is { } version && ReleaseVersion.IsClean(version))
                result = result.SetItem(UpdateServerKey(key), version);
        return result;
    }

    private static string? StringOf(JsonObject obj, string key)
        => obj[key] is JsonValue v && v.GetValueKind() == JsonValueKind.String ? v.GetValue<string>() : null;
}
