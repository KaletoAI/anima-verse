using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Task 52 / E7-T7: main.ts room-marker inventory/menu and authoritative avatar seat reconciliation.
/// Availability generations and request-time seat stamps reject late GETs; activity writes hold infinity until
/// acknowledgement, then request a fresh map. Fixed/anchored prop markers never become place targets or poses.
/// </summary>
public sealed partial class AvatarOffersController
{
    private readonly CancellationTokenSource _lifetime=new();
    private readonly List<JsonObject> _placeOffers=new();
    private string _offersRoom="",_offersLoc="",_seatKey="";
    private LocationSlot? _placeTile;
    private long _offersGeneration,_offersAppliedGeneration;
    private int _placesEpoch;
    private bool _activityBusy;
    public Task? PendingActivity { get; private set; }
    /// <summary>Task 57: run prop-action mesh picking before room targets; it must publish semantic prop_actions.</summary>
    public Func<Vec3,Vec3,Vector2,bool>? PickPropAction { get; set; }

    public async Task RefreshPlacesAsync()
    {
        if(!_active || _disposed || Map is not { } map || Self(map) is not { } me) return;
        long generation=++_offersGeneration;
        int epoch=_placesEpoch;
        double askedAt=_clock(); string loc=Text(me,"location_id"),room=Text(me,"room_id");
        try
        {
            using var doc=await _source.GetPlacesAsync();
            if(!_active || _disposed || epoch!=_placesEpoch || generation<_offersAppliedGeneration || FigureGround.PollIsStale(askedAt,_position.OwnSeatChangeAt)
                || Map is not { } current || Self(current) is not { } self || Text(self,"location_id")!=loc || Text(self,"room_id")!=room) return;
            _offersAppliedGeneration=generation;
            var root=doc.RootElement;
            _offersRoom=Text(root,"room_id"); _offersLoc=loc; _placeOffers.Clear();
            if(root.TryGetProperty("places",out var rows)) foreach(var row in rows.EnumerateArray())
            {
                // Task 57 owns semantic offers; their poses cannot authorize a room-marker write.
                if(row.TryGetProperty("prop_actions",out _)) continue;
                if(JsonNode.Parse(row.GetRawText()) is JsonObject offer) _placeOffers.Add(offer);
            }
            RebuildPlaces();
        }
        catch(Exception e) { if(!_disposed && _active && generation==_offersGeneration) { ClearPlaces(); Toast?.Invoke(e.Message); } }
    }
    private static int[] FreeSlots(JsonObject offer) => offer["free_slots"] is JsonArray a
        ? a.OfType<JsonValue>().Where(v=>v.TryGetValue<int>(out _)).Select(v=>v.GetValue<int>()).ToArray() : Array.Empty<int>();
    private JsonObject? RoomOffer(string id)
    {
        if(_placeTile is null || !_placeTile.Places.Markers.TryGetValue(_offersRoom,out var markers)
            || !markers.TryGetValue(id,out var marker) || marker.Fixed || marker.Anchor is not null) return null;
        return _placeOffers.FirstOrDefault(o=>o["id"]?.GetValue<string>()==id && o["poses"] is JsonArray { Count: >0 });
    }
    private void RebuildPlaces()
    {
        var tile=_world.Slots.GetValueOrDefault(_offersLoc);
        if(!CanUse || tile is null || tile.Ring!=Ring.Near || !tile.Ready || Map is not { } map || Self(map) is not { } me
            || Text(me,"location_id")!=_offersLoc || Text(me,"room_id")!=_offersRoom)
        { Places.Clear(); _placeTile=null; CloseMenu(new()); return; }
        _placeTile=tile;
        var offers=_placeOffers.Where(o=>RoomOffer(o["id"]?.GetValue<string>() ?? "") is not null)
            .Select(o=>new PlaceOffer(o["id"]!.GetValue<string>(),o["group"]?.GetValue<string>() ?? "",
                o["free"]?.GetValue<double>() ?? 0,FreeSlots(o))).ToArray();
        string skip=me.TryGetProperty("place",out var place) && place.ValueKind==JsonValueKind.Object ? Text(place,"id") : "";
        Places.Sync(tile,_offersRoom,offers,skip);
        if(_hud.SceneOwned("placeMenu")?["offer"]?["id"]?.GetValue<string>() is { } id)
        {
            if(RoomOffer(id) is not { } fresh) CloseMenu(new());
            else
            {
                var menu=_hud.SceneOwned("placeMenu")!.DeepClone(); menu!["offer"]=fresh.DeepClone();
                _hud.SetState("placeMenu",menu);
            }
        }
    }
    private void ClearPlaces()
    {
        _placesEpoch++; _offersGeneration++; _placeOffers.Clear(); _offersRoom=_offersLoc=""; _placeTile=null;
        Places.Clear(); CloseMenu(new());
    }
    public bool Pick(Vec3 origin,Vec3 direction,Vector2 viewport)
    {
        if(!CanUse) return false;
        if(PickPropAction?.Invoke(origin,direction,viewport)==true) return true;
        if(Places.Hit(origin,direction) is not { } hit || RoomOffer(hit.Id) is not { } offer) return false;
        var css=_hud.ViewportToCss(viewport);
        _hud.SetState("placeMenu",new JsonObject { ["x"]=(double)css.X,["y"]=(double)css.Y,["offer"]=offer.DeepClone() });
        return true;
    }
    public bool Hover(Vec3 origin,Vec3 direction)
    {
        var hit=CanUse ? Places.Hit(origin,direction) : null;
        Places.Hover(hit); return hit is not null;
    }
    public async Task PickRoomPoseAsync(string id,string pose)
    {
        if(!CanUse || _activityBusy || RoomOffer(id) is not { } offer || offer.ContainsKey("prop_actions")
            || offer["poses"] is not JsonArray poses || !poses.Any(p=>p?["key"]?.GetValue<string>()==pose)) return;
        CloseMenu(new());
        await ActivityAsync(JsonSerializer.SerializeToElement(new { place_id=id,pose }),false);
    }
    private void StandUp() => PendingActivity=ActivityAsync(JsonSerializer.SerializeToElement(new { activity="" }),true);
    private async Task ActivityAsync(JsonElement body,bool standUp)
    {
        if(_activityBusy || _disposed) return;
        _activityBusy=true; _steering.SeatWritePending=true; _steering.SeatTakingPending=!standUp;
        _position.OwnSeatChangeAt=double.PositiveInfinity;
        _position.Channel.DiscardPendingAnswers();
        // Cached placement observes the same infinity as fresh polls, including activity and the label.
        _figures.HoldAvatarPlacement=true;
        try
        {
            var answer=await _source.PostActivityAsync(body,_lifetime.Token);
            if(_disposed) return;
            if(answer.Status is <200 or >=300) throw new ApiException(answer.Status,"/play/self/activity",answer.Message);
            if(!standUp) _steering.CancelRoute();
            // Taking a seat blocks the final dirty position report until the first fresh authoritative seat row.
            if(!standUp) _steering.SetSeated(true);
            if(standUp) { _steering.SetSeated(false); _seatKey=""; }
        }
        catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
        finally
        {
            if(!_disposed)
            {
                _position.OwnSeatChangeAt=_clock(); _activityBusy=false;
                _steering.SeatWritePending=_steering.SeatTakingPending=false;
                RefreshMap?.Invoke();
            }
        }
    }

    /// <summary>Task 52: root/face/lean belong to the numbered slot; footprint yaw rotates the marker-local facing.</summary>
    public void ReconcilePlace(JsonElement map,double polledAt)
    {
        if(!_active || _disposed || FigureGround.PollIsStale(polledAt,_position.OwnSeatChangeAt)
            || _steering.PropActionDriven || _figures.ServerDriven || Avatar is not { } f || Self(map) is not { } me) return;
        if(!me.TryGetProperty("place",out var p) || p.ValueKind!=JsonValueKind.Object)
        {
            if(_steering.AvatarSeated || _seatKey.Length>0)
            {
                _steering.SetSeated(false); _seatKey=""; f.Face=null; f.Lean=null; f.SurfaceGroup="ground"; f.ApplyRotation();
                _figures.SetPlayerAnimation(f.CharacterName,null);
                _figures.SetPlayerTarget(f.CharacterName,new(f.Position.X,(float)_world.PlayerFloorY(_world.FootprintAt(f.Position.X,f.Position.Z),_steering.RoomId,f.Position.X,f.Position.Z),f.Position.Z));
            }
            return;
        }
        _steering.SetSeated(true);
        var tile=_world.Slots.GetValueOrDefault(Text(me,"location_id"));
        if(tile is null || tile.Ring!=Ring.Near || !tile.Ready || !tile.Places.Markers.TryGetValue(Text(p,"room_id"),out var markers)
            || !markers.TryGetValue(Text(p,"id"),out var held)) { _seatKey=""; return; }
        int? slot=p.TryGetProperty("slot",out var s) && s.ValueKind==JsonValueKind.Number && s.TryGetInt32(out int index) ? index : null;
        if(PlaceSlots.SlotFor(held.Slots,slot) is not { } seat) return;
        // A pose change can keep the exact same slot and geometry. Release the steering animation override
        // before reading this fresh row, so later authoritative clips remain observable too (Task 52 review).
        _figures.SetPlayerAnimation(f.CharacterName,null);
        f.Activity=Text(me,"activity_animation");
        // Include geometry and pose so a re-lift/remount or a pose change re-applies an otherwise identical slot.
        string key=$"{tile.Group.GetInstanceId()}:{held.Id}:{slot}:{seat}:{held.Rotation}:{held.Tilt}:{held.Roll}:{tile.Stands.Frame.Yaw}";
        if(key==_seatKey) return;
        _seatKey=key; _steering.CancelRoute(); _steering.WalkIn=_steering.Correction=_steering.VerticalRide=null;
        _figures.SetStairRide(f.CharacterName,null);
        _figures.SnapPlayerTo(f.CharacterName,new((float)seat.X,(float)seat.Y,(float)seat.Z));
        f.Face=null;
        if(held.Rotation is double angle)
        {
            double a=angle*Math.PI/180;
            var dir=SceneView.TileDirToWorld(tile.Stands.Frame.Yaw,Math.Sin(a),Math.Cos(a));
            f.Face=new((float)dir.X,0,(float)dir.Z); f.FaceTowards(f.Face.Value,snap:true);
        }
        f.Lean=held.Tilt.GetValueOrDefault()!=0 || held.Roll.GetValueOrDefault()!=0 ? (held.Tilt ?? 0,held.Roll ?? 0) : null;
        f.SurfaceGroup=held.Group; f.ApplyRotation();
    }
}
