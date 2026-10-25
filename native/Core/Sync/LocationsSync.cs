using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Sync;

/// <summary>A conditional GET's answer: the status, the <c>ETag</c> header ("" when absent) and the parsed body (200 only).</summary>
public readonly record struct ConditionalAnswer(int Status, string Etag, JsonElement? Body);

/// <summary><c>/world/locations?view=3d</c> as last delivered, with the ETag it came with.</summary>
public sealed record Locations3d(string Etag, JsonElement Root);

/// <summary>
/// <c>getLocations3d</c> of client3d/src/api.ts: a conditional GET (<c>If-None-Match</c> with the cached ETag),
/// single-flight. A 304 answers the CACHED data with ITS ETag — another caller may not have applied that data
/// yet; a 304 with nothing cached is an error like any other non-2xx (the browser's <c>json()</c> throws on it).
/// </summary>
public sealed class LocationsCache
{
    private readonly Func<string?, Task<ConditionalAnswer>> _fetch;
    private Locations3d? _cache;
    private Task<Locations3d>? _inFlight;

    /// <param name="fetch">GET with <c>If-None-Match: etag</c> when the argument is non-null.</param>
    public LocationsCache(Func<string?, Task<ConditionalAnswer>> fetch) => _fetch = fetch;

    public Locations3d? Cached => _cache;
    /// <summary>Requests sent (the tests count single-flight with it).</summary>
    public int Requests { get; private set; }

    public Task<Locations3d> GetAsync()
    {
        if (_inFlight is not null) return _inFlight;
        var t = RunAsync();
        if (!t.IsCompleted)
        {
            _inFlight = t;
            t.ContinueWith(_ => { if (ReferenceEquals(_inFlight, t)) _inFlight = null; }, CancellationToken.None,
                           TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        }
        return t;
    }

    private async Task<Locations3d> RunAsync()
    {
        Requests++;
        var answer = await _fetch(_cache?.Etag);
        if (answer.Status == 304 && _cache is not null) return _cache;
        if (answer.Status is < 200 or > 299 || answer.Body is not { } body)
            throw new InvalidOperationException($"HTTP {answer.Status} on /world/locations");
        _cache = new Locations3d(answer.Etag, body);
        return _cache;
    }
}

/// <summary>
/// The location re-sync of client3d/src/main.ts (<c>syncLocations</c>): the applied ETag and the revision it
/// names (<see cref="RevOf"/>). A poll whose <c>locations_rev</c> differs from <see cref="Rev"/> syncs
/// (<see cref="Differs"/>), so does a timer every <see cref="ResyncMs"/>, and a poll that brings a new placeable
/// location forces it. Data is applied only when forced or when the ETag changed; a failed request keeps the
/// applied revision (the server was briefly away).
/// </summary>
public sealed class LocationsSync
{
    public const double ResyncMs = 120_000;

    private readonly LocationsCache _cache;
    private readonly Action<Locations3d> _apply;

    public LocationsSync(LocationsCache cache, Action<Locations3d> apply)
    {
        _cache = cache;
        _apply = apply;
    }

    public string AppliedEtag { get; private set; } = "";
    public string Rev { get; private set; } = "";
    /// <summary>How often data was applied (the log and the tests).</summary>
    public int Applied { get; private set; }

    /// <summary>The boot's first answer: applied by the world build itself.</summary>
    public void Seed(Locations3d first)
    {
        AppliedEtag = first.Etag;
        Rev = RevOf(first.Etag);
    }

    public async Task SyncAsync(bool force = false)
    {
        try
        {
            var l = await _cache.GetAsync();
            if (force || l.Etag != AppliedEtag)
            {
                _apply(l);
                Applied++;
                AppliedEtag = l.Etag;
            }
            Rev = RevOf(l.Etag);
        }
        catch (Exception)
        {
            // Server briefly unavailable; retain the applied revision.
        }
    }

    /// <summary><c>map.locations_rev !== locationsRev</c> — a missing revision differs from every string.</summary>
    public bool Differs(string? mapRev) => mapRev != Rev;

    /// <summary><c>etag.replace(/^W\//, '').replace(/^"|"$/g, '')</c>.</summary>
    public static string RevOf(string etag)
    {
        var s = etag.StartsWith("W/", StringComparison.Ordinal) ? etag[2..] : etag;
        if (s.StartsWith('"')) s = s[1..];
        if (s.EndsWith('"')) s = s[..^1];
        return s;
    }

    /// <summary>The worldmap's <c>locations_rev</c> when it is a string, else null.</summary>
    public static string? MapRev(JsonElement map)
        => map.ValueKind == JsonValueKind.Object && map.TryGetProperty("locations_rev", out var r)
           && r.ValueKind == JsonValueKind.String ? r.GetString() : null;
}
