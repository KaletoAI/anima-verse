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

/// <summary>One entry of <c>GET /assets/animation-clips</c> → <c>clips[]</c> (§ A7/§ A8).</summary>
public sealed record ClipEntry(string Kind, string Role, string Set, string Url, bool Loop);

/// <summary>
/// A clip FBX imported once: its animation plus the skeleton it was keyed on
/// (bone names, the per-bone node defaults). Shared by every figure.
/// </summary>
public sealed class ClipSource
{
    public required string Kind { get; init; }
    public required string Url { get; init; }
    public required bool Loop { get; init; }
    public required Animation Anim { get; init; }
    public required string[] Bones { get; init; }
    /// <summary>The bone's node default — for a clip FBX that is the take's first frame (Godot stores it as the rest).</summary>
    public required Quaternion[] RestRotations { get; init; }
    public required Vector3[] RestPositions { get; init; }
    /// <summary>Bone name → index of its rotation track in <see cref="Anim"/>.</summary>
    public required Dictionary<string, int> RotationTracks { get; init; }
    public required Dictionary<string, int> PositionTracks { get; init; }
    public int RotationTrackCount => RotationTracks.Count;
}

/// <summary>What one clip produced on one skeleton.</summary>
public readonly record struct BoundClip(string Kind, Animation? Anim, int Tracks);

/// <summary>
/// The server's clip library on the native side.
///
/// <b>Which clip.</b> The browser plays the LOCOMOTION roles through the
/// server's mapping (<c>locomotion: {walk, run, idle} → kind</c>,
/// <c>game/walk.setLocomotionClips</c>: a missing/empty role keeps its own
/// name), and resolves a kind along the character's set chain down to the
/// neutral set. The spike uses the NEUTRAL set only (<c>set</c> empty), solo
/// clips only (<c>role</c> empty): first listed entry whose lower-cased kind
/// equals the role's kind. <c>loop</c> missing = loop (§ A8).
///
/// <b>Import.</b> Each clip URL is downloaded and imported exactly once
/// (<see cref="LoadAsync"/> caches the task per URL) with Godot's runtime
/// <c>FBXDocument</c>; the generated scene is freed, the <see cref="Animation"/>
/// and the bone defaults are kept.
///
/// <b>Godot drops constant curves.</b> The clip FBX keys 52 bones (Lcl
/// Rotation) + the hips (Lcl Translation), but the importer only emits tracks
/// for curves that MOVE (idle: 40 rotation tracks, walk: 20) and stores the
/// constant value as the node default (= the skeleton rest of the imported
/// scene). A bone without a track would otherwise stay in the CHARACTER's bind
/// pose (T-pose forearms in idle). The retarget therefore writes a one-key
/// constant track from the clip bone's default for every clip bone the target
/// has — which restores the file's track list.
///
/// <b>Retarget (the spike's simplest one).</b> Bones are matched by name after
/// stripping a namespace (<c>…:</c>) and the <c>mixamorig</c> prefix (Godot
/// sanitises <c>mixamorig:Hips</c> to <c>mixamorig_Hips</c>), case-insensitive —
/// the browser's <c>normBoneName</c>. ROTATION tracks are copied verbatim (local
/// quaternions of the reference rig, written onto the character's bone).
/// The HIPS position keeps the target's rest x/z (the clip plays in place) and
/// scales the clip's hips height by the height ratio
/// <c>k = target hips rest height / source standing hips height</c>, i.e. the
/// browser's <c>rest + (y − ref)·k</c> = <c>y·k</c>; the source standing height
/// is the median of the IDLE clip's hips track (the browser's no-rig fallback).
/// Other position and all scale tracks are dropped. A clip that binds fewer than
/// <see cref="MinTracks"/> tracks is not played (browser <c>MIN_CLIP_TRACKS</c>).
///
/// What the browser does beyond this (<c>adaptExternalClips</c>,
/// <c>figures.ts</c>): rest-pose correction against the reference rig
/// <c>/assets/animation-rig</c> (q = K_p⁻¹·c·K_b per bone, so rigs whose bone
/// rolls differ from the reference get the same motion), the reference rig's
/// rest hips (113.032 units) as the standing height, hips scale-outlier
/// healing, root-motion paths for <c>keep</c>/<c>foot_lock</c> clips, per-rig
/// root-path relock and foot pinning (<c>legPin</c>), bridge lift/heading,
/// embedded clips winning per kind, clip transitions, set chains and
/// <c>activity_animation</c> clips, pace-matched walk playback.
/// </summary>
public sealed class ClipLibrary
{
    public const int MinTracks = 8;
    public static readonly string[] Roles = { "idle", "walk" };

    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly Dictionary<string, Task<ClipSource?>> _cache = new();

    public List<ClipEntry> Entries { get; } = new();
    public Dictionary<string, string> Locomotion { get; } = new();
    /// <summary>Role → clip, after <see cref="LoadRolesAsync"/>; null = no clip for that role.</summary>
    public Dictionary<string, ClipSource?> ByRole { get; } = new();
    public int ClipsLoaded { get; private set; }
    public int ClipsFailed { get; private set; }

    public ClipLibrary(IWorldSource source, Action<string> log)
    {
        _source = source;
        _log = log;
    }

    public void Parse(JsonElement root)
    {
        Entries.Clear();
        foreach (var c in Json.Arr(root, "clips"))
        {
            if (c.ValueKind != JsonValueKind.Object) continue;
            bool loop = !(c.TryGetProperty("loop", out var l) && l.ValueKind == JsonValueKind.False);
            var url = Json.Str(c, "url");
            if (url.Length == 0) continue;
            Entries.Add(new ClipEntry(Json.Str(c, "kind").ToLowerInvariant(), Json.Str(c, "role"),
                                      Json.Str(c, "set"), url, loop));
        }
        Locomotion.Clear();
        if (root.TryGetProperty("locomotion", out var loco) && loco.ValueKind == JsonValueKind.Object)
            foreach (var p in loco.EnumerateObject())
                if (p.Value.ValueKind == JsonValueKind.String)
                    Locomotion[p.Name] = p.Value.GetString()!.Trim().ToLowerInvariant();
    }

    /// <summary>The kind a locomotion role plays (<c>locomotionClip</c>): the mapping, else the role's own name.</summary>
    public string KindOf(string role)
        => Locomotion.TryGetValue(role, out var k) && k.Length > 0 ? k : role;

    /// <summary>Neutral-set solo clip of the role's kind, or null.</summary>
    public ClipEntry? Pick(string role)
    {
        var kind = KindOf(role);
        return Entries.FirstOrDefault(e => e.Kind == kind && e.Role.Length == 0 && e.Set.Length == 0);
    }

    private Task? _roles;

    /// <summary>Fetch the list, then download + import the idle and walk clips (once each).</summary>
    public Task LoadRolesAsync() => _roles ??= LoadRolesCore();

    /// <summary>Completes when the role clips are in (or failed); never throws.</summary>
    public async Task WaitRolesAsync()
    {
        if (_roles is null) return;
        try { await _roles; }
        catch (Exception) { /* reported by the caller of LoadRolesAsync */ }
    }

    private async Task LoadRolesCore()
    {
        using (var doc = await _source.GetAnimationClipsAsync()) Parse(doc.RootElement);
        foreach (var role in Roles)
        {
            var entry = Pick(role);
            if (entry is null)
            {
                _log($"clips: no neutral-set clip of kind '{KindOf(role)}' for role {role}");
                ByRole[role] = null;
                continue;
            }
            ByRole[role] = await LoadAsync(entry);
        }
    }

    /// <summary>One import per URL, shared by every caller.</summary>
    public Task<ClipSource?> LoadAsync(ClipEntry entry)
    {
        if (!_cache.TryGetValue(entry.Url, out var task))
            _cache[entry.Url] = task = ImportAsync(entry);
        return task;
    }

    private async Task<ClipSource?> ImportAsync(ClipEntry entry)
    {
        try
        {
            var bytes = await _source.GetBytesAsync(entry.Url);
            var clip = Import(bytes, entry);
            ClipsLoaded++;
            _log($"clip {entry.Kind}: {clip.Bones.Length} bones, {clip.Anim.GetTrackCount()} tracks "
                 + $"({clip.RotationTrackCount} rotation), {clip.Anim.Length:0.###} s, loop={entry.Loop}");
            return clip;
        }
        catch (Exception e)
        {
            ClipsFailed++;
            _log($"clip {entry.Kind} ({entry.Url}) failed: {e.Message}");
            return null;
        }
    }

    /// <summary>Runtime FBX import (main thread: it builds nodes), then keep only the data.</summary>
    public static ClipSource Import(byte[] fbx, ClipEntry entry)
    {
        // Through a temp file, not AppendFromBuffer: from a buffer the FBX
        // reader asks Godot's memory file for more bytes than remain and every
        // import prints two "Reading less data than requested" warnings
        // (harmless, but they drown the log). From a file it reads cleanly.
        var tmp = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"anima-clip-{Guid.NewGuid():N}.fbx");
        Node root;
        try
        {
            System.IO.File.WriteAllBytes(tmp, fbx);
            var doc = new FbxDocument();
            var state = new FbxState();
            var err = doc.AppendFromFile(tmp, state);
            if (err != Error.Ok) throw new InvalidOperationException($"FBX import failed: {err}");
            root = doc.GenerateScene(state) as Node ?? throw new InvalidOperationException("FBX scene is empty");
        }
        finally
        {
            try { System.IO.File.Delete(tmp); } catch (System.IO.IOException) { }
        }
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
            return new ClipSource
            {
                Kind = entry.Kind, Url = entry.Url, Loop = entry.Loop, Anim = anim,
                Bones = bones, RestRotations = rots, RestPositions = poss,
                RotationTracks = rot, PositionTracks = pos,
            };
        }
        finally
        {
            root.Free();
        }
    }

    /// <summary>
    /// The source's standing hips height: median of the idle clip's hips
    /// position track (browser fallback without a served rig), else the clip's
    /// own hips default.
    /// </summary>
    public double StandingHipsY(ClipSource fallback)
    {
        var src = ByRole.GetValueOrDefault("idle") ?? fallback;
        int hb = Array.FindIndex(src.Bones, b => NormBone(b) == "hips");
        if (hb < 0) return 0;
        if (src.PositionTracks.TryGetValue(src.Bones[hb], out var t))
        {
            int n = src.Anim.TrackGetKeyCount(t);
            if (n > 0)
            {
                var ys = Enumerable.Range(0, n).Select(k => (double)src.Anim.TrackGetKeyValue(t, k).AsVector3().Y)
                                   .Select(Math.Abs).OrderBy(y => y).ToArray();
                return ys[n / 2];
            }
        }
        return Math.Abs(src.RestPositions[hb].Y);
    }

    /// <summary>
    /// Build <paramref name="clip"/> for the skeleton under <paramref name="modelRoot"/>
    /// (track paths are relative to it — the AnimationPlayer's root node).
    /// </summary>
    public BoundClip Retarget(ClipSource clip, Node3D modelRoot, Skeleton3D skel)
    {
        var target = new Dictionary<string, int>();
        for (int i = 0; i < skel.GetBoneCount(); i++) target.TryAdd(NormBone(skel.GetBoneName(i)), i);
        var skelPath = modelRoot.GetPathTo(skel).ToString();
        double refY = StandingHipsY(clip);

        var anim = new Animation
        {
            Length = clip.Anim.Length,
            LoopMode = clip.Loop ? Animation.LoopModeEnum.Linear : Animation.LoopModeEnum.None,
        };
        int tracks = 0;
        for (int b = 0; b < clip.Bones.Length; b++)
        {
            var name = clip.Bones[b];
            var key = NormBone(name);
            if (!target.TryGetValue(key, out int ti)) continue;
            var path = new NodePath($"{skelPath}:{skel.GetBoneName(ti)}");

            int rt = anim.AddTrack(Animation.TrackType.Rotation3D);
            anim.TrackSetPath(rt, path);
            if (clip.RotationTracks.TryGetValue(name, out int st))
            {
                anim.TrackSetInterpolationType(rt, clip.Anim.TrackGetInterpolationType(st));
                for (int k = 0; k < clip.Anim.TrackGetKeyCount(st); k++)
                    anim.RotationTrackInsertKey(rt, clip.Anim.TrackGetKeyTime(st, k),
                                                clip.Anim.TrackGetKeyValue(st, k).AsQuaternion());
            }
            else
            {
                anim.RotationTrackInsertKey(rt, 0, clip.RestRotations[b]);
            }
            tracks++;

            if (key != "hips" || !(refY > 1e-6)) continue;
            // Hips: in place (target rest x/z), height = clip height · k,
            // measured in the model frame like the browser's world-y ratio.
            var parentXf = modelRoot.GlobalTransformOf(skel);
            int parent = skel.GetBoneParent(ti);
            var restLocal = skel.GetBoneRest(ti).Origin;
            var restModel = parent < 0 ? parentXf * restLocal : parentXf * skel.GetBoneGlobalRest(ti).Origin;
            double scaleK = restModel.Y / refY;
            var toLocal = parentXf.AffineInverse();
            Vector3 Map(double y)
            {
                var m = new Vector3(restModel.X, (float)(y * scaleK), restModel.Z);
                // A hips bone under another bone keeps its rest offset (spike: root hips only).
                return parent < 0 ? toLocal * m : restLocal + new Vector3(0, (float)(y * scaleK - restModel.Y), 0);
            }
            int pt = anim.AddTrack(Animation.TrackType.Position3D);
            anim.TrackSetPath(pt, path);
            if (clip.PositionTracks.TryGetValue(name, out int sp))
            {
                anim.TrackSetInterpolationType(pt, clip.Anim.TrackGetInterpolationType(sp));
                for (int k2 = 0; k2 < clip.Anim.TrackGetKeyCount(sp); k2++)
                    anim.PositionTrackInsertKey(pt, clip.Anim.TrackGetKeyTime(sp, k2),
                                                Map(Math.Abs(clip.Anim.TrackGetKeyValue(sp, k2).AsVector3().Y)));
            }
            else
            {
                anim.PositionTrackInsertKey(pt, 0, Map(Math.Abs(clip.RestPositions[b].Y)));
            }
            tracks++;
        }
        return tracks >= MinTracks ? new BoundClip(clip.Kind, anim, tracks) : new BoundClip(clip.Kind, null, tracks);
    }

    /// <summary>The browser's <c>normBoneName</c>, plus a namespace strip and Godot's <c>_</c> spelling.</summary>
    public static string NormBone(string name)
    {
        int colon = name.LastIndexOf(':');
        var s = colon >= 0 ? name[(colon + 1)..] : name;
        if (s.StartsWith("mixamorig", StringComparison.OrdinalIgnoreCase))
        {
            s = s[9..];
            while (s.Length > 0 && char.IsDigit(s[0])) s = s[1..];
            if (s.StartsWith('_')) s = s[1..];
        }
        return s.ToLowerInvariant();
    }

    /// <summary>Release the imported animations (they are Godot resources held from C#).</summary>
    public void Release()
    {
        foreach (var task in _cache.Values)
            if (task.IsCompletedSuccessfully && task.Result is { } clip) clip.Anim.Dispose();
        _cache.Clear();
        ByRole.Clear();
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
