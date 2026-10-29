using System;
using System.Linq;
using System.Text.Json;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>, overview camera part (Task 8): an <see cref="OverviewCamera"/> driven through Godot's
/// real input path (<see cref="Viewport.PushInput"/> → <c>_UnhandledInput</c>) with synthetic events and
/// fixed frame steps, compared with numbers derived BY HAND here from the formulas of
/// <see cref="CameraMath"/> / engine.ts — not recorded from a run.
///
/// Setup of every case (<c>Reset</c>): target (0,0,0), distance 40, yaw 0 (camera on +Z looking −Z, right =
/// +X), pitch offset 0; the check's own viewport is 1600 × 900 (project.godot's window), lens 45° vertical. One pixel at
/// camera depth s spans s · k with k = 2 · tan 22.5° / 900 = 9.204745830513223e-4.
///
///   A  wheel up ×3 at (840, 450), no frame between: the ray through x + 40 px rises like the centre ray
///      (the right vector is horizontal), so it meets y = 0 at depth 40 too: hit H = (40 · 40 · k, 0, 0)
///      = (1.4727593328821156, 0, 0). targetDist = 40 · e^−0.36 = 27.90705304284124; each notch pulls by
///      1 − e^−0.12 towards the SAME H, so target = H · (1 − e^−0.36) = (0.4452500123300986, 0, 0).
///   B  left drag (800, 450) → (840, 450): yaw = −40 · .005 = −.2 radians,
///      target stays (0,0,0); 40 px &gt; 4 px → a drag, no click.
///   C  Q, then one frame of 0.05 s: targetYaw π/4, yaw = π/4 · (1 − e^−0.4) = 0.2589300303525642; base pitch
///      at 40 m = 18 + 44 · √(39.2 / 149.2) = 40.55336239889695°; the lens stands at CameraPose(…) and the
///      target projects to the middle (800, 450).
///   D  clicks: left press + release in place → Clicked; Shift + left with 3 px (≤ 4) → Clicked, targetYaw
///      −0.015; right press + release → nothing; a move without buttons → Hovered.
///   E  view shift: chat box x 1000..1600 over the full height → free strip left only, centre x 500 →
///      dx = −300, clamped to −0.35 · 800 = −280; dy 0. After 40 frames of 0.1 s the chase is at
///      −280 · (1 − e^−32) = −280: the target projects to (520, 450), the projection is FRUSTUM, the own
///      ray through (520, 450) meets the ground at the target. Closed again → back to (800, 450), PERSPECTIVE.
///   F  zoomTo(root (10, 2, −5)): fly to (10, 2.85, −5) at 4.5 m; seven frames of 0.1 s (t = 1.12 → 1) land on it.
///   G  W held while the HUD owns the keyboard: the key is dropped, the target stays.
///   H  boot framing of the fixture world: world_bounds x −104..300, z −203..134 → centre (98, −34.5), radius
///      hypot(404, 337) / 2 = 263.05 → 263.05 · 1.15 / sin 22.5° = 790.50 → clamped to 150; y = the ground there.
/// </summary>
public static class OverviewCheck
{
    private const float W = 1600, H = 900;
    private const double K = 9.204745830513223e-4;
    private const double Hx = 1.4727593328821156;              // A/B: 40 · 40 · K
    private const double WheelDist = 27.90705304284124;        // A: 40 · e^−0.36
    private const double WheelTargetX = 0.4452500123300986;    // A: Hx · (1 − e^−0.36)
    private const double QYaw = 0.2589300303525642;            // C
    private const double Pitch40 = 40.55336239889695;          // C
    private const double MetresTol = 2e-3, PxTol = 0.05;       // float32 camera transform

    public static string Run(Node3D host, JsonElement worldmap, WorldHeight height)
    {
        // The headless root window is 64 × 64: the camera gets its own 1600 × 900 viewport (the project's
        // window size), and the events are pushed into that viewport.
        var vp = new SubViewport { Name = "OverviewCheckViewport", Size = new Vector2I((int)W, (int)H), HandleInputLocally = true };
        host.AddChild(vp);
        var cam = new OverviewCamera { Name = "OverviewCheckCamera" };
        vp.AddChild(cam);
        var size = cam.GetViewport().GetVisibleRect().Size;
        Expect("viewport", size == new Vector2(W, H), $"{size}");
        cam.Current = true;
        cam.SetProcess(false);   // frames are stepped by hand
        int clicks = 0, hovers = 0;
        Vector2 lastClick = default;
        cam.Clicked += p => { clicks++; lastClick = p; };
        cam.Hovered += p => { if (p is not null) hovers++; };
        try
        {
            void Reset()
            {
                cam.Control.Restore(new OverviewControl.Snapshot(new Vec3(0, 0, 0), 40, 40, 0, 0, 0));
                cam.Step(0);
            }
            void Push(InputEvent e) => vp.PushInput(e);
            InputEventMouseButton Button(MouseButton b, bool pressed, Vector2 at, bool shift = false)
                => new() { ButtonIndex = b, Pressed = pressed, Position = at, GlobalPosition = at, Factor = 1, ShiftPressed = shift,
                           ButtonMask = pressed ? MaskOf(b) : 0 };
            InputEventMouseMotion Motion(Vector2 at, Vector2 rel, MouseButtonMask mask)
                => new() { Position = at, GlobalPosition = at, Relative = rel, ButtonMask = mask };

            // A — wheel ×3 towards the cursor.
            Reset();
            var a = new Vector2(840, 450);
            for (int i = 0; i < 3; i++)
            {
                Push(Button(MouseButton.WheelUp, true, a));
                Push(Button(MouseButton.WheelUp, false, a));
            }
            Near("A targetDist", cam.Control.TargetDist, WheelDist, 1e-9);
            Near("A target.x", cam.Control.Target.X, WheelTargetX, MetresTol);
            Near("A target.z", cam.Control.Target.Z, 0, MetresTol);
            Near("A target.y", cam.Control.Target.Y, 0, 1e-9);

            // B — a 40 px bare-left orbit.
            Reset();
            int clicksBefore = clicks;
            Push(Button(MouseButton.Left, true, new Vector2(800, 450)));
            Push(Motion(new Vector2(840, 450), new Vector2(40, 0), MouseButtonMask.Left));
            Push(Button(MouseButton.Left, false, new Vector2(840, 450)));
            Near("B target.x", cam.Control.Target.X, 0, MetresTol);
            Near("B targetYaw", cam.Control.TargetYaw, -.2, 1e-12);
            Near("B target.z", cam.Control.Target.Z, 0, MetresTol);
            Expect("B is a drag, not a click", clicks == clicksBefore, $"{clicks - clicksBefore} clicks");

            // C — Q and one frame.
            Reset();
            Push(new InputEventKey { Keycode = Key.Q, Pressed = true });
            Push(new InputEventKey { Keycode = Key.Q, Pressed = false });
            Near("C targetYaw", cam.Control.TargetYaw, Math.PI / 4, 1e-12);
            cam.Step(0.05);
            Near("C yaw", cam.Yaw, QYaw, 1e-12);
            var pose = CameraMath.CameraPose(new Vec3(0, 0, 0), 40, QYaw, Pitch40);
            var gp = cam.GlobalPosition;
            Near("C lens x", gp.X, pose.X, MetresTol);
            Near("C lens y", gp.Y, pose.Y, MetresTol);
            Near("C lens z", gp.Z, pose.Z, MetresTol);
            var mid = cam.UnprojectPosition(Vector3.Zero);
            Expect("C target in the middle", mid.DistanceTo(new Vector2(800, 450)) < PxTol, $"{mid}");

            // D — clicks under the slops, hover.
            Reset();
            clicksBefore = clicks;
            var d = new Vector2(700, 300);
            Push(Button(MouseButton.Left, true, d));
            Push(Button(MouseButton.Left, false, d));
            Expect("D plain click", clicks == clicksBefore + 1 && lastClick == d, $"{clicks - clicksBefore} at {lastClick}");
            Expect("D click leaves the target", cam.Control.Target == new Vec3(0, 0, 0), $"{cam.Control.Target}");
            Push(Button(MouseButton.Left, true, d, shift: true));
            Push(Motion(d + new Vector2(3, 0), new Vector2(3, 0), MouseButtonMask.Left));
            Push(Button(MouseButton.Left, false, d + new Vector2(3, 0)));
            Expect("D 3 px orbit is a click", clicks == clicksBefore + 2, $"{clicks - clicksBefore}");
            Near("D 3 px orbit turns", cam.Control.TargetYaw, -0.015, 1e-12);
            Push(Button(MouseButton.Right, true, d));
            Push(Button(MouseButton.Right, false, d));
            Expect("D right release is no click", clicks == clicksBefore + 2, $"{clicks - clicksBefore}");
            int hoversBefore = hovers;
            Push(Motion(new Vector2(10, 10), new Vector2(1, 1), 0));
            Expect("D hover", hovers == hoversBefore + 1, $"{hovers - hoversBefore}");

            // E — the chat box shifts the picture, the own ray follows it.
            Reset();
            cam.SetChatBox(new HudRect(1000, 0, 600, 900));
            for (int i = 0; i < 40; i++) cam.Step(0.1);
            var (dx, dy) = cam.ViewShiftPx;
            Near("E dx", dx, -280, 1e-6);
            Near("E dy", dy, 0, 1e-12);
            Expect("E frustum projection", cam.Projection == Camera3D.ProjectionType.Frustum, $"{cam.Projection}");
            var shifted = cam.UnprojectPosition(Vector3.Zero);
            Expect("E target at (520, 450)", shifted.DistanceTo(new Vector2(520, 450)) < PxTol, $"{shifted}");
            var hit = cam.GroundPoint(new Vector2(520, 450));
            Expect("E own ray hits the target", hit is Vec3 h && Math.Abs(h.X) < MetresTol && Math.Abs(h.Z) < MetresTol, $"{hit}");
            // Godot's ProjectRayNormal ignores frustum_offset — the reason for RayAt (kept as evidence).
            var godotDir = cam.ProjectRayNormal(new Vector2(520, 450));
            var godotHit = OverviewControl.HitGround(new Vec3(cam.GlobalPosition.X, cam.GlobalPosition.Y, cam.GlobalPosition.Z),
                                                     new Vec3(godotDir.X, godotDir.Y, godotDir.Z));
            double godotMiss = godotHit is Vec3 g ? Math.Sqrt(g.X * g.X + g.Z * g.Z) : double.PositiveInfinity;
            cam.SetChatBox(null);
            for (int i = 0; i < 40; i++) cam.Step(0.1);
            Expect("E shift cleared", cam.ViewShiftPx == (0, 0), $"{cam.ViewShiftPx}");
            Expect("E perspective again", cam.Projection == Camera3D.ProjectionType.Perspective, $"{cam.Projection}");
            var back = cam.UnprojectPosition(Vector3.Zero);
            Expect("E target back in the middle", back.DistanceTo(new Vector2(800, 450)) < PxTol, $"{back}");

            // F — zoomTo.
            Reset();
            cam.ZoomTo(new Vector3(10, 2, -5));
            Near("F targetDist", cam.Control.TargetDist, 4.5, 0);
            for (int i = 0; i < 7; i++) cam.Step(0.1);
            Expect("F on the figure", Distance(cam.Control.Target, new Vec3(10, 2.85, -5)) < 1e-12, $"{cam.Control.Target}");

            // G — keys while the HUD owns the keyboard.
            Reset();
            Push(new InputEventKey { Keycode = Key.W, Pressed = true });
            Expect("G w held", cam.Control.KeysDown.Contains("w"), "not held");
            cam.KeysBlocked = () => true;
            cam._Process(0.1);
            cam.KeysBlocked = null;
            Expect("G keys dropped", cam.Control.KeysDown.Count == 0, string.Join(",", cam.Control.KeysDown));
            Expect("G target stays", cam.Control.Target == new Vec3(0, 0, 0), $"{cam.Control.Target}");

            // H — boot framing of the fixture world.
            var bounds = OverviewControl.WorldBoundsOf(worldmap);
            Expect("H bounds", bounds == new BoundsXZ(-104, 300, -203, 134), $"{bounds}");
            cam.FrameWorld(bounds, height.GroundAt);
            Expect("H target", cam.Control.Target == new Vec3(98, height.GroundAt(98, -34.5), -34.5), $"{cam.Control.Target}");
            Near("H distance", cam.Distance, 150, 0);

            return $"overview A..H ok (wheel {WheelTargetX:0.####}/{WheelDist:0.###}, orbit {-.2:0.####}, yaw {QYaw:0.####}, "
                   + $"shift {dx:0.#}px, godot ray miss {godotMiss:0.##} m, frame y {cam.Control.Target.Y:0.###})";
        }
        finally
        {
            vp.QueueFree();
        }
    }

    private static MouseButtonMask MaskOf(MouseButton b) => b switch
    {
        MouseButton.Left => MouseButtonMask.Left,
        MouseButton.Right => MouseButtonMask.Right,
        MouseButton.Middle => MouseButtonMask.Middle,
        _ => 0,
    };

    private static double Distance(Vec3 a, Vec3 b)
        => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y) + (a.Z - b.Z) * (a.Z - b.Z));

    private static void Near(string what, double got, double want, double tol)
    {
        if (!(Math.Abs(got - want) <= tol)) throw new InvalidOperationException($"overview {what}: got {got:R}, want {want:R} ± {tol}");
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"overview {what}: {detail}");
    }
}
