using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Hud;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

public class ItemPayloadTests
{
    private const string SamplePayloadJson = """
    {
      "location_id": "loc-inn",
      "items": [
        {
          "item_id": "ledger-book",
          "room_id": "r-parlour",
          "name": "Harbour Ledger",
          "quantity": 3,
          "at": [1.25, -2.5],
          "y": 0.78,
          "yaw": 35.0,
          "size_m": 0.34,
          "model_url": "/inventory/items/ledger-book/model?v=abc123",
          "model_version": "abc123",
          "image_url": "/inventory/items/ledger-book/image",
          "actions": [
            { "id": "look", "label": "Look at", "source": "core" },
            { "id": "take", "label": "Take", "source": "core" },
            { "id": "read", "label": "Read", "source": "core" },
            { "id": "polish", "label": "Polish cover", "source": "pkg.bookcare" }
          ]
        },
        {
          "item_id": "brass-key",
          "room_id": "r-cellar",
          "name": "Brass Key",
          "quantity": 1,
          "at": [-0.5, 1.75],
          "y": 0.0,
          "yaw": -90.0,
          "size_m": 0.18,
          "image_url": "/inventory/items/brass-key/image",
          "actions": [
            { "id": "look", "label": "Look at", "source": "core" },
            { "id": "take", "label": "Take", "source": "core" }
          ]
        }
      ]
    }
    """;

    [Fact]
    public void ParsesGlbAndCardItemsWithEveryFieldAndUnknownActions()
    {
        using var doc = JsonDocument.Parse(SamplePayloadJson);
        var items = ItemPayload.Parse(doc.RootElement);

        Assert.Equal(2, items.Count);

        var glb = items[0];
        Assert.Equal("ledger-book", glb.ItemId);
        Assert.Equal("r-parlour", glb.RoomId);
        Assert.Equal("Harbour Ledger", glb.Name);
        Assert.Equal(3, glb.Quantity);
        Assert.Equal(1.25, glb.X);
        Assert.Equal(-2.5, glb.Z);
        Assert.Equal(0.78, glb.Y);
        Assert.Equal(35.0, glb.Yaw);
        Assert.Equal(0.34, glb.SizeM);
        Assert.Equal("/inventory/items/ledger-book/model?v=abc123", glb.ModelUrl);
        Assert.Equal("/inventory/items/ledger-book/image", glb.ImageUrl);
        Assert.Equal(4, glb.Actions.Count);
        Assert.Equal(new WorldItemAction("look", "Look at", "core"), glb.Actions[0]);
        Assert.Equal(new WorldItemAction("take", "Take", "core"), glb.Actions[1]);
        Assert.Equal(new WorldItemAction("read", "Read", "core"), glb.Actions[2]);
        Assert.Equal(new WorldItemAction("polish", "Polish cover", "pkg.bookcare"), glb.Actions[3]);

        var card = items[1];
        Assert.Equal("brass-key", card.ItemId);
        Assert.Equal("r-cellar", card.RoomId);
        Assert.Equal("Brass Key", card.Name);
        Assert.Equal(1, card.Quantity);
        Assert.Equal(-0.5, card.X);
        Assert.Equal(1.75, card.Z);
        Assert.Equal(0.0, card.Y);
        Assert.Equal(-90.0, card.Yaw);
        Assert.Equal(0.18, card.SizeM);
        Assert.Null(card.ModelUrl);
        Assert.Equal("/inventory/items/brass-key/image", card.ImageUrl);
        Assert.Equal(2, card.Actions.Count);
        Assert.Equal(new WorldItemAction("look", "Look at", "core"), card.Actions[0]);
        Assert.Equal(new WorldItemAction("take", "Take", "core"), card.Actions[1]);
    }

    [Fact]
    public void NullModelUrlAndMalformedEntriesAreHandledSafely()
    {
        const string json = """
        {
          "location_id": "loc-test",
          "items": [
            "not-an-object",
            { "item_id": "", "room_id": "r1", "at": [0, 0], "y": 0 },
            { "item_id": "bad-at", "room_id": "r1", "at": [1], "y": 0 },
            { "item_id": "bad-size", "room_id": "r1", "at": [0, 0], "y": 0, "size_m": -1 },
            { "item_id": "bad-qty", "room_id": "r1", "at": [0, 0], "y": 0, "quantity": 0 },
            {
              "item_id": "null-urls",
              "room_id": "r1",
              "name": "Plain Stone",
              "quantity": 2,
              "at": [2.0, 3.0],
              "y": 0.1,
              "yaw": 0,
              "size_m": 0.2,
              "model_url": null,
              "image_url": null,
              "actions": ["inspect_runes"]
            }
          ]
        }
        """;

        using var doc = JsonDocument.Parse(json);
        var items = ItemPayload.Parse(doc.RootElement);

        var sole = Assert.Single(items);
        Assert.Equal("null-urls", sole.ItemId);
        Assert.Null(sole.ModelUrl);
        Assert.Null(sole.ImageUrl);
        Assert.Single(sole.Actions);
        Assert.Equal("inspect_runes", sole.Actions[0].Id);
    }

    [Fact]
    public void HudProtocolV4AndNearestOfferIncludeItems()
    {
        Assert.Equal(4, HudProtocol.Version);
        Assert.Contains("itemMenu", HudProtocol.SceneFields);
        Assert.Contains("pickItemAction", HudProtocol.GameActions);
        Assert.Contains("closeItemMenu", HudProtocol.GameActions);
        Assert.Contains("openItemReader", HudProtocol.UiActions);
        Assert.Equal("""{"v":4,"kind":"ui","name":"openItemReader","args":["ledger-book"]}""",
            HudProtocol.Ui("openItemReader", JsonValue.Create("ledger-book")));

        var pickMsg = HudProtocol.Parse("""{"v":4,"kind":"action","name":"pickItemAction","args":["brass-key","take"]}""", out _);
        Assert.NotNull(pickMsg);
        Assert.NotNull(HudProtocol.Parse("""{"v":4,"kind":"action","name":"closeItemMenu","args":[]}""", out _));

        Assert.Equal("item", Offers.NearestOffer(2.2, null, 1.4, null, 0.8));
        // Equal distance preserves existing tie-break priority before item.
        Assert.Equal("stairs", Offers.NearestOffer(null, null, 1.0, null, 1.0));

        var cmd = SceneKeys.Interact(new JsonObject
        {
            ["talkTarget"] = new JsonObject { ["dist"] = 2.0 },
            ["itemOffer"] = new JsonObject { ["dist"] = 0.6 },
        });
        Assert.Equal("openNearestItemMenu", cmd?.Name);
        Assert.False(cmd?.Ui ?? true);
    }

    [Fact]
    public async Task GetLocationItemsUsesConditionalEtagOn304()
    {
        string? seenIfNoneMatch = null;
        int calls = 0;
        var handler = new ConditionalHandler(req =>
        {
            calls++;
            seenIfNoneMatch = req.Headers.IfNoneMatch.ToString();
            if (calls == 2 && seenIfNoneMatch == "\"etag-items-1\"")
                return new HttpResponseMessage(HttpStatusCode.NotModified);

            var res = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(SamplePayloadJson, Encoding.UTF8, "application/json"),
            };
            res.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"etag-items-1\"");
            return res;
        });

        using var api = new AnimaApi("http://fixture.invalid:8000", handler);
        using var first = await api.GetLocationItemsAsync("loc-inn");
        Assert.NotNull(first);
        Assert.Equal(2, ItemPayload.Parse(first!.RootElement).Count);

        using var second = await api.GetLocationItemsAsync("loc-inn");
        Assert.Equal(2, calls);
        Assert.Equal("\"etag-items-1\"", seenIfNoneMatch);
        Assert.NotNull(second);
        Assert.Equal(2, ItemPayload.Parse(second!.RootElement).Count);
    }

    private sealed class ConditionalHandler(System.Func<HttpRequestMessage, HttpResponseMessage> respond) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(respond(request));
    }
}
