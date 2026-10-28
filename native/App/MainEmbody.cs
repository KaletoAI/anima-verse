using System.Collections.Generic;
using System.Text.Json;
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
/// gate precede the single mode transition. Walking and write APIs belong to Task 49; follow reads the live root.
/// </summary>
public partial class Main
{
    private EmbodyMode? _embody;
    private bool _pendingTakeControl, _pendingArrivalTakeControl;
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
            PoseEmbody();
        };
        camera.Posed += PoseEmbody;
        hud.SceneEscape = CancelPendingControl;
        hud.LockedEntry = null; // Entry offers are supplied by E7's subsequent room/entry task.
        hud.Handlers["enterEmbodied"] = _ => EnterEmbodied();
        hud.Handlers["exitEmbodied"] = _ => { CancelPendingControl(); _embody.Exit(); };
        hud.Handlers["takeControl"] = _ => TakeControl();
    }

    private void EmbodyToast(string message) => _hud?.SendUi("toast", message, true);

    private void CancelPendingControl()
    {
        if (!_pendingTakeControl && !_pendingArrivalTakeControl) return;
        _pendingTakeControl = _pendingArrivalTakeControl = false;
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
            return;
        }
        _pendingArrivalTakeControl = false;
        _embody?.Enter();
    }

    /// <summary>Self panel path: wait, fly to the map point (or tile centre) at min(distance,15), open, enter.</summary>
    private void TakeControl()
    {
        if (Embodied || Leaving) return;
        if (!ControlBootReady || AvatarFigure()?.Loading == true)
        {
            _pendingTakeControl = true;
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
        if (Leaving) { CancelPendingControl(); return; }
        if ((_pendingTakeControl || _pendingArrivalTakeControl) && ControlBootReady && AvatarRow() is null)
            CancelPendingControl();
        if (_pendingTakeControl && ControlBootReady && AvatarFigure()?.Loading != true) TakeControl();
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

    private void ReassertEmbodyLens() => _camera?.RefreshFirstPerson();

    private void DetachEmbody()
    {
        if (_hud is { } hud && IsInstanceValid(hud)) { hud.SceneEscape = null; hud.LockedEntry = null; }
        if (_camera is { } camera && IsInstanceValid(camera)) camera.Posed -= PoseEmbody;
        if (_embodiedBody is { } f && IsInstanceValid(f))
        { f.HeadPosed -= ReassertEmbodyLens; f.SetFirstPerson(false); f.FirstPersonViewYaw = null; }
        _embodiedBody = null;
    }
}
