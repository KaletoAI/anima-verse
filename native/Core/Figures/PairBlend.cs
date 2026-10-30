using System;

namespace AnimaNative.Figures;

public readonly record struct PairPose(double X, double Y, double Z, double Yaw);

/// <summary>Pair entry view maths, mirrored in client3d/src/game/pairBlend.ts. Always real seconds.</summary>
public static class PairBlend
{
    public const double BlendS = 0.4;

    /// <summary>Blend the adoption pose toward this frame's moving root, taking the shortest yaw.</summary>
    public static (PairPose Pose, double Weight) Sample(PairPose from, PairPose target, double elapsedS)
    {
        double u = Math.Clamp(elapsedS / BlendS, 0, 1), weight = u * u * (3 - 2 * u);
        double delta = Math.Atan2(Math.Sin(target.Yaw - from.Yaw), Math.Cos(target.Yaw - from.Yaw));
        return (new(from.X + (target.X - from.X) * weight, from.Y + (target.Y - from.Y) * weight,
                    from.Z + (target.Z - from.Z) * weight, from.Yaw + delta * weight), weight);
    }
}
