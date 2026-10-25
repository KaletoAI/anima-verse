using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Bench;
using AnimaNative.Check;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Entry scene. Online: login screen → world build → the overview camera framing the world;
/// with <c>--bench</c> the camera drive starts once the world and the first
/// figures have loaded (Task S2). With <c>-- --check</c> / <c>-- --check-bench</c>:
/// the offline self-tests, then quit with their exit code. When gdCEF is linked
/// (and no <c>--no-hud</c>), the React HUD runs over the world (Task S4,
/// <see cref="HudOverlay"/>); this class is its SCENE side: game state, figure
/// selection, the scene's game actions.
/// </summary>
public partial class Main : Node3D
{
    private CliOptions? _options;
    private AnimaApi? _api;
    /// <summary>What the world is built from: the logged-in API, or the payload dump of <c>--offline</c>.</summary>
    private IWorldSource? _source;
    private WorldBuilder? _builder;
    private Label? _status;
    private OverviewCamera? _camera;
    private FigureManager? _figures;
    private ScatterLayer? _scatter;
    private string _groundSummary = "ground[plain]";
    private string _waterSummary = "water[none]";
    private bool _waterDrawn;
    private readonly CancellationTokenSource _stop = new();
    private HudOverlay? _hud;
    private string? _selected;
    private int _selectedPoll = -1;
    // ---- overview picking (Task 9) ----
    private LocationPicking? _picking;
    private EventPins? _pins;
    private readonly OpenView _openView = new();
    /// <summary>The info panel as last published (main.ts keeps the click's snapshot; only view.open is patched).</summary>
    private JsonObject? _info;
    /// <summary>Normal play: not a bench drive, not an offline dump (those keep the built world static).</summary>
    private bool _interactive;
    private Vector2? _hoverAt;
    private bool _hoverPending;
    private (int Serial, Dictionary<string, LocationInfo> Rows)? _placeRows;
    private bool _leaving;
    /// <summary>The window is set up once per PROCESS: back to the title reloads this scene and must not undo F11.</summary>
    private static bool _windowApplied;

    /// <summary>The bench anchor of the current world (S2 drives its path relative to it).</summary>
    public AnchorInfo? Anchor { get; private set; }

    public override void _Ready() => _ = RunAsync();

    private async Task RunAsync()
    {
        try
        {
            _options = CliOptions.FromGodot();
        }
        catch (Exception e)
        {
            GD.PrintErr($"[native] {e.Message}");
            GetTree().Quit(2);
            return;
        }
        if (_options.Check)
        {
            int code = await CheckRunner.RunAsync(this);
            GetTree().Quit(code);
            return;
        }
        ApplyWindowSize();
        BuildStage();
        if (_options.CheckBench)
        {
            int code = await BenchCheck.RunAsync(this, _camera!, _options);
            GetTree().Quit(code);
            return;
        }
        if (_options.Offline is { } dump)
        {
            // --offline: the REAL world from a payload dump, headless-capable, no login, no HUD (Task S3c).
            _source = new FixtureSource(System.IO.Path.GetFullPath(dump));
            Log($"offline source: {((FixtureSource)_source).Dir}");
            await LoadWorldAsync();
            return;
        }
        if (!_options.NoHud) AttachHud();
        var launch = Launcher();
        ApplyStoredFullscreen(launch.Fullscreen);
        _windowApplied = true;
        ShowLogin(launch);
    }

    /// <summary>
    /// Start values of the login screen: <c>--server</c>/<c>--user</c> win over
    /// <c>user://launcher.json</c>, which wins over empty fields (<see cref="LauncherSettings.Merge"/>).
    /// </summary>
    private LauncherSettings Launcher()
    {
        var stored = LauncherStore.Load();
        var launch = LauncherSettings.Merge(stored, _options!.Server, _options.User);
        string From(string value, string? cli)
            => value.Length == 0 ? "none" : !string.IsNullOrWhiteSpace(cli) ? "cli" : "file";
        Log($"launcher: server '{launch.Server}' ({From(launch.Server, _options.Server)}) "
            + $"user '{launch.User}' ({From(launch.User, _options.User)}) "
            + $"fullscreen {(launch.Fullscreen ? "on" : "off")} — settings {ProjectSettings.GlobalizePath(LauncherStore.DefaultPath)}");
        return launch;
    }

    /// <summary>
    /// The remembered window mode, at the first start of the process only — not for a
    /// bench (it measures in its fixed window) nor next to an explicit <c>--size</c>.
    /// </summary>
    private void ApplyStoredFullscreen(bool fullscreen)
    {
        if (_windowApplied || !fullscreen || _options!.Bench || _options.Size is not null) return;
        if (DisplayServer.GetName() == "headless") return;
        DisplayServer.WindowSetMode(DisplayServer.WindowMode.Fullscreen);
        Log("window: full screen (remembered; F11 toggles)");
    }

    /// <summary>
    /// F11: full screen ⇄ window, remembered in the launcher file. <c>Fullscreen</c>, not
    /// <c>ExclusiveFullscreen</c>: the same on Wayland, keeps the compositor on X11 (screen
    /// recorders keep working) and takes the window to the monitor size like the other.
    /// Handled in <c>_Input</c>, before the login fields and the HUD (which lets F11 through).
    /// </summary>
    public override void _Input(InputEvent e)
    {
        if (e is not InputEventKey { Pressed: true, Echo: false, Keycode: Key.F11 }) return;
        GetViewport().SetInputAsHandled();
        if (DisplayServer.GetName() == "headless") return;
        var mode = DisplayServer.WindowGetMode();
        bool full = mode is not (DisplayServer.WindowMode.Fullscreen or DisplayServer.WindowMode.ExclusiveFullscreen);
        DisplayServer.WindowSetMode(full ? DisplayServer.WindowMode.Fullscreen : DisplayServer.WindowMode.Windowed);
        LauncherStore.Update(s => s with { Fullscreen = full });
        Log($"window: {(full ? "full screen" : "windowed")} (F11, remembered)");
    }

    /// <summary><c>--size=WxH</c> (a bench run defaults to 1920x1080), centred on the current screen.</summary>
    private void ApplyWindowSize()
    {
        if (_windowApplied) return;
        var size = _options!.Size ?? (_options.Bench ? CliOptions.DefaultBenchSize : (Vector2I?)null);
        if (size is not { } s || DisplayServer.GetName() == "headless") return;
        DisplayServer.WindowSetMode(DisplayServer.WindowMode.Windowed);
        DisplayServer.WindowSetSize(s);
        var usable = DisplayServer.ScreenGetUsableRect(DisplayServer.WindowGetCurrentScreen());
        DisplayServer.WindowSetPosition(usable.Position + (usable.Size - s) / 2);
        Log($"window size requested {s.X}x{s.Y}, got {DisplayServer.WindowGetSize().X}x{DisplayServer.WindowGetSize().Y}");
    }

    /// <summary>Sky colour, ambient, sun + fill like the browser engine (no fog, no water).</summary>
    private void BuildStage()
    {
        var env = new Godot.Environment
        {
            BackgroundMode = Godot.Environment.BGMode.Color,
            BackgroundColor = new Color("9fc7e8"),
            AmbientLightSource = Godot.Environment.AmbientSource.Color,
            AmbientLightColor = new Color("dfeeff"),
            AmbientLightEnergy = 0.7f,
            TonemapMode = Godot.Environment.ToneMapper.Linear,
        };
        AddChild(new WorldEnvironment { Name = "Env", Environment = env });
        var sun = new DirectionalLight3D
        {
            Name = "Sun",
            LightColor = new Color("fff2d8"),
            LightEnergy = 1.0f,
            ShadowEnabled = true,
            DirectionalShadowMaxDistance = 200f,
            RotationDegrees = new Vector3(-50f, -35f, 0f),
        };
        AddChild(sun);
        AddChild(new DirectionalLight3D
        {
            Name = "Fill",
            LightColor = new Color("dde8ff"),
            LightEnergy = 0.25f,
            RotationDegrees = new Vector3(-35f, 130f, 0f),
        });
        _camera = new OverviewCamera { Name = "Camera" };
        AddChild(_camera);
        _camera.Current = true;
        _camera.JumpTo(Vector3.Zero, OverviewControl.InitialDist);
        // The click chain (engine.ts pointerup): figure → [seat/glyph/stair: E2/E7] → location → nothing.
        _camera.Clicked += at =>
        {
            if (_hud?.Active == true) PickAt(at);
        };
        // engine.ts pointermove without a gesture → onHover(pickLocation): the cursor, once per frame.
        _camera.Hovered += at =>
        {
            _hoverAt = at;
            _hoverPending = true;
        };

        var hud = new CanvasLayer { Name = "Hud" };
        AddChild(hud);
        _status = new Label { Position = new Vector2(12, 8), Modulate = new Color(0.1f, 0.1f, 0.1f) };
        hud.AddChild(_status);
    }

    private void ShowLogin(LauncherSettings launch)
    {
        var layer = new CanvasLayer { Name = "LoginLayer", Layer = 10 };
        AddChild(layer);
        var login = new LoginScreen().Setup(launch.Server, launch.User);
        layer.AddChild(login);
        login.Submit = async (server, user, password) =>
        {
            _api?.Dispose();
            _api = new AnimaApi(server);
            using (await _api.LoginAsync(user, password)) { }
            // Remembered only after the server accepted them; the password is not part of the file.
            LauncherStore.Update(s => s with { Server = server, User = user });
            Log($"logged in as '{user}' on {server} (server and user remembered)");
            _source = _api;
            // ONE login: the HUD's browser gets this very session (HudOverlay.Start).
            _hud?.Start(_api.BaseUri, _api.SessionToken());
            layer.QueueFree();
            await LoadWorldAsync();
        };
    }

    private async Task LoadWorldAsync()
    {
        SetStatus("Loading world…");
        try
        {
            MeshoptNative.EnsureLoaded(ProjectSettings.GlobalizePath("res://bin"));
            var world = new Node3D { Name = "World" };
            AddChild(world);
            var builder = _builder = new WorldBuilder(_source!, Log, strict: false)
            {
                PlainGround = _options!.PlainGround,
                NoWater = _options.NoWater,
            };
            var stats = await builder.BuildAsync(world, _options!.Goto);
            Anchor = stats.Anchor;
            _interactive = !_options.Bench && _options.Offline is null;
            _picking = new LocationPicking(builder);
            // main.ts: the avatar's location is the open one from the first mount on.
            if (stats.OpenLocation.Length > 0) _openView.TryOpen(stats.OpenLocation, true, out _);
            RefreshOpenBadge();
            _pins = new EventPins();
            world.AddChild(_pins);
            _pins.Update(builder.FirstMap!.Value, PlaceOf);
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
                world.AddChild(_scatter);
            }

            _figures = new FigureManager(_source!, builder.Height!, Log, strict: false);
            world.AddChild(_figures);
            _figures.Polled += () =>
            {
                // applyWorldMap → updatePins(map), every poll.
                if (_pins is not null && IsInstanceValid(_pins) && _figures.LatestMap is { } polled) _pins.Update(polled, PlaceOf);
            };
            await _figures.InitAsync();
            _ = _figures.PollLoopAsync(_stop.Token);
            _hud?.SetBoot(HudProtocol.BootReady());
            var timer = new Godot.Timer { WaitTime = 1.0, Autostart = true };
            AddChild(timer);
            timer.Timeout += () =>
            {
                PublishHudState();
                SetStatus($"{worldStatus}, {FigureLine()}"
                          + (_scatter is not null ? $"\n{_scatter.Summary()}" : "")
                          + (_hud?.Active == true
                              ? "   —   " + CameraHint + ", click a figure: plaque, F/Enter: chat, M: menu"
                              : "   —   " + CameraHint));
            };
            if (_options.Offline is not null && !_options.Bench)
            {
                await _figures.FirstPollDone;
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
                if (_scatter is not null) Log("offline scatter " + _scatter.Summary());
                Log("offline figures " + FigureLine());
                foreach (var line in ShaderSafety.Lines) Log("offline " + line);
                GetTree().Quit(0);
                return;
            }
            if (_options.Bench)
            {
                await _figures.FirstPollDone;
                if (_scatter is not null) await ScatterSettled(_scatter);
                StartBench(builder);
            }
        }
        catch (Exception e)
        {
            if (_stop.IsCancellationRequested) return;   // back to the title during the load: the scene is gone
            GD.PrintErr($"[native] world load failed: {e}");
            SetStatus("World load failed: " + e.Message);
            if ((_options!.Bench && _options.QuitAfterBench) || _options.Offline is not null) GetTree().Quit(1);
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
        AddChild(new BenchRunner(_camera!, settings, result =>
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
            var file = BenchOutput.Emit(result);
            BenchOutput.ShowPanel(this, result, file);
            _ = ReportBench(BenchOutput.Line(result));
        }));
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
        } while (layer.Field.Busy && Time.GetTicksMsec() - start < 60000);
        Log($"scatter settled after {(Time.GetTicksMsec() - start) / 1000.0:0.0} s: {layer.Summary()}");
    }

    private string FigureLine()
    {
        var s = _figures!.Stats;
        return $"{s.Figures} figures ({s.GlbFigures} models, {s.Placeholders} placeholders), "
               + $"{s.ClipsLoaded} clips" + (s.UnboundClips > 0 ? $", {s.UnboundClips} unbound" : "");
    }

    /// <summary>The overview camera's bindings (engine.ts), for the status line.</summary>
    private const string CameraHint = "drag: pan, right/middle or Shift+drag: orbit, wheel: zoom, WASD/arrows: move, Q/E: turn, +/-: zoom";

    public override void _ExitTree()
    {
        _stop.Cancel();
        _builder?.Models?.FreeAll();
        if (_hud is not null && IsInstanceValid(_hud)) _hud.Handlers.Clear();   // the overlay outlives this scene
        _api?.Dispose();
    }

    // ---- HUD scene side (Task S4) ---------------------------------------------------

    /// <summary>The overlay (once per process) + the game actions this spike answers.</summary>
    private void AttachHud()
    {
        _hud = HudOverlay.Ensure(GetTree(), Log);
        if (_hud is null) return;
        var hud = _hud;
        _camera!.KeysBlocked = () => IsInstanceValid(hud) && hud.KeysToHud;
        hud.Handlers.Clear();
        hud.Handlers["zoomTo"] = args => ZoomTo(args.Count > 0 ? args[0]?.GetValue<string>() : null);
        // The chat panel's box (HUD CSS px) → the camera's view shift (viewport px).
        hud.Handlers["setChatBox"] = args => _camera?.SetChatBox(hud.ChatBoxInWindow(args));
        hud.Handlers["clearSelection"] = _ => Select(null);
        hud.Handlers["closeOpenView"] = _ => CloseOpenLocation();
        hud.Handlers["closeInfo"] = _ => SetInfo(null);
        hud.Handlers["infoAction"] = args => InfoAction(Arg(args, 0), Arg(args, 1));
        hud.Handlers["setVolumes"] = _ => { };                                  // no audio in the spike
        hud.Handlers["backToTitle"] = args => { _ = BackToTitleAsync(); };
        // Scene-owned fields the chat, plaque and menu read (minimum viable set).
        hud.SetState("mode", "overview");
        hud.SetState("connection", "ok");
        hud.SetState("clock", "");
        hud.SetState("selected", null);
        hud.SetState("openView", null);
        hud.SetState("info", null);
    }

    /// <summary>1 Hz: connection, game clock and the selected figure's fresh row (main.ts does this per poll).</summary>
    private void PublishHudState()
    {
        if (_hud is null || _figures is null) return;
        _hud.SetState("connection", _figures.LastPollFailed ? "lost" : "ok");
        if (_figures.LatestMap is not { } map) return;
        var clock = "";
        if (map.TryGetProperty("game_time", out var gt) && gt.ValueKind == JsonValueKind.Object)
            clock = Str(gt, "label_display") is { Length: > 0 } display ? display : Str(gt, "label") ?? "";
        _hud.SetState("clock", clock);
        if (_selected is not null && _figures.PollSerial != _selectedPoll) Select(_selected);
    }

    /// <summary>
    /// <c>selected = { char, isAvatar }</c> with the character's row of the latest
    /// worldmap (the HUD's <c>MapCharacter</c>, passed through unchanged); a name
    /// that is not on the map drops the selection, like main.ts <c>refreshSelection</c>.
    /// </summary>
    private void Select(string? name)
    {
        if (_hud is null) return;
        _selected = null;
        JsonNode? value = null;
        if (name is not null && _figures?.LatestMap is { } map
            && map.TryGetProperty("characters", out var chars) && chars.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in chars.EnumerateArray())
            {
                if (Str(row, "name") != name) continue;
                value = new JsonObject
                {
                    ["char"] = JsonNode.Parse(row.GetRawText()),
                    ["isAvatar"] = Str(map, "avatar") == name,
                };
                _selected = name;
                _selectedPoll = _figures.PollSerial;
                break;
            }
        }
        _hud.SetState("selected", value);
    }

    /// <summary>
    /// A click the HUD did not take (engine.ts <c>pointerup</c>, a left release without a drag): the ray through
    /// the pointer — the camera's own, which honours the view shift — asks the figures first, then the
    /// locations (<see cref="PickChain"/>): a figure gets the plaque and keeps the panel, a location opens its
    /// info panel and clears the selection, empty ground clears both.
    /// </summary>
    private void PickAt(Vector2 click)
    {
        if (_figures is null || _camera is null) return;
        var (o, d) = _camera.RayAt(click);
        var figure = _figures.CharacterAt(o, d);
        // Asked only when no figure took the click, as engine.ts does.
        var location = figure is null ? _picking?.Pick(o, d) : null;
        var outcome = PickChain.Resolve(figure?.Name, location?.Id);
        Log($"pick at ({click.X:0},{click.Y:0}): "
            + (figure is { } f ? $"figure {f.Name} at {f.Distance:0.##} m ({_figures.LastPickCandidates} near the ray, "
                                 + $"{_figures.LastPickSkinnedVertices} vertices skinned, {_figures.LastPickMs:0.##} ms)"
               : location is { } l ? $"location {l.Id} at {l.Distance:0.##} m ({_picking!.LastBoxTests} boxes, "
                                     + $"{_picking.LastTriangleQueries} meshes, {_picking.LastMs:0.##} ms)"
               : "nothing"));
        Select(outcome.Selected);
        if (outcome.Info == InfoChange.Clear) SetInfo(null);
        else if (outcome.Info == InfoChange.Show) ShowInfo(outcome.InfoLocationId!);
    }

    // ---- info panel, open view, hover, auto-close (Task 9) -----------------------------------------

    private void SetInfo(JsonObject? info)
    {
        _info = info;
        _hud?.SetState("info", info?.DeepClone());
    }

    /// <summary>
    /// main.ts <c>engine.onPick(id)</c>: the panel of a known place (its world-map row), with the characters in
    /// it, its events, who is in which room, the view state and the avatar's whereabouts. An id without a row
    /// leaves the panel as it is.
    /// </summary>
    private void ShowInfo(string id)
    {
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        if (map is not { } m) return;
        var slot = _builder?.Slots.GetValueOrDefault(id);
        // `openable: !!residency.get(id) && openable(tile)` — a place that is not built cannot be opened.
        if (InfoPanel.FromWorldMap(m, id, new InfoView(slot?.Openable == true, _openView.OpenId == id)) is { } info)
            SetInfo(info);
    }

    /// <summary>
    /// main.ts <c>infoAction(id, kind)</c>: "Close view" closes the open location; "Zoom in" and "Look inside"
    /// fly to the place's centre at <c>min(targetDist, 15)</c>, "Look inside" also opens it. Then only the
    /// panel's <c>view.open</c> is brought up to date.
    /// </summary>
    private void InfoAction(string? id, string? kind)
    {
        if (id is null || _camera is null) return;
        if (kind == "closeView") CloseOpenLocation();
        else if (PlaceCentre(id) is { } centre)
        {
            _camera.FlyTo(centre, OpenView.FlyInDist(_camera.Control.TargetDist));
            if (kind == "lookInside") OpenLocation(id);
        }
        if (_info is { } info && Str(info, "id") == id && info["view"] is JsonObject v)
        {
            v["open"] = _openView.OpenId == id;
            SetInfo(info);
        }
    }

    /// <summary><c>openLocation(id)</c>: only a built, openable place; the previously open one closes.</summary>
    private void OpenLocation(string id)
    {
        var slot = _builder?.Slots.GetValueOrDefault(id);
        if (!_openView.TryOpen(id, slot?.Openable == true, out var closed)) return;
        if (closed is not null) _ = _builder!.SetOpenAsync(closed, false);
        _ = _builder!.SetOpenAsync(id, true);
        RefreshOpenBadge();
    }

    /// <summary><c>closeOpenLocation()</c>.</summary>
    private void CloseOpenLocation()
    {
        if (_openView.Close() is { } closed) _ = _builder?.SetOpenAsync(closed, false);
        RefreshOpenBadge();
    }

    /// <summary><c>refreshOpenBadge</c>: the open place's name, when it has one.</summary>
    private void RefreshOpenBadge()
    {
        var name = _openView.OpenId is { } id ? RowsOfPlaces().GetValueOrDefault(id)?.Name : null;
        _hud?.SetState("openView", OpenView.BadgeName(name));
    }

    public override void _Process(double delta)
    {
        if (_hoverPending)
        {
            _hoverPending = false;
            Hover(_hoverAt);
        }
        // The overview auto-close of main.ts' frame hook (no auto-reopen). The measuring runs keep their world.
        if (_interactive && _openView.OpenId is { } open && _camera is not null)
        {
            var slot = _builder?.Slots.GetValueOrDefault(open);
            var target = _camera.Target;
            if (slot is null || !IsInstanceValid(slot.Group)
                || OpenView.ShouldClose(_camera.Distance, target.X, target.Z, slot.Group.Position.X, slot.Group.Position.Z, slot.Width))
            {
                Log($"open view {open} closes (camera {_camera.Distance:0.#} m)");
                CloseOpenLocation();
            }
        }
    }

    /// <summary>
    /// <c>applyHoverCursor</c>: the pointing hand over a pickable location, the arrow elsewhere — only for a
    /// pointer over the SCENE (the camera reports moves the HUD did not take), and only while clicks pick.
    /// </summary>
    private void Hover(Vector2? at)
    {
        var shape = Input.CursorShape.Arrow;
        if (at is { } p && _hud?.Active == true && _picking is not null && _camera is not null)
        {
            var (o, d) = _camera.RayAt(p);
            if (_picking.Pick(o, d) is not null) shape = Input.CursorShape.PointingHand;
        }
        if (_hud is not null) _hud.SceneCursor = shape;
        if (_hud?.PointerOverHud == true) return;   // the page owns the cursor there
        Input.SetDefaultCursorShape(shape);
    }

    /// <summary>The world-map location rows by id (latest poll, else the build's), parsed once per poll.</summary>
    private Dictionary<string, LocationInfo> RowsOfPlaces()
    {
        int serial = _figures?.PollSerial ?? -1;
        if (_placeRows is { } cached && cached.Serial == serial) return cached.Rows;
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        var rows = new Dictionary<string, LocationInfo>();
        if (map is { } m)
            foreach (var l in LocationInfo.ParseList(m))
                rows[l.Id] = l;
        _placeRows = (serial, rows);
        return rows;
    }

    /// <summary><c>tile.center</c>: the built group's position, else the row's position on the ground.</summary>
    private Vector3? PlaceCentre(string id)
    {
        if (_builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group)) return slot.Group.Position;
        if (RowsOfPlaces().GetValueOrDefault(id) is { IsPlaced: true } row && _builder?.Height is { } h)
            return new Vector3((float)row.PosX!.Value, (float)h.GroundAt(row.PosX.Value, row.PosZ!.Value), (float)row.PosZ.Value);
        return null;
    }

    /// <summary>A place for the event pins: centre x/z and <c>tile.height</c> (measured, else the reading height).</summary>
    private (double X, double Z, double Height)? PlaceOf(string id)
    {
        if (_builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group))
            return (slot.Group.Position.X, slot.Group.Position.Z, slot.Height);
        if (RowsOfPlaces().GetValueOrDefault(id) is not { IsPlaced: true } row) return null;
        var (isBuilding, nature) = LocationView.Kind(row);
        return (row.PosX!.Value, row.PosZ!.Value, EventPinRule.DefaultPlaceHeight(isBuilding, nature, LocationView.DetectStyle(row)));
    }

    private static string? Arg(JsonArray args, int i)
        => args.Count > i && args[i] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static string? Str(JsonObject o, string key)
        => o[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    /// <summary>The plaque's "Zoom to" (main.ts <c>zoomTo</c>): fly to the figure's root + 0.85 m at 4.5 m; no follow.</summary>
    private void ZoomTo(string? name)
    {
        if (name is null || _figures is null || _camera is null) return;
        if (!_figures.Figures.TryGetValue(name, out var fig) || !IsInstanceValid(fig)) return;
        _camera.ZoomTo(fig.GlobalPosition);
        Log($"camera → {name} (HUD zoomTo)");
    }

    /// <summary>
    /// The menu's "Back to title" (and the top bar's "Log out"): end the shared session,
    /// back to the login screen. Like the browser (client3d main.ts <c>backToTitle</c>:
    /// logout, then <c>location.reload()</c>) the world is not taken apart by hand: the
    /// scene reload frees everything Main built (world, figures, scatter, the 1 Hz timer)
    /// and the cancelled token ends the worldmap poll; the HUD overlay, under the root,
    /// survives. Order: the HUD page ends the session first through its own cookie jar
    /// (HudOverlay.LeaveAsync — only a server answer can drop CEF's HttpOnly copy), then
    /// Godot asks <c>/auth/status</c> and logs out only a session that is still alive
    /// (an anonymous logout is not a no-op on the server), and empties its container.
    /// The reload runs whatever failed before it — a dead server must not keep the
    /// player out of the title screen.
    /// </summary>
    private async Task BackToTitleAsync()
    {
        if (_leaving) return;
        _leaving = true;
        Log("back to title");
        _stop.Cancel();
        try
        {
            if (_hud is not null) await _hud.LeaveAsync();
            if (_api is not null)
            {
                if (await _api.IsAuthenticatedAsync())
                {
                    await _api.LogoutAsync();
                    Log("logout: the client's session ended");
                }
                else Log("logout: no live session left on the client side");
            }
        }
        catch (Exception e)
        {
            Log($"logout: {e.Message}");
        }
        finally
        {
            _api?.ForgetCookies();
            _api?.Dispose();
            _api = null;
            _source = null;
            GetTree().ReloadCurrentScene();
        }
    }

    private static string? Str(JsonElement o, string key)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    private void SetStatus(string text)
    {
        if (_status is not null) _status.Text = text;
    }

    private static void Log(string line) => GD.Print("[native] " + line);
}
