using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Sync;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="SyncStream"/> (port of packages/player-ui/src/syncHub.ts) against a fake transport on a simulated
/// clock, the SSE line parser against hand-written frames, and <see cref="HttpEventSource"/> against fake HTTP
/// answers. Expected times derive from the constants: deadline 35 s, tolerance 10 s, retry 5 s doubling to 60 s.
/// </summary>
public class SyncStreamTests
{
    private sealed class FakeSource : IEventSourceLike
    {
        public Action<string>? OnMessage { get; set; }
        public Action? OnError { get; set; }
        public Action? OnPing { get; set; }
        public Action? OnBye { get; set; }
        public int ReadyState { get; set; }
        public bool Closed { get; private set; }
        public void Close()
        {
            Closed = true;
            ReadyState = 2;
        }
        public void Frame(string json) => OnMessage?.Invoke(json);
    }

    private sealed class Rig
    {
        public readonly ManualClock Clock = new();
        public readonly TimerQueue Timers;
        public readonly List<FakeSource> Sources = new();
        public readonly List<double> OpenedAt = new();
        public readonly SyncStream Hub;
        public int Woken;

        public Rig()
        {
            Timers = new TimerQueue(() => Clock.Ms);
            Hub = new SyncStream(url =>
            {
                Assert.Equal("/events/sync", url);
                var s = new FakeSource();
                Sources.Add(s);
                OpenedAt.Add(Clock.Ms);
                return s;
            }, Timers);
        }

        public FakeSource Last => Sources[^1];

        /// <summary>Advance to t, firing every timer at its due time.</summary>
        public void RunTo(double t)
        {
            while (Timers.NextDue is double due && due <= t)
            {
                Clock.Set(Math.Max(Clock.Ms, due));
                Timers.Pump();
            }
            Clock.Set(t);
        }
    }

    /// <summary>
    /// The opening frame of /events/sync is <c>{topics, resync: true}</c> (app/core/sync_stream.py). The FIRST
    /// resync only wakes the listeners (the generation stays 0 — nothing was fetched under an older one yet) and
    /// marks the stream connected; a LATER resync bumps the generation to 1 and wakes them again.
    /// </summary>
    [Fact]
    public void FirstResyncOnlyWakesLaterOnesInvalidate()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => rig.Woken++);
        Assert.Single(rig.Sources);   // the first listener starts the stream
        Assert.False(rig.Hub.Connected);
        rig.Last.Frame("{\"topics\": [], \"resync\": true}");
        Assert.True(rig.Hub.Connected);
        Assert.Equal(0, rig.Hub.Generation);
        Assert.Equal(1, rig.Woken);
        rig.Last.Frame("{\"topics\": [\"presence\"], \"resync\": true}");
        Assert.Equal(1, rig.Hub.Generation);
        Assert.Equal(2, rig.Woken);
    }

    /// <summary>A topic frame wakes exactly the listeners of a topic it names.</summary>
    [Fact]
    public void TopicsWakeMatchingListeners()
    {
        var rig = new Rig();
        int a = 0, b = 0;
        rig.Hub.OnTopics(new[] { "presence", "world" }, () => a++);
        rig.Hub.OnTopics(new[] { "notices" }, () => b++);
        Assert.Single(rig.Sources);   // one stream for every listener
        rig.Last.Frame("{\"topics\": [\"world\"], \"resync\": false}");
        rig.Last.Frame("{\"topics\": [\"self\"]}");
        rig.Last.Frame("not json");
        rig.Last.Frame("null");
        Assert.Equal((1, 0), (a, b));
        rig.Last.Frame("{\"topics\": [\"notices\", \"presence\"]}");
        Assert.Equal((2, 1), (a, b));
    }

    /// <summary>
    /// Deadline: opened at 0 → closed at 35 s without a frame, disconnected, retry 5 s later (40 s). A ping at
    /// 30 s re-arms: the next deadline is 65 s. The retries of a stream that never delivers double: 5, 10, 20, 40,
    /// 60, 60 s after each deadline (35 s after each open).
    /// </summary>
    [Fact]
    public void DeadlineClosesAndRetriesWithDoublingBackoff()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.Last.Frame("{\"resync\": true}");
        rig.RunTo(30_000);
        rig.Last.OnPing!();
        rig.RunTo(64_999);
        Assert.False(rig.Last.Closed);
        Assert.True(rig.Hub.Connected);
        rig.RunTo(65_000);
        Assert.True(rig.Last.Closed);
        Assert.False(rig.Hub.Connected);
        rig.RunTo(600_000);
        // Open times: 0; 65 + 5 = 70; 70 + 35 + 10 = 115; 115 + 35 + 20 = 170; 170 + 35 + 40 = 245;
        // 245 + 35 + 60 = 340; 340 + 35 + 60 = 435; 435 + 35 + 60 = 530.
        Assert.Equal(new double[] { 0, 70_000, 115_000, 170_000, 245_000, 340_000, 435_000, 530_000 }, rig.OpenedAt);
    }

    /// <summary>A resync resets the retry delay: after two missed deadlines (next delay 20 s) a resync → 5 s again.</summary>
    [Fact]
    public void ResyncResetsTheBackoff()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.RunTo(35_000 + 5000 + 35_000);   // two deadlines: delays 5 s, then 10 s scheduled
        Assert.Equal(20_000, rig.Hub.RetryMs);
        rig.RunTo(85_000);                    // reopened at 75 + 10 = 85 s
        Assert.Equal(3, rig.Sources.Count);
        rig.Last.Frame("{\"resync\": true}");
        Assert.Equal(5000, rig.Hub.RetryMs);
    }

    /// <summary>
    /// A transport that gave up (readyState 2: a 401, a non-stream answer) retries after 5 s; one that is
    /// reconnecting by itself (readyState 0) only goes disconnected and keeps its source.
    /// </summary>
    [Fact]
    public void ErrorsRetryOnlyWhenTheTransportGaveUp()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.Last.Frame("{\"resync\": true}");
        rig.Last.ReadyState = 0;
        rig.Last.OnError!();
        Assert.False(rig.Hub.Connected);
        Assert.True(rig.Hub.HasSource);
        rig.Last.Frame("{\"resync\": true}");   // the transport reconnected by itself
        Assert.True(rig.Hub.Connected);
        rig.RunTo(1000);
        rig.Last.ReadyState = 2;
        rig.Last.OnError!();
        Assert.False(rig.Hub.HasSource);
        rig.RunTo(5999);
        Assert.Single(rig.Sources);
        rig.RunTo(6000);
        Assert.Equal(2, rig.Sources.Count);
    }

    /// <summary>A suspended machine: the deadline fires 50 s late (> 35 + 10) → one more 35-s window, then it closes.</summary>
    [Fact]
    public void ALateDeadlineGrantsOneFreshWindow()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.Clock.Set(50_000);   // the process slept: nothing fired at 35 s
        rig.Timers.Pump();
        Assert.False(rig.Last.Closed);
        rig.RunTo(84_999);
        Assert.False(rig.Last.Closed);
        rig.RunTo(85_000);
        Assert.True(rig.Last.Closed);
    }

    /// <summary><c>bye</c> stops for good: closed, disconnected, no retry ever; <see cref="SyncStream.Restart"/> reopens.</summary>
    [Fact]
    public void ByeStopsUntilRestart()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.Last.Frame("{\"resync\": true}");
        rig.Last.OnBye!();
        Assert.True(rig.Last.Closed);
        Assert.True(rig.Hub.Stopped);
        rig.RunTo(1_000_000);
        Assert.Single(rig.Sources);
        int gen = rig.Hub.Generation;
        rig.Hub.Restart();
        Assert.Equal(2, rig.Sources.Count);
        Assert.Equal(gen + 1, rig.Hub.Generation);
    }

    /// <summary>Stop (logout, back to the title): the transport closes and no timer reopens it.</summary>
    [Fact]
    public void StopEndsTheStreamAndEveryTimer()
    {
        var rig = new Rig();
        rig.Hub.OnTopics(new[] { "presence" }, () => { });
        rig.Last.ReadyState = 2;
        rig.Last.OnError!();             // a retry is pending (5 s)
        rig.Hub.Stop();
        Assert.Equal(0, rig.Timers.Pending);
        rig.RunTo(1_000_000);
        Assert.Single(rig.Sources);
        Assert.False(rig.Hub.Connected);
    }

    // ---- the SSE line parser -----------------------------------------------------------------------

    private static List<SseEvent> Parse(params string[] lines)
    {
        var p = new SseParser();
        var list = new List<SseEvent>();
        foreach (var l in lines)
            if (p.Line(l) is { } ev) list.Add(ev);
        return list;
    }

    /// <summary>The three frame shapes app/core/sync_stream.py writes, and the standard's corner cases.</summary>
    [Fact]
    public void ParserReadsTheServersFrames()
    {
        var events = Parse("retry: 5000", "data: {\"topics\": [], \"resync\": true}", "",
                           "event: ping", "data: {}", "",
                           ": a comment", "event: bye", "data: {}", "");
        Assert.Equal(new[] { "message", "ping", "bye" }, events.Select(e => e.Type));
        Assert.Equal("{\"topics\": [], \"resync\": true}", events[0].Data);
        // Two data lines join with LF; ONE leading space goes; no space is fine; an event without data is not
        // dispatched and its type does not leak into the next one.
        var more = Parse("data:  two spaces", "data:b", "", "event: lonely", "", "data: x", "");
        Assert.Equal(" two spaces\nb", more[0].Data);
        Assert.Equal(new[] { "message", "message" }, more.Select(e => e.Type));
        var p = new SseParser();
        p.Line("retry: 12x");
        Assert.Null(p.RetryMs);
        p.Line("retry: 250");
        Assert.Equal(250, p.RetryMs);
    }

    // ---- the HTTP transport -----------------------------------------------------------------------

    private static HttpResponseMessage Stream(HttpStatusCode code, string body, string type = "text/event-stream")
    {
        var res = new HttpResponseMessage(code) { Content = new StringContent(body, Encoding.UTF8) };
        res.Content.Headers.ContentType = new MediaTypeHeaderValue(type);
        return res;
    }

    /// <summary>
    /// Frames arrive in order; the server ending the stream REESTABLISHES (readyState 0, an error, a new request
    /// after the stream's <c>retry:</c> of 10 ms); a 401 FAILS (readyState 2, one error, no new request).
    /// </summary>
    [Fact]
    public async Task HttpTransportReconnectsAfterAnEndAndGivesUpOnARefusal()
    {
        int requests = 0;
        var got = new List<string>();
        var errors = new List<int>();
        var failed = new TaskCompletionSource();
        HttpEventSource? src = null;
        src = new HttpEventSource((url, ct) =>
        {
            Assert.Equal("/events/sync", url);
            requests++;
            return Task.FromResult(requests == 1
                ? Stream(HttpStatusCode.OK, "retry: 10\ndata: {\"resync\": true}\n\nevent: ping\ndata: {}\n\n")
                : Stream(HttpStatusCode.Unauthorized, "{\"detail\":\"Not authenticated\"}", "application/json"));
        }, "/events/sync");
        src.OnMessage = d => { lock (got) got.Add("msg " + d); };
        src.OnPing = () => { lock (got) got.Add("ping"); };
        src.OnError = () =>
        {
            lock (errors) errors.Add(src!.ReadyState);
            if (src.ReadyState == 2) failed.TrySetResult();
        };
        await failed.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await src.Loop.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(new[] { "msg {\"resync\": true}", "ping" }, got);
        Assert.Equal(new[] { 0, 2 }, errors);
        Assert.Equal(2, requests);
        Assert.Equal(2, src.ReadyState);
    }

    /// <summary>Close during a read that waits for data (an idle stream): the loop ends at once, nothing reconnects.</summary>
    [Fact]
    public async Task HttpTransportCloseCancelsAnOpenRead()
    {
        int requests = 0;
        var opened = new TaskCompletionSource();
        var src = new HttpEventSource((_, _) =>
        {
            requests++;
            var res = new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new IdleStream()) };
            res.Content.Headers.ContentType = new MediaTypeHeaderValue("text/event-stream");
            return Task.FromResult(res);
        }, "/events/sync");
        src.OnOpen = () => opened.TrySetResult();
        await opened.Task.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(1, src.ReadyState);
        src.Close();
        await src.Loop.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(2, src.ReadyState);
        Assert.Equal(1, requests);
    }

    /// <summary>An open stream that never delivers: every read waits until it is cancelled.</summary>
    private sealed class IdleStream : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => 0; set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken ct = default)
        {
            await Task.Delay(Timeout.Infinite, ct);
            return 0;
        }
        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken ct)
            => ReadAsync(buffer.AsMemory(offset, count), ct).AsTask();
    }

    /// <summary>A network error before any answer reestablishes (readyState 0) — the browser's EventSource does too.</summary>
    [Fact]
    public async Task HttpTransportRetriesANetworkError()
    {
        int requests = 0;
        var second = new TaskCompletionSource();
        var src = new HttpEventSource((_, _) =>
        {
            requests++;
            if (requests == 1) throw new HttpRequestException("connection refused");
            second.TrySetResult();
            return Task.FromResult(Stream(HttpStatusCode.OK, "retry: 10\n"));
        }, "/events/sync", retryMs: 20);
        var states = new List<int>();
        src.OnError = () => { lock (states) states.Add(src.ReadyState); };
        await second.Task.WaitAsync(TimeSpan.FromSeconds(10));
        src.Close();
        await src.Loop.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(0, states[0]);
    }
}
