using System;
using AnimaNative.Overview;

namespace AnimaNative.Scene;

/// <summary>Task 53 / E7-T8: one frame's camera-to-chest capsule, matching occlusion.ts OccState.</summary>
public readonly record struct OcclusionState(Vec3 A, Vec3 B, double Radius, double Strength);

/// <summary>
/// Task 53 / E7-T8: Godot-free occlusion.ts arithmetic and its fragment probe, pinned by occlusion.json.
/// Only embodied third person enables the corridor; gates and radius are world metres, never avatar-scaled.
/// </summary>
public static class Occlusion
{
    public const double RadiusM = 1.5, GateM = 25, FadeFromM = 20, CameraClearM = .5, ChestM = 1.2;

    /// <summary>occlusionUniforms: gate distance and clearance use the SAME chest endpoint; close cameras collapse.</summary>
    public static OcclusionState Uniforms(Vec3 camera, Vec3? avatar, bool embodied)
    {
        var b = avatar is { } p ? new Vec3(p.X, p.Y + ChestM, p.Z) : default;
        if (!embodied || avatar is null) return new(b, b, RadiusM, 0);
        double dx = b.X-camera.X, dy = b.Y-camera.Y, dz = b.Z-camera.Z;
        double d = Math.Sqrt(dx*dx + dy*dy + dz*dz);
        var a = d > CameraClearM ? new Vec3(camera.X+dx/d*CameraClearM, camera.Y+dy/d*CameraClearM, camera.Z+dz/d*CameraClearM) : b;
        return new(a, b, RadiusM, Math.Clamp((GateM-d)/(GateM-FadeFromM), 0, 1));
    }

    /// <summary>CPU twin of the shader: clamped segment distance, round caps, smooth outer half-radius, tile gate.</summary>
    public static double Hide(OcclusionState s, Vec3 p, double gate = 1)
    {
        double x = s.B.X-s.A.X, y = s.B.Y-s.A.Y, z = s.B.Z-s.A.Z;
        double t = Math.Clamp(((p.X-s.A.X)*x+(p.Y-s.A.Y)*y+(p.Z-s.A.Z)*z)/Math.Max(x*x+y*y+z*z, 1e-6), 0, 1);
        double dx = p.X-s.A.X-x*t, dy = p.Y-s.A.Y-y*t, dz = p.Z-s.A.Z-z*t;
        double rim = Math.Clamp((Math.Sqrt(dx*dx+dy*dy+dz*dz)-s.Radius*.5)/(s.Radius*.5), 0, 1);
        return s.Strength * gate * (1-rim*rim*(3-2*rim));
    }

    /// <summary>The fixed 4×4 screen-space Bayer threshold; discard only when hide is STRICTLY greater.</summary>
    public static double Threshold(double x, double y)
    {
        x = Math.Floor(x)%4; y = Math.Floor(y)%4;
        return (Math.Abs(y%2-x%2)*8+y%2*4+Math.Abs(Math.Floor(y/2)-Math.Floor(x/2))*2+Math.Floor(y/2))/16;
    }
}
