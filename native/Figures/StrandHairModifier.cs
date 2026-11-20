using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// What a figure needs to bind its hair per strand (figureRuntime.ts <c>loadStrandRecord</c> + the GLB's per-vertex
/// binding): the template's strand primitives read from the GLB bytes (<see cref="StrandGlb.Read"/>; Godot's import
/// drops the attributes) and the record of <c>model.hair_strands</c> (<see cref="StrandRecordCache.Get"/>).
/// </summary>
public sealed record StrandHairSource(IReadOnlyList<StrandGlbPrimitive> Primitives,
                                      Func<(StrandRecordState State, HairStrandRecord? Record)> Record);

/// <summary>
/// The per-strand hair of ONE figure on Godot (hairSim.ts <c>createStrandHair</c> — the clock and the sim are
/// <see cref="StrandHairDriver"/>'s, this class is the three half): a <see cref="SkeletonModifier3D"/> under the figure's
/// skeleton, so it steps after the AnimationMixer and the secondary motion on the frame's final pose, with the frame
/// time.
///
/// THE MESH. The skinned surface whose positions are the record's primitive (<see cref="StrandGlbPrimitive"/>, matched
/// bit for bit, Godot's vertex order via <see cref="StrandGlbPrimitive.Kept"/>). Nothing changes on it until
/// <see cref="SetEnabled"/>(true): then the MeshInstance gets an <see cref="ArrayMesh"/> CLONE owned by this handle
/// (figures are duplicates sharing their template's mesh), uncompressed, its card vertices skinned to the Head bind
/// alone (index head, weights (1, 0, 0, 0); the scalp cap, card 0, keeps its skin); every stepping frame the rebuilt
/// positions and normals (head-bind space) go into the clone's vertex buffer with ONE
/// <c>RenderingServer.MeshSurfaceUpdateVertexRegion</c> (<see cref="StrandUpload"/>). The upload happens inside the
/// skeleton's modifier pass, i.e. before the skeleton's own skin upload of the same update, which bumps the skeleton
/// version and so makes the GPU re-skin the instance from the new buffer (renderer_rd mesh_storage: an instance is
/// re-skinned when its skeleton's version changed). Off: the template's mesh goes back, the clone is dropped.
///
/// THE FRAME. Godot's skin matrix of a bind is <c>bone global pose · bind pose</c> (skeleton space) and the geometry
/// space IS the bind space (no three <c>bindMatrix</c>), so the endpoint rule's bind→world of a joint of the hair
/// skin is <c>skeleton global · bone global pose · bind pose</c> — the follow matrices, the head frame and, for the
/// body capsules, <see cref="CollisionBinding.Update"/> with the identity mesh frame (README "Hair chains", the
/// accepted deviation).
///
/// COLLIDERS (Ruling H-R7): the record's hair capsules without the head region, bound to the BODY skins' joints
/// (<see cref="CollisionBinding.Bind"/> under <see cref="Collision.Version"/>); their bind ends are the bind-rule
/// reference. Partners are not ported (own capsules only).
/// </summary>
public partial class StrandHairModifier : SkeletonModifier3D
{
    /// <summary>The capsule region the strand sim leaves out (Ruling H-R7).</summary>
    public const string SkippedRegion = "head";

    private readonly MeshInstance3D _mesh;
    private readonly ArrayMesh _template;
    private readonly int _surface;
    private readonly int _headBind, _headBone;
    private readonly Affine _headBindPose;
    private readonly int[] _followBones;
    private readonly Affine[] _followBindPoses;
    private readonly CollisionBinding? _collision;
    private readonly Node3D _root;
    private ArrayMesh? _clone;
    private byte[]? _buffer;
    private StrandVertexLayout _layout;
    private readonly Stopwatch _clock = new();

    public StrandHairDriver Driver { get; }
    public HairStrandRecord Record => Driver.Record;
    /// <summary>The hair mesh it drives.</summary>
    public MeshInstance3D Mesh => _mesh;
    public int Surface => _surface;
    /// <summary>The ids of the capsules the sim collides with (hairSim.ts <c>capsuleIds</c>).</summary>
    public IReadOnlyList<string> CapsuleIds { get; }
    /// <summary>Godot vertex → GLB vertex of the hair primitive.</summary>
    public int[] Kept { get; }
    public bool Enabled => _clone is not null;
    /// <summary>This frame's world freeze (nothing is stepped or written).</summary>
    public bool Frozen { get; set; }
    /// <summary>The check steps it itself (<see cref="StepNow"/>).</summary>
    public bool Manual { get; set; }
    /// <summary>The clone's vertex-buffer bytes as last uploaded (the check reads them back), null while off.</summary>
    public byte[]? Uploaded => _buffer;
    public StrandVertexLayout Layout => _layout;
    public int Uploads { get; private set; }
    /// <summary>ms of the last encode + upload call (the driver's own cost is <see cref="StrandHairDriver.CostMs"/>).</summary>
    public double LastUploadMs { get; private set; }

    private StrandHairModifier(MeshInstance3D mesh, int surface, int headBind, int headBone, Affine headBindPose, int[] followBones,
                               Affine[] followBindPoses, CollisionBinding? collision, StrandHairDriver driver, Node3D root, int[] kept)
    {
        Name = "StrandHair";
        _mesh = mesh;
        _template = (ArrayMesh)mesh.Mesh;
        _surface = surface;
        _headBind = headBind;
        _headBone = headBone;
        _headBindPose = headBindPose;
        _followBones = followBones;
        _followBindPoses = followBindPoses;
        _collision = collision;
        Driver = driver;
        _root = root;
        Kept = kept;
        CapsuleIds = collision?.Capsules.Select(c => c.Capsule.Id).ToList() ?? new List<string>();
    }

    /// <summary>
    /// hairSim.ts <c>createStrandHair</c>: bind <paramref name="record"/> to the hair surface under <paramref name="body"/>.
    /// Null (nothing touched, <paramref name="why"/> says why) when no skinned surface is one of the strand primitives,
    /// the record's head or follow bones are not binds of that surface's skin, or record and mesh do not belong
    /// together (<see cref="StrandMismatch"/>). Added under <paramref name="skel"/>, before the first-person modifier.
    /// </summary>
    public static StrandHairModifier? TryCreate(Node3D body, Skeleton3D skel, Node3D root, IReadOnlyList<StrandGlbPrimitive> primitives,
                                                HairStrandRecord record, out string why)
    {
        why = "";
        var candidates = primitives.Where(p => p.Has(record.VertexCard) && p.Has(record.VertexU)).ToList();
        if (candidates.Count == 0) { why = "no primitive carries " + record.VertexCard + " / " + record.VertexU; return null; }
        MeshInstance3D? mesh = null;
        int surface = -1;
        StrandGlbPrimitive? prim = null;
        Godot.Collections.Array? arrays = null;
        foreach (var mi in Walk(body).OfType<MeshInstance3D>())
        {
            if (mi.Skin is null || mi.Mesh is not ArrayMesh m) continue;
            for (int s = 0; s < m.GetSurfaceCount() && prim is null; s++)
            {
                var fits = candidates.Where(c => c.Kept.Length == SurfaceVertexCount(m, s)).ToList();
                if (fits.Count == 0) continue;
                var a = m.SurfaceGetArrays(s);
                var pos = Flat(a[(int)Godot.Mesh.ArrayType.Vertex].AsVector3Array());
                foreach (var c in fits)
                    if (StrandGlb.Matches(c, pos)) { prim = c; mesh = mi; surface = s; arrays = a; break; }
            }
            if (prim is not null) break;
        }
        if (prim is null || mesh is null || arrays is null) { why = "no skinned surface matches the strand primitive"; return null; }
        var skin = mesh.Skin!;
        int BindOf(string bone)
        {
            string key = BoneNames.Norm(bone);
            for (int i = 0; i < skin.GetBindCount(); i++)
            {
                string name = skin.GetBindName(i);
                if (name.Length == 0 && skin.GetBindBone(i) is var b && b >= 0 && b < skel.GetBoneCount()) name = skel.GetBoneName(b);
                if (BoneNames.Norm(name) == key) return i;
            }
            return -1;
        }
        int BoneOf(int bind)
        {
            string name = skin.GetBindName(bind);
            int bone = name.Length > 0 ? skel.FindBone(name) : skin.GetBindBone(bind);
            return bone >= 0 && bone < skel.GetBoneCount() ? bone : -1;
        }
        int headBind = BindOf(record.HeadBone);
        var followBinds = record.FollowBones.Select(BindOf).ToArray();
        if (headBind < 0 || followBinds.Length == 0 || followBinds.Any(i => i < 0)) { why = "head or follow bone not in the hair skin"; return null; }
        int headBone = BoneOf(headBind);
        var followBones = followBinds.Select(BoneOf).ToArray();
        if (headBone < 0 || followBones.Any(b => b < 0)) { why = "a bind names no bone of the skeleton"; return null; }
        var pos0 = Flat(arrays[(int)Godot.Mesh.ArrayType.Vertex].AsVector3Array());
        var nrm0 = Flat(arrays[(int)Godot.Mesh.ArrayType.Normal].AsVector3Array());
        var card = prim.Attributes[record.VertexCard];
        var u = prim.Attributes[record.VertexU];
        StrandSim sim;
        try
        {
            if (card.Any(c => c < 0 || c > ushort.MaxValue || c != Math.Floor(c))) throw new StrandMismatch($"{record.VertexCard} is no u16");
            var binding = StrandSim.Bind(record, pos0, nrm0, card.Select(c => (ushort)c).ToArray(), u.Select(x => (float)x).ToArray());
            sim = new StrandSim(binding, record);
        }
        catch (StrandMismatch e) { why = e.Message; return null; }

        // Colliders: the record's hair capsules without the head region, bound to the body skins' joints.
        var capsules = StrandSim.RecordCapsules(record).Where(c => c.Region != SkippedRegion).ToList();
        var collision = capsules.Count > 0
            ? CollisionBinding.Bind(new CollisionPayload(Collision.Version, capsules), BodyJoints(body, skel), Affine.Identity) : null;
        var binds = (collision?.Capsules ?? Array.Empty<BoundCapsule>())
            .Select(c => new StrandBind(new[] { c.Bind.A.X, c.Bind.A.Y, c.Bind.A.Z }, new[] { c.Bind.B.X, c.Bind.B.Y, c.Bind.B.Z })).ToList();
        var driver = new StrandHairDriver(record, sim, binds);
        var mod = new StrandHairModifier(mesh, surface, headBind, headBone, SecondaryMotionModifier.ToAffine(skin.GetBindPose(headBind)),
                                         followBones, followBinds.Select(i => SecondaryMotionModifier.ToAffine(skin.GetBindPose(i))).ToArray(),
                                         collision, driver, root, prim.Kept);
        skel.AddChild(mod);
        if (skel.GetChildren().OfType<FirstPersonBodyModifier>().FirstOrDefault() is { } fp) skel.MoveChild(fp, -1);
        return mod;
    }

    private static int SurfaceVertexCount(ArrayMesh m, int s) => m.SurfaceGetArrayLen(s);

    private static float[] Flat(Vector3[] v)
    {
        var f = new float[v.Length * 3];
        for (int i = 0; i < v.Length; i++) { f[3 * i] = v[i].X; f[3 * i + 1] = v[i].Y; f[3 * i + 2] = v[i].Z; }
        return f;
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren()) foreach (var d in Walk(c)) yield return d;
    }

    /// <summary>collision.ts <c>bodyJoints</c>: per normalised bone name the first BODY (non-garment) skin's bind.</summary>
    public static Dictionary<string, BodyJoint> BodyJoints(Node3D body, Skeleton3D skel)
    {
        var joints = new Dictionary<string, BodyJoint>();
        foreach (var mi in Walk(body).OfType<MeshInstance3D>())
        {
            if (mi.Skin is not { } skin || SecondaryMotionModifier.IsGarment(mi, body)) continue;
            for (int i = 0; i < skin.GetBindCount(); i++)
            {
                string name = skin.GetBindName(i);
                int bone = name.Length > 0 ? skel.FindBone(name) : skin.GetBindBone(i);
                if (bone < 0 || bone >= skel.GetBoneCount()) continue;
                joints.TryAdd(BoneNames.Norm(skel.GetBoneName(bone)), new BodyJoint(bone, SecondaryMotionModifier.ToAffine(skin.GetBindPose(i))));
            }
        }
        return joints;
    }

    // ---- the pose ---------------------------------------------------------------------------------------------------

    /// <summary>Column-major 4×4 (three's <c>elements</c>, the core's matrices).</summary>
    public static double[] Mat(Affine a) => new[] { a.Xx, a.Xy, a.Xz, 0, a.Yx, a.Yy, a.Yz, 0, a.Zx, a.Zy, a.Zz, 0, a.Ox, a.Oy, a.Oz, 1 };

    private Affine BoneWorld(Skeleton3D skel, int bone)
        => SecondaryMotionModifier.ToAffine((skel.IsInsideTree() ? skel.GlobalTransform : skel.Transform) * skel.GetBoneGlobalPose(bone));

    /// <summary>The pose of this frame: the follow and head bind→world matrices and the own capsules now (world).</summary>
    public StrandPose Pose()
    {
        var skel = GetSkeleton() ?? throw new InvalidOperationException("strand hair without a skeleton");
        var follow = new double[_followBones.Length][];
        for (int k = 0; k < follow.Length; k++) follow[k] = Mat(BoneWorld(skel, _followBones[k]).Times(_followBindPoses[k]));
        var caps = Array.Empty<(double[], double[], double)>();
        if (_collision is { } c)
        {
            c.Update(n => BoneWorld(skel, n), Affine.Identity, Affine.Identity);
            caps = c.Capsules.Select(e => (new[] { e.Now.A.X, e.Now.A.Y, e.Now.A.Z }, new[] { e.Now.B.X, e.Now.B.Y, e.Now.B.Z }, e.Now.R)).ToArray();
        }
        return new StrandPose { Follow = follow, Head = Mat(BoneWorld(skel, _headBone).Times(_headBindPose)), Capsules = caps };
    }

    private double[] RootMatrix()
        => Mat(SecondaryMotionModifier.ToAffine(_root.IsInsideTree() ? _root.GlobalTransform : _root.Transform));

    // ---- on / off ---------------------------------------------------------------------------------------------------

    /// <summary>On: the owned clone (cards Head-only), the sim reset to the current targets and uploaded. Off: the
    /// template's mesh back, the clone dropped.</summary>
    public void SetEnabled(bool on)
    {
        if (on == Enabled) return;
        if (on)
        {
            _clone = CloneWithHeadSkin();
            _mesh.Mesh = _clone;
            var fmt = _clone.SurfaceGetFormat(_surface);
            int n = _clone.SurfaceGetArrayLen(_surface);
            var rsFmt = (RenderingServer.ArrayFormat)(ulong)fmt;
            _layout = new StrandVertexLayout(n,
                (int)RenderingServer.MeshSurfaceGetFormatOffset(rsFmt, n, (int)Godot.Mesh.ArrayType.Vertex),
                (int)RenderingServer.MeshSurfaceGetFormatVertexStride(rsFmt, n),
                (int)RenderingServer.MeshSurfaceGetFormatOffset(rsFmt, n, (int)Godot.Mesh.ArrayType.Normal),
                (int)RenderingServer.MeshSurfaceGetFormatNormalTangentStride(rsFmt, n));
            _buffer = RenderingServer.MeshGetSurface(_clone.GetRid(), _surface)["vertex_data"].AsByteArray();
            Driver.Enable(Pose(), RootMatrix());
            Upload();
        }
        else
        {
            Driver.Disable();
            if (IsInstanceValid(_mesh)) _mesh.Mesh = _template;
            _clone = null;
            _buffer = null;
        }
    }

    /// <summary>The template's surfaces re-added uncompressed, the strand surface's card vertices on the Head bind alone.</summary>
    private ArrayMesh CloneWithHeadSkin()
    {
        var clone = new ArrayMesh { BlendShapeMode = _template.BlendShapeMode };
        for (int i = 0; i < _template.GetBlendShapeCount(); i++) clone.AddBlendShape(_template.GetBlendShapeName(i));
        var vk = Driver.Sim.Binding.Vk;
        for (int s = 0; s < _template.GetSurfaceCount(); s++)
        {
            var arrays = _template.SurfaceGetArrays(s);
            var fmt = _template.SurfaceGetFormat(s);
            if (s == _surface)
            {
                int per = (fmt & Godot.Mesh.ArrayFormat.FlagUse8BoneWeights) != 0 ? 8 : 4;
                var bones = arrays[(int)Godot.Mesh.ArrayType.Bones].AsInt32Array();
                var weights = arrays[(int)Godot.Mesh.ArrayType.Weights].AsFloat32Array();
                for (int v = 0; v < vk.Length; v++)
                {
                    if (vk[v] < 0) continue;
                    for (int k = 0; k < per; k++) { bones[v * per + k] = k == 0 ? _headBind : 0; weights[v * per + k] = k == 0 ? 1 : 0; }
                }
                arrays[(int)Godot.Mesh.ArrayType.Bones] = bones;
                arrays[(int)Godot.Mesh.ArrayType.Weights] = weights;
            }
            var blends = _template.SurfaceGetBlendShapeArrays(s);
            clone.AddSurfaceFromArrays(_template.SurfaceGetPrimitiveType(s), arrays, blends, new Godot.Collections.Dictionary(),
                                       fmt & ~Godot.Mesh.ArrayFormat.FlagCompressAttributes);
            clone.SurfaceSetMaterial(s, _template.SurfaceGetMaterial(s));
            clone.SurfaceSetName(s, _template.SurfaceGetName(s));
        }
        return clone;
    }

    // ---- the frame --------------------------------------------------------------------------------------------------

    public override void _ProcessModificationWithDelta(double delta)
    {
        if (!Manual) StepNow(delta);
    }

    /// <summary>One frame: the driver's clock (steps, carry, reset, rebuild); a frame that rebuilt is uploaded.</summary>
    public bool StepNow(double delta)
    {
        if (!Enabled || GetSkeleton() is null) return false;
        if (!Driver.Update(delta, Pose, RootMatrix(), Frozen)) return false;
        Upload();
        return true;
    }

    private void Upload()
    {
        if (_clone is null || _buffer is null) return;
        _clock.Restart();
        StrandUpload.Write(_buffer, _layout, Driver.Pos, Driver.Nrm);
        RenderingServer.MeshSurfaceUpdateVertexRegion(_clone.GetRid(), _surface, 0, _buffer);
        LastUploadMs = _clock.Elapsed.TotalMilliseconds;
        Uploads++;
    }

    /// <summary><c>dispose()</c>: off, and nothing of this handle left.</summary>
    public void Release()
    {
        SetEnabled(false);
        if (IsInstanceValid(this)) QueueFree();
    }
}
