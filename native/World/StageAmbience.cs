using AnimaNative.Ground;
using AnimaNative.Scene;
using AnimaNative.Water;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// <c>engine.applyAmbience(daylight, tint)</c> on the native stage: sun, fill and ambient intensities × daylight, their
/// colours × tint (multiplied in LINEAR space, as three multiplies its working colours), the water's sky reflection
/// along (<c>setSurfaceSky(sky × daylight × tint)</c>, a uniform of sRGB numbers); the sky background stays.
///
/// NEUTRAL BASE UNTIL E3: the native client has no game-hour light model yet, so the base is the fixed stage of
/// Main.BuildStage (the browser's default hour scaled by <see cref="Ambience.StageScale"/>) and the water's default
/// sky. When E3 brings <c>setGameHour</c>, only these base values move.
/// </summary>
public sealed class StageAmbience
{
    public static readonly Color SunBase = new("fff2d8"), FillBase = new("dde8ff"), AmbientBase = new("dfeeff");
    public const float SunEnergy = 1.0f, FillEnergy = 0.25f, AmbientEnergy = 0.7f;

    public DirectionalLight3D? Sun { get; init; }
    public DirectionalLight3D? Fill { get; init; }
    public Environment? Env { get; init; }
    /// <summary>The terrain's water material (its <c>tw_sky</c>), asked at every apply — the ground may come later.</summary>
    public System.Func<ShaderMaterial?>? Water { get; init; }

    private AmbienceState _applied = new(double.NaN, 0, 0, 0);

    /// <summary>Apply an eased state; an unchanged one writes nothing.</summary>
    public void Apply(AmbienceState a)
    {
        if (a == _applied) return;
        _applied = a;
        var tint = new Color((float)a.R, (float)a.G, (float)a.B).SrgbToLinear();
        Color Tinted(Color baseSrgb) => (baseSrgb.SrgbToLinear() * tint).LinearToSrgb();
        if (Sun is not null) { Sun.LightEnergy = (float)(SunEnergy * a.Daylight); Sun.LightColor = Tinted(SunBase); }
        if (Fill is not null) { Fill.LightEnergy = (float)(FillEnergy * a.Daylight); Fill.LightColor = Tinted(FillBase); }
        if (Env is not null) { Env.AmbientLightEnergy = (float)(AmbientEnergy * a.Daylight); Env.AmbientLightColor = Tinted(AmbientBase); }
        if (Water?.Invoke() is { } water)
        {
            var sky = (new Color((float)WaterShade.Sky.R, (float)WaterShade.Sky.G, (float)WaterShade.Sky.B).SrgbToLinear() * tint * (float)a.Daylight).LinearToSrgb();
            water.SetShaderParameter("tw_sky", new Vector3(sky.R, sky.G, sky.B));
        }
    }
}
