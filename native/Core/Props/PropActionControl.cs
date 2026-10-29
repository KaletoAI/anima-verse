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
    public Func<Task> RefreshWorld { get; set; }=()=>Task.CompletedTask;
    public event Action? PauseChanged;
    public event Action<string?>? NotifyChanged;
    /// <summary>Task 67 #5: reconciliation errors are observable without replacing the mutation verdict.</summary>
    public event Action<string>? RefreshFailed;
    public JsonObject? OwnedRun => (_state["current"] as JsonArray ?? new()).OfType<JsonObject>()
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
        Preparation.Changed(id); _uncertain=true; _epoch++; PauseChanged?.Invoke();
        return RefreshAsync();
    }
    public async Task RefreshAsync()
    {
        if(_disposed) return;
        int epoch=_epoch; long serial=++_refreshSerial;
        using var state=await source.GetPropActionStateAsync();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        var fresh=JsonNode.Parse(state.RootElement.GetRawText())!.AsObject();
        // Exact own approaches need this private status while applying their public world route.
        _state=fresh;
        await RefreshWorld();
        if(_disposed || epoch!=_epoch || serial!=_refreshSerial) return;
        _uncertain=false; Preparation.AdoptFreshState(); PauseChanged?.Invoke();
    }
    public async Task<JsonDocument> MutateAsync(Func<Task<JsonDocument>> mutation)
    {
        string id=$"{_session}:{++_sequence}";
        try { await PrepareAsync(id); return await mutation(); }
        finally
        {
            if(!_disposed)
            {
                try { NotifyChanged?.Invoke(id); await ChangedAsync(id); }
                catch(Exception e) { RefreshFailed?.Invoke(e.Message); }
            }
        }
    }
    /// <summary>Task 57: success alone tombstones the captured journey; refusal leaves it retriable.</summary>
    public Task ReleaseAsync(string executionId,string? journey,Action release)
        =>ManualGate.Cancel(executionId,journey,async ()=>
        {
            using var result=await MutateAsync(()=>source.CancelPropActionAsync(executionId));
            string status=result.RootElement.TryGetProperty("status",out var s) ? s.GetString() ?? "" : "";
            if(status is "refused" or "failed") throw new InvalidOperationException(result.RootElement.GetProperty("reason").GetString());
            if(_disposed) return;
            _released.Add(executionId); release();
        });
    public Task ExpireAsync() => Preparation.Expire(clock()) ? ChangedAsync(null) : Task.CompletedTask;
    public void Dispose() { _disposed=true; _epoch++; }
}
