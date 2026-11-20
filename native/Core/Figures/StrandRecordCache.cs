using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Sync;

namespace AnimaNative.Figures;

/// <summary>What <see cref="StrandRecordCache.Get"/> knows of one record.</summary>
public enum StrandRecordState
{
    /// <summary>Loading, or waiting for the retry time after a passing failure (the browser's <c>undefined</c>).</summary>
    Pending,
    /// <summary>Definitively none: 404, or another record version (the browser's <c>null</c>).</summary>
    None,
    /// <summary>The record (parsed).</summary>
    Ready,
}

/// <summary>
/// figures.ts <c>FigureLibrary.strandRecord</c>: strand records by sha256 (<c>model.hair_strands {url, sha256}</c>),
/// shared by every figure of one model. The URL always serves the CURRENT record with <c>ETag: "&lt;sha256&gt;"</c>
/// (app/routes/characters.py), so an answer whose ETag is not <c>"&lt;sha&gt;"</c> belongs to another model and is never kept
/// under this sha; it, a network error and any other non-2xx stay <see cref="StrandRecordState.Pending"/> and are asked
/// again after <see cref="RetryMs"/>; a 404 is <see cref="StrandRecordState.None"/> for the session; a 200 with the
/// matching ETag is the record when its version is <see cref="StrandSim.RecordVersion"/>, else None
/// (client3d/scripts/smoke_strand_record.mjs [a]–[d]). Godot-free; thread-safe (the fetch may finish on any thread).
/// </summary>
public sealed class StrandRecordCache
{
    /// <summary><c>STRAND_RETRY_MS</c>.</summary>
    public const double RetryMs = 30_000;

    private readonly Func<string, Task<ConditionalAnswer>> _fetch;
    private readonly Func<double> _nowMs;
    private readonly Action<string>? _log;
    private readonly object _lock = new();
    private readonly Dictionary<string, (StrandRecordState State, HairStrandRecord? Record)> _records = new(StringComparer.Ordinal);
    private readonly Dictionary<string, double> _retryAt = new(StringComparer.Ordinal);

    /// <summary>Downloads started (the smoke's <c>downloads</c>).</summary>
    public int Downloads { get; private set; }

    /// <param name="fetch">GET of a server-relative URL: status, ETag and the JSON body (404 / 5xx come back as a
    /// status; a network failure throws).</param>
    public StrandRecordCache(Func<string, Task<ConditionalAnswer>> fetch, Func<double> nowMs, Action<string>? log = null)
    {
        _fetch = fetch;
        _nowMs = nowMs;
        _log = log;
    }

    /// <summary>The smoke's <c>strandRetryAt.set(sha, 0)</c>: the retry time of a sha (tests).</summary>
    public void SetRetryAt(string sha, double ms) { lock (_lock) _retryAt[sha] = ms; }

    /// <summary>The record <paramref name="url"/> / <paramref name="sha256"/> names; the first call (and the first after
    /// the retry time) starts the download.</summary>
    public (StrandRecordState State, HairStrandRecord? Record) Get(string url, string sha256)
    {
        lock (_lock)
        {
            if (_records.TryGetValue(sha256, out var hit)) return hit;
            if (_nowMs() < (_retryAt.TryGetValue(sha256, out var at) ? at : 0)) return (StrandRecordState.Pending, null);
            _records[sha256] = (StrandRecordState.Pending, null);
            Downloads++;
        }
        _ = Load(url, sha256);
        return (StrandRecordState.Pending, null);
    }

    private async Task Load(string url, string sha256)
    {
        try
        {
            var answer = await _fetch(url);
            if (answer.Status == 404) { Settle(sha256, StrandRecordState.None, null); return; }
            if (answer.Status < 200 || answer.Status >= 300) { Later(url, sha256, answer.Status.ToString()); return; }
            if (answer.Etag != $"\"{sha256}\"") { Later(url, sha256, $"ETag {answer.Etag}"); return; }
            HairStrandRecord? record = null;
            if (answer.Body is { ValueKind: JsonValueKind.Object } body)
            {
                try { record = HairStrandRecord.Parse(body); }
                catch (StrandMismatch) { record = null; }
            }
            Settle(sha256, record is not null && record.Version == StrandSim.RecordVersion ? StrandRecordState.Ready : StrandRecordState.None,
                   record is not null && record.Version == StrandSim.RecordVersion ? record : null);
        }
        catch (Exception e)
        {
            Later(url, sha256, e.Message);
        }
    }

    private void Settle(string sha, StrandRecordState state, HairStrandRecord? record)
    {
        lock (_lock) _records[sha] = (state, record);
    }

    private void Later(string url, string sha, string why)
    {
        _log?.Invoke($"[figures] strand record not loadable now, retrying later: {url} {why}");
        lock (_lock)
        {
            _records.Remove(sha);
            _retryAt[sha] = _nowMs() + RetryMs;
        }
    }
}
