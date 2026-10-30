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
    private string _semanticLog="";
    private bool _propPrepared;
    private double? _propPreviewYaw;
    private static void LogProp(string message)=>GD.Print("[native] [prop] "+message);
    private double _nextPropPoll,_lastSemanticPoll=double.NegativeInfinity,_lastStatePoll=double.NegativeInfinity;
    private Task? _semanticRefresh,_stateRefresh;
    private bool _propPollBusy,_propMutationBusy,_manualPropRelease;
    private void AttachProps()
    {
        if(!_source.SupportsPropActions) return;
        var props=PropActions=new(_source,_clock) { RefreshOffers=()=>RefreshSemanticOffersAsync(),Log=LogProp };
        props.PrepareWrites=async ()=> {
            _propPrepared=true;
            _steering.CancelRoute();
            if(Avatar is { } f && !_figures.ServerDriven) _figures.SetPlayerTarget(f.CharacterName,f.Position);
            var point=Avatar is { } a ? new AnimaNative.Scatter.P2(a.Position.X,a.Position.Z) : (AnimaNative.Scatter.P2?)null;
            bool serverOwned=_figures.ServerDriven || props.OwnedRun is not null || _steering.PropActionDriven || _steering.AvatarSeated;
            bool sent=!serverOwned && point is not null && _position.Channel.Dirty;
            var timer=System.Diagnostics.Stopwatch.StartNew();
            await _position.Channel.PreparePropActionAsync(point,serverOwned);
            LogProp(serverOwned ? "position pre-flush skipped (server-owned)" : sent
                ? $"position pre-flush point=({point!.Value.X:F2},{point.Value.Z:F2}) ms={timer.ElapsedMilliseconds}"
                : $"position pre-flush skipped (clean) ms={timer.ElapsedMilliseconds}");
        };
        props.RefreshWorld=async ()=> {
            if(RefreshPropWorld is { } refresh) await refresh();
            else { using var doc=await _source.GetWorldMapAsync(); if(!_disposed) _figures.ApplyPolled(doc.RootElement.Clone()); }
        };
        _figures.SuppressAvatarPropEntry=()=>_manualPropRelease;
        _figures.PropEntryError=message=>Toast?.Invoke(message);
        props.PauseChanged+=PropPauseChanged;
        props.NotifyChanged+=PropNotifyChanged;
        props.RefreshFailed+=PropRefreshFailed;
        props.RunEnded+=PropRunEnded;
        props.MotionReceived+=PropMotionReceived;
        _figures.OwnPropMotionReleased+=ReleaseLocalProp;
        _hud.PropActionResult=(result,source)=> {
            props.ConsumeMotion(result,source);
            string status=PropActionMotion.Text(result["status"]);
            if(source=="cancel" && status is not ("refused" or "failed") && _figures.OwnPropMotion?.Cancel!=true) ReleaseLocalProp();
        };
        _hud.PropActionTarget=PreviewPropTarget;
        _hud.PropActionPrepare=id=>props.PrepareAsync(id);
        _hud.PropActionsChanged=id=> {
            if(id is not null) { InvalidatePropOffers(); }
            PendingPropAction=ObservePropAsync(async ()=> { await props.ChangedAsync(id); await RefreshSemanticOffersAsync(false); PublishPropSnapshot(); });
        };
        _hud.Handlers["pickPropAction"]=args=> {
            CloseMenu(new());
            if(args.Count<3 || args[1] is not JsonObject target) return;
            PreviewPropTarget(target);
            PendingPropAction=MutatePropAsync(()=>RequestLoggedAsync(PropActionMotion.Text(args[0]),target,
                PropActionMotion.Text(args[2]),args.Count>3 ? args[3]?.GetValue<string>() : null));
        };
        _hud.Handlers["respondPropAction"]=args=> {
            if(args.Count<2 || args[1] is not JsonValue b || !b.TryGetValue<bool>(out var accept)) return;
            PendingPropAction=MutatePropAsync(()=>_source.RespondPropActionAsync(PropActionMotion.Text(args[0]),accept,_lifetime.Token),"respond");
        };
        _hud.Handlers["cancelPropAction"]=args=> {
            if(args.Count==0) return;
            string id=PropActionMotion.Text(args[0]);
            PendingPropAction=PropActionMotion.Text(props.OwnedRun?["execution_id"])==id ? ReleaseOwnedPropAsync()
                : MutatePropAsync(()=>_source.CancelPropActionAsync(id,_lifetime.Token),"cancel");
        };
        _position.PropMotionOwned=()=>_figures.OwnPropMotion is not null || props.OwnedRun is not null || (_propPrepared && props.Paused);
        _position.ManualPropWithdrawn=props.ManualGate.Withdrawn;
        _steering.ReleasePropAction=()=> { if(!props.Paused && !props.ManualGate.Pending) PendingPropAction=ReleaseOwnedPropAsync(); };
        PickPropAction=PickSemanticProp;
        PropPauseChanged();
        PendingPropAction=ObservePropAsync(async ()=> { await RefreshPropStateAsync(); await RefreshSemanticOffersAsync(false); PublishPropSnapshot(); });
    }
    private void PreviewPropTarget(JsonObject target)
    {
        if(Avatar is not { } avatar) return;
        var placement=_world.Slots.Values.SelectMany(tile=>tile.Placements)
            .FirstOrDefault(rec=>rec.Spec.PlacementId==PropActionMotion.Text(target["placement_id"]));
        if(placement?.Node is not { } node) return;
        _propPreviewYaw=avatar.Yaw;
        avatar.FaceTowards(node.GlobalPosition-avatar.Position,snap:true);
    }
    private void PropMotionReceived(JsonObject motion,string source,string executionId)
    {
        if(_disposed) return;
        if(motion["departure"] is not null && _propPreviewYaw is { } previous && Avatar is { } avatar) avatar.FaceTowards(new((float)Math.Sin(previous),0,(float)Math.Cos(previous)),snap:true);
        _manualPropRelease=false; _propPrepared=false; _propPreviewYaw=null;
        _position.OwnSeatChangeAt=_clock(); _position.Channel.DiscardPendingAnswers();
        _steering.CancelRoute(); _steering.PropActionDriven=true; _steering.SetSeated(false); _seatKey="";
        _figures.PlayOwnPropMotion(motion,source,executionId);
        if(_figures.OwnPropMotion is not null) _figures.SetServerDriven(true);
    }
    private void PropPauseChanged()
    {
        if(_disposed || PropActions is not { } props) return;
        PublishPropSnapshot();
        if(props.OwnedRun is not null && !props.ManualGate.Pending) _manualPropRelease=false;
        _position.Channel.ReportsPaused=props.Paused;
        _steering.PropPreparationPending=props.Paused;
    }
    private void PropRefreshFailed(string message) { if(!_disposed) Toast?.Invoke(message); }
    private void PropNotifyChanged(string? id) { if(id is not null) { InvalidatePropOffers(); } _hud.NotifyPropActionsChanged(id); }
    private void InvalidatePropOffers() { _semanticGeneration++; _lastSemanticPoll=double.NegativeInfinity; _lastStatePoll=_clock(); _nextPropPoll=_clock()+PropPollPeriod(); }
    public Func<double> PropPollPeriod { get; set; }=()=>AnimaNative.Sync.PollSpec.Worldmap3d.IntervalMs;
    private double PropPollInterval=>PropPollPeriod();
    private void PublishPropSnapshot() { if(!_disposed && PropActions is { } props) _hud.SetState("propActionSnapshot",new JsonObject { ["offers"]=_semanticOffers.DeepClone(),["state"]=props.State }); }
    private async Task<JsonDocument> RequestLoggedAsync(string action,JsonObject target,string revision,string? partner)
    {
        var timer=System.Diagnostics.Stopwatch.StartNew();
        LogProp($"request sent action={JsonSerializer.Serialize(action)} placement={JsonSerializer.Serialize(PropActionMotion.Text(target["placement_id"]))}");
        try {
            var answer=await _source.RequestPropActionAsync(action,JsonSerializer.SerializeToElement(target),revision,partner,_lifetime.Token);
            LogProp($"request answered status={answer.RootElement.GetProperty("status").GetString()} ms={timer.ElapsedMilliseconds}");
            return answer;
        } catch { LogProp($"request answered status=error ms={timer.ElapsedMilliseconds}"); throw; }
    }
    private async Task ObservePropAsync(Func<Task> work)
    {
        try { await work(); }
        catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
    }
    private async Task MutatePropAsync(Func<Task<JsonDocument>> operation,string source="request")
    {
        if(_propMutationBusy || _disposed || PropActions is not { } props) return;
        _propMutationBusy=true;
        try {
            using var answer=await props.MutateAsync(operation,source);
            if(answer.RootElement.TryGetProperty("status",out var s) && s.GetString() is "refused" or "failed")
                throw new InvalidOperationException(answer.RootElement.GetProperty("reason").GetString());
            await RefreshSemanticOffersAsync(false);
        } catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
        finally { _propMutationBusy=false; }
    }
    private async Task ReleaseOwnedPropAsync()
    {
        if(_disposed || PropActions is not { OwnedRun: { } run } props) return;
        string? journey=Self(Map!.Value) is { } me && me.TryGetProperty("travel",out var tr) && tr.ValueKind==JsonValueKind.Object ? Text(tr,"journey_id") : _position.OwnedPropJourney;
        await ObservePropAsync(async ()=> {
            try { await props.ReleaseAsync(PropActionMotion.Text(run["execution_id"]),journey,()=> {
                if(_figures.OwnPropMotion?.Cancel!=true) ReleaseLocalProp();
            });
                await RefreshSemanticOffersAsync(false);
            }
            finally { PropPauseChanged(); }
        });
    }
    private void PropRunEnded(string status,string reason)
    {
        if(_disposed) return;
        _nextPropPoll=_clock()+PropPollPeriod();
        if(_propPreviewYaw is { } yaw && Avatar is { } avatar) { avatar.FaceTowards(new((float)Math.Sin(yaw),0,(float)Math.Cos(yaw)),snap:true); _propPreviewYaw=null; }
        ReleaseLocalProp();
    }
    private void ReleaseLocalProp()
    {
        PropActions?.ManualGate.Withdraw(_position.OwnedPropJourney);
        PropActions?.ManualGate.Withdraw(PropActionMotion.Text(_figures.OwnPropMotion?.Plan["journey_id"]) is { Length:>0 } playedJourney ? playedJourney : _position.OwnedPropJourney);
        _figures.WithdrawOwnPropInteraction();
        _position.ReleasePropDriver();
        _manualPropRelease=true; _propPrepared=false;
        Avatar?.ReleasePropAtRenderedPoint();
        _figures.ClearOwnPropMotion();
        LogProp("motion ended: handed back");
        _position.OwnSeatChangeAt=_clock(); _position.Channel.DiscardPendingAnswers();
        _figures.ClearPropEntry(_figures.AvatarName); _figures.SetServerDriven(false);
        _steering.PropActionDriven=false; _steering.SetSeated(false); _seatKey="";
        if(Avatar is { } f) { f.Face=null; f.Lean=null; f.SurfaceGroup="ground"; f.ApplyRotation(); _figures.SetPlayerAnimation(f.CharacterName,null); }
        PropPauseChanged();
    }
    // Startup, mode changes and the timer share one normal read budget.
    private Task RefreshPropStateAsync()
    {
        if(_disposed || PropActions is not { } props) return Task.CompletedTask;
        if(_stateRefresh is { IsCompleted:false }) return _stateRefresh;
        if(_clock()-_lastStatePoll<PropPollInterval) return Task.CompletedTask;
        _lastStatePoll=_clock();
        return _stateRefresh=props.RefreshAsync();
    }
    public Task RefreshSemanticOffersAsync(bool force=true)
    {
        if(_disposed || PropActions is null) return Task.CompletedTask;
        if(_semanticRefresh is { IsCompleted:false }) return _semanticRefresh;
        if(!force && _clock()-_lastSemanticPoll<PropPollInterval) return Task.CompletedTask;
        _lastSemanticPoll=_clock();
        return _semanticRefresh=ReadSemanticOffersAsync();
    }
    private async Task ReadSemanticOffersAsync()
    {
        long generation; string room,loc;
        do {
            generation=_semanticGeneration; room=_position.RoomId; loc=_position.LocationId;
            await ReadSemanticOffersOnceAsync();
        } while(!_disposed && (generation!=_semanticGeneration || room!=_position.RoomId || loc!=_position.LocationId));
    }
    private async Task ReadSemanticOffersOnceAsync()
    {
        long generation=_semanticGeneration;
        string room=_position.RoomId,loc=_position.LocationId;
        try {
            using var doc=await _source.GetPropActionsAsync();
            if(_disposed || generation!=_semanticGeneration || room!=_position.RoomId || loc!=_position.LocationId) return;
            _semanticOffers=JsonNode.Parse(doc.RootElement.GetRawText())!.AsArray();
            var rows=_semanticOffers.OfType<JsonObject>().ToArray();
            string summary=$"n={rows.Length} enabled={rows.Count(a=>a["enabled"]?.GetValue<bool>()==true)} reasons={JsonSerializer.Serialize(rows.Select(a=>PropActionMotion.Text(a["reason"])).Where(r=>r.Length>0).Distinct().Order().ToArray())}";
            if(summary!=_semanticLog) { _semanticLog=summary; LogProp("offers refreshed "+summary); }
            RefreshOpenSemanticMenu(); PublishPropSnapshot();
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
        ["id"]=id,["label"]=(PropActionMotion.Text(actions.First()["prop_label"]) is { Length: >0 } title ? JsonValue.Create(title) : actions.First()["label"]?.DeepClone()),["group"]="",["capacity"]=1,["free"]=0,
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
    private (JsonObject Offer,Node3D Node,Vector3 Point)? HitSemanticProp(Vec3 origin,Vec3 direction)
    {
        var o=new Vector3((float)origin.X,(float)origin.Y,(float)origin.Z); var d=new Vector3((float)direction.X,(float)direction.Y,(float)direction.Z).Normalized();
        double best=double.PositiveInfinity; (JsonObject Offer,Node3D Node,Vector3 Point)? hit=null;
        foreach(var (rec,actions) in SemanticMeshes()) foreach(var mesh in PropMeshes(rec.Node!))
            if(mesh.IsVisibleInTree() && MeshRay.Static(mesh,o,d) is double t && t<best) { best=t; hit=(SemanticOffer("prop-action:"+rec.Spec.PlacementId,actions),rec.Node!,o+d*(float)t); }
        return hit;
    }
    private bool PickSemanticProp(Vec3 origin,Vec3 direction,Vector2 viewport)
    {
        if(HitSemanticProp(origin,direction) is not { } hit) return false;
        var css=_hud.ViewportToCss(viewport);
        _hud.SetState("placeMenu",new JsonObject { ["x"]=(double)css.X,["y"]=(double)css.Y,["offer"]=hit.Offer }); ClearHover(); return true;
    }
    private void TickProps()
    {
        if(_disposed || PropActions is not { } props || _propPollBusy || _clock()<_nextPropPoll) return;
        _nextPropPoll=_clock()+PropPollInterval;
        _propPollBusy=true;
        PendingPropAction=ObservePropAsync(async ()=> { try {
            if(await props.ExpireAsync()) _lastStatePoll=_clock();
            else await RefreshPropStateAsync();
            await RefreshSemanticOffersAsync(false); PublishPropSnapshot();
        } finally { _propPollBusy=false; } });
    }
    private void DetachProps()
    {
        if(PropActions is not { } props) return;
        props.PauseChanged-=PropPauseChanged; props.NotifyChanged-=PropNotifyChanged; props.RefreshFailed-=PropRefreshFailed; props.RunEnded-=PropRunEnded; props.MotionReceived-=PropMotionReceived; _figures.OwnPropMotionReleased-=ReleaseLocalProp; props.Dispose();
        _hud.PropActionPrepare=null; _hud.PropActionsChanged=null; _hud.PropActionResult=null; _hud.PropActionTarget=null;
        foreach(string name in new[]{"pickPropAction","respondPropAction","cancelPropAction"}) _hud.Handlers.Remove(name);
        _figures.SuppressAvatarPropEntry=null; _figures.PropEntryError=null; _position.PropMotionOwned=null; _position.ManualPropWithdrawn=null;
        _steering.ReleasePropAction=null; _steering.PropPreparationPending=false; _position.Channel.ReportsPaused=false;
        PickPropAction=null;
    }
}
