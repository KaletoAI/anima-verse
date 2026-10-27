using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The session calls of back-to-title against a local stand-in for app/routes/auth.py
/// (login sets the HttpOnly <c>av_session</c>, status reports it, logout deletes it with
/// an expired Set-Cookie like Starlette's <c>delete_cookie</c>): after a logout this
/// process holds no session — also when the server's answer is an error.
/// </summary>
public class AnimaApiSessionTests
{
    private sealed class FakeAuthServer : IDisposable
    {
        private readonly HttpListener _listener = new();
        private readonly CancellationTokenSource _stop = new();
        public string Url { get; }
        public bool SessionAlive { get; private set; }
        public int LogoutStatus { get; set; } = 200;
        public List<string> Requests { get; } = new();
        public List<JsonElement> PositionReports { get; } = new();

        public FakeAuthServer()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            Url = $"http://127.0.0.1:{port}";
            _listener.Prefixes.Add(Url + "/");
            _listener.Start();
            _ = Task.Run(Loop);
        }

        private async Task Loop()
        {
            while (!_stop.IsCancellationRequested)
            {
                HttpListenerContext ctx;
                try { ctx = await _listener.GetContextAsync(); }
                catch (Exception) { return; }
                var path = ctx.Request.Url!.AbsolutePath;
                var cookie = ctx.Request.Cookies["av_session"]?.Value;
                Requests.Add($"{ctx.Request.HttpMethod} {path} cookie={cookie ?? "-"}");
                string body;
                if (path == "/auth/login")
                {
                    SessionAlive = true;
                    ctx.Response.AddHeader("Set-Cookie", "av_session=tok; HttpOnly; Path=/; SameSite=lax");
                    body = "{\"status\":\"success\",\"user\":{\"username\":\"demo\"}}";
                }
                else if (path == "/auth/status")
                {
                    bool ok = SessionAlive && cookie == "tok";
                    body = ok ? "{\"authenticated\":true,\"user\":{}}" : "{\"authenticated\":false,\"user\":null}";
                }
                else if (path == "/auth/logout")
                {
                    if (cookie == "tok") SessionAlive = false;
                    ctx.Response.StatusCode = LogoutStatus;
                    if (LogoutStatus == 200)
                        ctx.Response.AddHeader("Set-Cookie", "av_session=\"\"; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/; SameSite=lax");
                    body = LogoutStatus == 200 ? "{\"status\":\"success\"}" : "{\"detail\":\"boom\"}";
                }
                else if (path == "/play/pos")
                {
                    using var input = new StreamReader(ctx.Request.InputStream, ctx.Request.ContentEncoding);
                    using var report = JsonDocument.Parse(await input.ReadToEndAsync());
                    PositionReports.Add(report.RootElement.Clone());
                    body = "{\"ok\":true}";
                }
                else
                {
                    ctx.Response.StatusCode = 404;
                    body = "{\"detail\":\"Not Found\"}";
                }
                var bytes = Encoding.UTF8.GetBytes(body);
                ctx.Response.ContentType = "application/json";
                await ctx.Response.OutputStream.WriteAsync(bytes);
                ctx.Response.Close();
            }
        }

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Close();
        }
    }

    [Fact]
    public async Task LogoutEndsTheSessionAndEmptiesTheContainer()
    {
        using var server = new FakeAuthServer();
        using var api = new AnimaApi(server.Url);
        Assert.False(await api.IsAuthenticatedAsync());
        using (await api.LoginAsync("demo", "pw")) { }
        Assert.Equal("tok", api.SessionToken());
        Assert.True(await api.IsAuthenticatedAsync());

        await api.LogoutAsync();
        Assert.Null(api.SessionToken());
        Assert.False(server.SessionAlive);
        Assert.Contains("POST /auth/logout cookie=tok", server.Requests);
        Assert.False(await api.IsAuthenticatedAsync());
        Assert.Equal("GET /auth/status cookie=-", server.Requests[^1]);
    }

    /// <summary>
    /// The rebuild after a character switch: a NEW api takes over the live session of the old one without a login
    /// request — the server sees the same cookie, and the session is still the one alive.
    /// </summary>
    [Fact]
    public async Task AdoptedSessionIsTheLiveOneWithoutALogin()
    {
        using var server = new FakeAuthServer();
        string token;
        using (var first = new AnimaApi(server.Url))
        {
            using (await first.LoginAsync("demo", "pw")) { }
            token = first.SessionToken()!;
        }
        using var api = new AnimaApi(server.Url);
        Assert.Null(api.SessionToken());
        api.AdoptSession(token);
        Assert.Equal("tok", api.SessionToken());
        Assert.True(await api.IsAuthenticatedAsync());
        Assert.Equal("GET /auth/status cookie=tok", server.Requests[^1]);
        Assert.Single(server.Requests, r => r.StartsWith("POST /auth/login", StringComparison.Ordinal));
        Assert.Throws<ArgumentException>(() => api.AdoptSession(""));
    }

    [Fact]
    public async Task AFailedLogoutStillForgetsTheCookie()
    {
        using var server = new FakeAuthServer { LogoutStatus = 500 };
        using var api = new AnimaApi(server.Url);
        using (await api.LoginAsync("demo", "pw")) { }
        var e = await Assert.ThrowsAsync<ApiException>(api.LogoutAsync);
        Assert.Equal(500, e.Status);
        Assert.Null(api.SessionToken());
        Assert.False(await api.IsAuthenticatedAsync());
    }

    [Fact]
    public async Task PositionConsumerSendsCanonicalStampAndRotatesOnlyOnNewControlOwnership()
    {
        using var server = new FakeAuthServer();
        using var api = new AnimaApi(server.Url);
        using (await api.LoginAsync("demo", "pw")) { }
        api.BeginPositionControlSession();
        using (await api.ReportPositionAsync(1.25, -2.5, 1234)) { }
        using (await api.ReportPositionAsync(2.25, -3.5, 1484)) { }
        api.BeginPositionControlSession();
        using (await api.ReportPositionAsync(3.25, -4.5, 1734)) { }

        Assert.Equal(3, server.PositionReports.Count);
        var first = server.PositionReports[0];
        var second = server.PositionReports[1];
        var nextControl = server.PositionReports[2];
        foreach (var report in server.PositionReports)
        {
            Assert.Equal(new[] { "seq", "session", "t_ms", "x", "z" },
                report.EnumerateObject().Select(p => p.Name).OrderBy(name => name, StringComparer.Ordinal));
            Assert.Matches("^[A-Za-z0-9_-]{8,64}$", report.GetProperty("session").GetString()!);
            Assert.InRange(report.GetProperty("seq").GetInt32(), 1, int.MaxValue);
        }
        Assert.Equal(1.25, first.GetProperty("x").GetDouble());
        Assert.Equal(-2.5, first.GetProperty("z").GetDouble());
        Assert.Equal(1234, first.GetProperty("t_ms").GetDouble());
        Assert.Equal(1, first.GetProperty("seq").GetInt32());
        Assert.Equal(2, second.GetProperty("seq").GetInt32());
        Assert.Equal(first.GetProperty("session").GetString(), second.GetProperty("session").GetString());
        Assert.NotEqual(first.GetProperty("session").GetString(), nextControl.GetProperty("session").GetString());
        Assert.Equal(1, nextControl.GetProperty("seq").GetInt32());
        Assert.Equal("POST /play/pos cookie=tok", server.Requests[^1]);
    }
}
