using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Cache;
using Godot;

namespace AnimaNative.Figures;

/// <summary>Task 64 / E10-T3: derived resources and JSON sidecars in the SAME DiskCache as HTTP bodies.
/// ResourceSaver/Loader run on the engine thread; disk integrity and JSON run on workers. A sidecar is published
/// last and names the resource's SHA-256, so eviction or interrupted publication is a miss. No path is trusted
/// from JSON. Temporary engine serialization files are unique and always removed; the indexed .res/.json bodies
/// alone persist. Version keys include Godot's version; old code entries age out under the existing v1 LRU.</summary>
public sealed class FigureCache(DiskCache disk)
{
    public DiskCache Disk { get; } = disk;
    public string Engine { get; } = EngineVersion();
    public int Imports { get; set; }
    public int Plans { get; set; }
    public int Fits { get; set; }
    public int ImportedHits { get; set; }
    public int PlanHits { get; set; }
    public int FitHits { get; set; }
    public double CachedMs { get; private set; }
    public double ImportMs { get; set; }
    public double FitMs { get; set; }
    private sealed record ResourceData<T>(string Hash, string AnimationDigest, T Data);
    public sealed record SourceData(string Url, string Validator, int ImportVersion, string[] Bones, Quat[] Rotations,
        V3[] Positions, Dictionary<string, int> RotationTracks, Dictionary<string, int> PositionTracks,
        Dictionary<string, TrackData> RotationKeys, Dictionary<string, TrackData> PositionKeys, double? HipsMedian, double Length);
    public sealed record TrackData(Animation.InterpolationType Interp, double[] Times, Quat[]? Rotations, V3[]? Positions);
    public sealed record RigBone(string Key, Quat World, Quat Parent, string? ParentBone, V3 Position);
    public sealed record RigData(List<RigBone> Bones, double? Hips);
    public sealed record FitData(string BoundDigest, long Keys, ClipExtras? Extras, int FitVersion);

    private static string EngineVersion() => Godot.Engine.GetVersionInfo()["string"].AsString();
    /// <summary>Only reuse validated HTTP input. no-store, foreign origins and credential URLs never produce an
    /// identity here. Content SHA supplements ETag, covering a stale-v response and validators reused by a server.</summary>
    public Task<string?> IdentityAsync(string url, byte[] bytes) => Task.Run(() =>
    {
        // Task 67 #2: keep worker-lock contention off the engine thread; reuse this validated input's digest.
        var entry = Disk.KnownEntry(url, bytes);
        return entry is not null ? DerivedKeys.Of(url, entry.Etag, entry.Digest) : null;
    });
    public string ImportKey(string url, string identity)
        => "derived:import:" + DerivedKeys.Of(url, identity, DerivedKeys.ClipImportVersion, Engine);

    public async Task<T?> ReadJson<T>(string key) where T : class
    {
        return await Task.Run(() =>
        {
            try { return Disk.Read(key) is { } h ? JsonSerializer.Deserialize<T>(h.Body) : null; }
            catch (JsonException) { return null; }
        });
    }
    public Task WriteJson<T>(string key, T value) => Task.Run(() =>
        Disk.Store(key, JsonSerializer.SerializeToUtf8Bytes(value), null, new(true, true, Disk.Now, "immutable"), ".json"));

    public sealed record PreparedResource<T>(string Path, string AnimationDigest, T Data) : IDisposable
    {
        public void Dispose() => DeleteTemporary(Path);
    }

    /// <summary>Task 64: prefetch imports concurrently with the download queue. All disk and sidecar work is done
    /// before the main-thread import loop; a warm library does not pay one asynchronous frame turn per file.</summary>
    public Task<PreparedResource<T>?> PrepareAnimation<T>(string key) where T : class => Task.Run(() => PrepareCore<T>(key));

    private PreparedResource<T>? PrepareCore<T>(string key) where T : class
    {
        string? temp = null;
        try
        {
            var metadata = Disk.Read(key + ":json");
            var meta = metadata is { } json ? JsonSerializer.Deserialize<ResourceData<T>>(json.Body) : null;
            if (meta?.Data is null) return null;
            var body = Disk.Read(key + ":res");
            if (body is not { } hit || DerivedKeys.Hash(hit.Body) != meta.Hash) return null;
            temp = Path.Combine(Path.GetTempPath(), "anima-resource-" + Guid.NewGuid().ToString("N") + ".res");
            File.WriteAllBytes(temp, hit.Body);
            return new PreparedResource<T>(temp, meta.AnimationDigest, meta.Data);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        { if (temp is not null) DeleteTemporary(temp); return null; }
    }

    public (Animation Animation, T Data)? LoadPrepared<T>(PreparedResource<T> prepared)
    {
        var watch = Stopwatch.StartNew();
        Animation? anim = null;
        using (prepared)
        {
            try
            {
                anim = ResourceLoader.Load<Animation>(prepared.Path, cacheMode: ResourceLoader.CacheMode.Ignore);
                if (anim is null || AnimationDigest(anim) != prepared.AnimationDigest) { anim?.Dispose(); return null; }
                return (anim, prepared.Data);
            }
            catch (InvalidOperationException) { anim?.Dispose(); return null; }
            finally { CachedMs += watch.Elapsed.TotalMilliseconds; }
        }
    }

    /// <summary>Task 64: explicit synchronous fit modes retain their same-call contract, including disk access;
    /// the live Lazy mode always uses workers. Awaiting the synchronous branch completes without yielding.</summary>
    public async Task<(Animation Animation, T Data)?> ReadAnimation<T>(string key, bool synchronous = false) where T : class
    {
        var prepared = synchronous ? PrepareCore<T>(key) : await PrepareAnimation<T>(key);
        return prepared is not null ? LoadPrepared(prepared) : null;
    }

    public async Task WriteAnimation<T>(string key, Animation animation, T data, bool synchronous = false)
    {
        string temp = Path.Combine(Path.GetTempPath(), "anima-resource-" + Guid.NewGuid().ToString("N") + ".res");
        try
        {
            if (ResourceSaver.Save(animation, temp) != Error.Ok) return;
            string animationDigest = AnimationDigest(animation);
            void Publish()
            {
                var bytes = File.ReadAllBytes(temp);
                var meta = new ResourceData<T>(DerivedKeys.Hash(bytes), animationDigest, data);
                Disk.Store(key + ":res", bytes, null, new(true, true, Disk.Now, "immutable"), ".res");
                Disk.Store(key + ":json", JsonSerializer.SerializeToUtf8Bytes(meta), null, new(true, true, Disk.Now, "immutable"), ".json");
            }
            if (synchronous) Publish();
            else await Task.Run(Publish);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        finally { DeleteTemporary(temp); }
    }

    private static void DeleteTemporary(string path)
    {
        try { File.Delete(path); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }

    /// <summary>Task 64: exact final engine content after relock/ground; distinct from the pre-relock BoundClip
    /// digest. The check asserts BOTH against a fresh fit, including transitions, counts and Scale3D tracks.</summary>
    public static string AnimationDigest(Animation animation)
    {
        var hash = new ContentDigest();
        hash.Add(animation.Length); hash.Add((int)animation.LoopMode); hash.Add(animation.GetTrackCount());
        for (int t = 0; t < animation.GetTrackCount(); t++)
        {
            hash.Add(animation.TrackGetPath(t).ToString()); hash.Add((int)animation.TrackGetType(t));
            hash.Add((int)animation.TrackGetInterpolationType(t)); hash.Add(animation.TrackGetKeyCount(t));
            for (int k = 0; k < animation.TrackGetKeyCount(t); k++)
            {
                hash.Add(BitConverter.SingleToInt32Bits(animation.TrackGetKeyTransition(t, k)));
                double time = animation.TrackGetKeyTime(t, k);
                var value = animation.TrackGetKeyValue(t, k);
                if (value.VariantType == Variant.Type.Quaternion) hash.Add(time, value.AsQuaternion());
                else if (value.VariantType == Variant.Type.Vector3) hash.Add(time, value.AsVector3());
                else throw new InvalidOperationException("Unexpected cached animation track type");
            }
        }
        return hash.Finish();
    }

    public static SourceData DataOf(ClipSource src, string identity)
    {
        TrackData Track(SourceTrack t) => new(t.Interp, t.Times, t.Rotations?.Select(RestAdapter.ToQuat).ToArray(),
            t.Positions?.Select(v => new V3(v.X, v.Y, v.Z)).ToArray());
        return new(src.Url, identity, DerivedKeys.ClipImportVersion, src.Bones, src.RestRotations.Select(RestAdapter.ToQuat).ToArray(),
            src.RestPositions.Select(v => new V3(v.X, v.Y, v.Z)).ToArray(), src.RotationTracks, src.PositionTracks,
            src.RotationKeys.ToDictionary(k => k.Key, k => Track(k.Value)), src.PositionKeys.ToDictionary(k => k.Key, k => Track(k.Value)),
            src.HipsMedian, src.Length);
    }
    public static ClipSource Restore(Animation animation, SourceData data, ClipSourceEntry entry)
    {
        SourceTrack Track(TrackData t) => new(t.Interp, t.Times, t.Rotations?.Select(RestAdapter.ToGodot).ToArray(),
            t.Positions?.Select(v => new Vector3((float)v.X, (float)v.Y, (float)v.Z)).ToArray());
        return new ClipSource
        {
            Kind = entry.Kind, Set = entry.Set, Url = entry.Url, Loop = entry.Loops, RootMotion = entry.RootMotion, KeepFacing = entry.KeepFacing,
            HeightOffsets = entry.HeightOffsets, Anim = animation, Bones = data.Bones,
            RestRotations = data.Rotations.Select(RestAdapter.ToGodot).ToArray(),
            RestPositions = data.Positions.Select(v => new Vector3((float)v.X, (float)v.Y, (float)v.Z)).ToArray(),
            RotationTracks = data.RotationTracks, PositionTracks = data.PositionTracks, Length = data.Length, HipsMedian = data.HipsMedian,
            RotationKeys = data.RotationKeys.ToDictionary(k => k.Key, k => Track(k.Value)),
            PositionKeys = data.PositionKeys.ToDictionary(k => k.Key, k => Track(k.Value)), CacheIdentity = data.Validator,
        };
    }
    public string Describe() => $"figures cache: FBX imports={Imports} plan computations={Plans} fits={Fits} "
        + $"cached(import/plan/fit)={ImportedHits}/{PlanHits}/{FitHits} import={ImportMs:0} fit={FitMs:0} cached={CachedMs:0} ms";
}
