using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Sync;

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
    /// <summary>
    /// <c>GET /play/heightfield/stats?keys=tx:tz,…</c> (§ G2): the statistics the overview's cap kept back, at most
    /// <see cref="AnimaApi.HeightTileBatchMax"/> keys (more is a 400), answered <c>{sig, tile_stats: {"tx,tz": …}}</c>.
    /// A source that does not serve it answers 404 — the background fill then gives up (the level stays coarse).
    /// </summary>
    Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/heightfield/stats", "not served by this source"));
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
    /// <summary>
    /// <c>GET /play/explored</c> (§ A12): the avatar's exploration memory <c>{cells: ["cx,cz", …], sig}</c> — the veil's
    /// cells, fetched on <c>explored_sig</c> only. A source that does not serve it answers 404 (the veil keeps standing).
    /// </summary>
    Task<JsonDocument> GetExploredAsync()
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/explored", "not served by this source"));
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
    public const int HeightTileBatchMax = Terrain.HeightTiles.BatchMax;

    /// <summary>Name of the session cookie (app/core/sessions.py <c>SESSION_COOKIE_NAME</c>).</summary>
    public const string SessionCookieName = "av_session";

    private readonly HttpClient _http;
    /// <summary>
    /// The same handler (and cookie container) without a timeout, for the event stream: <c>Timeout</c> is the
    /// whole request's budget, and <c>/events/sync</c> is one request that lasts the session.
    /// </summary>
    private readonly HttpClient _streams;
    private readonly CookieContainer _cookies = new();
    private string _positionSession = "";
    private int _positionSequence;
    public Uri BaseUri { get; }

    /// <summary>
    /// A request answered 401 — the session is gone (api.ts <c>json()</c> dispatches <c>auth:required</c> once
    /// per failing call; the same here). Not raised by <c>POST /auth/login</c> (a wrong password is not a lost
    /// session) nor by the event stream (the browser's EventSource does not announce one either).
    /// </summary>
    public event Action? Unauthorized;

    /// <summary>The one failure that needs a login rather than a retry (api.ts <c>isAuthError</c>).</summary>
    public static bool IsAuthError(Exception? e) => e is ApiException { Status: 401 }
                                                     || (e is AggregateException a && IsAuthError(a.InnerException));

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
        _streams = new HttpClient(handler, disposeHandler: false) { BaseAddress = BaseUri, Timeout = Timeout.InfiniteTimeSpan };
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
    /// Takes over a session this process already holds (its <see cref="SessionToken"/> from an API that is being
    /// replaced): the cookie goes into this container as the server set it — name <c>av_session</c>, path <c>/</c> —
    /// without a login request. Used by the rebuild after a character switch, which keeps the one live session the
    /// HUD's browser shares. The server's next sliding refresh renews it as usual.
    /// </summary>
    public void AdoptSession(string token)
    {
        if (string.IsNullOrEmpty(token)) throw new ArgumentException("an empty session token cannot be adopted", nameof(token));
        _cookies.Add(BaseUri, new Cookie(SessionCookieName, token, "/") { HttpOnly = true });
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

    /// <summary>
    /// <c>getWorldMap(all)</c>: <c>all</c> asks for the UNFILTERED view (contract § A12) — the admin's switch; the
    /// server answers 403 for anybody else, so callers pass it only for role <c>admin</c>.
    /// </summary>
    public Task<JsonDocument> GetWorldMapAsync(bool all) => GetJson(all ? "/play/worldmap?all=1" : "/play/worldmap");

    public Task<JsonDocument> GetPropActionsAsync() => GetJson("/play/prop-actions");
    public Task<JsonDocument> GetPropActionStateAsync() => GetJson("/play/prop-actions/state");
    public Task<JsonDocument> GetPlacesAsync() => GetJson("/play/places");
    public Task<JsonDocument> RequestPropActionAsync(string actionId, JsonElement target, string revision, string? partner)
        => PostJson("/play/prop-actions/request", new { action_id = actionId, target, revision, partner = partner ?? "" });
    public Task<JsonDocument> RespondPropActionAsync(string executionId, bool accept)
        => PostJson("/play/prop-actions/respond", new { execution_id = executionId, accept });
    public Task<JsonDocument> CancelPropActionAsync(string executionId)
        => PostJson("/play/prop-actions/cancel", new { execution_id = executionId });
    public Task<JsonDocument> SetRoomPoseAsync(string placeId, string pose)
        => placeId.Length == 0 ? PostJson("/play/self/activity", new { activity = pose })
            : PostJson("/play/self/activity", new { place_id = placeId, pose });
    public Task<JsonDocument> WakeAsync() => PostJson("/play/self/activity", new { activity = "" });
    public void BeginPositionControlSession()
    {
        _positionSession = Guid.NewGuid().ToString("N");
        _positionSequence = 0;
    }

    public Task<JsonDocument> ReportPositionAsync(double x, double z, double timeMs)
    {
        if (_positionSession.Length == 0) BeginPositionControlSession();
        return PostJson("/play/pos", new { x, z, seq = ++_positionSequence, t_ms = timeMs, session = _positionSession });
    }

    private async Task<JsonDocument> PostJson(string path, object body)
    {
        using var content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        using var res = await _http.PostAsync(Relative(path), content);
        return await ReadJson(res, path);
    }
    public Task<JsonDocument> GetHeightfieldAsync() => GetJson("/play/heightfield");
    public Task<JsonDocument> GetLocations3dAsync() => GetJson("/world/locations?view=3d");

    /// <summary>
    /// <c>GET /world/locations?view=3d</c> with <c>If-None-Match</c> (api.ts <c>getLocations3d</c>; the cache and
    /// the single flight are <see cref="LocationsCache"/>'s): 304 comes back as a status without a body, 200 with
    /// the body and its <c>ETag</c>; anything else throws like every other call (401 included).
    /// </summary>
    public async Task<ConditionalAnswer> GetLocations3dConditionalAsync(string? etag)
    {
        const string path = "/world/locations?view=3d";
        using var req = new HttpRequestMessage(HttpMethod.Get, Relative(path));
        if (etag is not null) req.Headers.TryAddWithoutValidation("If-None-Match", etag);
        using var res = await _http.SendAsync(req);
        if (res.StatusCode == HttpStatusCode.NotModified) return new ConditionalAnswer(304, res.Headers.ETag?.ToString() ?? "", null);
        await EnsureOk(res, path);
        var bytes = await res.Content.ReadAsByteArrayAsync();
        using var doc = JsonDocument.Parse(bytes);
        return new ConditionalAnswer((int)res.StatusCode, res.Headers.ETag?.ToString() ?? "", doc.RootElement.Clone());
    }

    /// <summary>
    /// An event stream (<c>/events/sync</c>) for <see cref="HttpEventSource"/>: GET with this session, headers
    /// only, NO status check — the transport tells a refusal from a stream itself.
    /// </summary>
    public async Task<HttpResponseMessage> OpenEventStreamAsync(string path, CancellationToken ct)
    {
        var req = new HttpRequestMessage(HttpMethod.Get, Relative(path));
        req.Headers.Accept.Clear();
        req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        req.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true };
        return await _streams.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
    }

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

    /// <summary><c>GET /play/heightfield/stats?keys=tx:tz,…</c> — the same key spelling as the tile batch (<c>fetchHeightTileStats</c>).</summary>
    public Task<JsonDocument> GetHeightTileStatsAsync(IReadOnlyList<(int Tx, int Tz)> keys)
    {
        if (keys.Count == 0 || keys.Count > HeightTileBatchMax)
            throw new ArgumentOutOfRangeException(nameof(keys), $"1..{HeightTileBatchMax} keys per call");
        var query = string.Join(",", keys.Select(k => $"{k.Tx}:{k.Tz}"));
        return GetJson("/play/heightfield/stats?keys=" + Uri.EscapeDataString(query));
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

    public Task<JsonDocument> GetExploredAsync() => GetJson("/play/explored");

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

    private async Task<JsonDocument> ReadJson(HttpResponseMessage res, string path)
    {
        await EnsureOk(res, path);
        // The body and its parse leave the caller's context: a height tile batch is ~8 MB of JSON, and parsing it on
        // the Godot main thread was a frame-sized stall. EnsureOk (and with it the Unauthorized event) still runs on the
        // caller's context, and the caller's own await resumes there as before.
        var bytes = await res.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
        return JsonDocument.Parse(bytes);
    }

    private async Task EnsureOk(HttpResponseMessage res, string path)
    {
        if (res.IsSuccessStatusCode) return;
        if (res.StatusCode == HttpStatusCode.Unauthorized && path != "/auth/login") Unauthorized?.Invoke();
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

    public void Dispose()
    {
        _streams.Dispose();
        _http.Dispose();
    }
}
