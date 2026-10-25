using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace AnimaNative.Api;

/// <summary>A non-2xx answer: carries status and path so the UI can say which call failed.</summary>
public sealed class ApiException : Exception
{
    public int Status { get; }
    public string Path { get; }

    public ApiException(int status, string path, string? detail = null)
        : base($"HTTP {status} on {path}" + (string.IsNullOrWhiteSpace(detail) ? "" : $": {detail}"))
    {
        Status = status;
        Path = path;
    }
}

/// <summary>
/// What the world builder reads. Implemented by <see cref="AnimaApi"/> (online)
/// and by the fixture source of the <c>--check</c> mode (offline), so both paths
/// build the very same nodes.
/// </summary>
public interface IWorldSource
{
    /// <summary><c>GET /play/worldmap</c> (§ A1.3) — authoritative for location placement (pos, yaw).</summary>
    Task<JsonDocument> GetWorldMapAsync();
    Task<JsonDocument> GetHeightfieldAsync();
    /// <summary>At most <see cref="AnimaApi.HeightTileBatchMax"/> keys; tiles not in the index are absent.</summary>
    Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys);
    /// <summary><c>GET /world/locations?view=3d</c> — ids, names, rooms, map3d; NO position (§ A1.3).</summary>
    Task<JsonDocument> GetLocations3dAsync();
    /// <summary>The scene recipe (§ B1); null on 404 (nothing to compose).</summary>
    Task<JsonDocument?> GetLocationSceneAsync(string locationId);
    /// <summary>Raw bytes of a server-relative URL as it appears in a payload (GLB variants, clips, character models).</summary>
    Task<byte[]> GetBytesAsync(string url);
    /// <summary><c>GET /characters/{name}/model3d</c> (§ A7); null on 404 (no model — the normal state).</summary>
    Task<JsonDocument?> GetCharacterModelAsync(string name);
    /// <summary><c>GET /assets/animation-clips</c> (§ A7/§ A8): <c>{clips: [{kind, role, set, url, loop, …}], locomotion, …}</c>.</summary>
    Task<JsonDocument> GetAnimationClipsAsync();
    /// <summary><c>GET /play/terrain</c> (§ A9): painted areas with their scatter rows, the type catalog, prop boxes.</summary>
    Task<JsonDocument> GetTerrainAsync();
    /// <summary>
    /// <c>GET /play/terrain-layers</c> (§ A16.7): without keys the INDEX (format, layer table, coarse overview
    /// mask, tile keys), with keys (at most <see cref="Ground.LayerCut.BatchMax"/>, payload spelling
    /// <c>"tx,tz"</c>) the fine masks of those tiles — <c>fetchTerrainLayers</c> of client3d/src/api.ts.
    /// </summary>
    Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys);
    /// <summary><c>GET /assets/surface-textures</c> (§ A7/§ A9): the bare array <c>[{kind, name, url, size_m, material?} | {kind, name, blend}]</c>.</summary>
    Task<JsonDocument> GetSurfaceTexturesAsync();
}

/// <summary>
/// The HTTP side of the native client. One <see cref="HttpClient"/> with a
/// <see cref="CookieContainer"/>: the session is the HttpOnly cookie
/// <c>av_session</c> that <c>POST /auth/login</c> sets (app/routes/auth.py,
/// app/core/auth_dependency.py); the container replays it — and any renewed
/// copy the sliding session sends back — on every later request. The password
/// is used for the one login request and is not kept.
///
/// Requests mirror the browser client (client3d/src/api.ts); no endpoint here is
/// invented.
/// </summary>
public sealed class AnimaApi : IWorldSource, IDisposable
{
    /// <summary>Server cap of <c>/play/heightfield/tiles</c> (§ A16.5, BATCH_MAX).</summary>
    public const int HeightTileBatchMax = 64;

    /// <summary>Name of the session cookie (app/core/sessions.py <c>SESSION_COOKIE_NAME</c>).</summary>
    public const string SessionCookieName = "av_session";

    private readonly HttpClient _http;
    private readonly CookieContainer _cookies = new();
    public Uri BaseUri { get; }

    public AnimaApi(string server)
    {
        BaseUri = new Uri(server.TrimEnd('/') + "/");
        var handler = new HttpClientHandler
        {
            CookieContainer = _cookies,
            UseCookies = true,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        _http = new HttpClient(handler) { BaseAddress = BaseUri, Timeout = TimeSpan.FromSeconds(180) };
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
    }

    /// <summary>
    /// <c>POST /auth/login</c> with the JSON body <c>{username, password}</c>.
    /// Returns the <c>user</c> object of the answer. 400/401/429 surface as
    /// <see cref="ApiException"/> with the server's <c>detail</c> text.
    /// </summary>
    public async Task<JsonDocument> LoginAsync(string user, string password)
    {
        var body = JsonSerializer.Serialize(new Dictionary<string, string>
        {
            ["username"] = user,
            ["password"] = password,
        });
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        using var res = await _http.PostAsync("auth/login", content);
        return await ReadJson(res, "/auth/login");
    }

    /// <summary>
    /// The current value of the HttpOnly session cookie, or null before a login.
    /// HttpOnly hides it from page scripts, not from this process: the native HUD
    /// hands this one session to its embedded browser (HudOverlay, Task S4) so both
    /// channels run on ONE login.
    /// </summary>
    public string? SessionToken()
    {
        var cookie = _cookies.GetCookies(BaseUri)[SessionCookieName];
        return cookie is null || cookie.Expired || cookie.Value.Length == 0 ? null : cookie.Value;
    }

    /// <summary>
    /// <c>POST /auth/logout</c>: ends the session server-side (both channels share it), the
    /// answer's Set-Cookie drops it from this container, and the container is emptied of
    /// this server's cookies afterwards in any case. Call it only with a LIVE session
    /// (<see cref="IsAuthenticatedAsync"/>): an anonymous logout is not a no-op on the
    /// server (<c>release_active_character</c> falls back to the legacy account row).
    /// </summary>
    public async Task LogoutAsync()
    {
        try
        {
            using var content = new StringContent("{}", Encoding.UTF8, "application/json");
            using var res = await _http.PostAsync("auth/logout", content);
            await EnsureOk(res, "/auth/logout");
        }
        finally
        {
            ForgetCookies();
        }
    }

    /// <summary><c>GET /auth/status</c> → <c>authenticated</c>: whether this container's session is alive.</summary>
    public async Task<bool> IsAuthenticatedAsync()
    {
        using var doc = await GetJson("/auth/status");
        return doc.RootElement.ValueKind == JsonValueKind.Object
               && doc.RootElement.TryGetProperty("authenticated", out var a)
               && a.ValueKind == JsonValueKind.True;
    }

    /// <summary>Expires every cookie this container holds for the server (the session copy of this process).</summary>
    public void ForgetCookies()
    {
        foreach (Cookie c in _cookies.GetCookies(BaseUri)) c.Expired = true;
    }

    /// <summary>
    /// <c>POST /play/bench-result</c>: hands one bench summary to the server,
    /// which appends it to <c>logs/bench.jsonl</c> next to the browser's runs.
    /// </summary>
    public async Task PostBenchResultAsync(string json)
    {
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var res = await _http.PostAsync("play/bench-result", content);
        await EnsureOk(res, "/play/bench-result");
    }

    public Task<JsonDocument> GetWorldMapAsync() => GetJson("/play/worldmap");
    public Task<JsonDocument> GetHeightfieldAsync() => GetJson("/play/heightfield");
    public Task<JsonDocument> GetLocations3dAsync() => GetJson("/world/locations?view=3d");

    /// <summary>
    /// <c>GET /play/heightfield/tiles?keys=tx:tz,tx:tz</c> — the colon joins a
    /// pair, the comma separates pairs (§ A16.5), URI-encoded like
    /// <c>fetchHeightTiles</c>. The payload names the tiles <c>"tx,tz"</c>.
    /// </summary>
    public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx, int Tz)> keys)
    {
        if (keys.Count == 0 || keys.Count > HeightTileBatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys), $"1..{HeightTileBatchMax} keys per call");
        var query = string.Join(",", keys.Select(k => $"{k.Tx}:{k.Tz}"));
        return GetJson("/play/heightfield/tiles?keys=" + Uri.EscapeDataString(query));
    }

    public Task<JsonDocument?> GetLocationSceneAsync(string locationId)
        => GetJsonOrNull($"/play/locations/{Uri.EscapeDataString(locationId)}/scene");

    public Task<JsonDocument?> GetCharacterModelAsync(string name)
        => GetJsonOrNull($"/characters/{Uri.EscapeDataString(name)}/model3d");

    public Task<JsonDocument> GetAnimationClipsAsync() => GetJson("/assets/animation-clips");

    public Task<JsonDocument> GetTerrainAsync() => GetJson("/play/terrain");

    /// <summary>The wire wants <c>tx:tz</c> (the comma separates keys there), URI-encoded like the browser.</summary>
    public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)
    {
        if (keys.Count == 0) return GetJson("/play/terrain-layers");
        if (keys.Count > Ground.LayerCut.BatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys), $"1..{Ground.LayerCut.BatchMax} keys per call");
        var query = string.Join(",", keys.Select(k => ReplaceFirst(k, ',', ':')));
        return GetJson("/play/terrain-layers?keys=" + Uri.EscapeDataString(query));
    }

    public Task<JsonDocument> GetSurfaceTexturesAsync() => GetJson("/assets/surface-textures");

    /// <summary>JS <c>String.replace(',', ':')</c>: the FIRST occurrence only.</summary>
    private static string ReplaceFirst(string s, char from, char to)
    {
        int i = s.IndexOf(from);
        return i < 0 ? s : s[..i] + to + s[(i + 1)..];
    }

    /// <summary>§ A7: <c>{format, rotation, offset_*, floors, height_m, signature}</c>, null on 404.</summary>
    public Task<JsonDocument?> GetLocationModelMetaAsync(string locationId)
        => GetJsonOrNull($"/play/locations/{Uri.EscapeDataString(locationId)}/model/meta");

    /// <summary>§ A7: the location GLB (Meshopt delivery copy), null on 404.</summary>
    public async Task<byte[]?> GetLocationModelAsync(string locationId)
    {
        var path = $"/play/locations/{Uri.EscapeDataString(locationId)}/model";
        using var res = await _http.GetAsync(Relative(path));
        if (res.StatusCode == HttpStatusCode.NotFound) return null;
        await EnsureOk(res, path);
        return await res.Content.ReadAsByteArrayAsync();
    }

    public async Task<byte[]> GetBytesAsync(string url)
    {
        using var res = await _http.GetAsync(Relative(url));
        await EnsureOk(res, url);
        return await res.Content.ReadAsByteArrayAsync();
    }

    private async Task<JsonDocument> GetJson(string path)
    {
        using var res = await _http.GetAsync(Relative(path));
        return await ReadJson(res, path);
    }

    private async Task<JsonDocument?> GetJsonOrNull(string path)
    {
        using var res = await _http.GetAsync(Relative(path));
        if (res.StatusCode == HttpStatusCode.NotFound) return null;
        return await ReadJson(res, path);
    }

    private static async Task<JsonDocument> ReadJson(HttpResponseMessage res, string path)
    {
        await EnsureOk(res, path);
        var bytes = await res.Content.ReadAsByteArrayAsync();
        return JsonDocument.Parse(bytes);
    }

    private static async Task EnsureOk(HttpResponseMessage res, string path)
    {
        if (res.IsSuccessStatusCode) return;
        string? detail = null;
        try
        {
            var text = await res.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.ValueKind == JsonValueKind.Object
                && doc.RootElement.TryGetProperty("detail", out var d))
                detail = d.ValueKind == JsonValueKind.String ? d.GetString() : d.ToString();
        }
        catch (Exception)
        {
            // Not JSON (a proxy page, an empty body): status + path say enough.
        }
        throw new ApiException((int)res.StatusCode, path.Split('?')[0], detail);
    }

    /// <summary>Payload URLs are server-absolute ("/play/…"); resolve them against the base.</summary>
    private Uri Relative(string path) => new(BaseUri, path.TrimStart('/'));

    public void Dispose() => _http.Dispose();
}
