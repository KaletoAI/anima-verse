using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Api;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative;

public partial class Main : Node3D
{
    private bool _embodied, _controlReady, _controlPreparing, _positionBusy;
    private int _controlGeneration;
    private double _nextPositionMs;
    private Task _positionWrite = Task.CompletedTask;
    private string? _positionWriteError;
    private Task _controlPreparation = Task.CompletedTask;

    private Task EnterNativeControlAsync()
    {
        if (!_interactive || _figures is null || _api is null) return Task.CompletedTask;
        _embodied = true;
        _controlReady = false;
        _hud?.SetState("mode", "embodied");
        ClosePlaceMenu();
        if (_figures.Figures.TryGetValue(_figures.AvatarName, out var fig)) _camera?.ZoomTo(fig.Position);
        return Task.CompletedTask;
    }

    private void ExitNativeControl()
    {
        _controlGeneration++;
        _embodied = _controlReady = false;
        if (_figures is not null) _figures.ControlledName = null;
        _hud?.SetState("mode", "overview");
    }

    private async Task PrepareNativeSteeringAsync()
    {
        if (_controlPreparing || _api is not { } api || _figures is not { } figures) return;
        _controlPreparing = true;
        int generation = _controlGeneration;
        try
        {
            // Tombstone BEFORE the await: an old worldmap cannot resurrect a journey while cancellation is in flight.
            figures.CancelOwnedMotion();
            await _positionWrite;
            using var state = await api.GetPropActionStateAsync();
            await OwnedPropControl.ReleaseAsync(state.RootElement, api.CancelPropActionAsync, api.WakeAsync);
            if (generation != _controlGeneration || !_embodied || Leaving || _stop.IsCancellationRequested) return;
            api.BeginPositionControlSession();
            _actionEpoch++;
            figures.CancelOwnedMotion();
            figures.ControlledName = figures.AvatarName;
            if (figures.Figures.TryGetValue(figures.AvatarName, out var fig))
            {
                fig.Activity = "";
                fig.EndPublicEntry();
                fig.PlayDirect(FigureClips.IdleClip("walk", fig.Poses));
            }
            _controlReady = true;
            _hud?.NotifyPropActionsChanged();
            await RefreshActionViewAsync();
        }
        catch (Exception error)
        {
            if (generation == _controlGeneration)
            {
                ExitNativeControl();
                _hud?.SendUi("toast", JsonValue.Create(error.Message), JsonValue.Create(true));
                await RefreshActionViewAsync();
            }
        }
        finally { _controlPreparing = false; }
    }

    private void TickNativeControl(double dt)
    {
        if (!_embodied || _figures is not { } figures || _camera is null
            || !figures.Figures.TryGetValue(figures.AvatarName, out var fig)) return;
        if (_propActionBarriers.Count > 0) return;
        bool blocked = _hud?.KeysToHud == true || figures.WorldFrozen
            || _hud?.HudOwned("movementLocked") is JsonValue locked && locked.TryGetValue<bool>(out var on) && on;
        float x = 0, z = 0;
        if (!blocked)
        {
            if (Input.IsPhysicalKeyPressed(Key.A) || Input.IsPhysicalKeyPressed(Key.Left)) x--;
            if (Input.IsPhysicalKeyPressed(Key.D) || Input.IsPhysicalKeyPressed(Key.Right)) x++;
            if (Input.IsPhysicalKeyPressed(Key.W) || Input.IsPhysicalKeyPressed(Key.Up)) z--;
            if (Input.IsPhysicalKeyPressed(Key.S) || Input.IsPhysicalKeyPressed(Key.Down)) z++;
        }
        bool moving = x != 0 || z != 0;
        if (moving && !_controlReady)
        {
            if (!_controlPreparing) _controlPreparation = PrepareNativeSteeringAsync();
            return;
        }
        if (!_controlReady) return;
        if (moving)
        {
            var direction = new Vector3(x, 0, z).Normalized().Rotated(Vector3.Up, (float)_camera.Yaw);
            // No client-side permission/rule engine: /play/pos judges and reconciles every report.
            var at = fig.Position + direction * (float)(NpcWalk.WalkSpeed * Math.Min(dt, 0.1));
            at.Y = (float)(_builder?.PairRoomStandY(_avatarRoom, at.X, at.Z)
                ?? _builder?.FigureGroundY(at.X, at.Z) ?? fig.Position.Y);
            fig.Position = fig.Target = at;
            fig.FaceTowards(direction);
        }
        fig.SetMotion(moving, false, "walk");
        fig.Play(moving ? FigureClips.MoveClip("walk", false, fig.Poses) : FigureClips.IdleClip("walk", fig.Poses));
        fig.UpdateFigure(dt);
        _camera.Target = fig.Position + Vector3.Up * 0.85f;
        if (Time.GetTicksMsec() >= _nextPositionMs && !_positionBusy)
        {
            _nextPositionMs = Time.GetTicksMsec() + 250;
            _positionWrite = ReportNativePositionAsync(fig.Position, _controlGeneration);
        }
    }

    private async Task ReportNativePositionAsync(Vector3 at, int generation)
    {
        if (_api is not { } api) return;
        _positionBusy = true;
        _positionWriteError = null;
        try
        {
            using var result = await api.ReportPositionAsync(at.X, at.Z, Time.GetTicksMsec());
            if (generation != _controlGeneration) return;
            var root = result.RootElement;
            if (root.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object
                && _figures?.Figures.TryGetValue(_figures.AvatarName, out var fig) == true)
            {
                double x = Json.Num(pos, "x"), z = Json.Num(pos, "z");
                if (Math.Abs(x - at.X) > 0.01 || Math.Abs(z - at.Z) > 0.01)
                    fig.SnapTo(new Vector3((float)x, (float)(_builder?.FigureGroundY(x, z) ?? at.Y), (float)z));
            }
        }
        catch (Exception error)
        {
            _positionWriteError = error.Message;
            if (generation == _controlGeneration)
            {
                ExitNativeControl();
                _hud?.SendUi("toast", JsonValue.Create(error.Message), JsonValue.Create(true));
                await RefreshActionViewAsync();
                if (_figures is { } figures && figures.LastPlans.TryGetValue(figures.AvatarName, out var plan)
                    && figures.Figures.TryGetValue(figures.AvatarName, out var avatar))
                    avatar.SnapTo(new Vector3((float)plan.Pos.X, (float)plan.Pos.Y, (float)plan.Pos.Z));
            }
        }
        finally { _positionBusy = false; }
    }
}
