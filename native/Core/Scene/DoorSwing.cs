using System;

namespace AnimaNative.Scene;

/// <summary>
/// When a door prop stands open, and how far — a port of client3d/src/game/doorSwing.ts, checked against
/// shared/test-vectors/door_swing.json (hand derivations in client3d/scripts/smoke_door_swing.mjs). View state: the
/// rendered avatar drives proximity in every mode (Task 51 / E7-T6); absent avatars target 0.
/// </summary>
public static class DoorSwing
{
    /// <summary><c>DOOR_OPEN_RANGE</c>: metres from the threshold that count as "in front of it".</summary>
    public const double OpenRange = 2.0;
    /// <summary><c>DOOR_OPEN_DEG</c>.</summary>
    public const double OpenDeg = 85;
    /// <summary><c>DOOR_SWING_RATE</c>: radians per second.</summary>
    public const double SwingRate = 3.0;

    private const double OpenRad = OpenDeg * Math.PI / 180;

    /// <summary><c>doorDistance</c>: the distance while the door is on the avatar's storey, else +∞ ("nobody in front").</summary>
    public static double DoorDistance(int doorLevel, int avatarLevel, double distM)
        => doorLevel == avatarLevel ? distM : double.PositiveInfinity;

    /// <summary><c>doorTargetAngle</c>: shut when locked; open by swing·85° within the range (NaN/∞ are not near).</summary>
    public static double DoorTargetAngle(double distM, bool enterable, int swing)
    {
        if (!enterable) return 0;
        return distM <= OpenRange ? swing * OpenRad : 0;
    }

    /// <summary><c>easeAngle</c>: at most rate·dt towards the target, never past it.</summary>
    public static double EaseAngle(double current, double target, double dt, double rate = SwingRate)
    {
        double step = Math.Max(0, rate) * Math.Max(0, dt);
        double diff = target - current;
        if (double.IsNaN(diff)) return double.NaN;   // JS Math.sign(NaN) is NaN; C#'s Math.Sign would throw
        if (Math.Abs(diff) <= step) return target;
        return current + Math.Sign(diff) * step;
    }
}
