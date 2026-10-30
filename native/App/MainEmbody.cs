using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Sync;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Task 48 / E7-T3: embodied mode glue from main.ts. Boot/model waits and the Task 44 achieved near/ready
/// gate precede the single mode transition. Tasks 49/50 supply walking, position writes and server reconciliation.
/// </summary>
public partial class Main
{
    private EmbodyMode? _embody;
    private PlayerSteering? _playerSteering;
    private FigureManager? _steeringFigures;
    private AvatarPositionController? _avatarPosition;
    private AvatarRoomsController? _avatarRooms;
    private AvatarOffersController? _avatarOffers;
    private string? _entryPin;

    /// <summary>Task 50: entry waits own their pin independently of approach and teleport holds.</summary>
    private void SetEntryPin(string? id)
    {
        if (_entryPin == id) return;
        if (_entryPin is { } old) _builder?.Release(old, "entry");
        _entryPin = id;
        if (id is not null) _builder?.Pin(id, "entry");
    }
    private bool _pendingTakeControl, _pendingArrivalTakeControl;
    private bool _autoControlHandled;
    private AvatarRecovery? _avatarRecovery;
    private Task _avatarIdentity = Task.CompletedTask;

    private AvatarRecovery SessionAvatar()
    {
        if (_avatarRecovery is not null) return _avatarRecovery;
        _avatarRecovery = new AvatarRecovery(_source!, RefreshAvatarMapAsync);
        _avatarRecovery.Remembered += name => Log($"session avatar: '{name}'");
        return _avatarRecovery;
    }
    private Figure? _embodiedBody;
    private bool Embodied => _embody?.Active == true;
    private bool ControlBootReady => _boot?.Progress.Label == BootProgress.Ready && _figures?.FirstPollDone.IsCompleted == true;

    private Figure? AvatarFigure()
    {
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        var name = map is { } m ? Str(m, "avatar") : null;
        return name is not null && _figures?.Figures.GetValueOrDefault(name) is { } f && IsInstanceValid(f) ? f : null;
    }

    private JsonElement? AvatarRow()
    {
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        if (map is not { } m || !m.TryGetProperty("characters", out var chars) || chars.ValueKind != JsonValueKind.Array) return null;
        var name = Str(m, "avatar");
        foreach (var row in chars.EnumerateArray()) if (Str(row, "name") == name) return row;
        return null;
    }

    /// <summary>Task 44 supplies both facts: far/near alone cannot promise the detail mount is ready.</summary>
    private bool AvatarWaitsForPlace()
    {
        string id = AvatarRow() is { } row ? Str(row, "location_id") ?? "" : "";
        var slot = _builder?.Slots.GetValueOrDefault(id);
        return Readiness.AvatarWaitsForPlace(true, id, slot is null ? null : new(slot.Ring == Ring.Near ? "near" : "far", slot.Ready));
    }

    private static Vec3 V3(Vector3 p) => new(p.X, p.Y, p.Z);

    /// <summary>Registered on the persistent HUD overlay; callbacks are detached with this Main scene.</summary>
    private void AttachEmbody(HudOverlay hud)
    {
        var camera = _camera!;
        camera.ProcessPriority = 100; // After the figure manager's manual AnimationPlayer.Advance.
        _embody = new EmbodyMode(camera.Control, () => AvatarFigure() is { } f ? V3(f.GlobalPosition) : null,
            () => AvatarFigure() is { } f ? V3(camera.FirstPerson ? f.Lens : f.Eye) : null);
        _embody.CapHint += () => EmbodyToast(EmbodyMode.CapMessage);
        _embody.Changed += () =>
        {
            hud.SetState("mode", Embodied ? "embodied" : "overview");
            SyncPlayerSteering();
            _avatarRooms?.SetActive(Embodied);
            _avatarOffers?.SetActive(Embodied);
            PoseEmbody();
        };
        camera.Posed += PoseEmbody;
        hud.SceneEscape = CancelPendingControl;
        hud.Handlers["enterEmbodied"] = _ => TakeControl();
        hud.Handlers["exitEmbodied"] = _ => { CancelPendingControl(); _embody.Exit(); };
        hud.Handlers["takeControl"] = _ => TakeControl();
    }

    private void EmbodyToast(string message) => _hud?.SendUi("toast", message, true);

    /// <summary>Each Main lifetime is one session start, including the character-switch resume path.</summary>
    private void TryAutoTakeControl()
    {
        if (_autoControlHandled || Leaving || !ControlBootReady || !_avatarIdentity.IsCompleted) return;
        if (!string.IsNullOrEmpty(_options?.Goto) || _showAll || Embodied || _avatarRecovery?.OwnCharacter is null)
        { _autoControlHandled = true; return; }
        _autoControlHandled = true;
        Log($"automatic take-control: '{_avatarRecovery.OwnCharacter}'");
        TakeControl();
    }

    private void CancelPendingControl()
    {
        _autoControlHandled = true;
        if (!_pendingTakeControl && !_pendingArrivalTakeControl) return;
        _pendingTakeControl = _pendingArrivalTakeControl = false;
        _avatarRecovery?.Cancel();
        SetEntryPin(null);
        _boot?.SetNote(null);
    }

    /// <summary>Browser onSelect: only a user selection change cancels, never a poll refreshing the plaque.</summary>
    private void SelectForInput(string? name)
    {
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        string? avatar = map is { } m ? Str(m, "avatar") : null;
        if (name != avatar || name is null) CancelPendingControl();
        Select(name);
    }

    private void EnterEmbodied()
    {
        if (Embodied || Leaving) return;
        if (AvatarWaitsForPlace())
        {
            if (!_pendingArrivalTakeControl) EmbodyToast("Loading this place…");
            _pendingArrivalTakeControl = true;
            SetEntryPin(AvatarRow() is { } me ? Str(me, "location_id") : null);
            return;
        }
        _pendingArrivalTakeControl = false;
        SetEntryPin(null);
        _embody?.Enter();
    }

    /// <summary>Self panel path: wait, fly to the map point (or tile centre) at min(distance,15), open, enter.</summary>
    private void TakeControl()
    {
        if (Embodied || Leaving || _pendingTakeControl || _pendingArrivalTakeControl) return;
        _avatarRecovery?.Cancel();
        _pendingTakeControl = true;
        ContinueTakeControl();
    }

    private void ContinueTakeControl()
    {
        var recovery = _avatarRecovery;
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        recovery?.Tick(map, AvatarFigure() is { Loading: false });
        if (recovery?.Failure is { } failure)
        {
            CancelPendingControl();
            EmbodyToast(failure);
            return;
        }
        if (!ControlBootReady || !_avatarIdentity.IsCompleted)
        {
            _boot?.SetNote(BootNote.Characters);
            return;
        }
        if (recovery is not null && !recovery.Waiting && recovery.TryBegin(map, _stop.Token))
            EmbodyToast("Bringing your avatar back…");
        if (recovery?.Waiting == true || recovery?.Failure is not null) return;
        if (AvatarFigure()?.Loading == true)
        {
            _boot?.SetNote(BootNote.Characters);
            return;
        }
        _pendingTakeControl = false;
        _boot?.SetNote(null);
        var row = AvatarRow();
        string id = row is { } r ? Str(r, "location_id") ?? "" : "";
        var centre = PlaceCentre(id);
        Vector3? at = centre;
        if (row is { } me && me.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object
            && World.Json.NumOrNull(pos, "x") is double x && World.Json.NumOrNull(pos, "z") is double z)
            at = new Vector3((float)x, (float)(_builder?.Height?.GroundAt(x,z) ?? 0), (float)z);
        if (at is not Vector3 point) { EmbodyToast("Your avatar is not on the map yet."); return; }
        _camera?.FlyTo(point, OpenView.FlyInDist(_camera.Control.TargetDist));
        if (centre is not null) OpenLocation(id);
        EnterEmbodied();
        if (!Embodied && !_pendingArrivalTakeControl) EmbodyToast("Your avatar is not on the map yet.");
    }

    /// <summary>Resume pending requests only after their gate changes; no async continuation can revive cancelled control.</summary>
    private void TickEmbody()
    {
        if (Leaving) { CancelPendingControl(); _avatarRooms?.SetActive(false); _playerSteering?.SetActive(false); return; }
        TryAutoTakeControl();
        SyncPlayerSteering();
        TickAvatarRooms();
        TickAvatarOffers();
        if (_pendingArrivalTakeControl && _avatarRecovery?.NeedsRecovery(_figures?.LatestMap ?? _builder?.FirstMap) == true)
        {
            _pendingArrivalTakeControl = false;
            _pendingTakeControl = true;
            SetEntryPin(null);
        }
        if (_pendingArrivalTakeControl && ControlBootReady && AvatarRow() is null)
            CancelPendingControl();
        if (_pendingTakeControl) ContinueTakeControl();
        if (_pendingArrivalTakeControl && ControlBootReady && AvatarFigure() is not null && !AvatarWaitsForPlace())
        {
            // Reopen after the mount commits: takeControl may have requested a view before a slot existed.
            if (AvatarRow() is { } row && Str(row, "location_id") is { } id) OpenLocation(id);
            EnterEmbodied();
        }
    }

    /// <summary>Camera frame hook: own-body mode and view heading; the final skeleton hook places the lens again.</summary>
    private void PoseEmbody()
    {
        var figure = Embodied ? AvatarFigure() : null;
        // Task 53: camera has its final third-person pose; first person and overview clear the shared corridor.
        OcclusionMaterials.Update(_camera?.GlobalPosition ?? Vector3.Zero, figure?.GlobalPosition,
            Embodied && !Leaving, _camera?.FirstPerson == true);
        if (_embodiedBody != figure)
        {
            if (_embodiedBody is { } old && IsInstanceValid(old))
            {
                old.SetFirstPerson(false); old.FirstPersonViewYaw = null; old.HeadPosed -= ReassertEmbodyLens;
            }
            _embodiedBody = figure;
            if (figure is not null) figure.HeadPosed += ReassertEmbodyLens;
        }
        if (figure is null) return;
        bool firstPerson = _camera?.FirstPerson == true;
        figure.SetFirstPerson(firstPerson);
        figure.FirstPersonViewYaw = firstPerson ? CameraFraming.ViewHeading(_camera!.Yaw) : null;
    }

    /// <summary>Task 49: install once after world/figures arrive; steering precedes the single manager movement tick.</summary>
    private void SyncPlayerSteering()
    {
        if (_figures is null || _builder is null) return;
        if (_steeringFigures != _figures)
        {
            if (_steeringFigures is { } old && IsInstanceValid(old)) old.BeforeTick -= StepPlayerSteering;
            _avatarOffers?.Dispose(); _avatarOffers = null;
            _avatarRooms?.Dispose(); _avatarRooms = null;
            _avatarPosition?.Dispose();
            _steeringFigures = _figures;
            _playerSteering = new PlayerSteering(_figures, _builder)
            { LoadingPlace = () => EmbodyToast("Loading this place…") };
            _avatarPosition = new AvatarPositionController(_figures, _builder, _playerSteering, _source!)
            {
                Toast = EmbodyToast,
                FlyTo = point => { if (_camera is { } cam) cam.FlyTo(point, cam.Control.TargetDist); }
            };
            if (_hud is { } overlay)
                _avatarRooms = new AvatarRoomsController(_figures, _builder, _playerSteering, _source!, overlay)
                {
                    Toast = EmbodyToast,
                    AdoptRoom = room => _avatarPosition?.AdoptRoom(room),
                    AutoOpen = id => { if (id is null) CloseOpenLocation(); else OpenLocation(id); }
                };
            if (_hud is { } offerHud)
                _avatarOffers = new AvatarOffersController(_figures, _builder, _playerSteering, _source!, offerHud, _avatarPosition)
                {
                    Toast = EmbodyToast,
                    OpenLocation = OpenLocation,
                    RefreshMap = RefreshOffersMap,
                    RefreshPropWorld = RefreshPropWorldAsync,
                    PropPollPeriod = PropPollPeriod,
                    RoomRequestInFlight = () => _avatarRooms?.Channel.InFlight == true
                };
            _figures.BeforeTick += StepPlayerSteering;
        }
        _playerSteering!.SetActive(Embodied);
        _avatarPosition?.SetActive(Embodied, _figures.LatestMap ?? _builder.FirstMap);
    }

    /// <summary>Task 49: browser key names come from the shared camera key set; HUD-owned typing/overlay releases them.</summary>
    private void StepPlayerSteering(double dt)
    {
        if (_playerSteering is null || _camera is null) return;
        _playerSteering.SetActive(Embodied && !Leaving);
        _playerSteering.MovementLocked = _hud?.HudOwned("movementLocked")?.GetValue<bool>() == true;
        _avatarPosition?.BeforeSteering();
        if (_hud is { } hud && HudRouting.KeysToHud(hud.Ui)) _camera.Control.ReleaseKeys();
        _playerSteering.Step(System.Math.Min(dt, CameraMath.MaxFrameDt),
            (IReadOnlySet<string>)_camera.Control.KeysDown, _camera.Yaw);
    }

    private void ReassertEmbodyLens() => _camera?.RefreshFirstPerson();

    private void DetachEmbody()
    {
        CancelPendingControl();
        _avatarRecovery?.Dispose(); _avatarRecovery = null;
        OcclusionMaterials.Update(Vector3.Zero, null, false, false);
        ResetMinimap();
        SetEntryPin(null);
        _avatarOffers?.Dispose(); _avatarOffers = null;
        _avatarRooms?.Dispose(); _avatarRooms = null;
        _avatarPosition?.Dispose(); _avatarPosition = null;
        _playerSteering?.SetActive(false);
        if (_steeringFigures is { } manager && IsInstanceValid(manager)) manager.BeforeTick -= StepPlayerSteering;
        _playerSteering = null; _steeringFigures = null;
        if (_hud is { } hud && IsInstanceValid(hud)) { hud.SceneEscape = null; hud.LockedEntry = null; }
        if (_camera is { } camera && IsInstanceValid(camera)) camera.Posed -= PoseEmbody;
        if (_embodiedBody is { } f && IsInstanceValid(f))
        { f.HeadPosed -= ReassertEmbodyLens; f.SetFirstPerson(false); f.FirstPersonViewYaw = null; }
        _embodiedBody = null;
    }
}
