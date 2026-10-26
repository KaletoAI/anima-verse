using System;
using System.Collections.Generic;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The hemisphere's n.y term as a SHADER term on the terrain (Task 26b). The stage emulates three's HemisphereLight as an
/// ambient colour plus a pair of opposite shadowless directional lights (<see cref="StageAmbience"/>,
/// <see cref="Sky.StageLight"/>): <c>ambient + pair·max(0, n.y) − pair·max(0, −n.y) = ambient + pair·n.y</c>. Each of those
/// two lights runs Godot's whole <c>light_compute</c> (Lambert + the GGX block, even at specular 0) for every fragment of
/// every lit material. The ground materials are our own shaders, so for them the pair is computed once in the shader
/// instead — <c>EMISSION += ALBEDO · (1 − METALLIC) · av_hemi · n.y</c>, which is the exact sum Godot forms for the pair
/// (<c>diffuse_light += colour·energy·π · max(N·L, 0)/π</c>, then <c>× albedo × ao × (1 − metallic)</c>; ao is 1, the
/// ground writes no AO) — and the terrain instances sit on <see cref="Layer"/>, which the two pair lights do not light
/// (<c>light_cull_mask</c>; the shader skips a masked directional light before <c>light_compute</c>). Since Task 26c the
/// scatter and the undergrowth do the same (Scatter/ScatterShaders.cs, their nodes on <see cref="Layer"/>). Everything
/// else (models, recipe pieces, figures — StandardMaterial3D) keeps the pair lights.
///
/// <c>av_hemi</c> = the pair's linear colour × its energy (<c>Color.SrgbToLinear() · E</c>, Godot's own decode), pushed by
/// the stage on every clock/ambience change to every bound material, like <see cref="VeilUniforms"/>.
/// </summary>
public static class HemiUniforms
{
    /// <summary>Render layer 20: the instances whose shader carries the hemisphere term (the pair lights skip it).</summary>
    public const uint Layer = 1u << 19;

    /// <summary>The cull mask of the two pair lights: everything but <see cref="Layer"/>.</summary>
    public const uint PairCullMask = 0xFFFFFFFFu & ~Layer;

    /// <summary>The shader uniform name.</summary>
    public const string Uniform = "av_hemi";

    private static readonly List<WeakReference<ShaderMaterial>> Bound = new();
    private static Vector3 _value;
    private static bool _off;

    /// <summary>The term bound now (linear colour × energy).</summary>
    public static Vector3 Value => _value;

    /// <summary>The bench switch <c>no-hemi-extra-lights</c>: the shader term zero (the pair lights are hidden with it).</summary>
    public static bool Off
    {
        get => _off;
        set
        {
            if (_off == value) return;
            _off = value;
            Push();
        }
    }

    /// <summary>The live bound materials (dead ones are dropped on the way).</summary>
    public static List<ShaderMaterial> Materials()
    {
        var live = new List<ShaderMaterial>();
        lock (Bound)
        {
            Bound.RemoveAll(w => !w.TryGetTarget(out var m) || !GodotObject.IsInstanceValid(m));
            foreach (var w in Bound)
                if (w.TryGetTarget(out var m)) live.Add(m);
        }
        return live;
    }

    /// <summary>A ground or scatter material: the current term now, every later change too.</summary>
    public static void Bind(ShaderMaterial? material)
    {
        if (material is null) return;
        lock (Bound)
        {
            bool known = false;
            foreach (var w in Bound)
                if (w.TryGetTarget(out var m) && ReferenceEquals(m, material)) { known = true; break; }
            if (!known) Bound.Add(new WeakReference<ShaderMaterial>(material));
        }
        material.SetShaderParameter(Uniform, _off ? Vector3.Zero : _value);
    }

    /// <summary>The stage's pair (linear colour × energy); an unchanged value writes nothing.</summary>
    public static void Set(Vector3 linearTimesEnergy)
    {
        if (linearTimesEnergy == _value) return;
        _value = linearTimesEnergy;
        Push();
    }

    private static void Push()
    {
        var v = _off ? Vector3.Zero : _value;
        foreach (var m in Materials()) m.SetShaderParameter(Uniform, v);
    }

    /// <summary>A new world: nothing bound (the value stays the stage's — the next stage flush writes its own).</summary>
    public static void Reset()
    {
        lock (Bound) Bound.Clear();
        _off = false;
    }
}
