using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The secondary motion on a Godot figure (figures.ts: <c>createSecondaryMotion(THREE, this.root, motion, template)</c>
/// in the Figure constructor, <c>secondary.update(realDelta, {frozen, far})</c> at the end of <c>Figure.update</c>):
/// a <see cref="SkeletonModifier3D"/> under the figure's <see cref="Skeleton3D"/>, so Godot runs it AFTER the
/// AnimationMixer has posed the bones, every frame, with the real frame time. The arithmetic is the core's
/// (<see cref="SecondaryMotion"/> on a <see cref="MotionRig"/> of the skeleton's bones, base = the skeleton's global
/// transform, world metres).
///
/// Godot's bone pose is position + rotation + scale; the motion's bone matrix is not (a symmetric scale in an oblique
/// frame, i.e. shear), so the driven bones' poses written here are only the nearest TRS (picking, attachments), and the
/// EXACT skin matrices <c>global · bind pose</c> of every driven/rigid bind and its descendants are pushed to the
/// RenderingServer right after the skeleton's own skin upload (<c>skeleton_3d.cpp</c> NOTIFICATION_UPDATE_SKELETON:
/// modifiers → skin upload → pose restore, one deferred notification; a deferred call queued from the modifier runs
/// after it in the same message-queue flush).
///
/// The skinned normals are corrected per surface by <see cref="SkinNormalMaterial"/> (the browser's inverse transpose,
/// <c>installSkinnedNormalCorrection</c>), fed the per-bind linear parts each step.
/// </summary>
public partial class SecondaryMotionModifier : SkeletonModifier3D
{
    private sealed record SkinBinding(MeshInstance3D Mesh, int[] Nodes, Affine[] BindPoses);

    private sealed record Surface(MeshInstance3D Mesh, int Index, Material? Previous, ShaderMaterial Material, SkinBinding Skin);

    private static readonly ConditionalWeakTable<Mesh, Dictionary<int, (V3 Centroid, double Mass)>> CentroidCache = new();

    private readonly MotionRig _rig;
    private readonly SecondaryMotion _motion;
    private readonly List<SkinBinding> _skins = new();
    private readonly List<Surface> _surfaces = new();
    private readonly List<(Rid Skeleton, int Bind, Transform3D Xf)> _push = new();
    private bool _pushQueued;
    private bool _resetRequested;

    /// <summary>The world stands still (<c>game_rate</c> 0, or a pair at rate 0): no dynamics, the particles ride along.</summary>
    public bool Frozen { get; set; }
    /// <summary>The low tier (<c>secondaryFar = model.tier === 'low'</c>): reset and no swing.</summary>
    public bool Far { get; set; }
    /// <summary>The check drives the steps itself (<see cref="StepNow"/>); the engine's process call does nothing.</summary>
    public bool Manual { get; set; }
    /// <summary>The payload revision configured last.</summary>
    public string? Rev { get; private set; }
    /// <summary>Correct the skinned normals (<see cref="SkinNormalMaterial"/>); false = stock Godot normals.</summary>
    public bool CorrectNormals { get; }

    public MotionRig Rig => _rig;
    public SecondaryMotion Motion => _motion;
    public int CorrectedSurfaces => _surfaces.Count;
    /// <summary>The surfaces whose material could not be carried (their normals stay stock), with the reason.</summary>
    public List<string> Skipped { get; } = new();
    /// <summary>The skin matrices of the last step for every bind of every skin (skeleton space), the check's skinning.</summary>
    public IReadOnlyList<(MeshInstance3D Mesh, Affine[] Skin)> LastSkins => _lastSkins;
    private readonly List<(MeshInstance3D, Affine[])> _lastSkins = new();
    /// <summary>The binds pushed exactly to the RenderingServer in the last step.</summary>
    public int PushedBinds { get; private set; }
    public int Steps { get; private set; }

    private SecondaryMotionModifier(MotionRig rig, SecondaryMotion motion, bool correctNormals, string? rev)
    {
        Name = "SecondaryMotion";
        _rig = rig;
        _motion = motion;
        CorrectNormals = correctNormals;
        Rev = rev;
    }

    public static Affine ToAffine(Transform3D t) => BridgeFit.ToAffine(t);

    public static Transform3D ToTransform(Affine a)
        => new(new Basis(new Vector3((float)a.Xx, (float)a.Xy, (float)a.Xz), new Vector3((float)a.Yx, (float)a.Yy, (float)a.Yz),
                         new Vector3((float)a.Zx, (float)a.Zy, (float)a.Zz)),
               new Vector3((float)a.Ox, (float)a.Oy, (float)a.Oz));

    /// <summary>The skeleton's bones as a rig at their RESTS (the bind pose) under <paramref name="baseFrame"/>.</summary>
    public static MotionRig RigOf(Skeleton3D skel, Affine baseFrame)
    {
        int n = skel.GetBoneCount();
        var rig = new MotionRig(Enumerable.Range(0, n).Select(skel.GetBoneName).ToList(),
                                Enumerable.Range(0, n).Select(skel.GetBoneParent).ToList()) { Base = baseFrame };
        for (int i = 0; i < n; i++) rig.Local[i] = ToAffine(skel.GetBoneRest(i));
        rig.UpdateWorld();
        return rig;
    }

    /// <summary>glTF extras <c>anchor_blend</c> of a bone (Godot 4.7 imports a joint's extras as the bone meta <c>extras</c>).</summary>
    public static IReadOnlyDictionary<string, double>? AnchorBlendOf(Skeleton3D skel, int bone)
    {
        if (!skel.HasBoneMeta(bone, "extras")) return null;
        var extras = skel.GetBoneMeta(bone, "extras");
        if (extras.VariantType != Variant.Type.Dictionary) return null;
        var dict = extras.AsGodotDictionary();
        if (!dict.TryGetValue("anchor_blend", out var raw) || raw.VariantType != Variant.Type.Dictionary) return null;
        var result = new Dictionary<string, double>();
        foreach (var (k, v) in raw.AsGodotDictionary())
        {
            // Number(share): a non-number reads NaN and is dropped by the core's filter.
            double share = v.VariantType is Variant.Type.Float or Variant.Type.Int ? v.AsDouble() : double.NaN;
            result[k.AsString()] = share;
        }
        return result;
    }

    /// <summary>
    /// Build the motion for a figure body (<paramref name="body"/> = the figure's body root, the skeleton inside it), or
    /// null when no bone of <paramref name="payload"/> exists on this skeleton (the browser's matching test — the caller
    /// asks again when the payload revision changes). The bind frame is the skeleton relative to the body's parent
    /// (three builds before the figure root is placed). Added as a child of the skeleton.
    /// </summary>
    public static SecondaryMotionModifier? TryCreate(Node3D body, Skeleton3D skel, MotionPayload? payload, bool correctNormals = true)
    {
        if (skel.GetBoneCount() == 0) return null;
        var bindBase = ToAffine(body.Transform * body.GlobalTransformOf(skel));
        var rig = RigOf(skel, bindBase);
        if (!SecondaryMotion.Matches(rig, payload)) return null;
        var probes = BridgeFit.SkinsOf(body, skel);
        var skins = probes.Select(p => new MotionSkin(p.BindNodes, p.BindPoses, p.Rest, p.Bones, p.Weights)).ToList();
        var firstMesh = probes.Select(p => (p.Owner as MeshInstance3D)?.Mesh).FirstOrDefault(m => m is not null);
        Dictionary<int, (V3, double)> centroids;
        if (firstMesh is not null && CentroidCache.TryGetValue(firstMesh, out var cached)) centroids = cached;
        else
        {
            centroids = SecondaryMotion.MeasureCentroids(skins);
            if (firstMesh is not null) CentroidCache.AddOrUpdate(firstMesh, centroids);
        }
        var joints = probes.SelectMany(p => p.BindNodes).Where(n => n >= 0).ToList();
        var motion = new SecondaryMotion(rig, joints, centroids, n => AnchorBlendOf(skel, n), payload);
        var mod = new SecondaryMotionModifier(rig, motion, correctNormals, payload?.Rev);
        foreach (var mi in probes.Select(p => p.Owner).OfType<MeshInstance3D>().Distinct())
        {
            var skin = mi.Skin!;
            int binds = skin.GetBindCount();
            var nodes = new int[binds];
            var poses = new Affine[binds];
            for (int i = 0; i < binds; i++)
            {
                string name = skin.GetBindName(i);
                int bone = name.Length > 0 ? skel.FindBone(name) : skin.GetBindBone(i);
                nodes[i] = bone >= 0 && bone < skel.GetBoneCount() ? bone : 0;
                poses[i] = ToAffine(skin.GetBindPose(i));
            }
            mod._skins.Add(new SkinBinding(mi, nodes, poses));
        }
        skel.AddChild(mod);
        mod.InstallMaterials();
        return mod;
    }

    /// <summary>Swap every carried surface to its correcting twin (per figure: the uniform is this skeleton's).</summary>
    private void InstallMaterials()
    {
        if (!CorrectNormals || _motion.ParticleCount + _motion.RigidCount == 0) return;
        foreach (var skin in _skins)
        {
            var mi = skin.Mesh;
            if (mi.Mesh is not { } mesh) continue;
            if (skin.Nodes.Length > SkinNormalMaterial.MaxBinds)
            {
                Skipped.Add($"{mi.Name}: {skin.Nodes.Length} binds > {SkinNormalMaterial.MaxBinds}");
                continue;
            }
            for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            {
                var previous = mi.GetSurfaceOverrideMaterial(s);
                var source = previous ?? mi.MaterialOverride ?? mesh.SurfaceGetMaterial(s);
                if (mesh is ArrayMesh am && (am.SurfaceGetFormat(s) & Mesh.ArrayFormat.FlagUse8BoneWeights) != 0)
                {
                    Skipped.Add($"{mi.Name}/{s}: 8 bone weights");
                    continue;
                }
                if (source is not BaseMaterial3D bm)
                {
                    Skipped.Add($"{mi.Name}/{s}: not a standard material");
                    continue;
                }
                if (SkinNormalMaterial.TryConvert(bm) is not { } twin)
                {
                    Skipped.Add($"{mi.Name}/{s}: {SkinNormalMaterial.Unsupported(bm)}");
                    continue;
                }
                mi.SetSurfaceOverrideMaterial(s, twin);
                _surfaces.Add(new Surface(mi, s, previous, twin, skin));
            }
        }
    }

    private void RemoveMaterials()
    {
        foreach (var s in _surfaces)
            if (IsInstanceValid(s.Mesh)) s.Mesh.SetSurfaceOverrideMaterial(s.Index, s.Previous);
        _surfaces.Clear();
    }

    /// <summary>The surfaces' correcting materials (the check reads their uniforms).</summary>
    public IEnumerable<ShaderMaterial> Materials => _surfaces.Select(s => s.Material);

    /// <summary><c>configure(payload)</c> on a revision change.</summary>
    public void Configure(MotionPayload? payload)
    {
        _motion.Configure(payload);
        Rev = payload?.Rev;
        if (_motion.ParticleCount + _motion.RigidCount == 0) RemoveMaterials();
        else if (_surfaces.Count == 0) InstallMaterials();
    }

    /// <summary><c>secondary.reset()</c> before the next step (a jump, a snap, an arrival).</summary>
    public void RequestReset() => _resetRequested = true;

    public override void _ProcessModificationWithDelta(double delta)
    {
        if (!Manual) StepNow(delta);
    }

    /// <summary>
    /// One step: read the posed bones, run the core, write the driven bones' nearest TRS, queue the exact skin
    /// matrices for the RenderingServer and feed the normal materials.
    /// </summary>
    public void StepNow(double delta)
    {
        var skel = GetSkeleton();
        if (skel is null) return;
        Steps++;
        _rig.Base = ToAffine(skel.IsInsideTree() ? skel.GlobalTransform : skel.Transform);
        for (int i = 0; i < _rig.Count; i++) _rig.Local[i] = ToAffine(skel.GetBonePose(i));
        if (_resetRequested)
        {
            _motion.Reset();
            _resetRequested = false;
        }
        _motion.Update(delta, Frozen, Far);
        var owned = _motion.Owned;
        if (owned.Count == 0) return;
        foreach (int i in owned)
        {
            var t = ToTransform(_rig.Local[i]);
            skel.SetBonePosePosition(i, t.Origin);
            skel.SetBonePoseRotation(i, t.Basis.GetRotationQuaternion());
            skel.SetBonePoseScale(i, t.Basis.Scale);
        }
        // Every bind whose bone is owned or hangs below an owned one gets its exact matrix.
        var affected = new bool[_rig.Count];
        foreach (int i in _rig.PreOrder)
            affected[i] = owned.Contains(i) || (_rig.Parent(i) is var p && p >= 0 && affected[p]);
        var baseInv = _rig.Base.Inverted();
        _push.Clear();
        _lastSkins.Clear();
        foreach (var skin in _skins)
        {
            var mats = new Affine[skin.Nodes.Length];
            for (int j = 0; j < mats.Length; j++)
            {
                mats[j] = baseInv.Times(_rig.World[skin.Nodes[j]]).Times(skin.BindPoses[j]);
                if (affected[skin.Nodes[j]] && IsInstanceValid(skin.Mesh) && skin.Mesh.GetSkinReference() is { } sr)
                    _push.Add((sr.GetSkeleton(), j, ToTransform(mats[j])));
            }
            _lastSkins.Add((skin.Mesh, mats));
        }
        PushedBinds = _push.Count;
        foreach (var s in _surfaces)
        {
            var mats = _lastSkins.FirstOrDefault(e => e.Item1 == s.Mesh).Item2;
            if (mats is not null) SkinNormalMaterial.SetSkin(s.Material, mats);
        }
        if (_push.Count > 0 && !_pushQueued)
        {
            _pushQueued = true;
            Callable.From(Push).CallDeferred();
        }
    }

    /// <summary>After the skeleton's own skin upload of this frame: the exact matrices win.</summary>
    private void Push()
    {
        _pushQueued = false;
        foreach (var (rid, bind, xf) in _push)
            if (rid.IsValid) RenderingServer.SkeletonBoneSetTransform(rid, bind, xf);
    }

    /// <summary><c>dispose()</c>: the bones and the materials back to the skeleton's own.</summary>
    public void Release()
    {
        _motion.Dispose();
        RemoveMaterials();
        if (IsInstanceValid(this)) QueueFree();
    }
}
