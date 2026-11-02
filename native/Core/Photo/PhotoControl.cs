using System;
using System.Collections.Generic;
using AnimaNative.Overview;

namespace AnimaNative.Photo;

/// <summary>Engine photo camera controls: real time, YXZ look and normalized view-plane flight.</summary>
public sealed class PhotoControl
{
    public bool Active { get; private set; }
    public double Speed { get; private set; } = 4;
    public double Yaw { get; private set; }
    public double Pitch { get; private set; }
    public Vec3 Position { get; private set; }
    private readonly HashSet<string> _keys = new();
    public IReadOnlySet<string> Keys => _keys;
    public void Enter(Vec3 position, double yaw, double pitch)
    { Position=position; Yaw=yaw; Pitch=pitch; Active=true; ReleaseKeys(); }
    public void Leave() { Active=false; ReleaseKeys(); }
    public void ReleaseKeys() => _keys.Clear();
    public void Key(string key, bool pressed) { if (pressed && Active) _keys.Add(key); else _keys.Remove(key); }
    public void Wheel(double deltaY) => Speed=Math.Clamp(Speed*Math.Exp(-deltaY*.0012),.5,20);
    public void Look(double dx,double dy)
    { Yaw-=dx*.005; Pitch=Math.Clamp(Pitch-dy*.005,-Math.PI*.49,Math.PI*.49); }
    public void Step(double delta)
    {
        if (!Active) return;
        int Axis(string plus,string minus) => (_keys.Contains(plus)?1:0)-(_keys.Contains(minus)?1:0);
        int f=Axis("w","s"), r=Axis("d","a"), y=Axis("e","q");
        double x=-Math.Sin(Yaw)*Math.Cos(Pitch)*f+Math.Cos(Yaw)*r;
        double dy=Math.Sin(Pitch)*f+y;
        double z=-Math.Cos(Yaw)*Math.Cos(Pitch)*f-Math.Sin(Yaw)*r;
        double length=Math.Sqrt(x*x+dy*dy+z*z);
        if (length==0) return;
        double step=Speed*(_keys.Contains("shift")?3:1)*Math.Clamp(delta,0,CameraMath.MaxFrameDt)/length;
        Position=new(Position.X+x*step,Position.Y+dy*step,Position.Z+z*step);
    }
}
