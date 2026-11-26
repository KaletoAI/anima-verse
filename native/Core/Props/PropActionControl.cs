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
/// Task 57 / E7-T12: the own furniture run's reservation lifecycle — request/respond/cancel answers, the state reads
/// that confirm them, the HUD's prepare/changed correlation and the manual release. Plan E3 Task 6: the avatar walks
/// on its own order from the click on, so nothing here pauses input or pre-flushes the position any more, and no
/// motion plan is read (the order of an answer is the controller's). Correlation is local transport metadata, never
/// an execution identity or server nonce. Scene owns this object; Dispose invalidates late continuations.
/// </summary>
public sealed class PropActionControl(IWorldSource source,Func<double> clock) : IDisposable
{
    public PropPreparationBarrier Preparation { get; }=new();
    public ManualPropGate ManualGate { get; }=new();
    private readonly HashSet<string> _endedOwn=new(StringComparer.Ordinal);
    private readonly HashSet<string> _released=new(StringComparer.Ordinal);
    private JsonObject _state=new() { ["incoming"]=new JsonArray(),["current"]=new JsonArray(),["outgoing"]=new JsonArray(),["recent_results"]=new JsonArray() };
    private int _epoch;
    private int _knownFailedEpoch=-1;
    public int Generation=>_epoch;
    private long _refreshSerial;
    private Task? _refreshTask;
    private bool _disposed;
    private long _sequence;
    private readonly string _session=Guid.NewGuid().ToString("N");
    public JsonObject State=>(JsonObject)_state.DeepClone();
    public Func<Task>? RefreshOffers { get; set; }
    public Action<string>? Log { get; set; }
    private string _offeredOwnKey="";
    private JsonObject? _requestedRun,_trackedRun;
    public event Action<string,string>? RunEnded;
    /// <summary>The tracked run ended because a NEW own run took its place (old id, new id): another action on the same
    /// piece switches in place, an accepted invitation replaces what ran. Not an end: the avatar stays the server's.</summary>
    public event Action<string,string>? RunSuperseded;
    /// <summary>A refused or failed mutation that was not about the own run. The server keeps the current run on a
    /// refusal and ends it only when a new request replaced it, so only the following state read
    /// (<see cref="ReconcileRun"/>) may end it; this only undoes the local click preview.</summary>
    public event Action<string,string>? MutationRejected;
    /// <summary>The own run the client tracks or plays ("" = none).</summary>
    public string OwnExecutionId=>PropActionMotion.Text((_trackedRun ?? OwnedRun)?["execution_id"]);
    private string OwnStateKey => OwnedRun is { } run ? $"{PropActionMotion.Text(run["execution_id"])}|{PropActionMotion.Text(run["status"])}|{PropActionMotion.Text(run["phase"])}" : "";
    public Func<Task> RefreshWorld { get; set; }=()=>Task.CompletedTask;
    /// <summary>The state, the preparation or the tracked run changed (the controller republishes its snapshot).</summary>
    public event Action? Changed;
    public event Action<string?>? NotifyChanged;
    /// <summary>Task 67 #5: reconciliation errors are observable without replacing the mutation verdict.</summary>
    public event Action<string>? RefreshFailed;
    public JsonObject? OwnedRun => _requestedRun ?? (_state["current"] as JsonArray ?? new()).OfType<JsonObject>()
        .FirstOrDefault(r=>!_released.Contains(PropActionMotion.Text(r["execution_id"])) && PropActionMotion.Text(r["status"]) is "approaching" or "active")
        ?? (_state["outgoing"] as JsonArray ?? new()).OfType<JsonObject>()
        .FirstOrDefault(r=>!_released.Contains(PropActionMotion.Text(r["execution_id"])) && PropActionMotion.Text(r["status"])=="approaching");
    /// <summary>The HUD is about to mutate: the next state read must come after this epoch.</summary>
    public Task PrepareAsync(string id)
    {
        ObjectDisposedException.ThrowIf(_disposed,this);
        Preparation.Begin(id,clock()); _epoch++; Changed?.Invoke();
        return Task.CompletedTask;
    }
    public Task ChangedAsync(string? id)
    {
        if(_disposed) return Task.CompletedTask;
        bool knownFailure=_knownFailedEpoch==_epoch;
        Preparation.Changed(id); _epoch++;
        if(knownFailure) { Preparation.AdoptFreshState(); _knownFailedEpoch=-1; }
        Changed?.Invoke();
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
        Changed?.Invoke();
        string key=OwnStateKey;
        if(key!=_offeredOwnKey && RefreshOffers is { } refresh) { await refresh(); _offeredOwnKey=key; }
        if(!ended) await RefreshWorld();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        Preparation.AdoptFreshState(); Changed?.Invoke();
    }
    /// <summary>
    /// One mutation answer (a request, a response, a cancel — also the HUD's own): a refusal of the own run ends it, any
    /// other refusal only undoes the click; an approaching answer becomes the tracked run until a state read confirms it.
    /// </summary>
    public void ConsumeAnswer(JsonObject answer,string source)
    {
        if(_disposed) return;
        string id=PropActionMotion.Text(answer["execution_id"]),status=PropActionMotion.Text(answer["status"]);
        bool own=id.Length>0 && id==OwnExecutionId;
        if(source=="cancel") { ConsumeCancel(id,status,own); return; }
        if(status is "failed" or "refused") {
            string reason=PropActionMotion.Text(answer["reason"]);
            if(own) { _trackedRun??=OwnedRun?.DeepClone().AsObject(); EndRun(status,reason); }
            else RejectMutation(status,reason);
            return;
        }
        if(_released.Contains(id) || status=="cancelled") return;
        if(status=="approaching") { _requestedRun=(JsonObject)answer.DeepClone(); _trackedRun=(JsonObject)answer.DeepClone(); }
    }
    private void ConsumeCancel(string id,string status,bool own)
    {
        if(status is "refused" or "failed") return;
        _released.Add(id);
        Preparation.AdoptFreshState();
        // Withdrawing an invitation or stopping another row leaves the own run alone.
        if(!own && !_endedOwn.Contains(id)) return;
        _endedOwn.Add(id);
        if(own) _trackedRun=_requestedRun=null;
    }
    private void RejectMutation(string status,string reason)
    {
        _knownFailedEpoch=_epoch;
        MutationRejected?.Invoke(status,reason);
    }
    public async Task<JsonDocument> MutateAsync(Func<Task<JsonDocument>> mutation,string source="request")
    {
        string id=$"{_session}:{++_sequence}";
        try {
            await PrepareAsync(id);
            var answer=await mutation();
            if(_disposed) return answer;
            var answerNode=JsonNode.Parse(answer.RootElement.GetRawText())!.AsObject();
            ConsumeAnswer(answerNode,source);
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
        if(status is "cancelled" or "failed" or "completed" || (row is null && PropActionMotion.Text(previous["status"])=="approaching")) {
            if(OwnedRun is { } next && PropActionMotion.Text(next["execution_id"]) is { Length:>0 } nextId && nextId!=id) {
                _released.Add(id); _trackedRun=(JsonObject)next.DeepClone();
                Log?.Invoke($"run superseded: status={status} next={nextId}");
                RunSuperseded?.Invoke(id,nextId);
                return false;
            }
            EndRun(status.Length>0 ? status : "cancelled",row is null ? "approach_withdrawn" : PropActionMotion.Text(row["reason"])); return true;
        }
        else if(OwnedRun is { } owned) _trackedRun=(JsonObject)owned.DeepClone();
        return false;
    }
    private void EndRun(string status,string reason)
    {
        if(_trackedRun is null) return;
        _endedOwn.Add(PropActionMotion.Text(_trackedRun["execution_id"]));
        _released.Add(PropActionMotion.Text(_trackedRun["execution_id"]));
        _trackedRun=_requestedRun=null;
        Preparation.AdoptFreshState();
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
                ConsumeCancel(executionId,status,own:true);
                release();
            } finally {
                if(!_disposed) { Preparation.Changed(requestId); Preparation.AdoptFreshState(); Changed?.Invoke(); }
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
