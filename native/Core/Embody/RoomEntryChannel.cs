using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Embody;

/// <summary>
/// Task 51 / E7-T6: main.ts' ONE room request machine shared by walking, stairs and lift. Durations use
/// the caller's monotonic milliseconds: hold 1.5 s, rejection 4 s from answer, confirmation 10 s from send.
/// Reset cancels the owned deadline and invalidates late continuations; transport must honor cancellation.
/// </summary>
public sealed class RoomEntryChannel(Func<string,CancellationToken,Task<PositionAnswer>> send, Func<double> clock) : IDisposable
{
    public const double HoldSeconds=1.5, RejectMs=4000, ConfirmMs=10000;
    public const int TimeoutMs=10000;
    private RoomWalkState _walk=RoomWalk.IdleRoomWalk();
    private readonly Dictionary<string,double> _rejected=new();
    private CancellationTokenSource? _flight;
    private double _requestedAt;
    private int _generation;
    public string? RequestedRoom { get; private set; }
    public bool InFlight => _flight is not null;
    public Task<bool>? Pending { get; private set; }
    public Action<string>? Toast { get; set; }
    public bool Rejected(string room) => _rejected.GetValueOrDefault(room)>clock();
    public void Idle() => _walk=RoomWalk.IdleRoomWalk();

    /// <summary>Keep the old due clock while gated, so a freed line does not add a second hold.</summary>
    public void Walk(string? current, P2 pos, IReadOnlyList<ElevatorRoom> rooms, int level)
    {
        if (RequestedRoom is { } requested && (requested==current || clock()-_requestedAt>ConfirmMs)) RequestedRoom=null;
        var before=_walk;
        var result=RoomWalk.NearestRoomSwitch(current,pos,rooms,level,before,clock(),HoldSeconds);
        if (result.Next is not { } next || next==current) { _walk=result.State; return; }
        bool gated=InFlight || next==RequestedRoom || Rejected(next);
        _walk=gated ? before : result.State;
        if (!gated) Pending=EnterAsync(next);
    }

    /// <summary>Only rides announce player-authored refusal text; walking stays silent and awaits the poll.</summary>
    public async Task<bool> EnterAsync(string room, bool announce=false)
    {
        if (InFlight || Rejected(room)) return false;
        var deadline=new CancellationTokenSource(TimeoutMs);
        _flight=deadline; int generation=_generation;
        RequestedRoom=room; _requestedAt=clock();
        try
        {
            var answer=await send(room,deadline.Token).WaitAsync(deadline.Token);
            if (generation!=_generation) return false;
            if (answer.Status is >=200 and <300) return true;
            if (announce && answer.Reason.Length>0 && answer.Message.Length>0) Toast?.Invoke(answer.Message);
        }
        catch (Exception) when (generation==_generation) { /* Timeout/network refusal shares the cooldown. */ }
        catch (OperationCanceledException) { return false; }
        finally
        {
            if (_flight==deadline) _flight=null;
            deadline.Dispose();
        }
        if (generation==_generation) { _rejected[room]=clock()+RejectMs; RequestedRoom=null; }
        return false;
    }

    public void Reset()
    {
        _generation++; _flight?.Cancel(); _flight=null;
        Idle(); RequestedRoom=null; _rejected.Clear();
    }
    public void Dispose() => Reset();
}
