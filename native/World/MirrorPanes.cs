using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scene;
using Godot;
using CoreVec3 = AnimaNative.Overview.Vec3;

namespace AnimaNative.World;

/// <summary>
/// The mirror panes (slot preset <c>mirror</c>, packages/scene-render/src/mirrorSurface.ts part 2) — native technique:
/// one SubViewport + Camera3D per pane in the main World3D. The camera stands at the viewer's mirror image and looks
/// straight through the pane with an off-axis frustum whose near plane IS the pane (<see cref="MirrorMath.ReflectionView"/>;
/// Godot 4.7's Camera3D has no custom/oblique projection, and this frustum clips everything behind the mirror the
/// same way). The pane material samples the viewport texture projectively (three's <c>texture2DProj</c>) and blends the
/// silver tint as Reflector.js does. Cost policy of the 3D client (sceneRecipe.ts <c>MIRROR_OPTS</c>): 512 px, at most
/// TWO passes per frame across all panes, taken in turns (<see cref="MirrorBudget"/>), no refresh beyond 12 m once a pane
/// has a reflection. Only the PANE is left out of its own pass (the shader discards when drawn by its own camera), so
/// the frame and the dresser stay in the reflection.
/// </summary>
public sealed partial class MirrorPanes : Node
{
    /// <summary>One pane: its surface, its plane and vertices in the mesh's space, and its render target.</summary>
    public sealed class Pane
    {
        public required MeshInstance3D Mesh { get; init; }
        public required int Surface { get; init; }
        public required string Slot { get; init; }
        public required MirrorPlane Plane { get; init; }
        public required Vector3[] LocalVertices { get; init; }
        public required SubViewport Viewport { get; init; }
        public required Camera3D Camera { get; init; }
        public required ShaderMaterial Material { get; init; }
        /// <summary>Has a pass been requested once? Until then the distance cap must not keep the target black.</summary>
        public bool Rendered { get; set; }
        public int Passes { get; set; }
        public MirrorMath.View? LastView { get; set; }
        public bool Detached { get; set; }
    }

    private const string ShaderCode = @"shader_type spatial;
render_mode unshaded, cull_disabled;
// Anima native mirror pane (mirrorSurface.ts MIRROR_FRAGMENT): the reflection, looked up projectively, overlaid with the tint.
uniform sampler2D reflection : source_color, filter_linear, repeat_disable;
uniform vec3 tint : source_color = vec3(0.46666667);
uniform vec4 tex_u = vec4(0.0);
uniform vec4 tex_v = vec4(0.0);
uniform vec4 tex_w = vec4(0.0, 0.0, 0.0, 1.0);
uniform vec3 mirror_eye = vec3(1e9);
varying vec3 mirror_world;
float mirror_overlay(float b, float t) { return b < 0.5 ? 2.0 * b * t : 1.0 - 2.0 * (1.0 - b) * (1.0 - t); }
void vertex() {
	mirror_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}
void fragment() {
	// Its own reflection pass does not draw the pane (only the pane: the frame stays in the picture).
	if (distance(CAMERA_POSITION_WORLD, mirror_eye) < 0.001) discard;
	vec4 p = vec4(mirror_world, 1.0);
	float w = dot(tex_w, p);
	vec2 uv = vec2(dot(tex_u, p), dot(tex_v, p)) / max(w, 1e-6);
	vec3 base = texture(reflection, uv).rgb;
	ALBEDO = vec3(mirror_overlay(base.r, tint.r), mirror_overlay(base.g, tint.g), mirror_overlay(base.b, tint.b));
}
";

    private static Shader? _shader;
    private readonly List<Pane> _panes = new();
    private double _frame;

    /// <summary>The shared mirror shader (compiled once, checked by <see cref="ShaderSafety"/>).</summary>
    public static Shader? MirrorShader()
    {
        _shader ??= new Shader { Code = ShaderCode };
        return ShaderSafety.Ok(_shader, "mirror") ? _shader : null;
    }

    public MirrorBudget Budget { get; } = new(MirrorMath.ClientMaxPerFrame);
    public double MaxDistanceM { get; init; } = MirrorMath.ClientMaxDistanceM;
    public int TextureSize { get; init; } = MirrorMath.ClientTextureSize;
    public IReadOnlyList<Pane> Panes => _panes;
    /// <summary>Passes granted in the last <see cref="Tick"/>.</summary>
    public int LastGrants { get; private set; }

    public MirrorPanes() => Name = "MirrorPanes";

    /// <summary>
    /// <c>attachMirror</c>: make surface <paramref name="surface"/> of <paramref name="mesh"/> a mirror. The plane is measured
    /// from THAT surface's faces (a glTF primitive = one material = three's material group); nothing measurable leaves the
    /// mesh as modelled and says so once, naming the slot and the reason. Returns null then.
    /// </summary>
    public Pane? Attach(MeshInstance3D mesh, int surface, string slot, Action<string> log)
    {
        if (mesh.Mesh is not { } m || surface >= m.GetSurfaceCount()) return null;
        var arrays = m.SurfaceGetArrays(surface);
        var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var indexVariant = arrays[(int)Mesh.ArrayType.Index];
        int[]? index = indexVariant.VariantType == Variant.Type.Nil ? null : indexVariant.AsInt32Array();
        if (index is { Length: 0 }) index = null;
        var positions = new double[verts.Length * 3];
        for (int i = 0; i < verts.Length; i++)
        {
            positions[i * 3] = verts[i].X;
            positions[i * 3 + 1] = verts[i].Y;
            positions[i * 3 + 2] = verts[i].Z;
        }
        int total = index?.Length ?? verts.Length;
        var (plane, why) = MirrorMath.MeasureFaces(positions, index, new[] { (0, total) });
        if (plane is not { } pl)
        {
            log($"mirror slot \"{slot}\": {why} — left as modelled");
            return null;
        }
        var shader = MirrorShader();
        if (shader is null) return null;
        // A re-applied placement hands the same surface over again: free the pane that is already there.
        foreach (var old in _panes.Where(p => p.Mesh == mesh && p.Surface == surface).ToList()) Detach(old);
        int size = Math.Max(16, TextureSize);
        var viewport = new SubViewport
        {
            Name = $"Mirror{_panes.Count}",
            Size = new Vector2I(size, size),
            RenderTargetUpdateMode = SubViewport.UpdateMode.Disabled,
            Msaa3D = Viewport.Msaa.Msaa4X,
        };
        var camera = new Camera3D
        {
            Name = "Reflection", Projection = Camera3D.ProjectionType.Frustum, KeepAspect = Camera3D.KeepAspectEnum.Height,
            Current = true,
        };
        viewport.AddChild(camera);
        AddChild(viewport);
        var material = new ShaderMaterial { Shader = shader, ResourceName = "MirrorSurface" };
        material.SetShaderParameter("reflection", viewport.GetTexture());
        material.SetShaderParameter("tint", new Color(MirrorMath.PresetTint >> 16 & 255, MirrorMath.PresetTint >> 8 & 255,
                                                      MirrorMath.PresetTint & 255) / 255f);
        mesh.SetSurfaceOverrideMaterial(surface, material);
        var pane = new Pane
        {
            Mesh = mesh, Surface = surface, Slot = slot, Plane = pl, LocalVertices = verts, Viewport = viewport,
            Camera = camera, Material = material,
        };
        _panes.Add(pane);
        return pane;
    }

    /// <summary><c>disposeMirror</c>: the pane leaves the rotation, its viewport goes.</summary>
    public void Detach(Pane pane)
    {
        if (pane.Detached) return;
        pane.Detached = true;
        Budget.Forget(pane);
        _panes.Remove(pane);
        if (IsInstanceValid(pane.Viewport)) pane.Viewport.QueueFree();
    }

    /// <summary>Every pane whose mesh is gone or lies under <paramref name="root"/> (a dropped location or swapped mesh).</summary>
    public int DetachUnder(Node? root)
    {
        var gone = _panes.Where(p => !IsInstanceValid(p.Mesh) || (root is not null && (p.Mesh == root || root.IsAncestorOf(p.Mesh)))).ToList();
        foreach (var p in gone) Detach(p);
        return gone.Count;
    }

    /// <summary>
    /// One frame of reflections (the render hooks of three, in a fixed order): every pane that is shown and in the
    /// camera's view asks the budget — after the distance cap, which a pane without a reflection ignores — and a granted
    /// pane gets its camera set and ONE render of its viewport. The frame counter rises by one per grant and once more at
    /// the end (the top-level render), exactly the numbers <see cref="MirrorBudget"/> was written for.
    /// </summary>
    public int Tick(Camera3D camera)
    {
        int grants = 0;
        var eye = camera.GlobalPosition;
        var planes = camera.GetFrustum();
        foreach (var pane in _panes.ToList())
        {
            if (!IsInstanceValid(pane.Mesh)) { Detach(pane); continue; }
            if (!pane.Mesh.IsVisibleInTree()) continue;
            var xf = pane.Mesh.GlobalTransform;
            if (!InFrustum(planes, xf * pane.Mesh.GetAabb())) continue;
            var p = xf * ToGodot(pane.Plane.Point);
            var n = (xf.Basis.Inverse().Transposed() * ToGodot(pane.Plane.Normal)).Normalized();
            double dist = p.DistanceTo(eye);
            if (!MirrorMath.MirrorRefreshes(pane.Rendered, dist, MaxDistanceM)) continue;
            if (!Budget.Allow(_frame, pane)) continue;
            _frame += 1;
            grants++;
            var view = MirrorMath.ReflectionView(ToCore(p), ToCore(n), pane.LocalVertices.Select(v => ToCore(xf * v)).ToList(), ToCore(eye));
            if (view is not { } v) continue;
            Aim(pane, v, camera.Far);
            pane.Viewport.RenderTargetUpdateMode = SubViewport.UpdateMode.Once;
            pane.Rendered = true;
            pane.Passes++;
        }
        _frame += 1;
        LastGrants = grants;
        return grants;
    }

    /// <summary>The reflection camera for a view, and the lookup rows on whatever material the surface draws now (a cut clone included).</summary>
    public static void Aim(Pane pane, MirrorMath.View v, float far)
    {
        pane.LastView = v;
        var cam = pane.Camera;
        cam.Transform = new Transform3D(new Basis(ToGodot(v.Right), ToGodot(v.Up), ToGodot(v.Back)), ToGodot(v.Eye));
        cam.SetFrustum((float)v.Size, new Vector2((float)v.OffsetX, (float)v.OffsetY), (float)v.Near, Math.Max(far, (float)v.Near + 1));
        var mat = pane.Mesh.GetSurfaceOverrideMaterial(pane.Surface) as ShaderMaterial ?? pane.Material;
        mat.SetShaderParameter("tex_u", Row(v.TexU));
        mat.SetShaderParameter("tex_v", Row(v.TexV));
        mat.SetShaderParameter("tex_w", Row(v.TexW));
        mat.SetShaderParameter("mirror_eye", ToGodot(v.Eye));
        mat.SetShaderParameter("reflection", pane.Viewport.GetTexture());
    }

    private static Vector4 Row(double[] r) => new((float)r[0], (float)r[1], (float)r[2], (float)r[3]);

    /// <summary>An AABB is out of view when all 8 corners lie over one frustum plane (Godot's planes face outwards).</summary>
    public static bool InFrustum(Godot.Collections.Array<Plane> planes, Aabb box)
    {
        foreach (var pl in planes)
        {
            bool allOver = true;
            for (int i = 0; i < 8 && allOver; i++)
                if (!pl.IsPointOver(box.GetEndpoint(i))) allOver = false;
            if (allOver) return false;
        }
        return true;
    }

    private static Vector3 ToGodot(CoreVec3 v) => new((float)v.X, (float)v.Y, (float)v.Z);
    private static CoreVec3 ToCore(Vector3 v) => new(v.X, v.Y, v.Z);
}
