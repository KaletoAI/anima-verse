using System;
using System.Collections.Generic;
using AnimaNative.Photo;
using Godot;

namespace AnimaNative.Ui;

public partial class OverviewCamera
{
    public PhotoControl Photo { get; } = new();
    private Transform3D _playTransform;
    private ProjectionType _playProjection;
    private float _playFov, _playSize;
    private Vector2 _playOffset;
    private bool _photoDrag;
    private readonly HashSet<MouseButton> _photoButtons = new();

    public void EnterPhoto()
    {
        if (Photo.Active) return;
        _playTransform=Transform; _playProjection=Projection; _playFov=Fov; _playSize=Size; _playOffset=FrustumOffset;
        var forward=-GlobalBasis.Z.Normalized();
        Photo.Enter(new(GlobalPosition.X,GlobalPosition.Y,GlobalPosition.Z),
            Math.Atan2(-forward.X,-forward.Z),Math.Asin(Math.Clamp(forward.Y,-1,1)));
        Control.ReleaseGesture(); _photoDrag=false;
        // Remove only the HUD projection shift; the original smoothed values remain asleep.
        SetPerspective(Fov,Near,Far);
    }

    public void LeavePhoto()
    {
        if (!Photo.Active) return;
        Photo.Leave(); _photoDrag=false; Control.ReleaseGesture();
        Transform=_playTransform; Fov=_playFov; Size=_playSize; FrustumOffset=_playOffset; Projection=_playProjection;
    }

    private void StepPhoto(double delta)
    {
        Photo.Step(delta);
        var p=Photo.Position;
        GlobalPosition=new((float)p.X,(float)p.Y,(float)p.Z);
        GlobalBasis=Basis.FromEuler(new((float)Photo.Pitch,(float)Photo.Yaw,0),EulerOrder.Yxz);
    }

    public void PhotoInput(InputEvent input)
    {
        switch (input)
        {
            case InputEventKey key:
                var name=key.Keycode==Key.Shift ? "shift" : KeyName(key);
                if (name is not null) Photo.Key(name,key.Pressed);
                break;
            case InputEventMouseButton b when b.ButtonIndex is MouseButton.WheelUp or MouseButton.WheelDown:
                if (b.Pressed) Photo.Wheel((b.ButtonIndex==MouseButton.WheelUp ? -1 : 1)*WheelNotchDeltaY*(b.Factor>0?b.Factor:1));
                break;
            case InputEventMouseButton b:
                if (b.Pressed) _photoButtons.Add(b.ButtonIndex); else _photoButtons.Remove(b.ButtonIndex);
                _photoDrag=b.Pressed; break;
            case InputEventMouseMotion m when _photoDrag:
                Photo.Look(m.Relative.X,m.Relative.Y); break;
        }
    }
}
