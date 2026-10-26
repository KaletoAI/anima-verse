using System;
using System.Collections.Generic;
using AnimaNative.Ground;
using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The exploration veil's shared uniforms (client3d/src/scene/fogVeil.ts: ONE uniform object per value for every veiled
/// material) on Godot: the Godot-free <see cref="FogVeilState{T}"/> holds the two cell textures, the crossfade and the
/// strength; every ground material (dry, wet, plain — <see cref="GroundShader"/>'s <c>fv_*</c>) is
/// <see cref="Bind">bound</see> once and then receives each change. Per frame only what moved is written (the alpha
/// follows the camera height, the mix runs for 0.6 s after the memory grew); a texture is made only when the explored
/// set changed (<c>explored_sig</c>), never per frame.
///
/// Module state like the browser's — one veil per process; <see cref="Reset"/> on a new world (back to the title, a
/// check) drops the bindings and returns to "nothing explored".
/// </summary>
public static class VeilUniforms
{
    /// <summary>The sky before the first clock reading (<c>uFogColor</c> 0x9fc7e8), linear.</summary>
    public static readonly Vector3 DefaultSky = Linear(new Color(0x9fc7e8ff));

    private static ImageTexture? _neutral;
    private static FogVeilState<ImageTexture>? _state;
    private static readonly List<WeakReference<ShaderMaterial>> Bound = new();
    private static Vector3 _color = DefaultSky;
    private static double _pushedAlpha = double.NaN, _pushedMix = double.NaN;
    private static int _pushedVersion = -1;

    /// <summary>"Nothing is explored": the one zero texel every veil falls back to (never freed).</summary>
    public static ImageTexture Neutral => _neutral ??= Make(FogCells.Neutral);

    public static FogVeilState<ImageTexture> State => _state ??= new FogVeilState<ImageTexture>(Neutral, Make);

    /// <summary>The haze colour bound now (the clock's sky, linear).</summary>
    public static Vector3 SkyColor => _color;

    /// <summary>How many cell textures were made (one per changed memory).</summary>
    public static int Uploads { get; private set; }

    /// <summary><c>makeCells</c>: an R8 texture, one texel per cell (sampled linear and clamped by the shader's hints).</summary>
    public static ImageTexture Make(FogCells cells)
    {
        if (!ReferenceEquals(cells, FogCells.Neutral)) Uploads++;
        return ImageTexture.CreateFromImage(Image.CreateFromData(cells.Cols, cells.Rows, false, Image.Format.R8, cells.Data));
    }

    private static Vector3 Linear(Color srgb)
    {
        var c = srgb.SrgbToLinear();
        return new Vector3(c.R, c.G, c.B);
    }

    /// <summary>The live bound materials (dead ones are dropped on the way).</summary>
    public static List<ShaderMaterial> Materials()
    {
        var live = new List<ShaderMaterial>();
        Bound.RemoveAll(w => !w.TryGetTarget(out var m) || !GodotObject.IsInstanceValid(m));
        foreach (var w in Bound)
            if (w.TryGetTarget(out var m)) live.Add(m);
        return live;
    }

    /// <summary>A veiled ground material: every value of NOW is written, later changes reach it too.</summary>
    public static void Bind(ShaderMaterial? material)
    {
        if (material is null) return;
        if (!Materials().Contains(material)) Bound.Add(new WeakReference<ShaderMaterial>(material));
        WriteTextures(material);
        material.SetShaderParameter("fv_mix", (float)State.Mix);
        material.SetShaderParameter("fv_alpha", (float)State.Alpha);
        material.SetShaderParameter("fv_color", _color);
    }

    private static void WriteTextures(ShaderMaterial m)
    {
        var s = State;
        m.SetShaderParameter("fv_cells_a", s.A);
        m.SetShaderParameter("fv_cells_b", s.B);
        m.SetShaderParameter("fv_geom_a", V4(s.GeomA));
        m.SetShaderParameter("fv_geom_b", V4(s.GeomB));
    }

    private static Vector4 V4((double X, double Y, double Z, double W) g) => new((float)g.X, (float)g.Y, (float)g.Z, (float)g.W);

    private static void Push()
    {
        var s = State;
        bool textures = s.Version != _pushedVersion, alpha = s.Alpha != _pushedAlpha, mix = s.Mix != _pushedMix;
        if (!textures && !alpha && !mix) return;
        foreach (var m in Materials())
        {
            if (textures) WriteTextures(m);
            if (mix) m.SetShaderParameter("fv_mix", (float)s.Mix);
            if (alpha) m.SetShaderParameter("fv_alpha", (float)s.Alpha);
        }
        _pushedVersion = s.Version;
        _pushedAlpha = s.Alpha;
        _pushedMix = s.Mix;
    }

    /// <summary><c>setFogVeilCells</c>: the whole memory (the answer of <c>/play/explored</c>).</summary>
    public static void SetCells(IReadOnlyList<string> cells)
    {
        State.SetCells(cells);
        Push();
    }

    /// <summary><c>setFogVeilFogged(map.fogged !== false)</c>.</summary>
    public static void SetFogged(bool on)
    {
        State.SetFogged(on);
        Push();
    }

    /// <summary><c>setFogVeilCameraHeight(camera.y − target.y)</c>, per frame.</summary>
    public static void SetCameraHeight(double metres)
    {
        State.SetCameraHeight(metres);
        Push();
    }

    /// <summary><c>setFogVeilSky</c>: the clock's sky (linear), with the background and the distance fog.</summary>
    public static void SetSky(Vector3 linear)
    {
        if (linear == _color) return;
        _color = linear;
        foreach (var m in Materials()) m.SetShaderParameter("fv_color", _color);
    }

    /// <summary><c>tickFogVeil(dt)</c>: the crossfade of a memory that has just grown.</summary>
    public static void Tick(double dt)
    {
        if (State.Tick(dt)) Push();
    }

    /// <summary>A new world: nothing explored, nothing bound, the default sky (<c>releaseFogVeil</c> + the module's start).</summary>
    public static void Reset()
    {
        State.Release();
        _state = null;
        Bound.Clear();
        _color = DefaultSky;
        _pushedAlpha = _pushedMix = double.NaN;
        _pushedVersion = -1;
    }

    public static string Summary()
    {
        var s = State;
        return $"veil[cells={s.ExploredCells} alpha={s.Alpha:0.###} mix={s.Mix:0.##} fogged={(s.Fogged ? "yes" : "no")} "
               + $"height={s.CameraHeight:0.#} bound={Materials().Count} uploads={Uploads}]";
    }
}
