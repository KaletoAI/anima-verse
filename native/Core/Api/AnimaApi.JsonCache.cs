using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Cache;

namespace AnimaNative.Api;

/// <summary>Task 63 / E10-T2, P3-R32/R33: scene fingerprints revalidate every access; terrain JSON uses
/// content signatures learned from live indexes. locations_rev never enters persistence. The shared DiskCache
/// supplies origin isolation, integrity and the 4 GiB LRU; signature reuse does not grant HTTP immutability.</summary>
public sealed partial class AnimaApi
{
    private sealed record SignatureStamp(string Sig);
    private readonly SemaphoreSlim _jsonSignatures = new(1, 1);
    private readonly SemaphoreSlim _layerRefresh = new(1, 1);
    private SignatureStamp? _heightStamp, _heightReadyStamp, _layerStamp, _terrainStamp;
    private string _mapHeightSig = "";
    private long _layerPollVersion, _layerIndexVersion;
    private static string PayloadSig(JsonElement root, string name = "sig")
        => root.ValueKind == JsonValueKind.Object && root.TryGetProperty(name, out var s) && s.ValueKind == JsonValueKind.String
            ? s.GetString() ?? "" : "";
    private static SignatureStamp? Stamp(SignatureStamp? previous, string sig)
        => sig.Length == 0 ? null : previous?.Sig == sig ? previous : new(sig);
    // Readers never synchronously wait on filesystem publication; index writers await the async gate.
    private SignatureStamp? HeightStamp() => Volatile.Read(ref _heightReadyStamp);
    private SignatureStamp? LayerStamp() => Volatile.Read(ref _layerStamp);
    private SignatureStamp? TerrainStamp() => Volatile.Read(ref _terrainStamp);
    private void UpdateHeightReady() => Volatile.Write(ref _heightReadyStamp,
        _mapHeightSig.Length == 0 || _heightStamp?.Sig == _mapHeightSig ? _heightStamp : null);

    /// <summary>Task 63: a poll invalidates in-flight height publications even before the overview reload finishes;
    /// the overview remains the height key authority. A missing/mismatching index disables disk reuse.</summary>
    private async Task ObserveWorldSignatures(JsonElement root)
    {
        await _jsonSignatures.WaitAsync();
        try
        {
            string height = PayloadSig(root, "height_sig");
            if (_mapHeightSig != height)
            {
                _mapHeightSig = height;
                if (_heightStamp is { } old) _heightStamp = new(old.Sig);
            }
            UpdateHeightReady();
            Volatile.Write(ref _terrainStamp, Stamp(_terrainStamp, PayloadSig(root, "terrain_sig")));
            Interlocked.Increment(ref _layerPollVersion);
        }
        finally { _jsonSignatures.Release(); }
    }
    private async Task<JsonDocument> HeightIndex()
    {
        var doc = await GetJson("/play/heightfield");
        await _jsonSignatures.WaitAsync();
        try { _heightStamp = Stamp(_heightStamp, PayloadSig(doc.RootElement)); UpdateHeightReady(); }
        finally { _jsonSignatures.Release(); }
        return doc;
    }
    private async Task<JsonDocument> LayerIndex()
    {
        long poll = Interlocked.Read(ref _layerPollVersion);
        var doc = await GetJson("/play/terrain-layers");
        await _jsonSignatures.WaitAsync();
        try
        {
            Volatile.Write(ref _layerStamp, Stamp(_layerStamp, PayloadSig(doc.RootElement)));
            Interlocked.Exchange(ref _layerIndexVersion, poll);
        }
        finally { _jsonSignatures.Release(); }
        return doc;
    }

    /// <summary>Task 63: room-floor edits can move layers_sig while terrain_sig stands still. After a live
    /// worldmap poll, check the layer index before the next mask lookup so disk hits retain the streamer's
    /// mismatch/re-index discovery. The normal boot index already satisfies this check; no warm mask GETs.</summary>
    private async Task<JsonDocument> FetchLayerMasks(string[] keys)
    {
        if (_byteCache is not null && Interlocked.Read(ref _layerIndexVersion) != Interlocked.Read(ref _layerPollVersion))
        {
            await _layerRefresh.WaitAsync();
            try
            {
                if (Interlocked.Read(ref _layerIndexVersion) != Interlocked.Read(ref _layerPollVersion))
                { using var index = await LayerIndex(); }
            }
            finally { _layerRefresh.Release(); }
        }
        return await FetchSignatureJson("/play/terrain-layers", keys, "tiles", LayerStamp);
    }

    private async Task<JsonDocument?> FetchSceneJson(string path)
    {
        if (_byteCache is null) return await GetJsonOrNull(path);
        var gate = _byteLocks.GetOrAdd(path, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync();
        try
        {
            var found = await Task.Run(() => _byteCache.Read(path));
            using var req = new HttpRequestMessage(HttpMethod.Get, Relative(path));
            if (found?.Entry.Etag is { } etag) req.Headers.TryAddWithoutValidation("If-None-Match", etag);
            double start = MonotonicMs;
            using var res = await _http.SendAsync(req);
            Measurements.Add("JSON", "download", MonotonicMs - start, 1);
            if (res.StatusCode == HttpStatusCode.NotModified && found is { } cached)
            {
                var policy = HttpCachePolicy.From(res, _byteCache.Now, cached.Entry.CacheControl);
                await Task.Run(() => _byteCache.Refresh(path, res.Headers.ETag?.ToString() ?? cached.Entry.Etag, policy));
                Interlocked.Increment(ref _revalidated); Interlocked.Add(ref _saved, cached.Body.Length);
                return await Task.Run(() => ParseCachedJson(cached.Body));
            }
            if (res.StatusCode == HttpStatusCode.NotFound)
            {
                await Task.Run(() => _byteCache.Refresh(path, null, new(false, false, _byteCache.Now, "")));
                return null;
            }
            var doc = await ReadJson(res, path);
            Interlocked.Increment(ref _fetched);
            await Task.Run(() =>
            {
                var policy = HttpCachePolicy.From(res, _byteCache.Now);
                // Scenes require a fingerprint; freshness/immutable headers never skip their conditional request.
                if (res.Headers.ETag is null) policy = policy with { Store = false };
                _byteCache.Store(path, JsonSerializer.SerializeToUtf8Bytes(doc.RootElement), res.Headers.ETag?.ToString(), policy);
            });
            return doc;
        }
        finally { gate.Release(); }
    }

    private JsonDocument ParseCachedJson(byte[] bytes)
    {
        using var parse = Measurements.Time("JSON", "parse");
        return JsonDocument.Parse(bytes);
    }
    private static string SignatureKey(string path, SignatureStamp stamp, string? tile)
        => "json:" + path + "?sig=" + Uri.EscapeDataString(stamp.Sig)
           + (tile is null ? "" : "&tile=" + Uri.EscapeDataString(tile));
    private static string BatchPath(string path, string[]? keys)
        => keys is null ? path : path + "?keys=" + Uri.EscapeDataString(string.Join(",", keys.Select(k => ReplaceFirst(k, ',', ':'))));

    /// <summary>Task 63 / R-1 guard: capture the requested index stamp, split by tile, and publish only while
    /// that SAME stamp is current and response.sig equals it. Mismatches stay in memory. A partial disk hit is
    /// never mixed with another signature: refetch the full request if the missing part races the index.</summary>
    private async Task<JsonDocument> FetchSignatureJson(string path, string[]? keys, string? field,
                                                       Func<SignatureStamp?> current)
    {
        string request = BatchPath(path, keys);
        var stamp = current();
        if (_byteCache is null || stamp is null) return await GetJson(request);
        var gate = _byteLocks.GetOrAdd("json:" + path, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync();
        try
        {
            if (!ReferenceEquals(current(), stamp)) return await GetJson(request);
            var hits = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            JsonElement template = default;
            JsonDocument? whole = null;
            await Task.Run(() =>
            {
                foreach (var tile in keys ?? new string?[] { null })
                {
                    var cached = _byteCache.Read(SignatureKey(path, stamp, tile));
                    if (cached is null) continue;
                    using var doc = ParseCachedJson(cached.Value.Body);
                    var root = doc.RootElement;
                    if (PayloadSig(root) != stamp.Sig) continue;
                    if (tile is null) whole = JsonDocument.Parse(cached.Value.Body);
                    else if (root.TryGetProperty(field!, out var items) && items.TryGetProperty(tile, out var item))
                    { hits[tile] = item.Clone(); if (template.ValueKind == JsonValueKind.Undefined) template = root.Clone(); }
                    else continue;
                    Interlocked.Increment(ref _cacheHits); Interlocked.Add(ref _saved, cached.Value.Body.Length);
                }
            });
            if (!ReferenceEquals(current(), stamp)) { whole?.Dispose(); return await GetJson(request); }
            if (whole is not null) return whole;
            string[]? missing = keys?.Where(k => !hits.ContainsKey(k)).ToArray();
            if (missing is { Length: 0 }) return await Task.Run(() => ParseCachedJson(WithItems(template, field!, hits)));
            string fetchPath = BatchPath(path, missing);
            double start = MonotonicMs;
            using var res = await _http.GetAsync(Relative(fetchPath));
            Measurements.Add("JSON", "download", MonotonicMs - start, 1);
            var downloaded = await ReadJson(res, fetchPath);
            Interlocked.Increment(ref _fetched);
            bool matches = PayloadSig(downloaded.RootElement) == stamp.Sig && ReferenceEquals(current(), stamp);
            if (!matches)
            {
                if (hits.Count == 0) return downloaded;
                downloaded.Dispose();
                return await GetJson(request);
            }
            bool stampMoved = false;
            var result = await Task.Run(async () =>
            {
                var policy = HttpCachePolicy.From(res, _byteCache.Now);
                // Signature reuse is explicit R-1 semantics, never HTTP immutable (R-2).
                policy = policy with { Immutable = false };
                await _jsonSignatures.WaitAsync().ConfigureAwait(false);
                try
                {
                    if (!ReferenceEquals(current(), stamp)) { stampMoved = true; return downloaded; }
                    if (keys is null)
                    {
                        _byteCache.Store(SignatureKey(path, stamp, null), JsonSerializer.SerializeToUtf8Bytes(downloaded.RootElement), null, policy);
                        return downloaded;
                    }
                    if (!downloaded.RootElement.TryGetProperty(field!, out var items) || items.ValueKind != JsonValueKind.Object)
                        return downloaded;
                    foreach (var tile in missing!)
                        if (items.TryGetProperty(tile, out var item))
                        {
                            hits[tile] = item.Clone();
                            _byteCache.Store(SignatureKey(path, stamp, tile),
                                WithItems(downloaded.RootElement, field!, new Dictionary<string, JsonElement> { [tile] = item }), null, policy);
                        }
                    var merged = ParseCachedJson(WithItems(downloaded.RootElement, field!,
                        keys.Where(hits.ContainsKey).ToDictionary(k => k, k => hits[k], StringComparer.Ordinal)));
                    downloaded.Dispose();
                    return merged;
                }
                finally { _jsonSignatures.Release(); }
            });
            if (stampMoved && hits.Count > 0) { result.Dispose(); return await GetJson(request); }
            return result;
        }
        finally { gate.Release(); }
    }

    private static byte[] WithItems(JsonElement template, string field, IReadOnlyDictionary<string, JsonElement> items)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
        {
            writer.WriteStartObject();
            foreach (var property in template.EnumerateObject()) if (property.Name != field) property.WriteTo(writer);
            writer.WritePropertyName(field); writer.WriteStartObject();
            foreach (var (key, item) in items) { writer.WritePropertyName(key); item.WriteTo(writer); }
            writer.WriteEndObject(); writer.WriteEndObject();
        }
        return stream.ToArray();
    }
}
