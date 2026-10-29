using System;
using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Tasks 49/50 / E7-T4/T5: main.ts steering targets; FigureManager remains the single movement/animation
/// pipeline. AvatarPositionController supplies corrections, server handoff and refusal answers; later room/offer
/// tasks supply rides, walk-ins and activity writes.
/// </summary>
public sealed class PlayerSteering(FigureManager figures, WorldBuilder world)
{
    public const double MinLead = .15, RefusedRadiusM = .8, RefusedMemoryS = 4;
    public const int RefusedMax = 8;
    public bool Active { get; private set; }
    public bool MovementLocked { get; set; }
    /// <summary>Task 50 / Task 57 hook: authoritative prop entry/approach forbids steering and position writes.</summary>
    public bool PropActionDriven { get; set; }
    /// <summary>Task 57: preparation blocks input; owned prop movement requests an awaited explicit cancellation.</summary>
    public bool PropPreparationPending { get; set; }
    public Action? ReleasePropAction { get; set; }
    public Action<P2>? SteeringInput { get; set; }
    public double Clock => _clock;
    public bool PendingSnap { get; set; }
    public string RoomId { get; set; } = "";
    public P2? Route { get; private set; }
    public int StalledFrames { get; private set; }
    public sealed record OwnedMove(Vector3 Goal, double Until);
    public OwnedMove? VerticalRide { get; set; }
    public OwnedMove? WalkIn { get; set; }
    public OwnedMove? Correction { get; set; }
    public Action? LoadingPlace { get; set; }
    /// <summary>Local stand-up notification; the activity write and stale-seat reconciliation are E7-T7.</summary>
    public Action? StandUp { get; set; }
    /// <summary>Task 52: authoritative seat ownership, reset for each seat so repeated sit/stand cycles work.</summary>
    public bool AvatarSeated { get; private set; }
    public bool SeatWritePending { get; set; }
    /// <summary>Task 52: taking a new seat holds input; getting up waits only for the local bridge, not the network.</summary>
    public bool SeatTakingPending { get; set; }
    public void SetSeated(bool seated) { if(seated && !AvatarSeated) _stoodUp=false; AvatarSeated=seated; }
    private readonly List<(P2 At, double Until)> _refused = new();
    private bool _clipOverride, _bridgeHeld, _stoodUp;
    private double _clock, _nextLoadingToast;
    private Figure? Avatar => figures.Figures.GetValueOrDefault(figures.AvatarName);
    private JsonElement? Map => figures.LatestMap ?? world.FirstMap;

    public void SetActive(bool active)
    {
        if (Active == active) return;
        Active = active;
        figures.SetPlayerDriven(active ? figures.AvatarName : null);
        if (!active)
        {
            CancelRoute(); VerticalRide = WalkIn = Correction = null;
            if (Avatar is { } f) { f.Ride=null; f.Target=f.Position; }
            _clipOverride=_bridgeHeld=_stoodUp=false;
            world.ClearPlayerApproach();
        }
    }

    public void CancelRoute() { Route=null; StalledFrames=0; figures.SetWalkTarget(null); }

    /// <summary>Task 49: skip any refusal disc that would swallow the accepted home; bound memory to eight/four seconds.</summary>
    public void RememberRefused(P2 point, P2? home)
    {
        if (home is { } h && double.Hypot(point.X-h.X,point.Z-h.Z)<=RefusedRadiusM) return;
        _refused.RemoveAll(r => r.Until<=_clock);
        _refused.Add((point,_clock+RefusedMemoryS));
        if (_refused.Count>RefusedMax) _refused.RemoveAt(0);
    }

    private bool Blocked(LocationSlot? mine, double x, double z, P2? from = null)
    {
        if (world.PlayerBlocked(mine,x,z,from,Map)) return true;
        foreach (var r in _refused)
            if (r.Until>_clock && double.Hypot(x-r.At.X,z-r.At.Z)<RefusedRadiusM) return true;
        return false;
    }

    /// <summary>Task 49: draped terrain outdoors, the figure-height plane indoors; preserve the browser's plane fallback.</summary>
    public bool OnGroundRay(Vec3 origin, Vec3 direction)
    {
        if (Avatar is not { } f) return false;
        Vec3? hit=world.FootprintAt(f.Position.X,f.Position.Z) is null && world.Height is { } height
            ? GroundRay.Hit(height,origin,direction) : null;
        if (hit is null && Math.Abs(direction.Y)>1e-9)
        {
            double t=(f.Position.Y-origin.Y)/direction.Y;
            if (t>=0) hit=new(origin.X+t*direction.X,f.Position.Y,origin.Z+t*direction.Z);
        }
        return hit is { } p && OnGroundClick(new(p.X,p.Z));
    }

    public bool OnGroundClick(P2 hit)
    {
        if (Active && !MovementLocked && !PropPreparationPending && PropActionDriven) { ReleasePropAction?.Invoke(); return false; }
        if (!Active || MovementLocked || PropPreparationPending || VerticalRide is not null || WalkIn is not null || PendingSnap || Avatar is not { } f)
        { if (PendingSnap) ToastLoading(); return false; }
        var pos=new P2(f.Position.X,f.Position.Z);
        var mine=world.FootprintAt(pos.X,pos.Z);
        if (ClickMove.PlanClickWalk(pos,hit,(x,z)=>Blocked(mine,x,z)) is not { } goal) return false;
        Route=goal; StalledFrames=0;
        figures.SetWalkTarget(new((float)goal.X,(float)world.PlayerFloorY(mine,RoomId,goal.X,goal.Z),(float)goal.Z));
        return true;
    }

    private void ToastLoading()
    {
        if (_clock<_nextLoadingToast) return;
        _nextLoadingToast=_clock+4; LoadingPlace?.Invoke();
    }

    /// <summary>Task 49: ordering matches main.ts; held bridges suppress both goal and facing until the snap on release.</summary>
    public void Step(double dt, IReadOnlySet<string> keys, double yaw)
    {
        _clock+=dt;
        if (!Active) { CancelRoute(); VerticalRide=WalkIn=Correction=null; return; }
        if (PendingSnap) { ToastLoading(); return; }
        if (PropPreparationPending) { CancelRoute(); return; }
        if (PropActionDriven) { CancelRoute(); if (!MovementLocked && Walk.WalkDir(keys,yaw) is not null) ReleasePropAction?.Invoke(); return; }
        if (SeatTakingPending) return;
        if (!figures.ServerDriven) figures.TakePlayerTravel(figures.AvatarName);
        if (Avatar is not { } f) return;
        if (MovementLocked) { CancelRoute(); f.Target=f.Position; return; }
        var pos=f.Position;
        bool Arrived(OwnedMove move,double radius,bool height) =>
            double.Hypot(pos.X-move.Goal.X,pos.Z-move.Goal.Z)<radius && (!height || Math.Abs(pos.Y-move.Goal.Y)<radius);
        if (VerticalRide is { } ride)
        {
            if (!Arrived(ride,.2,true) && _clock<=ride.Until) return;
            VerticalRide=null; f.Ride=null;
        }
        if (WalkIn is { } walkIn)
        {
            if (!Arrived(walkIn,.3,false) && _clock<=walkIn.Until) return;
            WalkIn=null;
        }
        if (Correction is { } correction)
        {
            if (!Arrived(correction,PositionChannel.CorrectArriveM,false) && _clock<=correction.Until) return;
            Correction=null;
        }
        P2? dir=Walk.WalkDir(keys,yaw);
        if (dir is not null) CancelRoute();
        double reach=double.PositiveInfinity;
        var from=new P2(pos.X,pos.Z);
        if (dir is null && Route is { } goal)
        {
            if (ClickMove.ReachedGoal(from,goal)) CancelRoute();
            else if (ClickMove.GoalDir(from,goal) is { } to) { dir=new(to.X,to.Z); reach=to.Dist; }
            else CancelRoute();
        }
        if (dir is not null) SteeringInput?.Invoke(from);
        if (figures.ServerDriven) return;
        if (dir is not null && !_stoodUp && (AvatarSeated || figures.LastPlans.GetValueOrDefault(f.CharacterName)?.Rule is "seat" or "pool"))
        {
            _stoodUp=true; AvatarSeated=false; f.Face=null; f.Lean=null; f.SurfaceGroup="ground"; f.ApplyRotation();
            // Task 49 / groundAvatarGoal: even a released key must land the get-up on the floor, not seat height.
            double floor=world.PlayerFloorY(world.FootprintAt(pos.X,pos.Z),RoomId,pos.X,pos.Z);
            figures.SetPlayerTarget(f.CharacterName,new(pos.X,(float)floor,pos.Z));
            StandUp?.Invoke();
        }
        string walking=FigureClips.PoseKind("walking",f.Poses);
        if (dir is not null) { figures.SetPlayerAnimation(f.CharacterName,walking); _clipOverride=true; }
        else if (_clipOverride)
        {
            figures.SetPlayerAnimation(f.CharacterName,null); _clipOverride=false;
            if (f.BridgePace>0) f.CancelBridge();
        }
        if (dir is { } facing)
        {
            double limit=f.Player is null ? 1 : f.PaceLimitFor(walking);
            if (limit<=0) { _bridgeHeld=true; dir=null; }
            else if (limit<1) { f.FaceTowards(new((float)facing.X,0,(float)facing.Z),snap:true); _bridgeHeld=false; }
        }
        if (_bridgeHeld && dir is { } released)
        { f.FaceTowards(new((float)released.X,0,(float)released.Z),snap:true); _bridgeHeld=false; }
        if (dir is not { } direction) return;
        var here=world.FootprintAt(pos.X,pos.Z);
        var raw=world.FigureGroundMove(pos.X,pos.Z);
        double pace=WalkGround.TerrainPace(raw.Speed,raw.Scope);
        double lead=Math.Min(Math.Max(NpcWalk.WalkSpeed*dt,MinLead),reach);
        var target=new P2(pos.X+direction.X*lead,pos.Z+direction.Z*lead);
        target=Walk.SlideBlocked(from,target,(x,z)=>Blocked(here,x,z,from));
        if (world.PlayerWalls(here,RoomId) is { } walls)
            target=Collide.ClampAgainstWalls(from,target,walls.Segments,walls.Radius);
        if (Route is not null)
        {
            StalledFrames=ClickMove.WalkStalled(from,target) ? StalledFrames+1 : 0;
            if (StalledFrames>=ClickMove.StallFrames) CancelRoute();
        }
        if (world.HoldPlayerApproach(target.X,target.Z)) { target=from; ToastLoading(); }
        figures.SetPlayerTarget(f.CharacterName,new((float)target.X,(float)world.PlayerFloorY(here,RoomId,target.X,target.Z),(float)target.Z),pace);
    }
}
