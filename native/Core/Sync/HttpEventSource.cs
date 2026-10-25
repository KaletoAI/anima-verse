using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Sync;

/// <summary>One dispatched server-sent event.</summary>
public readonly record struct SseEvent(string Type, string Data, string LastEventId);

/// <summary>
/// The event-stream interpretation of the WHATWG HTML standard (§ 9.2.6), line by line: a blank line
/// dispatches; <c>:</c> starts a comment; <c>field: value</c> loses ONE leading space of the value; fields
/// <c>event</c>, <c>data</c> (joined with LF), <c>id</c> (ignored when it holds NUL) and <c>retry</c> (ASCII
/// digits only) — anything else is ignored. An event without data is not dispatched; the type defaults to
/// <c>message</c>. The line split (CR, LF, CRLF) is the reader's (<see cref="StreamReader.ReadLineAsync()"/>
/// splits the same three).
/// </summary>
public sealed class SseParser
{
    private string _type = "";
    private readonly StringBuilder _data = new();
    private bool _hasData;

    public string LastEventId { get; private set; } = "";
    /// <summary>The reconnection time the stream asked for (ms), or null.</summary>
    public int? RetryMs { get; private set; }

    /// <summary>Feed one line without its terminator; returns the event a blank line dispatches.</summary>
    public SseEvent? Line(string line)
    {
        if (line.Length == 0) return Dispatch();
        if (line[0] == ':') return null;
        int colon = line.IndexOf(':');
        string field = colon < 0 ? line : line[..colon];
        string value = colon < 0 ? "" : line[(colon + 1)..];
        if (value.StartsWith(' ')) value = value[1..];
        switch (field)
        {
            case "event":
                _type = value;
                break;
            case "data":
                _data.Append(value).Append('\n');
                _hasData = true;
                break;
            case "id":
                if (!value.Contains('\0')) LastEventId = value;
                break;
            case "retry":
                if (value.Length > 0 && IsAsciiDigits(value) && int.TryParse(value, out int ms)) RetryMs = ms;
                break;
        }
        return null;
    }

    private static bool IsAsciiDigits(string s)
    {
        foreach (char c in s)
            if (c is < '0' or > '9') return false;
        return true;
    }

    private SseEvent? Dispatch()
    {
        if (!_hasData)
        {
            _type = "";
            return null;
        }
        var data = _data.ToString(0, _data.Length - 1);   // the last LF goes
        var ev = new SseEvent(_type.Length > 0 ? _type : "message", data, LastEventId);
        _data.Clear();
        _hasData = false;
        _type = "";
        return ev;
    }
}

/// <summary>
/// A DOM <c>EventSource</c> over <see cref="HttpClient"/> for <see cref="SyncStream"/> — the native transport of
/// <c>GET /events/sync</c>, with the session cookie of the caller's client. Same states and the same two ways
/// to end as the standard's (§ 9.2.3):
///   • a network error, or a stream that ends or breaks after it was open, REESTABLISHES: readyState 0, an
///     error, then a new request after the reconnection time (the server's <c>retry:</c>, else 3 s);
///   • an answer that is not 200 with <c>text/event-stream</c> (a 401 of a dead session, a proxy page) FAILS:
///     readyState 2, an error, no new request — the hub's own backoff takes over.
/// The request reads headers only (<see cref="HttpCompletionOption.ResponseHeadersRead"/>) and then the body
/// line by line; <see cref="Close"/> cancels the read and drops the response, so a logout ends the stream at
/// once. Callbacks run where the read loop's awaits resume — on Godot's main thread when the source is
/// created there (its synchronization context). No <c>Last-Event-ID</c>: /events/sync sends no ids.
/// </summary>
public sealed class HttpEventSource : IEventSourceLike
{
    public const int DefaultRetryMs = 3000;

    private readonly Func<string, CancellationToken, Task<HttpResponseMessage>> _send;
    private readonly string _url;
    private readonly CancellationTokenSource _cts = new();
    private readonly Action<string>? _log;
    private volatile int _state;
    private int _retryMs;

    public Action<string>? OnMessage { get; set; }
    public Action? OnError { get; set; }
    public Action? OnPing { get; set; }
    public Action? OnBye { get; set; }
    public Action? OnOpen { get; set; }
    public int ReadyState => _state;
    /// <summary>The loop (for tests: completes once the source is closed or failed).</summary>
    public Task Loop { get; }

    /// <param name="send">GET <paramref name="url"/> with the session, headers read only, NO status check.</param>
    /// <param name="retryMs">The reconnection time until the stream names one (browsers use about 3 s).</param>
    public HttpEventSource(Func<string, CancellationToken, Task<HttpResponseMessage>> send, string url,
                           Action<string>? log = null, int retryMs = DefaultRetryMs)
    {
        _send = send;
        _retryMs = retryMs;
        _url = url;
        _log = log;
        Loop = RunAsync();
    }

    public void Close()
    {
        _state = 2;
        try { _cts.Cancel(); }
        catch (ObjectDisposedException) { }
    }

    private bool Closed => _state == 2;

    private async Task RunAsync()
    {
        // The creator sets the callbacks right after the constructor: nothing may be read before.
        await Task.Yield();
        var ct = _cts.Token;
        while (!Closed)
        {
            HttpResponseMessage? res = null;
            try
            {
                try { res = await _send(_url, ct); }
                catch (Exception) when (!Closed)
                {
                    if (!await Reestablish(ct)) return;
                    continue;
                }
                catch (Exception) { return; }
                if (Closed) return;
                var type = res.Content.Headers.ContentType?.MediaType ?? "";
                if (res.StatusCode != HttpStatusCode.OK || !type.Equals("text/event-stream", StringComparison.OrdinalIgnoreCase))
                {
                    _log?.Invoke($"sync stream: HTTP {(int)res.StatusCode} {type} — the transport gives up");
                    Fail();
                    return;
                }
                _state = 1;
                OnOpen?.Invoke();
                await ReadAsync(res, ct);
            }
            catch (Exception) when (!Closed)
            {
                // A read that broke: reestablish below.
            }
            catch (Exception)
            {
                return;
            }
            finally
            {
                res?.Dispose();
            }
            if (Closed) return;
            if (!await Reestablish(ct)) return;
        }
    }

    private async Task ReadAsync(HttpResponseMessage res, CancellationToken ct)
    {
        await using var stream = await res.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        var parser = new SseParser();
        while (!Closed)
        {
            var line = await reader.ReadLineAsync(ct);
            if (line is null) return;   // the server ended the stream
            if (parser.Line(line) is not { } ev)
            {
                if (parser.RetryMs is int r) _retryMs = r;
                continue;
            }
            if (Closed) return;
            switch (ev.Type)
            {
                case "message": OnMessage?.Invoke(ev.Data); break;
                case "ping": OnPing?.Invoke(); break;
                case "bye": OnBye?.Invoke(); break;
            }
        }
    }

    private void Fail()
    {
        if (Closed) return;
        _state = 2;
        OnError?.Invoke();
    }

    /// <summary>readyState 0 + error, wait the reconnection time; false when the source was closed meanwhile.</summary>
    private async Task<bool> Reestablish(CancellationToken ct)
    {
        if (Closed) return false;
        _state = 0;
        OnError?.Invoke();
        if (Closed) return false;
        try { await Task.Delay(_retryMs, ct); }
        catch (OperationCanceledException) { return false; }
        return !Closed && _state == 0;
    }
}
