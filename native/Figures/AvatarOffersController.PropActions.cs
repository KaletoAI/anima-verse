using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Props;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Task 57 / E7-T12: semantic HUD commands, prepare/changed bridge and Task 52 mesh-pick extension.
/// Ownership ledger: owns PropActionControl subscriptions/handlers; borrows mounted placement nodes and never
/// clones materials or creates shaders. Dispose detaches every callback; mesh references are rebuilt from live slots.
/// </summary>
public sealed partial class AvatarOffersController
{
    public PropActionControl? PropActions { get; private set; }
    public Func<Task>? RefreshPropWorld { get; set; }
    public Task? PendingPropAction { get; private set; }
    private JsonArray _semanticOffers=new();
    private long _semanticGeneration;
    private double _nextPropPoll,_propBurstUntil;
    private bool _propPollBusy,_propMutationBusy,_manualPropRelease;
    private void AttachProps()
    {
        if(!_source.SupportsPropActions) return;
        var props=PropActions=new(_source,_clock);
        props.PrepareWrites=async ()=> {
            _steering.CancelRoute();
            if(Avatar is { } f && !_figures.ServerDriven) _figures.SetPlayerTarget(f.CharacterName,f.Position);
            await _position.Channel.PreparePropActionAsync(Avatar is { } a ? new(a.Position.X,a.Position.Z) : null,
                _figures.ServerDriven || props.OwnedRun is not null || _steering.PropActionDriven || _steering.AvatarSeated);
        };
        props.RefreshWorld=async ()=> {
            if(RefreshPropWorld is { } refresh) await refresh();
            else { using var doc=await _source.GetWorldMapAsync(); if(!_disposed) _figures.ApplyPolled(doc.RootElement.Clone()); }
        };
        _figures.SuppressAvatarPropEntry=()=>_manualPropRelease;
        _figures.PropEntryError=message=>Toast?.Invoke(message);
        props.PauseChanged+=PropPauseChanged;
        props.NotifyChanged+=PropNotifyChanged;
        _hud.PropActionPrepare=props.PrepareAsync;
        _hud.PropActionsChanged=id=> { _propBurstUntil=_clock()+5000; PendingPropAction=ObservePropAsync(()=>props.ChangedAsync(id)); };
        _hud.Handlers["pickPropAction"]=args=> {
            CloseMenu(new());
            if(args.Count<3 || args[1] is not JsonObject target) return;
            PendingPropAction=MutatePropAsync(()=>_source.RequestPropActionAsync(PropActionMotion.Text(args[0]),
                JsonSerializer.SerializeToElement(target),PropActionMotion.Text(args[2]),args.Count>3 ? args[3]?.GetValue<string>() : null,_lifetime.Token));
        };
        _hud.Handlers["respondPropAction"]=args=> {
            if(args.Count<2 || args[1] is not JsonValue b || !b.TryGetValue<bool>(out var accept)) return;
            PendingPropAction=MutatePropAsync(()=>_source.RespondPropActionAsync(PropActionMotion.Text(args[0]),accept,_lifetime.Token));
        };
        _hud.Handlers["cancelPropAction"]=args=> {
            if(args.Count==0) return;
            string id=PropActionMotion.Text(args[0]);
            PendingPropAction=PropActionMotion.Text(props.OwnedRun?["execution_id"])==id ? ReleaseOwnedPropAsync()
                : MutatePropAsync(()=>_source.CancelPropActionAsync(id,_lifetime.Token));
        };
        _figures.OwnedPropApproaching=()=>PropActionMotion.Text(props.OwnedRun?["status"])=="approaching";
        _position.PropMotionOwned=()=>props.OwnedRun is not null;
        _position.ManualPropWithdrawn=props.ManualGate.Withdrawn;
        _steering.ReleasePropAction=()=> { if(!props.Paused && !props.ManualGate.Pending) PendingPropAction=ReleaseOwnedPropAsync(); };
        PickPropAction=PickSemanticProp;
        PropPauseChanged();
        PendingPropAction=ObservePropAsync(async ()=> { await props.RefreshAsync(); await RefreshSemanticOffersAsync(); });
    }
    private void PropPauseChanged()
    {
        if(_disposed || PropActions is not { } props) return;
        if(props.OwnedRun is not null && !props.ManualGate.Pending) _manualPropRelease=false;
        _position.Channel.ReportsPaused=props.Paused;
        _steering.PropPreparationPending=props.Paused;
    }
    private void PropNotifyChanged(string? id) { _hud.NotifyPropActionsChanged(id); _propBurstUntil=_clock()+5000; }
    private async Task ObservePropAsync(Func<Task> work)
    {
        try { await work(); }
        catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
    }
    private async Task MutatePropAsync(Func<Task<JsonDocument>> operation)
    {
        if(_propMutationBusy || _disposed || PropActions is not { } props) return;
        _propMutationBusy=true;
        try {
            using var answer=await props.MutateAsync(operation);
            if(answer.RootElement.TryGetProperty("status",out var s) && s.GetString() is "refused" or "failed")
                throw new InvalidOperationException(answer.RootElement.GetProperty("reason").GetString());
            await RefreshSemanticOffersAsync();
        } catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
        finally { _propMutationBusy=false; }
    }
    private async Task ReleaseOwnedPropAsync()
    {
        if(_disposed || PropActions is not { OwnedRun: { } run } props) return;
        string? journey=Self(Map!.Value) is { } me && me.TryGetProperty("travel",out var tr) && tr.ValueKind==JsonValueKind.Object ? Text(tr,"journey_id") : _position.OwnedPropJourney;
        await ObservePropAsync(async ()=> {
            try { await props.ReleaseAsync(PropActionMotion.Text(run["execution_id"]),journey,()=> {
                _manualPropRelease=true;
                _position.OwnSeatChangeAt=_clock(); _position.Channel.DiscardPendingAnswers();
                _figures.ClearPropEntry(_figures.AvatarName); _figures.SetServerDriven(false);
                _steering.PropActionDriven=false; _steering.SetSeated(false); _seatKey="";
                if(Avatar is { } f) { f.Face=null; f.Lean=null; f.ApplyRotation(); _figures.SetPlayerAnimation(f.CharacterName,null); }
            }); }
            finally { PropPauseChanged(); }
        });
    }
    public async Task RefreshSemanticOffersAsync()
    {
        if(_disposed || PropActions is null) return;
        long generation=++_semanticGeneration;
        string room=_position.RoomId,loc=_position.LocationId;
        try {
            using var doc=await _source.GetPropActionsAsync();
            if(_disposed || generation!=_semanticGeneration || room!=_position.RoomId || loc!=_position.LocationId) return;
            _semanticOffers=JsonNode.Parse(doc.RootElement.GetRawText())!.AsArray();
            RefreshOpenSemanticMenu();
        } catch(Exception e) { if(!_disposed && generation==_semanticGeneration) Toast?.Invoke("Furniture actions unavailable: "+e.Message); }
    }
    private bool RefreshOpenSemanticMenu()
    {
        if(_hud.SceneOwned("placeMenu")?["offer"]?["id"]?.GetValue<string>() is not { } id
            || !id.StartsWith("prop-action:",StringComparison.Ordinal)) return false;
        var binding=SemanticMeshes().FirstOrDefault(row=>"prop-action:"+row.Placement.Spec.PlacementId==id);
        if(binding.Placement is null) { CloseMenu(new()); return true; }
        var menu=_hud.SceneOwned("placeMenu")!.DeepClone(); menu!["offer"]=SemanticOffer(id,binding.Actions);
        _hud.SetState("placeMenu",menu); return true;
    }
    private static JsonObject SemanticOffer(string id,IEnumerable<JsonObject> actions) =>new() {
        ["id"]=id,["label"]=actions.First()["label"]?.DeepClone(),["group"]="",["capacity"]=1,["free"]=0,
        ["free_slots"]=new JsonArray(),["poses"]=new JsonArray(),["prop_actions"]=new JsonArray(actions.Select(a=>(JsonNode?)a.DeepClone()).ToArray()) };
    private IEnumerable<(PlacedModel Placement,JsonObject[] Actions)> SemanticMeshes()
    {
        if(!_active || _disposed || _steering.MovementLocked || PropActions?.Paused==true
            || Map is not { } map || Self(map) is not { } me || _world.Slots.GetValueOrDefault(Text(me,"location_id")) is not { Ready:true,Ring:Ring.Near } tile) yield break;
        foreach(var rec in tile.Placements) {
            var spec=rec.Spec;
            if(spec.Role!="prop" || spec.RoomId!=Text(me,"room_id") || spec.PlacementId.Length==0 || rec.Node is not { } node
                || !GodotObject.IsInstanceValid(node) || !node.IsVisibleInTree()) continue;
            var actions=_semanticOffers.OfType<JsonObject>().Where(a=>PropActionMotion.Text(a["target"]?["placement_id"])==spec.PlacementId
                && PropActionMotion.Text(a["target"]?["variant_uid"])==spec.VariantUid
                && PropActionMotion.Text(a["target"]?["room_id"])==spec.RoomId
                && PropActionMotion.Text(a["target"]?["location_id"])==tile.Loc.Id).ToArray();
            if(actions.Length>0) yield return(rec,actions);
        }
    }
    private static IEnumerable<MeshInstance3D> PropMeshes(Node node)
    { if(node is MeshInstance3D mesh) yield return mesh; foreach(var child in node.GetChildren()) foreach(var m in PropMeshes(child)) yield return m; }
    private JsonObject? HitSemanticProp(Vec3 origin,Vec3 direction)
    {
        var o=new Vector3((float)origin.X,(float)origin.Y,(float)origin.Z); var d=new Vector3((float)direction.X,(float)direction.Y,(float)direction.Z).Normalized();
        double best=double.PositiveInfinity; JsonObject? offer=null;
        foreach(var (rec,actions) in SemanticMeshes()) foreach(var mesh in PropMeshes(rec.Node!))
            if(mesh.IsVisibleInTree() && MeshRay.Static(mesh,o,d) is double t && t<best) { best=t; offer=SemanticOffer("prop-action:"+rec.Spec.PlacementId,actions); }
        return offer;
    }
    private bool PickSemanticProp(Vec3 origin,Vec3 direction,Vector2 viewport)
    {
        if(HitSemanticProp(origin,direction) is not { } offer) return false;
        var css=_hud.ViewportToCss(viewport);
        _hud.SetState("placeMenu",new JsonObject { ["x"]=(double)css.X,["y"]=(double)css.Y,["offer"]=offer }); return true;
    }
    private void TickProps()
    {
        if(_disposed || PropActions is not { } props || _propPollBusy || _clock()<_nextPropPoll) return;
        _nextPropPoll=_clock()+150;
        bool moving=_figures.HasPropMotion || props.OwnedRun is not null || _clock()<_propBurstUntil;
        if(!moving && !props.Paused) return;
        _propPollBusy=true;
        PendingPropAction=ObservePropAsync(async ()=> { try { await props.ExpireAsync(); if(moving || props.Paused) await props.RefreshAsync(); } finally { _propPollBusy=false; } });
    }
    private void DetachProps()
    {
        if(PropActions is not { } props) return;
        props.PauseChanged-=PropPauseChanged; props.NotifyChanged-=PropNotifyChanged; props.Dispose();
        _hud.PropActionPrepare=null; _hud.PropActionsChanged=null;
        foreach(string name in new[]{"pickPropAction","respondPropAction","cancelPropAction"}) _hud.Handlers.Remove(name);
        _figures.OwnedPropApproaching=null; _figures.SuppressAvatarPropEntry=null; _figures.PropEntryError=null; _position.PropMotionOwned=null; _position.ManualPropWithdrawn=null;
        _steering.ReleasePropAction=null; _steering.PropPreparationPending=false; _position.Channel.ReportsPaused=false;
        PickPropAction=null;
    }
}
