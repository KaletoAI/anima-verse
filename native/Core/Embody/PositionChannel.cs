using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

/// <summary>
/// Task 50 / E7-T5: main.ts position channel, driven by a duration clock. One flight, a reserved cancel,
/// send-time echo ring and answerFloor prevent late replies from reclaiming a newer server journey.
/// Renderer callbacks run on the caller's synchronization context; disposed channels never apply a late answer.
/// </summary>
public sealed class PositionChannel(Func<PositionReport, CancellationToken, Task<PositionAnswer>> write,
    Func<double> clock, string? session = null) : IDisposable
{
    public const int ReportMs = 330, TimeoutMs = 8000, RefusalQuietMs = 4000;
    public const double SnapM = 2, CorrectWalkM = 8, CorrectSeconds = 3, CorrectArriveM = .2;
    public string Session { get; } = session ?? Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
    public DriverState Driver { get; private set; } = new(DriverKind.PLAYER);
    public CancelledJourney Cancelled { get; private set; } = CancelledJourney.None;
    public long Seq { get; private set; }
    public long AnswerFloor { get; private set; }
    public bool Dirty { get; private set; }
    public bool InFlight { get; private set; }
    public Func<bool> CanReport { get; set; } = () => true;
    /// <summary>Task 57: synchronously pause manual writes until fresh prop state and world adoption.</summary>
    public bool ReportsPaused { get; set; }
    private bool _propDraining, _propDrainFailed;
    /// <summary>Task 57: flush the rendered final point, then await both current and queued real HTTP writes.</summary>
    public async Task PreparePropActionAsync(P2? point, bool serverOwned)
    {
        ReportsPaused = true;
        if (serverOwned) _pending = null;
        else if (Dirty && point is { } p)
        {
            _pending = (new(Math.Floor(p.X*100+.5)/100, Math.Floor(p.Z*100+.5)/100), ++Seq);
            Dirty = false;
        }
        _propDraining = true; _propDrainFailed = false;
        try
        {
            Flush();
            await WhenIdle;
            if (_propDrainFailed) throw new InvalidOperationException("Position synchronization failed; furniture action was not sent.");
        }
        finally { _propDraining = false; }
    }
    public event Action<PositionAnswer>? Adopted;
    public event Action<P2, P2?>? Refused;
    public event Action<P2>? Corrected;
    public event Action<string>? Toast;
    public event Action<DriverState, DriverState>? DriverChanged;
    public Task WhenIdle => _idle?.Task ?? Task.CompletedTask;
    private readonly List<long> _sent = new();
    private readonly CancellationTokenSource _lifetime = new();
    private TaskCompletionSource? _idle;
    private (P2 Point, long Seq)? _pending;
    private P2? _reported;
    private double _lastReport, _quietUntil;
    private string _quietReason = "";
    private bool _disposed;

    public bool OwnEcho(PositionOrigin? origin) => PosEcho.IsOwnEcho(_sent, Session, origin);
    public bool Suppressed(string? journey) => PosEcho.SuppressedJourney(Driver, Cancelled, journey);

    public void ApplyDriver(DriverPayload payload) => Apply(PosEcho.AvatarDriver(Driver, payload, Cancelled));
    private void Apply(DriverResult result)
    {
        var previous = Driver;
        Driver = result.State; Cancelled = result.Cancelled;
        if (previous.Kind != DriverKind.SERVER && Driver.Kind == DriverKind.SERVER)
        { AnswerFloor = Seq + 1; _pending = null; }
        if (previous != Driver) DriverChanged?.Invoke(previous, Driver);
    }

    /// <summary>Reserve before notifying takeover; a previous flight must finish before cancellation is sent.</summary>
    public void Input(P2 point)
    {
        if (Driver.Kind != DriverKind.SERVER || _disposed || ReportsPaused || !CanReport()) return;
        long seq = ++Seq;
        _pending = (point, seq);
        Apply(PosEcho.AvatarDriver(Driver, new DriverInput(seq), Cancelled));
        Flush();
    }

    /// <summary>Task 50: leaving control or entering the Task 57 guard invalidates every older flight.</summary>
    public void DiscardPendingAnswers() { AnswerFloor = Seq + 1; _pending = null; }

    public void CorrectBaseline(P2 point) { _reported = point; Dirty = false; }
    public void Tick(P2 point, bool moved)
    {
        if (_disposed || ReportsPaused || !CanReport() || Driver.Kind == DriverKind.SERVER) return;
        if (moved && (_reported is not { } p || Math.Abs(p.X-point.X) >= .01 || Math.Abs(p.Z-point.Z) >= .01)) Dirty = true;
        if (InFlight || !Dirty || clock() - _lastReport < ReportMs) return;
        Dirty = false;
        _pending = (new(Math.Floor(point.X*100+.5)/100, Math.Floor(point.Z*100+.5)/100), ++Seq);
        Flush();
    }

    private void Flush()
    {
        if (InFlight || _pending is not { } p) return;
        _pending = null;
        if (_disposed || Driver.Kind == DriverKind.SERVER || (!_propDraining && (ReportsPaused || !CanReport()))) { Dirty = true; return; }
        InFlight = true;
        _idle ??= new TaskCompletionSource();
        _lastReport = clock();
        PosEcho.PushSeq(_sent, p.Seq);
        _ = Send(p.Point, p.Seq, _lastReport);
    }

    private async Task Send(P2 point, long seq, double sentAt)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
        deadline.CancelAfter(TimeoutMs);
        try
        {
            var answer = await write(new(point.X, point.Z, seq, sentAt, Session), deadline.Token).WaitAsync(deadline.Token);
            if (_propDraining && !answer.Ok) _propDrainFailed = true;
            if (_disposed || !PosEcho.AnswerApplies(Driver, seq, AnswerFloor)) return;
            if (answer.Status is >= 200 and < 300)
            {
                if (!answer.Ok) { Dirty = true; return; }
                _reported = point; Adopted?.Invoke(answer); return;
            }
            if (answer.Status == 401) { Dirty = true; return; }
            Refused?.Invoke(point, answer.Pos);
            if (answer.Pos is { } home) { CorrectBaseline(home); Corrected?.Invoke(home); }
            if (answer.Status == 409) Apply(PosEcho.AvatarDriver(Driver, new DriverRefused(seq), Cancelled));
            double now = clock();
            if (answer.Message.Length > 0 && (answer.Reason != _quietReason || now > _quietUntil))
            { _quietReason = answer.Reason; _quietUntil = now + RefusalQuietMs; Toast?.Invoke(answer.Message); }
        }
        catch (Exception)
        {
            if (_propDraining) _propDrainFailed = true;
            if (!_disposed && PosEcho.AnswerApplies(Driver, seq, AnswerFloor)) Dirty = true;
        }
        finally
        {
            InFlight = false;
            var idle = _idle;
            if (_pending is not null && !_disposed) Flush();
            if (!InFlight) { _idle = null; idle?.TrySetResult(); }
        }
    }

    public void Dispose() { _disposed = true; _pending = null; _lifetime.Cancel(); _lifetime.Dispose(); }
}
