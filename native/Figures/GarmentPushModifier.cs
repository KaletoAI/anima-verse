using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The GPU garment push of ONE figure (packages/scene-render/src/garmentCollision.ts <c>createGarmentCollision</c>, own
/// capsules only): every skinned garment mesh under the body whose kind collides (<see cref="GarmentPush.Capsules"/>)
/// has its vertices pushed out of the body's collision capsules after skinning, in its vertex shader. OFF unless the
/// client was started with <c>--garment-push</c> (<see cref="Enabled"/>); off, nothing is created and nothing on the
/// figure changes.
///
/// THE MATERIAL. Per garment surface a <see cref="ShaderMaterial"/> that draws the surface's own material — a
/// StandardMaterial3D through Godot 4.7.2's generator (<see cref="StandardShaderCode"/>, fed by
/// <see cref="CutMaterials.FeedStandard"/>: the same port and the same values the room cut uses), a ShaderMaterial (the
/// skinned-normal twin of <see cref="SkinNormalMaterial"/>) through its own code and parameters — with the push
/// INSERTED (<see cref="GarmentPush.Inject"/>: declarations and the function before <c>vertex()</c>, the call as its last
/// statement, nothing of the original changed). Godot's StandardMaterial3D code is not readable at runtime (no
/// <c>shader_get_code</c> for a material's internal shader; on the headless renderer it is empty), hence the port. The
/// material is per figure and mesh (the capsule uniforms are), set as a surface OVERRIDE; the template's materials are
/// never touched. Godot renders shadows with the same material's <c>vertex()</c>, so the shadow is cast by the pushed
/// garment without a material of its own (three needs <c>customDepthMaterial</c> for that).
///
/// THE BIND POSITION. Godot skins in a compute pre-pass: <c>vertex()</c> sees the skinned VERTEX only. The bind rule
/// needs the unskinned position, so every pushed mesh is a per-TEMPLATE copy (<see cref="PushMeshOf"/>) whose garment
/// surfaces carry CUSTOM0 = RGBA float (bind position xyz, the GLB's <c>_COLLIDE</c> weight in w, 1 without one — read
/// from the GLB bytes like the strand attributes, matched to Godot's vertex order by position, <see cref="StrandGlb"/>).
/// Figures of one template share that copy as they share the template's mesh.
///
/// THE SPACE. VERTEX at the end of <c>vertex()</c> is the skinned position Σ wᵢ · (bone global pose · bind pose)ᵢ ·
/// position: Godot's skin matrices map the geometry (= bind) space into the SKELETON's frame, and the instance is then
/// drawn with MODEL_MATRIX = the MeshInstance3D's global transform — so world = meshGlobal · VERTEX, and a world point
/// enters VERTEX's space through meshGlobal⁻¹ (three's <c>capsuleInFrame(c.now, inverse(matrixWorld))</c>, radius ×
/// linearScale). The world capsules are <see cref="CollisionBinding.Update"/> with boneWorld = skeletonGlobal · bone
/// global pose and the identity mesh frame — exactly what the CPU twins use (<see cref="StrandHairModifier.Pose"/>, the
/// hair chains); for a mesh that hangs at the skeleton's frame (every glTF import: the MeshInstance3D a child of the
/// Skeleton3D with no transform) meshGlobal⁻¹ · skeletonGlobal is the identity and the uniforms ARE the skeleton-space
/// capsules. The bind ends (<c>collideBindA/B</c>) are the binding's bind capsules in the geometry space, unchanged (the
/// geometry space IS the bind space on Godot, as for the hair chains).
///
/// WHEN. A <see cref="SkeletonModifier3D"/> after the secondary motion (and the strand hair) and before the first-person
/// head: it reads the bones exactly as this frame's skin upload will (three: the render hooks after the skeleton
/// update). The secondary motion's EXACT non-TRS skin matrices of driven extension bones (chest, chains) are not seen
/// here — their capsules follow the nearest TRS the bones carry.
///
/// EXCLUSION. <see cref="Exclude"/> puts a mesh's materials back while the per-strand hair runs on it
/// (figureRuntime.ts <c>setStrandHair</c> → <c>excludeMesh</c>).
/// </summary>
public partial class GarmentPushModifier : SkeletonModifier3D
{
    /// <summary><c>--garment-push</c>: the GPU garment push on (default off; the owner judges the picture).</summary>
    public static bool Enabled { get; set; }

    /// <summary>The glTF attribute of the push weight (three <c>_collide</c>).</summary>
    public const string WeightAttribute = "_COLLIDE";

    private static readonly Dictionary<string, Shader> Shaders = new();
    /// <summary>Every push material → what it wraps and the override it replaced (the unwrap of a re-wrap).</summary>
    private static readonly ConditionalWeakTable<ShaderMaterial, Wrapped> Registry = new();
    /// <summary>Per template mesh its copy with CUSTOM0 (shared by every figure of the template).</summary>
    private static readonly ConditionalWeakTable<Mesh, ArrayMesh> Copies = new();
    private static readonly HashSet<string> Logged = new();

    private sealed record Wrapped(Material Source, Material? Previous);

    internal sealed class SurfaceState
    {
        public required int Index { get; init; }
        public required Material? Previous { get; set; }
        public required Material Source { get; set; }
        public required ShaderMaterial Material { get; set; }
    }

    /// <summary>One pushed mesh (garmentCollision.ts <c>GarmentCollisionEntry</c>).</summary>
    public sealed class Entry
    {
        public required MeshInstance3D Mesh { get; init; }
        public required string Kind { get; init; }
        public required IReadOnlyList<BoundCapsule> Capsules { get; init; }
        public required Mesh Original { get; init; }
        public required ArrayMesh PushMesh { get; init; }
        public bool Squeeze => Kind == "hair";
        public bool Excluded { get; internal set; }
        /// <summary>The capsules in the mesh's space as of the last update — what the uniforms hold.</summary>
        public CapsuleNow[] Local { get; internal set; } = Array.Empty<CapsuleNow>();
        internal Vector4[] BindA = Array.Empty<Vector4>(), BindB = Array.Empty<Vector4>();
        internal readonly List<SurfaceState> Surfaces = new();
        public IEnumerable<ShaderMaterial> Materials => Surfaces.Select(s => s.Material);
        public IEnumerable<int> SurfaceIndices => Surfaces.Select(s => s.Index);
    }

    private readonly Node3D _body;
    private readonly CollisionBinding _binding;
    private readonly List<Entry> _entries = new();

    public IReadOnlyList<Entry> Entries => _entries;
    public CollisionBinding Binding => _binding;
    /// <summary>Why a garment mesh or surface was left as it was (unsupported material, mesh, …).</summary>
    public List<string> Skipped { get; } = new();
    /// <summary>Uniform writes so far (one per mesh and frame).</summary>
    public int Updates { get; private set; }
    /// <summary>The check drives the frames itself (<see cref="UpdateNow"/>).</summary>
    public bool Manual { get; set; }

    private GarmentPushModifier(Node3D body, CollisionBinding binding)
    {
        Name = "GarmentPush";
        _body = body;
        _binding = binding;
    }

    // ---- build ------------------------------------------------------------------------------------------------------

    /// <summary>
    /// <c>createGarmentCollision(three, root, payload)</c>: null (nothing touched) while <see cref="Enabled"/> is off,
    /// without a payload / bound capsule, or when no garment mesh can be pushed. <paramref name="weights"/>: the GLB's
    /// primitives that carry <see cref="WeightAttribute"/> (<c>StrandGlb.Read(plain, "_COLLIDE")</c>), empty = weight 1.
    /// </summary>
    public static GarmentPushModifier? TryCreate(Node3D body, Skeleton3D skel, CollisionPayload? payload,
                                                 IReadOnlyList<StrandGlbPrimitive>? weights = null)
    {
        if (!Enabled) return null;
        var garments = Walk(body).OfType<MeshInstance3D>()
            .Where(mi => mi.Skin is not null && mi.Mesh is not null && !mi.HasMeta(SubmergedGhost.Meta)
                         && SecondaryMotionModifier.IsGarment(mi, body) && GarmentPush.Collides(KindOf(mi, body)))
            .ToList();
        if (garments.Count == 0 || payload is null) return null;
        var binding = CollisionBinding.Bind(payload, StrandHairModifier.BodyJoints(body, skel), Affine.Identity);
        if (binding is null || binding.Capsules.Count == 0) return null;
        var mod = new GarmentPushModifier(body, binding);
        foreach (var mi in garments) mod.Install(mi, weights ?? Array.Empty<StrandGlbPrimitive>());
        if (mod._entries.Count == 0)
        {
            foreach (var s in mod.Skipped) LogOnce("garment push: " + s);
            mod.Free();
            return null;
        }
        skel.AddChild(mod);
        mod.KeepOrder();
        foreach (var s in mod.Skipped) LogOnce("garment push: " + s);
        mod.UpdateNow();
        return mod;
    }

    /// <summary>Right after the secondary motion and the strand hair, before the first-person head (call after either is added).</summary>
    public void KeepOrder()
    {
        if (GetParent() is not Skeleton3D skel) return;
        var fp = skel.GetChildren().OfType<FirstPersonBodyModifier>().FirstOrDefault();
        skel.MoveChild(this, -1);
        if (fp is not null) skel.MoveChild(fp, -1);
    }

    /// <summary><c>garmentKind</c>: the first garment ancestor's <c>extras.garment.kind</c>, else its <c>garment_&lt;kind&gt;_</c> name, else "".</summary>
    public static string KindOf(Node node, Node root)
    {
        for (var n = node; n is not null && n != root; n = n.GetParent())
        {
            bool named = n.Name.ToString().StartsWith("garment_", StringComparison.Ordinal);
            Godot.Collections.Dictionary? garment = null;
            if (n.HasMeta("extras") && n.GetMeta("extras").VariantType == Variant.Type.Dictionary
                && n.GetMeta("extras").AsGodotDictionary().TryGetValue("garment", out var g) && g.VariantType == Variant.Type.Dictionary)
                garment = g.AsGodotDictionary();
            if (!named && garment is null) continue;
            if (garment is not null && garment.TryGetValue("kind", out var k) && k.VariantType == Variant.Type.String && k.AsString().Length > 0)
                return k.AsString();
            return GarmentPush.KindFromName(n.Name.ToString());
        }
        return "";
    }

    private void Install(MeshInstance3D mi, IReadOnlyList<StrandGlbPrimitive> weights)
    {
        string kind = KindOf(mi, _body);
        var capsules = GarmentPush.Capsules(kind, _binding.Capsules, c => c.Capsule.Region);
        if (capsules.Count == 0) return;
        if (mi.MaterialOverride is not null) { Skipped.Add($"{mi.Name}: a material_override hides surface materials"); return; }
        if (mi.Mesh is not ArrayMesh original) { Skipped.Add($"{mi.Name}: not an ArrayMesh"); return; }
        var copy = PushMeshOf(original, weights, out var why);
        if (copy is null) { Skipped.Add($"{mi.Name}: {why}"); return; }
        bool squeeze = kind == "hair";
        var entry = new Entry { Mesh = mi, Kind = kind, Capsules = capsules, Original = original, PushMesh = copy };
        for (int s = 0; s < original.GetSurfaceCount(); s++)
        {
            var previous = mi.GetSurfaceOverrideMaterial(s);
            var (source, prev) = Unwrapped(previous, original, s);
            var mat = Wrap(source, prev, squeeze, out var reason);
            if (mat is null) { Skipped.Add($"{mi.Name}/{s}: {reason}"); continue; }
            entry.Surfaces.Add(new SurfaceState { Index = s, Previous = prev, Source = source, Material = mat });
        }
        if (entry.Surfaces.Count == 0) return;
        entry.BindA = capsules.Select(c => new Vector4((float)c.Bind.A.X, (float)c.Bind.A.Y, (float)c.Bind.A.Z, 0)).ToArray();
        entry.BindB = capsules.Select(c => new Vector4((float)c.Bind.B.X, (float)c.Bind.B.Y, (float)c.Bind.B.Z, 0)).ToArray();
        mi.Mesh = copy;
        foreach (var st in entry.Surfaces)
        {
            mi.SetSurfaceOverrideMaterial(st.Index, st.Material);
            WriteBind(entry, st.Material);
        }
        _entries.Add(entry);
    }

    /// <summary>What a surface's current override wraps: a push material → its source and the override it replaced.</summary>
    private static (Material Source, Material? Previous) Unwrapped(Material? current, Mesh mesh, int surface)
    {
        if (current is ShaderMaterial sm && Registry.TryGetValue(sm, out var w)) return (w.Source, w.Previous);
        var source = current ?? mesh.SurfaceGetMaterial(surface)
                     ?? new StandardMaterial3D { DiffuseMode = BaseMaterial3D.DiffuseModeEnum.Lambert, DisableReceiveShadows = true };
        return (source, current);
    }

    /// <summary>The material a push material wraps (for the secondary motion's normal twin); anything else as it is.</summary>
    public static Material? Unwrap(Material? m) => m is ShaderMaterial sm && Registry.TryGetValue(sm, out var w) ? w.Source : m;

    /// <summary>
    /// The push twin of <paramref name="source"/>: its own shader code (generator port / own code) with the push
    /// inserted, its own parameter values; null (with the reason) when its look cannot be carried exactly.
    /// </summary>
    public static ShaderMaterial? Wrap(Material source, Material? previous, bool squeeze, out string reason)
    {
        reason = "";
        string baseCode, kind;
        StandardShaderSpec? spec = null;
        switch (source)
        {
            case StandardMaterial3D std:
                spec = CutMaterials.SpecOf(std);
                var generated = StandardShaderCode.Generate(spec);
                if (generated is null) { reason = "material keeps its look unpushed (" + string.Join(", ", spec.Unsupported) + ")"; return null; }
                baseCode = generated;
                kind = "std" + (spec.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor ? "+scissor" : "")
                       + (spec.AlbedoFromVertexColor ? "+vc" : "") + (spec.NormalMap ? "+n" : "");
                break;
            case ShaderMaterial sm when sm.Shader is { } sh && sh.GetMode() == Shader.Mode.Spatial:
                baseCode = sh.Code;
                kind = "shader" + sh.GetShaderUniformList().Count;
                break;
            default:
                reason = $"a {source.GetClass()} has no spatial shader to extend";
                return null;
        }
        string code;
        try { code = GarmentPush.Inject(baseCode, squeeze); }
        catch (ArgumentException e) { reason = e.Message; return null; }
        if (!Shaders.TryGetValue(code, out var shader)) Shaders[code] = shader = new Shader { Code = code };
        if (!ShaderSafety.Ok(shader, $"garment-push[{kind}{(squeeze ? "+squeeze" : "")}]")) { reason = "the pushed shader did not compile"; return null; }
        var mat = new ShaderMaterial { Shader = shader, RenderPriority = source.RenderPriority, NextPass = source.NextPass };
        if (source is StandardMaterial3D s3 && spec is not null) CutMaterials.FeedStandard(mat, s3, spec);
        else if (source is ShaderMaterial src)
            foreach (var p in src.Shader.GetShaderUniformList())
            {
                var name = p.AsGodotDictionary()["name"].AsString();
                mat.SetShaderParameter(name, src.GetShaderParameter(name));
            }
        Registry.AddOrUpdate(mat, new Wrapped(source, previous));
        return mat;
    }

    /// <summary>
    /// The template mesh with CUSTOM0 (RGBA float: the vertex's position, its <c>_COLLIDE</c> weight) on every surface
    /// (once per template mesh). Null with the reason when the copy could not be EXACT: a surface already uses CUSTOM0,
    /// a shadow mesh or LODs the copy would lose.
    /// </summary>
    public static ArrayMesh? PushMeshOf(ArrayMesh original, IReadOnlyList<StrandGlbPrimitive> weights, out string why)
    {
        why = "";
        if (Copies.TryGetValue(original, out var cached)) return cached;
        if (original.ShadowMesh is not null) { why = "a shadow mesh (the copy would draw shadows without CUSTOM0)"; return null; }
        var copy = new ArrayMesh { BlendShapeMode = original.BlendShapeMode, CustomAabb = original.CustomAabb, ResourceName = original.ResourceName };
        for (int i = 0; i < original.GetBlendShapeCount(); i++) copy.AddBlendShape(original.GetBlendShapeName(i));
        for (int s = 0; s < original.GetSurfaceCount(); s++)
        {
            var fmt = original.SurfaceGetFormat(s);
            if ((fmt & Mesh.ArrayFormat.FormatCustom0) != 0) { why = $"surface {s} already carries CUSTOM0"; return null; }
            var lods = RenderingServer.MeshGetSurface(original.GetRid(), s);
            if (lods.TryGetValue("lods", out var l) && l.VariantType == Variant.Type.Array && l.AsGodotArray().Count > 0)
            { why = $"surface {s} has LODs (the copy would lose them)"; return null; }
            var arrays = original.SurfaceGetArrays(s);
            var pos = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
            var w = WeightsFor(pos, weights);
            var custom = new float[pos.Length * 4];
            for (int v = 0; v < pos.Length; v++)
            {
                custom[4 * v] = pos[v].X; custom[4 * v + 1] = pos[v].Y; custom[4 * v + 2] = pos[v].Z;
                custom[4 * v + 3] = w is null ? 1f : (float)w[v];
            }
            arrays[(int)Mesh.ArrayType.Custom0] = custom;
            var flags = (fmt & ~Mesh.ArrayFormat.FlagCompressAttributes) | Mesh.ArrayFormat.FormatCustom0
                        | (Mesh.ArrayFormat)((long)Mesh.ArrayCustomFormat.RgbaFloat << (int)Mesh.ArrayFormat.FormatCustom0Shift);
            copy.AddSurfaceFromArrays(original.SurfaceGetPrimitiveType(s), arrays, original.SurfaceGetBlendShapeArrays(s),
                                      new Godot.Collections.Dictionary(), flags);
            copy.SurfaceSetMaterial(s, original.SurfaceGetMaterial(s));
            copy.SurfaceSetName(s, original.SurfaceGetName(s));
        }
        Copies.AddOrUpdate(original, copy);
        return copy;
    }

    /// <summary>The <c>_COLLIDE</c> values of the GLB primitive whose kept positions are this surface's, bit for bit; null = none.</summary>
    private static double[]? WeightsFor(Vector3[] pos, IReadOnlyList<StrandGlbPrimitive> weights)
    {
        var candidates = weights.Where(p => p.Has(WeightAttribute) && p.Kept.Length == pos.Length).ToList();
        if (candidates.Count == 0) return null;
        var flat = new float[pos.Length * 3];
        for (int i = 0; i < pos.Length; i++) { flat[3 * i] = pos[i].X; flat[3 * i + 1] = pos[i].Y; flat[3 * i + 2] = pos[i].Z; }
        return candidates.FirstOrDefault(p => StrandGlb.Matches(p, flat))?.Attributes[WeightAttribute];
    }

    // ---- the frame --------------------------------------------------------------------------------------------------

    public override void _ProcessModificationWithDelta(double delta)
    {
        if (!Manual) UpdateNow();
    }

    /// <summary>
    /// One frame (garmentCollision.ts <c>frameUpdate</c>): the capsules from the bones as posed now, each into its mesh's
    /// space, written to the mesh's materials; a surface whose override someone else replaced is wrapped again.
    /// </summary>
    public void UpdateNow()
    {
        var skel = GetParent() as Skeleton3D;
        if (skel is null || !IsInstanceValid(skel)) return;
        var skelWorld = SecondaryMotionModifier.ToAffine(skel.IsInsideTree() ? skel.GlobalTransform : skel.Transform);
        _binding.Update(n => skelWorld.Times(SecondaryMotionModifier.ToAffine(skel.GetBoneGlobalPose(n))), Affine.Identity, Affine.Identity);
        foreach (var e in _entries)
        {
            if (e.Excluded || !IsInstanceValid(e.Mesh)) continue;
            Resync(e);
            var inv = MeshWorld(e.Mesh).Inverted();
            e.Local = e.Capsules.Select(c => InFrame(c.Now, inv)).ToArray();
            var a = new Vector4[Collision.CollideMax];
            var b = new Vector4[Collision.CollideMax];
            for (int i = 0; i < e.Local.Length; i++)
            {
                var c = e.Local[i];
                a[i] = new Vector4((float)c.A.X, (float)c.A.Y, (float)c.A.Z, (float)c.R);
                b[i] = new Vector4((float)c.B.X, (float)c.B.Y, (float)c.B.Z, 0);
            }
            foreach (var st in e.Surfaces)
            {
                st.Material.SetShaderParameter("collideA", a);
                st.Material.SetShaderParameter("collideB", b);
                st.Material.SetShaderParameter("collideCount", e.Local.Length);
                // The skinned-normal twin's per-frame skin (the secondary motion wrote it on its own material this pass).
                if (st.Source is ShaderMaterial sm && sm.Shader is { } sh && sh.Code.Contains(SkinNormalMaterial.SkinParam, StringComparison.Ordinal))
                    st.Material.SetShaderParameter(SkinNormalMaterial.SkinParam, sm.GetShaderParameter(SkinNormalMaterial.SkinParam));
            }
            Updates++;
        }
    }

    /// <summary>A mesh's world frame as Godot draws it (MODEL_MATRIX).</summary>
    public static Affine MeshWorld(MeshInstance3D mi) => SecondaryMotionModifier.ToAffine(mi.IsInsideTree() ? mi.GlobalTransform : mi.Transform);

    /// <summary>garmentCollision.ts <c>capsuleInFrame</c>: ends through m, radius × m's linear scale.</summary>
    public static CapsuleNow InFrame(CapsuleNow c, Affine m) => new(m.Apply(c.A), m.Apply(c.B), c.R * Collision.LinearScale(m));

    private static void WriteBind(Entry e, ShaderMaterial m)
    {
        var a = Enumerable.Range(0, Collision.CollideMax).Select(i => i < e.BindA.Length ? e.BindA[i] : new Vector4(0, 0, 0, -1)).ToArray();
        var b = Enumerable.Range(0, Collision.CollideMax).Select(i => i < e.BindB.Length ? e.BindB[i] : Vector4.Zero).ToArray();
        m.SetShaderParameter("collideBindA", a);
        m.SetShaderParameter("collideBindB", b);
        m.SetShaderParameter("collideCount", 0);
    }

    /// <summary>Someone replaced a surface's override (the secondary motion installing or removing its normal twin): wrap what is there now.</summary>
    private void Resync(Entry e)
    {
        if (e.Mesh.Mesh != e.PushMesh) return;   // the strand hair's clone, or a foreign mesh: leave it
        foreach (var st in e.Surfaces)
        {
            var current = e.Mesh.GetSurfaceOverrideMaterial(st.Index);
            if (current == st.Material) continue;
            var (source, previous) = Unwrapped(current, e.Original, st.Index);
            if (source != st.Source || st.Material is null)
            {
                var mat = Wrap(source, previous, e.Squeeze, out var reason);
                if (mat is null) { LogOnce($"garment push: {e.Mesh.Name}/{st.Index}: {reason}"); continue; }
                WriteBind(e, mat);
                st.Material = mat;
                st.Source = source;
            }
            st.Previous = previous;
            e.Mesh.SetSurfaceOverrideMaterial(st.Index, st.Material);
        }
    }

    /// <summary>
    /// <c>excludeMesh(mesh, on)</c>: on = the mesh's surfaces wear what they wore before the push (the per-strand hair runs
    /// on it); off = the push materials again, the uniforms written on the next frame. A mesh not pushed is ignored.
    /// </summary>
    public void Exclude(MeshInstance3D mesh, bool on)
    {
        var e = _entries.FirstOrDefault(x => x.Mesh == mesh);
        if (e is null || e.Excluded == on) return;
        e.Excluded = on;
        foreach (var st in e.Surfaces) mesh.SetSurfaceOverrideMaterial(st.Index, on ? st.Previous : st.Material);
    }

    /// <summary><c>dispose()</c>: the original meshes and overrides back, the modifier gone.</summary>
    public void Release()
    {
        foreach (var e in _entries)
        {
            if (!IsInstanceValid(e.Mesh)) continue;
            if (e.Mesh.Mesh == e.PushMesh) e.Mesh.Mesh = e.Original;
            foreach (var st in e.Surfaces) e.Mesh.SetSurfaceOverrideMaterial(st.Index, st.Previous);
        }
        _entries.Clear();
        if (IsInstanceValid(this)) QueueFree();
    }

    private static void LogOnce(string line)
    {
        if (Logged.Add(line)) GD.Print("[native] " + line);
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren()) foreach (var d in Walk(c)) yield return d;
    }
}
