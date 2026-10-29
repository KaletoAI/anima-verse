using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.World;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>: the offline self-test. Runs the online code paths against
/// <c>native/fixtures/</c> and compares every count with the number derived BY
/// HAND in <c>native/fixtures/README.md</c> (not with a recording of current
/// output). Prints one <c>CHECK ok …</c> line and returns 0, or prints
/// <c>CHECK FAILED …</c> and returns 1.
/// </summary>
public static class CheckRunner
{
    // ---- Expected values, derived in native/fixtures/README.md ----
    private const string Goto = "harbour";                         // → loc-house by name substring
    private static readonly Vector3 ExpectedAnchor = new(64f, 7.5f, 128f);
    // Task 23: the CDLOD terrain's first frame at the bench start camera (64, 31.5, 168) — README "CDLOD terrain".
    private const int ExpTiles = 1, ExpTerrainPieces = 41, ExpTerrainTriangles = 64000;
    private const int ExpLocations = 3, ExpScenes = 2;
    private const int ExpBuildings = 1, ExpBuildingsMeshopt = 1;
    private const int ExpBuildingVertices = 2220, ExpBuildingIndices = 3330;
    // S3c: the yard (no model, closed) shows its FAR SHELL — 1 level plate + 6 non-glass walls (leaves included);
    // skipped: 3 degenerate (2-point plate, zero-length wall, empty shaft) + 5 interior (house plate + wall, yard
    // glass + 2 stair boxes) — README "Recipe primitives".
    private const int ExpPrimitives = 7, ExpSkipped = 8, ExpShellCopies = 7, ExpDegenerate = 3, ExpInterior = 5;
    // Task 15/16: every location mounts its interior once (hidden at fade 0), EVERY storey — house wall + its level-1
    // slab = 2, yard 6 walls + 2 stair boxes + its level-1 slab = 9 (README "Yard scene").
    private const int ExpInteriorMounted = 11;
    private const float ExpHouseDatum = 4f, ExpYardDatum = 2.91357421875f;
    private const float ExpPlateArea = 46f;                        // 8 × 6 minus the 2 × 1 hole
    private const float ExpBuildingMaxM = 12f, ExpBuildingBottom = -0.25f;
    private static readonly Vector2 ExpBuildingAnchor = new(1.5f, -2f);

    // ---- S1b figures (worldmap.json / worldmap_poll2.json, README "Figures") ----
    private const int ExpFigures = 3, ExpGlbFigures = 2, ExpPlaceholders = 1, ExpClipsLoaded = 5, ExpClipsFailed = 4;
    private const int ExpTracksPerClip = 53;                       // 52 rotations + the hips position
    private const int ExpBoundTracks = 4 * ExpTracksPerClip;        // Stand-Relaxed, walk, waiting (female), reading on Ada
    private static readonly string[] ExpIndexKinds = { "Stand-Relaxed", "walk", "waiting", "reading" };
    private static readonly string[] ExpActions = { "stand-relaxed", "walk", "waiting", "reading", "idle" };
    // Bram's FBX (fixtures/animals/animal_takes.fbx): its own three takes, no library (rig generic) — README "Figures".
    private static readonly string[] ExpBramActions = { "idle", "sit", "walk" };
    private const string Ada = "Ada Wren", Bram = "Bram Holt", Cleo = "Cleo Marsh";
    private static readonly Vector3 ExpAda = new(-50f, 3.595947265625f, 30f);     // free, overview
    private static readonly Vector3 ExpBram = new(64f, 4.0675f, 132.32f);         // house huddle, fine tile
    private static readonly Vector3 ExpCleo = new(263f, 4.875f, -100f);           // journey, overview
    private const float ExpAdaHeight = 1.60f, ExpBramHeight = 1.80f;
    // Poll 2 walked in 0.5 s frames (README "Second poll"): Ada runs 3.06 m twice, then walks 1.7 m twice and 0.48 m.
    private static readonly Vector3 ExpAdaRun1 = new(-46.94f, 3.7705078125f, 30f);
    private static readonly Vector3 ExpAdaWalk1 = new(-42.18f, 3.7705078125f, 30f);
    // Task 42: receipt age .49; shown 144.686+.7=145.386 gives goal x254.614.
    // Root catches up 1.7 m to x261.3, but Y samples that reached arc point: 4.875*(254.614+256)/512.
    private static readonly Vector3 ExpCleoStep1 = new(261.3f, 4.86180322265625f, -100f);
    private static readonly Vector3 ExpAdaEnd = new(-40f, 3.7705078125f, 30f);
    // movement_poses (README "Clips"): standing plays stand-relaxed (exact), walking names mob1-walk,
    // which the library lacks → its public kind walk.
    private const string ExpStandingKind = "stand-relaxed", ExpMovingWant = "mob1-walk", ExpMovingKind = "walk";
    private const string AdaUrl = "/characters/Ada%20Wren/model3d/file?v=fixtureada000001";
    private const string AdaLowUrl = "/characters/Ada%20Wren/model3d/file?tier=low&v=fixtureadalow01";

    public static async Task<int> RunAsync(Node3D host, string? only = null, string? cacheDir = null)
    {
        try
        {
            var dir = Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures");
            MeshoptNative.EnsureLoaded(ProjectSettings.GlobalizePath("res://bin"));
            if (only == "update")
            {
                GD.Print($"CHECK ok {await UpdateCheck.RunAsync(host)}");
                return 0;
            }
            if (only == "cache")
            {
                GD.Print($"CHECK ok {await CacheCheck.RunAsync(host, dir, cacheDir)}");
                return 0;
            }
            if (only == "audio")
            {
                GD.Print($"CHECK ok {await AudioCheck.RunAsync(host, dir)}");
                return 0;
            }
            if (only == "propactions")
            {
                GD.Print($"CHECK ok {await PropActionsCheck.RunAsync(host, dir)}");
                return 0;
            }
            if (only == "minimap")
            {
                GD.Print($"CHECK ok {await MinimapCheck.RunAsync(host, dir)}");
                return 0;
            }
            if (only == "embody")
            {
                GD.Print($"CHECK ok {await EmbodyCheck.RunAsync(host, dir)}");
                return 0;
            }
            if (only == "residency")
            {
                var alone = await ResidencyCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "travel")
            {
                var alone = await TravelCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "verify")
            {
                var alone = await VerifyCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "fidelity")
            {
                var alone = await FidelityCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "props")
            {
                var alone = await PropsCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "light")
            {
                var alone = LightCheck.Run(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "fog")
            {
                var alone = FogCheck.Run(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "terrain")
            {
                var alone = await TerrainCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "stream")
            {
                var alone = await StreamCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "water")
            {
                var alone = WaterCheck.Run(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "veil")
            {
                var alone = await VeilCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "shadow")
            {
                var alone = await ShadowCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "matrix")
            {
                var alone = await MatrixCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "backdrop")
            {
                var alone = BackdropCheck.Run(host);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "placement")
            {
                var alone = await PlacementCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "walk")
            {
                var alone = await WalkCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "bridges")
            {
                var alone = await BridgeCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "clips")
            {
                var alone = await ClipFitCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "secondary")
            {
                var alone = await SecondaryCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "animals")
            {
                var alone = await AnimalCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "pairs")
            {
                var alone = await PairCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "storeys")
            {
                var alone = await StoreysCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "scatter")
            {
                // The fixture world (heights) and the scatter section alone — the S3 reference plus the Task 26 worker.
                var src = new FixtureSource(dir);
                var w = new Node3D { Name = "CheckWorld" };
                host.AddChild(w);
                var b = new WorldBuilder(src, line => GD.Print("[check] " + line), strict: true);
                await b.BuildAsync(w, Goto, new SyncCheck.BuildProbe().Hooks(src));
                var alone = await ScatterCheck.RunAsync(w, src, b.Height!, dir);
                b.Models?.FreeAll();
                w.QueueFree();
                GD.Print($"CHECK ok scatter {alone}");
                return 0;
            }
            if (only == "figures")
            {
                // The fixture world (heights) and the figure section alone — clips, set chain, activities, tiers (Task 28).
                var src = new FixtureSource(dir);
                var w = new Node3D { Name = "CheckWorld" };
                host.AddChild(w);
                var b = new WorldBuilder(src, line => GD.Print("[check] " + line), strict: true);
                await b.BuildAsync(w, Goto, new SyncCheck.BuildProbe().Hooks(src));
                CheckPlacementRule();
                var alone = await CheckFigures(w, src, b);
                b.Models?.FreeAll();
                w.QueueFree();
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            var meshopt = CheckMeshopt(dir);

            var source = new FixtureSource(dir);
            var world = new Node3D { Name = "CheckWorld" };
            host.AddChild(world);
            var builder = new WorldBuilder(source, line => GD.Print("[check] " + line), strict: true);
            var probe = new SyncCheck.BuildProbe();
            var stats = await builder.BuildAsync(world, Goto, probe.Hooks(source));

            Expect("anchor", stats.Anchor.Position().DistanceTo(ExpectedAnchor) < 1e-4f, $"{stats.Anchor.Position()}");
            Expect("anchor location", stats.Anchor.LocationId == "loc-house", stats.Anchor.LocationId ?? "null");
            Expect("anchor height source", stats.Anchor.Source == Anchor.OverviewSource, stats.Anchor.Source);
            CheckAnchorRule(dir);
            Eq("tiles", stats.Tiles, ExpTiles);
            Eq("terrain pieces", stats.TerrainPieces, ExpTerrainPieces);
            Eq("terrain wet pieces", stats.TerrainWet, 0);
            Eq("terrain draws", stats.TerrainDraws, 1);
            Eq("terrain triangles", stats.TerrainTriangles, ExpTerrainTriangles);
            Expect("tile requests", source.TileRequests.SequenceEqual(new[] { "0,0" }), string.Join(";", source.TileRequests));
            Eq("locations", stats.Locations, ExpLocations);
            Eq("scenes", stats.Scenes, ExpScenes);
            Eq("buildings", stats.Buildings, ExpBuildings);
            Eq("buildings_meshopt", stats.BuildingsCompressed, ExpBuildingsMeshopt);
            Eq("building_vertices", stats.BuildingVertices, ExpBuildingVertices);
            Eq("building_indices", stats.BuildingIndices, ExpBuildingIndices);
            Eq("primitives", stats.Primitives, ExpPrimitives);
            Eq("skipped", stats.Skipped, ExpSkipped);
            Eq("shell_copies", stats.Recipe.ShellCopies, ExpShellCopies);
            Eq("degenerate", stats.Recipe.Degenerate, ExpDegenerate);
            Eq("interior", stats.Recipe.Interior, ExpInterior);
            Eq("panes", stats.Recipe.Panes, 0);
            Eq("interior mounted", stats.Recipe.InteriorMounted, ExpInteriorMounted);
            Eq("missing models", stats.Models.Missing, 1);   // the house's crate: no fixture for its URL
            Eq("failures", stats.Failures, 0);

            // Location frames: datum from the fine tile where loaded, else the overview.
            var house = world.GetNode<Node3D>("Locations/Loc_loc-house");
            var yard = world.GetNode<Node3D>("Locations/Loc_loc-yard");
            Near("house datum", house.Position.Y, ExpHouseDatum);
            Near("yard datum", yard.Position.Y, ExpYardDatum);
            Near("yard yaw", yard.Rotation.Y, Mathf.DegToRad(30f));

            // § B2 placement of the building, measured in its location frame.
            var placed = house.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString().StartsWith("Placed_building"));
            var box = ModelPlacement.Measure(placed, Transform3D.Identity);
            Near("building max xz", Math.Max(box.Size.X, box.Size.Z), ExpBuildingMaxM);
            Near("building bottom", box.Position.Y, ExpBuildingBottom);
            Near("building anchor x", box.GetCenter().X, ExpBuildingAnchor.X);
            Near("building anchor z", box.GetCenter().Z, ExpBuildingAnchor.Y);

            // The plate with a hole: area of the hole-free pieces.
            float area = PlateArea(dir);
            Near("plate area", area, ExpPlateArea);
            Expect("recipe mesh", yard.GetChildren().OfType<MeshInstance3D>().Any(n => n.Name.ToString().StartsWith("Recipe")),
                   "yard has no Recipe mesh");
            Expect("no recipe under house", !house.GetChildren().OfType<MeshInstance3D>().Any(n => n.Name.ToString().StartsWith("Recipe")),
                   "house drew its recipe despite the model");

            CheckPlacementRule();
            var figures = await CheckFigures(world, source, builder);
            var bench = BenchMathCheck.Run(source);
            var scatter = await ScatterCheck.RunAsync(world, source, builder.Height!, dir);
            var hud = HudCheck.Run(source);
            var ground = await GroundCheck.RunAsync(world, source, builder, stats, dir);
            var s3c = await S3cCheck.RunAsync(host, dir);
            var launcher = LauncherCheck.Run();
            var update = await UpdateCheck.RunAsync(host);
            var overview = OverviewCheck.Run(host, builder.FirstMap!.Value, builder.Height!);
            var pick = await PickCheck.RunAsync(host, world, builder, dir);
            var labels = await LabelCheck.RunAsync(host, world, builder, dir);
            var sync = await SyncCheck.RunAsync(source, probe, dir);
            var verify = await VerifyCheck.RunAsync(host, dir);
            var storeys = await StoreysCheck.RunAsync(host, dir);
            var placement = await PlacementCheck.RunAsync(host, dir);
            var walk = await WalkCheck.RunAsync(host, dir);
            var embody = await EmbodyCheck.RunAsync(host, dir);
            var audio = await AudioCheck.RunAsync(host, dir);
            var minimap = await MinimapCheck.RunAsync(host, dir);
            var propactions = await PropActionsCheck.RunAsync(host, dir);
            var residency = await ResidencyCheck.RunAsync(host, dir);
            var travel = await TravelCheck.RunAsync(host, dir);
            var bridges = await BridgeCheck.RunAsync(host, dir);
            var pairs = await PairCheck.RunAsync(host, dir);
            var clipFit = await ClipFitCheck.RunAsync(host, dir);
            var secondary = await SecondaryCheck.RunAsync(host, dir);
            var animals = await AnimalCheck.RunAsync(host, dir);
            var fidelity = await FidelityCheck.RunAsync(host, dir);
            var props = await PropsCheck.RunAsync(host, dir);
            var light = LightCheck.Run(host, dir);
            var fogLine = FogCheck.Run(host, dir);
            var backdrop = BackdropCheck.Run(host);
            var terrainLine = await TerrainCheck.RunAsync(host, dir);
            var streamLine = await StreamCheck.RunAsync(host, dir);
            var waterLine = WaterCheck.Run(host, dir);
            var veilLine = await VeilCheck.RunAsync(host, dir);
            var matrixLine = await MatrixCheck.RunAsync(host, dir);
            var shadowLine = await ShadowCheck.RunAsync(host, dir);
            var cacheLine = await CacheCheck.RunAsync(host, dir, cacheDir);

            GD.Print($"CHECK ok terrain_pieces={stats.TerrainPieces} tiles={stats.Tiles} buildings={stats.Buildings} "
                     + $"primitives={stats.Primitives} skipped={stats.Skipped} | {stats.Summary()} plate_area={area:0.###} "
                     + $"| meshopt {meshopt} | {figures} | bench {bench} | scatter {scatter} | hud {hud} | {ground} | {s3c} | {launcher} | {update} | {overview} | {pick} | {labels} | {sync} | {verify} | {storeys} | {placement} | {walk} | {travel} | {residency} | {embody} | {minimap} | {audio} | {propactions} | {bridges} | {pairs} | {clipFit} | {secondary} | {animals} | {fidelity} | {props} | {light} | {fogLine} | {backdrop} | {terrainLine} | {streamLine} | {waterLine} | {veilLine} | {matrixLine} | {shadowLine} | {cacheLine}");
            builder.Models?.FreeAll();
            world.QueueFree();
            return 0;
        }
        catch (Exception e)
        {
            GD.PrintErr($"CHECK FAILED {e.GetType().Name}: {e.Message}");
            GD.Print($"CHECK FAILED {e.GetType().Name}: {e.Message}");
            return 1;
        }
    }

    /// <summary>
    /// Meshopt round trip on a REAL server delivery copy (fixture provenance in
    /// the README): the decoded GLB must hold, bufferView for bufferView, the
    /// original's bytes (the server's codec is lossless and keeps view indices),
    /// and Godot must import the same vertex/index totals from both.
    /// </summary>
    private static string CheckMeshopt(string dir)
    {
        var original = File.ReadAllBytes(Path.Combine(dir, "building_original.glb"));
        var compressed = File.ReadAllBytes(Path.Combine(dir, "building_meshopt.glb"));
        Expect("fixture is compressed", GlbMeshoptDecoder.IsCompressed(compressed), "building_meshopt.glb has no EXT_meshopt_compression");
        Expect("original is plain", !GlbMeshoptDecoder.IsCompressed(original), "building_original.glb is compressed");
        Expect("passthrough", ReferenceEquals(GlbMeshoptDecoder.Decode(original), original), "plain GLB was rewritten");

        var decoded = GlbMeshoptDecoder.Decode(compressed, out var ds);
        Expect("decoded is plain", !GlbMeshoptDecoder.IsCompressed(decoded), "extension still listed");
        int views = CompareViews(original, decoded);

        var (origRoot, origCounts) = GlbLoader.Import(original, "building_original.glb");
        origRoot.Free();
        var (decRoot, decCounts) = GlbLoader.Import(decoded, "building_meshopt.glb (decoded)");
        decRoot.Free();
        var (jsonVerts, jsonIdx) = JsonCounts(original);
        Eq("json vertices", jsonVerts, ExpBuildingVertices);
        Eq("json indices", jsonIdx, ExpBuildingIndices);
        Eq("godot vertices (original)", origCounts.Vertices, ExpBuildingVertices);
        Eq("godot indices (original)", origCounts.Indices, ExpBuildingIndices);
        Eq("godot vertices (decoded)", decCounts.Vertices, origCounts.Vertices);
        Eq("godot indices (decoded)", decCounts.Indices, origCounts.Indices);
        return $"views={views} decoded={ds.Views} (attr={ds.Attributes} tri={ds.Triangles} seq={ds.Indices}) "
               + $"vertices={decCounts.Vertices} indices={decCounts.Indices} surfaces={decCounts.Surfaces} "
               + $"bytes {compressed.Length}->{decoded.Length} (original {original.Length})";
    }

    /// <summary>Byte equality of every bufferView between two GLBs with the same JSON indices.</summary>
    private static int CompareViews(byte[] a, byte[] b)
    {
        var (ja, ba) = GlbMeshoptDecoder.ReadGlb(a);
        var (jb, bb) = GlbMeshoptDecoder.ReadGlb(b);
        using var da = JsonDocument.Parse(ja);
        using var db = JsonDocument.Parse(jb);
        var va = da.RootElement.GetProperty("bufferViews").EnumerateArray().ToArray();
        var vb = db.RootElement.GetProperty("bufferViews").EnumerateArray().ToArray();
        Eq("bufferView count", vb.Length, va.Length);
        for (int i = 0; i < va.Length; i++)
        {
            ReadOnlySpan<byte> Slice(JsonElement v, byte[] bin)
            {
                int off = v.TryGetProperty("byteOffset", out var o) ? o.GetInt32() : 0;
                return bin.AsSpan(off, v.GetProperty("byteLength").GetInt32());
            }
            Expect($"bufferView {i} bytes", Slice(va[i], ba).SequenceEqual(Slice(vb[i], bb)), "decoded bytes differ");
        }
        Expect("buffers", db.RootElement.GetProperty("buffers").GetArrayLength() == 1, "fallback buffer kept");
        return va.Length;
    }

    /// <summary>Hand-check numbers straight from the glTF JSON: Σ POSITION counts, Σ indices counts.</summary>
    private static (int Vertices, int Indices) JsonCounts(byte[] glb)
    {
        var (json, _) = GlbMeshoptDecoder.ReadGlb(glb);
        using var doc = JsonDocument.Parse(json);
        var acc = doc.RootElement.GetProperty("accessors").EnumerateArray().ToArray();
        int v = 0, idx = 0;
        foreach (var mesh in doc.RootElement.GetProperty("meshes").EnumerateArray())
        foreach (var prim in mesh.GetProperty("primitives").EnumerateArray())
        {
            v += acc[prim.GetProperty("attributes").GetProperty("POSITION").GetInt32()].GetProperty("count").GetInt32();
            if (prim.TryGetProperty("indices", out var i)) idx += acc[i.GetInt32()].GetProperty("count").GetInt32();
        }
        return (v, idx);
    }

    /// <summary>The anchor rule (<see cref="Anchor.FromWorld"/>) on the fixture world: id match, origin default (no avatar), fogged/unplaced = error.</summary>
    private static void CheckAnchorRule(string dir)
    {
        using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap.json")));
        using var det = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "locations.json")));
        using var hf = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "heightfield.json")));
        var details = LocationInfo.ParseList(det.RootElement);
        var grid = HeightfieldOverview.Parse(hf.RootElement).Grid;
        var yard = Anchor.FromWorld(map.RootElement, details, grid, "LOC-YARD");
        Expect("goto by id", yard.LocationId == "loc-yard"
               && yard.Position().DistanceTo(new Vector3(-100f, ExpYardDatum, 50f)) < 1e-4f, $"{yard.Position()}");
        var origin = Anchor.FromWorld(map.RootElement, details, grid, null);
        Expect("goto default", origin.Position() == Vector3.Zero && origin.LocationId is null, $"{origin.Position()}");
        foreach (var bad in new[] { "cellar", "template", "nowhere" })
        {
            bool threw = false;
            try { Anchor.FromWorld(map.RootElement, details, grid, bad); }
            catch (InvalidOperationException) { threw = true; }
            Expect($"goto '{bad}' rejected", threw, "resolved instead of failing");
        }
    }

    /// <summary>
    /// Figures (Task S1b, whole library Task 28), two polls. Poll 1: three characters (free GLB, FBX in a location
    /// huddle, model-less traveller); poll 2: one moved, re-signed and given an activity, one vanished, one further
    /// along its route; then the model revision, the clip choice per kind and the distance tiers.
    /// Every expectation is derived in native/fixtures/README.md ("Clips", "Clip choice", "Tiers").
    /// </summary>
    private static async Task<string> CheckFigures(Node3D world, FixtureSource source, WorldBuilder builder)
    {
        var height = builder.Height!;
        var mgr = new FigureManager(source, height, line => GD.Print("[check] " + line), strict: true)
        {
            ClipFit = ClipFitMode.OnDemandSync,
            Slots = () => builder.Slots,
            AutoTick = false,
            FocusTarget = () => new Vector3(263, 0, -100),   // Cleo's journey point: the model queue serves her first
        };
        world.AddChild(mgr);
        await mgr.InitAsync();
        var clips = mgr.Clips;
        Expect("standing pose → its clip (trimmed, lower-cased)", clips.StandingKind == ExpStandingKind, clips.StandingKind);
        Expect("walking pose → its clip", clips.MovingKind == ExpMovingWant, clips.MovingKind);
        Expect("blank running kind → default run", FigureClips.MoveClip(FigureClips.WalkRun, true, clips.Poses) == "run",
               FigureClips.MoveClip(FigureClips.WalkRun, true, clips.Poses));
        Eq("transition rules (junk row dropped)", clips.Transitions.Count, 2);
        var start = FigureClips.Transition(ExpStandingKind, ExpMovingKind, clips.Transitions);
        Expect("transition stand-relaxed → walk", start is { Kind: "start-walk", Accel: 8 }, $"{start}");
        var getUp = FigureClips.Transition("sitting", ExpMovingKind, clips.Transitions);
        Expect("exit rule sitting → *", getUp is { Kind: "get-up-chair", Accel: 0 }, $"{getUp}");

        // ---- the whole library: 9 listed, 5 imported, 4 × 404, commit in listing order ----
        await clips.WaitClipsAsync();
        Eq("listed clips", clips.Entries.Count, 9);
        Eq("clips imported", clips.ClipsLoaded, ExpClipsLoaded);
        Eq("clips failed (404)", clips.ClipsFailed, ExpClipsFailed);
        Expect("pair half named <kind>__<role>", clips.Entries[0].Kind == "stand-relaxed__a", clips.Entries[0].Kind);
        Expect("committed kinds in listing order", clips.Index.Kinds.SequenceEqual(ExpIndexKinds), string.Join(",", clips.Index.Kinds));
        Expect("female stand-relaxed and walk failed → no slot", clips.Clip("stand-relaxed", "female") is null && clips.Clip("walk", "female") is null, "slot");
        Expect("loop flags per FILE", clips.Clip("waiting", "female")!.Loop && !clips.Clip("waiting")!.Loop
                                      && !clips.Clip("reading")!.Loop && clips.Clip("walk")!.Loop, "flags");
        Expect("root motion: keep yes, strip no, missing no", clips.Clip("waiting", "female")!.RootMotion
                                      && !clips.Clip("reading")!.RootMotion && !clips.Clip("walk")!.RootMotion, "root motion");
        var chain = clips.ClipsFor(new[] { "female" }).Select(c => $"{c.Kind}/{c.Set}").ToList();
        Expect("set chain [female, '']", chain.SequenceEqual(new[] { "Stand-Relaxed/", "walk/", "waiting/female", "reading/" }),
               string.Join(",", chain));
        Eq("each clip URL downloaded once", clips.Entries.Count(e => source.ByteRequests.Count(u => u == e.Url) == 1), 9);

        using (var map = await source.GetWorldMapAsync()) await mgr.Apply(map.RootElement);
        var st = mgr.Stats;
        Eq("figures", st.Figures, ExpFigures);
        Eq("glb_figures", st.GlbFigures, ExpGlbFigures);
        Eq("placeholders", st.Placeholders, ExpPlaceholders);
        Eq("clips_loaded", st.ClipsLoaded, ExpClipsLoaded);
        Eq("bound_tracks", st.BoundTracks, ExpBoundTracks);
        Eq("kinds_bound (actions)", st.KindsBound, ExpActions.Length + ExpBramActions.Length);
        Eq("unbound_clips", st.UnboundClips, 0);
        Eq("offmap", st.Offmap, 0);
        Eq("model_failures", st.ModelFailures, 0);
        Expect("model queue: nearest the focus first", mgr.ModelLoadOrder.Take(3).SequenceEqual(new[] { Cleo, Bram, Ada }),
               string.Join(",", mgr.ModelLoadOrder));
        var poll1 = st.Summary();

        var ada = mgr.Figures[Ada];
        var bram = mgr.Figures[Bram];
        var cleo = mgr.Figures[Cleo];
        Expect("rules", ada.Rule == "free" && bram.Rule == "tile" && cleo.Rule == "journey",
               $"{ada.Rule}/{bram.Rule}/{cleo.Rule}");
        NearV("Ada position", ada.Position, ExpAda);
        NearV("Bram position", bram.Position, ExpBram);
        NearV("Cleo position", cleo.Position, ExpCleo);
        Near("Ada y = ground", ada.Position.Y, (float)height.GroundAt(-50, 30));
        Expect("Ada and Bram are models, Cleo is not", ada.IsGlb && bram.IsGlb && !cleo.IsGlb, "body kinds");
        Near("Ada height", ModelPlacement.Measure(ada.Body!, Transform3D.Identity).Size.Y, ExpAdaHeight);
        Near("Bram height", ModelPlacement.Measure(bram.Body!, Transform3D.Identity).Size.Y, ExpBramHeight);
        // Cleo has no model and the fixture serves no fallback pool (its manifest is a 404): the portrait stands in
        // (npcs.ts' sprite branch) — no tag height; her avatar_url is a character image, so it is asked for as a cut-out
        // (?transparent=1, transparentPortraitUrl) and drawn instead of the initials "CM".
        Expect("Cleo portrait", cleo.Portrait is { HasPicture: true } && cleo.TagHeight is null && mgr.PoolState == "failed"
                                && st.Portraits == 1 && st.PoolFigures == 0, $"portrait {cleo.Portrait is not null} pool {mgr.PoolState}");
        Expect("Cleo initials gone with the picture", cleo.Portrait!.Initials.Text == "CM" && !cleo.Portrait.Initials.Visible
               && source.ByteRequests.Contains("/characters/Cleo%20Marsh/images/cleo.png?transparent=1"), cleo.Portrait.Initials.Text);
        Eq("Ada metallic materials (forced to 0)", FigureManager.MetallicMaterials(ada.Body!), 0);
        // Bram: the FBX and its separate texture, each fetched once; his own takes with the model.clips flags.
        Eq("Bram FBX + texture fetched once each", source.ByteRequests.Count(u => u.Contains("Bram", StringComparison.Ordinal)), 2);
        Expect("Bram's actions are his takes", bram.ClipKinds.SequenceEqual(ExpBramActions) && bram.Legs.Count == 0,
               string.Join(",", bram.ClipKinds));
        Expect("Bram's sit is a one-shot, walk loops", bram.Player!.GetAnimation("sit").LoopMode == Animation.LoopModeEnum.None
               && bram.Player.GetAnimation("walk").LoopMode == Animation.LoopModeEnum.Linear, "loop flags");
        Expect("Bram stands: the idle take", bram.CurrentClip == "idle", bram.CurrentClip);

        // Ada's actions: the four kinds of her chain + the idle alias (CLIP_SYNONYMS: 'stand' ⊂ stand-relaxed).
        Expect("Ada actions", ada.ClipKinds.SequenceEqual(ExpActions), string.Join(",", ada.ClipKinds));
        var player = ada.Player!;
        // The library is fitted lazily (Task 35b): the clips read below are fitted now (the play would do it).
        foreach (var action in new[] { "waiting", "reading", "idle" }) ada.EnsureClip(action);
        Expect("waiting from the female set", ada.ClipSets.GetValueOrDefault("waiting") == "female", $"{ada.ClipSets.GetValueOrDefault("waiting")}");
        Expect("waiting loops (female file)", player.GetAnimation("waiting").LoopMode == Animation.LoopModeEnum.Linear, "not looping");
        Expect("reading one-shot", player.GetAnimation("reading").LoopMode == Animation.LoopModeEnum.None, "loops");
        Expect("idle alias = the stand-relaxed clip", player.GetAnimation("idle") == player.GetAnimation(ExpStandingKind), "other clip");
        ExpectClip(ada, "poll 1 standing", ExpStandingKind, ExpStandingKind, 1);

        // The binding itself: after one evaluation the skeleton holds the clip's values.
        CheckBinding(mgr, ada);
        CheckClipChoice(ada);
        // The importer cross-check (rest_reference.json): FBX values and the mesh-sole sampling against three's.
        var restInfo = CheckRestReference(mgr, ada, source);
        ada.Replay();

        // ---- poll 2 ----
        using (var map = await source.GetWorldMapFileAsync("worldmap_poll2.json")) await mgr.Apply(map.RootElement);
        st = mgr.Stats;
        Eq("poll2 figures", st.Figures, 2);
        Expect("Bram removed", !mgr.Figures.ContainsKey(Bram), "still there");
        Eq("Ada model3d requests (model_sig changed)", source.ModelRequests.Count(n => n == Ada), 2);
        Eq("Ada GLB downloads (same URL, cached)", source.ByteRequests.Count(u => u == AdaUrl), 1);
        Eq("Cleo model3d requests (sig absent, unchanged)", source.ModelRequests.Count(n => n == Cleo), 1);
        Eq("clips still downloaded once", clips.Entries.Count(e => source.ByteRequests.Count(u => u == e.Url) == 1), 9);
        Eq("poll2 bound_tracks", st.BoundTracks, ExpBoundTracks);
        Expect("Ada reloaded", ada.LoadedSig == "ada-2" && ada.IsGlb, ada.LoadedSig ?? "null");
        NearV("Ada still at the old point", ada.Position, ExpAda);
        mgr.Tick(0.5);
        Expect("Ada runs (10 m > 6)", ada.Moving && ada.Running, $"moving {ada.Moving} running {ada.Running}");
        ExpectClip(ada, "poll 2 running: the walk take as the run stand-in", "run", ExpMovingKind, 1.5);
        Near("Ada faces +x", ada.Rotation.Y, Mathf.Pi / 2f);
        NearV("Ada after one run step", ada.Position, ExpAdaRun1);
        Expect("Cleo walks, never runs (travelling)", cleo.Moving && !cleo.Running, $"moving {cleo.Moving} running {cleo.Running}");
        NearV("Cleo after one walk step", cleo.Position, ExpCleoStep1);
        mgr.Tick(0.5);
        mgr.Tick(0.5);
        NearV("Ada walks the last 3.88 m", ada.Position, ExpAdaWalk1);
        Expect("Ada walks", ada.Moving && !ada.Running, "running");
        ExpectClip(ada, "poll 2 walking", ExpMovingWant, ExpMovingKind, 1);
        mgr.Tick(0.5);
        mgr.Tick(0.5);
        NearV("Ada arrived", ada.Position, ExpAdaEnd);
        mgr.Tick(0.5);
        Expect("Ada stands after arriving", !ada.Moving, "moving");
        // Six half-second route frames: root x263-6*1.7=252.8, shown=144.686+6*.7=148.886;
        // reached-point Y = 4.875*(251.114+256)/512. She keeps walking beyond the stale poll point.
        NearV("Cleo follows the advancing route", cleo.Position, new Vector3(252.8f, 4.82847802734375f, -100f));
        Near("Ada keeps facing +x (no neighbour, no marker)", ada.Rotation.Y, Mathf.Pi / 2f);
        ExpectClip(ada, "poll 2 arrived: activity_animation", "reading", "reading", 1);
        CheckHoldsLastFrame(ada, "reading");

        // ---- model_rev (refreshIfChanged): unchanged → nothing, changed → one reload, the GLB stays cached ----
        using (var map = Load("worldmap_poll2.json")) await mgr.Apply(map.RootElement);
        Eq("same sig + rev: no model3d request", source.ModelRequests.Count(n => n == Ada), 2);
        await mgr.Apply(WithRev("worldmap_poll2.json", Ada, "r2"));
        Eq("model_rev changed: one model3d request", source.ModelRequests.Count(n => n == Ada), 3);
        Eq("model_rev reload: GLB still cached", source.ByteRequests.Count(u => u == AdaUrl), 1);

        var tiers = await CheckTiers(mgr, ada, source);
        int modelLoads = st.ModelLoads;   // the summary's poll-2 count, before the retirement step reloads Ada once more
        var retired = await CheckRetire(mgr, ada, source);
        var info = RestMismatch(source, ada);
        var memory = $"ada clips {ada.ClipKinds.Count} actions {ada.ClipKeys} keys {ada.ClipBytes / 1048576.0:0.00} MiB";
        mgr.QueueFree();
        return $"figures {poll1} | poll2 figures={st.Figures} glb_figures={st.GlbFigures} placeholders={st.Placeholders} "
               + $"model_loads={modelLoads} | {tiers} | {retired} | {memory} | {restInfo} | {info}";
    }

    /// <summary>
    /// Task 35 (figures.ts <c>retireModels</c> / <c>freeRetired</c>, README "Retired models"): while both of Ada's tier
    /// templates are current nothing is freed; once her model changes (rev r3, the answer now serves the old LOW file as
    /// her only edition) and the new body is live, the replaced full edition's template is freed — exactly one — and the
    /// figure keeps playing on the template it uses.
    /// </summary>
    private static async Task<string> CheckRetire(FigureManager mgr, Figure ada, FixtureSource source)
    {
        int before = mgr.TemplateCount;
        Eq("nothing stale while both tiers are current", mgr.RetireStaleTemplates(), 0);
        source.ModelAnswers[Ada] = "{\"model\": {\"format\": \"glb\", \"rig\": \"mixamo\", \"url\": \"" + AdaLowUrl
                                   + "\", \"model_rev\": \"r3\"}, \"animation_sets\": []}";
        try
        {
            await mgr.Apply(WithRev("worldmap_poll2.json", Ada, "r3"));
        }
        finally { source.ModelAnswers.Remove(Ada); }
        Expect("Ada on her new model", ada.LoadedRev == "r3" && ada.LoadedUrl == AdaLowUrl && ada.Player is not null,
               $"rev {ada.LoadedRev} url {ada.LoadedUrl}");
        Eq("the replaced full edition is freed", mgr.RetireStaleTemplates(), 1);
        Eq("templates after the retirement", mgr.TemplateCount, before - 1);
        Eq("a second pass frees nothing", mgr.RetireStaleTemplates(), 0);
        Expect("Ada still animates on the template she uses", ada.Animates && ada.Player!.HasAnimation(ada.CurrentClip),
               ada.CurrentClip);
        return $"retired 1 of {before} templates after the model change";
    }

    /// <summary>The figure plays <paramref name="clip"/> for <paramref name="kind"/> at <paramref name="pace"/>.</summary>
    private static void ExpectClip(Figure fig, string what, string kind, string clip, double pace)
        => Expect($"{fig.CharacterName} {what}", fig.CurrentKind == kind && fig.CurrentClip == clip
                                                 && Math.Abs(fig.CurrentPace - pace) < 1e-9
                                                 && Math.Abs(fig.Player!.SpeedScale - pace) < 1e-6,
                  $"kind {fig.CurrentKind} clip {fig.CurrentClip} pace {fig.CurrentPace}, expected {kind}/{clip}/{pace}");

    /// <summary>
    /// <c>Figure.play(kind)</c> on Ada's five actions (README "Clip choice"): exact, the female file, the alias,
    /// a curated stand-in, a run served by the walk take at pace 1.5; then back to what she wants.
    /// </summary>
    private static void CheckClipChoice(Figure ada)
    {
        ada.Play("waiting");
        ExpectClip(ada, "waiting", "waiting", "waiting", 1);
        ada.Play("idle");
        ExpectClip(ada, "idle (alias)", "idle", "idle", 1);
        ada.Play("lie");
        ExpectClip(ada, "lie → standing stand-in", "lie", ExpStandingKind, 1);
        ada.Play("Run-Fast");
        ExpectClip(ada, "run-fast → walk take, sped up", "run-fast", ExpMovingKind, 1.5);
        ada.Play("");
        ExpectClip(ada, "empty kind = the standing pose", ExpStandingKind, ExpStandingKind, 1);
        ada.Replay();
        ExpectClip(ada, "replay", ExpStandingKind, ExpStandingKind, 1);
    }

    /// <summary>A one-shot holds its LAST frame once it ran out (the browser's <c>clampWhenFinished</c>).</summary>
    private static void CheckHoldsLastFrame(Figure fig, string action)
    {
        var player = fig.Player!;
        var skel = fig.Skeleton!;
        var anim = player.GetAnimation(action);
        player.Advance(anim.Length + 1.0);
        Expect($"{action} finished", !player.IsPlaying(), "still playing");
        int bone = skel.FindBone("mixamorig_LeftUpLeg");
        var model = (Node3D)fig.Body!.GetChild(0);
        int track = anim.FindTrack(new NodePath($"{model.GetPathTo(skel)}:mixamorig_LeftUpLeg"), Animation.TrackType.Rotation3D);
        Expect($"{action} LeftUpLeg track", track >= 0, "missing");
        var last = anim.RotationTrackInterpolate(track, anim.Length);
        var got = skel.GetBonePoseRotation(bone);
        Expect($"{action} holds its last frame", got.IsEqualApprox(last) || got.IsEqualApprox(-last), $"{got} vs {last}");
    }

    /// <summary>
    /// The distance tiers (README "Tiers", npcs.ts <c>tickFigureTiers</c> with 25/35 m): the camera on Ada's +x side
    /// at 30, 24, 30, 36, 30, 24, 36 m → full, full, full, low, low, full, low; the low edition downloads once, the
    /// way back is a cache swap.
    /// </summary>
    private static async Task<string> CheckTiers(FigureManager mgr, Figure ada, FixtureSource source)
    {
        var expected = new[] { (30f, FigureTier.Full), (24f, FigureTier.Full), (30f, FigureTier.Full), (36f, FigureTier.Low),
                               (30f, FigureTier.Low), (24f, FigureTier.Full), (36f, FigureTier.Low) };
        var seen = new List<string>();
        foreach (var (d, tier) in expected)
        {
            await mgr.TickTiers(ada.Position + new Vector3(d, 0, 0));
            seen.Add($"{d}→{ada.LoadedTier}");
            Expect($"tier at {d} m", ada.WantedTier == tier && ada.LoadedTier == tier
                                     && ada.LoadedUrl == (tier == FigureTier.Low ? AdaLowUrl : AdaUrl),
                   $"wanted {ada.WantedTier} loaded {ada.LoadedTier} url {ada.LoadedUrl}");
        }
        Eq("low edition downloaded once", source.ByteRequests.Count(u => u == AdaLowUrl), 1);
        Eq("full edition still downloaded once", source.ByteRequests.Count(u => u == AdaUrl), 1);
        Eq("tiers ask no model3d", source.ModelRequests.Count(n => n == Ada), 3);
        Eq("low tier bound tracks", ada.BoundTracks, ExpBoundTracks);
        return "tiers " + string.Join(" ", seen);
    }

    /// <summary>A world-map fixture with one character's <c>model_rev</c> replaced.</summary>
    private static JsonElement WithRev(string file, string name, string rev)
    {
        var node = JsonNode.Parse(File.ReadAllText(Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures", file)))!;
        foreach (var c in node["characters"]!.AsArray())
            if (c!["name"]!.GetValue<string>() == name) c["model_rev"] = rev;
        return JsonDocument.Parse(node.ToJsonString()).RootElement.Clone();
    }

    /// <summary>
    /// Evaluate the standing clip once and read the skeleton back: a moving bone holds the clip's key 0 corrected, a
    /// bone Godot left without a track holds the clip's node default (the restored constant), the hips stand in place
    /// with their WORLD height scaled by the standing reference: y_world = y0 · hipsRestWorldY / ref (README "Clips").
    /// </summary>
    private static void CheckBinding(FigureManager mgr, Figure fig)
    {
        var player = fig.Player ?? throw new InvalidOperationException("no AnimationPlayer");
        var skel = fig.Skeleton ?? throw new InvalidOperationException("no skeleton");
        var clip = mgr.Clips.Clip("Stand-Relaxed")!;
        Expect("stand-relaxed playing", player.CurrentAnimation == ExpStandingKind, player.CurrentAnimation);
        player.Seek(0, true);

        void SameRot(string bone, Quaternion want)
        {
            int i = skel.FindBone(bone);
            Expect($"{bone} on skeleton", i >= 0, "missing");
            var got = skel.GetBonePoseRotation(i);
            Expect($"stand-relaxed {bone} rotation", got.IsEqualApprox(want) || got.IsEqualApprox(-want), $"{got} vs {want}");
        }
        string moving = "mixamorig_LeftUpLeg", constant = "mixamorig_LeftForeArm";
        Expect("LeftUpLeg has a track", clip.RotationTracks.ContainsKey(moving), "no track");
        Expect("LeftForeArm has none (constant in the file)", !clip.RotationTracks.ContainsKey(constant), "has a track");
        var model = (Node3D)fig.Body!.GetChild(0);
        var fixes = RestAdapter.Build(mgr.Clips.DonorRest!, model, skel);
        Quaternion Fixed(string bone, Quaternion c)
            => fixes.TryGetValue(ClipLibrary.NormBone(bone), out var f) ? RestAdapter.Apply(f, c).Normalized() : c;
        SameRot(moving, Fixed(moving, clip.Anim.TrackGetKeyValue(clip.RotationTracks[moving], 0).AsQuaternion()));
        SameRot(constant, Fixed(constant, clip.RestRotations[Array.IndexOf(clip.Bones, constant)]));

        var (h, parent) = ClipLibrary.HipsParentFrame(model, skel);
        var restWorld = parent * skel.GetBoneRest(h).Origin;
        var poseWorld = parent * skel.GetBonePosePosition(h);
        double refY = mgr.Clips.DonorHipsY!.Value;
        double y0 = Math.Abs(clip.Anim.TrackGetKeyValue(clip.PositionTracks["mixamorig_Hips"], 0).AsVector3().Y);
        Near("hips x in place", poseWorld.X, restWorld.X, 1e-5f);
        Near("hips z in place", poseWorld.Z, restWorld.Z, 1e-5f);
        Near("hips world y = y0 · rest/ref", poseWorld.Y, (float)(y0 * restWorld.Y / refY), 1e-5f);
    }

    /// <summary>
    /// IMPORTER CROSS-CHECK, not the oracle of the correction (that is shared/test-vectors/retarget.json):
    /// <c>native/fixtures/rest_reference.json</c> (written by <c>native/fixtures/rest_reference.mjs</c> on three's
    /// loaders) proves what no vector can — that Godot's FBX/glTF importers hand the Core math the same clip values and
    /// rests as three's, and that the Godot adapter's mesh-sole sampling (<see cref="RestAdapter.SolesOf"/>) finds the
    /// soles three's <c>restSolesOf</c> finds. Three tracked demo rigs: Minerva (= Ada; no stance rule), Johanna (leg
    /// stance), Hagrid (torso + foot stance). Per model: corrected-bone count and stance bones; per clip/time/bone the
    /// clip value and the corrected rotation within 0.5°; for Ada the pose read back off her skeleton.
    /// </summary>
    private static string CheckRestReference(FigureManager mgr, Figure ada, FixtureSource source)
    {
        // The reference names the clip FILES (idle.fbx / walk.fbx); the fixture library serves them as the
        // standing pose's Stand-Relaxed and the walking pose's walk.
        static string SampleKind(JsonElement sample)
            => sample.GetProperty("clip").GetString() == "idle" ? ExpStandingKind : ExpMovingKind;
        ClipSource ClipOf(string action) => mgr.Clips.Clip(action == ExpStandingKind ? "Stand-Relaxed" : action)!;
        const double TolDeg = 0.5;
        var donor = mgr.Clips.DonorRest ?? throw new InvalidOperationException("reference rig not loaded");
        Expect("rig hips height", mgr.Clips.DonorHipsY is > 1.13 and < 1.131, $"{mgr.Clips.DonorHipsY}");
        using var refDoc = Load("rest_reference.json");
        double maxClip = 0, maxFixed = 0, maxPose = 0;
        int compared = 0, models = 0;
        string worst = "";
        Quaternion Q(JsonElement a) => new((float)a[0].GetDouble(), (float)a[1].GetDouble(),
                                           (float)a[2].GetDouble(), (float)a[3].GetDouble());
        double Deg(Quaternion a, Quaternion b) => Mathf.RadToDeg(a.Normalized().AngleTo(b.Normalized()));
        Quaternion Sample(ClipSource clip, string bone, double t)
        {
            int b = Array.FindIndex(clip.Bones, n => ClipLibrary.NormBone(n) == ClipLibrary.NormBone(bone));
            if (b < 0) throw new InvalidOperationException($"clip {clip.Kind} has no bone {bone}");
            return clip.RotationTracks.TryGetValue(clip.Bones[b], out var tr)
                ? clip.Anim.RotationTrackInterpolate(tr, t) : clip.RestRotations[b];
        }
        foreach (var model in refDoc.RootElement.GetProperty("models").EnumerateArray())
        {
            var name = model.GetProperty("name").GetString()!;
            var file = model.GetProperty("file").GetString()!;
            var (root, _) = GlbLoader.Import(File.ReadAllBytes(source.Resolve("repo:" + file)), file);
            try
            {
                var skel = ClipLibrary.Find<Skeleton3D>(root)!;
                var stance = new HashSet<string>();
                var fixes = RestAdapter.Build(donor, root, skel, stanceBones: stance);
                Eq($"{name} corrected bones", fixes.Count, model.GetProperty("corrected_bones").GetInt32());
                var wantStance = model.GetProperty("stance_bones").EnumerateArray().Select(e => e.GetString()!).ToHashSet();
                Expect($"{name} stance bones", stance.SetEquals(wantStance),
                       $"got [{string.Join(",", stance.OrderBy(x => x))}], browser [{string.Join(",", wantStance.OrderBy(x => x))}]");
                foreach (var sample in model.GetProperty("samples").EnumerateArray())
                {
                    var role = SampleKind(sample);
                    var clip = ClipOf(role);
                    double t = sample.GetProperty("time").GetDouble();
                    foreach (var bone in sample.GetProperty("bones").EnumerateObject())
                    {
                        var c = Sample(clip, bone.Name, t);
                        double dc = Deg(c, Q(bone.Value.GetProperty("clip")));
                        var key = ClipLibrary.NormBone(bone.Name);
                        var q = fixes.TryGetValue(key, out var f) ? RestAdapter.Apply(f, c) : c;
                        double dq = Deg(q, Q(bone.Value.GetProperty("corrected")));
                        maxClip = Math.Max(maxClip, dc);
                        if (dq > maxFixed) { maxFixed = dq; worst = $"{name}/{role}@{t}/{bone.Name}"; }
                        Expect($"{name} {role}@{t} {bone.Name} clip value (importers)", dc <= TolDeg, $"{dc:0.###}°");
                        Expect($"{name} {role}@{t} {bone.Name} corrected vs browser", dq <= TolDeg, $"{dq:0.###}°");
                        compared++;
                    }
                }
                models++;
            }
            finally { root.Free(); }
        }

        // End to end on Ada (Minerva): evaluate the bound clip, read the skeleton.
        var minerva = refDoc.RootElement.GetProperty("models").EnumerateArray().First(m => m.GetProperty("name").GetString() == "Minerva McGonagall");
        var player = ada.Player!;
        var skelA = ada.Skeleton!;
        foreach (var sample in minerva.GetProperty("samples").EnumerateArray())
        {
            var role = SampleKind(sample);
            double t = sample.GetProperty("time").GetDouble();
            player.Play(role, 0);
            player.Seek(t, true);
            foreach (var bone in sample.GetProperty("bones").EnumerateObject())
            {
                int i = skelA.FindBone("mixamorig_" + bone.Name);
                Expect($"Ada bone {bone.Name}", i >= 0, "missing");
                double d = Deg(skelA.GetBonePoseRotation(i), Q(bone.Value.GetProperty("corrected")));
                maxPose = Math.Max(maxPose, d);
                Expect($"Ada pose {role}@{t} {bone.Name} vs browser", d <= TolDeg, $"{d:0.###}°");
            }
        }
        return $"rest_reference (importer cross-check) models={models} compared={compared} max_clip_dev={maxClip:0.####}° "
               + $"max_corrected_dev={maxFixed:0.####}° ({worst}) max_pose_dev={maxPose:0.####}°";
    }

    /// <summary>
    /// Information only (no expectation): how far the character's bind pose sits
    /// from the reference rig the clips were authored on, bone by bone (local
    /// rest rotations) — the error the spike's verbatim copy carries and the
    /// browser's rest correction removes.
    /// </summary>
    private static string RestMismatch(FixtureSource source, Figure fig)
    {
        var refRoot = new FbxDocument();
        var state = new FbxState();
        if (refRoot.AppendFromFile(source.Resolve("repo:shared/models/rig/reference.fbx"), state) != Error.Ok)
            return "rest_mismatch=n/a";
        var scene = refRoot.GenerateScene(state);
        try
        {
            var rs = ClipLibrary.Find<Skeleton3D>(scene)!;
            var ts = fig.Skeleton!;
            double sum = 0, max = 0; int n = 0; string worst = "";
            for (int i = 0; i < ts.GetBoneCount(); i++)
            {
                int r = rs.FindBone(ts.GetBoneName(i));
                if (r < 0) continue;
                var a = ts.GetBoneRest(i).Basis.GetRotationQuaternion();
                var b = rs.GetBoneRest(r).Basis.GetRotationQuaternion();
                double deg = Mathf.RadToDeg(a.AngleTo(b));
                sum += deg; n++;
                if (deg > max) { max = deg; worst = ts.GetBoneName(i); }
            }
            return $"rest_mismatch_deg mean={sum / Math.Max(n, 1):0.0} max={max:0.0} ({worst}) over {n} bones";
        }
        finally { scene.Free(); }
    }

    /// <summary>
    /// The placement orchestration on its own (<see cref="FigurePlacement.Plan"/>, main.ts <c>computeNpcPlacements</c>):
    /// offmap, the fogged route, the clamped route, a free point that leaves a room (snap), and a CLOSED building whose
    /// room figure hides while the rest huddle. A hand tile "h": centre (10, 0, 20), yaw 90° → tileToWorld(lx, lz) =
    /// (10 + lz, ·, 20 − lx), width 10, fade 0, room "hall" with a centre; tile ground 0.5, terrain 0.25 everywhere.
    /// </summary>
    private static void CheckPlacementRule()
    {
        var tile = new PlacementTile
        {
            Frame = new TileFrame(new Overview.Vec3(10, 0, 20), Math.PI / 2), Width = 10, IsBuilding = true,
            RoomCenters = new Dictionary<string, Overview.Vec3> { ["hall"] = new(12, 0.3, 21) },
        };
        LocationPlacement? TileOf(string id) => id == "h" ? new LocationPlacement(tile, true, (_, _) => 0.5, (_, _, _) => null) : null;
        var rows = new List<CharacterRow>
        {
            new("Zed", "h", null, null, null, null, null),
            new("Amy", "h", null, null, null, null, null),
            new("Hal", "h", null, null, null, null, null) { RoomId = "hall" },
            new("Nob", "", null, null, null, null, null),                                  // offmap
            new("Fog", "", 7, 8, null, null, new TravelInfo(null, null)),                // withheld route → pos
            new("Dot", "", null, null, null, null, new TravelInfo(new() { (1, 1) }, 0)),  // degenerate, no pos → offmap
            new("Run", "", 0, 0, null, null, new TravelInfo(new() { (0, 0), (3, 4) }, 99)), // clamped to the end
            new("Wil", "", 5, 6, null, null, null),                                       // wilderness, came out of a room
        };
        var shown = new Dictionary<string, ShownPlacement> { ["Wil"] = new("hall", true) };
        var plans = FigurePlacement.Plan(rows, TileOf, (_, _) => 0.25, shown, _ => null).ToDictionary(p => p.Name);
        Expect("offmap", !plans.ContainsKey("Nob") && !plans.ContainsKey("Dot"), string.Join(",", plans.Keys));
        Expect("fog → pos", plans["Fog"] is { Rule: "journey-pos", OnTerrain: true } && plans["Fog"].Pos == new Overview.Vec3(7, 0.25, 8), $"{plans["Fog"]}");
        Expect("route end", plans["Run"] is { Rule: "journey" } && plans["Run"].Pos == new Overview.Vec3(3, 0.25, 4), $"{plans["Run"]}");
        Expect("free out of a room snaps", plans["Wil"] is { Rule: "free", Snap: true } && shown["Wil"] == new ShownPlacement(null, false), $"{plans["Wil"]}");
        // Sorted Amy, Hal, Zed (i 0..2 of 3): x = (i − 1)·2.3, z = 3.6 → world (13.6, 0.5, 20 − x).
        NearPlan("Amy huddle", plans["Amy"], 13.6, 0.5, 22.3);
        NearPlan("Hal huddle", plans["Hal"], 13.6, 0.5, 20);
        NearPlan("Zed huddle", plans["Zed"], 13.6, 0.5, 17.7);
        Expect("closed interior hides the room figure", plans["Hal"].Hidden && !plans["Amy"].Hidden && !plans["Zed"].Hidden
               && plans["Amy"] is { Rule: "tile", Snap: true }, "hidden flags");
        Expect("shown placement written", shown["Amy"] == new ShownPlacement(null, false) && shown["Hal"] == new ShownPlacement(null, false), "shown");
    }

    private static void NearPlan(string what, FigurePlan got, double x, double y, double z)
        => Expect(what, Math.Abs(got.Pos.X - x) < 1e-6 && Math.Abs(got.Pos.Y - y) < 1e-6 && Math.Abs(got.Pos.Z - z) < 1e-6,
                  $"got {got.Pos}, expected ({x}, {y}, {z})");

    private static JsonDocument Load(string file)
        => JsonDocument.Parse(File.ReadAllBytes(Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures", file)));

    private static void NearV(string what, Vector3 got, Vector3 want, float eps = 1e-3f)
        => Expect(what, got.DistanceTo(want) <= eps, $"got {got}, expected {want}");


    /// <summary>The top face of the yard's holed plate as the native builder makes it (<see cref="RecipeGeometry.Plate"/>).</summary>
    private static float PlateArea(string dir)
    {
        using var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "scene_loc-yard.json")));
        var plate = ScenePayload.Parse(doc.RootElement).Plates.First(p => p.Holes.Length > 0);
        var mesh = RecipeGeometry.Plate(plate);
        double area = 0;
        for (int i = 0; i + 2 < mesh.Indices.Count; i += 3)
        {
            var a = mesh.Positions[mesh.Indices[i]];
            var b = mesh.Positions[mesh.Indices[i + 1]];
            var c = mesh.Positions[mesh.Indices[i + 2]];
            if (Math.Abs(a.Y - plate.TopY) > 1e-6 || Math.Abs(b.Y - plate.TopY) > 1e-6 || Math.Abs(c.Y - plate.TopY) > 1e-6) continue;
            area += Math.Abs((b.X - a.X) * (c.Z - a.Z) - (c.X - a.X) * (b.Z - a.Z)) / 2;
        }
        return (float)area;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }

    private static void Eq(string what, int got, int want)
        => Expect(what, got == want, $"got {got}, expected {want}");

    private static void Near(string what, float got, float want, float eps = 1e-3f)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got}, expected {want}");
}
