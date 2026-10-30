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
    private JsonObject _state=new() { ["current"]=new JsonArray(),["outgoing"]=new JsonArray() };
    private int _epoch;
    public int Generation=>_epoch;
    private long _refreshSerial;
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
    private string? _adoptedJourney;
    public event Action<string,string>? RunEnded;
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
    public Task ChangedAsync(string? id,bool immediateWorld=false)
    {
        if(_disposed) return Task.CompletedTask;
        Preparation.Changed(id); _uncertain=true; _epoch++; PauseChanged?.Invoke();
        return RefreshAsync(immediateWorld);
    }
    public async Task RefreshAsync(bool immediateWorld=false)
    {
        if(_disposed) return;
        int epoch=_epoch; long serial=++_refreshSerial;
        // Start the map before private-state latency can consume the 0.3 s lead.
        var stateRequest=source.GetPropActionStateAsync();
        Task<Exception?>? world=null;
        if(immediateWorld) { Log?.Invoke("approaching answer: immediate worldmap poll"); world=ObserveWorldRefreshAsync(); }
        using var state=await stateRequest;
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) { if(world is not null) await world; return; }
        var fresh=JsonNode.Parse(state.RootElement.GetRawText())!.AsObject();
        // Exact own approaches need this private status while applying their public world route.
        _trackedRun ??= OwnedRun?.DeepClone().AsObject();
        _state=fresh; _requestedRun=null;
        ReconcileRun(); PauseChanged?.Invoke();
        if(world is not null) { if(await world is { } error) throw error; } else await RefreshWorld();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        _uncertain=false; Preparation.AdoptFreshState(); PauseChanged?.Invoke();
        string key=OwnStateKey;
        if(key!=_offeredOwnKey && RefreshOffers is { } refresh) { await refresh(); _offeredOwnKey=key; }
    }
    // Observe the parallel map failure immediately, including superseded or failed state reads.
    private async Task<Exception?> ObserveWorldRefreshAsync()
    {
        try { await RefreshWorld(); return null; }
        catch(Exception error) { return error; }
    }
    public async Task<JsonDocument> MutateAsync(Func<Task<JsonDocument>> mutation)
    {
        string id=$"{_session}:{++_sequence}";
        bool approaching=false;
        try {
            await PrepareAsync(id);
            var answer=await mutation();
            if(answer.RootElement.TryGetProperty("status",out var status) && status.GetString()=="approaching") {
                _requestedRun=JsonNode.Parse(answer.RootElement.GetRawText())!.AsObject();
                _trackedRun=(JsonObject)_requestedRun.DeepClone(); _adoptedJourney=null; approaching=true;
            }
            return answer;
        }
        finally
        {
            if(!_disposed)
            {
                try { NotifyChanged?.Invoke(id); await ChangedAsync(id,approaching); }
                catch(Exception e) { RefreshFailed?.Invoke(e.Message); }
            }
        }
    }
    private void ReconcileRun()
    {
        if(_trackedRun is not { } previous) { _trackedRun=OwnedRun?.DeepClone().AsObject(); return; }
        string id=PropActionMotion.Text(previous["execution_id"]);
        var row=new[]{"current","outgoing","recent_results"}.SelectMany(k=>(_state[k] as JsonArray ?? new()).OfType<JsonObject>())
            .FirstOrDefault(r=>PropActionMotion.Text(r["execution_id"])==id);
        string status=PropActionMotion.Text(row?["status"]);
        if(status is "cancelled" or "failed" || (row is null && PropActionMotion.Text(previous["status"])=="approaching"))
            EndRun(status.Length>0 ? status : "cancelled",row is null ? "approach_withdrawn" : PropActionMotion.Text(row["reason"]));
        else if(OwnedRun is { } owned) _trackedRun=(JsonObject)owned.DeepClone();
    }
    /// <summary>A fresh map may withdraw an adopted approach before the private lifecycle poll catches up.</summary>
    public void ObserveWorld(string? journey,bool physicalState)
    {
        if(_trackedRun is null) return;
        if(!string.IsNullOrEmpty(journey)) _adoptedJourney=journey;
        else if(_adoptedJourney is not null && !physicalState) EndRun("cancelled","approach_withdrawn");
    }
    private void EndRun(string status,string reason)
    {
        if(_trackedRun is null) return;
        _released.Add(PropActionMotion.Text(_trackedRun["execution_id"]));
        _trackedRun=_requestedRun=null; _adoptedJourney=null;
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
            using var result=await MutateAsync(async ()=> {
                try {
                    var answer=await source.CancelPropActionAsync(executionId);
                    Log?.Invoke($"release answered status={answer.RootElement.GetProperty("status").GetString()} ms={timer.ElapsedMilliseconds}");
                    return answer;
                } catch { Log?.Invoke($"release answered status=error ms={timer.ElapsedMilliseconds}"); throw; }
            });
            string status=result.RootElement.TryGetProperty("status",out var s) ? s.GetString() ?? "" : "";
            if(status is "refused" or "failed") throw new InvalidOperationException(result.RootElement.GetProperty("reason").GetString());
            if(_disposed) return;
            _released.Add(executionId);
            _trackedRun=_requestedRun=null; _adoptedJourney=null;
            release();
        });
    public Task ExpireAsync() => Preparation.Expire(clock()) ? ChangedAsync(null) : Task.CompletedTask;
    public void Dispose() { _disposed=true; _epoch++; }
}
