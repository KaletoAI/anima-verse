using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace AnimaNative.Cache;

/// <summary>Task 62 / E10-T1: Godot-free persistent byte store, inventory §6 T1 / R-4.
/// A caller supplies the globalized user://cache root. Only version trees below it are discarded.
/// Bodies and index use temp + rename; content-addressed body names preserve the old index across a crash.
/// SHA-256 detects same-length corruption as well as truncation. One instance owns an origin during a load;
/// the instance lock protects concurrent workers. IO failures degrade to misses, never failed boots.</summary>
public sealed class DiskCache
{
    public const int FormatVersion = 1;
    public const long DefaultLimitBytes = 4L * 1024 * 1024 * 1024;
    public sealed record Entry(string Key, string File, long Bytes, string Digest, string? Etag,
        string CacheControl, bool Immutable, DateTimeOffset StoredAt, DateTimeOffset FreshUntil, DateTimeOffset LastUsed);
    private sealed record Index(int Version, List<Entry> Entries);
    private readonly object _gate = new();
    private readonly Dictionary<string, Entry> _entries = new(StringComparer.Ordinal);
    private readonly JsonSerializerOptions _json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private readonly Func<DateTimeOffset> _now;
    private readonly int _version;
    public string DirectoryPath { get; }
    public long LimitBytes { get; }
    public long Bytes { get { lock (_gate) return _entries.Values.Sum(e => e.Bytes); } }
    public int Count { get { lock (_gate) return _entries.Count; } }
    public DateTimeOffset Now => _now();

    public DiskCache(string root, Uri origin, long limitBytes = DefaultLimitBytes, int formatVersion = FormatVersion,
                     Func<DateTimeOffset>? now = null)
    {
        LimitBytes = Math.Max(0, limitBytes); _version = formatVersion; _now = now ?? (() => DateTimeOffset.UtcNow);
        root = Path.GetFullPath(root);
        DirectoryPath = Path.Combine(root, "v" + formatVersion, Hash(origin.GetLeftPart(UriPartial.Authority)));
        try
        {
            Directory.CreateDirectory(root);
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
            // Unindexed bodies and interrupted writes cannot be resurrected after a crash.
            var kept = _entries.Values.Select(e => e.File).ToHashSet(StringComparer.Ordinal);
            foreach (var file in Directory.GetFiles(DirectoryPath))
                if (Path.GetFileName(file) != "index.json" && !kept.Contains(Path.GetFileName(file))) System.IO.File.Delete(file);
            Evict(); Save();
        }
        catch (Exception e) when (Io(e)) { _entries.Clear(); }
    }

    public (Entry Entry, byte[] Body)? Read(string key)
    {
        lock (_gate)
        {
            if (!_entries.TryGetValue(key, out var e)) return null;
            try
            {
                var body = System.IO.File.ReadAllBytes(Path.Combine(DirectoryPath, e.File));
                if (body.LongLength != e.Bytes || Hash(body) != e.Digest) { RemoveCore(key); Save(); return null; }
                e = e with { LastUsed = Now }; _entries[key] = e; Save();
                return (e, body);
            }
            catch (Exception ex) when (Io(ex)) { RemoveCore(key); return null; }
        }
    }

    public void Store(string key, byte[] body, string? etag, HttpCachePolicy policy)
    {
        lock (_gate)
        {
            try
            {
                if (!policy.Store || body.LongLength > LimitBytes) { RemoveCore(key); Save(); return; }
                string digest = Hash(body), file = Hash(key) + "-" + digest + ".bin";
                Atomic(Path.Combine(DirectoryPath, file), body);
                _entries.TryGetValue(key, out var old);
                _entries[key] = new(key, file, body.LongLength, digest, etag, policy.CacheControl, policy.Immutable,
                    Now, policy.FreshUntil, Now);
                Evict(); Save();
                if (old is not null && old.File != file) System.IO.File.Delete(Path.Combine(DirectoryPath, old.File));
            }
            catch (Exception ex) when (Io(ex)) { }
        }
    }

    /// <summary>Task 62: a 304 updates validators/freshness atomically without rewriting hundreds of MiB of GLBs.</summary>
    public void Refresh(string key, string? etag, HttpCachePolicy policy)
    {
        lock (_gate)
        {
            try
            {
                if (!policy.Store) RemoveCore(key);
                else if (_entries.TryGetValue(key, out var e))
                    _entries[key] = e with { Etag = etag, CacheControl = policy.CacheControl,
                        Immutable = policy.Immutable, StoredAt = Now, FreshUntil = policy.FreshUntil, LastUsed = Now };
                Save();
            }
            catch (Exception ex) when (Io(ex)) { }
        }
    }

    private bool Valid(Entry e)
        => e is not null && e.Key is not null && e.Digest is not null && e.Digest.Length == 64
           && e.Bytes >= 0 && e.File == Hash(e.Key) + "-" + e.Digest + ".bin"
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
        if (_entries.Remove(key, out var e))
            try { System.IO.File.Delete(Path.Combine(DirectoryPath, e.File)); } catch (Exception ex) when (Io(ex)) { }
    }
    private void Save() => Atomic(Path.Combine(DirectoryPath, "index.json"),
        JsonSerializer.SerializeToUtf8Bytes(new Index(_version, _entries.Values.ToList()), _json));
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
    private static string Hash(string text) => Hash(Encoding.UTF8.GetBytes(text));
    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
}
