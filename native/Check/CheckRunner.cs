using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
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
    private const int ExpOverviewVertices = 9, ExpOverviewTriangles = 6;
    private const int ExpTiles = 1, ExpTileVertices = 25;
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
    private const int ExpFigures = 3, ExpGlbFigures = 1, ExpPlaceholders = 2, ExpClipsLoaded = 2;
    private const int ExpTracksPerClip = 53;                       // 52 rotations + the hips position
    private const int ExpBoundTracks = 2 * ExpTracksPerClip;        // idle + walk on the one GLB figure
    private const string Ada = "Ada Wren", Bram = "Bram Holt", Cleo = "Cleo Marsh";
    private static readonly Vector3 ExpAda = new(-50f, 3.595947265625f, 30f);     // free, overview
    private static readonly Vector3 ExpBram = new(64f, 4.0675f, 132.32f);         // house huddle, fine tile
    private static readonly Vector3 ExpCleo = new(263f, 4.875f, -100f);           // journey, overview
    private const float ExpAdaHeight = 1.60f, ExpBramHeight = 1.80f, ExpCleoHeight = 1.70f;
    private static readonly Vector3 ExpAdaHalfway = new(-45f, 3.68316650390625f, 30f);
    private static readonly Vector3 ExpCleoHalfway = new(259.5f, 4.875f, -100f);
    private static readonly Vector3 ExpAdaEnd = new(-40f, 3.7705078125f, 30f);
    private const string IdleUrl = "/assets/animation-clips/stand-relaxed.fbx?v=fixturestand0001";
    private const string WalkUrl = "/assets/animation-clips/walk.fbx?v=fixturewalk00001";
    private const string AdaUrl = "/characters/Ada%20Wren/model3d/file?v=fixtureada000001";

    public static async Task<int> RunAsync(Node3D host, string? only = null)
    {
        try
        {
            var dir = Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures");
            MeshoptNative.EnsureLoaded(ProjectSettings.GlobalizePath("res://bin"));
            if (only == "verify")
            {
                var alone = await VerifyCheck.RunAsync(host, dir);
                GD.Print($"CHECK ok {alone}");
                return 0;
            }
            if (only == "storeys")
            {
                var alone = await StoreysCheck.RunAsync(host, dir);
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
            Eq("overview_vertices", stats.OverviewVertices, ExpOverviewVertices);
            Eq("overview_triangles", stats.OverviewTriangles, ExpOverviewTriangles);
            Eq("tiles", stats.Tiles, ExpTiles);
            Eq("tile_vertices", stats.TileVertices, ExpTileVertices);
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
            var figures = await CheckFigures(world, source, builder.Height!);
            var bench = BenchMathCheck.Run(source);
            var scatter = await ScatterCheck.RunAsync(world, source, builder.Height!, dir);
            var hud = HudCheck.Run(source);
            var ground = await GroundCheck.RunAsync(world, source, builder, stats, dir);
            var s3c = await S3cCheck.RunAsync(host, dir);
            var launcher = LauncherCheck.Run();
            var overview = OverviewCheck.Run(host, builder.FirstMap!.Value, builder.Height!);
            var pick = await PickCheck.RunAsync(host, world, builder, dir);
            var labels = await LabelCheck.RunAsync(host, world, builder, dir);
            var sync = await SyncCheck.RunAsync(source, probe, dir);
            var verify = await VerifyCheck.RunAsync(host, dir);
            var storeys = await StoreysCheck.RunAsync(host, dir);

            GD.Print($"CHECK ok terrain_vertices={stats.TerrainVertices} tiles={stats.Tiles} buildings={stats.Buildings} "
                     + $"primitives={stats.Primitives} skipped={stats.Skipped} | {stats.Summary()} plate_area={area:0.###} "
                     + $"| meshopt {meshopt} | {figures} | bench {bench} | scatter {scatter} | hud {hud} | {ground} | {s3c} | {launcher} | {overview} | {pick} | {labels} | {sync} | {verify} | {storeys}");
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
    /// Figures (Task S1b), two polls. Poll 1: three characters (free GLB,
    /// FBX in a location huddle, model-less traveller); poll 2: one moved and
    /// re-signed, one vanished, one further along its route.
    /// </summary>
    private static async Task<string> CheckFigures(Node3D world, FixtureSource source, WorldHeight height)
    {
        var mgr = new FigureManager(source, height, line => GD.Print("[check] " + line), strict: true) { AutoTick = false, PollSeconds = 5.0 };   // the README derivation lerps over 5 s
        world.AddChild(mgr);
        await mgr.InitAsync();
        Expect("idle role → mapped kind", mgr.Clips.KindOf("idle") == "stand-relaxed", mgr.Clips.KindOf("idle"));
        Expect("run role keeps its name", mgr.Clips.KindOf("run") == "run", mgr.Clips.KindOf("run"));
        using (var map = Load("worldmap.json")) await mgr.Apply(map.RootElement);
        var st = mgr.Stats;
        Eq("figures", st.Figures, ExpFigures);
        Eq("glb_figures", st.GlbFigures, ExpGlbFigures);
        Eq("placeholders", st.Placeholders, ExpPlaceholders);
        Eq("clips_loaded", st.ClipsLoaded, ExpClipsLoaded);
        Eq("bound_tracks", st.BoundTracks, ExpBoundTracks);
        Eq("unbound_clips", st.UnboundClips, 0);
        Eq("offmap", st.Offmap, 0);
        Eq("model_failures", st.ModelFailures, 0);
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
        Expect("Ada is GLB", ada.IsGlb && !bram.IsGlb && !cleo.IsGlb, "body kinds");
        Near("Ada height", ModelPlacement.Measure(ada.Body!, Transform3D.Identity).Size.Y, ExpAdaHeight);
        Near("Bram height", ModelPlacement.Measure(bram.Body!, Transform3D.Identity).Size.Y, ExpBramHeight);
        Near("Cleo height", ModelPlacement.Measure(cleo.Body!, Transform3D.Identity).Size.Y, ExpCleoHeight);

        // Clip cache: one download per clip URL, the FBX model is never fetched.
        Eq("idle downloads", source.ByteRequests.Count(u => u == IdleUrl), 1);
        Eq("walk downloads", source.ByteRequests.Count(u => u == WalkUrl), 1);
        Expect("FBX model not fetched", !source.ByteRequests.Any(u => u.Contains("Bram", StringComparison.Ordinal)),
               string.Join(";", source.ByteRequests));

        // The binding itself: after one evaluation the skeleton holds the clip's values.
        CheckBinding(mgr, ada, "idle");
        // The rest correction against the browser's own numbers (rest_reference.json).
        var restInfo = CheckRestReference(mgr, ada, source);
        ada.UpdateClip();

        // ---- poll 2 ----
        using (var map = Load("worldmap_poll2.json")) await mgr.Apply(map.RootElement);
        st = mgr.Stats;
        Eq("poll2 figures", st.Figures, 2);
        Expect("Bram removed", !mgr.Figures.ContainsKey(Bram), "still there");
        Eq("Ada model3d requests (model_sig changed)", source.ModelRequests.Count(n => n == Ada), 2);
        Eq("Ada GLB downloads (same URL, cached)", source.ByteRequests.Count(u => u == AdaUrl), 1);
        Eq("Cleo model3d requests (sig absent, unchanged)", source.ModelRequests.Count(n => n == Cleo), 1);
        Eq("clips still loaded once", source.ByteRequests.Count(u => u == IdleUrl || u == WalkUrl), 2);
        Eq("poll2 bound_tracks", st.BoundTracks, ExpBoundTracks);
        Expect("Ada reloaded", ada.LoadedSig == "ada-2" && ada.IsGlb, ada.LoadedSig ?? "null");
        Expect("Ada walks (2 m/s)", ada.Moving && ada.Player?.CurrentAnimation == "walk",
               $"{ada.PlannedSpeed} {ada.Player?.CurrentAnimation}");
        Near("Ada faces +x", ada.Rotation.Y, Mathf.Pi / 2f);
        NearV("Ada still at the old point", ada.Position, ExpAda);
        mgr.Tick(2.5);
        NearV("Ada halfway", ada.Position, ExpAdaHalfway);
        NearV("Cleo halfway", cleo.Position, ExpCleoHalfway);
        mgr.Tick(2.5);
        NearV("Ada arrived", ada.Position, ExpAdaEnd);
        Expect("Ada idles after arriving", !ada.Moving && ada.Player?.CurrentAnimation == "idle",
               ada.Player?.CurrentAnimation ?? "no player");

        var info = RestMismatch(source, ada);
        mgr.QueueFree();
        return $"figures {poll1} | poll2 figures={st.Figures} glb_figures={st.GlbFigures} placeholders={st.Placeholders} "
               + $"model_loads={st.ModelLoads} | {restInfo} | {info}";
    }

    /// <summary>
    /// Evaluate the clip once and read the skeleton back: a moving bone holds
    /// the clip's key 0 verbatim, a bone Godot left without a track holds the
    /// clip's node default (the restored constant), the hips are in place at
    /// the scaled height.
    /// </summary>
    private static void CheckBinding(FigureManager mgr, Figure fig, string role)
    {
        var player = fig.Player ?? throw new InvalidOperationException("no AnimationPlayer");
        var skel = fig.Skeleton ?? throw new InvalidOperationException("no skeleton");
        var clip = mgr.Clips.ByRole[role]!;
        Expect($"{role} playing", player.CurrentAnimation == role, player.CurrentAnimation);
        player.Seek(0, true);

        void SameRot(string bone, Quaternion want)
        {
            int i = skel.FindBone(bone);
            Expect($"{bone} on skeleton", i >= 0, "missing");
            var got = skel.GetBonePoseRotation(i);
            Expect($"{role} {bone} rotation", got.IsEqualApprox(want) || got.IsEqualApprox(-want), $"{got} vs {want}");
        }
        string moving = "mixamorig_LeftUpLeg", constant = "mixamorig_LeftForeArm";
        Expect("LeftUpLeg has a track", clip.RotationTracks.ContainsKey(moving), "no track");
        Expect("LeftForeArm has none (constant in the file)", !clip.RotationTracks.ContainsKey(constant), "has a track");
        // Both are rest-corrected (q = K_p⁻¹·c·K_b) with this skeleton's factors.
        var fixes = RestCorrections.Build(mgr.Clips.DonorRest!, (Node3D)skel.GetParent().GetParent(), skel);
        Quaternion Fixed(string bone, Quaternion c)
            => fixes.TryGetValue(ClipLibrary.NormBone(bone), out var f) ? RestCorrections.Apply(f, c).Normalized() : c;
        SameRot(moving, Fixed(moving, clip.Anim.TrackGetKeyValue(clip.RotationTracks[moving], 0).AsQuaternion()));
        SameRot(constant, Fixed(constant, clip.RestRotations[Array.IndexOf(clip.Bones, constant)]));

        int h = skel.FindBone("mixamorig_Hips");
        var rest = skel.GetBoneRest(h).Origin;
        var pose = skel.GetBonePosePosition(h);
        double refY = mgr.Clips.StandingHipsY(clip);
        double y0 = Math.Abs(clip.Anim.TrackGetKeyValue(clip.PositionTracks["mixamorig_Hips"], 0).AsVector3().Y);
        Near("hips x in place", pose.X, rest.X, 1e-5f);
        Near("hips z in place", pose.Z, rest.Z, 1e-5f);
        Near("hips y = y0 · rest/ref", pose.Y, (float)(y0 * rest.Y / refY), 1e-5f);
    }

    /// <summary>
    /// The rest-pose correction against the BROWSER'S OWN function:
    /// <c>native/fixtures/rest_reference.json</c> is written by
    /// <c>native/fixtures/rest_reference.mjs</c>, which runs
    /// <c>restCorrections</c>/<c>bindRelativeValues</c> of
    /// packages/scene-render/src/clipRetarget.ts on three's loaders with the same
    /// files. Three tracked demo rigs: Minerva (= Ada; no stance rule), Johanna
    /// (leg stance), Hagrid (torso + foot stance). Per model: the corrected-bone
    /// count and the stance bones must match; per clip/time/bone the clip value
    /// (importer agreement) and the corrected rotation must lie within 0.5°.
    /// For Ada the corrected rotations are also read back off her skeleton after
    /// the AnimationPlayer evaluated the bound clip (end to end).
    /// </summary>
    private static string CheckRestReference(FigureManager mgr, Figure ada, FixtureSource source)
    {
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
                var fixes = RestCorrections.Build(donor, root, skel, stanceBones: stance);
                Eq($"{name} corrected bones", fixes.Count, model.GetProperty("corrected_bones").GetInt32());
                var wantStance = model.GetProperty("stance_bones").EnumerateArray().Select(e => e.GetString()!).ToHashSet();
                Expect($"{name} stance bones", stance.SetEquals(wantStance),
                       $"got [{string.Join(",", stance.OrderBy(x => x))}], browser [{string.Join(",", wantStance.OrderBy(x => x))}]");
                foreach (var sample in model.GetProperty("samples").EnumerateArray())
                {
                    var role = sample.GetProperty("clip").GetString() == "idle" ? "idle" : "walk";
                    var clip = mgr.Clips.ByRole[role]!;
                    double t = sample.GetProperty("time").GetDouble();
                    foreach (var bone in sample.GetProperty("bones").EnumerateObject())
                    {
                        var c = Sample(clip, bone.Name, t);
                        double dc = Deg(c, Q(bone.Value.GetProperty("clip")));
                        var key = ClipLibrary.NormBone(bone.Name);
                        var q = fixes.TryGetValue(key, out var f) ? RestCorrections.Apply(f, c) : c;
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
            var role = sample.GetProperty("clip").GetString() == "idle" ? "idle" : "walk";
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
        return $"rest_reference models={models} compared={compared} max_clip_dev={maxClip:0.####}° "
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

    /// <summary>The far-view placement rule on its own: offmap, fogged route, huddle rows, ring, yaw.</summary>
    private static void CheckPlacementRule()
    {
        var house = new MapPlace("h", 10, 20, 90, 10, IsBuilding: true);
        var meadow = new MapPlace("m", -5, 5, 0, 30, IsBuilding: false);
        var placed = new Dictionary<string, MapPlace> { ["h"] = house, ["m"] = meadow };
        var rows = new List<CharacterRow>
        {
            new("Zed", "h", null, null, null, null, null),
            new("Amy", "h", null, null, null, null, null),
            new("Mo", "m", 1, 1, null, null, null),
            new("Nob", "", null, null, null, null, null),                                  // offmap
            new("Fog", "", 7, 8, null, null, new TravelInfo(null, null)),                // withheld route → pos
            new("Dot", "", null, null, null, null, new TravelInfo(new() { (1, 1) }, 0)),  // degenerate, no pos → offmap
            new("Run", "", 0, 0, null, null, new TravelInfo(new() { (0, 0), (3, 4) }, 99)), // clamped to the end
        };
        var spots = FigurePlacement.Resolve(rows, placed);
        Expect("offmap", !spots.ContainsKey("Nob") && !spots.ContainsKey("Dot"), string.Join(",", spots.Keys));
        Expect("fog → pos", spots["Fog"] is { X: 7, Z: 8, Rule: "journey-pos" }, $"{spots["Fog"]}");
        Expect("route end", spots["Run"] is { X: 3, Z: 4, Rule: "journey" }, $"{spots["Run"]}");
        // House, yaw 90°: Amy (i=0 of 2) local (−1.15, 3.6) → world (10 + 3.6, 20 + 1.15); Zed (1.15, 3.6) → (13.6, 18.85).
        NearXZ("Amy huddle", spots["Amy"], 13.6, 21.15);
        NearXZ("Zed huddle", spots["Zed"], 13.6, 18.85);
        // Meadow ring, one character, angle 0 → (−5 + 2.6, 5); its own pos is ignored (tile wins).
        NearXZ("Mo ring", spots["Mo"], -2.4, 5);
    }

    private static JsonDocument Load(string file)
        => JsonDocument.Parse(File.ReadAllBytes(Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures", file)));

    private static void NearV(string what, Vector3 got, Vector3 want, float eps = 1e-3f)
        => Expect(what, got.DistanceTo(want) <= eps, $"got {got}, expected {want}");

    private static void NearXZ(string what, FigureSpot got, double x, double z)
        => Expect(what, Math.Abs(got.X - x) < 1e-6 && Math.Abs(got.Z - z) < 1e-6, $"got ({got.X}, {got.Z}), expected ({x}, {z})");

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
