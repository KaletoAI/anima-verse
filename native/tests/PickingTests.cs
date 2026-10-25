using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The pure parts of the overview picking (Task 9): the click chain, the open view and its overview
/// auto-close, the event-pin rule and the ray math. Every expected value is derived BY HAND in the
/// comment of its case (from main.ts / engine.ts / three.js, not from a run).
/// </summary>
public class PickChainTests
{
    [Fact]
    public void FigureEatsTheClickAndKeepsThePanel()
    {
        // engine.ts pointerup: pickFigure true → return; onPick is never asked → info untouched.
        Assert.Equal(new PickOutcome("Ada", InfoChange.Unchanged, null), PickChain.Resolve("Ada", null));
        // A figure standing inside a location: still the figure, the location's panel does not open.
        Assert.Equal(new PickOutcome("Ada", InfoChange.Unchanged, null), PickChain.Resolve("Ada", "loc-house"));
    }

    [Fact]
    public void LocationClearsTheSelectionAndShowsItsPanel()
    {
        // pickFigure: no figure → setGameState({selected: null}), false → onPick(id) → info = panel(id).
        Assert.Equal(new PickOutcome(null, InfoChange.Show, "loc-house"), PickChain.Resolve(null, "loc-house"));
    }

    [Fact]
    public void EmptyGroundClearsBoth()
    {
        // selected = null (pickFigure miss) and onPick(null) → info = null.
        Assert.Equal(new PickOutcome(null, InfoChange.Clear, null), PickChain.Resolve(null, null));
    }
}

public class OpenViewTests
{
    [Fact]
    public void Constants()
    {
        Assert.Equal(60, OpenView.CloseCamDist);
        Assert.Equal(3, OpenView.CloseTargetFootprints);
        Assert.Equal(12, OpenView.CloseTargetMinM);
        Assert.Equal(15, OpenView.OpenFlyDist);
    }

    [Theory]
    // max(12, 3·w): w 2 → 6 < 12 → 12; w 4 → 12 = 12; w 10 → 30; w 0 (no footprint) → 12.
    [InlineData(2, 12)]
    [InlineData(4, 12)]
    [InlineData(10, 30)]
    [InlineData(0, 12)]
    public void CloseTargetDistance(double width, double want) => Assert.Equal(want, OpenView.CloseTargetDist(width));

    [Theory]
    // Centre (10, −5), width 10 → limit 30 m.
    // Camera exactly at 60 → not "> 60" → stays; 60.0001 → closes.
    [InlineData(60, 10, -5, false)]
    [InlineData(60.0001, 10, -5, true)]
    // Target (28, 19): offset (18, 24) → hypot 30 exactly (3-4-5 × 6) → not "> 30" → stays.
    [InlineData(20, 28, 19, false)]
    // Target (28, 19.5): offset (18, 24.5) → √(324 + 600.25) = √924.25 = 30.4015… > 30 → closes.
    [InlineData(20, 28, 19.5, true)]
    // Height is ignored: the rule measures on the ground plane only (y is not an argument at all).
    // Target (−15, −5): offset 25 ≤ 30, camera 59 ≤ 60 → stays.
    [InlineData(59, -15, -5, false)]
    public void AutoCloseRule(double camDist, double tx, double tz, bool close)
        => Assert.Equal(close, OpenView.ShouldClose(camDist, tx, tz, 10, -5, 10));

    [Fact]
    public void AutoCloseOnASmallFootprintUsesTheFloor()
    {
        // Width 1 (a shrine): 3 · 1 = 3 < 12 → the limit is 12. Offset (12, 0) → stays; (12.01, 0) → closes.
        Assert.False(OpenView.ShouldClose(30, 12, 0, 0, 0, 1));
        Assert.True(OpenView.ShouldClose(30, 12.01, 0, 0, 0, 1));
    }

    [Theory]
    // min(targetDist, 15): a camera already at 8 m stays at 8 (no zooming OUT), from 40 m → 15.
    [InlineData(8, 8)]
    [InlineData(15, 15)]
    [InlineData(40, 15)]
    public void FlyInNeverZoomsOut(double targetDist, double want) => Assert.Equal(want, OpenView.FlyInDist(targetDist));

    [Fact]
    public void OneOpenLocationAtATime()
    {
        var v = new OpenView();
        Assert.Null(v.OpenId);
        // Not openable (no interior): openLocation returns early, nothing changes.
        Assert.False(v.TryOpen("yard", openable: false, out var closed));
        Assert.Null(closed);
        Assert.Null(v.OpenId);
        // First open: nothing closes.
        Assert.True(v.TryOpen("house", openable: true, out closed));
        Assert.Null(closed);
        Assert.Equal("house", v.OpenId);
        // Same again: `if (openLocationId === id) return`.
        Assert.False(v.TryOpen("house", openable: true, out closed));
        Assert.Null(closed);
        // Another: the house closes, the shop is THE open one.
        Assert.True(v.TryOpen("shop", openable: true, out closed));
        Assert.Equal("house", closed);
        Assert.Equal("shop", v.OpenId);
        // Close: returns what closed; a second close is a no-op.
        Assert.Equal("shop", v.Close());
        Assert.Null(v.OpenId);
        Assert.Null(v.Close());
    }

    [Theory]
    [InlineData("Harbour House", "Harbour House")]
    [InlineData(" Harbour ", " Harbour ")]      // the badge keeps the name untrimmed (`openView = name`)
    [InlineData("", null)]
    [InlineData("   ", null)]
    [InlineData(" \t", null)]              // NBSP and tab are JS white space → blank
    [InlineData(null, null)]
    public void Badge(string? name, string? want) => Assert.Equal(want, OpenView.BadgeName(name));
}

public class EventPinRuleTests
{
    [Fact]
    public void GlyphPerLocation()
    {
        // `evs.some(e => e.category === 'danger') ? '🔥' : '❗'`, an empty list gets no pin.
        Assert.Equal("🔥", EventPinRule.GlyphFor(new string?[] { "social", "danger" }));
        Assert.Equal("❗", EventPinRule.GlyphFor(new string?[] { "social", null }));
        Assert.Equal("❗", EventPinRule.GlyphFor(new string?[] { "Danger" }));   // case matters (=== 'danger')
        Assert.Null(EventPinRule.GlyphFor(Array.Empty<string?>()));
    }

    [Fact]
    public void WantedOnlyForKnownPlaces()
    {
        var events = new Dictionary<string, IReadOnlyCollection<string?>>
        {
            ["a"] = new string?[] { "danger" },
            ["b"] = new string?[] { "news" },
            ["c"] = Array.Empty<string?>(),          // `!evs.length` → skipped
            ["ghost"] = new string?[] { "danger" },  // `!places.has(id)` → skipped
        };
        var wanted = EventPinRule.Wanted(events, id => id != "ghost");
        Assert.Equal(new Dictionary<string, string> { ["a"] = "🔥", ["b"] = "❗" }, wanted);
    }

    [Fact]
    public void ExistingPinsAreKeptAsTheyAre()
    {
        // Pins a (❗) and b exist. Now: a has a danger event (🔥), b has none, c is new.
        // main.ts: b goes (not wanted), c comes, a is skipped (`if (eventPins.has(locId)) continue`) — it keeps ❗.
        var (remove, add) = EventPinRule.Diff(new[] { "a", "b" },
                                              new Dictionary<string, string> { ["a"] = "🔥", ["c"] = "❗" });
        Assert.Equal(new[] { "b" }, remove);
        Assert.Equal(new[] { new KeyValuePair<string, string>("c", "❗") }, add);
    }

    [Fact]
    public void PlacementAndBob()
    {
        // setY(tile.height + 3.5): a 4 m building → 7.5, absolute.
        Assert.Equal(7.5, EventPinRule.PinY(4));
        // bob 0, dt 0.5 → 1.1; dy = sin(1.1) · 0.008 = 0.891207360061435 · 0.008 = 0.00712965888049148.
        var (bob, dy) = EventPinRule.BobStep(0, 0.5);
        Assert.Equal(1.1, bob, 12);
        Assert.Equal(0.00712965888049148, dy, 12);
        // A further frame of dt 1/60 → bob 1.1 + 0.036666… = 1.136666…; sin = 0.90724… → dy 0.0072579….
        (bob, dy) = EventPinRule.BobStep(bob, 1.0 / 60);
        Assert.Equal(1.1366666666666667, bob, 12);
        Assert.Equal(Math.Sin(1.1366666666666667) * 0.008, dy, 15);
        Assert.InRange(dy, 0.007257, 0.007259);
    }

    [Theory]
    // places.ts: !isBuilding ? (forest ? 3 : 0.3) : natureSite ? (forest ? 3 : 0.6) : 4.
    [InlineData(false, false, "forest", 3)]
    [InlineData(false, false, "grass", 0.3)]
    [InlineData(true, true, "forest", 3)]
    [InlineData(true, true, "water", 0.6)]
    [InlineData(true, false, "house", 4)]
    public void DefaultHeights(bool isBuilding, bool natureSite, string style, double want)
        => Assert.Equal(want, EventPinRule.DefaultPlaceHeight(isBuilding, natureSite, style));
}

public class RayMathTests
{
    private static readonly Vec3 O = new(0, 0, 0);

    [Fact]
    public void BoxSlabs()
    {
        // Box x 2..4, y −1..1, z −1..1; ray from the origin along +x: enters at t = 2.
        Assert.Equal(2, RayMath.RayBox(O, new Vec3(1, 0, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Direction (2, 0, 0): the same point at t = 1 (t is in units of d).
        Assert.Equal(1, RayMath.RayBox(O, new Vec3(2, 0, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Along −x: the box is behind → miss.
        Assert.Null(RayMath.RayBox(O, new Vec3(-1, 0, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Origin inside: 0.
        Assert.Equal(0, RayMath.RayBox(new Vec3(3, 0, 0), new Vec3(0, 1, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Parallel to the x slabs, outside them (y = 2 > 1): miss although x would cross.
        Assert.Null(RayMath.RayBox(new Vec3(0, 2, 0), new Vec3(1, 0, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Diagonal (1, 1, 0) from the origin: x enters at 2, y leaves at 1 → 2 > 1 → miss.
        Assert.Null(RayMath.RayBox(O, new Vec3(1, 1, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
        // Diagonal (1, 0.4, 0): x 2..4, y −2.5..2.5 → enters at 2 (y = 0.8 inside).
        Assert.Equal(2, RayMath.RayBox(O, new Vec3(1, 0.4, 0), new Vec3(2, -1, -1), new Vec3(4, 1, 1)));
    }

    [Fact]
    public void Spheres()
    {
        // Centre (5, 0, 0), r 1, ray along +x → meets it.
        Assert.True(RayMath.RaySphere(O, new Vec3(1, 0, 0), new Vec3(5, 0, 0), 1));
        // Passing at distance 1 exactly (tangent, offset y = 1): b² − a·c = 25 − 1·(25 + 1 − 1) = 0 → counts.
        Assert.True(RayMath.RaySphere(new Vec3(0, 1, 0), new Vec3(1, 0, 0), new Vec3(5, 0, 0), 1));
        // Offset y = 1.01 → 25 − (25 + 1.0201 − 1) = −0.0201 < 0 → miss.
        Assert.False(RayMath.RaySphere(new Vec3(0, 1.01, 0), new Vec3(1, 0, 0), new Vec3(5, 0, 0), 1));
        // Behind the origin → miss; origin inside → hit whatever the direction.
        Assert.False(RayMath.RaySphere(O, new Vec3(-1, 0, 0), new Vec3(5, 0, 0), 1));
        Assert.True(RayMath.RaySphere(new Vec3(5.5, 0, 0), new Vec3(-1, 0, 0), new Vec3(5, 0, 0), 1));
    }

    [Fact]
    public void Triangles()
    {
        // Triangle in the plane z = −5: (−1, −1), (1, −1), (0, 1). A ray from the origin along −z meets
        // (0, 0, −5) — inside (u, v ≥ 0) — at t = 5; with d = (0, 0, −2) at t = 2.5.
        var a = new Vec3(-1, -1, -5);
        var b = new Vec3(1, -1, -5);
        var c = new Vec3(0, 1, -5);
        Assert.Equal(5, RayMath.RayTriangle(O, new Vec3(0, 0, -1), a, b, c)!.Value, 12);
        Assert.Equal(2.5, RayMath.RayTriangle(O, new Vec3(0, 0, -2), a, b, c)!.Value, 12);
        // Both faces: reversing the winding does not change the hit.
        Assert.Equal(5, RayMath.RayTriangle(O, new Vec3(0, 0, -1), a, c, b)!.Value, 12);
        // Outside the edge: x = 0.9 at y = 0.5 is right of the edge (1,−1)→(0,1) (x there = 0.25) → miss.
        Assert.Null(RayMath.RayTriangle(new Vec3(0.9, 0.5, 0), new Vec3(0, 0, -1), a, b, c));
        // Behind: ray along +z → t = −5 → miss.
        Assert.Null(RayMath.RayTriangle(O, new Vec3(0, 0, 1), a, b, c));
        // In the plane of the triangle → miss.
        Assert.Null(RayMath.RayTriangle(new Vec3(-3, 0, -5), new Vec3(1, 0, 0), a, b, c));
    }

    [Fact]
    public void NearestOverAList()
    {
        // Two triangles of the shape above, at z = −5 (indices 0..2) and z = −3 (3..5): along −z the
        // nearer one at t = 3 wins.
        float[] xyz =
        {
            -1, -1, -5, 1, -1, -5, 0, 1, -5,
            -1, -1, -3, 1, -1, -3, 0, 1, -3,
        };
        int[] idx = { 0, 1, 2, 3, 4, 5 };
        Assert.Equal(3, RayMath.NearestTriangle(O, new Vec3(0, 0, -1), xyz, idx)!.Value, 6);
        // Shifted to x = 5: misses both.
        Assert.Null(RayMath.NearestTriangle(new Vec3(5, 0, 0), new Vec3(0, 0, -1), xyz, idx));
    }

    [Fact]
    public void AffineComposition()
    {
        // RotationY(π/2): +X → (cos, 0, −sin) = (0, 0, −1); +Z → (sin, 0, cos) = (1, 0, 0).
        var r = Affine.RotationY(Math.PI / 2);
        var p = r.Apply(1, 0, 0);
        Assert.Equal(0, p.X, 12);
        Assert.Equal(-1, p.Z, 12);
        // T(10, 0, 0) · R: the point (1, 0, 0) → R → (0, 0, −1) → T → (10, 0, −1).
        var tr = Affine.Translation(10, 0, 0).Times(r);
        var q = tr.Apply(1, 0, 0);
        Assert.Equal(10, q.X, 12);
        Assert.Equal(0, q.Y, 12);
        Assert.Equal(-1, q.Z, 12);
        // R · T(10, 0, 0): first T → (11, 0, 0), then R → (0, 0, −11).
        var rt = r.Times(Affine.Translation(10, 0, 0));
        var s = rt.Apply(1, 0, 0);
        Assert.Equal(0, s.X, 12);
        Assert.Equal(-11, s.Z, 12);
    }

    [Fact]
    public void SkinningBlendsTheBones()
    {
        // Bind 0 = identity, bind 1 = translation (0, 2, 0).
        // Vertex 0 (1, 0, 0), slots [0: 1.0, 1: 0]       → (1, 0, 0).
        // Vertex 1 (1, 0, 0), slots [0: 0.5, 1: 0.5]     → 0.5·(1,0,0) + 0.5·(1,2,0) = (1, 1, 0).
        // Vertex 2 (0, 0, 1), slots [1: 0.25, 0: 0.75]   → 0.25·(0,2,1) + 0.75·(0,0,1) = (0, 0.5, 1).
        // Vertex 3 (3, 3, 3), no weight at all           → (0, 0, 0) (the shader's sum is empty).
        float[] rest = { 1, 0, 0, 1, 0, 0, 0, 0, 1, 3, 3, 3 };
        int[] bones = { 0, 1, 0, 1, 1, 0, 0, 1 };
        float[] weights = { 1, 0, 0.5f, 0.5f, 0.25f, 0.75f, 0, 0 };
        var m = new[] { Affine.Identity, Affine.Translation(0, 2, 0) };
        var output = new float[12];
        Skinning.Apply(rest, bones, weights, 2, m, output);
        Assert.Equal(new float[] { 1, 0, 0, 1, 1, 0, 0, 0.5f, 1, 0, 0, 0 }, output);
    }
}

public class InfoFromWorldMapTests
{
    private const string Map = """
    {
      "avatar": "Pia",
      "locations": [
        { "id": "house", "name": "Harbour House", "description": "By the water", "pos_x": 10, "pos_z": 20,
          "rooms": [ { "id": "r1", "name": "Kitchen" }, { "id": "r2", "name": "Loft" } ] },
        { "id": "lake", "name": "Lake", "terrain": "water", "pos_x": 0, "pos_z": 0, "rooms": [ { "id": "z", "name": "Shore" } ] }
      ],
      "characters": [
        { "name": "Bram", "location_id": "house", "room_id": "r1", "activity": "cooking", "mood": "calm" },
        { "name": "Cleo", "location_id": "house", "movement_target_name": "Lake", "travel": { "eta_hhmm": "14:30" } },
        { "name": "Pia", "location_id": "lake", "pos": { "x": 4, "z": -1 } }
      ],
      "events_by_location": { "house": [ { "category": "danger", "text": "Fire!" }, { "category": "news", "text": "Party" } ] }
    }
    """;

    [Fact]
    public void GathersTheRowCharactersEventsRoomsAndAvatar()
    {
        using var doc = System.Text.Json.JsonDocument.Parse(Map);
        var info = InfoPanel.FromWorldMap(doc.RootElement, "house", new InfoView(true, false))!;
        // rooms: Kitchen ← Bram (room r1 matches the id), Loft ← nobody (Cleo's room is '' → matches neither).
        // present: Bram, Cleo (both location_id house) — Pia is at the lake. events: danger + news.
        // travel: the avatar Pia is at "lake" ≠ "house" → distance hypot(10 − 4, 20 − (−1)) = hypot(6, 21) = √477.
        // view as given.
        string want = "{\"id\":\"house\",\"name\":\"Harbour House\",\"description\":\"By the water\","
            + "\"rooms\":[{\"name\":\"Kitchen\",\"who\":[\"Bram\"]},{\"name\":\"Loft\",\"who\":[]}],"
            + "\"present\":[{\"name\":\"Bram\",\"activity\":\"cooking\",\"mood\":\"calm\",\"travelTo\":\"\",\"eta\":\"\"},"
            + "{\"name\":\"Cleo\",\"activity\":\"\",\"mood\":\"\",\"travelTo\":\"Lake\",\"eta\":\"14:30\"}],"
            + "\"events\":[{\"danger\":true,\"text\":\"Fire!\"},{\"danger\":false,\"text\":\"Party\"}],"
            + "\"travel\":{\"distanceM\":" + Math.Sqrt(477).ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "},"
            + "\"view\":{\"openable\":true,\"open\":false}}";
        Assert.Equal(want, info.ToJsonString());
    }

    [Fact]
    public void TheAvatarsOwnPlaceOffersNoTravelAndAreasListNoRooms()
    {
        using var doc = System.Text.Json.JsonDocument.Parse(Map);
        var info = InfoPanel.FromWorldMap(doc.RootElement, "lake", new InfoView(false, false))!;
        // terrain water → an area: no rooms; Pia is here → present [Pia]; same location → travel null.
        Assert.Empty(info["rooms"]!.AsArray());
        Assert.Single(info["present"]!.AsArray());
        Assert.Null(info["travel"]);
        Assert.Empty(info["events"]!.AsArray());
    }

    [Fact]
    public void AnUnknownIdLeavesThePanelAlone()
    {
        using var doc = System.Text.Json.JsonDocument.Parse(Map);
        Assert.Null(InfoPanel.FromWorldMap(doc.RootElement, "nowhere", new InfoView(false, false)));
    }
}
