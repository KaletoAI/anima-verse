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
/// Task 52 / E7-T7: main.ts talk/entry glue. Main owns this controller alongside rooms and position;
/// Dispose removes subscriptions, handlers, entry pins and the PlaceTargets node/resource ledger.
/// Published offers feed both SceneKeys/F and the unchanged HUD chip's nearestOffer rule.
/// Prop meshes/actions remain a separate Task 57 pick/menu extension, never room-marker aliases.
/// </summary>
public sealed partial class AvatarOffersController : IDisposable, IEntryDeps
{
    private readonly FigureManager _figures;
    private readonly WorldBuilder _world;
    private readonly PlayerSteering _steering;
    private readonly IWorldSource _source;
    private readonly HudOverlay _hud;
    private readonly AvatarPositionController _position;
    private readonly Func<double> _clock;
    private bool _active,_disposed;
    private int _generation;
    private double _nextOffers;
    private EntryOffer? _entry;
    private string? _entryReason;
    private string? _entryPin;
    private JsonElement? _seatMap;
    private double _seatMapAt;
    private JsonElement? Map => _figures.LatestMap ?? _world.FirstMap;
    private Figure? Avatar => _figures.Figures.GetValueOrDefault(_figures.AvatarName);
    private bool CanUse => _active && !_disposed && !_steering.MovementLocked && !_steering.PropActionDriven && !_figures.ServerDriven;
    private bool CanEnter => CanUse && !RoomRequestInFlight() && !_steering.PendingSnap && !_steering.SeatWritePending
        && !_steering.AvatarSeated && _steering.VerticalRide is null && _steering.WalkIn is null && _steering.Correction is null;
    public Func<bool> RoomRequestInFlight { get; set; }=()=>false;
    public IReadOnlyDictionary<string,string> LockedLocations { get; set; }=new Dictionary<string,string>();
    public Action<string>? Toast { get; set; }
    public Action<string>? OpenLocation { get; set; }
    public Action? RefreshMap { get; set; }
    public Task? PendingEntry { get; private set; }
    public bool HasLockedEntry => _entry is not null && _entryReason is not null;
    public PlaceTargets Places { get; }
    public string? NearestOffer => Offers.NearestOffer(Distance("talkTarget"),Distance("elevator"),Distance("stairs"),Distance("enterOffer"));
    private double? Distance(string field) => _hud.SceneOwned(field)?["dist"]?.GetValue<double>();
    private static string Text(JsonElement row,string field) => row.TryGetProperty(field,out var v) && v.ValueKind==JsonValueKind.String ? v.GetString()! : "";
    private static JsonElement? Self(JsonElement map)
    {
        if(map.TryGetProperty("characters",out var chars))
            foreach(var c in chars.EnumerateArray()) if(Text(c,"name")==Text(map,"avatar")) return c;
        return null;
    }

    public AvatarOffersController(FigureManager figures,WorldBuilder world,PlayerSteering steering,IWorldSource source,
        HudOverlay hud,AvatarPositionController position,Func<double>? clock=null)
    {
        _figures=figures; _world=world; _steering=steering; _source=source; _hud=hud; _position=position;
        _clock=clock ?? (()=>source.MonotonicMs);
        Places=new PlaceTargets(); figures.AddChild(Places);
        hud.LockedEntry=()=>HasLockedEntry;
        hud.Handlers["enterLocation"]=EntryAction;
        hud.Handlers["pickRoomPose"]=PoseAction;
        hud.Handlers["closePlaceMenu"]=CloseMenu;
        steering.StandUp=StandUp;
        figures.PositionMapApplied+=MapApplied;
        world.Dropped+=Dropped;
        hud.Handlers["pairFacing"] = args => {
            if (args.Count == 3 && args[0] is JsonValue phase && phase.TryGetValue<string>(out var p)
                && args[1] is JsonValue id && id.TryGetValue<string>(out var i)
                && args[2] is JsonValue partner && partner.TryGetValue<string>(out var name)) _figures.PairFacing(p, i, name);
        };
        AttachProps();
    }
    private void EntryAction(JsonArray _) => PendingEntry=EnterAsync();
    private void PoseAction(JsonArray args)
    {
        if(args.Count>=2 && args[0] is JsonValue a && a.TryGetValue<string>(out var id)
            && args[1] is JsonValue b && b.TryGetValue<string>(out var pose)) PendingActivity=PickRoomPoseAsync(id,pose);
    }
    private void CloseMenu(JsonArray _) => _hud.SetState("placeMenu",null);
    private void Dropped(LocationSlot slot)
    {
        if(slot==_placeTile) { ClearPlaces(); _seatKey=""; }
        if(slot.Loc.Id==_entry?.LocId) { _generation++; ReleaseEntry(); _entry=null; _hud.SetState("enterOffer",null); }
    }

    public void SetActive(bool active)
    {
        if(_active==active) return;
        _active=active; _generation++; _nextOffers=0; _seatKey="";
        if(!active) { ReleaseEntry(); _entry=null; _entryReason=null; _hud.SetState("talkTarget",null); _hud.SetState("enterOffer",null); ClearPlaces(); }
        else if(Map is { } map)
        {
            _seatMap=map.Clone(); _seatMapAt=MapReceiptTime(map);
            ReconcilePlace(map,_seatMapAt);
            PendingPlaces=RefreshPlacesAsync();
            if(PropActions is not null) PendingPropAction=ObservePropAsync(async ()=> { await RefreshPropStateAsync(); await RefreshSemanticOffersAsync(false); });
            UpdateOffers();
        }
    }
    private double MapReceiptTime(JsonElement map) => _source.ReceiptOf(map)?.PolledAt ?? _clock();
    public Task? PendingPlaces { get; private set; }
    private void MapApplied(JsonElement map,double polledAt)
    {
        if(FigureGround.PollIsStale(polledAt,_position.OwnSeatChangeAt)) return;
        ClearHover();
        _seatMap=map.Clone(); _seatMapAt=polledAt;
        ReconcilePlace(map,polledAt);
        if(_active) { PendingPlaces=RefreshPlacesAsync(); if(PropActions is { Paused:false }) _=RefreshSemanticOffersAsync(false); }
    }
    public void Tick()
    {
        TickProps();
        if(_hud.Ui.MenuOpen || _hud.Ui.OverlayOpen || _hud.SceneOwned("placeMenu") is not null) ClearHover();
        if(!_active || _disposed) return;
        // Rebuilds also follow tier swaps, re-lifts, and streamed room mounts without another server poll.
        RebuildPlaces();
        if(_seatMap is { } map) ReconcilePlace(map,_seatMapAt);
        if(_clock()<_nextOffers) return;
        _nextOffers=_clock()+1000; UpdateOffers();
    }

    /// <summary>Task 52: use live roots and the same shown-room lookup as computeNpcPlacements, skipping hidden bodies.</summary>
    public void UpdateOffers()
    {
        TalkOffer? talk=null;
        if(_active && !_disposed && Avatar is { } f && Map is { } map && Self(map) is { } me)
        {
            string loc=_world.PlaceAt(f.Position.X,f.Position.Z) ?? Text(me,"location_id");
            var others=new List<TalkCandidate>();
            if(map.TryGetProperty("characters",out var chars)) foreach(var c in chars.EnumerateArray())
            {
                string name=Text(c,"name");
                if(name==f.CharacterName || !_figures.Figures.TryGetValue(name,out var other) || other.Hidden) continue;
                others.Add(new(name,new(other.Position.X,other.Position.Z),Text(c,"location_id"),_figures.ShownRoom(name),other.Scale.X));
            }
            talk=Proximity.TalkTargetNear(new(f.CharacterName,new(f.Position.X,f.Position.Z),loc,_figures.ShownRoom(f.CharacterName)),others);
        }
        _hud.SetState("talkTarget",talk is { } t ? new JsonObject { ["name"]=t.Name,["dist"]=t.Dist } : null);
        _entry=null; _entryReason=null;
        if(CanUse && Avatar is { } avatar && Map is { } root)
        {
            var candidates=new List<EntryTile>();
            foreach(var loc in LocationInfo.ParseList(root))
            {
                if(!loc.IsPlaced) continue;
                var openings=new List<EntryOpening>();
                if(root.TryGetProperty("locations",out var rows)) foreach(var row in rows.EnumerateArray())
                {
                    if(Text(row,"id")!=loc.Id || !row.TryGetProperty("openings",out var oo)) continue;
                    foreach(var o in oo.EnumerateArray())
                        if(o.TryGetProperty("at_world",out var at) && o.TryGetProperty("inward",out var inward))
                            openings.Add(new(o.TryGetProperty("edge",out var edge) ? edge.GetInt32() : 0,
                                new(at[0].GetDouble(),at[1].GetDouble()),new(inward[0].GetDouble(),inward[1].GetDouble())));
                }
                if(openings.Count==0 && _world.Slots.GetValueOrDefault(loc.Id)?.Openable!=true) continue;
                candidates.Add(new(loc.Id,new(loc.PosX!.Value,loc.PosZ!.Value,loc.YawDeg*Math.PI/180),openings,
                    openings.Count==0 ? loc.Boundary?.Select(p=>new P2(p.X,p.Z)).ToArray() : null,Locks.IsLocked(LockedLocations,loc.Id)));
            }
            _entry=EnterLocation.EntryOfferNear(new(avatar.Position.X,avatar.Position.Z),_world.PlaceAt(avatar.Position.X,avatar.Position.Z) ?? "",candidates);
            if(_entry is { } entry && Locks.IsLocked(LockedLocations,entry.LocId)) _entryReason=Locks.LockReason(LockedLocations,entry.LocId);
        }
        _hud.SetState("enterOffer",_entry is { } e && _entryReason is null ? new JsonObject
        { ["name"]=LocationInfo.ParseList(Map!.Value).FirstOrDefault(l=>l.Id==e.LocId)?.Name ?? "",["dist"]=e.Dist } : null);
    }

    /// <summary>Task 52: explicit chip action uses exactly SceneKeys' resolution, including sole/multi-stop lifts.</summary>
    public void TriggerOffer()
    {
        var state=new JsonObject();
        foreach(var name in new[]{"talkTarget","stairs","elevator","enterOffer","elevatorOpen"}) state[name]=_hud.SceneOwned(name)?.DeepClone();
        var command=SceneKeys.Interact(state,HasLockedEntry);
        if(command is null) return;
        if(command.Ui) _hud.SendUi(command.Name);
        else if(command.Name=="elevatorOpen") _hud.SetState(command.Name,command.Argument);
        else if(_hud.Handlers.TryGetValue(command.Name,out var action)) action(command.Argument is null ? new() : new(command.Argument.DeepClone()));
    }
    private static string Key(EntryOffer e) => JsonSerializer.Serialize(new[]{e.LocId,e.Point.X.ToString("R",System.Globalization.CultureInfo.InvariantCulture),e.Point.Z.ToString("R",System.Globalization.CultureInfo.InvariantCulture),e.Inward.X.ToString("R",System.Globalization.CultureInfo.InvariantCulture),e.Inward.Z.ToString("R",System.Globalization.CultureInfo.InvariantCulture)});
    public async Task EnterAsync()
    {
        if(!CanUse || _entry is not { } offer) return;
        if(_entryReason is { } reason) { Toast?.Invoke(reason); return; }
        if(!CanEnter || _entryPin is not null) return;
        int generation=_generation;
        try
        {
            if(!await Readiness.EnterWhenReady(this,offer.LocId,Key(offer)) || generation!=_generation || !CanEnter) return;
            double x=offer.Point.X+offer.Inward.X*.5,z=offer.Point.Z+offer.Inward.Z*.5;
            var goal=new Vector3((float)x,(float)_world.FigureGroundY(x,z),(float)z);
            _steering.CancelRoute(); OpenLocation?.Invoke(offer.LocId);
            _figures.SetPlayerTarget(_figures.AvatarName,goal);
            _steering.WalkIn=new(goal,_steering.Clock+4);
        }
        catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
    }
    void IEntryDeps.RequestNear(string id) { _entryPin=id; _world.Pin(id,"entry"); }
    void IEntryDeps.Release(string id,string owner) { if(_entryPin==id) ReleaseEntry(); }
    private void ReleaseEntry() { if(_entryPin is { } id) _world.Release(id,"entry"); _entryPin=null; }
    Task IEntryDeps.Settled(string id) => _world.Residency.Settled(id);
    Task IEntryDeps.Sleep(int ms) => Task.Delay(ms,_lifetime.Token);
    bool IEntryDeps.IsReady(string id) => _world.IsReady(id);
    bool IEntryDeps.StillValid(string key) => CanEnter && _entry is { } e && _entryReason is null && Key(e)==key;
    bool IEntryDeps.Exists(string id) => !_disposed && _world.Known.Contains(id);
    bool IEntryDeps.CanProgress(string id) => _world.Residency.HasJob(id) || _world.Residency.Target(id)!=_world.Residency.Ring(id);

    public void Dispose()
    {
        if(_disposed) return;
        SetActive(false); DetachProps(); _disposed=true; _lifetime.Cancel();
        _figures.PositionMapApplied-=MapApplied; _world.Dropped-=Dropped; _steering.StandUp=null; _hud.LockedEntry=null;
        _hud.Handlers.Remove("enterLocation"); _hud.Handlers.Remove("pickRoomPose"); _hud.Handlers.Remove("closePlaceMenu");
        _hud.Handlers.Remove("pairFacing");
        Places.Clear(); Places.QueueFree(); _lifetime.Dispose();
    }
}
