using System;
using System.Collections.Generic;
using AnimaNative.Overview;

namespace AnimaNative.Photo;

public sealed record PhotoSubject(string Name, Vec3 Head);
public sealed record PhotoVisible(string name, double screen_x, double screen_y, double depth_m);
public sealed record PhotoCamera(double pitch_deg, double height_m, double fov_deg);
public readonly record struct PhotoRect(int X,int Y,int Width,int Height);

/// <summary>Browser photoView.ts framing in an orthonormal camera basis; wire names match PhotoView.</summary>
public sealed record PhotoView(IReadOnlyList<PhotoVisible> visible, PhotoCamera camera)
{
    public PhotoView Crop(PhotoRect rect,int width,int height)
    {
        if (rect==new PhotoRect(0,0,width,height)) return this;
        double left=(double)rect.X/width, top=(double)rect.Y/height;
        double w=(double)rect.Width/width, h=(double)rect.Height/height;
        double tan=Math.Tan(camera.fov_deg*Math.PI/360), pitch=camera.pitch_deg*Math.PI/180;
        double rx=(2*(left+w/2)-1)*width/height*tan, ry=(1-2*(top+h/2))*tan;
        var subjects=new List<PhotoVisible>();
        foreach (var v in visible)
            if (v.screen_x>=left-1e-9 && v.screen_x<=left+w+1e-9 && v.screen_y>=top-1e-9 && v.screen_y<=top+h+1e-9)
                subjects.Add(v with { screen_x=Math.Clamp((v.screen_x-left)/w,0,1), screen_y=Math.Clamp((v.screen_y-top)/h,0,1) });
        return new(subjects,camera with { fov_deg=2*Math.Atan(tan*h)*180/Math.PI,
            pitch_deg=Math.Asin(Math.Clamp((Math.Sin(pitch)+ry*Math.Cos(pitch))/Math.Sqrt(1+rx*rx+ry*ry),-1,1))*180/Math.PI });
    }

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
