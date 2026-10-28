using System.Text.Json.Nodes;
using AnimaNative.Embody;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 48: browser key precedence, including menu/lift Esc and nearest offer dispatch.</summary>
public class SceneKeysTests
{
    [Fact]
    public void EscapeClosesMenuBeforeLeavingModeAndOverlayOwnsIt()
    {
        var state = new JsonObject { ["mode"] = "embodied", ["elevatorOpen"] = true };
        Assert.Equal("elevator", SceneKeys.Escape(false, false, true, state));
        state["elevatorOpen"] = false;
        Assert.Equal("menu", SceneKeys.Escape(false, false, true, state));
        Assert.Equal("mode", SceneKeys.Escape(false, false, false, state));
        Assert.Equal("ignore", SceneKeys.Escape(false, true, true, state));
    }

    [Fact]
    public void FResolvesNearestOfferBeforeSelectedAvatarFallback()
    {
        var state = new JsonObject { ["mode"] = "overview", ["selected"] = new JsonObject { ["isAvatar"] = true } };
        Assert.Equal("enterEmbodied", SceneKeys.Interact(state)?.Name);
        state["talkTarget"] = new JsonObject { ["dist"] = 2.4 };
        state["stairs"] = new JsonObject { ["dist"] = 1.0 };
        Assert.Equal("rideStairs", SceneKeys.Interact(state)?.Name);
        state["talkTarget"]!["dist"] = .5;
        Assert.Equal("openChat", SceneKeys.Interact(state)?.Name);
        state["talkTarget"] = null; state["stairs"] = null; state["mode"] = "embodied";
        Assert.Null(SceneKeys.Interact(state));
        state["elevator"] = new JsonObject { ["dist"] = 1, ["levels"] = new JsonArray(0, 2), ["current"] = 0 };
        var ride = SceneKeys.Interact(state)!;
        Assert.Equal("rideElevator", ride.Name);
        Assert.Equal(2, ride.Argument!.GetValue<int>());
    }
}
