using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Figures;

/// <summary>
/// A clip FBX imported once: its animation plus the skeleton it was keyed on (bone names, the per-bone node
/// defaults), and the listing flags of the file it came from. Shared by every figure; <see cref="Kind"/> is the
/// committed kind (<c>clip.name = kind</c>).
/// </summary>
public sealed record ClipSource
{
    /// <summary>Task 64: validated input identity; null disables persistent dependants.</summary>
    public string? CacheIdentity { get; init; }
    public required string Kind { get; init; }
    public required string Set { get; init; }
    public required string Url { get; init; }
    /// <summary>The listing's loop flag of THIS file (missing = loop).</summary>
    public required bool Loop { get; init; }
    /// <summary>The file carries a root travel (<c>root_motion.mode</c> keep/foot_lock); its path is built at fit time.</summary>
    public required bool RootMotion { get; init; }
    public bool KeepFacing { get; init; }
    /// <summary>Saved reference-height corrections of this exact file and set.</summary>
    public ClipHeightOffsets HeightOffsets { get; init; }
    public required Animation Anim { get; init; }
    public required string[] Bones { get; init; }
    /// <summary>The bone's node default — for a clip FBX that is the take's first frame (Godot stores it as the rest).</summary>
    public required Quaternion[] RestRotations { get; init; }
    public required Vector3[] RestPositions { get; init; }
    /// <summary>Bone name → index of its rotation track in <see cref="Anim"/>.</summary>
    public required Dictionary<string, int> RotationTracks { get; init; }
    public required Dictionary<string, int> PositionTracks { get; init; }
    /// <summary><c>hipsTrackMedian</c> of the file (its hips position keys, or the constant default Godot kept), null without hips.</summary>
    public double? HipsMedian { get; init; }
    public int RotationTrackCount => RotationTracks.Count;
    /// <summary><see cref="Anim"/>'s length as Godot keeps it.</summary>
    public required double Length { get; init; }
    /// <summary>
    /// The keys of <see cref="RotationTracks"/> / <see cref="PositionTracks"/> read out of <see cref="Anim"/> ONCE at import
    /// (Task 35b): the retarget's key math then runs on a worker thread without touching the engine
    /// (<see cref="ClipLibrary.Compute"/>). The very values the engine returns — times as doubles, values as floats.
    /// </summary>
    public required Dictionary<string, SourceTrack> RotationKeys { get; init; }
    public required Dictionary<string, SourceTrack> PositionKeys { get; init; }
}

/// <summary>One source track's keys as plain arrays (rotations or positions, never both).</summary>
public sealed record SourceTrack(Animation.InterpolationType Interp, double[] Times, Quaternion[]? Rotations, Vector3[]? Positions);

/// <summary>What one clip produced on one skeleton: the bound animation (null under <see cref="ClipLibrary.MinTracks"/>),
/// its track and key counts, the root path of a root-motion clip (re-locked per rig at fit time, carried by the bridges)
/// and the <see cref="Digest"/> of everything written into the animation (SHA-256 over length, loop mode and every
/// track's path, type, interpolation and key bits, in insertion order): two bound clips with the same digest hold the
/// same keys bit for bit, so one <see cref="Animation"/> can serve both (Task 35, <see cref="FigureManager"/>).</summary>
public sealed record BoundClip(string Kind, Animation? Anim, int Tracks, long Keys, RootPath? RootPath, string? Digest = null);

/// <summary>
/// The server's WHOLE clip library on the native side — client3d's <c>FigureLibrary.load</c>:
///
///   • <b>listing</b> <c>GET /assets/animation-clips</c>: every <c>clips[]</c> entry is a source (a pair half as
///     <c>&lt;kind&gt;__&lt;role&gt;</c>, the kind as the server spells it), with its set, its loop flag (missing =
///     loop) and whether it carries root motion; <c>movement_poses</c> → <see cref="Poses"/>, <c>transition_clips</c>
///     → <see cref="Transitions"/> (the bridges between two clips, <see cref="Figure.Play"/>);
///   • <b>downloads</b> through a <see cref="FocusQueue"/> of width 4 in listing order (distance = list index);
///   • <b>import</b> ONE clip per frame (Godot's runtime <c>FBXDocument</c> builds nodes on the main thread);
///   • <b>commit</b> in listing order (<see cref="ClipLibraryRules.CommitInListOrder"/>): the first file per
///     (kind, set) wins, a failed one leaves its slot to the next; result kind → (set → clip);
///   • per character, <see cref="ClipsFor"/> picks per kind the first file along its set chain
///     <c>[...animation_sets, '']</c> — the loop and root-motion flags of THAT file count.
///
/// <b>Godot drops constant curves.</b> The clip FBX keys 52 bones + the hips translation, but the importer only
/// emits tracks for curves that MOVE and stores the constant value as the node default. The retarget therefore
/// writes a one-key constant track from that default for every clip bone the target has — the file's track list.
///
/// <b>Retarget</b> (<see cref="Retarget"/>, client3d <c>adaptExternalClips</c>): bones matched by
/// <see cref="NormBone"/>; rotations through the rest correction <c>q = K_p⁻¹·c·K_b</c>
/// (<see cref="RestCorrections"/>, vectors retarget.json) against the reference rig <c>/assets/animation-rig</c>,
/// without corrections the hips get <c>hipsRotFix</c>; the hips POSITION through <see cref="HipsTrack.Map"/>
/// (bounce against the standing reference, scale healing, root path; vectors hips_tracks.json); other positions
/// and scales are dropped; fewer than <see cref="MinTracks"/> tracks → not bound.
/// </summary>
public sealed class ClipLibrary
{
    public const int MinTracks = 8;
    /// <summary>The browser's clip download queue width (<c>createFocusQueue({max: 4})</c>).</summary>
    public const int DownloadWidth = 4;

    private readonly IWorldSource _source;
    private readonly Action<string> _log;

    /// <summary>Awaited between two imports (one clip per frame, like the browser's <c>nextFrame()</c>); null = no yield.</summary>
    public Func<Task>? NextFrame { get; set; }

    public List<ClipSourceEntry> Entries { get; } = new();
    /// <summary>The server's <c>movement_poses</c>, resolved; the default table before <see cref="Parse"/>.</summary>
    public PoseClips Poses { get; private set; } = PoseClips.Default;
    /// <summary>The server's <c>transition_clips</c>, resolved: which bridge clip opens between two kinds.</summary>
    public IReadOnlyList<ClipTransition> Transitions { get; private set; } = Array.Empty<ClipTransition>();
    /// <summary>The committed library (empty until <see cref="LoadClipsAsync"/> is through).</summary>
    public ClipIndex<ClipSource> Index { get; private set; } = new();
    public int ClipsLoaded { get; private set; }
    /// <summary>Keys of the committed source clips (the imported FBX takes, before any retarget).</summary>
    public long SourceKeys => Index.BySet.Values.SelectMany(b => b.Values)
                                   .Sum(c => Enumerable.Range(0, c.Anim.GetTrackCount()).Sum(t => (long)c.Anim.TrackGetKeyCount(t)));
    public int ClipsFailed { get; private set; }
    /// <summary>Download/prefetch phase wall time, and actual FBX import CPU time (ms), for the log.</summary>
    public double DownloadMs { get; private set; }
    public double ImportMs { get; private set; }

    public FigureCache? Cache { get; }
    public string? RigIdentity { get; private set; }
    public string PolicyDigest { get; private set; } = "";

    public ClipLibrary(IWorldSource source, Action<string> log, FigureCache? cache = null)
    {
        _source = source;
        _log = log;
        Cache = cache ?? ((source as AnimaApi)?.CacheStore is { } disk ? new FigureCache(disk) : null);
    }

    /// <summary>What a standing figure without an activity plays: <c>standingClipFor(none, none)</c>.</summary>
    public static string StandingKindOf(PoseClips poses) => FigureClips.StandingClipFor(null, null, poses);

    /// <summary>What a moving figure plays on dry land: <c>moveClip(walk_run, false)</c> = the walking pose's clip.</summary>
    public static string MovingKindOf(PoseClips poses) => FigureClips.MoveClip(FigureClips.WalkRun, false, poses);

    public string StandingKind => StandingKindOf(Poses);
    public string MovingKind => MovingKindOf(Poses);

    /// <summary>The committed clip of a kind in a set (<c>""</c> = neutral), or null.</summary>
    public ClipSource? Clip(string kind, string set = "")
        => Index.BySet.TryGetValue(kind, out var bySet) && bySet.TryGetValue(set, out var c) ? c : null;

    public void Parse(JsonElement root)
    {
        PolicyDigest = AnimaNative.Cache.DerivedKeys.Of(
            root.TryGetProperty("movement_poses", out var poses) ? poses.GetRawText() : "",
            root.TryGetProperty("transition_clips", out var transitions) ? transitions.GetRawText() : "");
        Entries.Clear();
        foreach (var c in Json.Arr(root, "clips"))
        {
            if (c.ValueKind != JsonValueKind.Object) continue;
            var url = Json.Str(c, "url");
            if (url.Length == 0) continue;
            var kind = Json.Str(c, "kind");
            var role = Json.Str(c, "role");
            bool? loop = c.TryGetProperty("loop", out var l) && l.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? l.ValueKind == JsonValueKind.True : null;
            // `!!c.root_motion && c.root_motion.mode !== 'strip'`
            bool rootMotion = c.TryGetProperty("root_motion", out var rm) && rm.ValueKind == JsonValueKind.Object
                              && !(rm.TryGetProperty("mode", out var mode) && mode.ValueKind == JsonValueKind.String && mode.GetString() == "strip");
            Entries.Add(new ClipSourceEntry(role.Length > 0 ? $"{kind}__{role}" : kind, Json.Str(c, "set"), url, loop, rootMotion)
            {
                KeepFacing = rootMotion && rm.TryGetProperty("mode", out var facingMode) && facingMode.ValueKind == JsonValueKind.String && facingMode.GetString() == "keep",
                HeightOffsets = c.TryGetProperty("height_offsets_cm", out var offsets) ? ClipHeightOffsets.Parse(offsets) : default,
            });
        }
        Poses = FigureClips.ResolveMovementPoses(root.TryGetProperty("movement_poses", out var mp) ? mp : null);
        Transitions = FigureClips.ResolveClipTransitions(root.TryGetProperty("transition_clips", out var tc) ? tc : null);
    }

    private Task? _clips;
    private readonly TaskCompletionSource _listing = new(TaskCreationOptions.RunContinuationsAsynchronously);

    /// <summary>Listing, rig, every clip (once). Completes when the library is committed.</summary>
    public Task LoadClipsAsync() => _clips ??= LoadClipsCore();

    /// <summary>Completes when the listing is parsed (or failed): the pose table is known from then on.</summary>
    public Task ListingParsed => _listing.Task;

    /// <summary>Completes when the clips are in (or failed); never throws (<c>settled</c>).</summary>
    public async Task WaitClipsAsync()
    {
        if (_clips is null) return;
        try { await _clips; }
        catch (Exception) { /* reported by the caller of LoadClipsAsync */ }
    }

    /// <summary>The reference rig the clips are authored on (<c>/assets/animation-rig</c>).</summary>
    public const string RigUrl = "/assets/animation-rig";

    /// <summary>Rest pose of the reference rig; null when it could not be loaded (then: verbatim copy + hips fix).</summary>
    public RestPoseData? DonorRest { get; private set; }
    /// <summary>The rig's rest hips height (<c>rigHipsHeight</c>) — the standing reference when the rig is there.</summary>
    public double? DonorHipsY { get; private set; }

    private async Task LoadClipsCore()
    {
        var rig = LoadRigAsync();
        try
        {
            using (var doc = await _source.GetAnimationClipsAsync()) Parse(doc.RootElement);
        }
        finally { _listing.TrySetResult(); }
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var buffers = new byte[]?[Entries.Count];
        var identities = new string?[Entries.Count];
        var prepared = new FigureCache.PreparedResource<FigureCache.SourceData>?[Entries.Count];
        var queue = new FocusQueue(DownloadWidth);
        await Task.WhenAll(Entries.Select((e, i) => queue.Push(new FocusJob(() => i, async () =>
        {
            try
            {
                buffers[i] = await _source.GetBytesAsync(e.Url);
                if (Cache is { } cache)
                {
                    identities[i] = await cache.IdentityAsync(e.Url, buffers[i]!);
                    if (identities[i] is { } identity)
                        prepared[i] = await cache.PrepareAnimation<FigureCache.SourceData>(cache.ImportKey(e.Url, identity));
                }
            }
            catch (Exception ex) { _log($"clip not loadable: {e.Url} ({ex.Message})"); }
        }))));
        DownloadMs = sw.Elapsed.TotalMilliseconds;
        sw.Restart();
        var results = new ClipSource?[Entries.Count];
        for (int i = 0; i < Entries.Count; i++)
        {
            if (buffers[i] is { } bytes)
            {
                try
                {
                    var entry = Entries[i];
                    string? identity = identities[i];
                    string? key = identity is not null ? Cache!.ImportKey(entry.Url, identity) : null;
                    var cacheWatch = System.Diagnostics.Stopwatch.StartNew();
                    var saved = prepared[i] is { } resource ? Cache!.LoadPrepared(resource) : null;
                    if (saved is not null) (_source as AnimaApi)?.Measurements.Add("clip", "cached", cacheWatch.Elapsed.TotalMilliseconds);
                    if (saved is { } hit && hit.Data.Url == entry.Url && hit.Data.Validator == identity
                        && hit.Data.ImportVersion == AnimaNative.Cache.DerivedKeys.ClipImportVersion)
                    {
                        try { results[i] = FigureCache.Restore(hit.Animation, hit.Data, entry); }
                        catch (Exception e) when (e is NullReferenceException or ArgumentException or IndexOutOfRangeException)
                        { hit.Animation.Dispose(); }
                        if (results[i] is not null) Cache!.ImportedHits++;
                    }
                    else saved?.Animation.Dispose();
                    if (results[i] is null)
                    {
                        var importWatch = System.Diagnostics.Stopwatch.StartNew();
                        using ((_source as AnimaApi)?.Measurements.Time("clip", "clip import"))
                            results[i] = Import(bytes, entry) with { CacheIdentity = identity };
                        ImportMs += importWatch.Elapsed.TotalMilliseconds;
                        if (Cache is not null) { Cache.Imports++; Cache.ImportMs += importWatch.Elapsed.TotalMilliseconds; }
                        if (key is not null) await Cache!.WriteAnimation(key, results[i]!.Anim, FigureCache.DataOf(results[i]!, identity!));
                        if (NextFrame is { } next) await next();
                    }
                    ClipsLoaded++;
                }
                catch (Exception ex) { _log($"clip not parsable: {Entries[i].Url} ({ex.Message})"); }
                buffers[i] = null;
            }
            if (results[i] is null) ClipsFailed++;
        }

        Index = ClipLibraryRules.CommitInListOrder(Entries, results, new CommitOps());
        // A file that lost its (kind, set) slot to an earlier one is never played: give its keys back.
        var kept = new HashSet<Animation>(Index.BySet.Values.SelectMany(s => s.Values).Select(c => c.Anim));
        foreach (var r in results)
            if (r is not null && !kept.Contains(r.Anim)) r.Anim.Dispose();
        await rig;
        var oneShots = Entries.Where(e => e.Loop == false).Select(e => e.Set.Length > 0 ? $"{e.Set}/{e.Kind}" : e.Kind)
                              .OrderBy(s => s, StringComparer.Ordinal).ToList();
        if (Cache is not null) _log(Cache.Describe());
        _log($"clips: {Entries.Count} listed, {ClipsLoaded} imported, {ClipsFailed} failed, {Index.Kinds.Count} kinds "
             + $"(download/cache-read {DownloadMs:0} ms, import {ImportMs:0} ms, cached {Cache?.CachedMs ?? 0:0} ms); one-shot: {(oneShots.Count > 0 ? string.Join(", ", oneShots) : "none")}");
    }

    /// <summary>The commit operations of the browser's library: rename to the kind, carry the file's flags.</summary>
    private sealed class CommitOps : IClipCommitOps<ClipSource>
    {
        public ClipSource Rename(ClipSource clip, string kind) => clip.Kind == kind ? clip : clip with { Kind = kind };
        public void SetFlags(ClipSource clip, ClipSourceEntry source) { /* set at import from the same entry */ }
        public bool IsPair(string kind) => ClipLibraryRules.IsPairName(kind);
        /// <summary>The pair half's root path (<c>extractRootPath</c>), see <see cref="PairRootOf"/>.</summary>
        public object? PairRoot(ClipSource clip) => PairRootOf(clip);
    }

    /// <summary>
    /// figures.ts <c>extractRootPath(clip)</c> on an imported clip: its position tracks as three would list them
    /// (<c>&lt;bone&gt;.position</c>, flat values) through <see cref="PairClip.ExtractRootPath"/> — in METRES already, Godot's
    /// FBX import converts the Mixamo centimetres the browser's FBXLoader keeps (the handshake's hips x: −0.366742 m here,
    /// −36.6742 cm there). Godot drops a CONSTANT curve and keeps its value as the bone's node default, so a half that
    /// stands still (the handshake) gets its one key from that default — the browser's constant track, one key.
    /// </summary>
    public static RootPath PairRootOf(ClipSource clip)
    {
        var tracks = new List<PairTrack>();
        foreach (var (bone, t) in clip.PositionTracks.OrderBy(kv => kv.Value))
        {
            int n = clip.Anim.TrackGetKeyCount(t);
            var times = new float[n];
            var values = new float[n * 3];
            for (int k = 0; k < n; k++)
            {
                times[k] = (float)clip.Anim.TrackGetKeyTime(t, k);
                var v = clip.Anim.TrackGetKeyValue(t, k).AsVector3();
                values[k * 3] = v.X; values[k * 3 + 1] = v.Y; values[k * 3 + 2] = v.Z;
            }
            tracks.Add(new PairTrack(bone + ".position", times, values));
        }
        int hips = Array.FindIndex(clip.Bones, b => NormBone(b) == "hips");
        if (hips >= 0 && !clip.PositionTracks.ContainsKey(clip.Bones[hips]))
        {
            var r = clip.RestPositions[hips];
            tracks.Add(new PairTrack(clip.Bones[hips] + ".position", new float[] { 0 }, new[] { r.X, r.Y, r.Z }));
        }
        return PairClip.ExtractRootPath(tracks, 1);
    }

    /// <summary><c>pairRootAt(clipName, t)</c>: a pair half's root XZ at clip time t (clip-frame metres); null when not loaded.</summary>
    public (double X, double Z)? PairRootAt(string clipName, double t)
        => Index.PairRoots.TryGetValue(clipName, out var p) && p is RootPath path ? BridgeTravel.RootPathAt(path, t) : null;

    /// <summary><c>clipsFor(name)</c>: per kind the first file along <c>[...sets, '']</c>.</summary>
    public List<ClipSource> ClipsFor(IReadOnlyList<string>? sets)
        => ClipLibraryRules.ClipsFor(Index, sets).Select(x => x.Clip).ToList();

    /// <summary>
    /// The library's standing reference for one fit (<c>adaptExternalClips</c>): the rig's rest hips height, else the
    /// median of the candidate named <c>idle</c>, else the standing cluster of all candidates' medians.
    /// </summary>
    public (double? Ref, string Source) StandingReference(IReadOnlyList<ClipSource> candidates)
    {
        var idle = candidates.FirstOrDefault(c => c.Kind == "idle")?.HipsMedian;
        double fallback = idle is > 1e-6 ? idle.Value : HipsTrack.ClusterRest(candidates.Select(c => c.HipsMedian ?? 0));
        return HipsTrack.StandingRef(DonorHipsY, fallback);
    }

    /// <summary>
    /// <c>/assets/animation-rig</c> → <see cref="DonorRest"/> (<c>restPoseOf(rig.scene)</c>) and
    /// <see cref="DonorHipsY"/> (<c>rigHipsHeight</c>). A failure is logged; the clips then play as a verbatim copy.
    /// </summary>
    private async Task LoadRigAsync()
    {
        try
        {
            var bytes = await _source.GetBytesAsync(RigUrl);
            RigIdentity = Cache is { } cache ? await cache.IdentityAsync(RigUrl, bytes) : null;
            string? key = RigIdentity is not null ? Cache!.ImportKey(RigUrl, RigIdentity) : null;
            var saved = key is not null ? await Cache!.ReadJson<FigureCache.RigData>(key) : null;
            if (saved?.Bones is { Count: > 0 } bones && bones.All(b => b is not null && !string.IsNullOrEmpty(b.Key)))
            {
                DonorRest = new RestPoseData();
                foreach (var bone in saved.Bones) DonorRest.Add(bone.Key, bone.World, bone.Parent, bone.ParentBone, bone.Position);
                DonorHipsY = saved.Hips;
                Cache!.ImportedHits++;
                return;
            }
            using var import = (_source as AnimaApi)?.Measurements.Time("clip", "clip import");
            if (Cache is not null) Cache.Imports++;
            var rigWatch = System.Diagnostics.Stopwatch.StartNew();
            var root = ImportFbxScene(bytes);
            try
            {
                var skel = Find<Skeleton3D>(root) ?? throw new InvalidOperationException("rig has no skeleton");
                var root3 = root as Node3D ?? throw new InvalidOperationException("rig root is not a Node3D");
                DonorRest = RestAdapter.Of(root3, skel);
                var hipsKey = DonorRest.Order.FirstOrDefault(k => k.EndsWith("hips", StringComparison.Ordinal));
                if (hipsKey is not null) DonorHipsY = DonorRest.Position[hipsKey].Y;
                if (Cache is not null) Cache.ImportMs += rigWatch.Elapsed.TotalMilliseconds;
                if (key is not null) await Cache!.WriteJson(key, new FigureCache.RigData(DonorRest.Order.Select(k =>
                    new FigureCache.RigBone(k, DonorRest.World[k], DonorRest.Parent[k], DonorRest.ParentBone[k], DonorRest.Position[k])).ToList(), DonorHipsY));
                _log($"rig: {DonorRest.World.Count} bones, rest hips height {DonorHipsY:0.####}");
            }
            finally { root.Free(); }
        }
        catch (Exception e)
        {
            DonorRest = null;
            DonorHipsY = null;
            _log($"rig {RigUrl} failed: {e.Message} — clips are copied 1:1 (no rest correction)");
        }
    }

    /// <summary>
    /// Runtime FBX import to a scene (main thread: it builds nodes). Through a temp file, not AppendFromBuffer:
    /// from a buffer the FBX reader asks Godot's memory file for more bytes than remain and every import prints two
    /// "Reading less data than requested" warnings (harmless, but they drown the log).
    /// </summary>
    public static Node ImportFbxScene(byte[] fbx)
    {
        var tmp = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"anima-fbx-{Guid.NewGuid():N}.fbx");
        try
        {
            System.IO.File.WriteAllBytes(tmp, fbx);
            var doc = new FbxDocument();
            var state = new FbxState();
            var err = doc.AppendFromFile(tmp, state);
            if (err != Error.Ok) throw new InvalidOperationException($"FBX import failed: {err}");
            return doc.GenerateScene(state) as Node ?? throw new InvalidOperationException("FBX scene is empty");
        }
        finally
        {
            try { System.IO.File.Delete(tmp); } catch (System.IO.IOException) { }
        }
    }

    /// <summary>Runtime FBX import (main thread: it builds nodes), then keep only the data.</summary>
    public static ClipSource Import(byte[] fbx, ClipSourceEntry entry)
    {
        var root = ImportFbxScene(fbx);
        try
        {
            var skel = Find<Skeleton3D>(root) ?? throw new InvalidOperationException("clip has no skeleton");
            var player = Find<AnimationPlayer>(root) ?? throw new InvalidOperationException("clip has no AnimationPlayer");
            var names = player.GetAnimationList();
            if (names.Length == 0) throw new InvalidOperationException("clip has no animation");
            var anim = player.GetAnimation(names[0]);
            int n = skel.GetBoneCount();
            var bones = new string[n];
            var rots = new Quaternion[n];
            var poss = new Vector3[n];
            for (int i = 0; i < n; i++)
            {
                bones[i] = skel.GetBoneName(i);
                var rest = skel.GetBoneRest(i);
                rots[i] = rest.Basis.GetRotationQuaternion();
                poss[i] = rest.Origin;
            }
            var rot = new Dictionary<string, int>();
            var pos = new Dictionary<string, int>();
            for (int t = 0; t < anim.GetTrackCount(); t++)
            {
                var bone = anim.TrackGetPath(t).GetConcatenatedSubNames();
                if (bone.Length == 0) continue;
                switch (anim.TrackGetType(t))
                {
                    case Animation.TrackType.Rotation3D: rot[bone] = t; break;
                    case Animation.TrackType.Position3D: pos[bone] = t; break;
                }
            }
            // hipsTrackMedian over the file's hips position (the constant default when Godot dropped the curve).
            double? median = null;
            int hb = Array.FindIndex(bones, b => NormBone(b) == "hips");
            if (hb >= 0)
            {
                var ys = new List<double>();
                if (pos.TryGetValue(bones[hb], out var pt))
                    for (int k = 0; k < anim.TrackGetKeyCount(pt); k++)
                    {
                        var v = anim.TrackGetKeyValue(pt, k).AsVector3();
                        ys.Add(v.X); ys.Add(v.Y); ys.Add(v.Z);
                    }
                else { ys.Add(poss[hb].X); ys.Add(poss[hb].Y); ys.Add(poss[hb].Z); }
                median = HipsTrack.Median(new[] { ("hips.position", (IReadOnlyList<double>)ys) });
            }
            return new ClipSource
            {
                Kind = entry.Kind, Set = entry.Set, Url = entry.Url, Loop = entry.Loops, RootMotion = entry.RootMotion, KeepFacing = entry.KeepFacing,
                HeightOffsets = entry.HeightOffsets,
                Anim = anim, Bones = bones, RestRotations = rots, RestPositions = poss,
                RotationTracks = rot, PositionTracks = pos, HipsMedian = median, Length = anim.Length,
                RotationKeys = rot.ToDictionary(kv => kv.Key, kv => KeysOf(anim, kv.Value, rotation: true)),
                PositionKeys = pos.ToDictionary(kv => kv.Key, kv => KeysOf(anim, kv.Value, rotation: false)),
            };
        }
        finally
        {
            root.Free();
        }
    }

    /// <summary>One track's keys read out of the engine (main thread), exactly as <c>track_get_key_*</c> return them.</summary>
    private static SourceTrack KeysOf(Animation anim, int track, bool rotation)
    {
        int n = anim.TrackGetKeyCount(track);
        var times = new double[n];
        var rots = rotation ? new Quaternion[n] : null;
        var poss = rotation ? null : new Vector3[n];
        for (int k = 0; k < n; k++)
        {
            times[k] = anim.TrackGetKeyTime(track, k);
            var v = anim.TrackGetKeyValue(track, k);
            if (rots is not null) rots[k] = v.AsQuaternion();
            else poss![k] = v.AsVector3();
        }
        return new SourceTrack(anim.TrackGetInterpolationType(track), times, rots, poss);
    }

    /// <summary>Column-major 16 numbers of a Godot transform (three's <c>Matrix4.elements</c>).</summary>
    internal static double[] ColumnMajor(Transform3D t) => new double[]
    {
        t.Basis.Column0.X, t.Basis.Column0.Y, t.Basis.Column0.Z, 0,
        t.Basis.Column1.X, t.Basis.Column1.Y, t.Basis.Column1.Z, 0,
        t.Basis.Column2.X, t.Basis.Column2.Y, t.Basis.Column2.Z, 0,
        t.Origin.X, t.Origin.Y, t.Origin.Z, 1,
    };

    /// <summary>The world (template-root-inclusive) rest frame the hips' parent puts the hips in, and the hips' index.</summary>
    public static (int Hips, Transform3D Parent) HipsParentFrame(Node3D modelRoot, Skeleton3D skel)
    {
        int hips = -1;
        for (int i = 0; i < skel.GetBoneCount() && hips < 0; i++)
            if (NormBone(skel.GetBoneName(i)).EndsWith("hips", StringComparison.Ordinal)) hips = i;
        var skelXf = modelRoot.Transform * modelRoot.GlobalTransformOf(skel);
        if (hips < 0) return (-1, skelXf);
        int parent = skel.GetBoneParent(hips);
        return (hips, parent < 0 ? skelXf : skelXf * skel.GetBoneGlobalRest(parent));
    }

    /// <summary>
    /// Build <paramref name="clip"/> for the skeleton under <paramref name="modelRoot"/> (track paths relative to it —
    /// the AnimationPlayer's root node), client3d <c>adaptExternalClips</c> for ONE clip: <see cref="Compute"/> then
    /// <see cref="Write"/> on the calling (main) thread. The lazy fit (Task 35b, <see cref="TemplateClips"/>) runs the two
    /// halves apart — the key math on a worker thread, the write on the main thread — with the same result bit for bit.
    /// </summary>
    public static BoundClip Retarget(ClipSource clip, Node3D modelRoot, Skeleton3D skel,
                                     IReadOnlyDictionary<string, RestFix>? corrections, double sourceRest, bool rigKnown)
    {
        var rig = RetargetRig.Of(modelRoot, skel);
        return Write(Compute(clip, rig, corrections, sourceRest, rigKnown), rig);
    }

    /// <summary>
    /// The retarget's key math, engine-free (Godot's math structs are plain managed code; the source keys were read at
    /// import, <see cref="ClipSource.RotationKeys"/>), so it runs on any thread: rotations <c>K_p⁻¹·c·K_b</c> where
    /// <paramref name="corrections"/> has the bone, verbatim where not, and with NO corrections at all the hips get
    /// <c>hipsRotFix</c> (the inverse world rotation of the hips' parent); the hips position through
    /// <see cref="HipsTrack.Map"/> against <paramref name="sourceRest"/> (skipped when it is not usable), root path only
    /// for a root-motion clip and <paramref name="rigKnown"/>. <paramref name="countOnly"/>: only the track and key
    /// counts (what the template's plan needs to know whether the clip binds), no values, no digest.
    /// </summary>
    public static RetargetKeys Compute(ClipSource clip, RetargetRig rig, IReadOnlyDictionary<string, RestFix>? corrections,
                                       double sourceRest, bool rigKnown, bool countOnly = false)
    {
        bool noCorrections = corrections is null || corrections.Count == 0;
        var hipsRotFix = rig.HipsRotFix;
        var loop = clip.Loop ? Animation.LoopModeEnum.Linear : Animation.LoopModeEnum.None;
        var digest = countOnly ? null : new ContentDigest();
        digest?.Add(clip.Length);
        digest?.Add((int)loop);
        var list = new List<RetargetTrack>();
        int tracks = 0;
        long keys = 0;
        RootPath? rootPath = null;
        for (int b = 0; b < clip.Bones.Length; b++)
        {
            var name = clip.Bones[b];
            var key = NormBone(name);
            if (!rig.ByKey.TryGetValue(key, out int ti)) continue;
            var path = rig.BonePaths[ti];
            bool isHips = ti == rig.Hips;

            Func<Quaternion, Quaternion> fix = q => q;
            if (isHips && noCorrections) fix = q => hipsRotFix * q;
            else if (corrections is not null && corrections.TryGetValue(key, out var rf)) fix = q => RestAdapter.Apply(rf, q);
            digest?.Add(path);
            digest?.Add((int)Animation.TrackType.Rotation3D);
            if (clip.RotationKeys.TryGetValue(name, out var st))
            {
                digest?.Add((int)st.Interp);
                int n = st.Times.Length;
                if (!countOnly)
                {
                    var rots = new Quaternion[n];
                    for (int k = 0; k < n; k++)
                    {
                        rots[k] = fix(st.Rotations![k]).Normalized();
                        digest!.Add(st.Times[k], rots[k]);
                    }
                    list.Add(new RetargetTrack(ti, Animation.TrackType.Rotation3D, st.Interp, st.Times, rots, null));
                }
                keys += n;
            }
            else
            {
                if (!countOnly)
                {
                    var q = fix(clip.RestRotations[b]).Normalized();
                    list.Add(new RetargetTrack(ti, Animation.TrackType.Rotation3D, null, new[] { 0.0 }, new[] { q }, null));
                    digest!.Add(-1);
                    digest.Add(0.0, q);
                }
                keys++;
            }
            tracks++;

            if (!isHips || !(sourceRest > 1e-6)) continue;
            // The hips position: bounce against the standing reference, in the parent's space + the rest.
            digest?.Add(path);
            digest?.Add((int)Animation.TrackType.Position3D);
            clip.PositionKeys.TryGetValue(name, out var sp);
            int count = sp?.Times.Length ?? 1;
            keys += count;
            tracks++;
            if (countOnly) continue;
            var restLocal = rig.RestOrigins[ti];
            double restWorldY = (rig.ParentXf * restLocal).Y;
            var raw = new List<double>(count * 3);
            double[] times;
            if (sp is not null)
            {
                digest!.Add((int)sp.Interp);
                times = sp.Times;
                foreach (var v in sp.Positions!)
                {
                    raw.Add(v.X); raw.Add(v.Y); raw.Add(v.Z);
                }
            }
            else
            {
                var v = clip.RestPositions[b];
                raw.Add(v.X); raw.Add(v.Y); raw.Add(v.Z);
                times = new[] { 0.0 };
                digest!.Add(-1);
            }
            var (values, rp) = HipsTrack.Map(raw, times, new HipsTrackOptions(
                sourceRest, clip.HipsMedian ?? 0, restWorldY > 1e-6 ? restWorldY : 1,
                rig.ParentInverse, new V3(restLocal.X, restLocal.Y, restLocal.Z),
                clip.RootMotion, rigKnown));
            var poss = new Vector3[times.Length];
            for (int k = 0; k < times.Length; k++)
            {
                poss[k] = new Vector3(values[k * 3], values[k * 3 + 1], values[k * 3 + 2]);
                digest!.Add(times[k], poss[k]);
            }
            list.Add(new RetargetTrack(ti, Animation.TrackType.Position3D, sp?.Interp, times, null, poss));
            rootPath = rp;
        }
        return new RetargetKeys
        {
            Kind = clip.Kind, Length = clip.Length, Loop = loop, Tracks = list, TrackCount = tracks, Keys = keys,
            RootPath = rootPath, Digest = digest?.Finish(),
        };
    }

    /// <summary>
    /// The engine half of the retarget (main thread): the Animation of <paramref name="keys"/> — one track after the
    /// other in the computed order, each with its path, the source interpolation where the file had a track, the keys
    /// written in one call where that stores them exactly (<see cref="KeyWriter"/>). Fewer than <see cref="MinTracks"/>
    /// tracks → nothing bound.
    /// </summary>
    public static BoundClip Write(RetargetKeys keys, RetargetRig rig)
    {
        if (keys.TrackCount < MinTracks) return new BoundClip(keys.Kind, null, keys.TrackCount, 0, null);
        var anim = new Animation { Length = keys.Length, LoopMode = keys.Loop };
        foreach (var t in keys.Tracks)
        {
            int at = anim.AddTrack(t.Type);
            anim.TrackSetPath(at, rig.NodePaths[t.Bone]);
            if (t.Interp is { } interp) anim.TrackSetInterpolationType(at, interp);
            if (t.Type == Animation.TrackType.Rotation3D) KeyWriter.Rotations(anim, at, t.Times, t.Rotations!);
            else KeyWriter.Positions(anim, at, t.Times, t.Positions!);
        }
        return new BoundClip(keys.Kind, anim, keys.TrackCount, keys.Keys, keys.RootPath, keys.Digest);
    }

    /// <summary>The browser's <c>normBoneName</c>, plus a namespace strip and Godot's <c>_</c> spelling (<see cref="BoneNames.Norm"/>).</summary>
    public static string NormBone(string name) => BoneNames.Norm(name);

    /// <summary>Release the imported animations (Godot resources held from C#).</summary>
    public void Release()
    {
        foreach (var bySet in Index.BySet.Values)
        foreach (var clip in bySet.Values)
            if (GodotObject.IsInstanceValid(clip.Anim)) clip.Anim.Dispose();
        Index = new ClipIndex<ClipSource>();
    }

    public static T? Find<T>(Node root) where T : Node
    {
        if (root is T t) return t;
        foreach (var child in root.GetChildren())
            if (Find<T>(child) is { } hit) return hit;
        return null;
    }
}

/// <summary>
/// The target skeleton of a retarget as plain data, read once per template on the main thread (Task 35b): bone key →
/// first bone (<see cref="ClipLibrary.NormBone"/>), every bone's track path (the engine's spelling, as the digest hashes
/// it) and rest origin, the hips and the rest frame of their parent — everything <see cref="ClipLibrary.Compute"/> needs
/// from the engine, so the key math can run on a worker thread.
/// </summary>
public sealed class RetargetRig
{
    public required Dictionary<string, int> ByKey { get; init; }
    public required string[] BonePaths { get; init; }
    public required NodePath[] NodePaths { get; init; }
    public required Vector3[] RestOrigins { get; init; }
    public required int Hips { get; init; }
    public required Transform3D ParentXf { get; init; }
    /// <summary><c>hipsRotFix</c>: the inverse world rotation of the hips' parent.</summary>
    public required Quaternion HipsRotFix { get; init; }
    /// <summary>The parent frame's inverse, column-major (<see cref="HipsTrackOptions.ParentInverse"/>).</summary>
    public required double[] ParentInverse { get; init; }

    public static RetargetRig Of(Node3D modelRoot, Skeleton3D skel)
    {
        var (hips, parentXf) = ClipLibrary.HipsParentFrame(modelRoot, skel);
        int n = skel.GetBoneCount();
        var byKey = new Dictionary<string, int>();
        var paths = new string[n];
        var nodePaths = new NodePath[n];
        var rests = new Vector3[n];
        var skelPath = modelRoot.GetPathTo(skel).ToString();
        for (int i = 0; i < n; i++)
        {
            byKey.TryAdd(ClipLibrary.NormBone(skel.GetBoneName(i)), i);
            nodePaths[i] = new NodePath($"{skelPath}:{skel.GetBoneName(i)}");
            paths[i] = nodePaths[i].ToString();
            rests[i] = skel.GetBoneRest(i).Origin;
        }
        return new RetargetRig
        {
            ByKey = byKey, BonePaths = paths, NodePaths = nodePaths, RestOrigins = rests, Hips = hips, ParentXf = parentXf,
            HipsRotFix = parentXf.Basis.GetRotationQuaternion().Inverse(),
            ParentInverse = ClipLibrary.ColumnMajor(parentXf.AffineInverse()),
        };
    }
}

/// <summary>One retargeted track: the target bone, its type, the source interpolation (null = Godot's default), its keys.</summary>
public sealed record RetargetTrack(int Bone, Animation.TrackType Type, Animation.InterpolationType? Interp, double[] Times,
                                   Quaternion[]? Rotations, Vector3[]? Positions);

/// <summary>What <see cref="ClipLibrary.Compute"/> made of one clip on one rig: the tracks in write order, the counts, the root path and the digest.</summary>
public sealed class RetargetKeys
{
    public required string Kind { get; init; }
    public required double Length { get; init; }
    public required Animation.LoopModeEnum Loop { get; init; }
    public required List<RetargetTrack> Tracks { get; init; }
    public required int TrackCount { get; init; }
    public required long Keys { get; init; }
    public RootPath? RootPath { get; init; }
    public string? Digest { get; init; }
    public bool Binds => TrackCount >= ClipLibrary.MinTracks;
}

/// <summary>
/// Writes a fresh track's keys in ONE call instead of one <c>*_track_insert_key</c> per key (Task 35, ruling P3-R11).
///
/// Godot keeps a track's keys in a vector that grows by 1.5× while keys are inserted one by one, so an inserted track
/// holds on average a quarter more slots than keys (measured on the world copy: 41.4 B per retargeted key instead of
/// the 32 B of a <c>TKey&lt;Quaternion&gt;</c>). Setting the track's <c>keys</c> property sizes the vector exactly.
///
/// That property carries the times as 32-bit floats, and the insert merges a key into its neighbour when their
/// times are within Godot's <c>is_equal_approx</c>. So the bulk path is taken only when it stores EXACTLY what the
/// inserts would have stored: every time representable as a float (the clip FBX takes are — 0 of 20 083 fixture keys
/// were not) and strictly ascending with gaps far above that merge tolerance. Anything else is inserted key by key.
/// The bound clip is therefore the same bit for bit either way; only its vector's spare capacity is gone.
/// </summary>
public static class KeyWriter
{
    /// <summary>Godot's merge tolerance for two key times (<c>CMP_EPSILON</c>, relative above 1 s), with a safety factor of 10.</summary>
    private const double MergeGap = 1e-4;

    /// <summary>The check's switch: write every retargeted track key by key (the reference the bulk path is compared with).</summary>
    public static bool ForceInsert { get; set; }

    /// <summary>Retargeted tracks written in one call / key by key since the start (the offline memory line reports both).</summary>
    public static long BulkTracks { get; private set; }
    public static long InsertedTracks { get; private set; }

    /// <summary>True when setting these times as floats stores them unchanged and no insert would have merged two keys.</summary>
    public static bool BulkSafe(IReadOnlyList<double> times)
    {
        for (int k = 0; k < times.Count; k++)
        {
            double t = times[k];
            if ((double)(float)t != t || !double.IsFinite(t)) return false;
            if (k > 0 && !(t - times[k - 1] > MergeGap * Math.Max(1, Math.Abs(t)))) return false;
        }
        return true;
    }

    public static void Rotations(Animation anim, int track, double[] times, Quaternion[] values)
    {
        if (ForceInsert || !BulkSafe(times))
        {
            for (int k = 0; k < times.Length; k++) anim.RotationTrackInsertKey(track, times[k], values[k]);
            InsertedTracks++;
            return;
        }
        BulkTracks++;
        var flat = new float[times.Length * 6];   // ROTATION_TRACK_SIZE: time, transition, x, y, z, w
        for (int k = 0; k < times.Length; k++)
        {
            int o = k * 6;
            flat[o] = (float)times[k];
            flat[o + 1] = 1f;
            flat[o + 2] = values[k].X;
            flat[o + 3] = values[k].Y;
            flat[o + 4] = values[k].Z;
            flat[o + 5] = values[k].W;
        }
        anim.Set($"tracks/{track}/keys", flat);
    }

    /// <summary>
    /// A copy of <paramref name="src"/> with the same keys bit for bit (times, transitions, values; every position /
    /// rotation / scale track written through the same exactness gate). An animation carrying any other track type is
    /// duplicated by Godot instead. Used for a figure's loop twin (<see cref="Figure.PlayName"/>).
    /// </summary>
    public static Animation Copy(Animation src)
    {
        int n = src.GetTrackCount();
        for (int t = 0; t < n; t++)
            if (src.TrackGetType(t) is not (Animation.TrackType.Position3D or Animation.TrackType.Rotation3D or Animation.TrackType.Scale3D))
                return (Animation)src.Duplicate();
        var dst = new Animation { Length = src.Length, LoopMode = src.LoopMode, Step = src.Step };
        for (int t = 0; t < n; t++)
        {
            var type = src.TrackGetType(t);
            int d = dst.AddTrack(type);
            dst.TrackSetPath(d, src.TrackGetPath(t));
            dst.TrackSetInterpolationType(d, src.TrackGetInterpolationType(t));
            dst.TrackSetInterpolationLoopWrap(d, src.TrackGetInterpolationLoopWrap(t));
            dst.TrackSetEnabled(d, src.TrackIsEnabled(t));
            dst.TrackSetImported(d, src.TrackIsImported(t));
            int keys = src.TrackGetKeyCount(t);
            var times = new double[keys];
            var trans = new float[keys];
            var vals = new Variant[keys];
            for (int k = 0; k < keys; k++)
            {
                times[k] = src.TrackGetKeyTime(t, k);
                trans[k] = src.TrackGetKeyTransition(t, k);
                vals[k] = src.TrackGetKeyValue(t, k);
            }
            int width = type == Animation.TrackType.Rotation3D ? 6 : 5;
            if (BulkSafe(times))
            {
                var flat = new float[keys * width];
                for (int k = 0; k < keys; k++)
                {
                    int o = k * width;
                    flat[o] = (float)times[k];
                    flat[o + 1] = trans[k];
                    if (type == Animation.TrackType.Rotation3D)
                    {
                        var q = vals[k].AsQuaternion();
                        flat[o + 2] = q.X; flat[o + 3] = q.Y; flat[o + 4] = q.Z; flat[o + 5] = q.W;
                    }
                    else
                    {
                        var v = vals[k].AsVector3();
                        flat[o + 2] = v.X; flat[o + 3] = v.Y; flat[o + 4] = v.Z;
                    }
                }
                dst.Set($"tracks/{d}/keys", flat);
            }
            else
                for (int k = 0; k < keys; k++) dst.TrackInsertKey(d, times[k], vals[k], trans[k]);
        }
        return dst;
    }

    public static void Positions(Animation anim, int track, double[] times, Vector3[] values)
    {
        if (ForceInsert || !BulkSafe(times))
        {
            for (int k = 0; k < times.Length; k++) anim.PositionTrackInsertKey(track, times[k], values[k]);
            InsertedTracks++;
            return;
        }
        BulkTracks++;
        var flat = new float[times.Length * 5];   // POSITION_TRACK_SIZE: time, transition, x, y, z
        for (int k = 0; k < times.Length; k++)
        {
            int o = k * 5;
            flat[o] = (float)times[k];
            flat[o + 1] = 1f;
            flat[o + 2] = values[k].X;
            flat[o + 3] = values[k].Y;
            flat[o + 4] = values[k].Z;
        }
        anim.Set($"tracks/{track}/keys", flat);
    }
}

/// <summary>
/// The incremental SHA-256 of a retargeted clip (<see cref="BoundClip.Digest"/>): the exact bits handed to Godot —
/// doubles and floats by their IEEE bit patterns, strings as UTF-8 with their length — so equal digests mean equal
/// content, not merely close values. Buffered: a template hashes ~300 000 keys in a few milliseconds.
/// </summary>
internal sealed class ContentDigest
{
    private readonly System.Security.Cryptography.IncrementalHash _hash =
        System.Security.Cryptography.IncrementalHash.CreateHash(System.Security.Cryptography.HashAlgorithmName.SHA256);
    private readonly byte[] _buf = new byte[4096];
    private int _n;

    private Span<byte> Room(int bytes)
    {
        if (_n + bytes > _buf.Length) Flush();
        var span = _buf.AsSpan(_n, bytes);
        _n += bytes;
        return span;
    }

    private void Flush()
    {
        if (_n == 0) return;
        _hash.AppendData(_buf, 0, _n);
        _n = 0;
    }

    public void Add(int v) => System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(Room(4), v);
    public void Add(double v) => System.Buffers.Binary.BinaryPrimitives.WriteInt64LittleEndian(Room(8), BitConverter.DoubleToInt64Bits(v));

    public void Add(string s)
    {
        var bytes = System.Text.Encoding.UTF8.GetBytes(s);
        Add(bytes.Length);
        Flush();
        _hash.AppendData(bytes);
    }

    public void Add(double time, Quaternion q)
    {
        var span = Room(24);
        System.Buffers.Binary.BinaryPrimitives.WriteInt64LittleEndian(span, BitConverter.DoubleToInt64Bits(time));
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[8..], q.X);
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[12..], q.Y);
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[16..], q.Z);
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[20..], q.W);
    }

    public void Add(double time, Vector3 v)
    {
        var span = Room(20);
        System.Buffers.Binary.BinaryPrimitives.WriteInt64LittleEndian(span, BitConverter.DoubleToInt64Bits(time));
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[8..], v.X);
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[12..], v.Y);
        System.Buffers.Binary.BinaryPrimitives.WriteSingleLittleEndian(span[16..], v.Z);
    }

    public string Finish()
    {
        Flush();
        return Convert.ToHexString(_hash.GetHashAndReset());
    }
}

internal static class NodeTransformExt
{
    /// <summary>Transform of <paramref name="node"/> relative to <paramref name="root"/> (works outside the tree).</summary>
    public static Transform3D GlobalTransformOf(this Node3D root, Node3D node)
    {
        var xf = Transform3D.Identity;
        for (Node? n = node; n is not null && n != root; n = n.GetParent())
            if (n is Node3D n3) xf = n3.Transform * xf;
        return xf;
    }
}
