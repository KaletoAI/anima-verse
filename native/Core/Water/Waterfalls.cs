using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Water;

/// <summary>One detected fall (<c>Waterfall</c>): arc midpoint, chord direction, stream width, top/bottom level, chord length.</summary>
public readonly record struct Waterfall(double X, double Z, double DirX, double DirZ, double Width, double TopY,
                                        double BottomY, double ChordM);

/// <summary>The curtain quad of a fall (<c>waterfallQuad</c>): lip-left, lip-right, foot-left, foot-right as x, y, z
/// triples, and the foot's centre where the foam disc lies.</summary>
public sealed record WaterfallQuad(double[] Positions, (double X, double Z) Bottom);

/// <summary>
/// Waterfalls of a drawn water stroke (<c>packages/scene-render/src/waterfall.ts</c> detection,
/// <c>client3d/src/scene/waterfall.ts</c> <c>waterfallQuad</c>): a run of axis segments steeper than 0.5 that drops
/// more than 1 m is one fall, standing at its arc midpoint, leaning 0.3 × its height down the chord.
/// </summary>
public static class Waterfalls
{
    /// <summary><c>WATERFALL_MIN_DROP_M</c>, <c>WATERFALL_MIN_SLOPE</c>, <c>WATERFALL_LEAN</c> (client).</summary>
    public const double MinDropM = 1.0, MinSlope = 0.5, Lean = 0.3;

    private static JsonElement? Field(JsonElement? o, string name)
        => o is { ValueKind: JsonValueKind.Object } e && e.TryGetProperty(name, out var v) ? v : null;

    /// <summary><c>strokeWidthM(meta)</c>: <c>meta.stroke.width_m</c> as a positive finite number (JS <c>Number()</c>), else null.</summary>
    public static double? StrokeWidthM(JsonElement? meta)
    {
        if (Field(meta, "stroke") is not { ValueKind: JsonValueKind.Object } stroke) return null;
        return WaterProfile.Finite(Field(stroke, "width_m")) is { } w && w > 0 ? w : null;
    }

    /// <summary>
    /// <c>waterfallsFrom(profile, widthM)</c>: <paramref name="profile"/> is <c>meta.water_profile</c> (its
    /// <c>axis</c>, ≥ 3 knots of finite numbers), <paramref name="widthM"/> the stroke width as the payload carries it;
    /// no width or a malformed axis = no falls.
    /// </summary>
    public static List<Waterfall> From(JsonElement? profile, JsonElement? widthM)
    {
        var falls = new List<Waterfall>();
        var axis = Field(profile, "axis");
        double? width = WaterProfile.Finite(widthM);
        if (axis is not { ValueKind: JsonValueKind.Array } a || a.GetArrayLength() < 3) return falls;
        if (width is not { } w || w <= 0) return falls;
        var knots = new List<WaterKnot>();
        foreach (var raw in a.EnumerateArray())
        {
            if (raw.ValueKind != JsonValueKind.Array) return falls;
            JsonElement? At(int i) => i < raw.GetArrayLength() ? raw[i] : null;
            if (WaterProfile.Finite(At(0)) is not { } x || WaterProfile.Finite(At(1)) is not { } z
                || WaterProfile.Finite(At(2)) is not { } s || WaterProfile.Finite(At(3)) is not { } level) return falls;
            knots.Add(new WaterKnot(x, z, s, level));
        }
        void Close(int lo, int hi)
        {
            if (RunToFall(knots, lo, hi, w) is { } fall) falls.Add(fall);
        }
        int start = -1;
        for (int i = 1; i < knots.Count; i++)
        {
            if (IsSteep(knots[i - 1], knots[i]))
            {
                if (start < 0) start = i - 1;
                continue;
            }
            if (start >= 0) Close(start, i - 1);
            start = -1;
        }
        if (start >= 0) Close(start, knots.Count - 1);
        return falls;
    }

    private static bool IsSteep(WaterKnot a, WaterKnot b)
    {
        double run = b.S - a.S;
        if (!(run > 0)) return false;
        return (a.Level - b.Level) / run > MinSlope;
    }

    private static Waterfall? RunToFall(List<WaterKnot> knots, int lo, int hi, double width)
    {
        var top = knots[lo];
        var bottom = knots[hi];
        if (!(top.Level - bottom.Level > MinDropM)) return null;
        double dx = bottom.X - top.X, dz = bottom.Z - top.Z;
        double len = Math.Sqrt(dx * dx + dz * dz);
        if (!(len > 1e-9)) return null;
        var (x, z) = ArcMidpoint(knots, lo, hi);
        return new Waterfall(x, z, dx / len, dz / len, width, top.Level, bottom.Level, len);
    }

    private static (double X, double Z) ArcMidpoint(List<WaterKnot> knots, int lo, int hi)
    {
        var a0 = knots[lo];
        var b0 = knots[hi];
        if (hi - lo == 1) return ((a0.X + b0.X) * 0.5, (a0.Z + b0.Z) * 0.5);
        double sMid = (a0.S + b0.S) * 0.5;
        int i = lo + 1;
        while (i < hi && knots[i].S < sMid) i++;
        var a = knots[i - 1];
        var b = knots[i];
        double span = b.S - a.S;
        double u = span > 1e-9 ? (sMid - a.S) / span : 0;
        return (a.X + (b.X - a.X) * u, a.Z + (b.Z - a.Z) * u);
    }

    // ── The look of the curtain and the foam (client3d/src/scene/waterfall.ts, view constants) ──
    /// <summary><c>WATERFALL_WAVE_M</c>: metres of curtain per tile of the wave normal map.</summary>
    public const double WaveM = 2.5;
    /// <summary><c>WATERFALL_G</c>: free fall, m/s².</summary>
    public const double G = 9.81;
    /// <summary><c>WATERFALL_WHITE_TOP</c>: how white the sheet already is at the lip.</summary>
    public const double WhiteTop = 0.35;
    /// <summary><c>WATERFALL_OPACITY</c>: the curtain material's own opacity.</summary>
    public const double Opacity = 0.8;
    /// <summary><c>WATERFALL_TINT</c> 0xc2dcea (sRGB; three decodes the hex to linear).</summary>
    public const string Tint = "#c2dcea";
    /// <summary><c>WATERFALL_FOAM_RADIUS_PER_M</c>, <c>WATERFALL_FOAM_LIFT_M</c>, <c>WATERFALL_FOAM_SEGMENTS</c>.</summary>
    public const double FoamRadiusPerM = 0.5, FoamLiftM = 0.05;
    public const int FoamSegments = 24;

    /// <summary><c>fallSpeedMs(h)</c>: the mean speed of water falling h metres from rest, √(g·h/2).</summary>
    public static double FallSpeedMs(double heightM) => Math.Sqrt(G * Math.Max(heightM, 0) * 0.5);

    /// <summary><c>foamRadius(fall, h)</c>: half a metre per metre of fall, never narrower than half the stream.</summary>
    public static double FoamRadius(Waterfall fall, double heightM) => Math.Max(fall.Width * 0.5, FoamRadiusPerM * heightM);

    /// <summary>The curtain shader's numbers (<c>patchCurtain</c>): the scroll in wave-map tiles per second and the tiles
    /// across / down the sheet.</summary>
    public static (double SpeedTilesS, double TilesX, double TilesY) Curtain(Waterfall fall)
    {
        double h = fall.TopY - fall.BottomY;
        return (FallSpeedMs(h) / WaveM, fall.Width / WaveM, h / WaveM);
    }

    /// <summary>The curtain's uv per <see cref="WaterfallQuad"/> corner: u across the stream, v 1 at the lip, 0 at the foot;
    /// its two triangles (three's index order, counter-clockwise; drawn double-sided).</summary>
    public static readonly double[] CurtainUv = { 0, 1, 1, 1, 0, 0, 1, 0 };
    public static readonly int[] CurtainIndex = { 0, 2, 1, 2, 3, 1 };

    /// <summary>
    /// The foam disc at the foot (<c>CircleGeometry(r, 24)</c> turned −90° about x, translated to the foot + 5 cm): the
    /// centre first with alpha <see cref="WaterShade.FoamStrength"/>, then the 25 rim points (the first and the last
    /// coincide) with alpha 0, as (x, y, z, alpha); the triangles (rim i, rim i + 1, centre) counter-clockwise from above.
    /// Null without a quad.
    /// </summary>
    public static (double[] Vertices, int[] Index)? FoamDisc(Waterfall fall)
    {
        if (Quad(fall) is not { } q) return null;
        double h = fall.TopY - fall.BottomY;
        double r = FoamRadius(fall, h);
        double y = fall.BottomY + FoamLiftM;
        var v = new List<double> { q.Bottom.X, y, q.Bottom.Z, WaterShade.FoamStrength };
        for (int s = 0; s <= FoamSegments; s++)
        {
            double a = (double)s / FoamSegments * Math.PI * 2;
            // CircleGeometry's (r cos a, r sin a, 0), turned −90° about x → (r cos a, 0, −r sin a).
            v.AddRange(new[] { q.Bottom.X + r * Math.Cos(a), y, q.Bottom.Z - r * Math.Sin(a), 0 });
        }
        var idx = new List<int>();
        for (int i = 1; i <= FoamSegments; i++) idx.AddRange(new[] { i, i + 1, 0 });
        return (v.ToArray(), idx.ToArray());
    }

    /// <summary><c>waterfallQuad(fall)</c>: the curtain from the lip to the leaning foot; no height or width = null.</summary>
    public static WaterfallQuad? Quad(Waterfall fall)
    {
        double height = fall.TopY - fall.BottomY;
        if (!(height > 0) || !(fall.Width > 0)) return null;
        double acrossX = fall.DirZ, acrossZ = -fall.DirX;
        double halfW = fall.Width * 0.5;
        double halfRun = Math.Max(fall.ChordM, 0) * 0.5;
        double lean = Lean * height;
        double topX = fall.X - fall.DirX * halfRun, topZ = fall.Z - fall.DirZ * halfRun;
        double botX = fall.X + fall.DirX * (halfRun + lean), botZ = fall.Z + fall.DirZ * (halfRun + lean);
        return new WaterfallQuad(new[]
        {
            topX - acrossX * halfW, fall.TopY, topZ - acrossZ * halfW,
            topX + acrossX * halfW, fall.TopY, topZ + acrossZ * halfW,
            botX - acrossX * halfW, fall.BottomY, botZ - acrossZ * halfW,
            botX + acrossX * halfW, fall.BottomY, botZ + acrossZ * halfW,
        }, (botX, botZ));
    }
}
