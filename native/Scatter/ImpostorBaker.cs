using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;
using Environment = Godot.Environment;

namespace AnimaNative.Scatter;

/// <summary>Task 38 (E4-T3): one owned texture and the vectored frame, shared by all entries leasing a low URL.</summary>
public sealed record ImpostorBake(Texture2D Texture, ImpostorFrame Frame) : IDisposable
{
    public void Dispose() => Texture.Dispose();
}

/// <summary>Task 38 (E4-T3): synchronous contact starts a deduplicated asynchronous bake; null means try next pass.
/// Acquire takes a reference only when it returns a bake; Release belongs to the entry's disposal.</summary>
public interface IImpostorSource
{
    ImpostorBake? Acquire(string url);
    void Release(string url);
}

/// <summary>Task 38 (E4-T3): the GPU half of <c>impostors.ts</c>. An isolated transparent World3D, one orthographic
/// midday view, 128², and a 16-entry reference-aware LRU. Only loaded degenerate models are refused; missing renderer
/// and failed downloads retry. ViewportTexture exposes no mipmap generation, so read back once, generate mipmaps,
/// and retain an ImageTexture after freeing the viewport. All geometry decisions come from ScatterLod's vectors.</summary>
public partial class ImpostorBaker : Node, IImpostorSource
{
    public const int TexturePx = 128, CacheMax = 16;
    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly ImpostorCache<ImpostorBake> _cache = new(CacheMax);
    private readonly HashSet<string> _pending = new(StringComparer.Ordinal);
    private bool _closed;
    public string LastVerdict { get; private set; } = "retry";
    public int CachedCount => _cache.Count;
    public int PendingCount => _pending.Count;

    public ImpostorBaker(IWorldSource source, Action<string> log) { _source = source; _log = log; Name = "ImpostorBaker"; }
    public ImpostorBake? Acquire(string url)
    {
        if (_closed) return null;
        var bake = _cache.Acquire(url);
        if (bake is not null || _cache.Contains(url) || _pending.Contains(url)) return bake;
        // DisplayServer headless uses the dummy renderer; it cannot emit FramePostDraw for a real bake.
        if (!IsInsideTree() || DisplayServer.GetName() == "headless")
        {
            LastVerdict = ScatterLod.ImpostorBakeVerdict("no-renderer");
            return null;
        }
        _pending.Add(url);
        _ = BakeAndStoreAsync(url);
        return null;
    }
    public void Release(string url) => _cache.Release(url);

    internal async Task BakeAndStoreAsync(string url)
    {
        ImpostorBake? bake = null;
        string attempt = "load-failed";
        try
        {
            byte[] bytes;
            try { bytes = await _source.GetBytesAsync(url); }
            catch (Exception e) { _log($"impostor load {url}: {e.Message}"); return; }
            if (_closed) return;
            // Match Task 37: parse resources on a worker, generate and mount scene nodes on the main thread.
            var parsed = await Task.Run(() =>
            {
                using var parse = (_source as AnimaApi)?.Measurements.Time("scene GLB", "parse");
                return GlbLoader.Parse(GlbLoader.Prepare(bytes), url);
            });
            using var doc = parsed.Doc;
            using var state = parsed.State;
            if (_closed) return;
            Node3D root;
            using ((_source as AnimaApi)?.Measurements.Time("scene GLB", "generate"))
            using (Ui.HitchLog.Time("impostor generate"))
                root = GlbLoader.Generate(doc, state, url);
            attempt = "unbakeable";
            bake = await RenderAsync(root);
            if (bake is not null) attempt = "baked";
        }
        catch (Exception e) { _log($"impostor bake {url}: {e.Message}"); }
        finally
        {
            LastVerdict = ScatterLod.ImpostorBakeVerdict(attempt);
            _pending.Remove(url);
            if (_closed) bake?.Dispose();
            else if (LastVerdict == "store") _cache.Store(url, bake);
            else if (LastVerdict == "refuse") _cache.Store(url, null);
        }
    }

    /// <summary>The whole GLB template, including every node transform and every surface. Bounds are from the model
    /// origin horizontally and the box centre vertically, exactly as Box3.setFromObject in the browser.</summary>
    private async Task<ImpostorBake?> RenderAsync(Node3D root)
    {
        SubViewport? viewport = null;
        try
        {
            var meshes = new List<(MeshInstance3D Node, Transform3D Xf)>();
            Vector3 min = new(float.PositiveInfinity, float.PositiveInfinity, float.PositiveInfinity), max = -min;
            void Visit(Node node, Transform3D parent)
            {
                var xf = node is Node3D n ? parent * n.Transform : parent;
                if (node is MeshInstance3D { Mesh: { } mesh } mi)
                {
                    meshes.Add((mi, xf));
                    var box = mesh.GetAabb();
                    for (int i = 0; i < 8; i++)
                    {
                        var p = xf * box.GetEndpoint(i);
                        min = min.Min(p); max = max.Max(p);
                    }
                }
                foreach (var child in node.GetChildren()) Visit(child, xf);
            }
            Visit(root, Transform3D.Identity);
            double h = max.Y - min.Y;
            double r = Math.Max(Math.Max(Math.Abs(min.X), Math.Abs(max.X)), Math.Max(Math.Abs(min.Z), Math.Abs(max.Z)));
            if (meshes.Count == 0 || !double.IsFinite(h) || !double.IsFinite(r)
                || ScatterLod.ImpostorFrame(h, r) is not { } frame) return null;
            viewport = new SubViewport
            {
                Name = "ImpostorBakeViewport", Size = new Vector2I(TexturePx, TexturePx),
                World3D = new World3D(), TransparentBg = true,
                RenderTargetUpdateMode = SubViewport.UpdateMode.Disabled,
            };
            AddChild(viewport);
            // Fixed mean ambient plus opposite signed Lambert lights reproduce the hemisphere's linear n.y term.
            // The bake materials carry the signed term directly; this prevents live world clock updates leaking in.
            var sky = Color.FromHtml("dfeeff").SrgbToLinear();
            var ground = Color.FromHtml("8a9a78").SrgbToLinear();
            var mean = (sky + ground) * 0.5f;
            var half = (sky - ground) * (float)(0.5 * StageLight.Energy(1.5));
            viewport.AddChild(new WorldEnvironment { Environment = new Environment
            {
                BackgroundMode = Environment.BGMode.Color, BackgroundColor = Colors.Transparent,
                AmbientLightSource = Environment.AmbientSource.Color, AmbientLightSkyContribution = 0,
                AmbientLightColor = mean.LinearToSrgb(), AmbientLightEnergy = (float)StageLight.Energy(1.5),
                ReflectedLightSource = Environment.ReflectionSource.Disabled,
                TonemapMode = Environment.ToneMapper.Linear, TonemapExposure = 1,
            } });
            viewport.AddChild(new DirectionalLight3D
            {
                Name = "BakeSun", LightColor = Color.FromHtml("fff2d8"), LightEnergy = (float)StageLight.Energy(2),
                ShadowEnabled = false, Basis = StageAmbience.LightBasisOf((0.6, 1.4, 1)),
            });
            // Scene nodes are replaced by plain mesh nodes so animation scripts cannot move the static bake.
            foreach (var (node, xf) in meshes)
            {
                var copy = new MeshInstance3D { Mesh = node.Mesh, Transform = xf,
                    CastShadow = GeometryInstance3D.ShadowCastingSetting.Off };
                for (int i = 0; i < node.Mesh!.GetSurfaceCount(); i++)
                    copy.SetSurfaceOverrideMaterial(i, ScatterShaders.ForImpostorBake(node.GetActiveMaterial(i), frame.Aspect,
                        new Vector3(half.R, half.G, half.B)));
                viewport.AddChild(copy);
            }
            var camera = CameraForBake(h, r, (min.Y + max.Y) / 2, frame);
            viewport.AddChild(camera);
            camera.MakeCurrent();
            viewport.RenderTargetUpdateMode = SubViewport.UpdateMode.Once;
            await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
            if (_closed || !IsInstanceValid(viewport)) return null;
            using var readback = Ui.HitchLog.Time("impostor readback");
            using var image = viewport.GetTexture().GetImage();
            if (image is null || image.IsEmpty()) throw new InvalidOperationException("empty impostor readback");
            image.Convert(Image.Format.Rgba8);
            if (image.GenerateMipmaps() != Error.Ok) throw new InvalidOperationException("impostor mipmaps failed");
            return new ImpostorBake(ImageTexture.CreateFromImage(image), frame);
        }
        finally
        {
            root.Free();
            if (viewport is not null && IsInstanceValid(viewport)) viewport.QueueFree();
        }
    }

    /// <summary>Task 38 (E4-T3): a square CPU frustum encloses BOTH dimensions of the rectangular frame, so even
    /// separate side meshes of a wide prop survive culling. The bake shader compensates X/Y in clip space.</summary>
    internal static Camera3D CameraForBake(double h, double r, double cy, ImpostorFrame frame)
    {
        double dist = h + 2 * r + 10;
        return new Camera3D
        {
            Projection = Camera3D.ProjectionType.Orthogonal, KeepAspect = Camera3D.KeepAspectEnum.Height,
            Size = (float)(h * frame.SpanH * Math.Max(1, frame.Aspect)), Near = 0.01f, Far = (float)(dist * 2),
            Position = new Vector3(0, (float)(cy + Math.Sin(ScatterLod.ImpostorElevRad) * dist),
                (float)(Math.Cos(ScatterLod.ImpostorElevRad) * dist)),
            Basis = StageAmbience.LightBasisOf((0, Math.Sin(ScatterLod.ImpostorElevRad), Math.Cos(ScatterLod.ImpostorElevRad))),
        };
    }

    public override void _ExitTree() { _closed = true; _cache.Dispose(); }
}
