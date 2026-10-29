using System;
using System.Collections.Concurrent;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Cache;
using AnimaNative.Sync;

namespace AnimaNative.Api;

/// <summary>Task 62 / E10-T1: binary cache below IWorldSource; Task 63 JSON uses the same store via AnimaApi.JsonCache.
/// Keys are path + query within the configured origin. Request headers, cookies and credentials never enter
/// the index or counters. A version query alone grants no freshness (inventory §2.3, R-2).</summary>
public sealed partial class AnimaApi
{
    private readonly DiskCache? _byteCache;
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _byteLocks = new(StringComparer.Ordinal);
    public BootMeasurements Measurements { get; } = new();
    private long _cacheHits, _revalidated, _fetched, _saved;
    public string CacheSummary() => $"cache: hits={Interlocked.Read(ref _cacheHits)} revalidated(304)={Interlocked.Read(ref _revalidated)} "
        + $"fetched={Interlocked.Read(ref _fetched)} bytes_saved={Interlocked.Read(ref _saved)} disk={_byteCache?.Bytes ?? 0}/{_byteCache?.LimitBytes ?? DiskCache.DefaultLimitBytes}";

    private bool Cacheable(Uri uri)
    {
        if (_byteCache is null || uri.GetLeftPart(UriPartial.Authority) != BaseUri.GetLeftPart(UriPartial.Authority)
            || uri.UserInfo.Length != 0) return false;
        foreach (var part in uri.Query.TrimStart('?').Split('&'))
        {
            var name = Uri.UnescapeDataString(part.Split('=')[0]).ToLowerInvariant();
            if (name is "password" or "authorization" or "cookie" or "av_session" or "token" or "access_token") return false;
        }
        string p = uri.AbsolutePath;
        return p.StartsWith("/assets/animation-clips/", StringComparison.Ordinal) || p == "/assets/animation-rig"
            || p.StartsWith("/assets/props/", StringComparison.Ordinal) || p.StartsWith("/assets/doors/", StringComparison.Ordinal)
            || p.StartsWith("/assets/surface-textures/", StringComparison.Ordinal) || p.StartsWith("/assets/audio/", StringComparison.Ordinal)
            || p.StartsWith("/static/client3d/models/", StringComparison.Ordinal)
            || (p.StartsWith("/characters/", StringComparison.Ordinal) && (p.Contains("/model3d/file", StringComparison.Ordinal)
                || p.Contains("/model3d/texture", StringComparison.Ordinal) || p.Contains("/images/", StringComparison.Ordinal)))
            || ((p.StartsWith("/play/locations/", StringComparison.Ordinal) || p.StartsWith("/play/rooms/", StringComparison.Ordinal))
                && p.EndsWith("/model", StringComparison.Ordinal));
    }

    private async Task<byte[]?> FetchBytes(string url, bool allowMissing = false)
    {
        var uri = Relative(url);
        string key = uri.PathAndQuery;
        bool cacheable = Cacheable(uri);
        // Per-key serialisation coalesces a fresh hit without serialising unrelated model/clip downloads.
        var gate = cacheable ? _byteLocks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1)) : null;
        if (gate is not null) await gate.WaitAsync();
        try
        {
            var found = cacheable ? await Task.Run(() => _byteCache!.Read(key)) : null;
            if (found is { } hit && (hit.Entry.Immutable || hit.Entry.FreshUntil > _byteCache!.Now))
            {
                Interlocked.Increment(ref _cacheHits); Interlocked.Add(ref _saved, hit.Body.Length);
                return hit.Body;
            }
            using var req = new HttpRequestMessage(HttpMethod.Get, uri);
            if (found?.Entry.Etag is { } etag) req.Headers.TryAddWithoutValidation("If-None-Match", etag);
            double started = MonotonicMs;
            using var res = await _http.SendAsync(req);
            if (res.StatusCode == HttpStatusCode.NotModified && found is { } cached)
            {
                Measurements.Add(BootMeasurements.Category(uri.AbsolutePath), "download", MonotonicMs - started, 1);
                var policy = HttpCachePolicy.From(res, _byteCache!.Now, cached.Entry.CacheControl);
                await Task.Run(() => _byteCache.Refresh(key, res.Headers.ETag?.ToString() ?? cached.Entry.Etag, policy));
                Interlocked.Increment(ref _revalidated); Interlocked.Add(ref _saved, cached.Body.Length);
                return cached.Body;
            }
            if (allowMissing && res.StatusCode == HttpStatusCode.NotFound) return null;
            await EnsureOk(res, uri.AbsolutePath);
            var body = await res.Content.ReadAsByteArrayAsync();
            Measurements.Add(BootMeasurements.Category(uri.AbsolutePath), "download", MonotonicMs - started, 1, body.Length);
            Interlocked.Increment(ref _fetched);
            if (cacheable) await Task.Run(() => _byteCache!.Store(key, body, res.Headers.ETag?.ToString(), HttpCachePolicy.From(res, _byteCache.Now)));
            return body;
        }
        finally { gate?.Release(); }
    }
}
