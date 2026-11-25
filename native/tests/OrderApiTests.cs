using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Plan E3 Task 5: <c>GET /play/orders?since=</c> over the real HTTP adapter and the payload reader.</summary>
public class OrderApiTests
{
    private sealed class Transport : HttpMessageHandler
    {
        public readonly List<string> Requests = new();
        public string Body = "{}";
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Requests.Add(request.Method.Method + " " + request.RequestUri!.PathAndQuery);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(Body, Encoding.UTF8, "application/json") });
        }
    }

    private const string Good = """{"order_id":"ord-1","revision":1,"seq":4,"kind":"walk","issued_motion_s":10,"eta_motion_s":12,"flip_motion_s":12,"deadline_motion_s":22,"status":"approaching","awaits":"","gait":"walk","speed_m_s":1.4,"target":{"location_id":"loc","room_id":"r","level":0,"x":1,"z":2},"hint_route":[],"snap":false,"actors":[{"name":"Ona","start":{"x":0,"y":0,"z":0}}]}""";

    [Fact]
    public async Task GetOrdersAsksSinceTheGivenSeq()
    {
        var transport = new Transport { Body = """{"orders":[],"seq":0,"motion_now":1}""" };
        using var api = new AnimaApi("http://fixture/", transport);
        using var doc = await api.GetOrdersAsync(7);
        Assert.Equal(new[] { "GET /play/orders?since=7" }, transport.Requests);
    }

    [Fact]
    public void PayloadKeepsGoodOrdersAndDropsBrokenOnes()
    {
        // One good order, one without an order_id, one of an unknown kind: only the good one is played.
        using var doc = JsonDocument.Parse("""{"orders":[""" + Good + """,{"kind":"walk"},{"order_id":"x","kind":"pair"}],"seq":9,"motion_now":123.5}""");
        var p = OrdersPayload.Parse(doc.RootElement);
        Assert.Equal(new[] { "ord-1" }, p.Orders.Select(o => o.Id));
        Assert.Equal(9, p.Seq);
        Assert.Equal(123.5, p.MotionNow);
    }

    [Fact]
    public void PayloadWithoutFieldsIsEmpty()
    {
        using var doc = JsonDocument.Parse("{}");
        var p = OrdersPayload.Parse(doc.RootElement);
        Assert.Empty(p.Orders);
        Assert.Equal(0, p.Seq);
        Assert.Null(p.MotionNow);
    }
}
