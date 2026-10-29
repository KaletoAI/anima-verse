using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Audio;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 60: real AnimaApi JSON/status handling through a deterministic HTTP transport, without sockets.
/// Cookie-container replay uses the existing session client; actual loopback tests remain in AnimaApiSessionTests.</summary>
public class SoundtrackApiTests
{
    private sealed class Transport(HttpStatusCode status, string body) : HttpMessageHandler
    {
        public readonly List<string> Requests = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Requests.Add(request.Method + " " + request.RequestUri!.AbsolutePath);
            return Task.FromResult(new HttpResponseMessage(status) { Content = new StringContent(body) });
        }
    }
    [Theory]
    [InlineData(200, "{\"music\":{\"day\":[7,\"day\",\"\"]}}", "day")]
    [InlineData(200, "invalid-json", "")]
    [InlineData(404, "{\"detail\":\"absent\"}", "")]
    [InlineData(500, "{\"detail\":\"unavailable\"}", "")]
    [InlineData(401, "{\"detail\":\"expired\"}", "")]
    public void SessionApiFetchesTheListingOnceAndFailuresBecomeSilence(int status, string body, string expected)
    {
        var transport = new Transport((HttpStatusCode)status, body);
        using var api = new AnimaApi("https://fixture.invalid", transport);
        api.AdoptSession("fixture-session");
        int expired = 0; api.Unauthorized += () => expired++;
        string[]? selected = null;
        using var driver = new SoundtrackDriver(() => 0, () => new(0, "overview", null, null), (_, _) => "",
            api.GetAudioManifestAsync, (urls, _) => selected = urls, (_, _) => { });
        driver.Pump(); driver.Tick();
        Assert.NotNull(selected);
        Assert.Equal(expected == "" ? Array.Empty<string>() : new[] { expected }, selected);
        Assert.Equal(new[] { "GET /assets/audio" }, transport.Requests);
        Assert.Equal(0, expired);
        Assert.Equal("fixture-session", api.SessionToken());
    }
}
