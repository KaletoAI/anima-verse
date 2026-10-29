using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using Xunit;

namespace AnimaNative.Tests;

public class AvatarRecoveryTests
{
    private static JsonElement Json(string raw) => JsonSerializer.Deserialize<JsonElement>(raw);
    private const string Present = """{"avatar":"Kai","characters":[{"name":"Kai","pos":{"x":1,"z":2},"location_id":""}]}""";
    private sealed class Transport : HttpMessageHandler
    {
        public readonly List<(string Method, string Path, string? Body)> Requests = new();
        public Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> Answer = (_, _) => Task.FromResult(Response(200, "{}"));
        public static HttpResponseMessage Response(int status, string body) => new((HttpStatusCode)status)
        { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Requests.Add((request.Method.Method, request.RequestUri!.AbsolutePath,
                request.Content is null ? null : await request.Content.ReadAsStringAsync(ct)));
            return await Answer(request, ct);
        }
    }

    [Theory]
    [InlineData("""{"user":{"settings":{"active_character":"Kai"}}}""", "Other", "Account", "Kai", 0)]
    [InlineData("{}", "Kai", "Account", "Kai", 0)]
    [InlineData("{}", "", "Kai", "Kai", 1)]
    [InlineData("{}", "", "", null, 1)]
    public async Task RemembersLoginThenFirstMapThenAccountOnlyOnce(string login, string avatar, string account, string? expected, int gets)
    {
        var transport = new Transport { Answer = (_, _) => Task.FromResult(Transport.Response(200,
            JsonSerializer.Serialize(new { active_character = account }))) };
        using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        int remembered = 0; recovery.Remembered += _ => remembered++;
        recovery.RememberLogin(Json(login));
        await recovery.RememberFirstMapAsync(Json(JsonSerializer.Serialize(new { avatar })));
        await recovery.RememberFirstMapAsync(Json("""{"avatar":"Stranger"}"""));
        Assert.Equal(expected, recovery.OwnCharacter);
        Assert.Equal(gets, transport.Requests.Count);
        if (gets > 0) Assert.Equal(("GET", "/account/characters", null), transport.Requests[0]);
        Assert.Equal(expected is null ? 0 : 1, remembered);
    }

    [Theory]
    [InlineData("""{"avatar":"","characters":[]}""")]
    [InlineData("""{"avatar":"Other","characters":[{"name":"Other","pos":{"x":3,"z":4}}]}""")]
    [InlineData("""{"avatar":"Kai","characters":[{"name":"Kai","location_id":"","pos":null}]}""")]
    [InlineData("""{"avatar":"Kai","characters":[]}""")]
    public async Task RestoresOnlyRememberedAvatarAndWaitsForOwnPointAndFigure(string missing)
    {
        var transport = new Transport();
        using var api = new AnimaApi("http://fixture/", transport);
        int polls = 0;
        using var recovery = new AvatarRecovery(api, () => { polls++; return Task.CompletedTask; });
        await recovery.RememberFirstMapAsync(Json(Present));
        Assert.True(recovery.TryBegin(Json(missing)));
        Assert.True(recovery.TryBegin(Json(missing)));
        await recovery.Request!;
        Assert.Single(transport.Requests);
        Assert.Equal(("POST", "/account/switch-character", "{\"character_name\":\"Kai\"}"), transport.Requests[0]);
        Assert.Equal(1, polls);
        Assert.False(recovery.Tick(Json(missing), true));
        Assert.True(recovery.Waiting);
        Assert.False(recovery.Tick(Json(Present), false));
        Assert.True(recovery.Tick(Json(Present), true));
        Assert.False(recovery.Waiting);
        Assert.False(recovery.TryBegin(Json(missing)));
        Assert.Single(transport.Requests);
    }

    [Theory]
    [InlineData("""{"avatar":"Kai","characters":[{"name":"Kai","location_id":"home","pos":null}]}""")]
    [InlineData(Present)]
    public async Task DoesNotSwitchForAPlacedAvatar(string map)
    {
        var transport = new Transport(); using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        await recovery.RememberFirstMapAsync(Json(Present));
        Assert.False(recovery.TryBegin(Json(map)));
        Assert.Empty(transport.Requests);
    }

    [Fact]
    public async Task RefusalPreservesServerSentenceAndDoesNotPollOrRetry()
    {
        var transport = new Transport { Answer = (_, _) => Task.FromResult(Transport.Response(403,
            """{"detail":"No access to character 'Kai'"}""")) };
        using var api = new AnimaApi("http://fixture/", transport);
        int polls = 0;
        using var recovery = new AvatarRecovery(api, () => { polls++; return Task.CompletedTask; });
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        Assert.Equal("No access to character 'Kai'", recovery.Failure);
        Assert.False(recovery.Waiting); Assert.Equal(0, polls);
        Assert.False(recovery.TryBegin(Json("{}"))); Assert.Single(transport.Requests);
    }

    [Fact]
    public async Task NoRememberedCharacterDoesNotSwitchToALaterMapAvatar()
    {
        var transport = new Transport(); using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        await recovery.RememberFirstMapAsync(Json("{}"));
        Assert.False(recovery.TryBegin(Json(Present)));
        Assert.Null(recovery.OwnCharacter); Assert.Single(transport.Requests);
    }

    [Fact]
    public async Task TimesOutAfterTenSecondsWithoutRetryAndAllowsANewPress()
    {
        double now = 0; var transport = new Transport(); using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask, () => now);
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        now = 9999; Assert.False(recovery.Tick(Json("{}"), true)); Assert.True(recovery.Waiting);
        now = 10000; Assert.False(recovery.Tick(Json("{}"), true));
        Assert.Equal("Your avatar is not on the map yet.", recovery.Failure);
        Assert.False(recovery.Waiting); Assert.Single(transport.Requests);
        recovery.Cancel(); Assert.True(recovery.TryBegin(Json("{}"))); await recovery.Request!;
        Assert.Equal(2, transport.Requests.Count);
    }

    [Fact]
    public async Task CancelledOrExpiredWriteCannotRepollOrReviveControl()
    {
        var answer = new TaskCompletionSource<HttpResponseMessage>();
        var transport = new Transport { Answer = (_, _) => answer.Task };
        using var api = new AnimaApi("http://fixture/", transport);
        int polls = 0;
        using var recovery = new AvatarRecovery(api, () => { polls++; return Task.CompletedTask; });
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); var request = recovery.Request!;
        recovery.Cancel(); answer.SetResult(Transport.Response(200, "{}")); await request;
        Assert.Equal(0, polls); Assert.False(recovery.Waiting);
        Assert.False(recovery.Tick(Json(Present), true)); Assert.Null(recovery.Failure);
    }

    [Fact]
    public async Task UnauthorizedSwitchUsesExistingSessionExpirySignal()
    {
        var transport = new Transport { Answer = (_, _) => Task.FromResult(Transport.Response(401, "{}")) };
        using var api = new AnimaApi("http://fixture/", transport);
        int expired = 0; api.Unauthorized += () => expired++;
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        Assert.Equal(1, expired); Assert.False(recovery.Waiting);
    }

    [Fact]
    public async Task PlacedAvatarKeepsWaitingForItsModelBeyondPlacementDeadline()
    {
        double now = 0; var transport = new Transport(); using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask, () => now);
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        now = 10001;
        Assert.False(recovery.Tick(Json(Present), false));
        Assert.Null(recovery.Failure); Assert.True(recovery.Waiting);
        Assert.True(recovery.Tick(Json(Present), true));
    }

    [Fact]
    public async Task TransportFailureWaitsForThePlacementDeadline()
    {
        double now = 0;
        var transport = new Transport { Answer = (_, _) => Task.FromException<HttpResponseMessage>(new HttpRequestException("offline")) };
        using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask, () => now);
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        Assert.Null(recovery.Failure); Assert.True(recovery.Waiting);
        now = 10000; recovery.Tick(Json("{}"), false);
        Assert.Equal("Your avatar is not on the map yet.", recovery.Failure);
        Assert.Single(transport.Requests);
    }

    [Fact]
    public async Task AuthoritativePlacementRecoversWhenTheSwitchResponseWasLost()
    {
        var transport = new Transport { Answer = (_, _) => Task.FromException<HttpResponseMessage>(new HttpRequestException("response lost")) };
        using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        await recovery.RememberFirstMapAsync(Json(Present));
        recovery.TryBegin(Json("{}")); await recovery.Request!;
        Assert.True(recovery.Tick(Json(Present), true));
        Assert.False(recovery.Waiting); Assert.Null(recovery.Failure);
        Assert.Single(transport.Requests);
    }

    [Fact]
    public async Task ReadinessWaitDoesNotSpendTheSingleSwitchAttempt()
    {
        var transport = new Transport(); using var api = new AnimaApi("http://fixture/", transport);
        using var recovery = new AvatarRecovery(api, () => Task.CompletedTask);
        await recovery.RememberFirstMapAsync(Json(Present));
        Assert.False(recovery.TryBegin(Json(Present)));
        Assert.True(recovery.TryBegin(Json("{}"))); await recovery.Request!;
        Assert.Single(transport.Requests);
    }
}
