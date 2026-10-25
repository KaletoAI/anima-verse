using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

namespace AnimaNative.Sync;

/// <summary>
/// The transport the hub reads — the slice of the DOM <c>EventSource</c> that syncHub.ts uses
/// (<c>EventSourceLike</c>): unnamed messages, the named events <c>ping</c> and <c>bye</c>, errors, close, and
/// <c>readyState</c> (0 connecting — the transport reconnects by itself, 1 open, 2 closed — it gave up).
/// Implemented by <see cref="HttpEventSource"/> online and by a fake in the tests.
/// </summary>
public interface IEventSourceLike
{
    Action<string>? OnMessage { get; set; }
    Action? OnError { get; set; }
    Action? OnPing { get; set; }
    Action? OnBye { get; set; }
    int ReadyState { get; }
    void Close();
}

/// <summary>
/// Port of <c>createSyncHub</c> (packages/player-ui/src/syncHub.ts) — the client of <c>GET /events/sync</c>:
///   • frames <c>{topics:[…]}</c> wake the listeners of those topics; <c>{resync:true}</c> means "everything may
///     have changed": the FIRST one (the stream's opening frame) only wakes every listener, every later one
///     bumps <see cref="Generation"/> (the poll scheduler drops results fetched before it) and wakes everyone;
///     a resync also resets the retry delay and marks the stream connected;
///   • any delivered frame or ping re-arms a 35 s deadline; a deadline that fires closes the stream and retries —
///     unless it fired more than 35 + 10 s after it was armed (the machine slept), then it grants one more window;
///   • a transport that gave up (readyState 2) or a missed deadline retries after 5 s, doubling to 60 s;
///   • <c>bye</c> (the session is gone) stops for good until <see cref="Restart"/>.
/// <see cref="Stop"/> is the native addition: back to the title / logout ends the stream and every timer.
/// Single-threaded like <see cref="PollScheduler"/>.
/// </summary>
public sealed class SyncStream : ISyncHub
{
    public const double DeadlineMs = 35_000;
    public const double LateMs = 10_000;
    public const double RetryStartMs = 5000;
    public const double RetryMaxMs = 60_000;
    public const string Path = "/events/sync";

    private sealed class Listener
    {
        public required IReadOnlyCollection<string> Topics;
        public required Action Fn;
    }

    private readonly Func<string, IEventSourceLike> _open;
    private readonly ISyncClock _clock;
    private readonly string _url;
    private readonly List<Listener> _listeners = new();
    private readonly List<Action> _states = new();
    private IEventSourceLike? _source;
    private bool _connected, _stopped, _seenResync;
    private int _gen;
    private double _retryMs = RetryStartMs;
    private int _retryToken, _deliveryToken;
    private bool _retryPending;
    private object? _deadlineTimer, _retryTimer;

    public SyncStream(Func<string, IEventSourceLike> open, ISyncClock clock, string url = Path)
    {
        _open = open;
        _clock = clock;
        _url = url;
    }

    public bool Connected => _connected;
    public int Generation => _gen;
    /// <summary>The next retry's delay (ms) — for the log and the tests.</summary>
    public double RetryMs => _retryMs;
    /// <summary>Stopped by a <c>bye</c> or by <see cref="Stop"/>.</summary>
    public bool Stopped => _stopped;
    /// <summary>A transport is open or connecting.</summary>
    public bool HasSource => _source is not null;
    /// <summary>Counts opened transports (the tests read reconnects off it).</summary>
    public int Opens { get; private set; }

    /// <summary>A short line for the log: state, generation, next retry.</summary>
    public string Describe() => $"sync stream {(_stopped ? "stopped" : _connected ? "connected" : _source is not null ? "connecting" : "waiting")}"
                                + $" gen={_gen} retry={_retryMs / 1000:0} s opens={Opens}";

    private void State()
    {
        foreach (var fn in _states.ToList()) fn();
    }

    private void SetConnected(bool v)
    {
        if (v == _connected) return;
        _connected = v;
        State();
    }

    private void Invalidate()
    {
        _gen++;
        State();
        foreach (var l in _listeners.ToList()) l.Fn();
    }

    private void ArmDeadline(IEventSourceLike s, bool late = false)
    {
        int token = ++_deliveryToken;
        double armedAt = _clock.Now();
        _clock.ClearTimeout(_deadlineTimer);
        _deadlineTimer = _clock.SetTimeout(() =>
        {
            if (token != _deliveryToken || !ReferenceEquals(_source, s)) return;
            if (!late && _clock.Now() - armedAt > DeadlineMs + LateMs)
            {
                // Suspension prevented frame delivery; allow one fresh window after wake.
                ArmDeadline(s, true);
                return;
            }
            _source = null;
            s.Close();
            SetConnected(false);
            ScheduleRetry();
        }, DeadlineMs);
    }

    /// <summary><c>start()</c>: open the transport unless one is open, a retry is pending, or the hub stopped.</summary>
    public void Start()
    {
        if (_stopped || _source is not null || _retryPending) return;
        IEventSourceLike s;
        try { s = _open(_url); }
        catch (Exception) { ScheduleRetry(); return; }
        Opens++;
        _source = s;
        ArmDeadline(s);
        s.OnMessage = data =>
        {
            if (!ReferenceEquals(_source, s)) return;
            JsonElement frame;
            try
            {
                using var doc = JsonDocument.Parse(data);
                frame = doc.RootElement.Clone();
            }
            catch (JsonException) { return; }
            // JS `!frame || typeof frame !== 'object'`: an array is an object there, null and scalars are not.
            if (frame.ValueKind is not (JsonValueKind.Object or JsonValueKind.Array)) return;
            ArmDeadline(s);
            if (frame.ValueKind == JsonValueKind.Array) return;
            if (frame.TryGetProperty("resync", out var r) && r.ValueKind == JsonValueKind.True)
            {
                if (_seenResync) Invalidate();
                else
                {
                    _seenResync = true;
                    foreach (var l in _listeners.ToList()) l.Fn();
                }
                _retryMs = RetryStartMs;
                SetConnected(true);
            }
            else if (frame.TryGetProperty("topics", out var t) && t.ValueKind == JsonValueKind.Array)
            {
                var topics = t.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.String)
                              .Select(x => x.GetString()!).ToHashSet(StringComparer.Ordinal);
                foreach (var l in _listeners.ToList())
                    if (l.Topics.Any(topics.Contains)) l.Fn();
            }
        };
        s.OnError = () =>
        {
            if (!ReferenceEquals(_source, s)) return;
            SetConnected(false);
            if (s.ReadyState == 2)
            {
                _source = null;
                s.Close();
                ScheduleRetry();
            }
        };
        s.OnPing = () =>
        {
            if (ReferenceEquals(_source, s)) ArmDeadline(s);
        };
        s.OnBye = () =>
        {
            if (!ReferenceEquals(_source, s)) return;
            _stopped = true;
            _retryToken++;
            _retryPending = false;
            _source = null;
            s.Close();
            SetConnected(false);
        };
    }

    private void ScheduleRetry()
    {
        if (_stopped || _retryPending) return;
        _retryPending = true;
        int token = ++_retryToken;
        double delay = _retryMs;
        _retryMs = Math.Min(RetryMaxMs, _retryMs * 2);   // avoid a tight loop after a closed/401 stream
        _retryTimer = _clock.SetTimeout(() =>
        {
            if (token != _retryToken || _stopped) return;
            _retryPending = false;
            Start();
        }, delay);
    }

    public IDisposable OnTopics(IReadOnlyCollection<string> topics, Action fn)
    {
        var listener = new Listener { Topics = topics, Fn = fn };
        _listeners.Add(listener);
        Start();
        return new Off(() => _listeners.Remove(listener));
    }

    public IDisposable OnState(Action fn)
    {
        _states.Add(fn);
        return new Off(() => _states.Remove(fn));
    }

    /// <summary><c>restart()</c> (after a re-login): invalidate, forget a bye, reset the backoff, reconnect.</summary>
    public void Restart()
    {
        Invalidate();
        _stopped = false;
        _retryToken++;
        _retryPending = false;
        _retryMs = RetryStartMs;
        var old = _source;
        _source = null;
        old?.Close();
        SetConnected(false);
        Start();
    }

    /// <summary>
    /// Native: end the stream for good (back to the title, logout, a lost session) — the transport closes,
    /// pending retry and deadline timers are cancelled, nothing reconnects until <see cref="Restart"/>.
    /// </summary>
    public void Stop()
    {
        _stopped = true;
        _retryToken++;
        _deliveryToken++;
        _retryPending = false;
        _clock.ClearTimeout(_retryTimer);
        _clock.ClearTimeout(_deadlineTimer);
        _retryTimer = _deadlineTimer = null;
        var old = _source;
        _source = null;
        old?.Close();
        SetConnected(false);
    }

    private sealed class Off : IDisposable
    {
        private Action? _fn;
        public Off(Action fn) => _fn = fn;
        public void Dispose()
        {
            var fn = _fn;
            _fn = null;
            fn?.Invoke();
        }
    }
}
