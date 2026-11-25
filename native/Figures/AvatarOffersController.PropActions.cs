using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Props;
using AnimaNative.Orders;
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
    /// <summary>One click on a furniture action: the request it sends and the local order the avatar walks meanwhile.</summary>
    private sealed class PropClick(string action,JsonObject target,string revision,IReadOnlyList<string>? members,string? consent)
    {
        public readonly string Action=action,Revision=revision;
        public readonly JsonObject Target=target;
        public readonly IReadOnlyList<string>? Members=members;
        public readonly string? Consent=consent;
        public Order? Local;
        public string ExecutionId="";
        public bool NoPath;
    }
    private PropClick? _currentClick,_queuedClick;
    private bool _clickInFlight;
    private int _localOrders;
    private Task _abandoning=Task.CompletedTask;
    /// <summary>Runs this avatar's clicks gave up: their (late) orders are not played, their reservation is cancelled.</summary>
    private readonly HashSet<string> _abandonedRuns=new(StringComparer.Ordinal);
    private Vector3? _turnAwayFrom;
    private double? _handBackAt;
    private bool _handBackPending;

    private void AttachProps()
    {
        if(!_source.SupportsPropActions) return;
        var props=PropActions=new(_source,_clock) { RefreshOffers=()=>RefreshSemanticOffersAsync(),Log=LogProp };
        props.RefreshWorld=async ()=> {
            if(RefreshPropWorld is { } refresh) await refresh();
            else { using var doc=await _source.GetWorldMapAsync(); if(!_disposed) _figures.ApplyPolled(doc.RootElement.Clone()); }
        };
        _figures.SuppressAvatarPropEntry=()=>_manualPropRelease;
        props.Changed+=PropStateChanged;
        props.NotifyChanged+=PropNotifyChanged;
        props.RefreshFailed+=PropRefreshFailed;
        props.RunEnded+=PropRunEnded;
        props.RunSuperseded+=PropRunSuperseded;
        props.MutationRejected+=PropMutationRejected;
        _figures.OwnPropRunLive=()=>props.OwnedRun is not null;
        _figures.OwnPairEnding+=PropPairEnding;
        _figures.OrderEnded+=AvatarOrderEnded;
        _figures.OrderFrameShown+=AvatarOrderFrame;
        _figures.IgnoresAvatarOrder=order=>order.ExecutionId.Length>0 && _abandonedRuns.Contains(order.ExecutionId);
        _hud.PropActionResult=(result,source)=> {
            string ownId=props.OwnExecutionId;
            props.ConsumeAnswer(result,source);
            AdoptAnswerOrder(result);
            string status=PropActionMotion.Text(result["status"]),id=PropActionMotion.Text(result["execution_id"]);
            // Only cancelling the own run hands the avatar back; a withdrawn invitation leaves it seated.
            if(source=="cancel" && status is not ("refused" or "failed") && id.Length>0 && id==ownId) RequestHandBack();
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
            // The action starts here, not when the menu opens: reading time in the menu is not measured.
            if(Avatar is { } avatar) _steering.FirstStep.Arm("prop_offer",_steering.Clock,avatar.Position.X,avatar.Position.Z);
            StartClick(new PropClick(PropActionMotion.Text(args[0]),(JsonObject)target.DeepClone(),PropActionMotion.Text(args[2]),
                AnimaNative.Api.PropActionRequest.BridgeMembers(args),
                args.Count>4 && args[4] is JsonValue c && c.TryGetValue<string>(out var consent) ? consent : null));
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
        _position.PropMotionOwned=()=>_figures.HasLiveOrder(_figures.AvatarName) || props.OwnedRun is not null;
        _position.ManualPropWithdrawn=props.ManualGate.Withdrawn;
        _steering.ReleasePropAction=()=> {
            if(props.ManualGate.Pending) return;
            if(props.OwnedRun is null && _currentClick is { } click && click.ExecutionId.Length==0) AbandonClick(click);
            else PendingPropAction=ReleaseOwnedPropAsync();
        };
        PickPropAction=PickSemanticProp;
        PropStateChanged();
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

    /// <summary>
    /// Plan E3 Task 6: the local order of a click (<see cref="LocalOrders.PropAction"/>) from the mounted scene: the
    /// furniture's prop marker (<c>placement_id</c>) in the target's room, its slot nearest to the avatar as the anchor,
    /// the marker's access of the role <c>actor</c> — else <see cref="AccessAuto.Compute"/> on the floor under the slot.
    /// Null when the scene does not hold the furniture (the request alone then decides).
    /// </summary>
    private Order? LocalOrderFor(JsonObject target)
    {
        if(Avatar is not { } avatar) return null;
        string placement=PropActionMotion.Text(target["placement_id"]),room=PropActionMotion.Text(target["room_id"]),loc=PropActionMotion.Text(target["location_id"]);
        if(placement.Length==0 || _world.Slots.GetValueOrDefault(loc) is not { Ready:true } tile) return null;
        var at=new Vec3(avatar.Position.X,avatar.Position.Y,avatar.Position.Z);
        PlaceEntry? best=null; Vec3 slot=default; double bestD=double.PositiveInfinity;
        foreach(var entry in tile.Places.Markers.Values.SelectMany(m=>m.Values).Distinct())
        {
            if(entry.PlacementId!=placement || entry.RoomId!=room) continue;
            foreach(var s in entry.Slots)
            {
                double d=double.Hypot(s.X-at.X,s.Z-at.Z);
                if(d<bestD) { bestD=d; best=entry; slot=s; }
            }
        }
        if(best is null) return null;
        double facing=(best.Rotation ?? 0)+best.FrameYawDeg;
        var anchor=new OrderPoint(slot.X,slot.Y,slot.Z,facing);
        var access=best.Access.TryGetValue("actor",out var marked) ? marked
            : AccessAuto.Compute(new OrderPoint(slot.X,at.Y,slot.Z,facing),0,0,null,null);
        OrderStep? exit=_steering.AvatarSeated ? new OrderStep("exit","seat","",0) : null;
        return LocalOrders.PropAction(++_localOrders,_figures.MotionNow,LocalOrders.DefaultSpeedMS,
            new LocalPropAction(_figures.AvatarName,null,new OrderPoint(at.X,at.Y,at.Z,avatar.Yaw*180/Math.PI),_position.RoomId,best.Level,
                access,anchor,best.Drop,"bridge",exit,"","",loc,room,best.Level));
    }

    /// <summary>
    /// A click: the avatar walks its local order at once (before the reservation is answered) and the request goes out —
    /// at once, or after the request still running (its answer is then superseded and cancelled before this one goes).
    /// </summary>
    private void StartClick(PropClick click)
    {
        _turnAwayFrom=null; _handBackAt=null; _handBackPending=false;
        click.Local=LocalOrderFor(click.Target);
        _currentClick=click;
        if(click.Local is { } local && _figures.StartLocalOrder(local)) { TakeAvatar(); LogProp($"local order {local.Id} started"); }
        else PreviewPropTarget(click.Target);
        if(_clickInFlight) { _queuedClick=click; return; }
        PendingPropAction=RunClicksAsync(click);
    }
    private async Task RunClicksAsync(PropClick first)
    {
        _clickInFlight=true;
        try {
            for(PropClick? click=first;click is not null && !_disposed;click=_queuedClick) {
                _queuedClick=null;
                await RequestClickAsync(click,retried:false);
            }
        }
        catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
        finally { _clickInFlight=false; }
    }
    private async Task RequestClickAsync(PropClick click,bool retried)
    {
        if(PropActions is not { } props) return;
        JsonObject answer;
        try {
            using var doc=await props.MutateAsync(()=>RequestLoggedAsync(click.Action,click.Target,click.Revision,click.Members,click.Consent));
            answer=JsonNode.Parse(doc.RootElement.GetRawText())!.AsObject();
        }
        catch(AnimaNative.Api.ApiException e) when(e.Status==409 && (e.Detail ?? "").Contains("request_in_progress",StringComparison.Ordinal) && !retried) {
            // The superseded run is still ending on the server: once after its end, never shown as a refusal.
            LogProp("request_in_progress: retry after the superseded run's end");
            await _abandoning;
            if(!_disposed && click==_currentClick) await RequestClickAsync(click,retried:true);
            return;
        }
        catch(Exception e) {
            if(!_disposed && click==_currentClick) RefuseClick(click,e is AnimaNative.Api.ApiException api && api.Detail is { Length:>0 } d ? d : e.Message);
            return;
        }
        if(_disposed) return;
        string status=PropActionMotion.Text(answer["status"]),exec=PropActionMotion.Text(answer["execution_id"]);
        if(status is "refused" or "failed") {
            if(click==_currentClick) RefuseClick(click,PropActionMotion.Text(answer["reason"]));
            return;
        }
        if(exec.Length==0 || status=="cancelled") return;
        if(click!=_currentClick || click.NoPath) {
            // The click was replaced (or found no path) while its request ran: let go of the reservation before the next.
            await AbandonRunAsync(exec);
            return;
        }
        click.ExecutionId=exec;
        AdoptAnswerOrder(answer);
        await RefreshSemanticOffersAsync(false);
    }
    /// <summary>The order of a mutation answer (field <c>order</c>, the actor's own run): taken over by the avatar's player.</summary>
    private void AdoptAnswerOrder(JsonObject answer)
    {
        if(answer["order"] is not JsonObject wire) return;
        Order? order;
        try { using var doc=JsonDocument.Parse(wire.ToJsonString()); order=OrderParse.From(doc.RootElement); }
        catch(Exception e) { LogProp("answer order unreadable: "+e.Message); return; }
        if(order is null || order.ActorNamed(_figures.AvatarName) is null) return;
        if(order.ExecutionId.Length>0 && _abandonedRuns.Contains(order.ExecutionId)) return;
        _figures.AdoptOrders(new[] { order },_figures.MotionNow);
        if(_figures.HasLiveOrder(_figures.AvatarName)) TakeAvatar();
    }
    private Task AbandonRunAsync(string executionId)
    {
        if(!_abandonedRuns.Add(executionId)) return _abandoning;
        LogProp($"superseded run {executionId}: cancel");
        return _abandoning=MutatePropAsync(()=>_source.CancelPropActionAsync(executionId,_lifetime.Token),"cancel");
    }
    /// <summary>Input let go of a click whose answer has not come: the avatar is handed back, a late answer is cancelled.</summary>
    private void AbandonClick(PropClick click)
    {
        if(_currentClick==click) _currentClick=null;
        _handBackPending=true;
    }
    /// <summary>A refusal of the click (or a failed request): stand, turn away from the furniture, say why.</summary>
    private void RefuseClick(PropClick click,string reason)
    {
        _currentClick=null;
        if(click.Local?.Actors[0].Anchor is { } anchor) _turnAwayFrom=new((float)anchor.X,(float)anchor.Y,(float)anchor.Z);
        LogProp($"click refused: {reason}");
        Toast?.Invoke(reason.Length>0 ? reason : "refused");
        if(_figures.HasLiveOrder(_figures.AvatarName)) _figures.RefuseOrder(_figures.AvatarName,reason);
        else _handBackPending=true;
    }
    private void AvatarOrderFrame(string name,OrderFrame frame)
    {
        if(_disposed || name!=_figures.AvatarName || !frame.Events.Contains("no_path") || _currentClick is not { } click) return;
        // No way to the furniture: say so, let go of the reservation (now, or when its answer comes) and of the avatar.
        click.NoPath=true; _currentClick=null;
        Toast?.Invoke("no_path");
        LogProp("local order: no_path");
        if(click.ExecutionId.Length>0) PendingPropAction=AbandonRunAsync(click.ExecutionId);
        _handBackPending=true;
    }
    private void AvatarOrderEnded(string name)
    {
        if(_disposed || name!=_figures.AvatarName) return;
        // A refused or given-up order, or the exit of an ended run: the avatar is the player's again.
        if(_currentClick is null || PropActions?.OwnedRun is null && _currentClick.ExecutionId.Length==0 && !_figures.HasLiveOrder(name))
            _handBackPending=true;
    }
    /// <summary>The run ended or is being let go: the avatar goes back once its order's exit has played, at the latest after the hold.</summary>
    private void RequestHandBack()
    {
        _currentClick=null;
        if(_figures.HasLiveOrder(_figures.AvatarName)) _handBackAt=_clock()+AnimaNative.Figures.FigureManager.OwnPairEndHoldS*1000;
        else _handBackPending=true;
    }
    private void TakeAvatar()
    {
        _manualPropRelease=false; _propPrepared=false; _propPreviewYaw=null; _handBackAt=null; _handBackPending=false;
        _position.OwnSeatChangeAt=_clock(); _position.Channel.DiscardPendingAnswers();
        _steering.CancelRoute(); _steering.PropActionDriven=true; _steering.SetSeated(false); _seatKey="";
        _figures.SetServerDriven(true);
    }
    private void PropStateChanged()
    {
        if(_disposed || PropActions is not { } props) return;
        PublishPropSnapshot();
        if(props.OwnedRun is not null && !props.ManualGate.Pending) _manualPropRelease=false;
    }
    private void PropRefreshFailed(string message) { if(!_disposed) Toast?.Invoke(message); }
    private void PropNotifyChanged(string? id) { if(id is not null) { InvalidatePropOffers(); } _hud.NotifyPropActionsChanged(id); }
    private void InvalidatePropOffers() { _semanticGeneration++; _lastSemanticPoll=double.NegativeInfinity; _lastStatePoll=_clock(); _nextPropPoll=_clock()+PropPollPeriod(); }
    public Func<double> PropPollPeriod { get; set; }=()=>AnimaNative.Sync.PollSpec.Worldmap3d.IntervalMs;
    private double PropPollInterval=>PropPollPeriod();
    private void PublishPropSnapshot() { if(!_disposed && PropActions is { } props) _hud.SetState("propActionSnapshot",new JsonObject { ["offers"]=_semanticOffers.DeepClone(),["state"]=props.State }); }
    private async Task<JsonDocument> RequestLoggedAsync(string action,JsonObject target,string revision,IReadOnlyList<string>? members,string? consent)
    {
        var timer=System.Diagnostics.Stopwatch.StartNew();
        LogProp($"request sent action={JsonSerializer.Serialize(action)} placement={JsonSerializer.Serialize(PropActionMotion.Text(target["placement_id"]))}");
        try {
            var answer=await _source.RequestPropActionAsync(action,JsonSerializer.SerializeToElement(target),revision,members,consent,_lifetime.Token);
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
        if(_disposed || PropActions is not { } props) return;
        if(source!="cancel") { if(_propMutationBusy) return; _propMutationBusy=true; }
        try {
            using var answer=await props.MutateAsync(operation,source);
            var node=JsonNode.Parse(answer.RootElement.GetRawText())!.AsObject();
            if(source!="cancel") AdoptAnswerOrder(node);
            if(answer.RootElement.TryGetProperty("status",out var s) && s.GetString() is "refused" or "failed")
                throw new InvalidOperationException(answer.RootElement.GetProperty("reason").GetString());
            await RefreshSemanticOffersAsync(false);
        } catch(Exception e) { if(!_disposed) Toast?.Invoke(e.Message); }
        finally { if(source!="cancel") _propMutationBusy=false; }
    }
    private async Task ReleaseOwnedPropAsync()
    {
        if(_disposed || PropActions is not { OwnedRun: { } run } props) return;
        string? journey=Self(Map!.Value) is { } me && me.TryGetProperty("travel",out var tr) && tr.ValueKind==JsonValueKind.Object ? Text(tr,"journey_id") : _position.OwnedPropJourney;
        await ObservePropAsync(async ()=> {
            try { await props.ReleaseAsync(PropActionMotion.Text(run["execution_id"]),journey,RequestHandBack);
                await RefreshSemanticOffersAsync(false);
            }
            finally { PropStateChanged(); }
        });
    }
    private void PropRunEnded(string status,string reason)
    {
        if(_disposed) return;
        _nextPropPoll=_clock()+PropPollPeriod();
        if(_propPreviewYaw is { } yaw && Avatar is { } avatar) { avatar.FaceTowards(new((float)Math.Sin(yaw),0,(float)Math.Cos(yaw)),snap:true); _propPreviewYaw=null; }
        RequestHandBack();
    }
    /// <summary>
    /// A new own run replaced the tracked one in place (another action on the same piece, an accepted invitation): no
    /// hand-back and no position report in between; the server's order of the new run places the avatar.
    /// </summary>
    private void PropRunSuperseded(string previous,string next)
    {
        if(_disposed) return;
        TakeAvatar();
        LogProp($"run superseded in place: {previous} -> {next}");
        PropStateChanged();
    }
    /// <summary>The own pair left the rows: its run has ended or is ending — read the state now, not a poll later, so the
    /// avatar's end (and with it the NPC half the figures hold) follows within one round trip.</summary>
    private void PropPairEnding()
    {
        if(_disposed) return;
        _lastStatePoll=double.NegativeInfinity; _nextPropPoll=_clock();
    }
    private void PropMutationRejected(string status,string reason)
    {
        if(_disposed) return;
        _nextPropPoll=_clock()+PropPollPeriod();
        if(_propPreviewYaw is { } yaw && Avatar is { } avatar) { avatar.FaceTowards(new((float)Math.Sin(yaw),0,(float)Math.Cos(yaw)),snap:true); _propPreviewYaw=null; }
        _propPrepared=false;
        LogProp($"mutation rejected: status={status} reason={reason}; own run kept until state says otherwise");
        PropStateChanged();
    }
    /// <summary>The avatar goes back to the player: its order (if any) is let go where the figure stands.</summary>
    private void HandBack()
    {
        _handBackAt=null; _handBackPending=false;
        PropActions?.ManualGate.Withdraw(_position.OwnedPropJourney);
        _figures.WithdrawOwnPropInteraction();
        _figures.DropOrder(_figures.AvatarName);
        _position.ReleasePropDriver();
        _manualPropRelease=PropActions?.OwnedRun is not null; _propPrepared=false;
        Avatar?.ReleasePropAtRenderedPoint();
        LogProp("order ended: handed back");
        _position.OwnSeatChangeAt=_clock(); _position.Channel.DiscardPendingAnswers();
        _figures.ClearPropEntry(_figures.AvatarName); _figures.SetServerDriven(false);
        _steering.PropActionDriven=false; _steering.SetSeated(false); _seatKey="";
        if(Avatar is { } f) {
            f.Face=null; f.Lean=null; f.SurfaceGroup="ground"; f.ApplyRotation(); _figures.SetPlayerAnimation(f.CharacterName,null);
            f.Target=f.Position;
            if(_turnAwayFrom is { } furniture && LocalOrders.TurnAwayYawDeg(new(f.Position.X,f.Position.Y,f.Position.Z),new(furniture.X,furniture.Y,furniture.Z)) is { } yaw)
                f.FaceTowards(new((float)Math.Sin(yaw*Math.PI/180),0,(float)Math.Cos(yaw*Math.PI/180)));
        }
        _turnAwayFrom=null;
        PropStateChanged();
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
    private void RefreshRoomOffers()
    {
        if(!_active || _disposed || PropActions is null) return;
        _semanticGeneration++;
        _semanticOffers=new();
        PublishPropSnapshot();
        PendingPropAction=ObservePropAsync(()=>RefreshSemanticOffersAsync());
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
            _lastSemanticPoll=_clock();
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
        // Plan E3 Task 6: offers only in the own room — the one the server confirmed (enter-room / position answers).
        if(!_active || _disposed || _steering.MovementLocked
            || _world.Slots.GetValueOrDefault(_position.LocationId) is not { Ready:true,Ring:Ring.Near } tile) yield break;
        string ownRoom=_position.RoomId;
        foreach(var rec in tile.Placements) {
            var spec=rec.Spec;
            if(spec.Role!="prop" || spec.RoomId!=ownRoom || spec.PlacementId.Length==0 || rec.Node is not { } node
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
        if(HitSemanticProp(origin,direction) is not { } hit) return HitForeignProp(origin,direction);
        var css=_hud.ViewportToCss(viewport);
        _hud.SetState("placeMenu",new JsonObject { ["x"]=(double)css.X,["y"]=(double)css.Y,["offer"]=hit.Offer }); ClearHover(); return true;
    }
    /// <summary>
    /// A click on furniture of a neighbour room (no offers there): a click walk to the spot under the hit, as a floor
    /// click would be — the furniture is offered once the avatar is in that room.
    /// </summary>
    private bool HitForeignProp(Vec3 origin,Vec3 direction)
    {
        if(!_active || _disposed || _world.Slots.GetValueOrDefault(_position.LocationId) is not { Ready:true,Ring:Ring.Near } tile) return false;
        var o=new Vector3((float)origin.X,(float)origin.Y,(float)origin.Z); var d=new Vector3((float)direction.X,(float)direction.Y,(float)direction.Z).Normalized();
        double best=double.PositiveInfinity; Vector3? point=null;
        foreach(var rec in tile.Placements) {
            if(rec.Spec.Role!="prop" || rec.Spec.RoomId==_position.RoomId || rec.Spec.PlacementId.Length==0 || rec.Node is not { } node
               || !GodotObject.IsInstanceValid(node) || !node.IsVisibleInTree()) continue;
            foreach(var mesh in PropMeshes(node))
                if(mesh.IsVisibleInTree() && MeshRay.Static(mesh,o,d) is double t && t<best) { best=t; point=o+d*(float)t; }
        }
        if(point is not { } hit) return false;
        CloseMenu(new());
        _steering.WalkTo(new AnimaNative.Scatter.P2(hit.X,hit.Z));
        return true;
    }
    private void TickProps()
    {
        if(_disposed || PropActions is not { } props) return;
        if(_handBackPending || _handBackAt is { } at && _clock()>=at) HandBack();
        if(_propPollBusy || _clock()<_nextPropPoll) return;
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
        props.Changed-=PropStateChanged; props.NotifyChanged-=PropNotifyChanged; props.RefreshFailed-=PropRefreshFailed; props.RunEnded-=PropRunEnded; props.RunSuperseded-=PropRunSuperseded; props.MutationRejected-=PropMutationRejected;
        _figures.OwnPairEnding-=PropPairEnding; _figures.OrderEnded-=AvatarOrderEnded; _figures.OrderFrameShown-=AvatarOrderFrame;
        _figures.OwnPropRunLive=null; _figures.IgnoresAvatarOrder=null; props.Dispose();
        _hud.PropActionPrepare=null; _hud.PropActionsChanged=null; _hud.PropActionResult=null; _hud.PropActionTarget=null;
        foreach(string name in new[]{"pickPropAction","respondPropAction","cancelPropAction"}) _hud.Handlers.Remove(name);
        _figures.SuppressAvatarPropEntry=null; _position.PropMotionOwned=null; _position.ManualPropWithdrawn=null;
        _steering.ReleasePropAction=null;
        PickPropAction=null;
    }
}
