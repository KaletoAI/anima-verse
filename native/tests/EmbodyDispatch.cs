using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using static AnimaNative.Tests.EmbodyVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>Task 47: embody.json shapes, fresh state per case, explicit sequence callbacks and NO_CANCEL decoding.</summary>
internal static class EmbodyDispatch
{
    public static Dictionary<string, Func<JsonArray, JsonNode?>> Create() => new()
    {
        ["constant"] = a => Constant(S(a[0])),
        ["pickablePlaceFor"] = a => JsonValue.Create(PlacePick.PickablePlaceFor(P(a[0]), ((JsonArray)a[1]!).Select(p => new PickPlace(S(p!["id"]), ((JsonArray)p["free"]!).Select(P).ToList())), NullableN(Arg(a, 2)))),
        ["nearestOffer"] = a => JsonValue.Create(Offers.NearestOffer(Dist(a[0], "talkTarget"), Dist(a[0], "elevator"), Dist(a[0], "stairs"), Dist(a[0], "enterOffer"))),
        ["avatarDriver"] = a => Driver(a),
        ["suppressedJourney"] = a => JsonValue.Create(PosEcho.SuppressedJourney(State(a[0]), Cancelled(a[1]), NullableS(a[2]))),
        ["answerApplies"] = a => JsonValue.Create(PosEcho.AnswerApplies(State(a[0]), (long)N(a[1]), (long)N(a[2]))),
        ["echoSequence"] = Echo,
        ["holdForSequence"] = Hold,
        ["avatarWaitsForPlace"] = a => JsonValue.Create(Readiness.AvatarWaitsForPlace(B(a[0]), S(a[1]),
            Missing(a[2]) ? null : new ResidentReadiness(S(a[2]!["ring"]), B(a[2]!["ready"])))),
        ["keyForScene"] = a => JsonValue.Create(KeyRouting.KeyForScene(B(a[0]!["typing"]), B(a[0]!["overlayOpen"]))),
        ["escTarget"] = a => JsonValue.Create(KeyRouting.EscTarget(B(a[0]!["typing"]), B(a[0]!["overlayOpen"]), B(a[0]!["menuOpen"]), B(a[1]))),
    };
    private static double? Dist(JsonNode? n, string key) => NullableN(Get(Get(n, key), "dist"));
    private static DriverState State(JsonNode? n) => new(Enum.Parse<DriverKind>(S(n!["kind"])), NullableS(n["j"]), (long)(NullableN(n["s"]) ?? 0));
    private static CancelledJourney Cancelled(JsonNode? n) => S(n) == "$NO_CANCEL" ? CancelledJourney.None : new(true, NullableS(n));
    private static JsonNode StateJson(DriverState s)
    {
        var o = new JsonObject { ["kind"] = s.Kind.ToString() };
        if (s.Kind != DriverKind.PLAYER) o["j"] = s.Journey;
        if (s.Kind == DriverKind.CANCELLING) o["s"] = s.FirstSeq;
        return o;
    }
    private static JsonNode Driver(JsonArray a)
    {
        var e = a[1]!;
        DriverEvent ev = S(e["kind"]) switch
        {
            "input" => new DriverInput((long)N(e["firstSeq"])),
            "refused" => new DriverRefused((long)N(e["seq"])),
            "payload" => new DriverPayload(B(e["hasRoute"]), NullableS(e["journeyId"]), NullableN(e["originOwnSeq"]) is double seq ? (long)seq : null),
            _ => throw new ArgumentException("Unknown driver event"),
        };
        var r = PosEcho.AvatarDriver(State(a[0]), ev, Cancelled(a[2]));
        return new JsonObject { ["state"] = StateJson(r.State), ["cancelled"] = r.Cancelled.HasValue ? r.Cancelled.Journey : "$NO_CANCEL" };
    }
    private static JsonNode Echo(JsonArray a)
    {
        var ring = new List<long>();
        foreach (var seq in (JsonArray)a[0]!) PosEcho.PushSeq(ring, (long)N(seq), (int)(NullableN(Arg(a, 3)) ?? PosEcho.EchoRingCap));
        return new JsonObject
        {
            ["ring"] = Array(ring, v => JsonValue.Create(v)),
            ["own"] = Array((JsonArray)a[2]!, o => JsonValue.Create(PosEcho.IsOwnEcho(ring, S(a[1]), Missing(o) ? null : new PositionOrigin(S(o!["session"]), (long)N(o["seq"]))))),
        };
    }
    private static JsonNode Hold(JsonArray a)
    {
        var state = new ReadinessState();
        var calls = new JsonArray();
        var frames = new JsonArray();
        foreach (var step in (JsonArray)a[0]!)
        {
            var deps = new HoldDeps(step!, calls);
            bool held;
            if (B(step!["clear"])) { Readiness.ClearApproach(deps, state); held = false; }
            else held = Readiness.HoldFor(deps, state, NullableN(step["x"]) ?? 0, NullableN(step["z"]) ?? 0);
            frames.Add(new JsonObject { ["held"] = held, ["state"] = new JsonObject { ["approachPin"] = state.ApproachPin, ["pendingSnap"] = null } });
        }
        return new JsonObject { ["frames"] = frames, ["calls"] = calls };
    }
    private sealed class HoldDeps(JsonNode step, JsonArray calls) : IReadinessDeps
    {
        public string? PlaceAt(double x, double z) => NullableS(step["id"]);
        public bool IsReady(string id) => B(step["ready"]);
        public void Pin(string id, string owner) => calls.Add(new JsonArray("pin", id, owner));
        public void Release(string id, string owner) => calls.Add(new JsonArray("release", id, owner));
    }
}
