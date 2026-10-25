using System;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// Free orbit/fly camera — the only input of the skeleton:
///   mouse drag (left or right button)  orbit around the target
///   wheel                              distance to the target
///   W/A/S/D                            move the target over the ground plane
/// Lens like the browser engine (client3d/src/scene/engine.ts): vertical FOV
/// 45°, near 0.2 m, far 800 m.
/// </summary>
public partial class FlyCamera : Camera3D
{
    public Vector3 Target { get; set; }
    public float Distance { get; set; } = 40f;
    /// <summary>Radians about +Y; 0 looks along −Z.</summary>
    public float Yaw { get; set; }
    /// <summary>Radians below the horizon (positive = looking down).</summary>
    public float Pitch { get; set; } = 0.55f;

    private bool _dragging;

    public FlyCamera()
    {
        Fov = 45f;
        Near = 0.2f;
        Far = 800f;
    }

    /// <summary>Start pose: look at <paramref name="target"/> from <paramref name="distance"/> metres.</summary>
    public void LookAtAnchor(Vector3 target, float distance = 40f)
    {
        Target = target;
        Distance = distance;
        Yaw = 0f;
        Pitch = 0.55f;
        Apply();
    }

    public override void _UnhandledInput(InputEvent e)
    {
        switch (e)
        {
            case InputEventMouseButton mb when mb.ButtonIndex is MouseButton.Left or MouseButton.Right:
                _dragging = mb.Pressed;
                break;
            case InputEventMouseButton mb when mb.Pressed && mb.ButtonIndex == MouseButton.WheelUp:
                Distance = Math.Max(2f, Distance * 0.9f);
                break;
            case InputEventMouseButton mb when mb.Pressed && mb.ButtonIndex == MouseButton.WheelDown:
                Distance = Math.Min(2000f, Distance * 1.1f);
                break;
            case InputEventMouseMotion mm when _dragging:
                Yaw -= mm.Relative.X * 0.005f;
                Pitch = Math.Clamp(Pitch + mm.Relative.Y * 0.005f, -1.2f, 1.5f);
                break;
        }
    }

    public override void _Process(double delta)
    {
        var move = Vector2.Zero;
        if (Input.IsKeyPressed(Key.W)) move.Y -= 1;
        if (Input.IsKeyPressed(Key.S)) move.Y += 1;
        if (Input.IsKeyPressed(Key.A)) move.X -= 1;
        if (Input.IsKeyPressed(Key.D)) move.X += 1;
        if (move != Vector2.Zero)
        {
            // Ground-plane movement relative to the view; faster when far out.
            float speed = Math.Max(5f, Distance) * 0.8f * (float)delta;
            var forward = new Vector3(-MathF.Sin(Yaw), 0, -MathF.Cos(Yaw));
            var right = new Vector3(MathF.Cos(Yaw), 0, -MathF.Sin(Yaw));
            Target += (right * move.X - forward * move.Y).Normalized() * speed;
        }
        Apply();
    }

    private void Apply()
    {
        var dir = new Vector3(-MathF.Sin(Yaw) * MathF.Cos(Pitch), -MathF.Sin(Pitch), -MathF.Cos(Yaw) * MathF.Cos(Pitch));
        if (!IsInsideTree()) return;
        var pos = Target - dir * Distance;
        LookAtFromPosition(pos, Target, Mathf.Abs(dir.Y) > 0.999f ? Vector3.Forward : Vector3.Up);
    }
}
