using System;
using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Task 50 / E7-T5: main.ts driver, report and reconciliation glue. Poll ownership is decided BEFORE E6
/// placement; foreign positions are reconciled AFTER it. Reports sample the actual root after the single
/// FigureManager tick. Task 57 replaces PropActionDriven's guard with the complete prop-action lifecycle.
/// </summary>
public sealed class AvatarPositionController : IDisposable
{
    private readonly FigureManager _figures;
    private readonly WorldBuilder _world;
    private readonly PlayerSteering _steering;
    private readonly Func<double> _clock;
    private readonly ReadinessState _readiness = new();
    private JsonElement? _row;
    private P2? _lastPosition;
    private bool _active, _disposed;
    public PositionChannel Channel { get; }
    public double OwnCorrectionAt { get; private set; }
    /// <summary>Task 52 seat write hook: infinity while pending, answer time after acknowledgement.</summary>
    public double OwnSeatChangeAt { get; set; }
    public string RoomId { get; private set; } = "";
    private double _ownRoomChangeAt;
    /// <summary>Task 51: successful rides outrank polls started before their acknowledgement and all older position flights.</summary>
    private double OwnStateChangedAt => Math.Max(_ownRoomChangeAt, Math.Max(OwnCorrectionAt, OwnSeatChangeAt));
    public void AdoptRoom(string room)
    {
        _ownRoomChangeAt = _clock();
        Channel.DiscardPendingAnswers();
        RoomId = room; _steering.RoomId = room;
    }
    public Action<string>? Toast { get; set; }
    public Action<Vector3>? FlyTo { get; set; }
    public PendingSnap? PendingSnap => _readiness.PendingSnap;
    private Figure? Avatar => _figures.Figures.GetValueOrDefault(_figures.AvatarName);
    private bool InPair => Avatar?.Pair is not null;
    private bool Seated => _row is { } row && HasObject(row, "place") && _steering.Correction is null;
    private bool CanReport => _active && !_disposed && !_steering.MovementLocked && !_steering.PropActionDriven
        && !InPair && !Seated && _readiness.PendingSnap is null && _steering.Correction is null;

    public AvatarPositionController(FigureManager figures, WorldBuilder world, PlayerSteering steering,
        IWorldSource source, Func<double>? clock = null, PositionChannel? channel = null)
    {
        _figures = figures; _world = world; _steering = steering;
        _clock = clock ?? (() => source.MonotonicMs);
        Channel = channel ?? new PositionChannel(source.ReportPositionAsync, _clock);
        Channel.CanReport = () => CanReport;
        Channel.Adopted += answer => { RoomId = answer.RoomId; _steering.RoomId = RoomId; };
        Channel.Refused += (point, home) => steering.RememberRefused(point, home ?? CurrentPoint());
        Channel.Corrected += CorrectTo;
        Channel.Toast += message => Toast?.Invoke(message);
        Channel.DriverChanged += DriverChanged;
        figures.SuppressAvatarJourney = Channel.Suppressed;
        figures.PositionMapApplying += Applying;
        figures.PositionMapApplied += Applied;
        figures.AfterTick += AfterTick;
        steering.SteeringInput = point => { if (!InPair) Channel.Input(point); };
    }

    public void SetActive(bool active, JsonElement? map = null)
    {
        if (_active == active) return;
        _active = active; _lastPosition = CurrentPoint();
        if (!active)
        {
            Channel.DiscardPendingAnswers();
            _figures.HoldAvatarPlacement = false;
            _world.SetPlayerReadinessMap(null);
            Readiness.ClearSnap(_world, _readiness); _world.ClearPlayerApproach();
            _steering.PendingSnap = false;
            return;
        }
        if (map is { } root) { double at = MapReceipt.FromMap(root)?.PolledAt ?? _clock(); Applying(root, at); Applied(root, at); }
    }

    private P2? CurrentPoint() => Avatar is { } f ? new(f.Position.X, f.Position.Z) : null;
    private static bool HasObject(JsonElement row, string key) => row.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.Object;
    private static string Text(JsonElement row, string key) => row.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
    private static P2? Point(JsonElement row) => row.TryGetProperty("pos", out var p) && p.ValueKind == JsonValueKind.Object
        && World.Json.NumOrNull(p,"x") is double x && World.Json.NumOrNull(p,"z") is double z
        && double.IsFinite(x) && double.IsFinite(z) ? new(x,z) : null;
    private static PositionOrigin? Origin(JsonElement row) => row.TryGetProperty("pos_origin",out var p) && p.ValueKind == JsonValueKind.Object
        && p.TryGetProperty("seq",out var s) && s.TryGetInt64(out long seq) ? new(Text(p,"session"),seq) : null;
    private Vector3 GroundPoint(P2 p) => new((float)p.X,(float)_world.FigureGroundY(p.X,p.Z),(float)p.Z);

    private void Applying(JsonElement root, double polledAt)
    {
        if (!_active) return;
        _figures.HoldAvatarPlacement = FigureGround.PollIsStale(polledAt, OwnStateChangedAt);
        if (_figures.HoldAvatarPlacement) return;
        _world.SetPlayerReadinessMap(root);
        if (!root.TryGetProperty("characters",out var rows) || rows.ValueKind != JsonValueKind.Array) return;
        _row = null;
        foreach (var row in rows.EnumerateArray()) if (Text(row,"name") == Text(root,"avatar")) { _row = row.Clone(); break; }
        if (_row is not { } me) return;
        RoomId = Text(me,"room_id"); _steering.RoomId = RoomId;
        // Task 57 hook: a browser-started prop entry/approach remains entirely server driven here.
        bool wasPropDriven = _steering.PropActionDriven;
        _steering.PropActionDriven = HasObject(me,"prop_action_entry") || HasObject(me,"local_approach");
        if (_steering.PropActionDriven)
        {
            if (!wasPropDriven) Channel.DiscardPendingAnswers();
            ClearOwnedMovement();
            _figures.SetServerDriven(true);
            return;
        }
        bool route = me.TryGetProperty("travel",out var tr) && tr.ValueKind == JsonValueKind.Object
            && tr.TryGetProperty("waypoints",out var points) && points.ValueKind == JsonValueKind.Array && points.GetArrayLength() >= 2;
        var origin = Origin(me);
        Channel.ApplyDriver(new(route, route ? Text(tr,"journey_id") is { Length: > 0 } j ? j : null : null,
            origin?.Session == Channel.Session ? origin.Seq : null));
        _figures.SetServerDriven(Channel.Driver.Kind == DriverKind.SERVER);
    }

    private void DriverChanged(DriverState before, DriverState after)
    {
        if (!_active || _disposed) return;
        if (after.Kind == DriverKind.SERVER) { ClearOwnedMovement(); _figures.SetServerDriven(true); }
        else if (before.Kind == DriverKind.SERVER)
        {
            Vector3? arrive = after.Kind == DriverKind.PLAYER && _row is { } me && Point(me) is { } p ? GroundPoint(p) : null;
            if (arrive is not null) OwnCorrectionAt = _clock();
            _figures.SetServerDriven(false, arrive);
        }
    }

    private void ClearOwnedMovement()
    {
        Readiness.ClearSnap(_world, _readiness); _world.ClearPlayerApproach();
        _steering.PendingSnap = false; _steering.CancelRoute(); _steering.WalkIn = _steering.Correction = null;
        _steering.VerticalRide = null; _figures.SetStairRide(_figures.AvatarName, null);
    }

    /// <summary>Walk at most 8 m for at most 3 s; farther corrections snap and invalidate the local plan.</summary>
    public void CorrectTo(P2 point)
    {
        if (!_active || Avatar is not { } f) return;
        OwnCorrectionAt = _clock();
        // Task 51: the authoritative correction takes ownership even while a stair/lift owns the steering branch.
        _steering.VerticalRide = null; _figures.SetStairRide(f.CharacterName, null);
        _world.ClearPlayerApproach(); _steering.CancelRoute(); _steering.WalkIn = null;
        var goal = GroundPoint(point);
        if (double.Hypot(point.X-f.Position.X,point.Z-f.Position.Z) > PositionChannel.CorrectWalkM)
        { _figures.SnapPlayerTo(f.CharacterName,goal); _steering.Correction = null; }
        else
        {
            _figures.SetPlayerTarget(f.CharacterName,goal);
            _steering.Correction = new(goal,_steering.Clock+PositionChannel.CorrectSeconds);
        }
        Channel.CorrectBaseline(point); _lastPosition = point;
    }

    private void Applied(JsonElement root, double polledAt)
    {
        if (!_active || _steering.PropActionDriven || Channel.Driver.Kind == DriverKind.SERVER
            || FigureGround.PollIsStale(polledAt,OwnStateChangedAt) || _row is not { } row) return;
        if (row.TryGetProperty("travel",out var tr) && tr.ValueKind == JsonValueKind.Object && Channel.Suppressed(Text(tr,"journey_id"))) return;
        Readiness.ClearSnap(_world,_readiness); _steering.PendingSnap = false;
        if (Seated || InPair || Channel.InFlight || _steering.WalkIn is not null || _steering.VerticalRide is not null
            || _steering.Correction is not null || CurrentPoint() is not { } at || Point(row) is not { } p || Channel.OwnEcho(Origin(row))) return;
        double distance = double.Hypot(p.X-at.X,p.Z-at.Z);
        if (distance <= PositionChannel.SnapM) return;
        if (distance > PositionChannel.CorrectWalkM && _world.PlaceAt(p.X,p.Z) is { } id && !_world.IsReady(id))
        {
            _world.ClearPlayerApproach();
            Readiness.HoldSnap(_world,_readiness,new(p.X,p.Z,id));
            _steering.PendingSnap = true; _steering.CancelRoute();
            if (Avatar is { } f) f.Target = f.Position;
            return;
        }
        CorrectTo(p);
        if (distance > PositionChannel.CorrectWalkM) FlyTo?.Invoke(GroundPoint(p));
    }

    /// <summary>Runs before steering so a ready teleport releases the hold on the same frame.</summary>
    public void BeforeSteering()
    {
        if (!_active || _readiness.PendingSnap is not { } snap || !Readiness.TrySnap(_world,snap)) return;
        Readiness.ClearSnap(_world,_readiness); _steering.PendingSnap = false;
        var p = new P2(snap.X,snap.Z); CorrectTo(p); FlyTo?.Invoke(GroundPoint(p));
    }

    private void AfterTick()
    {
        if (!_active || CurrentPoint() is not { } p) return;
        bool moved = _lastPosition is { } last && double.Hypot(p.X-last.X,p.Z-last.Z) > .00001;
        _lastPosition = p;
        if (CanReport) Channel.Tick(p,moved);
    }

    public void Dispose()
    {
        if (_disposed) return;
        SetActive(false); _disposed = true; Channel.Dispose();
        _figures.PositionMapApplying -= Applying; _figures.PositionMapApplied -= Applied; _figures.AfterTick -= AfterTick;
        _figures.SuppressAvatarJourney = null; _steering.SteeringInput = null;
    }
}
