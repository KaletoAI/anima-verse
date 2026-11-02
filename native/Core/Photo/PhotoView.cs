using System;
using System.Collections.Generic;
using AnimaNative.Overview;

namespace AnimaNative.Photo;

public sealed record PhotoSubject(string Name, Vec3 Head);
public sealed record PhotoVisible(string name, double screen_x, double screen_y, double depth_m);
public sealed record PhotoCamera(double pitch_deg, double height_m, double fov_deg);

/// <summary>Browser photoView.ts framing in an orthonormal camera basis; wire names match PhotoView.</summary>
public sealed record PhotoView(IReadOnlyList<PhotoVisible> visible, PhotoCamera camera)
{
    public static PhotoView Build(Vec3 position, Vec3 forward, Vec3 right, Vec3 up,
        double fov, double aspect, double near, double far, IEnumerable<PhotoSubject> subjects, double floorY)
    {
        var visible = new List<PhotoVisible>();
        double tan = Math.Tan(fov * Math.PI / 360);
        foreach (var subject in subjects)
        {
            var h = subject.Head;
            var p = new Vec3(h.X-position.X, h.Y-position.Y, h.Z-position.Z);
            double Dot(Vec3 v) => p.X*v.X + p.Y*v.Y + p.Z*v.Z;
            double z = Dot(forward);
            if (z <= 0) continue;
            double nx = Dot(right)/(z*tan*aspect), ny = Dot(up)/(z*tan);
            double nz = (far+near)/(far-near) - 2*far*near/((far-near)*z);
            if (!double.IsFinite(nx+ny+nz) || Math.Max(Math.Max(Math.Abs(nx),Math.Abs(ny)),Math.Abs(nz)) > 1+1e-9) continue;
            visible.Add(new(subject.Name, Math.Clamp((nx+1)/2,0,1), Math.Clamp((1-ny)/2,0,1),
                Math.Sqrt(p.X*p.X+p.Y*p.Y+p.Z*p.Z)));
        }
        return new(visible, new(Math.Asin(Math.Clamp(forward.Y,-1,1))*180/Math.PI, Math.Max(0,position.Y-floorY),fov));
    }
}
