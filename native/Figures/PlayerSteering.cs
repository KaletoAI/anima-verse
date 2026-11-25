using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Tasks 49/50 / E7-T4/T5: main.ts steering targets; FigureManager remains the single movement/animation
/// pipeline. AvatarPositionController supplies corrections, server handoff and refusal answers; later room/offer
/// tasks supply rides, walk-ins and activity writes.
/// Plan E2 Task 6: inside a building with a ready navigation a click walk follows a <see cref="Nav.NavRoute"/> over
/// the navmesh (stairs and lift links ride through <see cref="RideLink"/>), and every step there is clamped to the
/// mesh (<see cref="NavClamp"/>); without a navigation route the straight walk of today stays. Checks: --check nav A0–A7.
/// </summary>
public sealed class PlayerSteering(FigureManager figures, WorldBuilder world)
{
    public const double MinLead = .15, RefusedRadiusM = .8, RefusedMemoryS = 4;
    public const int RefusedMax = 8;
    public bool Active { get; private set; }
    public bool MovementLocked { get; set; }
    /// <summary>Task 50 / Task 57 hook: authoritative prop entry/approach forbids steering and position writes.</summary>
    public bool PropActionDriven { get; set; }
    /// <summary>Task 57 / plan E3 Task 6: input while the avatar plays its furniture order or run asks to let go of it.</summary>
    public Action? ReleasePropAction { get; set; }
    public Action<P2>? SteeringInput { get; set; }
    public double Clock => _clock;
    /// <summary>Measures the time from a click walk or a picked prop offer to the avatar's first centimetre.</summary>
    public FirstStepProbe FirstStep { get; } = new();
    public bool PendingSnap { get; set; }
    public string RoomId { get; set; } = "";
    /// <summary>The click walk's end goal, in both modes (the straight target or the navmesh plan's goal).</summary>
    public P2? Route { get; private set; }
    /// <summary>The navmesh route being followed (plan E2 Task 6); null on a straight walk.</summary>
    public NavRoute? NavRoute { get; private set; }
    /// <summary>Rides one link of the route (stairs or lift hop, by owner id); true = the ride started.</summary>
    public Func<ulong, Task<bool>>? RideLink { get; set; }
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
    private LocationSlot? _navSlot;
    private Task<bool>? _rideTask;
    private bool _linkRiding;
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

    /// <summary>Ends the click walk in both modes (straight and navmesh) and forgets a pending link ride answer.</summary>
    public void CancelRoute()
    {
        NavRoute=null; _navSlot=null; _rideTask=null; _linkRiding=false;
        CancelStraightRoute();
    }

    /// <summary>Clears only the straight route state and the walk marker; a navmesh route rides on (the link ride).</summary>
    public void CancelStraightRoute() { Route=null; StalledFrames=0; figures.SetWalkTarget(null); }

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

    /// <summary>
    /// Plan a click walk or an object action's approach (stairs, lifts or props). <paramref name="level"/> is the storey the
    /// click aimed at (the ground click passes the location's storey view; null = the avatar's own storey). Order: the
    /// locks of today, the refusal discs and gates (<c>Blocked</c>), then — with the footprint's navigation ready — a
    /// navmesh plan; no plan with start AND goal inside the footprint refuses (false), else the straight walk of today.
    /// </summary>
    public bool WalkTo(P2 hit, int? level = null)
    {
        if (Active && !MovementLocked && PropActionDriven) { ReleasePropAction?.Invoke(); return false; }
        if (!Active || MovementLocked || VerticalRide is not null || WalkIn is not null || PendingSnap || Avatar is not { } f)
        { if (PendingSnap) ToastLoading(); return false; }
        var pos=new P2(f.Position.X,f.Position.Z);
        var mine=world.FootprintAt(pos.X,pos.Z);
        if (ClickMove.PlanClickWalk(pos,hit,(x,z)=>Blocked(mine,x,z)) is not { } goal) return false;
        if (mine is not null && world.NavFor(mine) is { Ready: true } nav)
        {
            var from=new Vec3(f.Position.X,f.Position.Y,f.Position.Z);
            var to=new Vec3(goal.X,NavTargetY(nav,mine,goal,level,f.Position.Y),goal.Z);
            if (PlanNav(nav,mine,from,to) is { } plan)
            {
                CancelRoute();
                NavRoute=new NavRoute(plan); _navSlot=mine;
                Route=new P2(plan.Goal.X,plan.Goal.Z);
                figures.SetWalkTarget(new((float)plan.Goal.X,(float)plan.Goal.Y,(float)plan.Goal.Z));
                FirstStep.Arm("click_walk",_clock,pos.X,pos.Z);
                return true;
            }
            if (world.FootprintAt(goal.X,goal.Z)==mine) return false;   // inside, but no way there (a lock, a wall)
        }
        CancelRoute();
        Route=goal; StalledFrames=0;
        figures.SetWalkTarget(new((float)goal.X,(float)world.PlayerFloorY(mine,RoomId,goal.X,goal.Z),(float)goal.Z));
        FirstStep.Arm("click_walk",_clock,pos.X,pos.Z);
        return true;
    }

    /// <summary>
    /// The height of a click target for the planner: the floor of the aimed storey of the navigation source, else the
    /// storey whose floor is nearest to the avatar; a target outside the footprint stands on the ground there.
    /// </summary>
    private double NavTargetY(LocationNav nav, LocationSlot slot, P2 goal, int? level, double avatarY)
    {
        if (world.FootprintAt(goal.X,goal.Z)!=slot) return world.FigureGroundY(goal.X,goal.Z);
        NavStoreySource? best=null;
        foreach (var s in nav.Source.Storeys)
        {
            if (level is { } lv) { if (s.Level==lv) best=s; continue; }
            if (best is null || Math.Abs(s.FloorY-avatarY)<Math.Abs(best.FloorY-avatarY)) best=s;
        }
        return best?.FloorY ?? world.PlayerFloorY(slot,RoomId,goal.X,goal.Z);
    }

    /// <summary>The planner over the slot's navigation: inside = the slot's own footprint, its outside doors, the ground.</summary>
    private NavPlan? PlanNav(LocationNav nav, LocationSlot slot, Vec3 from, Vec3 to)
        => NavRoutePlanner.Plan(nav,from,to,(x,z)=>world.FootprintAt(x,z)==slot,world.NavOutsideDoors(slot),world.FigureGroundY(to.X,to.Z));

    /// <summary>
    /// The per-frame navmesh clamp of a step (<see cref="NavClamp.Step"/>) with two guards of the walking code: a slide is
    /// never longer than the step asked for (a longer one is the closest mesh point on the FAR side of an obstacle — a
    /// large frame step deep into furniture), and a step the clamp holds tries its two axis parts, the larger first, like
    /// <see cref="Walk.SlideBlocked"/> — so an avatar standing just off the mesh (between the eroded edge and the wall
    /// collision, after a snap or a server position) still slides along the wall without going deeper.
    /// </summary>
    private static P2 ClampToNav(P2 from, P2 to, double y, double storeyM, LocationNav nav)
    {
        P2 Clamp(P2 t)
        {
            var c=NavClamp.Step(from,t,y,storeyM,nav);
            return double.Hypot(c.X-from.X,c.Z-from.Z)>double.Hypot(t.X-from.X,t.Z-from.Z)+1e-9 ? from : c;
        }
        var clamped=Clamp(to);
        if (clamped!=from || to==from) return clamped;
        double dx=to.X-from.X, dz=to.Z-from.Z;
        bool xFirst=Math.Abs(dx)>=Math.Abs(dz);
        foreach (var part in xFirst ? new[]{new P2(to.X,from.Z),new P2(from.X,to.Z)} : new[]{new P2(from.X,to.Z),new P2(to.X,from.Z)})
        {
            if (part==from) continue;
            var c=Clamp(part);
            if (c!=from) return c;
        }
        return from;
    }

    /// <summary>The link ride's answer arrived: tell the route whether the ride started (Review B5: a started ride
    /// has already set <see cref="VerticalRide"/>, so the route waits for it to clear again).</summary>
    private void PollRide()
    {
        if (_rideTask is not { IsCompleted: true } task) return;
        _rideTask=null;
        bool started=task.IsCompletedSuccessfully && task.Result;
        if (NavRoute is not { RideRequested: true } nav) return;
        nav.LinkResult(started);
        _linkRiding=started;
    }

    /// <summary>
    /// One frame of the navmesh route: the direction to its next corner, or null (standing at a link, riding, done).
    /// AtLink asks <see cref="RideLink"/> once; Replan plans again to the same goal (keeping the stuck count, so the
    /// second time stuck aborts even across replans); Abort and Arrived end the route.
    /// </summary>
    private ClickMove.Direction? FollowNav(NavRoute route, Figure f, double dt)
    {
        if (_rideTask is not null) return null;            // the ride's answer is still on its way
        if (_linkRiding)
        {
            if (VerticalRide is not null) return null;
            _linkRiding=false;
            route.LinkFinished();
        }
        var here=new Vec3(f.Position.X,f.Position.Y,f.Position.Z);
        switch (route.Tick(here,dt))
        {
            case NavRouteEvent.AtLink:
                if (route.Current is NavLink link && RideLink is { } ride) { _rideTask=ride(link.Owner); PollRide(); }
                else route.LinkResult(false);
                return null;
            case NavRouteEvent.Replan:
                // The stuck count carries over (final review E2, I-2): only WalkTo starts a fresh one.
                if (_navSlot is { } slot && world.NavFor(slot) is { Ready: true } nav && PlanNav(nav,slot,here,route.Final) is { } plan)
                { NavRoute=route=new NavRoute(plan,route.StuckCount); break; }
                CancelRoute();
                return null;
            case NavRouteEvent.Abort:
            case NavRouteEvent.Arrived:
                CancelRoute();
                return null;
        }
        return route.Next is { } next ? ClickMove.GoalDir(new P2(here.X,here.Z),new P2(next.X,next.Z)) : null;
    }

    private void SampleFirstStep()
    {
        if (!FirstStep.Armed || Avatar is not { } a) return;
        if (FirstStep.Sample(_clock,a.Position.X,a.Position.Z) is not { } r) return;
        GD.Print(r.LatencyMs is { } ms
            ? $"[native] first_step source={r.Source} ms={ms.ToString("0.0",CultureInfo.InvariantCulture)} frames={r.Frames.ToString(CultureInfo.InvariantCulture)}"
            : $"[native] first_step source={r.Source} timeout");
    }

    private void ToastLoading()
    {
        if (_clock<_nextLoadingToast) return;
        _nextLoadingToast=_clock+4; LoadingPlace?.Invoke();
    }

    /// <summary>Task 49: ordering matches main.ts; held bridges suppress both goal and facing until the snap on release.</summary>
    private bool _sprintLogged;

    public void Step(double dt, IReadOnlySet<string> keys, double yaw)
    {
        using var hitch = AnimaNative.Ui.HitchLog.Time("PlayerSteering");
        _clock+=dt;
        SampleFirstStep();
        if (!Active) { CancelRoute(); VerticalRide=WalkIn=Correction=null; return; }
        if (PendingSnap) { ToastLoading(); return; }
        if (PropActionDriven) { CancelRoute(); if (!MovementLocked && Walk.WalkDir(keys,yaw) is not null) ReleasePropAction?.Invoke(); return; }
        if (SeatTakingPending) return;
        if (!figures.ServerDriven) figures.TakePlayerTravel(figures.AvatarName);
        if (Avatar is not { } f) return;
        if (MovementLocked) { CancelRoute(); f.Target=f.Position; return; }
        PollRide();
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
        var keyDir=Walk.WalkDir(keys,yaw);
        // SHIFT RUNS — only while the keys walk the figure; a click order walks (walk.ts sprintHeld).
        bool sprint=Walk.SprintHeld(keys,keyDir);
        if (sprint!=_sprintLogged)
        { _sprintLogged=sprint; Godot.GD.Print($"[steer] run {(sprint ? "on" : "off")} keys=[{string.Join(",",keys)}]"); }
        P2? dir=keyDir;
        if (dir is not null) CancelRoute();
        double reach=double.PositiveInfinity;
        var from=new P2(pos.X,pos.Z);
        if (dir is null && NavRoute is { } route)
        {
            if (FollowNav(route,f,dt) is { } to) { dir=new(to.X,to.Z); reach=to.Dist; }
        }
        else if (dir is null && Route is { } goal)
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
        // Renewed keys interrupt only a stop bridge, before PaceLimitFor can hold this frame.
        if (keyDir is not null) f.CancelStopBridge(walking);
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
        // The run boost widens the lead with the step: the step is capped at the lead.
        double lead=Math.Min(Math.Max(NpcWalk.WalkSpeed*(sprint ? NpcWalk.RunFactor : 1)*dt,MinLead),reach);
        var target=new P2(pos.X+direction.X*lead,pos.Z+direction.Z*lead);
        target=Walk.SlideBlocked(from,target,(x,z)=>Blocked(here,x,z,from));
        if (world.PlayerWalls(here,RoomId) is { } walls)
            target=Collide.ClampAgainstWalls(from,target,walls.Segments,walls.Radius);
        // Plan E2 Task 6: inside the footprint the step stays on the navmesh of the avatar's storey.
        if (here is not null && world.NavFor(here) is { Ready: true } navMap && f.Ride is null && world.FootprintAt(target.X,target.Z)==here)
            target=ClampToNav(from,target,f.Position.Y,here.Scene is { StoreyM: > 0 } sc ? sc.StoreyM : 3,navMap);
        // The 20-frame stall belongs to the straight walk; a navmesh route watches itself (NavRoute.Tick).
        if (Route is not null && NavRoute is null)
        {
            StalledFrames=ClickMove.WalkStalled(from,target) ? StalledFrames+1 : 0;
            if (StalledFrames>=ClickMove.StallFrames) CancelRoute();
        }
        if (world.HoldPlayerApproach(target.X,target.Z)) { target=from; ToastLoading(); }
        figures.SetPlayerTarget(f.CharacterName,new((float)target.X,(float)world.PlayerFloorY(here,RoomId,target.X,target.Z),(float)target.Z),pace,sprint);
    }
}
