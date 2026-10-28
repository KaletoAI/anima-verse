using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Overview;

/// <summary>A pointer button as the overview camera tells them apart (DOM <c>button</c> 0 / 1 / 2).</summary>
public enum PointerButton { Left, Middle, Right, Other }

/// <summary>Where the lens stands after a frame, and what it looks at (world metres, pitch in degrees).</summary>
public readonly record struct OverviewPose(Vec3 Position, Vec3 Target, double PitchDeg);

/// <summary>
/// The OVERVIEW camera's state and its input rules — the Godot-free half of the native overview
/// camera (<c>native/Ui/OverviewCamera.cs</c> feeds it events and ground hits and applies the pose).
/// A line-for-line port of the camera part of <c>client3d/src/scene/engine.ts</c> (Engine: the
/// fields <c>target/dist/targetDist/yaw/targetYaw/pitchOffset</c>, <c>flyTo</c>, <c>bindInput</c>,
/// the camera half of <c>frame()</c>). Task 48 (E7-T3) adds follow, bounded zoom and first person;
/// overview defaults remain unchanged.
///
/// Every formula that cameraMath.ts / cameraFraming.ts own goes through <see cref="CameraMath"/> /
/// <see cref="CameraFraming"/> (vector-checked). What engine.ts writes INLINE stays inline here,
/// with its constants named: the WASD pan step, the Q/E quarter turn, the +/− key factors, the
/// grab pan and the two click slops, the <c>THREE.MathUtils.lerp</c> of the easing.
///
/// Ground hits are supplied by the caller as functions (<c>groundPoint</c> of engine.ts: the ray
/// through the pointer meets the plane y = 0), evaluated lazily exactly where engine.ts raycasts.
/// </summary>
public sealed class OverviewControl
{
    // ---- engine.ts constants ------------------------------------------------------------------

    /// <summary>Click slop of an orbit gesture, CSS px (engine.ts <c>ORBIT_DRAG_PX</c>).</summary>
    public const double OrbitDragPx = 4;
    /// <summary>Click slop of a pan gesture, metres on the ground plane (engine.ts pointermove: <c>delta.length() &gt; 0.15</c>).</summary>
    public const double PanDragM = 0.15;
    /// <summary>WASD/arrow pan speed as a share of the eased distance per second (<c>this.dist * 0.9 * dt</c>).</summary>
    public const double KeyPanRate = 0.9;
    /// <summary>One Q/E step of the target yaw (radians, eased, no grid snap).</summary>
    public const double QuarterTurn = Math.PI / 4;
    /// <summary>The + key: target distance × 0.8 (clamped).</summary>
    public const double KeyZoomIn = 0.8;
    /// <summary>The − key: target distance × 1.25 (clamped).</summary>
    public const double KeyZoomOut = 1.25;
    /// <summary>The engine's start distance and yaw (before the boot framing).</summary>
    public const double InitialDist = 80, InitialYaw = Math.PI / 4;
    /// <summary>main.ts zoomTo: aim at the middle of a 1.70 m body (<c>p.y += 0.85</c>).</summary>
    public const double ZoomToLift = 0.85;
    /// <summary>main.ts <c>ZOOM_TO_BASE_DIST</c> / <c>ZOOM_TO_MAX_DIST</c>.</summary>
    public const double ZoomToBaseDist = 4.5, ZoomToMaxDist = 12;

    // ---- engine.ts mode fields (Task 48)               -----------------------------------------

    /// <summary>The mode's zoom floor and cap: both null in the overview (only the embodied mode sets them).</summary>
    public double? ZoomFloor { get; set; }
    public double? ZoomCap { get; set; }
    public double NearPitchDeg { get; set; } = CameraFraming.OverviewNearPitchDeg;
    public bool OrbitOnDrag { get; set; }
    /// <summary>Task 48: live eye callback; evaluated once after the fly per frame.</summary>
    public Func<Vec3?>? Follow { get; set; }
    public event Action? ZoomCapped;
    private readonly FirstPersonZoom _firstPersonZoom = new();
    public bool FirstPerson => _firstPersonZoom.Active;
    private Vec3? _followAt;

    private double ClampZoom(double distance)
    {
        if (ZoomCap is not null && distance > CameraMath.ZoomCeiling(CameraMath.ZoomFloorOf(ZoomFloor), ZoomCap) + 1e-6)
            ZoomCapped?.Invoke();
        return CameraMath.ClampZoom(distance, ZoomFloor, ZoomCap);
    }

    /// <summary>Task 48: release first person immediately on a mode edge, before the next frame.</summary>
    public void ResetFirstPerson() { _firstPersonZoom.Update(Dist, false, 0); _followAt = null; }

    // ---- the camera state (engine.ts public fields) ----------------------------------------------

    public Vec3 Target { get; set; }
    public double Dist { get; set; } = InitialDist;
    public double TargetDist { get; set; } = InitialDist;
    public double Yaw { get; set; } = InitialYaw;
    public double TargetYaw { get; set; } = InitialYaw;
    /// <summary>Free pitch share in degrees (not eased).</summary>
    public double PitchOffset { get; set; }

    private Vec3 _flyFrom, _flyTo;
    private bool _hasFly;
    private double _flyT = 1;

    private bool _dragging, _orbiting, _moved;
    private (double X, double Y) _orbitLast, _orbitStart;
    private Vec3 _dragStart;
    private readonly HashSet<string> _keys = new();

    /// <summary>A fly-to is running.</summary>
    public bool Flying => _flyT < 1 && _hasFly;

    /// <summary>Keys held down, lower-case DOM <c>key</c> names (<c>w</c>, <c>arrowup</c>, <c>q</c>, <c>+</c>…).</summary>
    public IReadOnlyCollection<string> KeysDown => _keys;

    // ---- placing the camera --------------------------------------------------------------------

    /// <summary>
    /// Put the camera on <paramref name="target"/> at <paramref name="dist"/> at once — what main.ts does at
    /// boot (<c>engine.target.copy(center); engine.dist = engine.targetDist = …</c>). Ends a running fly.
    /// </summary>
    public void JumpTo(Vec3 target, double dist)
    {
        Target = target;
        Dist = TargetDist = dist;
        _flyT = 1;
    }

    /// <summary>
    /// The boot framing of main.ts: the centre of <c>world_bounds</c> on the ground there
    /// (<c>worldCentre</c>: <paramref name="groundY"/> samples the terrain) at <see cref="CameraMath.FitDistance"/>.
    /// </summary>
    public void FrameWorld(BoundsXZ? bounds, Func<double, double, double> groundY)
    {
        var (x, z) = CameraMath.WorldCentreXZ(bounds);
        JumpTo(new Vec3(x, groundY(x, z), z), CameraMath.FitDistance(bounds));
    }

    /// <summary>engine.ts <c>flyTo</c>: ease the target onto <paramref name="point"/>; the distance is clamped without the cap.</summary>
    public void FlyTo(Vec3 point, double dist)
    {
        _flyFrom = Target;
        _flyTo = point;
        _hasFly = true;
        _flyT = 0;
        TargetDist = CameraMath.ClampZoom(dist, ZoomFloor, null);
    }

    /// <summary>main.ts <c>zoomTo</c>: fly to the figure's root lifted by 0.85 m at clamp(4.5, MIN_DIST, 12) = 4.5 m. No follow.</summary>
    public void ZoomTo(Vec3 figureRoot)
    {
        if (Follow is not null) return;
        FlyTo(new Vec3(figureRoot.X, figureRoot.Y + ZoomToLift, figureRoot.Z),
                 Math.Max(CameraFraming.MinDist, Math.Min(ZoomToMaxDist, ZoomToBaseDist)));
    }

    // ---- input (engine.ts bindInput) --------------------------------------------------------------

    /// <summary>
    /// A wheel event of <paramref name="deltaY"/> (DOM units; one notch ≈ 100). Zooming in pulls the
    /// target towards the cursor's ground hit (asked only then); any wheel aborts a fly.
    /// </summary>
    public void Wheel(double deltaY, Func<Vec3?> cursorHit)
    {
        double before = TargetDist;
        TargetDist = ClampZoom(before * CameraMath.WheelFactor(deltaY));
        if (Follow is null && TargetDist < before && cursorHit() is Vec3 p)
            Target = CameraMath.ZoomTowardCursor(Target, (p.X, p.Z), before, TargetDist);
        _flyT = 1;
    }

    /// <summary>
    /// pointerdown: middle/right, or left with Shift/Ctrl/Alt, starts an orbit; the bare left button grabs
    /// the ground point under the pointer (none = no pan).
    /// </summary>
    public void PointerDown(PointerButton button, bool shift, bool ctrl, bool alt, double x, double y, Func<Vec3?> groundHit)
    {
        bool orbit = button is PointerButton.Middle or PointerButton.Right
                     || (button == PointerButton.Left && (OrbitOnDrag || shift || ctrl || alt));
        if (orbit)
        {
            _orbiting = true;
            _moved = false;
            _orbitLast = (x, y);
            _orbitStart = (x, y);
            return;
        }
        if (button != PointerButton.Left) return;
        if (groundHit() is not Vec3 p) return;
        _dragging = true;
        _moved = false;
        _dragStart = p;
    }

    /// <summary>
    /// pointermove. Orbit: turn on the first pixel, count as a drag only past <see cref="OrbitDragPx"/>.
    /// Pan: the grabbed point goes back under the pointer (<c>target += dragStart − p</c>), a drag past
    /// <see cref="PanDragM"/>. Both abort a fly. Returns true when the move is a HOVER (no gesture running).
    /// </summary>
    public bool PointerMove(double x, double y, Func<Vec3?> groundHit)
    {
        if (_orbiting)
        {
            double dx = x - _orbitLast.X;
            double dy = y - _orbitLast.Y;
            if (double.Hypot(x - _orbitStart.X, y - _orbitStart.Y) > OrbitDragPx) _moved = true;
            _orbitLast = (x, y);
            var step = CameraMath.OrbitStep(TargetYaw, PitchOffset, dx, dy, FirstPerson);
            TargetYaw = step.TargetYaw;
            PitchOffset = step.PitchOffset;
            _flyT = 1;
            return false;
        }
        if (_dragging)
        {
            if (groundHit() is not Vec3 p) return false;
            var delta = new Vec3(_dragStart.X - p.X, _dragStart.Y - p.Y, _dragStart.Z - p.Z);
            if (Math.Sqrt(delta.X * delta.X + delta.Y * delta.Y + delta.Z * delta.Z) > PanDragM) _moved = true;
            Target = new Vec3(Target.X + delta.X, Target.Y + delta.Y, Target.Z + delta.Z);
            _flyT = 1;
            return false;
        }
        return true;
    }

    /// <summary>pointerup (any button) ends both gestures. Returns true when it is a CLICK: left button, no drag.</summary>
    public bool PointerUp(PointerButton button)
    {
        bool wasDrag = (_dragging || _orbiting) && _moved;
        _dragging = false;
        _orbiting = false;
        return !wasDrag && button == PointerButton.Left;
    }

    /// <summary>
    /// keydown with the DOM <c>key</c>, lower-cased: held for the pan; q/e turn the target yaw by a quarter;
    /// + / − scale the target distance. Repeats count, like the browser's auto-repeat keydown.
    /// </summary>
    public void KeyDown(string key)
    {
        _keys.Add(key);
        if (key == "q") TargetYaw += QuarterTurn;
        if (key == "e") TargetYaw -= QuarterTurn;
        if (key == "+") TargetDist = ClampZoom(TargetDist * KeyZoomIn);
        if (key == "-") TargetDist = ClampZoom(TargetDist * KeyZoomOut);
    }

    public void KeyUp(string key) => _keys.Remove(key);

    /// <summary>Forget every held key (the keyboard went to another surface; its key-ups will not arrive here).</summary>
    public void ReleaseKeys() => _keys.Clear();

    // ---- the frame (engine.ts frame(), camera part) -----------------------------------------------

    /// <summary>
    /// One frame of <paramref name="rawDt"/> seconds (clamped to <see cref="CameraMath.MaxFrameDt"/>): key
    /// pan, fly, easing of distance and yaw, then the pose — in engine.ts order.
    /// </summary>
    public OverviewPose Step(double rawDt)
    {
        double dt = Math.Min(rawDt, CameraMath.MaxFrameDt);

        // WASD/arrows relative to the view direction, at the eased distance of the previous frame.
        double panSpeed = Follow is null ? Dist * KeyPanRate * dt : 0;
        double fx = -Math.Sin(Yaw), fz = -Math.Cos(Yaw);
        double rx = -fz, rz = fx;
        double tx = Target.X, ty = Target.Y, tz = Target.Z;
        if (_keys.Contains("w") || _keys.Contains("arrowup")) { tx += fx * panSpeed; tz += fz * panSpeed; }
        if (_keys.Contains("s") || _keys.Contains("arrowdown")) { tx += fx * -panSpeed; tz += fz * -panSpeed; }
        if (_keys.Contains("a") || _keys.Contains("arrowleft")) { tx += rx * -panSpeed; tz += rz * -panSpeed; }
        if (_keys.Contains("d") || _keys.Contains("arrowright")) { tx += rx * panSpeed; tz += rz * panSpeed; }
        Target = new Vec3(tx, ty, tz);

        if (_flyT < 1 && _hasFly)
        {
            _flyT = CameraMath.FlyAdvance(_flyT, dt);
            double k = CameraMath.FlyEase(_flyT);
            // THREE.Vector3.lerpVectors: v1 + (v2 − v1) · alpha.
            Target = new Vec3(_flyFrom.X + (_flyTo.X - _flyFrom.X) * k,
                              _flyFrom.Y + (_flyTo.Y - _flyFrom.Y) * k,
                              _flyFrom.Z + (_flyTo.Z - _flyFrom.Z) * k);
        }

        _followAt = Follow?.Invoke();
        if (_followAt is Vec3 at)
        {
            double k = 1 - Math.Exp(-6 * dt);
            Target = new Vec3(Target.X + (at.X - Target.X) * k, Target.Y + (at.Y - Target.Y) * k,
                              Target.Z + (at.Z - Target.Z) * k);
        }
        double ease = CameraMath.Damp(dt);
        Dist = Lerp(Dist, TargetDist, ease);
        Yaw = Lerp(Yaw, TargetYaw, ease);

        double zoomDistance = FirstPerson ? TargetDist : Math.Max(Dist - 1e-6, TargetDist);
        _firstPersonZoom.Update(zoomDistance, _followAt is not null, dt);
        return Pose();
    }

    /// <summary>Task 48: current pose; third person has a 2 m stand-off, first person has no chase lag.</summary>
    public OverviewPose Pose()
    {
        double orbitDist = _followAt is not null ? Math.Max(Dist, CameraFraming.ThirdPersonMinDist) : Dist;
        double pitch = CameraMath.ClampPitchDeg((FirstPerson ? 0 : CameraFraming.BasePitchDeg(orbitDist, NearPitchDeg)) + PitchOffset, FirstPerson);
        if (FirstPerson && _followAt is Vec3 eye) return FirstPersonPose(eye, pitch);
        return new OverviewPose(CameraMath.CameraPose(Target, orbitDist, Yaw, pitch), Target, pitch);
    }

    /// <summary>Task 48: reassert the lens after figure/skeleton hooks without advancing the chase or zoom latch.</summary>
    public OverviewPose FirstPersonPose(Vec3 eye)
        => FirstPersonPose(eye, CameraMath.ClampPitchDeg(PitchOffset, true));

    private OverviewPose FirstPersonPose(Vec3 eye, double pitch)
    {
        Target = eye; // engine.placeFirstPerson: all target-dependent systems see the posed eye as well.
        var offset = CameraMath.CameraPose(new Vec3(0, 0, 0), 1, Yaw, pitch);
        return new OverviewPose(eye, new Vec3(eye.X - offset.X, eye.Y - offset.Y, eye.Z - offset.Z), pitch);
    }

    /// <summary><c>THREE.MathUtils.lerp</c>: <c>(1 − t) · x + t · y</c>.</summary>
    private static double Lerp(double x, double y, double t) => (1 - t) * x + t * y;

    // ---- save / restore (the bench drive hands the camera back) ------------------------------------

    /// <summary>Everything a bench run may overwrite.</summary>
    public readonly record struct Snapshot(Vec3 Target, double Dist, double TargetDist, double Yaw, double TargetYaw,
                                           double PitchOffset);

    public Snapshot Save() => new(Target, Dist, TargetDist, Yaw, TargetYaw, PitchOffset);

    /// <summary>Back to <paramref name="s"/>; a fly and any gesture end, held keys are forgotten.</summary>
    public void Restore(Snapshot s)
    {
        (Target, Dist, TargetDist, Yaw, TargetYaw, PitchOffset) = (s.Target, s.Dist, s.TargetDist, s.Yaw, s.TargetYaw, s.PitchOffset);
        _flyT = 1;
        _dragging = _orbiting = false;
        _keys.Clear();
    }

    // ---- geometry helpers of the scene side ----------------------------------------------------------

    /// <summary>
    /// <c>THREE.Ray.intersectPlane</c> for the ground plane y = 0: a ray parallel to it hits only when its
    /// origin lies on it; a hit behind the origin is none.
    /// </summary>
    public static Vec3? HitGround(Vec3 origin, Vec3 dir)
    {
        if (dir.Y == 0) return origin.Y == 0 ? origin : null;
        double t = -origin.Y / dir.Y;
        if (!(t >= 0)) return null;
        return new Vec3(origin.X + dir.X * t, origin.Y + dir.Y * t, origin.Z + dir.Z * t);
    }

    /// <summary>
    /// <c>world_bounds</c> of a <c>/play/worldmap</c> payload: an object with four finite numbers, else null
    /// (an empty world or an older server; <see cref="CameraMath.FitDistance"/> then answers 70).
    /// </summary>
    public static BoundsXZ? WorldBoundsOf(JsonElement map)
    {
        if (map.ValueKind != JsonValueKind.Object || !map.TryGetProperty("world_bounds", out var b)
            || b.ValueKind != JsonValueKind.Object) return null;
        static double? N(JsonElement o, string k)
            => o.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number && v.GetDouble() is var d
               && double.IsFinite(d) ? d : null;
        return N(b, "min_x") is double minX && N(b, "max_x") is double maxX
               && N(b, "min_z") is double minZ && N(b, "max_z") is double maxZ
            ? new BoundsXZ(minX, maxX, minZ, maxZ)
            : null;
    }
}
