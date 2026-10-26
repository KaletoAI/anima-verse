using System;
using AnimaNative.Scene;
using AnimaNative.Sky;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The Godot mapping of the browser's stage (<see cref="StageLight"/>, <see cref="ShadowFit"/>). Every expectation is
/// derived by hand from engine.ts / skyLight.ts, three r185's ColorManagement and Godot 4.7.2's color.h /
/// light_storage.cpp (the derivations: native/fixtures/README.md "Light"); none is a recording of current output.
/// </summary>
public class StageLightTests
{
    private static void Near(double want, double got, double eps = 1e-9)
        => Assert.True(Math.Abs(want - got) <= eps, $"expected {want}, got {got}");

    private static void NearRgb(double r, double g, double b, GodotSrgb c, double eps = 1e-9)
    {
        Near(r, c.R, eps);
        Near(g, c.G, eps);
        Near(b, c.B, eps);
    }

    private static void NearLin(LinearRgb want, LinearRgb got, double eps = 1e-12)
    {
        Near(want.R, got.R, eps);
        Near(want.G, got.G, eps);
        Near(want.B, got.B, eps);
    }

    // ---- the colour conversion ---------------------------------------------------------------------------------------

    /// <summary>
    /// three's <c>SRGBToLinear</c> (0.0773993808 = 1/12.92, 0.9478672986 = 1/1.055, 0.0521327014 = 0.055/1.055) is the
    /// formula of Godot's <c>srgb_to_linear</c> — so a hex decoded by three is what Godot decodes from bytes/255.
    /// </summary>
    [Fact]
    public void ThreeAndGodotDecodeSrgbAlike()
    {
        for (int b = 0; b <= 255; b++)
            Near(GodotSrgb.ToLinear(b / 255.0), LinearRgb.SrgbToLinear(b / 255.0), 1e-9);
    }

    /// <summary>
    /// Encode inverts Godot's decode: the renderer gets back the linear colour that went in. (Godot's own pair has a
    /// 2·10⁻⁹ seam at the knee — 0.0031308 encodes to 0.04044998 &lt; 0.04045, which decodes by the linear branch — hence
    /// 1e-8 there; everywhere else 1e-12.)
    /// </summary>
    [Fact]
    public void EncodeInvertsGodotsDecode()
    {
        foreach (double c in new[] { 0, 1e-4, 0.0031308, 0.0031309, 0.05, 0.2140, 0.5, 0.8879231179, 1, 1.7 })
        {
            var e = GodotSrgb.Encode(new LinearRgb(c, c, c));
            NearLin(new LinearRgb(c, c, c), e.Linear, Math.Abs(c - 0.0031308) < 1e-6 ? 1e-8 : 1e-12);
        }
    }

    /// <summary>
    /// An unblended hex reaches Godot as its bytes / 255: noon 0xfff2d8 → (1, 0.949020, 0.847059), moonlight 0x9fb4e0 →
    /// (0.623529, 0.705882, 0.878431). (three's encoder uses the exponent 0.41666, Godot's decode inverts 1/2.4 — using
    /// three's <c>getHex</c> here would be off in the 5th decimal, Encode is not.)
    /// </summary>
    [Fact]
    public void AnUnblendedHexArrivesAsItsBytes()
    {
        NearRgb(1, 242 / 255.0, 216 / 255.0, GodotSrgb.Encode(LinearRgb.FromSrgbHex(0xfff2d8)), 1e-9);
        NearRgb(159 / 255.0, 180 / 255.0, 224 / 255.0, GodotSrgb.Encode(LinearRgb.FromSrgbHex(0x9fb4e0)), 1e-9);
    }

    // ---- units --------------------------------------------------------------------------------------------------------

    /// <summary>Energy = I / π: noon sun 2.25 → 0.716197, hemi 1.55 → 0.493380, fill 0.55 → 0.175070.</summary>
    [Fact]
    public void EnergyIsTheThreeIntensityOverPi()
    {
        Near(0.716197243913529, StageLight.Energy(2.25), 1e-12);
        Near(0.493380323584987, StageLight.Energy(1.55), 1e-12);
        Near(0.175070437401286, StageLight.Energy(0.55), 1e-12);
        // The old stage factor 1/2.032 was π/2.032 = 1.546 × too bright.
        Near(1.546, Math.PI * (1 / (0.25 + 2 * Math.Sin(0.35 * Math.PI))), 1e-3);
    }

    // ---- the stage ----------------------------------------------------------------------------------------------------

    /// <summary>
    /// Before the first clock reading: the constructor's lights (sun 2.0, hemi 1.5, fill 0.5), the sun angle 0.35π, the sky
    /// 0x9fc7e8, the water untouched — and the ambience changes nothing (engine.applyAmbience returns without baseLights).
    /// </summary>
    [Fact]
    public void BeforeTheClockTheConstructorStageStands()
    {
        var f = StageLight.Compose(null, new AmbienceState(0.2, 1, 0.5, 0.5));
        Near(2.0 / Math.PI, f.Sun.Energy);
        Near(1.5 / Math.PI, f.Ambient.Energy);
        Near(1.5 / Math.PI, f.HemiPair.Energy);
        Near(0.5 / Math.PI, f.Fill.Energy);
        Near(0.35 * Math.PI, f.SunAngle);
        NearRgb(1, 242 / 255.0, 216 / 255.0, f.Sun.Color);
        NearRgb(159 / 255.0, 199 / 255.0, 232 / 255.0, f.Background);
        Assert.Null(f.WaterSky);
        Near(0, f.Night);
    }

    /// <summary>
    /// 9:00 — a = π/4, day = sin(π/4) = 0.707107 (> 0.45: the noon sun; > 0.35: the day sky); sun 0.25 + 2·0.707107 =
    /// 1.664214, hemi 0.35 + 1.2·0.707107 = 1.198528, fill 0.15 + 0.4·0.707107 = 0.432843 (each / π); offset
    /// (60·0.707107, 80·0.707107, 25) = (42.4264, 56.5685, 25), |·| = √5625 = 75; night max(0, 1 − 3·0.707) = 0.
    /// </summary>
    [Fact]
    public void NineOClock()
    {
        var f = StageLight.Compose(9, AmbienceState.Neutral);
        Near(1.6642135623730951 / Math.PI, f.Sun.Energy, 1e-12);
        Near(1.1985281374238571 / Math.PI, f.Ambient.Energy, 1e-12);
        Near(0.43284271247461906 / Math.PI, f.Fill.Energy, 1e-12);
        NearRgb(1, 242 / 255.0, 216 / 255.0, f.Sun.Color);
        NearRgb(159 / 255.0, 199 / 255.0, 232 / 255.0, f.Background);
        Assert.Equal((159 / 255.0, 199 / 255.0, 232 / 255.0), f.WaterSky);
        var off = StageLight.SunOffset(f.SunAngle);
        Near(42.42640687119285, off.X, 1e-12);
        Near(56.568542494923804, off.Y, 1e-12);
        Near(25, off.Z);
        Near(0, f.Night);
    }

    /// <summary>
    /// 22:00 — a = 16π/12 = 4π/3, sin = −0.866 → day 0: moonlight 0x9fb4e0, night sky 0x1a2340 (dusk = 0, the night
    /// branch with factor 0), sun 0.25, hemi 0.35, fill 0.15 (/π); offset (60·cos(4π/3), 80·0.08, 25) = (−30, 6.4, 25);
    /// night 1.
    /// </summary>
    [Fact]
    public void TenAtNight()
    {
        var f = StageLight.Compose(22, AmbienceState.Neutral);
        Near(0.25 / Math.PI, f.Sun.Energy, 1e-12);
        Near(0.35 / Math.PI, f.Ambient.Energy, 1e-12);
        Near(0.15 / Math.PI, f.Fill.Energy, 1e-12);
        NearRgb(159 / 255.0, 180 / 255.0, 224 / 255.0, f.Sun.Color);
        NearRgb(26 / 255.0, 35 / 255.0, 64 / 255.0, f.Background);
        Assert.Equal((26 / 255.0, 35 / 255.0, 64 / 255.0), f.WaterSky);
        var off = StageLight.SunOffset(f.SunAngle);
        Near(-30, off.X, 1e-9);
        Near(6.4, off.Y, 1e-12);
        Near(1, f.Night);
    }

    /// <summary>
    /// The room ambience multiplies the clock base: daylight 0.5 at noon halves every energy; the water's sky is
    /// getHex(sky · 0.5): 0x9f → linear 0.346704 · 0.5 = 0.173352 → sRGB 0.4549 → 116; 0xc7 → 0.571125 → 0.285562 → 146;
    /// 0xe8 → 0.806952 → 0.403476 → 170. The background stays the clock's sky. A tint (sRGB numbers, converted like
    /// <c>setRGB(..., SRGBColorSpace)</c>) multiplies the linear colours: red 1 keeps the noon sun's red at 1.
    /// </summary>
    [Fact]
    public void TheAmbienceMultipliesTheClockBase()
    {
        var f = StageLight.Compose(12, new AmbienceState(0.5, 1, 1, 1));
        Near(2.25 / Math.PI / 2, f.Sun.Energy, 1e-12);
        Near(1.55 / Math.PI / 2, f.Ambient.Energy, 1e-12);
        Near(0.55 / Math.PI / 2, f.Fill.Energy, 1e-12);
        Assert.Equal((116 / 255.0, 146 / 255.0, 170 / 255.0), f.WaterSky);
        NearRgb(159 / 255.0, 199 / 255.0, 232 / 255.0, f.Background);
        var tinted = StageLight.Compose(12, new AmbienceState(1, 1, 0.5, 0.5));
        Near(1, tinted.Sun.Color.R, 1e-9);
        // green: linear(0xf2) · linear(0.5) = 0.887923 · 0.214041 = 0.190052 → Godot sRGB 0.479...
        Near(0.8879231178819663 * LinearRgb.SrgbToLinear(0.5), tinted.Sun.Color.Linear.G, 1e-9);
    }

    /// <summary>
    /// The hemisphere: Godot's ambient + ± pair reproduces three's I · mix(G, S, ½ + ½·n.y) / π for every n.y — at noon
    /// n.y = 1 → I·S/π = 1.55·(0.737911, 0.854993, 1)/π = (0.364070, 0.421837, 0.493380); n.y = 0 → the mean;
    /// n.y = −1 → I·G/π = 1.55·(0.254152, 0.323470, 0.188021)/π = (0.125394, 0.159433, 0.092667).
    /// </summary>
    [Theory]
    [InlineData(1.0)]
    [InlineData(0.5)]
    [InlineData(0.0)]
    [InlineData(-0.3)]
    [InlineData(-1.0)]
    public void TheHemispherePairIsExactForLambert(double ny)
    {
        var amb = new AmbienceState(0.8, 1, 0.9, 0.7);
        var f = StageLight.Compose(12, amb);
        NearLin(StageLight.ThreeHemiDiffuse(1.55 * 0.8, StageLight.TintOf(amb), ny), StageLight.GodotHemiDiffuse(f, ny), 1e-12);
    }

    [Fact]
    public void TheHemisphereAtNoonByHand()
    {
        var f = StageLight.Compose(12, AmbienceState.Neutral);
        NearLin(new LinearRgb(0.36407047625422456, 0.4218365296574404, 0.4933803235848756), StageLight.GodotHemiDiffuse(f, 1), 1e-12);
        NearLin(new LinearRgb(0.2447320593948073, 0.2906345153642765, 0.29302369849669635), StageLight.GodotHemiDiffuse(f, 0), 1e-12);
        NearLin(new LinearRgb(0.12539364253539004, 0.15943250107111262, 0.09266707340851718), StageLight.GodotHemiDiffuse(f, -1), 1e-12);
    }

    /// <summary>The sun stands at snapShadowCentre(target, offset) + offset; the centre moves at most half a texel diagonal.</summary>
    [Fact]
    public void TheSunStandsOnTheSnappedTarget()
    {
        var (c, p) = StageLight.SunPlacement((10.03, 2, -7.5), Math.PI / 2);
        var off = StageLight.SunOffset(Math.PI / 2);
        Near(c.X + off.X, p.X, 1e-12);
        Near(c.Y + off.Y, p.Y, 1e-12);
        Near(c.Z + off.Z, p.Z, 1e-12);
        double moved = Math.Sqrt((c.X - 10.03) * (c.X - 10.03) + (c.Y - 2) * (c.Y - 2) + (c.Z + 7.5) * (c.Z + 7.5));
        Assert.True(moved <= ShadowSnap.TexelM() * Math.Sqrt(0.5) + 1e-12, $"{moved}");
    }

    // ---- the shadow fit -------------------------------------------------------------------------------------------------

    /// <summary>ceil((d + 70)/10)·10: 0.8 → 80, 5 → 80, 80 → 150, 81 → 160, 150 → 220.</summary>
    [Theory]
    [InlineData(0.8, 80)]
    [InlineData(5, 80)]
    [InlineData(80, 150)]
    [InlineData(81, 160)]
    [InlineData(150, 220)]
    public void ShadowMaxDistanceFollowsTheCamera(double dist, double want) => Near(want, ShadowFit.MaxDistanceM(dist));

    /// <summary>
    /// Godot's fit at max distance 150 (camera 80 m), 45° vertical FOV, 16:9, near 0.2: the far corners at
    /// (±150·tan 22.5°·16/9, ±150·tan 22.5°, 150) = (±110.4569, ±62.1320, 150), the centre at z = 75.1, the radius
    /// √(110.4569² + 62.1320² + 74.9²) = 147.2112, ×4096/4094 = 147.2831, texel 2r/4096 = 0.0719156 m — the browser's
    /// 140/2048 = 0.0683594 m within 5 %.
    /// </summary>
    [Fact]
    public void GodotsTexelAtTheBootZoomMatchesTheBrowser()
    {
        Near(0.07191558391985164, ShadowFit.TexelM(150, 45, 16.0 / 9, 0.2), 1e-12);
        Near(0.068359375, ShadowSnap.TexelM());
    }
}
