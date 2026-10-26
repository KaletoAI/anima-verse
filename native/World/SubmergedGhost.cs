using System;
using System.Collections.Generic;
using System.Globalization;
using AnimaNative.Water;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// THE UNDERWATER GHOST (<c>client3d/src/scene/submergedGhost.ts</c>, finding H3): the second draw that gives anything
/// standing in water a body below the waterline. The water surface IS the opaque terrain (Wasser v2 K-A), so whatever
/// stands under a mirror loses the depth test there and is cut off clean; the ghost draws the object once more with the
/// depth test INVERTED — only where the normal pass lost — tinted with the water, at 0.4 opacity, writing no depth, and
/// discarding everything above the waterline (an object also loses the test against itself: an arm in front of the
/// torso must not paint a blue patch on the dry half).
///
/// Godot 4.7: <c>render_mode depth_test_inverted</c> compiles to <c>COMPARE_OP_LESS</c> on the reverse-Z buffer
/// (scene_shader_forward_clustered.cpp), i.e. "strictly farther than what is stored" — three's <c>GreaterDepth</c> on its
/// forward-Z buffer, exactly. It only acts on a transparent material, which the ghost is (it writes ALPHA), so it is
/// drawn in the transparent pass after every opaque object, the terrain included.
///
/// One twin <see cref="MeshInstance3D"/> per mesh under the root, hung as a CHILD of the mesh it doubles with no
/// transform of its own (the world matrix is the original's), sharing its mesh and — for a skinned figure — its skin and
/// skeleton (Godot skins in a compute pre-pass, so <c>VERTEX</c> in the ghost's vertex stage is already posed); one ghost
/// material per source surface (its own albedo texture × the water tint). Built lazily on the first submersion, hidden
/// (never destroyed) afterwards; a dry object builds nothing. The gate is the caller's (<see cref="WaterGates.GhostCutY"/>).
/// </summary>
public sealed class SubmergedGhost
{
    /// <summary>Meta on every ghost mesh: the passes that walk a placement (pick, cut, slots) leave it alone.</summary>
    public const string Meta = "water_ghost";

    /// <summary>The isolation switch (the browser's toggle 22, <c>--no-water</c>): no ghost anywhere.</summary>
    public static bool Off { get; set; }

    private static readonly Dictionary<BaseMaterial3D.CullModeEnum, Shader> Shaders = new();
    private static readonly List<string> CompileLines = new();

    private readonly Node3D _root;
    private readonly List<MeshInstance3D> _meshes = new();
    private readonly List<ShaderMaterial> _materials = new();
    private bool _built, _shown;
    private double? _level;

    public SubmergedGhost(Node3D root) { _root = root; }

    /// <summary>How many second draws stand (0 while the object has never been in water).</summary>
    public int Count => _meshes.Count;
    public bool Visible => _shown;
    /// <summary>The world y the ghosts cut themselves off at (diagnostic / check).</summary>
    public double CutY { get; private set; }
    public IReadOnlyList<MeshInstance3D> Parts => _meshes;
    public IReadOnlyList<ShaderMaterial> Materials => _materials;

    /// <summary><c>set(waterLevel)</c>: null = dry; a number = the world y of the water surface over the object's base.</summary>
    public void Set(double? waterLevel)
    {
        _level = waterLevel is { } l && double.IsFinite(l) ? l : null;
        Reapply();
    }

    /// <summary>Re-decide from the level asked for and the switch; a standing ghost follows a rising lake.</summary>
    public void Reapply()
    {
        bool want = _level is not null && !Off;
        if (want && CutY != _level!.Value)
        {
            CutY = _level.Value;
            foreach (var m in _materials) m.SetShaderParameter("ghost_cut_y", (float)CutY);
        }
        if (want == _shown) return;
        _shown = want;
        if (want && !_built) Build();
        foreach (var g in _meshes)
            if (GodotObject.IsInstanceValid(g)) g.Visible = want;
    }

    /// <summary>Unhook the ghost meshes (the materials are the ghost's own; the meshes belong to the original).</summary>
    public void Dispose()
    {
        foreach (var g in _meshes)
            if (GodotObject.IsInstanceValid(g)) { g.GetParent()?.RemoveChild(g); g.QueueFree(); }
        _meshes.Clear();
        _materials.Clear();
        _built = _shown = false;
    }

    private void Build()
    {
        _built = true;
        var sources = new List<MeshInstance3D>();
        Collect(_root, sources);
        foreach (var src in sources)
        {
            var ghost = new MeshInstance3D
            {
                Name = "WaterGhost",
                Mesh = src.Mesh,
                Skin = src.Skin,
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                GIMode = GeometryInstance3D.GIModeEnum.Disabled,
                Visible = false,
            };
            ghost.SetMeta(Meta, true);
            int surfaces = src.Mesh.GetSurfaceCount();
            for (int i = 0; i < surfaces; i++)
            {
                var mat = Material(src.GetActiveMaterial(i));
                ghost.SetSurfaceOverrideMaterial(i, mat);
                _materials.Add(mat);
            }
            src.AddChild(ghost);
            // The SAME skeleton: the ghost's path to it from its own place in the tree.
            if (src.Skin is not null && src.GetNodeOrNull(src.Skeleton) is Skeleton3D skel)
                ghost.Skeleton = ghost.GetPathTo(skel);
            _meshes.Add(ghost);
        }
    }

    private static void Collect(Node n, List<MeshInstance3D> into)
    {
        if (n is MeshInstance3D mi && mi.Mesh is not null && !mi.HasMeta(Meta) && !mi.HasMeta(PropWaterSheets.Meta)) into.Add(mi);
        foreach (var c in n.GetChildren())
            if (c is not MeshInstance3D g || !g.HasMeta(Meta)) Collect(c, into);
    }

    /// <summary>ONE ghost material from one source material: its albedo texture (none = white), the water tint, its side
    /// and its alpha scissor (a cutout leaf stays a cutout under water).</summary>
    private ShaderMaterial Material(Material? src)
    {
        Texture2D? map = null;
        var cull = BaseMaterial3D.CullModeEnum.Back;
        double alphaTest = 0;
        if (src is BaseMaterial3D b)
        {
            map = b.AlbedoTexture;
            cull = b.CullMode;
            if (b.Transparency == BaseMaterial3D.TransparencyEnum.AlphaScissor) alphaTest = b.AlphaScissorThreshold;
        }
        else if (src is ShaderMaterial sm && sm.GetShaderParameter("texture_albedo").Obj is Texture2D t) map = t;
        var mat = new ShaderMaterial { Shader = ShaderFor(cull) };
        var tint = WaterShade.TintRgb(null);
        // setRGB, not setHex: the very numbers the water shader writes into look0.rgb (working space, linear).
        mat.SetShaderParameter("ghost_tint", new Vector3((float)tint.R, (float)tint.G, (float)tint.B));
        mat.SetShaderParameter("ghost_has_map", map is null ? 0f : 1f);
        if (map is not null) mat.SetShaderParameter("ghost_map", map);
        mat.SetShaderParameter("ghost_alpha_test", (float)alphaTest);
        mat.SetShaderParameter("ghost_cut_y", (float)CutY);
        mat.RenderPriority = 2;
        return mat;
    }

    /// <summary>The ghost shader for one cull mode (three's side: front / double / back), compiled once each.</summary>
    public static Shader ShaderFor(BaseMaterial3D.CullModeEnum cull)
    {
        if (Shaders.TryGetValue(cull, out var s)) return s;
        s = new Shader { Code = Code(cull) };
        ShaderSafety.Ok(s, $"water-ghost[{cull.ToString().ToLowerInvariant()}]");
        return Shaders[cull] = s;
    }

    public static string Code(BaseMaterial3D.CullModeEnum cull)
    {
        string c = cull switch
        {
            BaseMaterial3D.CullModeEnum.Disabled => "cull_disabled",
            BaseMaterial3D.CullModeEnum.Front => "cull_front",
            _ => "cull_back",
        };
        string op = WaterGates.GhostOpacity.ToString("0.0", CultureInfo.InvariantCulture);
        return $@"shader_type spatial;
// submergedGhost.ts: MeshBasicMaterial(map, water tint, opacity {op}, GreaterDepth, no depth write) + the waterline cut.
render_mode unshaded, blend_mix, depth_draw_never, depth_test_inverted, {c}, shadows_disabled;

uniform sampler2D ghost_map : source_color, filter_linear_mipmap, repeat_enable;
uniform float ghost_has_map = 0.0;
uniform vec3 ghost_tint = vec3(0.24705882, 0.49803922, 0.72156863);
uniform float ghost_cut_y = 0.0;
uniform float ghost_alpha_test = 0.0;
varying float v_ghost_y;

void vertex() {{
	v_ghost_y = (MODEL_MATRIX * vec4(VERTEX, 1.0)).y;
}}

void fragment() {{
	if (v_ghost_y > ghost_cut_y) discard;
	vec4 m = ghost_has_map > 0.5 ? texture(ghost_map, UV) : vec4(1.0);
	float a = {op} * m.a;
	if (a < ghost_alpha_test) discard;
	ALBEDO = m.rgb * ghost_tint;
	ALPHA = a;
}}
";
    }
}
