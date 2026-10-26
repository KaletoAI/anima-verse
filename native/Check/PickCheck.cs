using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>, overview picking part (Task 9): rays cast at the fixture world, the fixture figures and the
/// S3c world, compared with values derived BY HAND here from native/fixtures/README.md (positions, datums,
/// sizes) — not recorded from a run.
///
/// Main fixtures (README "Terrain", "Yard scene", "Figures"):
///   A1 house roof: the house group stands at (64, 4, 128), yaw 0; its building box is centred on local
///      (1.5, −2) → world (65.5, 126) with the underside at 4 − 0.25 = 3.75. A ray straight down from
///      y 100 there hits loc-house, at a y above 3.75 and not above the box top.
///   A2 yard plate: the yard (−100, 2.91357421875, 50), yaw +30°; its far shell copies the level-1 plate
///      (top_y 3, 8 × 6, hole x 1…3 z −1…0). Local (−2, 1) → world (−100 + (−2·cos30 + 1·sin30), 50 + (2·sin30 + 1·cos30))
///      = (−101.2320508, 51.8660254), outside the hole. Down from y 50: loc-yard at 50 − (2.91357421875 + 3)
///      = 44.08642578125 m.
///   A3 empty ground (0, −300): nothing. A4 the meadow (300, −200) has no scene (404) → not built → nothing.
///   B1 Ada (GLB, 1.60 m, feet (−50, 3.595947265625, 30)): a ray along +x at y + 1.0 from x −60 hits her
///      body; a 1.60 m figure is between 0.05 and 0.35 m wide on either side of its axis at 1.0 m (waist with
///      the arms hanging) → distance in [9.65, 9.95].
///   B2 the same ray 1 m to the side (z 31) and B3 0.15 m above her 1.60 m (y + 1.75): no figure.
///   B7 0.3 m beside Ada's axis at 1.2 m: nothing in her idle pose, her bind pose (T-pose) has the arm there.
///   B4 Cleo's PORTRAIT (no model, no pool in this fixture — Task 29; feet (263, 4.875, −100), sprite 2.6 m from
///      0.15 − 0.052 to 0.15 + 2.548 over the feet): along +z at 0.85 m from z −110 → the quad through the axis facing the
///      ray, z −100 → 10 m.
///   B5 Bram, the fixture animal (fixtures/animals/animal_takes.fbx, 0.5 m in the file, scaled 3.6 to his 1.80 m, feet
///      (64, 4.0675, 132.32), yaw 0) from straight above (y 50): the body's flat top at 4.0675 + 1.8 = 5.8675 → 44.1325 m.
///   B6 a ray along −z through his body (y + 1.5; the body box spans 0.3…0.5 of the file's height = 1.08…1.80 m, the
///      file's z −0.25…0.35 after the bind centring): Bram at 150 − (132.32 + 0.35 · 3.6) = 16.42 m, in front of the
///      house (the house box ends at z ≤ 132); the chain gives the figure and keeps the panel.
///   C  the camera's own ray: target (−50, ya + 1.0, 30) at 6 m → the centre pixel hits Ada at ≤ 6 m; 300 px to
///      the right is 300 · 6 · 2·tan(22.5°)/900 = 1.657 m off the axis → nothing.
///   E  the info panel of loc-house: Bram is there (room room-hall), no rooms in the row, no events, no avatar
///      (no travel), openable (building with an interior: its plate and wall), not open.
///   F  event pins (eventPins.ts <c>pinY</c> = ground datum + place height + 3.5, since 99c16a69): house 🔥 at
///      4 + its building height + 3.5, yard ❗ at 2.91357421875 + its shell height 3 (walls 0…3, plate top 3) + 3.5
///      = 9.41357421875, meadow ❗ unbuilt → the ground under its pin (300, −200): overview, x clamped to the last
///      cell (i 1, tx 1), fz = 56/256 = 0.21875 → 0·(1 − 0.21875) + 8·0.21875 = 1.75, plus the reading height 4 +
///      3.5 = 9.25; an unknown id none. Bob 0.5 s: sin(1.1) · 0.008 = 0.00712965888. Second poll: house only
///      "news" → its glyph changed → REBUILT as ❗ (a new node); yard gone; meadow unchanged → the SAME node, placed
///      again at 9.25 (the bob's offset is gone).
///
/// S3c world (README "S3c world"):
///   G  loc-closed (−40, 100), datum 4.693359375 (overview, README), yaw 0, square ±4: openable, mounted ONCE
///      (Task 15) with its shell building AND its interior, held at fade 0 (the shelf's URL is asked at the mount).
///      A ray straight down at local (0, −2) — the lift pad (centre y 0.05, height 0.1) — first hits the building.
///      Opened ("Look inside"): only the fade target moves (same group, no scene request); the crossfade numbers
///      (fade, roof transparency, shadow, hidden at 0.95, occlusion, close) are derived where they are checked.
///      After 0.75 s the same ray hits the pad top at 50 − (4.693359375 + 0.1) = 45.206640625 m. loc-open stays
///      closed (fade 0: hull whole with its cutouts off, interior hidden, the bench outside). Auto-close against
///      loc-closed (width 8 → limit max(12, 24) = 24): target 24 m off → stays, 24.5 m → closes; camera 60.5 m → closes.
/// </summary>
public static class PickCheck
{
    private const float AdaY = 3.595947265625f, BramY = 4.0675f, CleoY = 4.875f;
    private const double YardDatum = 2.91357421875, ClosedDatum = 4.693359375;

    public static async Task<string> RunAsync(Node3D host, Node3D world, WorldBuilder builder, string fixtures)
    {
        var picking = new LocationPicking(builder);
        static Vec3 V(double x, double y, double z) => new(x, y, z);
        var down = V(0, -1, 0);

        // ---- A: locations ----
        var house = world.GetNode<Node3D>("Locations/Loc_loc-house");
        var placed = house.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString().StartsWith("Placed_building"));
        var houseBox = ModelPlacement.Measure(placed, house.Transform);
        Near("house box underside", houseBox.Position.Y, 3.75, 1e-3);
        var a1 = picking.Pick(V(65.5, 100, 126), down);
        Expect("A1 house roof", a1?.Id == "loc-house", $"{a1}");
        double roofY = 100 - a1!.Value.Distance;
        Expect("A1 hit on the building", roofY > 3.75 && roofY <= houseBox.End.Y + 1e-3, $"y {roofY}, box top {houseBox.End.Y}");
        var a1Stats = $"{picking.LastBoxTests} boxes/{picking.LastTriangleQueries} meshes {picking.LastMs:0.###} ms";
        double c30 = Math.Cos(Math.PI / 6), s30 = Math.Sin(Math.PI / 6);
        var a2 = picking.Pick(V(-100 + (-2 * c30 + 1 * s30), 50, 50 + (2 * s30 + 1 * c30)), down);
        Expect("A2 yard plate", a2?.Id == "loc-yard", $"{a2}");
        Near("A2 distance", a2!.Value.Distance, 50 - (YardDatum + 3), 2e-3);
        Expect("A3 empty ground", picking.Pick(V(0, 50, -300), down) is null, "hit");
        Expect("A4 meadow without a scene", picking.Pick(V(300, 50, -200), down) is null, "hit");
        var census = picking.Census();

        // ---- B: figures (own manager, own source: fresh counters) ----
        var source = new FixtureSource(fixtures);
        var mgr = new FigureManager(source, builder.Height!, line => GD.Print("[check-pick] " + line), strict: true) { ClipFit = ClipFitMode.OnDemandSync, AutoTick = false, Slots = () => builder.Slots };
        world.AddChild(mgr);
        string figureInfo;
        try
        {
            await mgr.InitAsync();
            using (var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "worldmap.json"))))
                await mgr.Apply(map.RootElement);
            var ada = mgr.Figures["Ada Wren"];
            ada.Player!.Play(ada.CurrentClip, 0);   // the standing pose's clip (stand-relaxed)
            ada.Player.Seek(0, true);
            NearV("Ada feet", ada.GlobalPosition, new Vector3(-50, AdaY, 30));

            var b1 = mgr.CharacterAt(V(-60, AdaY + 1.0, 30), V(1, 0, 0));
            Expect("B1 Ada", b1?.Name == "Ada Wren", $"{b1}");
            Expect("B1 distance", b1!.Value.Distance is >= 9.65 and <= 9.95, $"{b1.Value.Distance}");
            figureInfo = $"ada skinned {mgr.LastPickSkinnedVertices} vertices {mgr.LastPickMs:0.###} ms ({mgr.LastPickCandidates} near)";
            // B7 the pose counts: 0.3 m beside her axis at 1.2 m (upper-arm height) the idle pose has nothing — the
            // arms hang along a body ≤ 0.25 m wide there — while her bind pose (the GLB's T-pose, arms out) has
            // the arm there. So the pick must skin; a pick against the stored mesh would answer Ada.
            var b7o = new Vector3(-49.7f, AdaY + 1.2f, 20);
            Expect("B7 idle pose: nothing", mgr.CharacterAt(V(b7o.X, b7o.Y, b7o.Z), V(0, 0, 1)) is null, "hit");
            Expect("B7 bind pose would hit", ada.Body!.FindChildren("*", "MeshInstance3D", true, false).OfType<MeshInstance3D>()
                       .Any(mi => MeshRay.Static(mi, b7o, new Vector3(0, 0, 1)) is not null), "the case does not discriminate");
            mgr.CharacterAt(V(-60, AdaY + 1.0, 30), V(1, 0, 0));
            figureInfo += $", again {mgr.LastPickMs:0.###} ms";
            Expect("B2 beside Ada", mgr.CharacterAt(V(-60, AdaY + 1.0, 31), V(1, 0, 0)) is null, "hit");
            Expect("B3 above Ada", mgr.CharacterAt(V(-60, AdaY + 1.75, 30), V(1, 0, 0)) is null, "hit");
            var b4 = mgr.CharacterAt(V(263, CleoY + 0.85, -110), V(0, 0, 1));
            Expect("B4 Cleo", b4?.Name == "Cleo Marsh", $"{b4}");
            Near("B4 distance", b4!.Value.Distance, 10, 1e-3);
            var b5 = mgr.CharacterAt(V(64, 50, 132.32), down);
            Expect("B5 Bram", b5?.Name == "Bram Holt", $"{b5}");
            Near("B5 distance", b5!.Value.Distance, 50 - (BramY + 1.8), 1e-3);
            var b6o = V(64, BramY + 1.5, 150);
            var b6 = mgr.CharacterAt(b6o, V(0, 0, -1));
            Expect("B6 Bram", b6?.Name == "Bram Holt", $"{b6}");
            Near("B6 distance", b6!.Value.Distance, 150 - (132.32 + 0.35 * 3.6), 1e-3);
            var b6loc = picking.Pick(b6o, V(0, 0, -1));
            Expect("B6 the house behind him", b6loc is null || (b6loc.Value.Id == "loc-house" && b6loc.Value.Distance > b6.Value.Distance),
                   $"{b6loc}");

            // ---- D: the chain ----
            Expect("D figure first", PickChain.Resolve(b6.Value.Name, b6loc?.Id) == new PickOutcome("Bram Holt", InfoChange.Unchanged, null), "");
            Expect("D location", PickChain.Resolve(null, a1.Value.Id) == new PickOutcome(null, InfoChange.Show, "loc-house"), "");
            Expect("D nothing", PickChain.Resolve(null, null) == new PickOutcome(null, InfoChange.Clear, null), "");

            // ---- C: through the camera's own ray ----
            CheckCamera(host, mgr);
        }
        finally
        {
            mgr.QueueFree();
        }

        // ---- E: the info panel ----
        var slotHouse = builder.Slots["loc-house"];
        Expect("E house openable", slotHouse.Openable && !slotHouse.Open, $"{slotHouse.Openable}/{slotHouse.Open}");
        var info = InfoPanel.FromWorldMap(builder.FirstMap!.Value, "loc-house", new InfoView(slotHouse.Openable, false))!;
        const string WantInfo = "{\"id\":\"loc-house\",\"name\":\"Harbour House\",\"description\":\"\",\"rooms\":[],"
            + "\"present\":[{\"name\":\"Bram Holt\",\"activity\":\"\",\"mood\":\"\",\"travelTo\":\"\",\"eta\":\"\"}],"
            + "\"events\":[],\"travel\":null,\"view\":{\"openable\":true,\"open\":false}}";
        Expect("E info panel", info.ToJsonString() == WantInfo, info.ToJsonString());

        // ---- F: event pins ----
        var pinInfo = CheckPins(world, builder, slotHouse, houseBox.Size.Y);

        // ---- G: look inside, close, auto-close (S3c world) ----
        var open = await CheckOpenView(host, fixtures);

        var stress = Stress();
        return $"pick A1..G ok (A1 {a1Stats}; location meshes {census.Meshes}, triangles {census.Triangles}; {figureInfo}; "
               + $"{pinInfo}; {open}; {stress})";
    }

    private static void CheckCamera(Node3D host, FigureManager mgr)
    {
        var vp = new SubViewport { Name = "PickCheckViewport", Size = new Vector2I(1600, 900) };
        host.AddChild(vp);
        var cam = new OverviewCamera { Name = "PickCheckCamera" };
        vp.AddChild(cam);
        try
        {
            cam.Current = true;
            cam.SetProcess(false);
            cam.JumpTo(new Vector3(-50, AdaY + 1.0f, 30), 6);
            cam.Step(0);
            var (o, d) = cam.RayAt(new Vector2(800, 450));
            var hit = mgr.CharacterAt(o, d);
            Expect("C centre pixel → Ada", hit?.Name == "Ada Wren" && hit.Value.Distance <= 6, $"{hit}");
            var (o2, d2) = cam.RayAt(new Vector2(1100, 450));
            Expect("C 300 px right → nothing", mgr.CharacterAt(o2, d2) is null, "hit");
        }
        finally
        {
            vp.QueueFree();
        }
    }

    /// <summary>The place answer of Main.PlaceOf for the check's builder: the built group, else the row on the ground.</summary>
    internal static (double X, double GroundY, double Z, double Height)? PlaceOfFor(WorldBuilder builder,
                                                                                 IReadOnlyDictionary<string, LocationInfo> rows, string id)
    {
        if (builder.Slots.TryGetValue(id, out var s)) return (s.Group.Position.X, s.Group.Position.Y, s.Group.Position.Z, s.Height);
        if (!rows.TryGetValue(id, out var row) || !row.IsPlaced) return null;
        var (b, n) = LocationView.Kind(row);
        return (row.PosX!.Value, builder.Height!.GroundAt(row.PosX.Value, row.PosZ!.Value), row.PosZ.Value,
                EventPinRule.DefaultPlaceHeight(b, n, LocationView.DetectStyle(row)));
    }

    private static string CheckPins(Node3D world, WorldBuilder builder, LocationSlot house, float houseHeight)
    {
        Near("F house height = its building", house.Height, houseHeight, 1e-4);
        Expect("F house height measured", house.HeightMeasured, "default");
        var yard = builder.Slots["loc-yard"];
        Near("F yard height = its shell", yard.Height, 3.0, 1e-4);
        var rows = LocationInfo.ParseList(builder.FirstMap!.Value).ToDictionary(l => l.Id);
        (double X, double GroundY, double Z, double Height)? PlaceOf(string id) => PlaceOfFor(builder, rows, id);
        var pins = new EventPins();
        world.AddChild(pins);
        try
        {
            using (var poll1 = JsonDocument.Parse("""
                { "events_by_location": {
                    "loc-house": [ { "category": "news" }, { "category": "danger" } ],
                    "loc-yard": [ { "category": "news" } ],
                    "loc-meadow": [ { "text": "no category" } ],
                    "loc-template": [ { "category": "danger" } ],
                    "ghost": [ { "category": "danger" } ] } }
                """))
                pins.Update(poll1.RootElement, PlaceOf);
            // loc-template has no position (not a placed place) and ghost is unknown: no pins.
            Expect("F pins", pins.Pins.Keys.OrderBy(k => k).SequenceEqual(new[] { "loc-house", "loc-meadow", "loc-yard" }),
                   string.Join(",", pins.Pins.Keys));
            string Glyph(string id) => pins.Pins[id].GetMeta("glyph").AsString();
            Expect("F glyphs", Glyph("loc-house") == "🔥" && Glyph("loc-yard") == "❗" && Glyph("loc-meadow") == "❗",
                   $"{Glyph("loc-house")}{Glyph("loc-yard")}{Glyph("loc-meadow")}");
            NearV("F house pin", pins.Pins["loc-house"].Position, new Vector3(64, 4 + houseHeight + 3.5f, 128));
            NearV("F yard pin", pins.Pins["loc-yard"].Position, new Vector3(-100, (float)(YardDatum + 3 + 3.5), 50));
            NearV("F meadow pin", pins.Pins["loc-meadow"].Position, new Vector3(300, 9.25f, -200));
            var pin = pins.Pins["loc-house"];
            if (pin is Label3D label)
                Expect("F glyph label", label.NoDepthTest && label.Billboard == BaseMaterial3D.BillboardModeEnum.Enabled
                       && label.FontSize == 72 && Math.Abs(label.PixelSize - 3f / 96f) < 1e-7 && label.Text == "🔥", "");
            else if (pin is Sprite3D sprite)
                Expect("F glyph sprite", sprite.NoDepthTest && sprite.Texture.GetWidth() == 96 && Math.Abs(sprite.PixelSize - 3f / 96f) < 1e-7, "");
            else Expect("F pin kind", false, pin.GetType().Name);
            float y0 = pins.Pins["loc-yard"].Position.Y;
            pins.Bob(0.5);
            Near("F bob", pins.Pins["loc-yard"].Position.Y - y0, 0.00712965888049148, 1e-6);
            var house1 = pins.Pins["loc-house"];
            var meadow1 = pins.Pins["loc-meadow"];

            using (var poll2 = JsonDocument.Parse("""
                { "events_by_location": { "loc-house": [ { "category": "news" } ], "loc-meadow": [ { "category": "news" } ] } }
                """))
                pins.Update(poll2.RootElement, PlaceOf);
            Expect("F poll 2 pins", pins.Pins.Keys.OrderBy(k => k).SequenceEqual(new[] { "loc-house", "loc-meadow" }),
                   string.Join(",", pins.Pins.Keys));
            Expect("F poll 2 house rebuilt as ❗", Glyph("loc-house") == "❗" && !ReferenceEquals(pins.Pins["loc-house"], house1),
                   Glyph("loc-house"));
            Expect("F poll 2 meadow kept", ReferenceEquals(pins.Pins["loc-meadow"], meadow1), "a new node");
            NearV("F poll 2 meadow placed again", pins.Pins["loc-meadow"].Position, new Vector3(300, 9.25f, -200), 1e-5f);
            Expect("F old house pin out of the tree", house1.GetParent() is null, "still a child");

            // The drawn look-alike (used when the system has no colour emoji font): hand-placed sample pixels.
            var fire = EventPins.FallbackImage("🔥");
            var bang = EventPins.FallbackImage("❗");
            Expect("F fallback size", fire.GetWidth() == 96 && fire.GetHeight() == 96, "");
            Expect("F fallback corner clear", fire.GetPixel(0, 0).A == 0 && bang.GetPixel(0, 0).A == 0, "");
            // Flame: glyph (0, −14) → canvas (48, 68) inside the inner drop → yellow; glyph (20, −14) → (68, 68) orange.
            var core = fire.GetPixel(48, 68);
            var rim = fire.GetPixel(68, 68);
            Expect("F flame core yellow", core.A > 0.99f && core.R > 0.95f && core.G > 0.7f && core.B < 0.3f, $"{core}");
            Expect("F flame rim orange", rim.A > 0.99f && rim.R > 0.9f && rim.G is > 0.25f and < 0.45f, $"{rim}");
            // Bang: dot at glyph (0, −24) → (48, 78); bar at glyph (0, 10) → (48, 44); gap at glyph (0, −12) → (48, 66).
            Expect("F bang dot/bar/gap", bang.GetPixel(48, 78).A > 0.99f && bang.GetPixel(48, 44).A > 0.99f && bang.GetPixel(48, 66).A == 0,
                   $"{bang.GetPixel(48, 78)} {bang.GetPixel(48, 44)} {bang.GetPixel(48, 66)}");
            if (pin is Label3D lab)
            {
                // A bitmap colour font (Noto's CBDT strikes are 109 px) must follow the requested size, else the pin
                // is drawn at the strike size: half the size → half the width.
                var w72 = lab.Font.GetStringSize("🔥", HorizontalAlignment.Left, -1, 72).X;
                var w36 = lab.Font.GetStringSize("🔥", HorizontalAlignment.Left, -1, 36).X;
                Expect("F emoji follows the font size", w72 > 0 && Math.Abs(w36 * 2 - w72) <= 2, $"{w72} / {w36}");
            }
            return $"pins glyphs from {EventPins.GlyphSource}, pin kind {pin.GetType().Name}";
        }
        finally
        {
            pins.QueueFree();
        }
    }

    private static async Task<string> CheckOpenView(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "s3c");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "PickS3cWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-pick-s3c] " + line), strict: true);
        try
        {
            var stats = await builder.BuildAsync(world, "Glass");
            var picking = new LocationPicking(builder);
            var view = new OpenView();
            Expect("G boot open", stats.OpenLocation == "loc-open" && view.TryOpen(stats.OpenLocation, true, out _), stats.OpenLocation);
            var closed = builder.Slots["loc-closed"];
            var openSlot = builder.Slots["loc-open"];
            Expect("G loc-closed openable, closed", closed.Openable && !closed.Open, "");
            Near("G loc-closed datum", closed.Group.Position.Y, ClosedDatum, 1e-4);
            Near("G loc-far shell height", builder.Slots["loc-far"].Height, 3.0, 1e-4);
            // Mounted once: the building AND the interior (pad, wall, the well outside; the shelf asked for and missing).
            var building = closed.Group.GetNode<Node3D>("Placed_building_loc-closed");
            var interior = closed.Group.GetNode<Node3D>("Interior");
            Expect("G mounted once", building.Visible && !interior.Visible && closed.Fade.Fade == 0
                   && interior.GetChildren().OfType<MeshInstance3D>().Any() && HasChild(closed.Group, "Placed_prop_well"),
                   string.Join(",", closed.Group.GetChildren().Select(c => c.Name.ToString())));
            Expect("G shelf asked at the mount", source.ByteRequests.Contains("/assets/props/shelf/model?tier=full"), "");
            var ray = new Vec3(-40, 50, 98);
            var before = picking.Pick(ray, new Vec3(0, -1, 0));
            Expect("G before: the building", before is { Id: "loc-closed" } b0 && b0.Distance < 50 - (ClosedDatum + 0.1) - 0.5, $"{before}");

            // "Look inside": the singleton moves, both targets flip — nothing is rebuilt or fetched.
            var groupBefore = closed.Group;
            int scenesBefore = source.SceneRequests.Count;
            Expect("G open loc-closed", view.TryOpen("loc-closed", closed.Openable, out var wasOpen) && wasOpen == "loc-open", wasOpen ?? "null");
            Expect("G targets", builder.SetOpen("loc-open", false) && builder.SetOpen("loc-closed", true) && closed.Open && !openSlot.Open, "");
            var far = new Vector3(-40, 30, 140);   // a camera no neighbour stands in front of (see the occlusion below)
            Tick(builder, far, 6);
            // f = 1 − e^(−0.4) = 0.32967995: interior up, the roof at 1 − 1.4·f → transparency 0.46155194, still casting.
            Near("G fade 0.1 s", closed.Fade.Fade, 0.32967995396436056, 1e-9);
            var roofMesh = closed.Fade.RoofMeshes.First();
            Expect("G 0.1 s: interior up, roof fading", interior.Visible && building.Visible
                   && roofMesh.CastShadow == GeometryInstance3D.ShadowCastingSetting.On, "");
            Near("G roof transparency 0.1 s", roofMesh.Transparency, 0.46155193555010476, 1e-6);
            Tick(builder, far, 39);
            // 45 frames = 0.75 s: f = 1 − e^(−3) = 0.950213 ≥ 0.95 → the roof is hidden, the shell casts no shadow.
            Near("G fade 0.75 s", closed.Fade.Fade, 0.950212931632136, 1e-9);
            Expect("G 0.75 s: roof hidden", !building.Visible && roofMesh.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");
            Expect("G no rebuild", ReferenceEquals(closed.Group, groupBefore) && source.SceneRequests.Count == scenesBefore, "");
            var after = picking.Pick(ray, new Vec3(0, -1, 0));
            Expect("G after: the lift pad", after?.Id == "loc-closed", $"{after}");
            Near("G pad distance", after!.Value.Distance, 50 - (ClosedDatum + 0.1), 2e-3);
            Expect("G loc-open stays closed", openSlot.Fade.Fade == 0 && openSlot.Group.GetNode<Node3D>("Placed_building_loc-open").Visible
                   && openSlot.Fade.Cutouts.All(h => !h.CutoutsOn)
                   && !openSlot.Group.GetNode<Node3D>("Interior").Visible
                   // the always-visible garden's group hangs off the tile, its bench in it (Task 16 room groups)
                   && openSlot.Group.GetNodeOrNull<Node3D>("Room_r-garden/Placed_prop_bench") is { } bench && bench.IsVisibleInTree(), "");

            // Neighbour occlusion: camera C (168, ·, 140), target the open centre (−40, 100) → d = (−208, −40);
            // loc-open's centre (64, 120) − C = (−104, −20) = d/2 → t = 0.5 ∈ (0.05, 0.92), off the line by 0 <
            // width · 1.05, and it is taller than 1.5 m → it fades: occl = 1 − e^(−8·n/60). loc-far (600, 128):
            // (432, −12)·d < 0 → t < 0 → stays.
            Expect("G loc-open tall", openSlot.Height > 1.5, $"{openSlot.Height}");
            var behind = new Vector3(168, 30, 140);
            Tick(builder, behind, 6);
            Near("G occlusion 0.1 s", openSlot.Fade.Occl, 0.5506710358827784, 1e-9);
            var hullMesh = openSlot.Fade.Meshes.First(m => openSlot.Group.GetNode<Node3D>("Placed_building_loc-open").IsAncestorOf(m));
            Near("G occluded transparency", hullMesh.Transparency, 0.5506710358827784, 1e-6);
            Expect("G occluded still shown", openSlot.Group.Visible && builder.Slots["loc-far"].Fade.Occl == 0, "");
            Tick(builder, behind, 54);
            Expect("G occluded hidden", !openSlot.Group.Visible && openSlot.Fade.Occl >= 0.95, $"{openSlot.Fade.Occl}");
            Tick(builder, far, 60);   // camera back: 0.99966·e^(−8t) falls under 0.02 within 0.49 s → snapped to 0
            Expect("G occlusion released", openSlot.Group.Visible && openSlot.Fade.Occl == 0 && hullMesh.Transparency == 0, $"{openSlot.Fade.Occl}");

            // The overview auto-close against loc-closed: centre (−40, 100), width 8 → 24 m.
            var cx = closed.Group.Position.X;
            var cz = closed.Group.Position.Z;
            Near("G width", closed.Width, 8, 1e-9);
            Expect("G 24 m off stays", !OpenView.ShouldClose(15, -40, 124, cx, cz, closed.Width), "");
            Expect("G 24.5 m off closes", OpenView.ShouldClose(15, -40, 124.5, cx, cz, closed.Width), "");
            Expect("G camera 60.5 m closes", OpenView.ShouldClose(60.5, -40, 100, cx, cz, closed.Width), "");

            // Close: 165 frames open (f = 1 − e^(−11)), then 60 closed → f·e^(−4) = 0.0183153: interior hidden (≤ 0.03),
            // the roof back but still at transparency 1.4·f = 0.0256415; 60 more → 0.000335: alpha 0.99953 ≥ 0.999 →
            // transparency 0, the roof is in the opaque pass again.
            Expect("G close", view.Close() == "loc-closed" && builder.SetOpen("loc-closed", false) && !closed.Open, "");
            Tick(builder, far, 60);
            Near("G fade closing", closed.Fade.Fade, 0.018315332986413725, 1e-9);
            Expect("G closing: interior hidden, roof back", !interior.Visible && building.Visible, "");
            Near("G closing roof transparency", roofMesh.Transparency, 0.025641466180979212, 1e-6);
            Tick(builder, far, 60);
            Expect("G closed: roof opaque", roofMesh.Transparency == 0 && roofMesh.CastShadow == GeometryInstance3D.ShadowCastingSetting.On,
                   $"{roofMesh.Transparency}");
            var again = picking.Pick(ray, new Vec3(0, -1, 0));
            Expect("G closed again: the building", again is { Id: "loc-closed" } b2 && b2.Distance < 50 - (ClosedDatum + 0.1) - 0.5, $"{again}");
            return $"look inside {before!.Value.Distance:0.###} → {after.Value.Distance:0.###} m, crossfade 0.75 s, occlusion 1 s";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    /// <summary>The frame hook's view pass, <paramref name="frames"/> frames at 60 fps from <paramref name="camera"/>.</summary>
    private static void Tick(WorldBuilder builder, Vector3 camera, int frames)
    {
        for (int i = 0; i < frames; i++) builder.TickView(1 / 60.0, camera);
    }

    /// <summary>
    /// The numbers behind the technique choice (information only): one 65 024-triangle mesh, three ways —
    /// Godot's TriangleMesh (BVH build once, then per query), the brute-force C# loop three.js runs, and a
    /// physics trimesh shape (what a <c>PhysicsRayQueryParameters3D</c> pick would need on every mesh up front).
    /// </summary>
    private static string Stress()
    {
        var sphere = new SphereMesh { Radius = 5, Height = 10, RadialSegments = 256, Rings = 128 };
        var arrays = sphere.GetMeshArrays();
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var idx = arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
        int tris = idx.Length / 3;
        var sw = Stopwatch.StartNew();
        var tm = mesh.GenerateTriangleMesh();
        double build = sw.Elapsed.TotalMilliseconds;
        sw.Restart();
        const int Q = 200;
        for (int i = 0; i < Q; i++) tm.IntersectRay(new Vector3(i * 0.01f, 0, 20), new Vector3(0, 0, -1));
        double query = sw.Elapsed.TotalMilliseconds / Q;
        var xyz = new float[verts.Length * 3];
        for (int v = 0; v < verts.Length; v++) { xyz[v * 3] = verts[v].X; xyz[v * 3 + 1] = verts[v].Y; xyz[v * 3 + 2] = verts[v].Z; }
        sw.Restart();
        double? t = null;
        for (int i = 0; i < 20; i++) t = RayMath.NearestTriangle(new Vec3(i * 0.01, 0, 20), new Vec3(0, 0, -1), xyz, idx);
        double brute = sw.Elapsed.TotalMilliseconds / 20;
        Expect("stress hit", t is double tt && Math.Abs(tt - 15) < 0.01, $"{t}");
        sw.Restart();
        var shape = mesh.CreateTrimeshShape();
        double trimesh = sw.Elapsed.TotalMilliseconds;
        shape?.Dispose();
        return $"technique {tris} triangles: TriangleMesh build {build:0.#} ms + {query * 1000:0.#} µs/ray, "
               + $"brute force {brute:0.##} ms/ray, trimesh shape {trimesh:0.#} ms";
    }

    private static bool HasChild(Node n, string name) => n.GetChildren().Any(c => c.Name.ToString() == name);

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"pick {what}: {detail}");
    }

    private static void Near(string what, double got, double want, double eps)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got}, expected {want}");

    private static void NearV(string what, Vector3 got, Vector3 want, float eps = 1e-3f)
        => Expect(what, got.DistanceTo(want) <= eps, $"got {got}, expected {want}");
}
