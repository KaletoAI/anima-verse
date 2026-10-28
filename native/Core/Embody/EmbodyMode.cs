using System;
using AnimaNative.Overview;

namespace AnimaNative.Embody;

/// <summary>
/// Task 48 / E7-T3: game/embody.ts mode edges. Residency/boot are caller-owned gates; camera facts and the
/// cap hint latch share one lifetime. Re-entering an active mode never resets its once-per-session hint.
/// </summary>
public sealed class EmbodyMode
{
    public const double EnterDistance = 7, MaxDistance = 34, ExitDistance = 70;
    public const string CapMessage = "That is as far out as you can look while in control — press Esc to leave control.";
    private readonly OverviewControl _camera;
    private readonly Func<Vec3?> _position, _eye;
    private bool _hinted;
    public bool Active { get; private set; }
    public event Action? CapHint;
    public event Action? Changed;

    public EmbodyMode(OverviewControl camera, Func<Vec3?> position, Func<Vec3?> eye)
    {
        (_camera, _position, _eye) = (camera, position, eye);
        camera.ZoomCapped += () =>
        {
            if (!Active || _hinted) return;
            _hinted = true;
            CapHint?.Invoke();
        };
    }

    public bool Enter()
    {
        if (Active || _position() is not Vec3 at) return false;
        _hinted = false;
        _camera.ZoomCap = MaxDistance;
        _camera.ZoomFloor = CameraFraming.EmbodyMinDist;
        _camera.NearPitchDeg = CameraFraming.EmbodyNearPitchDeg;
        _camera.OrbitOnDrag = true;
        _camera.FlyTo(_eye() ?? at, EnterDistance);
        _camera.Follow = _eye;
        Active = true;
        Changed?.Invoke();
        return true;
    }

    public void Exit()
    {
        _camera.Follow = null;
        _camera.OrbitOnDrag = false;
        _camera.ZoomCap = _camera.ZoomFloor = null;
        _camera.NearPitchDeg = CameraFraming.OverviewNearPitchDeg;
        _camera.ResetFirstPerson();
        _camera.FlyTo(_position() ?? _camera.Target, ExitDistance);
        Active = false;
        Changed?.Invoke();
    }
}
