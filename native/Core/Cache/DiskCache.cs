using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace AnimaNative.Cache;

/// <summary>Task 62 / E10-T1: Godot-free persistent byte store, inventory §6 T1 / R-4.
/// A caller supplies the globalized user://cache root. Only version trees below it are discarded.
/// Bodies and index use temp + rename; content-addressed body names preserve the old index across a crash.
/// SHA-256 detects same-length corruption as well as truncation. One instance owns an origin during a load;
/// the instance lock protects concurrent workers. IO failures degrade to misses, never failed boots.</summary>
public sealed class DiskCache : IDisposable
{
    public const int FormatVersion = 1;
    public const long DefaultLimitBytes = 4L * 1024 * 1024 * 1024;
    public sealed record Entry(string Key, string File, long Bytes, string Digest, string? Etag,
        string CacheControl, bool Immutable, DateTimeOffset StoredAt, DateTimeOffset FreshUntil, DateTimeOffset LastUsed);
    private sealed record Index(int Version, List<Entry> Entries);
    private readonly object _gate = new();
    private readonly Dictionary<string, Entry> _entries = new(StringComparer.Ordinal);
    private readonly object _bodyGate = new();
    // Each indexed entry and each pending publication owns a reference. Deletion cannot race a prepared body.
    private readonly Dictionary<string, int> _bodyReferences = new(StringComparer.Ordinal);
    private readonly JsonSerializerOptions _json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private readonly Func<DateTimeOffset> _now;
    private readonly int _version;
    private readonly string _root;
    private const string ClearMarker = "pending_clear";
    public sealed record Stats(long Bytes, long LimitBytes, int Entries);
    private Stats _snapshot;
    private bool _pendingClear, _dirty;
    private volatile bool _disposed;
    private Timer? _flushTimer;
    private readonly ConditionalWeakTable<byte[], Entry> _knownBodies = new();
    /// <summary>Task 67 #3: the frame thread reads one immutable snapshot, without locks, file IO or enumeration.</summary>
    public Stats Readout => Volatile.Read(ref _snapshot);
    private void PublishReadout() => Volatile.Write(ref _snapshot, _pendingClear
        ? new(0, LimitBytes, 0) : new(_entries.Values.Sum(e => e.Bytes), LimitBytes, _entries.Count));
    /// <summary>Task 67 #3: acknowledge the durable clear marker before zeroing the published readout.</summary>
    public void RequestClear()
    {
        lock (_gate)
        {
            Atomic(Path.Combine(_root, ClearMarker), new byte[] { 1 });
            _pendingClear = true; PublishReadout();
        }
    }
    /// <summary>Call once per process, before creating stores or starting worker loads.
    /// Only owned version trees are removed; the marker survives an interrupted/failed clear.
    /// False disables disk caching for this process, preserving a usable cold-start path on IO failure.</summary>
    public static bool PrepareRoot(string root, bool clear = false)
    {
        root = Path.GetFullPath(root);
        string marker = Path.Combine(root, ClearMarker);
        try
        {
            if (clear) Atomic(marker, new byte[] { 1 });
            if (!System.IO.File.Exists(marker)) return true;
            foreach (var dir in Directory.GetDirectories(root, "v*"))
                if (int.TryParse(Path.GetFileName(dir).AsSpan(1), out _)) Directory.Delete(dir, true);
            System.IO.File.Delete(marker);
            return true;
        }
        catch (Exception e) when (Io(e)) { return false; }
    }
    public string DirectoryPath { get; }
    public long LimitBytes { get; }
    public long Bytes { get { lock (_gate) return _entries.Values.Sum(e => e.Bytes); } }
    public int Count { get { lock (_gate) return _entries.Count; } }
    public DateTimeOffset Now => _now();

    public DiskCache(string root, Uri origin, long limitBytes = DefaultLimitBytes, int formatVersion = FormatVersion,
                     Func<DateTimeOffset>? now = null)
    {
        LimitBytes = Math.Max(0, limitBytes); _version = formatVersion; _now = now ?? (() => DateTimeOffset.UtcNow);
        _snapshot = new(0, LimitBytes, 0);
        root = _root = Path.GetFullPath(root);
        DirectoryPath = Path.Combine(root, "v" + formatVersion, OriginHash(origin));
        try
        {
            Directory.CreateDirectory(root);
            _pendingClear = System.IO.File.Exists(Path.Combine(root, ClearMarker));
            foreach (var dir in Directory.GetDirectories(root, "v*"))
                if (int.TryParse(Path.GetFileName(dir).AsSpan(1), out int version) && version != formatVersion)
                    Directory.Delete(dir, true);
            Directory.CreateDirectory(DirectoryPath);
            string path = Path.Combine(DirectoryPath, "index.json");
            if (System.IO.File.Exists(path))
            {
                try
                {
                    var index = JsonSerializer.Deserialize<Index>(System.IO.File.ReadAllBytes(path), _json);
                    if (index?.Version == formatVersion && index.Entries is not null)
                        foreach (var e in index.Entries)
                            if (Valid(e)) _entries[e.Key] = e;
                }
                catch (Exception e) when (e is JsonException or ArgumentException or NullReferenceException) { }
            }
            foreach (var e in _entries.Values) RetainBody(e.File);
            // Unindexed bodies and interrupted writes cannot be resurrected after a crash.
            var kept = _entries.Values.Select(e => e.File).ToHashSet(StringComparer.Ordinal);
            foreach (var file in Directory.GetFiles(DirectoryPath))
                if (Path.GetFileName(file) != "index.json" && !kept.Contains(Path.GetFileName(file))) System.IO.File.Delete(file);
            Evict(); Save();
        }
        catch (Exception e) when (Io(e)) { _entries.Clear(); PublishReadout(); }
    }

    /// <summary>Task 67 #2: validate bodies outside the worker lock, then recheck publication before returning.
    /// LRU touches are memory-only on this path; one delayed worker flush batches a busy warm load.</summary>
    public (Entry Entry, byte[] Body)? Read(string key)
    {
        Entry e;
        lock (_gate) { if (!_entries.TryGetValue(key, out e!)) return null; }
        byte[]? body = null;
        try
        {
            var bytes = System.IO.File.ReadAllBytes(Path.Combine(DirectoryPath, e.File));
            if (bytes.LongLength == e.Bytes && Hash(bytes) == e.Digest) body = bytes;
        }
        catch (Exception ex) when (Io(ex)) { }
        lock (_gate)
        {
            if (!_entries.TryGetValue(key, out var current) || current.File != e.File) return null;
            if (body is null)
            {
                RemoveCore(key); PublishReadout(); MarkDirty(); return null;
            }
            e = current with { LastUsed = Now }; _entries[key] = e;
            Remember(body, e); MarkDirty();
            return (e, body);
        }
    }

    /// <summary>Task 67 #2: only the exact bytes validated/read or published by this store may reuse its digest.
    /// Callers treat returned HTTP byte arrays as immutable. Unknown arrays and replaced/no-store entries miss;
    /// weak keys retain neither large bodies nor identities beyond their consumers' lifetimes.</summary>
    public Entry? KnownEntry(string key, byte[] body)
    {
        lock (_gate)
            return _knownBodies.TryGetValue(body, out var known) && known.Key == key
                && _entries.TryGetValue(key, out var current) && current.Digest == known.Digest
                ? current : null;
    }
    private void Remember(byte[] body, Entry entry)
    {
        _knownBodies.Remove(body); _knownBodies.Add(body, entry);
    }

    /// <summary>
    /// Publish <paramref name="body"/> for <paramref name="key"/>. Hashing and the body write run OUTSIDE the store lock
    /// (temp + rename, no fsync: a torn body fails its digest on read and is a miss); the lock only updates the entry
    /// and marks the index dirty. Holding the lock across hash + fsync + a full index rewrite serialised ~300
    /// concurrent model downloads at boot and starved the thread pool (user boot 2026-10-29: scenes 6 → 30 s, tiles
    /// 28 → 212 s).
    /// </summary>
    public void Store(string key, byte[] body, string? etag, HttpCachePolicy policy, string extension = ".bin")
    {
        if (extension is not (".bin" or ".res" or ".json")) throw new ArgumentException("Unsupported cache extension", nameof(extension));
        if (_disposed) return;
        if (!policy.Store || body.LongLength > LimitBytes)
        {
            lock (_gate) { if (!_disposed && _entries.ContainsKey(key)) { RemoveCore(key); PublishReadout(); MarkDirty(); } }
            return;
        }
        string digest = Hash(body), file = Hash(key) + "-" + digest + extension;
        RetainBody(file);
        Entry? old = null;
        bool published = false;
        try
        {
            WriteBody(Path.Combine(DirectoryPath, file), body);
            lock (_gate)
            {
                if (_disposed) return;
                _entries.TryGetValue(key, out old);
                _entries[key] = new(key, file, body.LongLength, digest, etag, policy.CacheControl, policy.Immutable,
                    Now, policy.FreshUntil, Now);
                published = true; // The pending body reference now belongs to the indexed entry.
                Evict(); PublishReadout(); MarkDirty();
                if (_entries.TryGetValue(key, out var stored)) Remember(body, stored);
            }
        }
        catch (Exception ex) when (Io(ex)) { }
        finally
        {
            // Obsolete body cleanup stays outside the metadata lock. A newer or pending Store may own it now.
            if (published) { if (old is not null) ReleaseBody(old.File); }
            else ReleaseBody(file);
        }
    }

    /// <summary>Task 62: a 304 updates validators/freshness atomically without rewriting hundreds of MiB of GLBs.</summary>
    public void Refresh(string key, string? etag, HttpCachePolicy policy)
    {
        lock (_gate)
        {
            if (_disposed) return;
            try
            {
                if (!policy.Store) RemoveCore(key);
                else if (_entries.TryGetValue(key, out var e))
                    _entries[key] = e with { Etag = etag, CacheControl = policy.CacheControl,
                        Immutable = policy.Immutable, StoredAt = Now, FreshUntil = policy.FreshUntil, LastUsed = Now };
                PublishReadout(); MarkDirty();   // batched like Store; ~300 revalidations at a warm boot
            }
            catch (Exception ex) when (Io(ex)) { }
        }
    }

    private bool Valid(Entry e)
        => e is not null && e.Key is not null && e.Digest is not null && e.Digest.Length == 64
           && e.Bytes >= 0 && new[] { ".bin", ".res", ".json" }.Any(ext => e.File == Hash(e.Key) + "-" + e.Digest + ext)
           && e.Digest.All(Uri.IsHexDigit) && System.IO.File.Exists(Path.Combine(DirectoryPath, e.File));
    private void Evict()
    {
        long total = _entries.Values.Sum(e => e.Bytes);
        foreach (var e in _entries.Values.OrderBy(e => e.LastUsed).ThenBy(e => e.Key, StringComparer.Ordinal).ToArray())
        {
            if (total <= LimitBytes) break;
            RemoveCore(e.Key); total -= e.Bytes;
        }
    }
    private void RemoveCore(string key)
    {
        if (_entries.Remove(key, out var e)) ReleaseBody(e.File);
    }
    private void RetainBody(string file)
    {
        lock (_bodyGate) _bodyReferences[file] = _bodyReferences.GetValueOrDefault(file) + 1;
    }
    private void ReleaseBody(string file)
    {
        lock (_bodyGate)
        {
            int remaining = _bodyReferences[file] - 1;
            if (remaining > 0) { _bodyReferences[file] = remaining; return; }
            _bodyReferences.Remove(file);
            try { System.IO.File.Delete(Path.Combine(DirectoryPath, file)); } catch (Exception ex) when (Io(ex)) { }
        }
    }
    /// <summary>The index is written (temp + fsync + rename) by the five-second one-shot flush after any change and on
    /// dispose — never per entry. A crash loses at most the last seconds of entries: their bodies are unindexed and
    /// deleted at the next start, so they are fetched again; a stale or torn body never passes its digest.</summary>
    private void Save()
    {
        PublishReadout(); _dirty = true;
        Atomic(Path.Combine(DirectoryPath, "index.json"),
            JsonSerializer.SerializeToUtf8Bytes(new Index(_version, _entries.Values.ToList()), _json));
        _dirty = false; _flushTimer?.Change(Timeout.Infinite, Timeout.Infinite);
    }
    private void MarkDirty()
    {
        if (_dirty || _disposed) return;
        _dirty = true;
        _flushTimer ??= new Timer(_ => FlushIndex(), null, Timeout.Infinite, Timeout.Infinite);
        _flushTimer.Change(TimeSpan.FromSeconds(5), Timeout.InfiniteTimeSpan);
    }
    /// <summary>Task 67 #2: API shutdown flushes remaining touches; IO failure still degrades to a safe miss.
    /// A removed/version-cleared tree must never be recreated by a delayed old store.</summary>
    public void FlushIndex()
    {
        lock (_gate)
        {
            if (_disposed || !_dirty || !Directory.Exists(DirectoryPath)) return;
            try { Save(); }
            catch (Exception ex) when (Io(ex)) { }
        }
    }
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            FlushIndex(); _disposed = true; _flushTimer?.Dispose();
        }
    }
    /// <summary>A cache body: temp + rename without fsync (the digest check on read catches a torn write).</summary>
    private static void WriteBody(string path, byte[] data)
    {
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            System.IO.File.WriteAllBytes(temp, data);
            System.IO.File.Move(temp, path, true);
        }
        finally { if (System.IO.File.Exists(temp)) System.IO.File.Delete(temp); }
    }

    private static void Atomic(string path, byte[] data)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(data); stream.Flush(true); }
            System.IO.File.Move(temp, path, true);
        }
        finally { if (System.IO.File.Exists(temp)) System.IO.File.Delete(temp); }
    }
    private static bool Io(Exception e) => e is IOException or UnauthorizedAccessException;
    /// <summary>Stable origin directory key, shared with local title snapshots.</summary>
    public static string OriginHash(Uri origin) => Hash(origin.GetLeftPart(UriPartial.Authority));

    private static string Hash(string text) => Hash(Encoding.UTF8.GetBytes(text));
    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
}
