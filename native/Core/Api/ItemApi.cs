using System;
using System.Collections.Concurrent;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Api;

public partial interface IWorldSource
{
    /// <summary><c>GET /play/locations/{location_id}/items</c> (ETag / 304 supported); null on 404 or unsupported source.</summary>
    Task<JsonDocument?> GetLocationItemsAsync(string locationId)
        => Task.FromResult<JsonDocument?>(null);

    /// <summary><c>POST /play/room-item/approach</c> with <c>{item_id}</c> → <c>{point: [x, z], room_id}</c> in location-local metres.</summary>
    Task<JsonDocument> ApproachRoomItemAsync(string itemId, CancellationToken ct = default)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/room-item/approach", "not served by this source"));

    /// <summary><c>POST /play/pickup</c> with <c>{item_id}</c>.</summary>
    Task<JsonDocument> PickupRoomItemAsync(string itemId, CancellationToken ct = default)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/pickup", "not served by this source"));

    /// <summary><c>POST /play/room-item/action</c> with <c>{item_id, action_id}</c>.</summary>
    Task<JsonDocument> RunRoomItemActionAsync(string itemId, string actionId, CancellationToken ct = default)
        => Task.FromException<JsonDocument>(new ApiException(404, "/play/room-item/action", "not served by this source"));
}

public sealed partial class AnimaApi
{
    private readonly ConcurrentDictionary<string, (string Etag, byte[] Body)> _memoryItemsCache = new(StringComparer.Ordinal);

    public Task<JsonDocument?> GetLocationItemsAsync(string locationId)
    {
        string path = $"/play/locations/{Uri.EscapeDataString(locationId)}/items";
        return _byteCache is not null ? FetchSceneJson(path) : FetchConditionalMemoryJson(path);
    }

    public Task<JsonDocument> ApproachRoomItemAsync(string itemId, CancellationToken ct = default)
        => PostItemJson("/play/room-item/approach", JsonSerializer.SerializeToElement(new { item_id = itemId }), ct);

    public Task<JsonDocument> PickupRoomItemAsync(string itemId, CancellationToken ct = default)
        => PostItemJson("/play/pickup", JsonSerializer.SerializeToElement(new { item_id = itemId }), ct);

    public Task<JsonDocument> RunRoomItemActionAsync(string itemId, string actionId, CancellationToken ct = default)
        => PostItemJson("/play/room-item/action", JsonSerializer.SerializeToElement(new { item_id = itemId, action_id = actionId }), ct);

    private async Task<JsonDocument?> FetchConditionalMemoryJson(string path)
    {
        var gate = _byteLocks.GetOrAdd(path, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync();
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, Relative(path));
            if (_memoryItemsCache.TryGetValue(path, out var cached) && cached.Etag.Length > 0)
                req.Headers.TryAddWithoutValidation("If-None-Match", cached.Etag);
            double start = MonotonicMs;
            using var res = await _http.SendAsync(req);
            Measurements.Add("JSON", "download", MonotonicMs - start, 1);
            if (res.StatusCode == HttpStatusCode.NotModified && cached.Body is not null)
                return await Task.Run(() => ParseCachedJson(cached.Body));
            if (res.StatusCode == HttpStatusCode.NotFound)
            {
                _memoryItemsCache.TryRemove(path, out _);
                return null;
            }
            var doc = await ReadJson(res, path);
            if (res.Headers.ETag?.ToString() is { Length: > 0 } etag)
                _memoryItemsCache[path] = (etag, JsonSerializer.SerializeToUtf8Bytes(doc.RootElement));
            else
                _memoryItemsCache.TryRemove(path, out _);
            return doc;
        }
        finally { gate.Release(); }
    }

    private async Task<JsonDocument> PostItemJson(string path, JsonElement body, CancellationToken ct)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(10000);
        using var request = new HttpRequestMessage(HttpMethod.Post, Relative(path))
        {
            Content = new StringContent(body.GetRawText(), Encoding.UTF8, "application/json"),
        };
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseContentRead, deadline.Token);
        return await ReadJson(response, path);
    }
}
