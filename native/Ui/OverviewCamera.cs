using System;
using AnimaNative.Hud;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// The overview camera — the browser's map camera (client3d/src/scene/engine.ts) in Godot. The rules
/// and the numbers live in <see cref="OverviewControl"/> (Godot-free, tested); this node only
///
///   • turns Godot input into the DOM gestures engine.ts binds (<see cref="_UnhandledInput"/> — what
///     the HUD routing did not take): left drag pans by grabbing the ground plane y = 0; middle/right
///     drag or Shift/Ctrl/Alt + left drag orbits and tilts; the wheel zooms towards the cursor;
///     W/A/S/D and the arrows pan, Q/E turn by 45°, + / − zoom by 0.8 / 1.25;
///   • answers the ground hit of a screen point (<see cref="GroundPoint"/>, the ray through the pointer
///     on y = 0 — engine.ts <c>groundPoint</c>);
///   • places the lens every frame and applies the HUD's view shift as a frustum shift
///     (<see cref="ApplyViewShift"/>);
///   • reports a release under the click slops as <see cref="Clicked"/> and a pointer move without a
///     gesture as <see cref="Hovered"/>.
///
/// Lens like the browser: vertical FOV 45°, near 0.2 m, far 800 m.
/// </summary>
public partial class OverviewCamera : Camera3D
{
    /// <summary>One wheel notch in DOM <c>deltaY</c> units (a Godot wheel event carries notches, scaled by <c>Factor</c>).</summary>
    public const double WheelNotchDeltaY = 100;
    /// <summary>engine.ts applyViewShift: the chase snaps to 0 below this many px, and skips a rebuild below 0.01 px.</summary>
    public const double ViewSnapPx = 0.05, ViewRebuildPx = 0.01;

    public OverviewControl Control { get; } = new();

    /// <summary>A left release without a drag (under 4 px orbit / 0.15 m pan), viewport px. The pick chain hangs here.</summary>
    public event Action<Vector2>? Clicked;
    /// <summary>A pointer move without a gesture (viewport px); null = the pointer left the window.</summary>
    public event Action<Vector2?>? Hovered;

    /// <summary>
    /// true while another surface owns the keyboard (the HUD while one types or a modal is open). The key-ups
    /// go there too, so held keys are dropped while it is true.
    /// </summary>
    public Func<bool>? KeysBlocked { get; set; }

    /// <summary>The look-at target (the scatter window and the bench follow it).</summary>
    public Vector3 Target
    {
        get => ToGodot(Control.Target);
        set => Control.Target = new Vec3(value.X, value.Y, value.Z);
    }

    /// <summary>The eased camera distance (m).</summary>
    public double Distance => Control.Dist;
    /// <summary>The eased yaw (radians, 0 = camera on +Z looking −Z).</summary>
    public double Yaw => Control.Yaw;

    /// <summary>Task 48 / E7-T3: the mode's live eye and bounded zoom, delegated to the tested controller.</summary>
    public Func<Vec3?>? Follow { get => Control.Follow; set => Control.Follow = value; }
    public double? ZoomCap { get => Control.ZoomCap; set => Control.ZoomCap = value; }
    public double? ZoomFloor { get => Control.ZoomFloor; set => Control.ZoomFloor = value; }
    public double NearPitchDeg { get => Control.NearPitchDeg; set => Control.NearPitchDeg = value; }
    public bool FirstPerson => Control.FirstPerson;
    public event Action? ZoomCapped { add => Control.ZoomCapped += value; remove => Control.ZoomCapped -= value; }
    /// <summary>Task 48: pose hooks run after the camera zoom latch, before final first-person placement.</summary>
    public event Action? Posed;

    private HudRect? _chatBox;
    private double _viewDx, _viewDy;
    private (double Dx, double Dy, float W, float H)? _viewApplied;

    /// <summary>The lens of engine.ts (<c>PerspectiveCamera(45, …)</c>, vertical field of view in degrees).</summary>
    public const float FovDeg = 45f;

    public OverviewCamera()
    {
        Fov = FovDeg;
        Near = 0.2f;
        Far = 800f;
    }

    // ---- placing ---------------------------------------------------------------------------------

    /// <summary>The boot framing (main.ts): world centre on the ground at the fit distance.</summary>
    public void FrameWorld(BoundsXZ? bounds, Func<double, double, double> groundY)
    {
        Control.FrameWorld(bounds, groundY);
        ApplyPose(Control.Pose());
    }

    /// <summary>Put the camera on <paramref name="target"/> at <paramref name="dist"/> at once.</summary>
    public void JumpTo(Vector3 target, double dist)
    {
        Control.JumpTo(new Vec3(target.X, target.Y, target.Z), dist);
        ApplyPose(Control.Pose());
    }

    public void FlyTo(Vector3 point, double dist) => Control.FlyTo(new Vec3(point.X, point.Y, point.Z), dist);

    /// <summary>The plaque's "Zoom to": fly to the figure root + 0.85 m at 4.5 m, no follow.</summary>
    public void ZoomTo(Vector3 figureRoot) => Control.ZoomTo(new Vec3(figureRoot.X, figureRoot.Y, figureRoot.Z));

    /// <summary>The HUD's chat panel in VIEWPORT px (main.ts <c>setChatBox</c> → <c>engine.obstruction</c>); null = closed.</summary>
    public void SetChatBox(HudRect? box) => _chatBox = box;

    // ---- the frame -------------------------------------------------------------------------------

    public override void _Process(double delta)
    {
        if (KeysBlocked?.Invoke() == true) Control.ReleaseKeys();
        Step(delta);
    }

    /// <summary>One camera frame (public for the headless check, which drives it with fixed steps).</summary>
    public void Step(double delta)
    {
        ApplyPose(Control.Step(delta));
        Posed?.Invoke();
        RefreshFirstPerson();
        ApplyViewShift(Math.Min(delta, CameraMath.MaxFrameDt));
    }

    /// <summary>Task 48: skeleton/frame hooks reassert the current head lens without advancing camera state.</summary>
    public void RefreshFirstPerson()
    {
        if (FirstPerson && Follow?.Invoke() is Vec3 eye) ApplyPose(Control.FirstPersonPose(eye));
    }

    private void ApplyPose(OverviewPose pose)
    {
        if (!IsInsideTree()) return;
        LookAtFromPosition(ToGodot(pose.Position), ToGodot(pose.Target), Vector3.Up);
    }

    /// <summary>
    /// The frustum shift of client3d/src/scene/viewShift.ts — engine.ts <c>applyViewShift</c>. three.js
    /// renders an off-centre cut-out with <c>setViewOffset(w, h, −dx, −dy, w, h)</c>; Godot has no view
    /// offset, so the same off-axis frustum is set directly: <see cref="Camera3D.ProjectionType.Frustum"/>
    /// with <c>size</c> = the near-plane height of the 45° lens and <c>frustum_offset</c> = the shift in
    /// near-plane metres, (−dx, +dy) · size / h. That moves the image by exactly (dx, dy) px and leaves the
    /// camera where it is (h_offset/v_offset would MOVE the camera: a parallax, not a pixel shift). Back to
    /// the plain perspective lens once the shift is 0 (three.js <c>clearViewOffset</c>).
    /// </summary>
    private void ApplyViewShift(double dt)
    {
        var size = GetViewport().GetVisibleRect().Size;
        float w = size.X, h = size.Y;
        var want = w > 0 && h > 0 ? ViewShift.For(w, h, _chatBox) : ViewShift.None;
        double k = CameraMath.Damp(dt);
        _viewDx += (want.Dx - _viewDx) * k;
        _viewDy += (want.Dy - _viewDy) * k;
        if (want.Dx == 0 && want.Dy == 0 && Math.Abs(_viewDx) < ViewSnapPx && Math.Abs(_viewDy) < ViewSnapPx)
        {
            _viewDx = 0;
            _viewDy = 0;
        }
        if (_viewDx == 0 && _viewDy == 0)
        {
            if (_viewApplied is not null)
            {
                SetPerspective(Fov, Near, Far);
                _viewApplied = null;
            }
            return;
        }
        if (_viewApplied is { } a && a.W == w && a.H == h
            && Math.Abs(a.Dx - _viewDx) < ViewRebuildPx && Math.Abs(a.Dy - _viewDy) < ViewRebuildPx) return;
        double nearH = NearPlaneHeight();
        double perPx = nearH / h;
        SetFrustum((float)nearH, new Vector2((float)(-_viewDx * perPx), (float)(_viewDy * perPx)), Near, Far);
        _viewApplied = (_viewDx, _viewDy, w, h);
    }

    /// <summary>The applied view shift in viewport px (right, down).</summary>
    public (double Dx, double Dy) ViewShiftPx => (_viewDx, _viewDy);

    /// <summary>Height of the lens' near plane: 2 · near · tan(fov / 2) — what a 45° perspective lens sees at <c>near</c>.</summary>
    private double NearPlaneHeight() => 2 * Near * Math.Tan(Fov * Math.PI / 360);

    // ---- rays ------------------------------------------------------------------------------------

    /// <summary>
    /// The ray through a viewport point, world space — three.js <c>Raycaster.setFromCamera</c>: from the
    /// lens through the point the INVERSE projection gives. Not <c>ProjectRayNormal</c>: Godot computes that
    /// from the symmetric half extents of the projection and ignores <c>frustum_offset</c>
    /// (Camera3D::project_local_ray_normal → Projection::get_viewport_half_extents, "assumes … no offset"),
    /// so it would miss by the view shift while the chat is open.
    /// </summary>
    public (Vec3 Origin, Vec3 Dir) RayAt(Vector2 screen)
    {
        var size = GetViewport().GetVisibleRect().Size;
        float nx = screen.X / size.X * 2f - 1f;
        float ny = 1f - screen.Y / size.Y * 2f;
        var v = GetCameraProjection().Inverse() * new Vector4(nx, ny, 0.5f, 1f);
        var local = new Vector3(v.X / v.W, v.Y / v.W, v.Z / v.W);
        var basis = GlobalTransform.Basis.Orthonormalized();
        var dir = (basis * local).Normalized();
        var o = GlobalPosition;
        return (new Vec3(o.X, o.Y, o.Z), new Vec3(dir.X, dir.Y, dir.Z));
    }

    /// <summary>Where the ray through a viewport point meets the ground plane y = 0 (engine.ts <c>groundPoint</c>), or null.</summary>
    public Vec3? GroundPoint(Vector2 screen)
    {
        if (!IsInsideTree()) return null;
        var (o, d) = RayAt(screen);
        return OverviewControl.HitGround(o, d);
    }

    // ---- input -----------------------------------------------------------------------------------

    public override void _UnhandledInput(InputEvent e)
    {
        switch (e)
        {
            case InputEventMouseButton mb when mb.ButtonIndex is MouseButton.WheelUp or MouseButton.WheelDown:
            {
                if (!mb.Pressed) break;
                double notches = mb.Factor > 0 ? mb.Factor : 1;
                double deltaY = (mb.ButtonIndex == MouseButton.WheelUp ? -1 : 1) * notches * WheelNotchDeltaY;
                var at = mb.Position;
                Control.Wheel(deltaY, () => GroundPoint(at));
                break;
            }
            case InputEventMouseButton mb when mb.ButtonIndex is MouseButton.WheelLeft or MouseButton.WheelRight:
                break;
            case InputEventMouseButton mb:
            {
                var at = mb.Position;
                var button = ButtonOf(mb.ButtonIndex);
                if (mb.Pressed)
                    Control.PointerDown(button, at.X, at.Y);
                else if (Control.PointerUp(button))
                    Clicked?.Invoke(at);
                break;
            }
            case InputEventMouseMotion mm:
            {
                var at = mm.Position;
                if (Control.PointerMove(at.X, at.Y)) Hovered?.Invoke(at);
                break;
            }
            case InputEventKey k:
            {
                if (KeyName(k) is not { } name) break;
                if (k.Pressed) Control.KeyDown(name);
                else Control.KeyUp(name);
                break;
            }
        }
    }

    public override void _Notification(int what)
    {
        if (what == NotificationWMMouseExit) Hovered?.Invoke(null);
        // The key-ups of a window that lost the focus never arrive.
        if (what == NotificationApplicationFocusOut) Control.ReleaseKeys();
    }

    private static PointerButton ButtonOf(MouseButton b) => b switch
    {
        MouseButton.Left => PointerButton.Left,
        MouseButton.Middle => PointerButton.Middle,
        MouseButton.Right => PointerButton.Right,
        _ => PointerButton.Other,
    };

    /// <summary>
    /// The DOM <c>key</c> name (lower-cased) the camera reads, for the keys it reads: letters by the
    /// layout's key label (as <c>e.key</c> is), the arrows, and + / − by the typed character (any key
    /// that types them, numpad included). Other keys are not tracked.
    /// </summary>
    public static string? KeyName(InputEventKey k)
    {
        if (k.Unicode == '+' || (k.Unicode == 0 && k.Keycode is Key.Plus or Key.KpAdd)) return "+";
        if (k.Unicode == '-' || (k.Unicode == 0 && k.Keycode is Key.Minus or Key.KpSubtract)) return "-";
        return k.Keycode switch
        {
            Key.W => "w",
            Key.A => "a",
            Key.S => "s",
            Key.D => "d",
            Key.Q => "q",
            Key.E => "e",
            Key.Up => "arrowup",
            Key.Down => "arrowdown",
            Key.Left => "arrowleft",
            Key.Right => "arrowright",
            _ => null,
        };
    }

    private static Vector3 ToGodot(Vec3 v) => new((float)v.X, (float)v.Y, (float)v.Z);
}
