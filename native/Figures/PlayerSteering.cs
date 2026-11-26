using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Tasks 49/50 / E7-T4/T5: main.ts steering targets; FigureManager remains the single movement/animation
/// pipeline. AvatarPositionController supplies corrections, server handoff and refusal answers; later room/offer
/// tasks supply rides, walk-ins and activity writes.
/// Plan E2 Task 6 / E3 Task 10: inside a building with a ready navigation a click walk is a local <c>walk</c> order
/// (<see cref="FigureManager.StartClickWalk"/>) the avatar's order player walks over the click planner's path
/// (<see cref="ClickWalkPath"/>; stairs and lift links ride through <see cref="FigureManager.AvatarLinkRide"/>); every
/// key step there is clamped to the mesh (<see cref="NavClamp"/>). Outside every navigation the straight walk of today
/// stays (<see cref="ClickMove"/>, its gates and its 20-frame stall), and it takes the rest of a click out of the building
/// at the outside door's point. A walk key ends the click's order (<c>Refuse("input")</c>, no turn-away) — except during
/// a link ride of the order (<see cref="LinkRiding"/>), which holds keys and clicks. Checks: --check nav A0–A8.
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
    /// <summary>
    /// The click walk's end goal, in both modes (the straight target, or the planned goal of the click's walk order while
    /// that order is played).
    /// </summary>
    public P2? Route => _walkOrder is not null ? WalkOrderId is not null ? _handoff ?? _orderGoal : null : _straightGoal;
    /// <summary>The click's local walk order while the avatar plays it (plan E3 Task 10); null on a straight walk.</summary>
    public string? WalkOrderId => _walkOrder is { } id && figures.ClickWalkLive(id) ? id : null;
    /// <summary>
    /// The planned goal of the click's walk order (3D) while it is played; for a click out of the building the outside
    /// door's point where the order hands over to the straight walk (<see cref="Route"/> stays the click).
    /// </summary>
    public Vec3? WalkGoal => WalkOrderId is not null ? _orderGoal3 : null;
    /// <summary>
    /// The click's walk order stands at a stair or lift link whose ride is requested or running
    /// (<see cref="FigureManager.ClickWalkRiding"/>): keys and clicks are held like during <see cref="VerticalRide"/>.
    /// </summary>
    public bool LinkRiding => WalkOrderId is { } id && figures.ClickWalkRiding(id);
    /// <summary>A vertical move owns the avatar: the E2 offer ride (<see cref="VerticalRide"/>) or a click walk's link ride.</summary>
    public bool Riding => VerticalRide is not null || LinkRiding;
    /// <summary>
    /// How close to the outside door's point the click's walk order must have ended for the straight walk to take the rest
    /// of a click out of the building: the order's arrival tolerance (<see cref="OrderPlayer.ArriveTolM"/>, 0.15 m) plus the
    /// straight walk's goal radius (<see cref="ClickMove.GoalArriveM"/>, 0.2 m).
    /// </summary>
    public const double HandoffM = OrderPlayer.ArriveTolM + ClickMove.GoalArriveM;
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
    /// <summary>The ids of the click walk orders (<c>local:&lt;n&gt;</c>), apart from the offers' and the room walks' counters.</summary>
    private int _clickWalks = 2_000_000;
    private string? _walkOrder;
    private ClickWalkPath? _walkPath;
    private P2 _orderGoal;
    private Vec3 _orderGoal3;
    private P2? _straightGoal;
    /// <summary>The click outside the footprint the straight walk takes over at the outside door (null inside).</summary>
    private P2? _handoff;
    private Vector3 _handoffMarker;
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

    /// <summary>
    /// Ends the click walk in both modes: the click's walk order is refused with <paramref name="reason"/> and let go
    /// where it stands (<see cref="FigureManager.EndClickWalk"/>), the straight goal and the walk marker are cleared.
    /// </summary>
    public void CancelRoute(string reason = "cancel")
    {
        if (_walkOrder is { } id) figures.EndClickWalk(id,reason);
        _walkOrder=null; _walkPath=null; _handoff=null;
        _straightGoal=null; StalledFrames=0; figures.SetWalkTarget(null);
    }

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
    /// A click out of the building (planner case 2) is the walk order to the outside door's point only; from there the
    /// straight walk takes the rest with its gates (<c>Blocked</c>, the walls, the loading hold, the terrain pace and its
    /// 20-frame stall), as every E2 route step had them — out in the open the order has no map to hold it.
    /// No click while a link ride of the click walk runs (<see cref="LinkRiding"/>).
    /// </summary>
    public bool WalkTo(P2 hit, int? level = null)
    {
        if (Active && !MovementLocked && PropActionDriven) { ReleasePropAction?.Invoke(); return false; }
        if (!Active || MovementLocked || Riding || WalkIn is not null || PendingSnap || Avatar is not { } f)
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
                bool outside=world.FootprintAt(plan.Goal.X,plan.Goal.Z)!=mine;
                var door=outside ? DoorOf(plan,world.NavOutsideDoors(mine)) : null;
                var orderGoal=door is { } d ? new Vec3(d.X,world.FigureGroundY(d.X,d.Z),d.Z) : plan.Goal;
                if (!StartWalkOrder(f,mine,orderGoal,level,door))
                { GD.Print($"[steer] click walk to ({goal.X:0.##}, {goal.Z:0.##}) not taken by the avatar's order player"); return false; }
                var marker=new Vector3((float)plan.Goal.X,(float)plan.Goal.Y,(float)plan.Goal.Z);
                if (door is not null) { _handoff=new P2(plan.Goal.X,plan.Goal.Z); _handoffMarker=marker; }
                figures.SetWalkTarget(marker);
                FirstStep.Arm("click_walk",_clock,pos.X,pos.Z);
                return true;
            }
            if (world.FootprintAt(goal.X,goal.Z)==mine) return false;   // inside, but no way there (a lock, a wall)
        }
        CancelRoute();
        _straightGoal=goal; StalledFrames=0;
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

    /// <summary>
    /// Plan E3 Task 10: the click's local walk order (<see cref="LocalOrders.Walk"/>) at the avatar's walking speed to the
    /// planned goal, on the click planner's path over the slot's navigation (<see cref="ClickWalkPath"/>, read live: a
    /// rebake swaps the map). True when the avatar took it.
    /// </summary>
    private bool StartWalkOrder(Figure f, LocationSlot slot, Vec3 goal, int? level, P2? door = null)
    {
        double yaw=f.Yaw*180/Math.PI;
        var start=new OrderPoint(f.Position.X,f.Position.Y,f.Position.Z,yaw);
        // A walk to an outside door's point goes out through that door only (also on a replan): no other door's way.
        var doors=door is { } only ? new[] { only } : world.NavOutsideDoors(slot);
        var path=new ClickWalkPath(()=>world.NavFor(slot),(x,z)=>world.FootprintAt(x,z)==slot,doors,world.FigureGroundY);
        int here=slot.Stands.RoomLevels.TryGetValue(RoomId,out var l) ? l : 0;
        var order=LocalOrders.Walk(++_clickWalks,figures.MotionNow,NpcWalk.WalkSpeed,f.CharacterName,start,RoomId,here,
                                   new OrderPoint(goal.X,goal.Y,goal.Z,yaw),slot.Loc.Id,"",level ?? here);
        if (!figures.StartClickWalk(order,path)) return false;
        _walkOrder=order.Id; _walkPath=path;
        _orderGoal=new P2(goal.X,goal.Z); _orderGoal3=goal;
        return true;
    }

    /// <summary>
    /// The outside door a plan out of the building leaves through (planner case 2: the navmesh path to the door's outer
    /// point, then straight to the click): the outer point (<see cref="WorldBuilder.NavOutsideDoors"/>) nearest to the
    /// path's corner before the click, within <see cref="NavRoutePlanner.UnreachableM"/> of it like the planner's own
    /// reach rule. Null when the plan does not end in a walk of at least two corners or no door is that close.
    /// </summary>
    private static P2? DoorOf(NavPlan plan, IReadOnlyList<P2> doors)
    {
        if (plan.Steps.Count == 0 || plan.Steps[^1] is not NavWalk { Points.Count: >= 2 } last) return null;
        var end=last.Points[^2];
        P2? best=null; double bestD=NavRoutePlanner.UnreachableM;
        foreach (var d in doors)
        {
            double dist=double.Hypot(d.X-end.X,d.Z-end.Z);
            if (dist<=bestD) { best=d; bestD=dist; }
        }
        return best;
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
        // A click walk's link ride (requested or running) owns the avatar like the E2 ride did: keys wait for its end.
        if (LinkRiding) return;
        var keyDir=Walk.WalkDir(keys,yaw);
        // SHIFT RUNS — only while the keys walk the figure; a click order walks (walk.ts sprintHeld).
        bool sprint=Walk.SprintHeld(keys,keyDir);
        if (sprint!=_sprintLogged)
        { _sprintLogged=sprint; Godot.GD.Print($"[steer] run {(sprint ? "on" : "off")} keys=[{string.Join(",",keys)}]"); }
        P2? dir=keyDir;
        // A walk key ends the click's walk order where it stands (no turn-away) and walks on from there.
        if (dir is not null) CancelRoute("input");
        double reach=double.PositiveInfinity;
        var from=new P2(pos.X,pos.Z);
        // The click's walk order draws the figure (FigureManager.TickOrder); it is over at its goal, at a refused link
        // ride or stuck, and when its navigation went away. Ended at the outside door's point of a click out of the
        // building, the straight walk takes the rest (WalkTo).
        bool orderWalking=false;
        if (_walkOrder is not null)
        {
            if (WalkOrderId is null || _walkPath is not { Ready: true })
            {
                var handoff=WalkOrderId is null && _handoff is { } h && double.Hypot(from.X-_orderGoal.X,from.Z-_orderGoal.Z)<=HandoffM ? h : (P2?)null;
                var marker=_handoffMarker;
                CancelRoute();
                if (handoff is { } rest) { _straightGoal=rest; figures.SetWalkTarget(marker); }
            }
            else orderWalking=true;
        }
        if (!orderWalking && dir is null && _straightGoal is { } goal)
        {
            if (ClickMove.ReachedGoal(from,goal)) CancelRoute();
            else if (ClickMove.GoalDir(from,goal) is { } to) { dir=new(to.X,to.Z); reach=to.Dist; }
            else CancelRoute();
        }
        if (dir is not null || orderWalking) SteeringInput?.Invoke(from);
        if (figures.ServerDriven) return;
        if ((dir is not null || orderWalking) && !_stoodUp && (AvatarSeated || figures.LastPlans.GetValueOrDefault(f.CharacterName)?.Rule is "seat" or "pool"))
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
        // The 20-frame stall belongs to the straight walk; the click's walk order watches itself (OrderWalk).
        if (_straightGoal is not null)
        {
            StalledFrames=ClickMove.WalkStalled(from,target) ? StalledFrames+1 : 0;
            if (StalledFrames>=ClickMove.StallFrames) CancelRoute();
        }
        if (world.HoldPlayerApproach(target.X,target.Z)) { target=from; ToastLoading(); }
        figures.SetPlayerTarget(f.CharacterName,new((float)target.X,(float)world.PlayerFloorY(here,RoomId,target.X,target.Z),(float)target.Z),pace,sprint);
    }
}
