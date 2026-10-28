using AnimaNative.Hud;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Bridge v3 (bridge.ts after the browser prop-action cutover): the native client speaks the wire without prop actions.
/// Expectations from bridge.ts by hand: <c>valid()</c> needs <c>v === 3</c>; <c>prop-action-prepare</c> needs a string
/// <c>request_id</c>; <c>prop-actions-changed</c> takes an optional string <c>request_id</c>; the scene answers a preparation
/// with <c>{v:3, kind:'prop-action-prepared', request_id, error?}</c>.
/// </summary>
public class HudProtocolV3Tests
{
    [Fact]
    public void AV2MessageIsDropped()
        => Assert.Null(HudProtocol.Parse("""{"v":2,"kind":"hud","patch":{}}""", out _));

    [Fact]
    public void PreparationNeedsAStringRequestId()
    {
        Assert.Equal("r1", HudProtocol.Parse("""{"v":3,"kind":"prop-action-prepare","request_id":"r1"}""", out _)?.RequestId);
        Assert.Null(HudProtocol.Parse("""{"v":3,"kind":"prop-action-prepare"}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":3,"kind":"prop-action-prepare","request_id":7}""", out _));
    }

    [Fact]
    public void InvalidationTakesAnOptionalStringRequestId()
    {
        var bare = HudProtocol.Parse("""{"v":3,"kind":"prop-actions-changed"}""", out _);
        Assert.Equal("prop-actions-changed", bare?.Kind);
        Assert.Null(bare?.RequestId);
        Assert.Equal("r2", HudProtocol.Parse("""{"v":3,"kind":"prop-actions-changed","request_id":"r2"}""", out _)?.RequestId);
        Assert.Null(HudProtocol.Parse("""{"v":3,"kind":"prop-actions-changed","request_id":false}""", out _));
    }

    [Fact]
    public void TheNewCommandsAreDeclaredAndTheOldPoseCommandIsGone()
    {
        Assert.NotNull(HudProtocol.Parse("""{"v":3,"kind":"action","name":"pickPropAction","args":[]}""", out _));
        Assert.NotNull(HudProtocol.Parse("""{"v":3,"kind":"action","name":"cancelPropAction","args":["e1"]}""", out _));
        Assert.Null(HudProtocol.Parse("""{"v":3,"kind":"action","name":"pickPlacePose","args":[null]}""", out _));
    }

    [Fact]
    public void PreparedCarriesTheErrorOnlyWhenThereIsOne()
    {
        Assert.Equal("""{"v":3,"kind":"prop-action-prepared","request_id":"r1","error":"no"}""", HudProtocol.PropActionPrepared("r1", "no"));
        Assert.Equal("""{"v":3,"kind":"prop-action-prepared","request_id":"r1"}""", HudProtocol.PropActionPrepared("r1", null));
    }
}
