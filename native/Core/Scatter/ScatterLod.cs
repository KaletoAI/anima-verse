using System;

namespace AnimaNative.Scatter;

/// <summary>The three detail distances (<c>ScatterLodCfg</c>).</summary>
public readonly record struct ScatterLodCfg(double NearM, double FarM, double CullM);

/// <summary>The horizontal view cone of one LOD pass (<c>ScatterViewCone</c>).</summary>
public readonly record struct ScatterViewCone(double FwdX, double FwdZ, double CosHalf);

/// <summary>
/// Port of <c>client3d/src/scene/scatterLod.ts</c> — the per-instance LOD of the scatter and the
/// undergrowth constants, with its DEFAULT config (<c>SCATTER_LOD_DEFAULTS</c> = 35 / 45 / 120 m).
/// Task 38 (E4-T3) adds the vectored impostor half beyond the mesh cull line.
/// </summary>
public static partial class ScatterLod
{
    public const double TierNear = 35, TierFar = 45, CullFar = 120;
    public const double MinShare = 0.25;
    public const double ModelHeightM = 2.0;
    public const double SwayFactorDefault = 1;
    public const double GroundOffsetLimitM = 5;
    public const double UnhideFactor = 0.92;
    public const double ConeMarginRad = 30 * Math.PI / 180;
    public const double ConeNearM = 40;
    public static readonly ScatterLodCfg Defaults = new(TierNear, TierFar, CullFar);

    public static double TargetH(double? propH) => propH is double h && h > 0 ? h : ModelHeightM;

    public static double GroundOffset(double? offsetM)
        => offsetM is double o && double.IsFinite(o) ? Math.Min(Math.Max(o, -GroundOffsetLimitM), GroundOffsetLimitM) : 0;

    public static double Sway(double swayM, double? factor)
    {
        if (!(swayM > 0)) return 0;
        double clamped = factor is double f && double.IsFinite(f) ? Math.Min(Math.Max(f, 0), 1) : SwayFactorDefault;
        return Js.Round(swayM * clamped * 100) / 100;
    }

    /// <summary>0 = full, 1 = low, 2 = hidden; hysteresis inside near..far, un-hide below 0.92·cull.</summary>
    public static byte InstanceTier(double distM, byte prev, ScatterLodCfg cfg)
    {
        if (!(distM <= cfg.CullM)) return 2;
        byte held = prev;
        if (prev == 2)
        {
            if (!(distM < UnhideFactor * cfg.CullM)) return 2;
            held = 1;
        }
        if (distM < cfg.NearM) return 0;
        if (distM > cfg.FarM) return 1;
        return held;
    }

    public static double InstanceShare(double distM, ScatterLodCfg cfg)
    {
        if (!(distM <= cfg.CullM)) return 0;
        if (distM <= cfg.FarM) return 1;
        double t = (distM - cfg.FarM) / (cfg.CullM - cfg.FarM);
        return 1 - t * (1 - MinShare);
    }

    /// <summary><c>instanceHash</c>: a stable [0, 1) per index (imul/xorshift on uint32 bits).</summary>
    public static double InstanceHash(int index)
    {
        uint h = unchecked((uint)index * 2654435761u);
        h = unchecked((h ^ (h >> 15)) * 2246822507u);
        h = unchecked((h ^ (h >> 13)) * 3266489909u);
        h ^= h >> 16;
        return h / 4294967296.0;
    }

    public static bool InstanceVisible(int index, double distM, ScatterLodCfg cfg)
    {
        double share = InstanceShare(distM, cfg);
        if (share >= 1) return true;
        if (share <= 0) return false;
        return InstanceHash(index) < share;
    }

    public static double HorizontalFovRad(double vFovDeg, double aspect)
    {
        if (!(vFovDeg > 0) || !(vFovDeg < 180) || !(aspect > 0) || !double.IsFinite(aspect)) return double.NaN;
        return 2 * Math.Atan(Math.Tan((vFovDeg * Math.PI) / 360) * aspect);
    }

    public static ScatterViewCone ViewCone(double fwdX, double fwdZ, double hfovRad)
    {
        double len = Math.Sqrt(fwdX * fwdX + fwdZ * fwdZ);
        if (!(len > 0) || !double.IsFinite(hfovRad) || !(hfovRad > 0)) return new ScatterViewCone(0, 1, -1);
        double half = hfovRad / 2 + ConeMarginRad;
        if (half >= Math.PI) return new ScatterViewCone(fwdX / len, fwdZ / len, -1);
        return new ScatterViewCone(fwdX / len, fwdZ / len, Math.Cos(half));
    }

    public static bool InViewCone(double dx, double dz, double fwdX, double fwdZ, double cosHalf)
    {
        double d2 = dx * dx + dz * dz;
        if (!(d2 > ConeNearM * ConeNearM)) return true;
        double len = Math.Sqrt(d2);
        return dx * fwdX + dz * fwdZ >= cosHalf * len;
    }

    // ---- undergrowth (section VI of scatterLod.ts) ----------------------------------------------

    public const double UgDensityPerM2 = 0.80;
    public const double UgCellM = 64;
    public const double UgCellRadiusM = 128;
    public const int UgMaxPerCell = 8000;
    public const double UgFadeM = 30;
    public const double UgCullM = 60;
    public const double UgMinShare = 0;
    public const double UgHMin = 0.24, UgHMax = 0.42;

    public static double UgDensityPer100m2(double value)
    {
        if (!double.IsFinite(value) || value <= 0) return 0;
        return UgDensityPerM2 * 100 * Math.Min(value, 1);
    }

    public static int UgCellCount(double value)
    {
        double density = UgDensityPer100m2(value);
        if (!(density > 0)) return 0;
        double cellM2 = UgCellM * UgCellM;
        return (int)Math.Min(Js.Round((cellM2 / 100) * density), UgMaxPerCell);
    }

    public static double UgHeight(double yaw)
    {
        double t = yaw / (Math.PI * 2);
        double frac = double.IsFinite(t) ? t - Math.Floor(t) : 0;
        return UgHMin + (UgHMax - UgHMin) * frac;
    }

    public static double UgShare(double distM)
    {
        if (!(distM <= UgCullM)) return 0;
        if (distM <= UgFadeM) return 1;
        double t = (distM - UgFadeM) / (UgCullM - UgFadeM);
        return 1 - t * (1 - UgMinShare);
    }

    public static bool UgVisible(int index, double distM)
    {
        double share = UgShare(distM);
        if (share >= 1) return true;
        if (share <= 0) return false;
        return InstanceHash(index) < share;
    }
}
