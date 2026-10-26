using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The browser's distance fog (engine.ts <c>new THREE.Fog(sky, 220, 520)</c>, colour = the clock's sky) as the one screen
/// pass of <see cref="FogPost"/>: a 2 × 2 quad under the camera whose shader writes clip space directly, drawn after
/// every other transparent surface (material priority 127). Nothing else in the scene fogs itself — the Environment fog
/// stays off, and no material writes <c>FOG</c> — so every material class goes through this one path.
/// </summary>
public partial class DistanceFog : MeshInstance3D
{
    private ShaderMaterial? _material;

    /// <summary>The pass material (null when its shader failed to compile: no fog then, logged by <see cref="ShaderSafety"/>).</summary>
    public ShaderMaterial? PassMaterial => _material;

    /// <summary>The <c>fog_srgb</c> last written (three's fog colour in the output space).</summary>
    public (double R, double G, double B) FogSrgb { get; private set; } = FogPost.FogSrgb(StageLight.BootSky);

    /// <summary>Hangs the pass under <paramref name="camera"/> (it then always lies in that camera's frustum) with the boot sky.</summary>
    public static DistanceFog Attach(Node3D camera)
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
        };
        var shader = new Shader { Code = FogPost.ShaderCode };
        if (ShaderSafety.Ok(shader, "fog-post"))
        {
            fog._material = new ShaderMaterial { Shader = shader, RenderPriority = FogPost.RenderPriority };
            fog.MaterialOverride = fog._material;
        }
        else fog.Visible = false;
        camera.AddChild(fog);
        fog.SetSky(StageLight.BootSky);
        return fog;
    }

    /// <summary><c>scene.fog.color.copy(sky)</c>: the fog follows the clock's sky (linear working space in, output space on the GPU).</summary>
    public void SetSky(LinearRgb sky)
    {
        FogSrgb = FogPost.FogSrgb(sky);
        _material?.SetShaderParameter("fog_srgb", new Vector3((float)FogSrgb.R, (float)FogSrgb.G, (float)FogSrgb.B));
    }
}
