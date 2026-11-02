using System;
using System.Collections.Generic;
using AnimaNative.Overview;

namespace AnimaNative.Photo;

/// <summary>Engine photo camera controls: real time, YXZ look and normalized view-plane flight.</summary>
public sealed class PhotoControl
{
    public bool Active { get; private set; }
    public bool Selecting { get; private set; }
    public double Speed { get; private set; } = 4;
    public double Yaw { get; private set; }
    public double Pitch { get; private set; }
    public Vec3 Position { get; private set; }
    private readonly HashSet<string> _keys = new();
    public IReadOnlySet<string> Keys => _keys;
    public void Enter(Vec3 position, double yaw, double pitch)
    { Position=position; Yaw=yaw; Pitch=pitch; Active=true; SetSelecting(false); }
    public void Leave() { Active=false; SetSelecting(false); }
    public void SetSelecting(bool value) { Selecting=value; ReleaseKeys(); }
    public void ReleaseKeys() => _keys.Clear();
    public void Key(string key, bool pressed) { if (pressed && Active && !Selecting) _keys.Add(key); else _keys.Remove(key); }
    public void Wheel(double deltaY) { if (!Selecting) Speed=Math.Clamp(Speed*Math.Exp(-deltaY*.0012),.5,20); }
    public void Look(double dx,double dy)
    { if (!Selecting) { Yaw-=dx*.005; Pitch=Math.Clamp(Pitch-dy*.005,-Math.PI*.49,Math.PI*.49); } }
    public void Step(double delta)
    {
        if (!Active || Selecting) return;
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

    public static PhotoRect SelectionRect(double sx,double sy,double ex,double ey,
        double left,double top,double displayWidth,double displayHeight,int width,int height)
    {
        int X(double x)=>(int)Math.Floor(Math.Clamp((x-left)/displayWidth,0,1)*width+.5);
        int Y(double y)=>(int)Math.Floor(Math.Clamp((y-top)/displayHeight,0,1)*height+.5);
        return new(Math.Min(X(sx),X(ex)),Math.Min(Y(sy),Y(ey)),Math.Abs(X(ex)-X(sx)),Math.Abs(Y(ey)-Y(sy)));
    }
    public static PhotoRect ShotRect(PhotoRect rect,int width,int height) =>
        rect.Width<64 || rect.Height<64 ? new(0,0,width,height) : rect;
}
