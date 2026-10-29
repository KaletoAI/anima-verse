using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;

namespace AnimaNative.Audio;

/// <summary>Task 59 / E8-T2: browser audio.ts gain automation, evaluated on the caller's clock.
/// Equal power means eight LINEAR segments through sin/cos knots, never the continuous curve.
/// Durations are seconds and volumes are linear amplitude (not decibels).</summary>
public static class AudioMath
{
    public const double RampS = .05, DefaultCrossfadeS = 3, PreloadS = 6;
    public const int FadeSteps = 8;
    public static double ClampVolume(double value) => Math.Clamp(value, 0, 1);
    public static double EqualPowerGainAt(double begin, double duration, bool up, double now)
    {
        double p = Math.Clamp((now - begin) / duration, 0, 1) * FadeSteps;
        int i = Math.Min((int)p, FadeSteps - 1);
        double Knot(int k) => up ? Math.Sin(k * Math.PI / (2 * FadeSteps)) : Math.Cos(k * Math.PI / (2 * FadeSteps));
        return Knot(i) + (Knot(i + 1) - Knot(i)) * (p - i);
    }
    public static TrackTiming Schedule(double requested, double now, double duration, double crossfade = DefaultCrossfadeS)
    {
        double begin = Math.Max(requested, now), fade = Math.Min(Math.Max(0, crossfade), duration / 3);
        double seam = begin + duration - fade;
        return new(begin, fade, seam, Math.Max(0, seam - PreloadS - now));
    }
    public static double StopRampEnd(double now, double fade) => now + Math.Max(RampS, fade);
    public static double StopGainAt(double gain, double begin, double fade, double now)
        => gain * (1 - Math.Clamp((now - begin) / Math.Max(RampS, fade), 0, 1));
    public static double RampGainAt(double gain, double target, double begin, double now)
        => gain + (ClampVolume(target) - gain) * Math.Clamp((now - begin) / RampS, 0, 1);
    public static string[] Shuffle(IEnumerable<string> urls, string seed)
    {
        var result = urls.ToArray();
        var random = ScatterMath.SeededRandom(seed);
        for (int i = result.Length - 1; i > 0; i--)
        {
            int j = (int)Math.Floor(random() * (i + 1));
            (result[i], result[j]) = (result[j], result[i]);
        }
        return result;
    }
}

/// <summary>Task 59: one decoded track's timing; wake is relative to the scheduling call.</summary>
public readonly record struct TrackTiming(double Begin, double Fade, double Seam, double WakeInS);
