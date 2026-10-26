using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The distance fog as a compute pass (<see cref="FogCompute"/>, Task 26b): a <see cref="CompositorEffect"/> on the overview
/// camera at <c>POST_TRANSPARENT</c> that fogs the resolved colour buffer in place from the depth texture. The default since
/// Task 26c (<c>--fog=pass</c> or the bench variant <c>fog-pass</c> switch it off; the overview camera does not draw the
/// screen pass of <see cref="DistanceFog"/> while it runs, so exactly one of the two fogs a frame).
///
/// Threading: the kernel is compiled and freed on the render thread (<c>RenderingServer.CallOnRenderThread</c>), the
/// callback runs there; the main thread only writes the sky colour and the lens into one immutable record. Without a
/// <see cref="RenderingDevice"/> (the headless dummy renderer of <c>--check</c> / <c>--offline</c>) nothing is created and
/// <see cref="Available"/> stays false. Mirror cameras do not carry the effect: they keep drawing the screen pass (its quad
/// stays visible on <see cref="DistanceFog.PassLayer"/>, only the overview camera leaves that layer out).
/// </summary>
public partial class FogComputeEffect : CompositorEffect
{
    private sealed record Params(double Near, double Far, (double R, double G, double B) FogSrgb);

    private RenderingDevice? _rd;
    private Rid _shader, _pipeline, _sampler;
    private volatile Params _params = new(FogPost.CameraNear, FogPost.CameraFar, FogPost.FogSrgb(StageLight.BootSky));
    private volatile bool _ready;

    /// <summary>The kernel compiled (on a GPU). False on the dummy renderer or after a compile error (logged once).</summary>
    public bool Available => _ready;
    /// <summary>The compile error, if the kernel did not compile ("" otherwise).</summary>
    public string Error { get; private set; } = "";
    /// <summary>Frames the kernel was dispatched in (render thread; diagnostics).</summary>
    public int Dispatches { get; private set; }

    public FogComputeEffect()
    {
        EffectCallbackType = EffectCallbackTypeEnum.PostTransparent;
        AccessResolvedColor = true;
        AccessResolvedDepth = true;
        Enabled = false;
        if (RenderingServer.GetRenderingDevice() is null) return;
        RenderingServer.CallOnRenderThread(Callable.From(Init));
    }

    /// <summary>Hangs a compositor with this effect on <paramref name="camera"/> (the overview camera only).</summary>
    public static FogComputeEffect Attach(Camera3D camera)
    {
        var effect = new FogComputeEffect();
        camera.Compositor = new Compositor { CompositorEffects = new Godot.Collections.Array<CompositorEffect> { effect } };
        return effect;
    }

    /// <summary>The fog colour in the output space (<see cref="FogPost.FogSrgb"/>) and the camera lens.</summary>
    public void Set((double R, double G, double B) fogSrgb, double near, double far)
    {
        var p = _params;
        if (p.FogSrgb == fogSrgb && p.Near == near && p.Far == far) return;
        _params = new Params(near, far, fogSrgb);
    }

    private void Init()
    {
        _rd = RenderingServer.GetRenderingDevice();
        if (_rd is null) return;
        var src = new RDShaderSource { Language = RenderingDevice.ShaderLanguage.Glsl, SourceCompute = FogCompute.ShaderCode };
        var spirv = _rd.ShaderCompileSpirVFromSource(src);
        if (!string.IsNullOrEmpty(spirv.CompileErrorCompute))
        {
            Error = spirv.CompileErrorCompute;
            GD.PrintErr("[native] fog compute: kernel FAILED to compile — the screen pass stays: " + Error);
            return;
        }
        _shader = _rd.ShaderCreateFromSpirV(spirv, "AnimaFogCompute");
        if (!_shader.IsValid) { Error = "shader create failed"; return; }
        _pipeline = _rd.ComputePipelineCreate(_shader);
        _sampler = _rd.SamplerCreate(new RDSamplerState
        {
            MinFilter = RenderingDevice.SamplerFilter.Nearest,
            MagFilter = RenderingDevice.SamplerFilter.Nearest,
            RepeatU = RenderingDevice.SamplerRepeatMode.ClampToEdge,
            RepeatV = RenderingDevice.SamplerRepeatMode.ClampToEdge,
        });
        _ready = _pipeline.IsValid && _sampler.IsValid;
        GD.Print($"[native] fog compute: kernel {(_ready ? "compiled" : "NOT ready")}");
    }

    public override void _RenderCallback(int effectCallbackType, RenderData renderData)
    {
        if (!_ready || _rd is null || effectCallbackType != (int)EffectCallbackTypeEnum.PostTransparent) return;
        if (renderData.GetRenderSceneBuffers() is not RenderSceneBuffersRD buffers) return;
        var size = buffers.GetInternalSize();
        if (size.X <= 0 || size.Y <= 0) return;
        var p = _params;
        var push = FogCompute.Push(size.X, size.Y, p.Near, p.Far, p.FogSrgb);
        var (gx, gy) = FogCompute.Groups(size.X, size.Y);
        uint views = buffers.GetViewCount();
        for (uint v = 0; v < views; v++)
        {
            var image = new RDUniform { UniformType = RenderingDevice.UniformType.Image, Binding = 0 };
            image.AddId(buffers.GetColorLayer(v));
            var depth = new RDUniform { UniformType = RenderingDevice.UniformType.SamplerWithTexture, Binding = 1 };
            depth.AddId(_sampler);
            depth.AddId(buffers.GetDepthLayer(v));
            var set = UniformSetCacheRD.GetCache(_shader, 0, new Godot.Collections.Array<RDUniform> { image, depth });
            long list = _rd.ComputeListBegin();
            _rd.ComputeListBindComputePipeline(list, _pipeline);
            _rd.ComputeListBindUniformSet(list, set, 0);
            _rd.ComputeListSetPushConstant(list, push, (uint)push.Length);
            _rd.ComputeListDispatch(list, (uint)gx, (uint)gy, 1);
            _rd.ComputeListEnd();
        }
        Dispatches++;
    }

    public override void _Notification(int what)
    {
        if (what != NotificationPredelete || _rd is null) return;
        var rd = _rd;
        Rid shader = _shader, sampler = _sampler;
        _ready = false;
        // The pipeline goes with its shader.
        RenderingServer.CallOnRenderThread(Callable.From(() =>
        {
            if (shader.IsValid) rd.FreeRid(shader);
            if (sampler.IsValid) rd.FreeRid(sampler);
        }));
    }
}
