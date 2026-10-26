using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The browser's distance fog (engine.ts <c>new THREE.Fog(sky, 220, 520)</c>, colour = the clock's sky) as the one screen
/// pass of <see cref="FogPost"/>: a 2 × 2 quad under the camera whose shader writes clip space directly, drawn after
/// every other transparent surface (material priority 127). Nothing else in the scene fogs itself — the Environment fog
/// stays off, and no material writes <c>FOG</c> — so every material class goes through this one path.
///
/// Task 26b: the same fog can run as a compute pass instead (<see cref="FogComputeEffect"/>, <see cref="UseCompute"/>):
/// this node then decides every frame which of the two fogs the overview camera — exactly one, or none while
/// <see cref="Off"/> (the bench variant <c>no-fog-pass</c>). The compute pass needs a GPU; without one (or before its
/// kernel compiled) the screen pass stays. Task 26c made the compute pass the default (<c>--fog=pass</c> is the
/// fallback): for every opaque pixel both land on the same display value (tests/BenchMatrixTests).
///
/// The quad sits on <see cref="PassLayer"/> alone. While the compute pass runs, the overview camera leaves that layer out
/// of its cull mask (so no screen or depth copy is made for it) but the quad stays visible: a mirror's camera (its own
/// SubViewport, the shared world, the default cull mask) still draws it, and the reflections stay fogged exactly as
/// before — the compositor effect rides on the overview camera only.
/// </summary>
public partial class DistanceFog : MeshInstance3D
{
    /// <summary>Render layer 18: the screen pass's quad (the overview camera drops it while the compute pass fogs).</summary>
    public const uint PassLayer = 1u << 17;

    private ShaderMaterial? _material;
    private bool _loggedFallback;

    /// <summary>The compute twin under the same camera (null in the checks that build a bare pass).</summary>
    public FogComputeEffect? Compute { get; private set; }

    /// <summary>The default (Task 26c; <c>--fog=pass</c> and the bench variant <c>fog-pass</c> turn it off): prefer the compute pass when it is available.</summary>
    public bool UseCompute { get; set; }

    /// <summary>The bench switch <c>no-fog-pass</c>: no fog at all (neither the screen pass nor the compute pass).</summary>
    public bool Off { get; set; }

    /// <summary>True while the compute pass fogs the frame (the overview camera does not draw the screen pass then).</summary>
    public bool ComputeActive => Compute is { Enabled: true };

    /// <summary>True while the screen pass fogs the overview camera's frame (visible and in that camera's cull mask).</summary>
    public bool PassInMainView => Visible && (GetParent() is not Camera3D cam || (cam.CullMask & PassLayer) != 0);

    /// <summary>The pass material (null when its shader failed to compile: no fog then, logged by <see cref="ShaderSafety"/>).</summary>
    public ShaderMaterial? PassMaterial => _material;

    /// <summary>The <c>fog_srgb</c> last written (three's fog colour in the output space).</summary>
    public (double R, double G, double B) FogSrgb { get; private set; } = FogPost.FogSrgb(StageLight.BootSky);

    /// <summary>
    /// Hangs the pass under <paramref name="camera"/> (it then always lies in that camera's frustum) with the boot sky; with
    /// <paramref name="compute"/> the compositor of the compute twin goes onto the camera too (disabled until chosen).
    /// </summary>
    public static DistanceFog Attach(Node3D camera, bool compute = false)
    {
        var fog = new DistanceFog
        {
            Name = "DistanceFog",
            Mesh = new QuadMesh { Size = new Vector2(2, 2) },
            CastShadow = ShadowCastingSetting.Off,
            GIMode = GIModeEnum.Disabled,
            // The vertex shader ignores the transform; the margin only keeps the culler from ever dropping the quad
            // (also for a mirror's camera, which shares the world).
            ExtraCullMargin = 16384,
            Layers = PassLayer,
        };
        var shader = new Shader { Code = FogPost.ShaderCode };
        if (ShaderSafety.Ok(shader, "fog-post"))
        {
            fog._material = new ShaderMaterial { Shader = shader, RenderPriority = FogPost.RenderPriority };
            fog.MaterialOverride = fog._material;
        }
        else fog.Visible = false;
        camera.AddChild(fog);
        if (compute && camera is Camera3D cam) fog.Compute = FogComputeEffect.Attach(cam);
        fog.SetSky(StageLight.BootSky);
        fog.Decide();
        return fog;
    }

    public override void _Process(double delta) => Decide();

    /// <summary>Which fog the overview camera gets this frame: none (<see cref="Off"/>), the compute pass (chosen and compiled), else the screen pass.</summary>
    public void Decide()
    {
        bool compute = !Off && UseCompute && Compute is { Available: true };
        if (UseCompute && !Off && !compute && !_loggedFallback && Compute is { Error.Length: > 0 })
        {
            _loggedFallback = true;
            GD.PrintErr("[native] fog: the compute pass is unavailable — the screen pass stays");
        }
        if (Compute is { } c)
        {
            if (compute && GetParent() is Camera3D cam) c.Set(FogSrgb, cam.Near, cam.Far);
            if (c.Enabled != compute) c.Enabled = compute;
        }
        // The quad stays up for the mirrors' cameras; the overview camera drops its layer while the compute pass runs.
        bool pass = !Off && _material is not null;
        if (Visible != pass) Visible = pass;
        if (GetParent() is Camera3D view)
        {
            uint mask = compute ? view.CullMask & ~PassLayer : view.CullMask | PassLayer;
            if (view.CullMask != mask) view.CullMask = mask;
        }
    }

    /// <summary><c>scene.fog.color.copy(sky)</c>: the fog follows the clock's sky (linear working space in, output space on the GPU).</summary>
    public void SetSky(LinearRgb sky)
    {
        FogSrgb = FogPost.FogSrgb(sky);
        _material?.SetShaderParameter("fog_srgb", new Vector3((float)FogSrgb.R, (float)FogSrgb.G, (float)FogSrgb.B));
    }
}
