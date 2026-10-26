using System;
using AnimaNative.Scene;

namespace AnimaNative.Sky;

/// <summary>
/// A colour ENCODED for a Godot <c>Color</c> that the renderer treats as sRGB (light colour, ambient colour, background
/// colour): Godot converts those with <c>Color.srgb_to_linear()</c> before it lights with them (light_storage.cpp,
/// render_scene_data_rd.cpp). <see cref="Encode"/> is the exact inverse of that conversion, so the renderer ends up with
/// the three linear working colour that went in.
/// </summary>
public readonly record struct GodotSrgb(double R, double G, double B)
{
    /// <summary>Godot 4.7.2 <c>Color::srgb_to_linear</c> (core/math/color.h), per channel.</summary>
    public static double ToLinear(double c)
        => c < 0.04045 ? c * (1.0 / 12.92) : Math.Pow((c + 0.055) * (1.0 / (1.0 + 0.055)), 2.4);

    /// <summary>The exact inverse of <see cref="ToLinear"/> (Godot's <c>linear_to_srgb</c>, exponent 1/2.4).</summary>
    public static double FromLinear(double c)
        => c < 0.0031308 ? 12.92 * c : (1.0 + 0.055) * Math.Pow(c, 1.0 / 2.4) - 0.055;

    /// <summary>A three linear working colour → the Godot <c>Color</c> channels that reproduce it.</summary>
    public static GodotSrgb Encode(LinearRgb c) => new(FromLinear(c.R), FromLinear(c.G), FromLinear(c.B));

    /// <summary>What the renderer computes from this colour (<c>srgb_to_linear</c>).</summary>
    public LinearRgb Linear => new(ToLinear(R), ToLinear(G), ToLinear(B));
}

/// <summary>One Godot light: its encoded colour and its energy (already mapped from the three intensity).</summary>
public readonly record struct GodotLight(GodotSrgb Color, double Energy);

/// <summary>
/// The whole stage of one frame, in Godot terms: sun, fill, the hemisphere (an ambient colour plus a pair of opposite
/// shadowless directional lights, the lower one negative), the background, the water's <c>tw_sky</c> (null = leave the
/// shader default), the sun's offset from the shadow centre, the sun angle and the night factor.
/// </summary>
public readonly record struct StageFrame(GodotLight Sun, GodotLight Fill, GodotLight Ambient, GodotLight HemiPair,
                                         GodotSrgb Background, (double R, double G, double B)? WaterSky,
                                         double SunAngle, double Night);

/// <summary>
/// The browser engine's light set (client3d/src/scene/engine.ts: the constructor, <c>setGameHour</c>,
/// <c>applyAmbience</c> and the per-frame sun placement) mapped onto Godot.
///
/// <b>Units — the 1/π mapping.</b> three r185 (physically based, no legacy lights) lights a diffuse surface with
/// <c>albedo/π · I · colour · N·L</c> for a directional light and <c>albedo/π · I · mix(ground, sky, ½ + ½·n.y)</c> for its
/// HemisphereLight. Godot 4.7.2 multiplies a directional or omni light's energy by π (light_storage.cpp, non-physical
/// units) and its Lambert term divides by π again (scene_forward_lights_inc.glsl), so it lights with
/// <c>albedo · E · colour · N·L</c>; its ambient colour lights with <c>albedo · E · colour</c> and no 1/π at all. Both
/// therefore agree when <c>E = I / π</c> — for the sun, the fill, the hemisphere and the prop lamps alike. The GGX
/// specular agrees under the same mapping (Godot's D_GGX carries the 1/π that three's does).
///
/// <b>Colours.</b> three keeps its colours in a LINEAR working space; a Godot light/ambient/background <c>Color</c> is
/// sRGB-encoded and converted by the renderer, so every colour goes through <see cref="GodotSrgb.Encode"/>. The water's
/// sky is the exception: the browser hands its shader the sRGB BYTES of <c>getHex()</c> divided by 255 (scene-render
/// <c>setSurfaceSky</c>) and the shader uses them as they are — native does the same.
///
/// <b>Hemisphere.</b> <c>mix(G, S, ½ + ½·n.y) = (S + G)/2 + (S − G)/2 · n.y</c> is linear in n.y over the whole sphere. Godot
/// has no hemisphere light, but an ambient colour of (S + G)/2 plus a directional light straight down with colour
/// (S − G)/2 (lighting <c>max(0, n.y)</c>) plus the same light straight up and NEGATIVE (taking <c>max(0, −n.y)</c> away)
/// gives exactly that sum for a Lambert surface. Both pair lights have no shadow and no specular, as three's hemisphere
/// light has neither.
/// </summary>
public static class StageLight
{
    // ---- engine.ts constants (no shared vector carries them yet; retyped with their source line) -------------------
    /// <summary><c>new THREE.HemisphereLight(0xdfeeff, 0x8a9a78, 1.5)</c> — its colours never change with the hour.</summary>
    public static readonly LinearRgb HemiSky = LinearRgb.FromSrgbHex(0xdfeeff), HemiGround = LinearRgb.FromSrgbHex(0x8a9a78);
    /// <summary><c>new THREE.DirectionalLight(0xdde8ff, 0.5)</c> at <c>(−30, 20, −25)</c>, target at the origin (never moved).</summary>
    public static readonly LinearRgb FillColour = LinearRgb.FromSrgbHex(0xdde8ff);
    public static readonly (double X, double Y, double Z) FillOffset = (-30, 20, -25);
    /// <summary>The constructor's sun <c>(0xfff2d8, 2.0)</c> and sky <c>0x9fc7e8</c> — the stage before the first clock reading.</summary>
    public static readonly LinearRgb BootSun = LinearRgb.FromSrgbHex(0xfff2d8), BootSky = LinearRgb.FromSrgbHex(0x9fc7e8);
    public const double BootSunI = 2.0, BootHemiI = 1.5, BootFillI = 0.5;
    /// <summary><c>private sunAngle = Math.PI * 0.35</c>: late morning until the clock is read.</summary>
    public const double DefaultSunAngle = Math.PI * 0.35;
    /// <summary>The sun's offset from its shadow centre: <c>(60·cos a, 80·max(0.08, sin a), 25)</c> (engine.ts frame()).</summary>
    public const double SunOffsetX = 60, SunOffsetY = 80, SunOffsetZ = 25, SunMinRise = 0.08;
    /// <summary>scene-render <c>surfaceSkyUniform</c>'s start value: the water's sky before any <c>setSurfaceSky</c>.</summary>
    public static readonly (double R, double G, double B) WaterSkyDefault = (0.62, 0.78, 0.91);

    /// <summary>A three light intensity → a Godot light (or ambient) energy: <c>I / π</c> (see the class summary).</summary>
    public static double Energy(double threeIntensity) => threeIntensity / Math.PI;

    /// <summary>The sun's offset from the (snapped) camera target for a sun angle.</summary>
    public static (double X, double Y, double Z) SunOffset(double sunAngle)
        => (Math.Cos(sunAngle) * SunOffsetX, Math.Max(SunMinRise, Math.Sin(sunAngle)) * SunOffsetY, SunOffsetZ);

    /// <summary>
    /// The sun's world position: <c>snapShadowCentre(target, offset) + offset</c>; the light shines from there to the
    /// snapped centre. (In Godot only the direction lights; the position keeps the browser's numbers for the check.)
    /// </summary>
    public static ((double X, double Y, double Z) Centre, (double X, double Y, double Z) Position) SunPlacement(
        (double X, double Y, double Z) target, double sunAngle)
    {
        var off = SunOffset(sunAngle);
        var c = ShadowSnap.SnapCentre(target, off);
        return (c, (c.X + off.X, c.Y + off.Y, c.Z + off.Z));
    }

    private static LinearRgb Mul(LinearRgb a, LinearRgb b) => new(a.R * b.R, a.G * b.G, a.B * b.B);
    private static LinearRgb Scale(LinearRgb a, double k) => new(a.R * k, a.G * k, a.B * k);

    /// <summary>The ambience tint (sRGB numbers 0..1, <c>setRGB(..., SRGBColorSpace)</c>) in the linear working space.</summary>
    public static LinearRgb TintOf(AmbienceState a)
        => new(LinearRgb.SrgbToLinear(a.R), LinearRgb.SrgbToLinear(a.G), LinearRgb.SrgbToLinear(a.B));

    /// <summary>
    /// The stage for a clock reading (<paramref name="hour"/>, null before the first reading) under the room ambience. Like engine.ts: before the first <c>setGameHour</c> the constructor's lights
    /// stand and <c>applyAmbience</c> does nothing (no <c>baseLights</c> yet); afterwards every intensity is
    /// base × daylight and every light colour base × tint, the hemisphere and fill colours keep their constructor base,
    /// and the water's sky is <c>getHex(sky × daylight × tint) / 255</c>. The background is the clock's sky, untouched
    /// by the ambience.
    /// </summary>
    public static StageFrame Compose(double? hour, AmbienceState ambience)
    {
        if (hour is not { } h)
            return Build(BootSun, BootSunI, BootHemiI, BootFillI, new LinearRgb(1, 1, 1), BootSky, null, DefaultSunAngle, 0);
        var c = SkyLight.GameHourLights(h);
        var tint = TintOf(ambience);
        double day = ambience.Daylight;
        int hex = Mul(Scale(c.Sky, day), tint).ToSrgbHex();
        var water = (((hex >> 16) & 255) / 255.0, ((hex >> 8) & 255) / 255.0, (hex & 255) / 255.0);
        double night = Ambience.NightFactorAt(h);
        return Build(Mul(c.Sun, tint), c.SunIntensity * day, c.HemiIntensity * day, c.FillIntensity * day, tint, c.Sky, water,
                     c.SunAngle, night);
    }

    private static StageFrame Build(LinearRgb sun, double sunI, double hemiI, double fillI, LinearRgb tint, LinearRgb sky,
                                    (double, double, double)? water, double sunAngle, double night)
    {
        var s = Mul(HemiSky, tint);
        var g = Mul(HemiGround, tint);
        var mean = new LinearRgb((s.R + g.R) / 2, (s.G + g.G) / 2, (s.B + g.B) / 2);
        var half = new LinearRgb((s.R - g.R) / 2, (s.G - g.G) / 2, (s.B - g.B) / 2);
        return new StageFrame(
            new GodotLight(GodotSrgb.Encode(sun), Energy(sunI)),
            new GodotLight(GodotSrgb.Encode(Mul(FillColour, tint)), Energy(fillI)),
            new GodotLight(GodotSrgb.Encode(mean), Energy(hemiI)),
            new GodotLight(GodotSrgb.Encode(half), Energy(hemiI)),
            GodotSrgb.Encode(sky), water, sunAngle, night);
    }

    /// <summary>
    /// The hemisphere's diffuse factor in three for a unit normal's y (what multiplies albedo):
    /// <c>I · mix(G, S, ½ + ½·n.y) / π</c> — the reference the Godot ambient + pair must reproduce.
    /// </summary>
    public static LinearRgb ThreeHemiDiffuse(double hemiI, LinearRgb tint, double ny)
    {
        var s = Mul(HemiSky, tint);
        var g = Mul(HemiGround, tint);
        double w = 0.5 + 0.5 * ny;
        return Scale(g.Lerp(s, w), hemiI / Math.PI);
    }

    /// <summary>
    /// The same factor as Godot computes it from a frame: <c>ambient·E + pair·E·max(0, n.y) − pair·E·max(0, −n.y)</c>
    /// (directional energy ×π, Lambert ÷π).
    /// </summary>
    public static LinearRgb GodotHemiDiffuse(StageFrame f, double ny)
    {
        var a = Scale(f.Ambient.Color.Linear, f.Ambient.Energy);
        var p = Scale(f.HemiPair.Color.Linear, f.HemiPair.Energy * (Math.Max(0, ny) - Math.Max(0, -ny)));
        return new LinearRgb(a.R + p.R, a.G + p.G, a.B + p.B);
    }
}

/// <summary>
/// Godot's directional shadow, fitted to the browser's one box: the browser's sun renders ONE orthographic shadow map of
/// ±70 m (<see cref="ShadowSnap.HalfM"/>) at 2048² around the camera target, 6.84 cm per texel. Godot fits its
/// orthogonal shadow (one split, the whole 4096² directional atlas) to the bounding sphere of the camera frustum from the
/// near plane to <c>directional_shadow_max_distance</c> and snaps it to texels itself (renderer_scene_cull.cpp
/// <c>_light_instance_setup_directional_shadow</c>). The max distance follows the camera distance plus the browser's half
/// box, in 10-m steps so the fit only changes in steps while zooming (a constant fit keeps the edges still).
/// </summary>
public static class ShadowFit
{
    /// <summary>The distance step of the max distance (m).</summary>
    public const double StepM = 10;
    /// <summary>Godot's default directional shadow atlas (<c>rendering/lights_and_shadows/directional_shadow/size</c>).</summary>
    public const int AtlasPx = 4096;

    /// <summary><c>ceil((cameraDist + 70) / 10) · 10</c>.</summary>
    public static double MaxDistanceM(double cameraDist) => Math.Ceiling((cameraDist + ShadowSnap.HalfM) / StepM) * StepM;

    /// <summary>
    /// The texel size Godot ends up with for a perspective camera (vertical FOV, aspect, near) and a max distance: the
    /// bounding sphere of the frustum slice's eight corners about their mean, grown by one texel per side
    /// (<c>size / (size − 2)</c>), over the atlas pixels.
    /// </summary>
    public static double TexelM(double maxDistance, double fovYDeg, double aspect, double near, int atlasPx = AtlasPx)
    {
        double th = Math.Tan(fovYDeg * Math.PI / 360);
        Span<(double X, double Y, double Z)> p = stackalloc (double, double, double)[8];
        int k = 0;
        foreach (double z in new[] { near, maxDistance })
            for (int sx = -1; sx <= 1; sx += 2)
                for (int sy = -1; sy <= 1; sy += 2)
                    p[k++] = (sx * z * th * aspect, sy * z * th, z);
        double cx = 0, cy = 0, cz = 0;
        foreach (var q in p) { cx += q.X; cy += q.Y; cz += q.Z; }
        cx /= 8; cy /= 8; cz /= 8;
        double r = 0;
        foreach (var q in p) r = Math.Max(r, Math.Sqrt((q.X - cx) * (q.X - cx) + (q.Y - cy) * (q.Y - cy) + (q.Z - cz) * (q.Z - cz)));
        r *= atlasPx / (atlasPx - 2.0);
        return 2 * r / atlasPx;
    }
}
