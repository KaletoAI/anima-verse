using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Bench;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Sync;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>Main, world build: the start with its six boot stages, the loading screen, the bench and offline runs.</summary>
public partial class Main : Node3D
{
    /// <summary>
    /// The start, reported in the browser's six boot stages (game/boot.ts) — native points:
    ///   world   — heightfield + worldmap + <c>/world/locations?view=3d</c> are in (retried with the title's note);
    ///   scenes  — every scene recipe of the start ring is fetched;
    ///   tiles   — the start ring's locations and the world props stand;
    ///   visible — the first frame after the world is in the tree and the camera framed it (note "characters");
    ///   figures — the first map's figures and the model loads they started are through;
    ///   arrival — the boot is done (no embodied take-over in this client yet, so nothing more to wait for).
    /// </summary>
    private async Task LoadWorldAsync()
    {
        SetStatus("Loading world…");
        var boot = _boot = new BootTracker(() => Time.GetTicksMsec());
        boot.Changed += PublishBoot;
        PublishBoot();
        try
        {
            MeshoptNative.EnsureLoaded(ProjectSettings.GlobalizePath("res://bin"));
            // A new world: the veil starts from "nothing explored" with nothing bound (its module state).
            VeilUniforms.Reset();
            HemiUniforms.Reset();
            var world = new Node3D { Name = "World" };
            AddChild(world);
            var builder = _builder = new WorldBuilder(_source!, Log, strict: false)
            {
                PlainGround = _options!.PlainGround,
                NoWater = _options.NoWater,
                VerifyFull = _options.Verify,
            };
            // The details go through the conditional cache from the start, so the first re-sync is a 304.
            var source = _source!;
            var api = _api;
            _locCache = new LocationsCache(api is not null
                ? api.GetLocations3dConditionalAsync
                : async _ =>
                {
                    using var doc = await source.GetLocations3dAsync();
                    return new ConditionalAnswer(200, "", doc.RootElement.Clone());
                });
            var cache = _locCache;
            var hooks = new WorldBuilder.BuildHooks
            {
                Stage = boot.Report,
                Bootstrap = fetch => BootRetry.RunAsync(fetch, AnimaApi.IsAuthError,
                    seconds => boot.SetNote(BootNote.Retry(seconds)), () => boot.SetNote(null),
                    ms => Task.Delay(TimeSpan.FromMilliseconds(ms), _stop.Token),
                    (line, e) => Log($"boot: world data {line}: {e.Message}")),
                Locations3d = async () => (await cache.GetAsync()).Root,
                // main.ts `api.getWorldMap(showAll)`: the stored start view (ReadStoredStart), online only.
                WorldMap = api is not null ? () => api.GetWorldMapAsync(_showAll) : null,
            };
            var stats = await builder.BuildAsync(world, _options!.Goto, hooks);
            Anchor = stats.Anchor;
            // The terrain streaming (Task 24): the anchor follows the camera target, the poll's signatures reload.
            var firstMap = builder.FirstMap!.Value;
            _streamer = new TerrainStreamer(builder, _source!, () => _camera!.Target, Log,
                                            World.Json.Str(firstMap, "height_sig"), World.Json.Str(firstMap, "terrain_sig"),
                                            stats.Anchor.X, stats.Anchor.Z, water: !_options.NoWater && !_options.PlainGround);
            world.AddChild(_streamer);
            // main.ts takeGameHour(): the world clock of the freshest map drives the night gate (every 60 s, below).
            TakeGameHour(builder.FirstMap!.Value);
            // main.ts `void syncExplored(firstMap)`: the veil's memory on its own signature.
            StartVeil(builder.FirstMap!.Value);
            _interactive = !_options.Bench && _options.Offline is null;
            _picking = new LocationPicking(builder);
            // main.ts: the avatar's location is the open one from the first mount on.
            if (stats.OpenLocation.Length > 0) _openView.TryOpen(stats.OpenLocation, true, out _);
            RefreshOpenBadge();
            _pins = new EventPins();
            world.AddChild(_pins);
            _pins.Update(builder.FirstMap!.Value, PlaceOf);
            _world = world;
            // main.ts takeBackdrop(firstMap): the mountain rings of § A17, then every poll below.
            TakeBackdrop(world, builder.FirstMap!.Value);
            // The CSS2D label layer: location names now, name tags once the figures are there. Under the HUD (layer 5).
            _placeLabels = new LocationLabels();
            SyncPlaceLabels();
            var labelsLayer = new CanvasLayer { Name = "Labels", Layer = 1 };
            AddChild(labelsLayer);
            _labelOverlay = new LabelOverlay { Camera = _camera };
            var placeLabels = _placeLabels;
            // `tile.labelObj.visible = tile.group.visible`: a neighbour the occlusion has hidden takes its name along.
            _labelOverlay.Sources.Add(() => placeLabels.Visible(id => OccludedPlace(id) ? null : PlaceOf(id)));
            // The room names of an open interior (mountShell step 16), and the in-world storey switch over them.
            _labelOverlay.Sources.Add(builder.VisibleRoomLabels);
            labelsLayer.AddChild(_labelOverlay);
            labelsLayer.AddChild(new LevelSwitchOverlay { Camera = _camera, Builder = builder });
            _avatarRoom = AvatarRoomOf(builder.FirstMap!.Value);
            if (_options.Bench || _options.Offline is not null)
            {
                // The measuring runs keep the spike's start: the target on the anchor, where the scatter window
                // settles before the drive (the drive itself sets the camera every frame, BenchRunner).
                _camera!.JumpTo(stats.Anchor.Position() + new Vector3(0, 1.5f, 0), 40);
            }
            else
            {
                // main.ts boot framing: the world_bounds centre on the ground, at the fit distance.
                _camera!.FrameWorld(OverviewControl.WorldBoundsOf(builder.FirstMap!.Value), builder.Height!.GroundAt);
            }
            Log("world " + stats.Summary());
            var worldStatus = $"{stats.Buildings} buildings, {stats.Tiles} tiles, {stats.Primitives} primitives"
                              + (stats.Failures > 0 ? $", {stats.Failures} locations failed (see log)" : "")
                              + (stats.Ground.Mode == "layers" ? $", ground {stats.Ground.Layers} layers / {stats.Ground.TexturesLoaded} textures"
                                                                : ", plain ground");
            _groundSummary = stats.Ground.Summary();
            _waterSummary = stats.WaterSummary();
            _waterDrawn = stats.WaterMode == "drawn";
            SetStatus(worldStatus + "   —   loading figures…");

            if (_options.Scatter)
            {
                // --scatter: the authored scatter AND the undergrowth (Task S3), anchored on the camera target.
                SetStatus(worldStatus + "   —   loading scatter…");
                var cam = _camera!;
                _scatter = await ScatterLayer.CreateAsync(_source!, builder.Height!, builder.FirstMap!.Value,
                                                          () => cam.Target, Log);
                if (_scatterPrefs != ScatterPrefs.Defaults) _scatter.Field.SetLod(ScatterPrefs.LodCfgOf(_scatterPrefs));
                world.AddChild(_scatter);
                _streamer.Scatter = _scatter;
            }

            // visible: the world stands and the camera looks at it — the next drawn frame shows it.
            boot.SetNote(BootNote.Characters);
            await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
            boot.Report("visible");

            _figures = new FigureManager(_source!, builder.Height!, Log, strict: false)
            {
                // main.ts setTerrainMove + setGroundHeight: the ground word and the height sampler every figure walks on.
                GroundMoveAt = builder.FigureGroundMove,
                GroundYAt = builder.FigureGroundY,
                // npcs.setPlaceAt / setRoomStandAt: a pair's seat height and its room's stand (§ A8a).
                SeatYAt = builder.PairSeatY,
                RoomStandAt = builder.PairRoomStandY,
                // npcs.tickFigureTiers(camera.position) and setModelFocus (distance² to engine.target), main.ts.
                CameraPosition = () => _camera is { } c && IsInstanceValid(c) ? c.GlobalPosition : null,
                FocusTarget = () => _camera is { } c && IsInstanceValid(c) ? c.Target : null,
                // Task 29: the room placement reads every mounted location's view state and stands.
                Slots = () => builder.Slots,
                CamDist = () => _camera is { } c && IsInstanceValid(c) ? c.Distance : FigureManager.DefaultCamDist,
            };
            world.AddChild(_figures);
            var tags = _tags = new NameTags(_figures, () => Time.GetTicksMsec()) { CamDist = () => _camera?.Distance ?? 0 };
            _labelOverlay.Sources.Add(tags.Visible);
            _figures.Polled += () =>
            {
                if (_figures.LatestMap is not { } polled) return;
                // applyWorldMap → updatePins(map), every poll; npcs.update → the tags' texts; the place labels follow.
                if (_pins is not null && IsInstanceValid(_pins)) _pins.Update(polled, PlaceOf);
                _avatarRoom = AvatarRoomOf(polled);
                tags.Apply(polled);
                SyncPlaceLabels();
                TakeBackdrop(world, polled);
            };
            await _figures.InitAsync();
            // The boot's own map places the first figures (main.ts npcs.update(firstMap)); the poll takes over.
            _figures.ApplyPolled(builder.FirstMap!.Value);
            StartSync();
            // main.ts `setInterval(takeGameHour, 60_000)`: the clock is re-read from the latest polled map.
            var clock = new Godot.Timer { Name = "GameHour", WaitTime = GameHourIntervalS, Autostart = true };
            clock.Timeout += () => TakeGameHour(_figures?.LatestMap ?? builder.FirstMap!.Value);
            AddChild(clock);
            if (_interactive)
            {
                // main.ts `setInterval(requestServerModels, 60_000)`: the scene sweep remounts a location whose signature moved.
                var sweep = new Godot.Timer { Name = "SceneSweep", WaitTime = WorldBuilder.SweepIntervalS, Autostart = true };
                AddChild(sweep);
                sweep.Timeout += () => _ = SweepScenesAsync(builder);
            }
            var timer = new Godot.Timer { WaitTime = 1.0, Autostart = true };
            AddChild(timer);
            timer.Timeout += () =>
            {
                SetStatus($"{worldStatus}, {FigureLine()}"
                          + (_labelOverlay is { } lo && IsInstanceValid(lo)
                              ? $", {lo.LastShown} labels ({lo.LastCollectMs + lo.LastDrawMs:0.00} ms)" : "")
                          + (_scatter is not null ? $"\n{_scatter.Summary()}" : "")
                          + $"\n{SyncLine()}"
                          + (_hud?.Active == true
                              ? "   —   " + CameraHint + ", click a figure: plaque, F/Enter: chat, M: menu"
                              : "   —   " + CameraHint));
            };
            await _figures.FirstPollDone;
            boot.Report("figures");
            boot.SetNote(null);
            boot.Report("arrival");
            Log("boot stages: " + boot.Describe());

            if (_options.Fly is { } fly && !_options.Bench) await FlyAsync(fly.Distance, fly.HeadingDeg);
            if (_options.Offline is not null && !_options.Bench)
            {
                if (_scatter is not null)
                {
                    await ScatterSettled(_scatter);
                    // One more LOD pass after the meshes landed (the browser's 1 Hz tick), so the line counts what is drawn.
                    int passes = _scatter.LodPasses;
                    ulong t0 = Time.GetTicksMsec();
                    while (_scatter.LodPasses <= passes && Time.GetTicksMsec() - t0 < 3000)
                        await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
                }
                Log("offline world " + stats.Summary());
                if (_scatter is not null) Log("offline scatter " + _scatter.Summary() + " " + _scatter.Digest());
                Log("offline figures " + FigureLine());
                foreach (var f in _figures!.Ordered()) Log("offline " + FigureDetail(f));
                // Task 29: every location with figures once OPEN (fade 1, storey 0) and once closed — where the room
                // ladder puts them (seat, pool, corridor, pos, centre, tile = huddle) and who hides.
                foreach (var (id, slot) in builder.Slots.OrderBy(kv => kv.Key, StringComparer.Ordinal))
                {
                    double was = slot.Fade.Fade;
                    slot.Fade.Snap(1);
                    _figures.TickPlacement();
                    string open = _figures.Census(id);
                    slot.Fade.Snap(0);
                    _figures.TickPlacement();
                    string closed = _figures.Census(id);
                    slot.Fade.Snap(was);
                    if (!open.StartsWith("figures=0", StringComparison.Ordinal))
                        Log($"offline placement {id} ({slot.Loc.Name}) open[{open}] closed[{closed}]");
                }
                _figures.TickPlacement();
                // Task 30: the NPC walk on this world's data — two synthetic polls (open ground, a room change).
                OfflineWalkProbe(builder);
                Log($"offline memory static {Performance.GetMonitor(Performance.Monitor.MemoryStatic) / 1048576.0:0} MiB, "
                    + $"library {_figures.Clips.SourceKeys} source keys, figure templates "
                    + $"{_figures.TemplateKeys} keys ≈{_figures.TemplateKeys * FigureManager.KeyBytes / 1048576.0:0} MiB in {_figures.TemplateCount} templates");
                if (_streamer is not null) Log("offline " + _streamer.Summary());
                Log("offline " + VeilUniforms.Summary());
                foreach (var line in ShaderSafety.Lines) Log("offline " + line);
                GetTree().Quit(0);
                return;
            }
            if (_options.Bench)
            {
                if (_scatter is not null) await ScatterSettled(_scatter);
                if (_options.BenchMatrix is not null) await RunBenchMatrixAsync(builder);
                else StartBench(builder);
            }
        }
        catch (Exception e)
        {
            if (_stop.IsCancellationRequested || Leaving) return;   // back to the title / a lost session: the scene is gone
            if (AnimaApi.IsAuthError(e)) return;   // the session died: OnUnauthorized brings the login back
            GD.PrintErr($"[native] world load failed: {e}");
            SetStatus("World load failed: " + e.Message);
            boot.SetNote(BootNote.Failed);
            if ((_options!.Bench && _options.QuitAfterBench) || _options.Offline is not null) GetTree().Quit(1);
        }
    }

    /// <summary><c>--fly</c>: the camera target's speed along the line (m/s) and the camera distance while flying (m).</summary>
    public const double FlySpeedMps = 50, FlyCameraDistM = 80;

    /// <summary>
    /// <c>--fly=M[,DEG]</c>: the streaming sanity drive — the camera target flies <paramref name="distance"/> metres in a
    /// straight line from where it stands (heading 0° = +x, 90° = +z) at <see cref="FlySpeedMps"/>, on the ground, at
    /// <see cref="FlyCameraDistM"/>; then the stream settles (idle for 2 s, at most 60 s). Logs the probe (longest frame,
    /// longest frame while streaming), the tiles taken / evicted and the builds.
    /// </summary>
    private async Task FlyAsync(double distance, double headingDeg)
    {
        if (_camera is not { } cam || _builder?.Height is not { } height || _streamer is not { } st) return;
        var start = cam.Target;
        double rad = headingDeg * Math.PI / 180;
        var dir = new Vector3((float)Math.Cos(rad), 0, (float)Math.Sin(rad));
        st.Probe.Reset();
        int taken0 = st.Stream.Counters.TilesTaken, evicted0 = st.Stream.Counters.TilesEvicted, builds0 = st.FieldBuilds;
        Log($"fly: {distance:0} m at {FlySpeedMps} m/s, heading {headingDeg:0.#}°, from ({start.X:0.#}, {start.Z:0.#})");
        ulong last = Time.GetTicksUsec();
        double t = 0;
        while (true)
        {
            await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
            ulong now = Time.GetTicksUsec();
            t += (now - last) / 1e6;
            last = now;
            double d = Math.Min(distance, FlySpeedMps * t);
            var p = start + dir * (float)d;
            p.Y = (float)height.GroundAt(p.X, p.Z);
            cam.JumpTo(p, FlyCameraDistM);
            if (d >= distance) break;
        }
        double flewS = t;
        await st.SettleAsync(maxSeconds: 60, quietSeconds: 2);
        var end = cam.Target;
        Log($"fly done in {flewS:0.0} s (+ settle): to ({end.X:0.#}, {end.Z:0.#}); tiles taken {st.Stream.Counters.TilesTaken - taken0}, "
            + $"evicted {st.Stream.Counters.TilesEvicted - evicted0}, held {height.Tiles.Count}; field builds {st.FieldBuilds - builds0}; "
            + $"frames {st.Probe.Frames}, max frame {st.Probe.MaxMs:0.##} ms, max while streaming {st.Probe.StreamMaxMs:0.##} ms "
            + $"over {st.Probe.StreamFrames} frames; ground under the target {height.GroundAt(end.X, end.Z):0.###} m "
            + $"(fine tile {(height.HasTile(height.TileKeyAt(end.X, end.Z)) ? "held" : "MISSING")})");
        Log("fly " + st.Summary());
        if (_scatter is not null)
        {
            await ScatterSettled(_scatter);
            Log("fly scatter " + _scatter.Summary() + " " + _scatter.Digest());
        }
        if (_builder.Terrain is { } terrain) Log("fly " + terrain.Summary());
        if (_builder.Ground is { } g) Log("fly " + g.Stats.Summary());
    }

    /// <summary>One scene sweep (<see cref="WorldBuilder.SweepAsync"/>); never fatal — a failure waits for the next one.</summary>
    private async Task SweepScenesAsync(WorldBuilder builder)
    {
        try
        {
            var remounted = await builder.SweepAsync(() => !_stop.IsCancellationRequested && !Leaving);
            if (remounted.Count > 0) SyncPlaceLabels();
        }
        catch (Exception e)
        {
            if (_stop.IsCancellationRequested || Leaving) return;
            Log($"scene sweep failed: {e.Message}");
        }
    }

    /// <summary>The boot state → the HUD (<c>boot</c> message) and the loading screen; the screen fades at <c>visible</c>.</summary>
    private void PublishBoot()
    {
        if (_boot is null) return;
        _hud?.SetBoot(_boot.ToHud());
        if (_loading is not { } screen || !IsInstanceValid(screen)) return;
        var progress = _boot.Progress;
        var note = _boot.Note;
        bool failed = note?.Kind == "failed";
        screen.ShowBoot(progress.Percent, BootTracker.StageText(progress.Label),
                        note is null ? null : BootTracker.NoteText(note), failed);
        if (!failed && _boot.Done.Contains("visible"))
        {
            var layer = _loadingLayer;
            screen.FadeOut(0.9, () =>
            {
                if (layer is not null && IsInstanceValid(layer)) layer.QueueFree();
                _loading = null;
                _loadingLayer = null;
            });
        }
    }

    /// <summary>
    /// The bench run: anchor from the CURRENT worldmap snapshot (latest poll,
    /// else the build's), frozen here; the embedded path; result → stdout line,
    /// <c>user://</c> file, on-screen panel; <c>--quit-after-bench</c> exits.
    /// </summary>
    private void StartBench(WorldBuilder builder)
    {
        var settings = BenchRunner.SettingsFor(_figures!.LatestMap ?? builder.FirstMap!.Value, builder,
                                               _options!.Goto, _options.Vsync, scatter: _scatter is not null,
                                               water: _waterDrawn);
        Log($"bench starts ({settings.Path.Keyframes.Length} keyframes)");
        builder.Terrain?.ResetPeak();
        _streamer?.Probe.Reset();
        AddChild(new BenchRunner(_camera!, settings, result =>
        {
            AddBenchExtras(result, builder);
            var file = BenchOutput.Emit(result);
            BenchOutput.ShowPanel(this, result, file);
            _ = ReportBench(BenchOutput.Line(result));
        }));
    }

    /// <summary>The native extra keys after the browser's, in this order (every bench result, single run or matrix pass).</summary>
    private void AddBenchExtras(JsonObject result, WorldBuilder builder)
    {
        if (_scatter is not null)
        {
            // Extra key after the browser's: what both scatter layers drew at the end of the drive.
            result["scatterLayers"] = _scatter.Summary();
            Log("bench scatter " + _scatter.Summary());
        }
        // Extra key (Task S3b): which ground material the run drew — "layers" (the browser's) or "plain".
        result["ground"] = _groundSummary;
        // Extra key (Task S3c): what the world showed — water, recipe primitives, models.
        result["water"] = _waterSummary;
        // Extra key (Task 23): the CDLOD terrain over the drive — the last frame, the largest one, the viewport.
        result["terrain"] = builder.Terrain?.Summary() ?? "terrain[none]";
        // Extra keys (Task 24): the streaming probe over the drive (the longest frame while the terrain streamed).
        if (_streamer is { } st)
        {
            st.AddBenchKeys(result);
            Log($"bench stream: max frame while streaming {st.Probe.StreamMaxMs:0.##} ms over {st.Probe.StreamFrames} frames; {st.Summary()}");
        }
        // Extra key (Task 26c): what the shadow pass draws at the drive's last pose (CPU census, the requested aspect).
        if (_stage is not null && _camera is not null)
        {
            var size = _options!.Size ?? (Vector2I)GetViewport().GetVisibleRect().Size;
            double aspect = size.Y > 0 ? (double)size.X / size.Y : 16.0 / 9.0;
            string census = Bench.ShadowCensus.Summary(Bench.ShadowCensus.Count(this, _camera, _stage.Sun, aspect));
            if (_shadowGate is { } gate)
                census += $" gate[registered={gate.Registered} inside={gate.Inside} passes={gate.Passes} last_ms={gate.LastPassMs:0.###}"
                          + $"{(gate.Off ? " off" : "")}]";
            result["shadowCasters"] = census;
            Log("bench " + census);
        }
    }

    /// <summary>Sends the result to the server's bench log, then honours <c>--quit-after-bench</c>.</summary>
    private async Task ReportBench(string line)
    {
        if (_api is null)
        {
            if (_options!.QuitAfterBench || _options.Offline is not null) GetTree().Quit(0);
            return;
        }
        try
        {
            await _api!.PostBenchResultAsync(line);
            Log("bench result sent to the server (logs/bench.jsonl)");
        }
        catch (Exception e)
        {
            Log("bench result NOT sent to the server: " + e.Message);
        }
        if (_options!.QuitAfterBench) GetTree().Quit(0);
    }

    /// <summary>
    /// Before the drive: the prop meshes of the start window have landed and the clearance re-sample is
    /// done (at most 60 s; a load that never finishes is logged and the run starts anyway). The browser
    /// starts after boot/arrival with its downloads still running; the warm-up then absorbs them.
    /// </summary>
    private async Task ScatterSettled(ScatterLayer layer)
    {
        ulong start = Time.GetTicksMsec();
        do
        {
            await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
        } while (layer.Busy && Time.GetTicksMsec() - start < 60000);
        Log($"scatter settled after {(Time.GetTicksMsec() - start) / 1000.0:0.0} s: {layer.Summary()}");
    }

    private string FigureLine()
    {
        var s = _figures!.Stats;
        // The underwater ghosts standing now (Task 25): figures whose bed is under a mirror, and their cut heights.
        var wading = _figures.Figures.Values.Where(f => f.Ghost is { Visible: true }).ToList();
        return $"{s.Figures} figures ({s.GlbFigures} models, {s.Placeholders} placeholders), "
               + $"{s.ClipsLoaded} clips" + (s.UnboundClips > 0 ? $", {s.UnboundClips} unbound" : "")
               + $", {wading.Count} in water"
               + (wading.Count > 0 ? $" [{string.Join(", ", wading.Select(f => $"{f.CharacterName} bed {f.Position.Y:0.##} cut {f.Ghost!.CutY:0.##}"))}]" : "");
    }

    /// <summary>One figure for the offline log: body, actions, set chain, what it asks for and what plays, tier, clip memory.</summary>
    private static string FigureDetail(Figure f)
        => $"figure {f.CharacterName}: {(f.IsGlb ? "model" : "placeholder")}, {f.ClipKinds.Count} actions, sets [{string.Join(",", f.Sets)}], "
           + $"activity '{f.Activity}' → asks '{f.CurrentKind}' plays '{f.CurrentClip}' pace {f.CurrentPace:0.##}, "
           + $"tier {f.LoadedTier}, {f.ClipKeys} clip keys, {f.ClipBytes / 1048576.0:0.0} MiB";

    /// <summary>The overview camera's bindings (engine.ts), for the status line.</summary>
    private const string CameraHint = "drag: pan, right/middle or Shift+drag: orbit, wheel: zoom, WASD/arrows: move, Q/E: turn, +/-: zoom";
}
