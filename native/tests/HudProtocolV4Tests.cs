using AnimaNative.Hud;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Bridge v4 (bridge.ts after the browser prop-action cutover): the native client speaks the wire with Task 57 prop actions.
/// Expectations from bridge.ts by hand: <c>valid()</c> needs <c>v === 4</c>; <c>prop-action-prepare</c> needs a string
/// <c>request_id</c>; <c>prop-actions-changed</c> takes an optional string <c>request_id</c>; the scene answers a preparation
/// with <c>{v:4, kind:'prop-action-prepared', request_id, error?}</c>.
/// </summary>
public class HudProtocolV4Tests
{
    [Fact]
    public void TextCapabilityIsOptionalAndResetWithThePage()
    {
        var ui = new HudUi();
        ui.Apply(new System.Text.Json.Nodes.JsonObject { ["typing"] = true });
        Assert.False(ui.TextInput);
        ui.Apply(new System.Text.Json.Nodes.JsonObject { ["textInput"] = true });
        Assert.True(ui.TextInput);
        ui.Apply(new System.Text.Json.Nodes.JsonObject { ["textInput"] = "invalid" });
        Assert.True(ui.TextInput);
        ui.Reset();
        Assert.False(ui.TextInput);
    }

    [Fact]
    public void TextRoundTripsAsAnAdditiveSceneToHudV4Message()
    {
        foreach (string value in new[] { ".", "(", "ö", "\"\\", "🙂" })
        {
            var wire = System.Text.Json.Nodes.JsonNode.Parse(HudProtocol.Text(value))!;
            Assert.Equal(4, wire["v"]!.GetValue<int>());
            Assert.Equal("text", wire["kind"]!.GetValue<string>());
            Assert.Equal(value, wire["value"]!.GetValue<string>());
            // Parse validates HUD -> scene only; text must never be accepted back.
            Assert.Null(HudProtocol.Parse(wire.ToJsonString(), out _));
        }
    }

    [Fact]
    public void SpeechIsCorrelatedAndDirectionChecked()
    {
        Assert.Equal(4, HudProtocol.Version);
        var msg = HudProtocol.Parse("""{"v":4,"kind":"speech","request_id":"s1","url":"/voice.wav"}""", out _);
        Assert.Equal("s1", msg?.RequestId);
        Assert.Equal("/voice.wav", msg?.Url);
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"speech","request_id":7,"url":"/voice.wav"}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"speech","request_id":"s1"}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"speech-done","request_id":"s1"}""", out _));
        Assert.Equal("""{"v":4,"kind":"speech-done","request_id":"s1"}""", HudProtocol.SpeechDone("s1"));
        Assert.Contains("clearClientCache", HudProtocol.GameActions);
        Assert.Contains("clientCache", HudProtocol.SceneFields);
    }

    [Fact]
    public void GraphicsRenderScaleSurvivesTheV4Wire()
    {
        foreach (var scale in AnimaNative.Overview.GraphicsPrefs.RenderScales)
        {
            var prefs = new AnimaNative.Overview.GraphicsPrefs("2x", false, scale);
            var json = "{\"v\":4,\"kind\":\"action\",\"name\":\"applyGraphicsPrefs\",\"args\":["
                + AnimaNative.Overview.GraphicsPrefs.Save(prefs) + "]}";
            var wire = HudProtocol.Parse(json, out _)!;
            var p = wire.Args![0]!;
            Assert.Equal(prefs, AnimaNative.Overview.GraphicsPrefs.Check(p["antiAliasing"], p["shadows"], p["renderScale"]).Prefs);
        }
    }

    [Fact]
    public void AV2MessageIsDropped()
        => Assert.Null(HudProtocol.Parse("""{"v":2,"kind":"hud","patch":{}}""", out _));

    [Fact]
    public void PreparationNeedsAStringRequestId()
    {
        Assert.Equal("r1", HudProtocol.Parse("""{"v":4,"kind":"prop-action-prepare","request_id":"r1"}""", out _)?.RequestId);
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"prop-action-prepare"}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"prop-action-prepare","request_id":7}""", out _));
    }

    [Fact]
    public void InvalidationTakesAnOptionalStringRequestId()
    {
        var bare = HudProtocol.Parse("""{"v":4,"kind":"prop-actions-changed"}""", out _);
        Assert.Equal("prop-actions-changed", bare?.Kind);
        Assert.Null(bare?.RequestId);
        Assert.Equal("r2", HudProtocol.Parse("""{"v":4,"kind":"prop-actions-changed","request_id":"r2"}""", out _)?.RequestId);
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"prop-actions-changed","request_id":false}""", out _));
    }

    [Fact]
    public void TheNewCommandsAreDeclaredAndTheOldPoseCommandIsGone()
    {
        Assert.NotNull(HudProtocol.Parse("""{"v":4,"kind":"action","name":"pickPropAction","args":[]}""", out _));
        Assert.NotNull(HudProtocol.Parse("""{"v":4,"kind":"action","name":"cancelPropAction","args":["e1"]}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":4,"kind":"action","name":"pickPlacePose","args":[null]}""", out _));
    }

    [Fact]
    public void SceneInvalidationPreservesCorrelationOrOmitsIt()
    {
        Assert.Equal("""{"v":4,"kind":"prop-actions-changed","request_id":"native:1"}""", HudProtocol.PropActionsChanged("native:1"));
        Assert.Equal("""{"v":4,"kind":"prop-actions-changed"}""", HudProtocol.PropActionsChanged());
    }

    [Fact]
    public void PreparedCarriesTheErrorOnlyWhenThereIsOne()
    {
        Assert.Equal("""{"v":4,"kind":"prop-action-prepared","request_id":"r1","error":"no"}""", HudProtocol.PropActionPrepared("r1", "no"));
        Assert.Equal("""{"v":4,"kind":"prop-action-prepared","request_id":"r1"}""", HudProtocol.PropActionPrepared("r1", null));
    }
}
