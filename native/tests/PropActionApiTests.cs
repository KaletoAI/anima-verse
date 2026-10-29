using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 57: actual HTTP adapter serialization, including absent partners and HTTP refusal detail.</summary>
public class PropActionApiTests
{
    private sealed class Transport : HttpMessageHandler
    {
        public readonly List<(string Method,string Path,JsonNode? Body)> Requests=new();
        public int Status=200;
        public string Body="{}";
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken ct)
        {
            var raw=request.Content is null ? null : await request.Content.ReadAsStringAsync(ct);
            Requests.Add((request.Method.Method,request.RequestUri!.AbsolutePath,raw is null ? null : JsonNode.Parse(raw)));
            return new((HttpStatusCode)Status) { Content=new StringContent(Body,Encoding.UTF8,"application/json") };
        }
    }
    [Fact]
    public async Task ExactRoutesBodiesAndRefusals()
    {
        var transport=new Transport(); using var api=new AnimaApi("http://fixture/",transport);
        using var target=JsonDocument.Parse("""{"location_id":"loc-props","room_id":"r-props","placement_id":"bench-56","variant_uid":"variant-56"}""");
        using var offers=await api.GetPropActionsAsync(); using var state=await api.GetPropActionStateAsync();
        using var solo=await api.RequestPropActionAsync("pose-56",target.RootElement,"revision-56");
        using var pair=await api.RequestPropActionAsync("pair-56",target.RootElement,"revision-56","fixture-npc");
        using var accept=await api.RespondPropActionAsync("execution-56-invite",true);
        using var cancel=await api.CancelPropActionAsync("execution-56-solo");
        Assert.Equal(6,transport.Requests.Count);
        Assert.Equal(("GET","/play/prop-actions"),(transport.Requests[0].Method,transport.Requests[0].Path));
        Assert.Equal(("GET","/play/prop-actions/state"),(transport.Requests[1].Method,transport.Requests[1].Path));
        var r=transport.Requests[2]; Assert.Equal("POST",r.Method); Assert.Equal("/play/prop-actions/request",r.Path);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse("""{"action_id":"pose-56","target":{"location_id":"loc-props","room_id":"r-props","placement_id":"bench-56","variant_uid":"variant-56"},"revision":"revision-56"}"""),r.Body));
        Assert.Equal("fixture-npc",transport.Requests[3].Body!["partner"]!.GetValue<string>());
        Assert.Equal("/play/prop-actions/respond",transport.Requests[4].Path);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse("""{"execution_id":"execution-56-invite","accept":true}"""),transport.Requests[4].Body));
        Assert.Equal("/play/prop-actions/cancel",transport.Requests[5].Path);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse("""{"execution_id":"execution-56-solo"}"""),transport.Requests[5].Body));
        transport.Status=409; transport.Body="""{"detail":{"execution_id":"","status":"refused","reason":"stale_definition"}}""";
        var error=await Assert.ThrowsAsync<ApiException>(()=>api.RequestPropActionAsync("pose-56",target.RootElement,"stale"));
        Assert.Equal(409,error.Status); Assert.Contains("stale_definition",error.Message);
        int unauthorized=0; api.Unauthorized+=()=>unauthorized++;
        transport.Status=401; await Assert.ThrowsAsync<ApiException>(()=>api.CancelPropActionAsync("execution-56-solo"));
        Assert.Equal(1,unauthorized);
    }
}
