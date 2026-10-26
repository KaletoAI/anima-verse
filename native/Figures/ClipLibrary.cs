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
    public required string Kind { get; init; }
    public required string Set { get; init; }
    public required string Url { get; init; }
    /// <summary>The listing's loop flag of THIS file (missing = loop).</summary>
    public required bool Loop { get; init; }
    /// <summary>The file carries a root travel (<c>root_motion.mode</c> keep/foot_lock); its path is built at fit time.</summary>
    public required bool RootMotion { get; init; }
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
}

/// <summary>What one clip produced on one skeleton: the bound animation (null under <see cref="ClipLibrary.MinTracks"/>),
/// its track and key counts, and the root path of a root-motion clip (re-locked per rig at fit time, carried by the bridges).</summary>
public sealed record BoundClip(string Kind, Animation? Anim, int Tracks, long Keys, RootPath? RootPath);

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
    /// <summary>Wall time of the downloads and of the imports (ms), for the log.</summary>
    public double DownloadMs { get; private set; }
    public double ImportMs { get; private set; }

    public ClipLibrary(IWorldSource source, Action<string> log)
    {
        _source = source;
        _log = log;
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
            Entries.Add(new ClipSourceEntry(role.Length > 0 ? $"{kind}__{role}" : kind, Json.Str(c, "set"), url, loop, rootMotion));
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
        var queue = new FocusQueue(DownloadWidth);
        await Task.WhenAll(Entries.Select((e, i) => queue.Push(new FocusJob(() => i, async () =>
        {
            try { buffers[i] = await _source.GetBytesAsync(e.Url); }
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
                    results[i] = Import(bytes, Entries[i]);
                    ClipsLoaded++;
                }
                catch (Exception ex) { _log($"clip not parsable: {Entries[i].Url} ({ex.Message})"); }
                buffers[i] = null;
                if (NextFrame is { } next) await next();
            }
            if (results[i] is null) ClipsFailed++;
        }
        ImportMs = sw.Elapsed.TotalMilliseconds;
        Index = ClipLibraryRules.CommitInListOrder(Entries, results, new CommitOps());
        // A file that lost its (kind, set) slot to an earlier one is never played: give its keys back.
        var kept = new HashSet<Animation>(Index.BySet.Values.SelectMany(s => s.Values).Select(c => c.Anim));
        foreach (var r in results)
            if (r is not null && !kept.Contains(r.Anim)) r.Anim.Dispose();
        await rig;
        var oneShots = Entries.Where(e => e.Loop == false).Select(e => e.Set.Length > 0 ? $"{e.Set}/{e.Kind}" : e.Kind)
                              .OrderBy(s => s, StringComparer.Ordinal).ToList();
        _log($"clips: {Entries.Count} listed, {ClipsLoaded} imported, {ClipsFailed} failed, {Index.Kinds.Count} kinds "
             + $"(download {DownloadMs:0} ms, import {ImportMs:0} ms); one-shot: {(oneShots.Count > 0 ? string.Join(", ", oneShots) : "none")}");
    }

    /// <summary>The commit operations of the browser's library: rename to the kind, carry the file's flags.</summary>
    private sealed class CommitOps : IClipCommitOps<ClipSource>
    {
        public ClipSource Rename(ClipSource clip, string kind) => clip.Kind == kind ? clip : clip with { Kind = kind };
        public void SetFlags(ClipSource clip, ClipSourceEntry source) { /* set at import from the same entry */ }
        public bool IsPair(string kind) => ClipLibraryRules.IsPairName(kind);
        /// <summary>The pair root path (<c>extractRootPath</c>) belongs to the pair clips (Task 32); the half is indexed now.</summary>
        public object? PairRoot(ClipSource clip) => null;
    }

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
            var root = ImportFbxScene(bytes);
            try
            {
                var skel = Find<Skeleton3D>(root) ?? throw new InvalidOperationException("rig has no skeleton");
                var root3 = root as Node3D ?? throw new InvalidOperationException("rig root is not a Node3D");
                DonorRest = RestAdapter.Of(root3, skel);
                var key = DonorRest.Order.FirstOrDefault(k => k.EndsWith("hips", StringComparison.Ordinal));
                if (key is not null) DonorHipsY = DonorRest.Position[key].Y;
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
                Kind = entry.Kind, Set = entry.Set, Url = entry.Url, Loop = entry.Loops, RootMotion = entry.RootMotion,
                Anim = anim, Bones = bones, RestRotations = rots, RestPositions = poss,
                RotationTracks = rot, PositionTracks = pos, HipsMedian = median,
            };
        }
        finally
        {
            root.Free();
        }
    }

    /// <summary>Column-major 16 numbers of a Godot transform (three's <c>Matrix4.elements</c>).</summary>
    private static double[] ColumnMajor(Transform3D t) => new double[]
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
    /// the AnimationPlayer's root node), client3d <c>adaptExternalClips</c> for ONE clip:
    /// rotations <c>K_p⁻¹·c·K_b</c> where <paramref name="corrections"/> has the bone, verbatim where not, and with NO
    /// corrections at all the hips get <c>hipsRotFix</c> (the inverse world rotation of the hips' parent); the hips
    /// position through <see cref="HipsTrack.Map"/> against <paramref name="sourceRest"/> (skipped when it is not
    /// usable), root path only for a root-motion clip and <paramref name="rigKnown"/>.
    /// </summary>
    public static BoundClip Retarget(ClipSource clip, Node3D modelRoot, Skeleton3D skel,
                                     IReadOnlyDictionary<string, RestFix>? corrections, double sourceRest, bool rigKnown)
    {
        var (hipsIdx, parentXf) = HipsParentFrame(modelRoot, skel);
        bool noCorrections = corrections is null || corrections.Count == 0;
        var hipsRotFix = parentXf.Basis.GetRotationQuaternion().Inverse();
        var target = new Dictionary<string, int>();
        for (int i = 0; i < skel.GetBoneCount(); i++) target.TryAdd(NormBone(skel.GetBoneName(i)), i);
        var skelPath = modelRoot.GetPathTo(skel).ToString();

        var anim = new Animation
        {
            Length = clip.Anim.Length,
            LoopMode = clip.Loop ? Animation.LoopModeEnum.Linear : Animation.LoopModeEnum.None,
        };
        int tracks = 0;
        long keys = 0;
        RootPath? rootPath = null;
        for (int b = 0; b < clip.Bones.Length; b++)
        {
            var name = clip.Bones[b];
            var key = NormBone(name);
            if (!target.TryGetValue(key, out int ti)) continue;
            var path = new NodePath($"{skelPath}:{skel.GetBoneName(ti)}");
            bool isHips = ti == hipsIdx;

            Func<Quaternion, Quaternion> fix = q => q;
            if (isHips && noCorrections) fix = q => hipsRotFix * q;
            else if (corrections is not null && corrections.TryGetValue(key, out var rf)) fix = q => RestAdapter.Apply(rf, q);
            int rt = anim.AddTrack(Animation.TrackType.Rotation3D);
            anim.TrackSetPath(rt, path);
            if (clip.RotationTracks.TryGetValue(name, out int st))
            {
                anim.TrackSetInterpolationType(rt, clip.Anim.TrackGetInterpolationType(st));
                int n = clip.Anim.TrackGetKeyCount(st);
                for (int k = 0; k < n; k++)
                    anim.RotationTrackInsertKey(rt, clip.Anim.TrackGetKeyTime(st, k),
                                                fix(clip.Anim.TrackGetKeyValue(st, k).AsQuaternion()).Normalized());
                keys += n;
            }
            else
            {
                anim.RotationTrackInsertKey(rt, 0, fix(clip.RestRotations[b]).Normalized());
                keys++;
            }
            tracks++;

            if (!isHips || !(sourceRest > 1e-6)) continue;
            // The hips position: bounce against the standing reference, in the parent's space + the rest.
            var restLocal = skel.GetBoneRest(ti).Origin;
            double restWorldY = (parentXf * restLocal).Y;
            var raw = new List<double>();
            var times = new List<double>();
            int pt = anim.AddTrack(Animation.TrackType.Position3D);
            anim.TrackSetPath(pt, path);
            if (clip.PositionTracks.TryGetValue(name, out int sp))
            {
                anim.TrackSetInterpolationType(pt, clip.Anim.TrackGetInterpolationType(sp));
                for (int k = 0; k < clip.Anim.TrackGetKeyCount(sp); k++)
                {
                    var v = clip.Anim.TrackGetKeyValue(sp, k).AsVector3();
                    raw.Add(v.X); raw.Add(v.Y); raw.Add(v.Z);
                    times.Add(clip.Anim.TrackGetKeyTime(sp, k));
                }
            }
            else
            {
                var v = clip.RestPositions[b];
                raw.Add(v.X); raw.Add(v.Y); raw.Add(v.Z);
                times.Add(0);
            }
            var (values, rp) = HipsTrack.Map(raw, times, new HipsTrackOptions(
                sourceRest, clip.HipsMedian ?? 0, restWorldY > 1e-6 ? restWorldY : 1,
                ColumnMajor(parentXf.AffineInverse()), new V3(restLocal.X, restLocal.Y, restLocal.Z),
                clip.RootMotion, rigKnown));
            for (int k = 0; k < times.Count; k++)
                anim.PositionTrackInsertKey(pt, times[k], new Vector3(values[k * 3], values[k * 3 + 1], values[k * 3 + 2]));
            keys += times.Count;
            rootPath = rp;
            tracks++;
        }
        if (tracks >= MinTracks) return new BoundClip(clip.Kind, anim, tracks, keys, rootPath);
        anim.Dispose();
        return new BoundClip(clip.Kind, null, tracks, 0, null);
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
