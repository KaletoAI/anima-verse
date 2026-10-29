using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Task 51 / E7-T6: main.ts rooms/storeys/stairs/lift glue over the rendered avatar's footprint. RoomEntryChannel
/// owns the single write/deadline, PlayerSteering owns the four-second vertical move, FigureManager owns motion.
/// Ownership: Main creates/disposes this with the figure manager; HUD handlers and hover clones detach here.
/// No nodes or shaders are created by this controller. Polls and position answers remain authoritative rooms.
/// </summary>
public sealed class AvatarRoomsController : IDisposable
{
    private readonly FigureManager _figures;
    private readonly WorldBuilder _world;
    private readonly PlayerSteering _steering;
    private readonly HudOverlay _hud;
    private readonly Func<double> _clock;
    private bool _active,_disposed;
    private int _generation;
    private double _nextOffers;
    private string? _followedLoc;
    private int? _followedLevel;
    private StairPrompt? _stairs;
    private ElevatorState? _elevator;
    public RoomEntryChannel Channel { get; }
    public VerticalPicking Picking { get; }
    public Task? PendingRide { get; private set; }
    public string GroundRoomId { get; set; }="";
    public IReadOnlyDictionary<int,string> FloorRoomIds { get; set; }=new Dictionary<int,string>();
    public IReadOnlyDictionary<string,string> LockedRooms { get; set; }=new Dictionary<string,string>();
    public string LockedLoc { get; set; }="";
    public Action<string?>? AutoOpen { get; set; }
    public Action<string>? AdoptRoom { get; set; }
    public Action<string>? Toast { get; set; }
    private Figure? Avatar => _figures.Figures.GetValueOrDefault(_figures.AvatarName);
    private LocationSlot? Tile => Avatar is { } f ? _world.FootprintAt(f.Position.X,f.Position.Z) : null;
    private bool CanUse => _active && !_disposed && !_steering.MovementLocked && !_steering.PropActionDriven && !_figures.ServerDriven;

    public AvatarRoomsController(FigureManager figures,WorldBuilder world,PlayerSteering steering,IWorldSource source,HudOverlay hud,Func<double>? clock=null)
    {
        _figures=figures; _world=world; _steering=steering; _hud=hud; _clock=clock ?? (()=>source.MonotonicMs);
        Channel=new(source.EnterRoomAsync,_clock) { Toast=message=>Toast?.Invoke(message) };
        Picking=new(world,UsableTargets);
        hud.Handlers["rideStairs"] = RideStairsAction;
        hud.Handlers["rideElevator"] = RideElevatorAction;
        world.Dropped+=Dropped;
    }
    private void RideStairsAction(JsonArray _) => PendingRide=RideStairsAsync();
    private void RideElevatorAction(JsonArray args)
    { if(args.Count>0 && args[0] is JsonValue v && v.TryGetValue<int>(out int level)) PendingRide=RideElevatorAsync(level); }
    private void Dropped(LocationSlot slot) { Picking.Clear(); if(_followedLoc==slot.Loc.Id) { _followedLoc=null; _followedLevel=null; Channel.Idle(); } }

    public void SetActive(bool active)
    {
        if(_active==active) return;
        _active=active; _generation++; _nextOffers=0; Channel.Reset(); _followedLoc=null; _followedLevel=null;
        if(!active) { ClearOffers(); Picking.Clear(); }
    }

    /// <summary>Resolve legacy room names once through the tile's ID table; a foreign raw room resets the hold.</summary>
    private string? Room(LocationSlot tile)
    {
        string raw=_steering.RoomId;
        if(raw.Length==0) return null;
        if(tile.Stands.RoomLevels.ContainsKey(raw) || tile.DetailRooms.ContainsKey(raw)) return raw;
        foreach(var (id,name) in tile.DetailRooms) if(name==raw) return id;
        return null;
    }
    private int? Level(LocationSlot tile,string? room) => room is null || room==GroundRoomId ? 0
        : tile.Stands.RoomLevels.TryGetValue(room,out int level) ? level : null;

    /// <summary>Unique mounted IDs, with corridors marked from HUD floorRoomIds; no duplicate name aliases.</summary>
    private List<ElevatorRoom> Rooms(LocationSlot tile)
    {
        var ids=tile.DetailRooms.Keys.Concat(FloorRoomIds.Values).Distinct();
        return ids.Where(id=>tile.Stands.RoomCenters.ContainsKey(id)).Select(id=>
        {
            var c=tile.Stands.RoomCenters[id];
            return new ElevatorRoom(id,tile.Stands.RoomLevels.GetValueOrDefault(id),new(c.X,c.Z),FloorRoomIds.Values.Contains(id));
        }).ToList();
    }
    private static List<ElevatorStop> Stops(LocationSlot tile) => tile.Places.ElevatorStops.Select(p=>new ElevatorStop(p.Key,new(p.Value.X,p.Value.Z))).ToList();
    private static bool Inside(LocationSlot tile,string id,P2 p)
    {
        var local=SceneView.WorldToTile(tile.Stands.Frame,p.X,p.Z);
        return tile.RoomRects.Any(pair=>pair.Key==id && Math.Abs(local.X-pair.Value.X)<=pair.Value.W/2 && Math.Abs(local.Z-pair.Value.Z)<=pair.Value.D/2);
    }

    /// <summary>Every-frame hysteresis and edge-triggered follow; offers sample at 1 Hz, like the browser.</summary>
    public void Tick()
    {
        if(!_active || _disposed) { Channel.Idle(); return; }
        if(Avatar is not { } figure) { Channel.Idle(); ClearOffers(); return; }
        var tile=Tile; var room=tile is null ? null : Room(tile);
        var p=new P2(figure.Position.X,figure.Position.Z);
        bool open=tile?.Openable==true;
        bool groundModel=tile?.Scene?.Models.Any(m=>m.Role=="building" && m.Display=="ground")==true;
        bool planHull=tile?.Scene?.Models.Any(m=>m.Role=="building" && m.PlanHull)==true;
        if(tile is not null && (groundModel || planHull))
        {
            var local=SceneView.WorldToTile(tile.Stands.Frame,p.X,p.Z);
            string? under=Ambience.RoomAtRects(tile.RoomRects,local.X,local.Z);
            if(under is null && !groundModel && planHull) under=Ambience.CorridorAtOutline(tile.Corridors,local.X,local.Z);
            open &= under is not null && !tile.Stands.AlwaysVisible.Contains(under);
        }
        AutoOpen?.Invoke(open ? tile!.Loc.Id : null);
        if(tile is null) { _followedLoc=null; _followedLevel=null; Channel.Idle(); ClearOffers(); return; }
        if(tile.Loc.Id!=_followedLoc) { _followedLoc=tile.Loc.Id; _followedLevel=null; }
        if(Level(tile,room) is { } level && level!=_followedLevel)
        { _followedLevel=level; _world.SetLevel(tile.Loc.Id,level); }
        bool interior=tile.Open;
        if(!CanUse || !(interior || tile.Fade.ShellArea || tile.Stands.AlwaysVisible.Count>0) || (room is null && _steering.RoomId.Length>0)) Channel.Idle();
        else
        {
            var locks=tile.Loc.Id==LockedLoc ? LockedRooms : new Dictionary<string,string>();
            string Unlocked(string id) => id==room || !Locks.IsLocked(locks,id) ? id : "";
            var candidates=Locks.UnlockedRooms(Rooms(tile).Where(r=>interior || tile.Stands.AlwaysVisible.Contains(r.Id)),locks,r=>r.Id,room ?? "");
            int? ownLevel=room is null ? null : Level(tile,room);
            var local=SceneView.WorldToTile(tile.Stands.Frame,p.X,p.Z);
            var rooms=RoomWalk.RoomWalkCandidates(ownLevel,p,candidates,id=>Inside(tile,id,p),
                lv=>tile.Corridors.Any(c=>c.Level==lv && SceneView.PointInPolygon(local.X,local.Z,c.Outline)),Unlocked(GroundRoomId),
                lv=>FloorRoomIds.TryGetValue(lv,out string? id) && tile.Stands.RoomLevels.ContainsKey(id) ? Unlocked(id) : "");
            Channel.Walk(room,p,rooms,ownLevel ?? tile.LevelFilter);
        }
        if(!CanUse || _steering.VerticalRide is not null) { ClearOffers(); Picking.Clear(); }
        else if(_clock()>=_nextOffers) { _nextOffers=_clock()+1000; UpdateOffers(); }
    }

    public void UpdateOffers()
    {
        var tile=Tile;
        if(!CanUse || tile?.Open!=true || Avatar is not { } f || _steering.VerticalRide is not null || Room(tile) is not { } room)
        { ClearOffers(); return; }
        var p=new P2(f.Position.X,f.Position.Z); int level=Level(tile,room) ?? 0;
        var rooms=Rooms(tile);
        _stairs=Stairs.StairsAt(p,level,tile.Places.Stairs,1);
        if(_stairs is { } stairs && Elevator.NearestRoomAt(stairs.Dest.Level,new(stairs.Dest.Pos.X,stairs.Dest.Pos.Z),rooms) is null) _stairs=null;
        _elevator=Elevator.At(p,level,Stops(tile),rooms,1);
        _hud.SetState("stairs",_stairs is { } s ? new JsonObject { ["dir"]=s.Dir,["dist"]=s.Dist,["dest"]=new JsonObject
            { ["level"]=s.Dest.Level,["x"]=s.Dest.Pos.X,["y"]=s.Dest.Pos.Y,["z"]=s.Dest.Pos.Z } } : null);
        _hud.SetState("elevator",_elevator is { } e ? new JsonObject { ["current"]=e.Current,["dist"]=e.Dist,
            ["levels"]=new JsonArray(e.Levels.Select(l=>(JsonNode?)JsonValue.Create(l)).ToArray()) } : null);
        SyncElevatorPicker();
    }
    private void ClearOffers()
    { _stairs=null; _elevator=null; _hud.SetState("stairs",null); _hud.SetState("elevator",null); _hud.SetState("elevatorOpen",false); }

    /// <summary>Run after all offers publish; an invisible picker must never capture Escape.</summary>
    public void SyncElevatorPicker()
    {
        double? Dist(string field) => _hud.SceneOwned(field)?["dist"]?.GetValue<double>();
        if(_hud.SceneOwned("elevatorOpen")?.GetValue<bool>()==true && Offers.NearestOffer(Dist("talkTarget"),Dist("elevator"),Dist("stairs"),Dist("enterOffer"))!="elevator")
            _hud.SetState("elevatorOpen",false);
    }

    public Task RideStairsAsync()
    {
        if(!CanUse || _stairs is not { } s || Tile is not { } tile) return Task.CompletedTask;
        string? target=Elevator.NearestRoomAt(s.Dest.Level,new(s.Dest.Pos.X,s.Dest.Pos.Z),Rooms(tile));
        var leg=Stairs.LegTo(tile.Places.Stairs,s.Dest);
        return RideAsync(tile,target,s.Dest.Level,s.Dest.Pos,leg is null ? null : new StairRide { Legs=new[]{leg},Leg=0,Armed=true });
    }
    public Task RideElevatorAsync(int level)
    {
        if(!CanUse || _elevator is not { } e || !Elevator.Options(e).Contains(level) || Tile is not { } tile || !tile.Places.ElevatorStops.TryGetValue(level,out var stop)) return Task.CompletedTask;
        _hud.SetState("elevatorOpen",false);
        return RideAsync(tile,Elevator.TargetRoom(level,Stops(tile),Rooms(tile)),level,stop,null);
    }

    /// <summary>Capture identity/generation before await; exit, remount or a foreign footprint cannot revive a ride.</summary>
    private async Task RideAsync(LocationSlot tile,string? target,int level,Vec3 goal,StairRide? stair)
    {
        if(target is null || Avatar is not { } f || Channel.InFlight || Channel.Rejected(target) || _steering.VerticalRide is not null) return;
        int generation=_generation;
        _steering.CancelRoute();
        if(!await Channel.EnterAsync(target,true) || generation!=_generation || !CanUse || Avatar!=f || Tile!=tile
            || !_world.Slots.TryGetValue(tile.Loc.Id,out var mounted) || mounted!=tile) return;
        _steering.RoomId=target; AdoptRoom?.Invoke(target);
        var point=new Vector3((float)goal.X,(float)goal.Y,(float)goal.Z);
        _figures.SetPlayerTarget(f.CharacterName,point);
        _figures.SetStairRide(f.CharacterName,stair);
        _steering.VerticalRide=new(point,_steering.Clock+4);
        _world.SetLevel(tile.Loc.Id,level); _followedLevel=level;
        Channel.Idle(); ClearOffers(); Picking.Clear();
    }

    private Vec3? Stand(LocationSlot tile,int level,VerticalTarget target)
    {
        if(target.Kind=="elevator")
        {
            var levels=Elevator.Levels(Stops(tile),Rooms(tile));
            return levels.Count>=2 && levels.Contains(level) && tile.Places.ElevatorStops.TryGetValue(level,out var stop) ? stop : null;
        }
        if(target.Flight<0 || target.Flight>=tile.Places.Stairs.Count) return null;
        var s=tile.Places.Stairs[target.Flight]; return s.Foot.Level==level ? s.Foot.Pos : s.Head.Level==level ? s.Head.Pos : null;
    }
    private IEnumerable<VerticalTarget> UsableTargets(LocationSlot tile)
    {
        if(!CanUse || tile!=Tile || !tile.Open || _steering.VerticalRide is not null || Room(tile) is not { } room) return Array.Empty<VerticalTarget>();
        return tile.Places.VerticalTargets.Where(t=>Stand(tile,Level(tile,room) ?? 0,t) is not null);
    }

    /// <summary>Out of reach walks to this flight's own landing only; arrival never queues an automatic ride.</summary>
    public void UseVertical(VerticalTarget target)
    {
        if(Tile is not { } tile || !UsableTargets(tile).Contains(target) || Room(tile) is not { } room) return;
        if(target.Kind=="elevator" && _elevator is { } e)
        {
            if(Elevator.SoleOption(e) is { } sole) PendingRide=RideElevatorAsync(sole);
            else _hud.SetState("elevatorOpen",_hud.SceneOwned("elevatorOpen")?.GetValue<bool>()!=true);
            return;
        }
        if(target.Kind=="stairs" && _stairs is { } s && Stairs.LegTo(new[]{tile.Places.Stairs[target.Flight]},s.Dest) is not null)
        { PendingRide=RideStairsAsync(); return; }
        if(Stand(tile,Level(tile,room) ?? 0,target) is { } point) _steering.WalkTo(new(point.X,point.Z));
    }
    public void Dispose()
    {
        if(_disposed) return;
        SetActive(false); _disposed=true; Channel.Dispose(); Picking.Dispose(); _world.Dropped-=Dropped;
        if(_hud.Handlers.GetValueOrDefault("rideStairs")==RideStairsAction) _hud.Handlers.Remove("rideStairs");
        if(_hud.Handlers.GetValueOrDefault("rideElevator")==RideElevatorAction) _hud.Handlers.Remove("rideElevator");
    }
}
