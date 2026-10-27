using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Collections.Generic;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Tests.Vectors;
using AnimaNative.Scene;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

public class PropActionMotionTests
{
    [Fact]
    public void SharedVectorsFollowEveryCornerAndMeasuredEntryClock()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(VectorFile.Directory, "prop_action_motion.json")));
        foreach (var c in doc.RootElement.GetProperty("local_cases").EnumerateArray())
        {
            var route = PublicMotionRoute.Parse(c, "vector", "room")!;
            var at = route.At(c.GetProperty("age_s").GetDouble());
            var want = c.GetProperty("expect_xz");
            Assert.Equal(want[0].GetDouble(), at.X, 8);
            Assert.Equal(want[1].GetDouble(), at.Z, 8);
        }
        foreach (var c in doc.RootElement.GetProperty("entry_cases").EnumerateArray())
        {
            double phase = PublicPropEntry.Phase(c.GetProperty("elapsed_game_s").GetDouble(),
                c.GetProperty("duration_game_s").GetDouble(), c.GetProperty("game_seconds_per_real_second").GetDouble(),
                c.GetProperty("age_s").GetDouble());
            Assert.Equal(c.GetProperty("expect_phase").GetDouble(), phase, 8);
            Assert.Equal(c.GetProperty("expect_clip_s").GetDouble(), phase * c.GetProperty("clip_duration_s").GetDouble(), 8);
        }
        foreach (var c in doc.RootElement.GetProperty("support_cases").EnumerateArray())
        {
            var lift = PublicPropEntry.SupportLift(c.GetProperty("first_hips_y").GetDouble(),
                c.GetProperty("last_hips_y").GetDouble(), c.GetProperty("hips_y").GetDouble(),
                c.GetProperty("support_y").GetDouble(), c.GetProperty("root_offset").GetDouble(),
                c.GetProperty("access_y").GetDouble());
            Assert.Equal(c.GetProperty("expect_supported").GetBoolean(), lift.HasValue);
            if (lift.HasValue) Assert.Equal(c.GetProperty("expect_lift").GetDouble(), lift.Value, 8);
        }
    }

    [Fact]
    public void CancelledJourneyCannotReturnAndProjectionLossClearsRoute()
    {
        var motion = new PublicMotionState();
        using var doc = JsonDocument.Parse("{\"journey_id\":\"old\",\"room_id\":\"room\",\"waypoints\":[[0,0],[2,0],[2,3]],\"progress_m\":0,\"paces_m_s_real\":[1,1]}");
        var route = PublicMotionRoute.Parse(doc.RootElement)!;
        motion.Adopt(route, 10);
        Assert.True(motion.TryAt(13, out var at));
        Assert.Equal(2, at.X);
        Assert.Equal(1, at.Z);
        motion.CancelOwned();
        motion.Adopt(route, 14);
        Assert.False(motion.TryAt(15, out _));
        motion.Adopt(route with { JourneyId = "new" }, 15);
        Assert.True(motion.TryAt(16, out _));
        motion.Adopt(null, 16);
        Assert.False(motion.TryAt(17, out _));
    }

    [Fact]
    public void HudAcceptsOnlySemanticFurnitureActionsAndRoomPose()
    {
        foreach (string action in new[] { "pickPropAction", "pickRoomPose", "closePlaceMenu", "respondPropAction", "cancelPropAction" })
            Assert.NotNull(HudProtocol.Parse($"{{\"v\":{HudProtocol.Version},\"kind\":\"action\",\"name\":\"{action}\",\"args\":[]}}", out _));
        Assert.DoesNotContain("pickPlacePose", HudProtocol.GameActions);
        Assert.NotNull(HudProtocol.Parse($"{{\"v\":{HudProtocol.Version},\"kind\":\"prop-actions-changed\"}}", out _));
    }

    [Fact]
    public void PreflightCorrelatesPrepareAcknowledgementAndFinallyInvalidation()
    {
        var prepare = HudProtocol.Parse("{\"v\":3,\"kind\":\"prop-action-prepare\",\"request_id\":\"mutation-7\"}", out _);
        Assert.Equal("mutation-7", prepare!.RequestId);
        Assert.Null(HudProtocol.Parse("{\"v\":3,\"kind\":\"prop-action-prepare\"}", out _));
        using var ack = JsonDocument.Parse(HudProtocol.PropActionPrepared(prepare.RequestId!, "position rejected"));
        Assert.Equal("prop-action-prepared", ack.RootElement.GetProperty("kind").GetString());
        Assert.Equal("mutation-7", ack.RootElement.GetProperty("request_id").GetString());
        Assert.Equal("position rejected", ack.RootElement.GetProperty("error").GetString());
        var changed = HudProtocol.Parse("{\"v\":3,\"kind\":\"prop-actions-changed\",\"request_id\":\"mutation-7\"}", out _);
        Assert.Equal(prepare.RequestId, changed!.RequestId);
        Assert.Null(HudProtocol.Parse("{\"v\":3,\"kind\":\"prop-actions-changed\"}", out _)!.RequestId);
    }

    [Fact]
    public void OnlyOwnTravelOrVisibleSameRoomLocalProjectionIsConsumed()
    {
        using var doc = JsonDocument.Parse("{\"characters\":[{\"name\":\"own\",\"room_id\":\"r\",\"travel\":{\"journey_id\":\"j\",\"waypoints\":[[0,0],[1,0]],\"progress_m\":0,\"paces_m_s_real\":[1]},\"local_approach\":{\"waypoints\":[[4,4],[8,8]]}},{\"name\":\"foreign\",\"room_id\":\"other\",\"local_approach\":{\"journey_id\":\"private\",\"room_id\":\"other\",\"waypoints\":[[4,4],[8,8]],\"progress_m\":0}}]}");
        var rows = CharacterRow.ParseList(doc.RootElement);
        Assert.Equal("j", rows[0].OwnRoute!.JourneyId);
        Assert.Null(rows[1].RouteFor("own", "r"));
        Assert.NotNull(rows[1].RouteFor("own", "other"));
    }

    [Fact]
    public async Task SteeringWaitsForActualCancellationThenCanonicalWake()
    {
        using var state = JsonDocument.Parse("{\"current\":[{\"execution_id\":\"entry\"}],\"incoming\":[],\"outgoing\":[]}");
        var cancel = new TaskCompletionSource<JsonDocument>();
        var wake = new TaskCompletionSource<JsonDocument>();
        var wakeEntered = new TaskCompletionSource();
        var calls = new List<string>();
        var release = OwnedPropControl.ReleaseAsync(state.RootElement,
            id => { calls.Add(id); return cancel.Task; },
            () => { calls.Add("wake"); wakeEntered.SetResult(); return wake.Task; });
        Assert.Equal(new[] { "entry" }, calls);
        Assert.False(release.IsCompleted);
        cancel.SetResult(JsonDocument.Parse("{\"status\":\"cancelled\"}"));
        await wakeEntered.Task;
        Assert.Equal(new[] { "entry", "wake" }, calls);
        Assert.False(release.IsCompleted);
        wake.SetResult(JsonDocument.Parse("{\"ok\":true}"));
        await release;
    }

    [Fact]
    public async Task FailedCancellationNeverPermitsWakeOrPositionOwnership()
    {
        using var state = JsonDocument.Parse("{\"current\":[{\"execution_id\":\"entry\"}]}");
        bool woke = false;
        await Assert.ThrowsAsync<InvalidOperationException>(() => OwnedPropControl.ReleaseAsync(state.RootElement,
            _ => Task.FromResult(JsonDocument.Parse("{\"status\":\"refused\",\"reason\":\"not_participant\"}")),
            () => { woke = true; return Task.FromResult(JsonDocument.Parse("{\"ok\":true}")); }));
        Assert.False(woke);
    }

    [Fact]
    public void SupportHeightFollowsMeasuredHipsNotElapsedPhase()
    {
        Assert.Equal(0.25, PublicPropEntry.SupportPhase(1, 0.2, 0.8)!.Value, 8);
        Assert.Equal(1, PublicPropEntry.SupportPhase(1, 0.2, 0.1)!.Value, 8);
        Assert.Null(PublicPropEntry.SupportPhase(1, 1, 1));
    }

    [Fact]
    public void FurnitureGeometryJoinsExactProvenanceAndKeepsBlockedReasons()
    {
        var entry = new PlaceEntry
        {
            Id = "marker", RoomId = "room", Group = "seat", Slots = Array.Empty<Vec3>(), Fixed = true,
            PlacementId = "placement", VariantUid = "variant",
        };
        using var doc = JsonDocument.Parse("[{\"action_id\":\"blocked\",\"target\":{\"room_id\":\"room\",\"placement_id\":\"placement\",\"variant_uid\":\"variant\"},\"enabled\":false,\"reason\":\"claim_conflict\"},{\"action_id\":\"wrong-variant\",\"target\":{\"room_id\":\"room\",\"placement_id\":\"placement\",\"variant_uid\":\"other\"},\"enabled\":true}]");
        var offer = Assert.Single(PlaceSlots.PropActionsFor(entry, doc.RootElement.EnumerateArray()));
        Assert.False(offer.GetProperty("enabled").GetBoolean());
        Assert.Equal("claim_conflict", offer.GetProperty("reason").GetString());
        Assert.Empty(PlaceSlots.PropActionsFor(new PlaceEntry
        {
            Id = "room-marker", RoomId = "room", Group = "seat", Slots = Array.Empty<Vec3>(),
        }, doc.RootElement.EnumerateArray()));
    }
}
