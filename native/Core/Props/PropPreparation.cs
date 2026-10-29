using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AnimaNative.Props;

/// <summary>Task 57: createPositionDrain; every real write owns one completion, including a queued final write.</summary>
public sealed class PositionDrain
{
    private readonly object _sync=new();
    private int _pending;
    private TaskCompletionSource? _idle;
    public Action Begin()
    {
        lock(_sync) { _pending++; _idle ??=new(); }
        bool finished=false;
        return ()=> { lock(_sync) { if(finished) return; finished=true; if(--_pending==0) { var idle=_idle; _idle=null; idle?.SetResult(); } } };
    }
    public Task WaitAsync() { lock(_sync) return _idle?.Task ?? Task.CompletedTask; }
}

/// <summary>
/// Task 57: createPropPreparationBarrier; a matching HTTP completion or inclusive 10,000 ms lease expiry
/// makes a request releasable. Only subsequently fetched authoritative state may actually release it.
/// Calls belong to the scene synchronization context; no timer fabricates an adopted state.
/// </summary>
public sealed class PropPreparationBarrier
{
    private readonly Dictionary<string,(bool Completed,double ExpiresAt)> _requests=new(StringComparer.Ordinal);
    public bool Pending=>_requests.Count>0;
    public void Begin(string requestId,double now=0)=>_requests[requestId]=(false,now+10000);
    public void Changed(string? requestId) { if(requestId is not null && _requests.TryGetValue(requestId,out var r)) _requests[requestId]=(true,r.ExpiresAt); }
    public bool Expire(double now)
    {
        bool expired=false;
        foreach(var (id,r) in _requests.ToArray()) if(!r.Completed && r.ExpiresAt<=now) { _requests[id]=(true,r.ExpiresAt); expired=true; }
        return expired;
    }
    public void AdoptFreshState() { foreach(var (id,r) in _requests.ToArray()) if(r.Completed) _requests.Remove(id); }
}
