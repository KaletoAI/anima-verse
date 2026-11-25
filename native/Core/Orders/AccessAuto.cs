using System;

namespace AnimaNative.Orders;

/// <summary>
/// The automatic access point of a furniture slot (docs/schnittstellen-3d.md, "Access is automatic for each chosen
/// marker slot"): the body slot minus the entry clip's root travel, turned by the facing and scaled to the figure —
/// the client's twin of app/core/room_stand.py <c>bridge_offset</c> / <c>bridge_scale</c> (vector
/// shared/test-vectors/access_auto.json, derived in scripts/smoke_access_auto.py).
/// </summary>
public static class AccessAuto
{
    /// <summary>
    /// <paramref name="slot"/> minus the clip travel (<paramref name="travelDx"/> = the figure's left,
    /// <paramref name="travelDz"/> = forward, metres on the reference rig) turned by <c>slot.YawDeg</c> (compass: 0 =
    /// +z, 90 = +x) and scaled by <c>(heightCm / 100) / clipRefHeightM</c> (1 when either is unknown or not positive).
    /// Y and the yaw are carried over: pass the slot at floor height, the figure finishes the clip facing the slot.
    /// </summary>
    public static OrderPoint Compute(OrderPoint slot, double travelDx, double travelDz, double? heightCm, double? clipRefHeightM)
    {
        double scale = Scale(heightCm, clipRefHeightM);
        double a = slot.YawDeg * Math.PI / 180.0;
        double tx = travelDx * scale, tz = travelDz * scale;
        double dx = tx * Math.Cos(a) + tz * Math.Sin(a);
        double dz = -tx * Math.Sin(a) + tz * Math.Cos(a);
        return new OrderPoint(slot.X - dx, slot.Y, slot.Z - dz, slot.YawDeg);
    }

    /// <summary><c>room_stand.bridge_scale</c>: figure size over the clip's reference rig; 1.0 when either is unknown.</summary>
    public static double Scale(double? heightCm, double? clipRefHeightM)
    {
        if (heightCm is not double h || clipRefHeightM is not double r) return 1.0;
        if (!double.IsFinite(h) || !double.IsFinite(r) || h <= 0 || r <= 0) return 1.0;
        return h / 100.0 / r;
    }
}
