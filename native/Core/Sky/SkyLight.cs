using System;

namespace AnimaNative.Sky;

/// <summary>
/// A colour in three's LINEAR working space (Rec. 709 primaries, linear transfer) — what <c>new THREE.Color(hex)</c>
/// holds after its sRGB → linear conversion, and what <c>lerp</c> mixes. <see cref="FromSrgbHex"/> /
/// <see cref="ToSrgbHex"/> are three's <c>setHex</c> / <c>getHex</c> with its exact transfer constants
/// (ColorManagement.js <c>SRGBToLinear</c> / <c>LinearToSRGB</c>).
/// </summary>
public readonly record struct LinearRgb(double R, double G, double B)
{
    /// <summary><c>SRGBToLinear</c>.</summary>
    public static double SrgbToLinear(double c)
        => c < 0.04045 ? c * 0.0773993808 : Math.Pow(c * 0.9478672986 + 0.0521327014, 2.4);

    /// <summary><c>LinearToSRGB</c>.</summary>
    public static double LinearToSrgb(double c)
        => c < 0.0031308 ? c * 12.92 : 1.055 * Math.Pow(c, 0.41666) - 0.055;

    /// <summary><c>new THREE.Color(0xrrggbb)</c>: the sRGB bytes into the linear working space.</summary>
    public static LinearRgb FromSrgbHex(int hex)
        => new(SrgbToLinear(((hex >> 16) & 255) / 255.0), SrgbToLinear(((hex >> 8) & 255) / 255.0),
               SrgbToLinear((hex & 255) / 255.0));

    /// <summary><c>color.getHex()</c>: back to sRGB, each channel <c>Math.round(clamp(c·255, 0, 255))</c>.</summary>
    public int ToSrgbHex()
    {
        static int Byte(double c) => (int)Scatter.Js.Round(Math.Max(0, Math.Min(255, LinearToSrgb(c) * 255)));
        return Byte(R) * 65536 + Byte(G) * 256 + Byte(B);
    }

    /// <summary><c>color.lerp(to, alpha)</c>, channel by channel in the working space.</summary>
    public LinearRgb Lerp(LinearRgb to, double alpha)
        => new(R + (to.R - R) * alpha, G + (to.G - G) * alpha, B + (to.B - B) * alpha);
}

/// <summary>The clock's lights (<c>gameHourLights</c>): sun angle, colours (LINEAR working space) and intensities.</summary>
public readonly record struct HourLights(double SunAngle, LinearRgb Sun, LinearRgb Sky, double SunIntensity,
                                         double HemiIntensity, double FillIntensity);

/// <summary>
/// The game-clock lighting of the browser (<c>client3d/src/scene/skyLight.ts</c> <c>gameHourLights</c>, called by
/// <c>Engine.setGameHour</c>). The colours stay in three's linear working space — a consumer that hands them to
/// Godot must treat them as linear (Godot's <c>Color</c> literals are sRGB). The intensities are three's
/// (physically based lights, divided by π in its BRDF); the Godot energy mapping is the consumer's.
/// </summary>
public static class SkyLight
{
    private static readonly LinearRgb Noon = LinearRgb.FromSrgbHex(0xfff2d8);
    private static readonly LinearRgb Warm = LinearRgb.FromSrgbHex(0xffb066);
    private static readonly LinearRgb Moon = LinearRgb.FromSrgbHex(0x9fb4e0);
    private static readonly LinearRgb SkyDay = LinearRgb.FromSrgbHex(0x9fc7e8);
    private static readonly LinearRgb SkyDusk = LinearRgb.FromSrgbHex(0xe89a63);
    private static readonly LinearRgb SkyNight = LinearRgb.FromSrgbHex(0x1a2340);

    private static double Clamp(double v, double lo, double hi) => Math.Max(lo, Math.Min(hi, v));

    /// <summary><c>THREE.MathUtils.smoothstep(x, min, max)</c>.</summary>
    private static double Smoothstep(double x, double min, double max)
    {
        if (x <= min) return 0;
        if (x >= max) return 1;
        x = (x - min) / (max - min);
        return x * x * (3 - 2 * x);
    }

    /// <summary>
    /// <c>gameHourLights(hour)</c>: the sun arc (6:00 east = 0, 12:00 zenith = π/2, 18:00 west = π), the sun colour
    /// (warm → noon by smoothstep(day, 0.05, 0.45), moonlight at night), the sky (day, dusk blend between day 0.15 and
    /// 0.35, night → dusk below), and the three intensities.
    /// </summary>
    public static HourLights GameHourLights(double hour)
    {
        double h = ((hour % 24) + 24) % 24;
        double sunAngle = (h - 6) / 12 * Math.PI;
        double day = Clamp(Math.Sin(sunAngle), 0, 1);
        double dusk = Clamp(1 - Math.Abs(h - 12) / 6, 0, 1);
        var sun = day > 0.05 ? Warm.Lerp(Noon, Smoothstep(day, 0.05, 0.45)) : Moon;
        var sky = day > 0.15
            ? SkyDay
            : SkyNight.Lerp(SkyDusk, Clamp(day / 0.15, 0, 1) * (dusk > 0.05 ? 1 : 0.3));
        if (day > 0.15 && day < 0.35) sky = sky.Lerp(SkyDusk, (0.35 - day) / 0.2);
        return new HourLights(sunAngle, sun, sky, 0.25 + day * 2, 0.35 + day * 1.2, 0.15 + day * 0.4);
    }
}
