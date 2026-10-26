using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// What a bound clip carries besides its tracks — the browser's per-clip stores (<c>clipRootPath</c>,
/// <c>clipRootTurn</c>, <c>clipBridgeLift</c>, <c>userData.groundOffset</c>), measured once per rig at fit time.
/// </summary>
public sealed class ClipExtras
{
    public RootPath? Path { get; set; }
    public RootTurn? Turn { get; set; }
    public BridgeLiftSpec? Lift { get; set; }
    /// <summary>The turn's pivot (the hips' rest point) in the body's frame, template units (the rig frame applied).</summary>
    public V3? PivotFrame { get; set; }
    /// <summary>How far the clip holds the body over the bind pose's lowest point, template units (≥ 0).</summary>
    public double GroundOffset { get; set; }
}

/// <summary>
/// The Godot edge of the per-rig bridge fit (figures.ts <c>fitLibraryAsync</c> after <c>adaptExternalClips</c>): the
/// model template's skeleton as a <see cref="ProbeRig"/>, a bound Animation as a <see cref="ProbeClip"/> resampled at
/// the times the probe reads (Godot's own track interpolation), the probe's rewritten tracks written back into the
/// Animation (the per-rig relock, leg pin and turn are BAKED — no run-time cost), and the skinned surfaces for the
/// clip ground offset. All the arithmetic is the core's (<see cref="FootLockMeasure"/>, <see cref="ClipGround"/>).
/// </summary>
public static class BridgeFit
{
    public static Affine ToAffine(Transform3D t)
        => new(t.Basis.Column0.X, t.Basis.Column0.Y, t.Basis.Column0.Z,
               t.Basis.Column1.X, t.Basis.Column1.Y, t.Basis.Column1.Z,
               t.Basis.Column2.X, t.Basis.Column2.Y, t.Basis.Column2.Z,
               t.Origin.X, t.Origin.Y, t.Origin.Z);

    /// <summary>The model root's own transform times the chain down to <paramref name="node"/> (three's probe world).</summary>
    public static Transform3D FrameOf(Node3D modelRoot, Node3D node) => modelRoot.Transform * modelRoot.GlobalTransformOf(node);

    /// <summary>The skeleton as the probe sees it: the frame of the Skeleton3D, its bones at their rests.</summary>
    public static ProbeRig RigOf(Node3D modelRoot, Skeleton3D skel)
    {
        var nodes = new List<ProbeNode>();
        for (int i = 0; i < skel.GetBoneCount(); i++)
        {
            var rest = skel.GetBoneRest(i);
            var q = rest.Basis.GetRotationQuaternion();
            var s = rest.Basis.Scale;
            nodes.Add(new ProbeNode(skel.GetBoneName(i), skel.GetBoneParent(i), true, new V3(rest.Origin.X, rest.Origin.Y, rest.Origin.Z),
                                    new Quat(q.X, q.Y, q.Z, q.W), new V3(s.X, s.Y, s.Z)));
        }
        return new ProbeRig(ToAffine(FrameOf(modelRoot, skel)), nodes);
    }

    /// <summary>Bone name → (rotation track, position track) of a bound Animation (−1 = none).</summary>
    private static Dictionary<string, (int Rot, int Pos)> TracksOf(Animation anim)
    {
        var map = new Dictionary<string, (int Rot, int Pos)>();
        for (int t = 0; t < anim.GetTrackCount(); t++)
        {
            var bone = anim.TrackGetPath(t).GetConcatenatedSubNames();
            if (bone.Length == 0) continue;
            var cur = map.TryGetValue(bone, out var e) ? e : (-1, -1);
            switch (anim.TrackGetType(t))
            {
                case Animation.TrackType.Rotation3D: if (cur.Item1 < 0) map[bone] = (t, cur.Item2); break;
                case Animation.TrackType.Position3D: if (cur.Item2 < 0) map[bone] = (cur.Item1, t); break;
            }
        }
        return map;
    }

    /// <summary>
    /// <paramref name="anim"/> as a probe clip whose every rotation/position track is sampled (Godot's interpolation) at
    /// <paramref name="times"/>; <paramref name="rawHipsKeys"/> keeps the hips position track on its OWN keys instead
    /// (the relock reads its sample times from there).
    /// </summary>
    public static ProbeClip ClipOf(string name, Animation anim, IReadOnlyList<double> times, bool rawHipsKeys)
    {
        var tracks = new List<ProbeTrack>();
        var keyTimes = times.Select(t => (float)t).ToArray();
        foreach (var (bone, (rot, pos)) in TracksOf(anim))
        {
            if (rot >= 0)
            {
                var v = new float[times.Count * 4];
                for (int k = 0; k < times.Count; k++)
                {
                    var q = anim.RotationTrackInterpolate(rot, times[k]);
                    v[k * 4] = q.X; v[k * 4 + 1] = q.Y; v[k * 4 + 2] = q.Z; v[k * 4 + 3] = q.W;
                }
                tracks.Add(new ProbeTrack { Node = bone, Prop = "quaternion", Times = keyTimes, Values = v });
            }
            if (pos >= 0)
            {
                if (rawHipsKeys && BoneNames.Norm(bone).EndsWith("hips", StringComparison.Ordinal))
                {
                    int n = anim.TrackGetKeyCount(pos);
                    var kt = new float[n];
                    var kv = new float[n * 3];
                    for (int k = 0; k < n; k++)
                    {
                        kt[k] = (float)anim.TrackGetKeyTime(pos, k);
                        var p = anim.TrackGetKeyValue(pos, k).AsVector3();
                        kv[k * 3] = p.X; kv[k * 3 + 1] = p.Y; kv[k * 3 + 2] = p.Z;
                    }
                    tracks.Add(new ProbeTrack { Node = bone, Prop = "position", Times = kt, Values = kv });
                    continue;
                }
                var v = new float[times.Count * 3];
                for (int k = 0; k < times.Count; k++)
                {
                    var p = anim.PositionTrackInterpolate(pos, times[k]);
                    v[k * 3] = p.X; v[k * 3 + 1] = p.Y; v[k * 3 + 2] = p.Z;
                }
                tracks.Add(new ProbeTrack { Node = bone, Prop = "position", Times = keyTimes, Values = v });
            }
        }
        return new ProbeClip { Name = name, Duration = anim.Length, Tracks = tracks };
    }

    /// <summary>
    /// The relock's probe clip of a bound bridge: every track sampled at <see cref="FootLockMeasure.SampleTimes"/> of the
    /// clip (the hips position track's keys, or 30 fps), the travel path attached.
    /// </summary>
    public static ProbeClip RelockClipOf(string name, Animation anim, RootPath path)
    {
        var raw = ClipOf(name, anim, Array.Empty<double>(), rawHipsKeys: true);
        var times = FootLockMeasure.SampleTimes(raw);
        var clip = ClipOf(name, anim, times, rawHipsKeys: false);
        clip.Path = path;
        return clip;
    }

    /// <summary>
    /// Copy the tracks the probe REWROTE (leg pin, turn) back into <paramref name="anim"/>: the old track's keys are
    /// replaced by the probe's (linear, like three's interpolants); a track the animation did not have is added.
    /// </summary>
    public static int WriteBack(ProbeClip clip, Animation anim, string skelPath)
    {
        var map = TracksOf(anim);
        int written = 0;
        foreach (var t in clip.Tracks.Where(t => t.Rewritten))
        {
            bool rot = t.Prop == "quaternion";
            int idx = map.TryGetValue(t.Node, out var e) ? (rot ? e.Rot : e.Pos) : -1;
            if (idx < 0)
            {
                idx = anim.AddTrack(rot ? Animation.TrackType.Rotation3D : Animation.TrackType.Position3D);
                anim.TrackSetPath(idx, new NodePath($"{skelPath}:{t.Node}"));
                map[t.Node] = rot ? (idx, map.TryGetValue(t.Node, out var o) ? o.Pos : -1) : (map.TryGetValue(t.Node, out var o2) ? o2.Rot : -1, idx);
            }
            for (int k = anim.TrackGetKeyCount(idx) - 1; k >= 0; k--) anim.TrackRemoveKey(idx, k);
            anim.TrackSetInterpolationType(idx, Animation.InterpolationType.Linear);
            for (int k = 0; k < t.Times.Length; k++)
            {
                if (rot)
                    anim.RotationTrackInsertKey(idx, t.Times[k],
                        new Quaternion(t.Values[k * 4], t.Values[k * 4 + 1], t.Values[k * 4 + 2], t.Values[k * 4 + 3]).Normalized());
                else
                    anim.PositionTrackInsertKey(idx, t.Times[k], new Vector3(t.Values[k * 3], t.Values[k * 3 + 1], t.Values[k * 3 + 2]));
            }
            written++;
        }
        return written;
    }

    /// <summary>The skinned surfaces under <paramref name="modelRoot"/> bound to <paramref name="skel"/>, as probe skins.</summary>
    public static List<ProbeSkin> SkinsOf(Node3D modelRoot, Skeleton3D skel)
    {
        var list = new List<ProbeSkin>();
        foreach (var mi in Walk(modelRoot).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is not { } mesh || mi.Skin is not { } skin) continue;
            if (mi.GetNodeOrNull<Skeleton3D>(mi.Skeleton) is { } s && s != skel) continue;
            int binds = skin.GetBindCount();
            var bindNodes = new int[binds];
            var bindPoses = new Affine[binds];
            for (int i = 0; i < binds; i++)
            {
                string name = skin.GetBindName(i);
                int bone = name.Length > 0 ? skel.FindBone(name) : skin.GetBindBone(i);
                bindNodes[i] = bone >= 0 && bone < skel.GetBoneCount() ? bone : 0;
                bindPoses[i] = ToAffine(skin.GetBindPose(i));
            }
            var frame = ToAffine(FrameOf(modelRoot, mi));
            for (int sf = 0; sf < mesh.GetSurfaceCount(); sf++)
            {
                var arrays = mesh.SurfaceGetArrays(sf);
                var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
                var bones = arrays[(int)Mesh.ArrayType.Bones].AsInt32Array();
                var weights = arrays[(int)Mesh.ArrayType.Weights].AsFloat32Array();
                if (verts.Length == 0 || bones.Length == 0 || bones.Length != weights.Length || bones.Length % verts.Length != 0) continue;
                var rest = new float[verts.Length * 3];
                for (int v = 0; v < verts.Length; v++)
                {
                    rest[v * 3] = verts[v].X; rest[v * 3 + 1] = verts[v].Y; rest[v * 3 + 2] = verts[v].Z;
                }
                list.Add(new ProbeSkin
                {
                    Owner = mi,
                    Rest = rest, Bones = bones, Weights = weights, Slots = bones.Length / verts.Length,
                    BindNodes = bindNodes, BindPoses = bindPoses, Frame = frame,
                });
            }
        }
        return list;
    }

    /// <summary>
    /// three's <c>Box3.setFromObject(template)</c> in the frame of the model root's PARENT (its own transform included):
    /// a skinned mesh by its vertices skinned in the rest pose (<c>SkinnedMesh.computeBoundingBox</c>), any other mesh
    /// by its AABB through the node chain.
    /// </summary>
    public static Aabb BindBox(Node3D modelRoot)
    {
        Aabb? box = null;
        void Add(Vector3 p) => box = box is { } b ? b.Expand(p) : new Aabb(p, Vector3.Zero);
        foreach (var mi in Walk(modelRoot).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is null) continue;
            if (mi.Skin is not null && mi.GetNodeOrNull<Skeleton3D>(mi.Skeleton) is { } skel)
            {
                var rig = RigOf(modelRoot, skel);
                var pose = new RigPose(rig);
                var rootInv = RigMath.Inverse(rig.Root);
                bool any = false;
                foreach (var sk in SkinsOf(modelRoot, skel).Where(s => ReferenceEquals(s.Owner, mi)))
                {
                    var mats = sk.BindNodes.Select((n, b) => rootInv.Times(pose.World(n)).Times(sk.BindPoses[b])).ToArray();
                    for (int v = 0; v < sk.VertexCount; v++)
                    {
                        double sx = 0, sy = 0, sz = 0;
                        for (int k = 0; k < sk.Slots; k++)
                        {
                            float w = sk.Weights[v * sk.Slots + k];
                            int bi = sk.Bones[v * sk.Slots + k];
                            if (w <= 0 || (uint)bi >= (uint)mats.Length) continue;
                            var p = mats[bi].Apply(sk.Rest[v * 3], sk.Rest[v * 3 + 1], sk.Rest[v * 3 + 2]);
                            sx += w * p.X; sy += w * p.Y; sz += w * p.Z;
                        }
                        var q = sk.Frame.Apply(sx, sy, sz);
                        Add(new Vector3((float)q.X, (float)q.Y, (float)q.Z));
                        any = true;
                    }
                }
                if (any) continue;
            }
            var xf = FrameOf(modelRoot, mi);
            var a = mi.Mesh.GetAabb();
            for (int c = 0; c < 8; c++) Add(xf * a.GetEndpoint(c));
        }
        return box ?? new Aabb();
    }

    /// <summary>The ground-offset probe clip: every track sampled at the distinct times of <see cref="ClipGround.SampleTimes"/>.</summary>
    public static ProbeClip GroundClipOf(string name, Animation anim)
    {
        var times = ClipGround.SampleTimes(anim.Length).Distinct().OrderBy(t => t).ToList();
        return ClipOf(name, anim, times, rawHipsKeys: false);
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}
