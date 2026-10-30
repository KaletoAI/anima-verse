using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;

namespace AnimaNative.Props;

/// <summary>
/// Task 57 / E7-T12: main.ts ownedPropRun/preparePropAction/refreshPropMotion/releaseOwnedProp orchestration.
/// Correlation is local transport metadata, never an execution identity or server nonce. Scene owns this object;
/// Dispose invalidates late continuations. Public rows never receive the private state held here.
/// </summary>
public sealed class PropActionControl(IWorldSource source,Func<double> clock) : IDisposable
{
    public PropPreparationBarrier Preparation { get; }=new();
    public ManualPropGate ManualGate { get; }=new();
    private readonly HashSet<string> _released=new(StringComparer.Ordinal);
    private JsonObject _state=new() { ["incoming"]=new JsonArray(),["current"]=new JsonArray(),["outgoing"]=new JsonArray(),["recent_results"]=new JsonArray() };
    private int _epoch;
    private int _knownFailedEpoch=-1;
    public int Generation=>_epoch;
    private long _refreshSerial;
    private Task? _refreshTask;
    private bool _uncertain=true,_disposed;
    private long _sequence;
    private readonly string _session=Guid.NewGuid().ToString("N");
    public bool Paused=>Preparation.Pending || _uncertain || ManualGate.Pending;
    public JsonObject State=>(JsonObject)_state.DeepClone();
    public Func<Task> PrepareWrites { get; set; }=()=>Task.CompletedTask;
    public Func<Task>? RefreshOffers { get; set; }
    public Action<string>? Log { get; set; }
    private string _offeredOwnKey="";
    private JsonObject? _requestedRun,_trackedRun;
    public event Action<string,string>? RunEnded;
    public event Action<JsonObject,string,string>? MotionReceived;
    private string OwnStateKey => OwnedRun is { } run ? $"{PropActionMotion.Text(run["execution_id"])}|{PropActionMotion.Text(run["status"])}|{PropActionMotion.Text(run["phase"])}" : "";
    public Func<Task> RefreshWorld { get; set; }=()=>Task.CompletedTask;
    public event Action? PauseChanged;
    public event Action<string?>? NotifyChanged;
    /// <summary>Task 67 #5: reconciliation errors are observable without replacing the mutation verdict.</summary>
    public event Action<string>? RefreshFailed;
    public JsonObject? OwnedRun => _requestedRun ?? (_state["current"] as JsonArray ?? new()).OfType<JsonObject>()
        .FirstOrDefault(r=>!_released.Contains(PropActionMotion.Text(r["execution_id"])) && PropActionMotion.Text(r["status"]) is "approaching" or "active")
        ?? (_state["outgoing"] as JsonArray ?? new()).OfType<JsonObject>()
        .FirstOrDefault(r=>!_released.Contains(PropActionMotion.Text(r["execution_id"])) && PropActionMotion.Text(r["status"])=="approaching");
    public async Task PrepareAsync(string id)
    {
        ObjectDisposedException.ThrowIf(_disposed,this);
        Preparation.Begin(id,clock()); _uncertain=true; _epoch++; PauseChanged?.Invoke();
        await PrepareWrites();
    }
    public Task ChangedAsync(string? id)
    {
        if(_disposed) return Task.CompletedTask;
        bool knownFailure=_knownFailedEpoch==_epoch;
        Preparation.Changed(id); _uncertain=!knownFailure; _epoch++;
        if(knownFailure) { Preparation.AdoptFreshState(); _knownFailedEpoch=-1; }
        PauseChanged?.Invoke();
        return RefreshAsync();
    }
    public Task RefreshAsync()
    {
        if(_disposed) return Task.CompletedTask;
        if(_refreshTask is { IsCompleted:false } pending) return pending;
        var completion=new TaskCompletionSource();
        _refreshTask=completion.Task;
        _=ReadFreshAsync(completion);
        return completion.Task;
    }
    private async Task ReadFreshAsync(TaskCompletionSource completion)
    {
        try {
            // A joined mutation still needs a state fetched after its preparation epoch.
            int epoch;
            do { epoch=_epoch; await RefreshCoreAsync(); }
            while(!_disposed && epoch!=_epoch);
            completion.SetResult();
        } catch(Exception error) { completion.SetException(error); }
    }
    private async Task RefreshCoreAsync()
    {
        if(_disposed) return;
        int epoch=_epoch; long serial=++_refreshSerial;
        using var state=await source.GetPropActionStateAsync();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        var fresh=JsonNode.Parse(state.RootElement.GetRawText())!.AsObject();
        // Lifecycle confirmation may arrive before or after local playback.
        _trackedRun ??= OwnedRun?.DeepClone().AsObject();
        _state=fresh; _requestedRun=null;
        bool ended=ReconcileRun();
        if(OwnedRun is { } owned) ConsumeMotion(owned,"state");
        PauseChanged?.Invoke();
        string key=OwnStateKey;
        if(key!=_offeredOwnKey && RefreshOffers is { } refresh) { await refresh(); _offeredOwnKey=key; }
        if(!ended) await RefreshWorld();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        _uncertain=false; Preparation.AdoptFreshState(); PauseChanged?.Invoke();
    }
    public void ConsumeMotion(JsonObject answer,string source)
    {
        if(_disposed) return;
        string id=PropActionMotion.Text(answer["execution_id"]),status=PropActionMotion.Text(answer["status"]);
        if(source=="cancel") {
            if(status is "refused" or "failed") return;
            _released.Add(id); _trackedRun=_requestedRun=null;
            _uncertain=false; Preparation.AdoptFreshState();
        } else {
            if(status is "failed" or "refused") { RejectMutation(status,PropActionMotion.Text(answer["reason"])); return; }
            if(_released.Contains(id) || status=="cancelled") return;
            if(source!="state" && status=="approaching") { _requestedRun=(JsonObject)answer.DeepClone(); _trackedRun=(JsonObject)answer.DeepClone(); }
        }
        if(answer["motion"] is JsonObject motion) MotionReceived?.Invoke((JsonObject)motion.DeepClone(),source,id);
    }
    private void RejectMutation(string status,string reason)
    {
        var previous=_trackedRun ?? OwnedRun;
        if(previous is not null) _released.Add(PropActionMotion.Text(previous["execution_id"]));
        _trackedRun=_requestedRun=null;
        _uncertain=false; _knownFailedEpoch=_epoch;
        RunEnded?.Invoke(status,reason);
    }
    public async Task<JsonDocument> MutateAsync(Func<Task<JsonDocument>> mutation,string source="request")
    {
        string id=$"{_session}:{++_sequence}";
        try {
            await PrepareAsync(id);
            var answer=await mutation();
            if(_disposed) return answer;
            var answerNode=JsonNode.Parse(answer.RootElement.GetRawText())!.AsObject();
            ConsumeMotion(answerNode,source);
            if(answer.RootElement.TryGetProperty("status",out var status) && status.GetString()=="approaching" && !_released.Contains(PropActionMotion.Text(answerNode["execution_id"]))) {
                _requestedRun=JsonNode.Parse(answer.RootElement.GetRawText())!.AsObject();
                _trackedRun=(JsonObject)_requestedRun.DeepClone();
            }
            return answer;
        }
        catch
        {
            if(!_disposed && source!="cancel") {
                RejectMutation("failed","request_failed");
            }
            throw;
        }
        finally
        {
            if(!_disposed)
            {
                try { NotifyChanged?.Invoke(id); await ChangedAsync(id); }
                catch(Exception e) { RefreshFailed?.Invoke(e.Message); }
            }
        }
    }
    private bool ReconcileRun()
    {
        if(_trackedRun is not { } previous) { _trackedRun=OwnedRun?.DeepClone().AsObject(); return false; }
        string id=PropActionMotion.Text(previous["execution_id"]);
        var row=new[]{"current","outgoing","recent_results"}.SelectMany(k=>(_state[k] as JsonArray ?? new()).OfType<JsonObject>())
            .FirstOrDefault(r=>PropActionMotion.Text(r["execution_id"])==id);
        string status=PropActionMotion.Text(row?["status"]);
        if(status is "cancelled" or "failed" or "completed" || (row is null && PropActionMotion.Text(previous["status"])=="approaching"))
            { EndRun(status.Length>0 ? status : "cancelled",row is null ? "approach_withdrawn" : PropActionMotion.Text(row["reason"])); return true; }
        else if(OwnedRun is { } owned) _trackedRun=(JsonObject)owned.DeepClone();
        return false;
    }
    private void EndRun(string status,string reason)
    {
        if(_trackedRun is null) return;
        _released.Add(PropActionMotion.Text(_trackedRun["execution_id"]));
        _trackedRun=_requestedRun=null;
        _uncertain=false; Preparation.AdoptFreshState();
        Log?.Invoke($"run ended without approach: status={status} reason={reason}");
        RunEnded?.Invoke(status,reason);
    }
    /// <summary>Task 57: success alone tombstones the captured journey; refusal leaves it retriable.</summary>
    public Task ReleaseAsync(string executionId,string? journey,Action release)
        =>ManualGate.Cancel(executionId,journey,async ()=>
        {
            var timer=System.Diagnostics.Stopwatch.StartNew();
            Log?.Invoke($"release requested execution={JsonSerializer.Serialize(executionId)}");
            string requestId=$"{_session}:{++_sequence}";
            try {
                await PrepareAsync(requestId);
                using var result=await source.CancelPropActionAsync(executionId);
                Log?.Invoke($"release answered status={result.RootElement.GetProperty("status").GetString()} ms={timer.ElapsedMilliseconds}");
                string status=result.RootElement.TryGetProperty("status",out var s) ? s.GetString() ?? "" : "";
                if(status is "refused" or "failed") throw new InvalidOperationException(result.RootElement.GetProperty("reason").GetString());
                if(_disposed) return;
                _released.Add(executionId);
                _trackedRun=_requestedRun=null;
                _uncertain=false; Preparation.AdoptFreshState();
                ConsumeMotion(JsonNode.Parse(result.RootElement.GetRawText())!.AsObject(),"cancel");
                release();
            } finally {
                if(!_disposed) { _uncertain=false; Preparation.Changed(requestId); Preparation.AdoptFreshState(); PauseChanged?.Invoke(); }
            }
        });
    public async Task<bool> ExpireAsync()
    {
        if(!Preparation.Expire(clock())) return false;
        await ChangedAsync(null);
        return true;
    }
    public void Dispose() { _disposed=true; _epoch++; }
}
