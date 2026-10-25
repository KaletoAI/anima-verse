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
using AnimaNative.Sync;
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
    // ---- sync (Task 10): the browser's polling cadence, the push stream, the boot stages ----
    private const string WorldmapKey = "c3d-worldmap";
    /// <summary>The clock and timers of the sync layer, pumped every frame (<see cref="_Process"/>).</summary>
    private readonly TimerQueue _timers = new(() => Time.GetTicksMsec());
    private double _nextTickMs = double.PositiveInfinity;
    private SyncStream? _hub;
    private PollScheduler? _poll;
    private IDisposable? _pollSub;
    private BootTracker? _boot;
    private readonly ConnectionState _conn = new();
    private LocationsCache? _locCache;
    private LocationsSync? _locSync;
    private object? _locTimer;
    /// <summary>The role of the logged-in user (<c>POST /auth/login</c> → <c>user.role</c>); "" offline.</summary>
    private string _role = "";
    private bool IsAdmin => _role == "admin";
    /// <summary>The admin's "show all locations" view (<c>/play/worldmap?all=1</c>), live like main.ts <c>applyShowAll</c>.</summary>
    private bool _showAll;
    /// <summary>main.ts <c>viewRev</c>: a poll fetched under an older view is dropped.</summary>
    private int _viewRev;
    private bool _viewSwitchBusy, _revealBusy;
    private ScatterPrefs _scatterPrefs = ScatterPrefs.Defaults;
    /// <summary>The login screen while it is the loading screen (null once it faded, and offline).</summary>
    private LoginScreen? _loading;
    private CanvasLayer? _loadingLayer;
    /// <summary>A line for the NEXT login screen (survives the scene reload): why the session ended.</summary>
    private static string? _loginNotice;
    // ---- overview picking (Task 9) ----
    private LocationPicking? _picking;
    private EventPins? _pins;
    // ---- labels and the performance readout (Task 11) ----
    private NameTags? _tags;
    private LocationLabels? _placeLabels;
    private LabelOverlay? _labelOverlay;
    private readonly PerfProbe _perf = new();
    private Node3D? _world;
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
        if (_loginNotice is { } notice)
        {
            login.ShowStatus(notice, true);
            _loginNotice = null;
        }
        login.Back = () => _ = BackToTitleAsync();
        login.Submit = async (server, user, password) =>
        {
            _api?.Dispose();
            _api = new AnimaApi(server);
            using (var answer = await _api.LoginAsync(user, password)) _role = RoleOf(answer.RootElement);
            // Remembered only after the server accepted them; the password is not part of the file.
            LauncherStore.Update(s => s with { Server = server, User = user });
            Log($"logged in as '{user}' (role '{_role}') on {server} (server and user remembered)");
            _source = _api;
            // api.ts `auth:required`: any later 401 ends this session on the client too.
            _api.Unauthorized += () => Callable.From(OnUnauthorized).CallDeferred();
            // ONE login: the HUD's browser gets this very session (HudOverlay.Start).
            _hud?.Start(_api.BaseUri, _api.SessionToken());
            // The login screen stays as the loading screen until the world is visible (TitleScreen).
            _loading = login;
            _loadingLayer = layer;
            await LoadWorldAsync();
        };
    }

    /// <summary><c>user.role</c> of the login answer (app/routes/auth.py), "" when absent.</summary>
    private static string RoleOf(JsonElement answer)
        => answer.ValueKind == JsonValueKind.Object && answer.TryGetProperty("user", out var u)
           && u.ValueKind == JsonValueKind.Object ? Str(u, "role") ?? "" : "";

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
            var world = new Node3D { Name = "World" };
            AddChild(world);
            var builder = _builder = new WorldBuilder(_source!, Log, strict: false)
            {
                PlainGround = _options!.PlainGround,
                NoWater = _options.NoWater,
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
            };
            var stats = await builder.BuildAsync(world, _options!.Goto, hooks);
            Anchor = stats.Anchor;
            _interactive = !_options.Bench && _options.Offline is null;
            _picking = new LocationPicking(builder);
            // main.ts: the avatar's location is the open one from the first mount on.
            if (stats.OpenLocation.Length > 0) _openView.TryOpen(stats.OpenLocation, true, out _);
            RefreshOpenBadge();
            _pins = new EventPins();
            world.AddChild(_pins);
            _pins.Update(builder.FirstMap!.Value, PlaceOf);
            _world = world;
            // The CSS2D label layer: location names now, name tags once the figures are there. Under the HUD (layer 5).
            _placeLabels = new LocationLabels();
            SyncPlaceLabels();
            var labelsLayer = new CanvasLayer { Name = "Labels", Layer = 1 };
            AddChild(labelsLayer);
            _labelOverlay = new LabelOverlay { Camera = _camera };
            var placeLabels = _placeLabels;
            _labelOverlay.Sources.Add(() => placeLabels.Visible(PlaceOf));
            labelsLayer.AddChild(_labelOverlay);
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
            }

            // visible: the world stands and the camera looks at it — the next drawn frame shows it.
            boot.SetNote(BootNote.Characters);
            await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
            boot.Report("visible");

            _figures = new FigureManager(_source!, builder.Height!, Log, strict: false);
            world.AddChild(_figures);
            var tags = _tags = new NameTags(_figures, () => Time.GetTicksMsec()) { CamDist = () => _camera?.Distance ?? 0 };
            _labelOverlay.Sources.Add(tags.Visible);
            _figures.Polled += () =>
            {
                if (_figures.LatestMap is not { } polled) return;
                // applyWorldMap → updatePins(map), every poll; npcs.update → the tags' texts; the place labels follow.
                if (_pins is not null && IsInstanceValid(_pins)) _pins.Update(polled, PlaceOf);
                tags.Apply(polled);
                SyncPlaceLabels();
            };
            await _figures.InitAsync();
            // The boot's own map places the first figures (main.ts npcs.update(firstMap)); the poll takes over.
            _figures.ApplyPolled(builder.FirstMap!.Value);
            StartSync();
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
                if (_scatter is not null) Log("offline scatter " + _scatter.Summary());
                Log("offline figures " + FigureLine());
                foreach (var line in ShaderSafety.Lines) Log("offline " + line);
                GetTree().Quit(0);
                return;
            }
            if (_options.Bench)
            {
                if (_scatter is not null) await ScatterSettled(_scatter);
                StartBench(builder);
            }
        }
        catch (Exception e)
        {
            if (_stop.IsCancellationRequested || _leaving) return;   // back to the title / a lost session: the scene is gone
            if (AnimaApi.IsAuthError(e)) return;   // the session died: OnUnauthorized brings the login back
            GD.PrintErr($"[native] world load failed: {e}");
            SetStatus("World load failed: " + e.Message);
            boot.SetNote(BootNote.Failed);
            if ((_options!.Bench && _options.QuitAfterBench) || _options.Offline is not null) GetTree().Quit(1);
        }
    }

    // ---- sync: the browser's polling cadence and push stream (Task 10) ------------------------------------

    /// <summary>
    /// The world map poll of main.ts: ONE subscription <c>c3d-worldmap</c> with the browser's budget
    /// (<see cref="PollSpec.Worldmap3d"/>: 3 s, 6 s while the push stream is connected, at least 3 s apart, backoff on
    /// failures) on <see cref="PollScheduler"/>; online the push stream <c>/events/sync</c> (<see cref="SyncStream"/>)
    /// wakes it early on <c>presence</c>/<c>world</c> and makes a resync drop what was in flight. The location details
    /// re-sync every 120 s and whenever a poll names another revision.
    /// </summary>
    private void StartSync()
    {
        if (_api is { } api)
        {
            _hub = new SyncStream(url => new HttpEventSource(api.OpenEventStreamAsync, url, Log), _timers);
            var hub = _hub;
            bool wasConnected = false;
            int seenGen = 0;
            hub.OnState(() =>
            {
                if (hub.Connected == wasConnected && hub.Generation == seenGen) return;
                wasConnected = hub.Connected;
                seenGen = hub.Generation;
                Log(hub.Describe());
            });
        }
        _poll = new PollScheduler(_timers, _hub);
        _nextTickMs = Time.GetTicksMsec() + PollSchedule.TickMs;
        _pollSub = _poll.Subscribe<PolledMap>(WorldmapKey, FetchWorldMapAsync, PollSpec.Worldmap3d, OnWorldMap);
        if (_locCache?.Cached is { } first)
        {
            _locSync = new LocationsSync(_locCache, l =>
            {
                _builder?.TakeDetails(l.Root);
                Log($"locations re-synced (ETag {l.Etag})");
            });
            _locSync.Seed(first);
            _ = _locSync.SyncAsync();
            ArmLocationsResync();
        }
    }

    private void ArmLocationsResync()
    {
        _locTimer = _timers.SetTimeout(() =>
        {
            if (_stop.IsCancellationRequested || _locSync is null) return;
            _ = _locSync.SyncAsync();
            ArmLocationsResync();
        }, LocationsSync.ResyncMs);
    }

    /// <summary>Back to the title, a lost session, the scene going: no poll, no stream, no timer survives.</summary>
    private void StopSync()
    {
        _pollSub?.Dispose();
        _pollSub = null;
        _poll = null;
        _hub?.Stop();
        _hub = null;
        _timers.ClearTimeout(_locTimer);
        _locTimer = null;
        _locSync = null;
        _nextTickMs = double.PositiveInfinity;
    }

    /// <summary>A polled map with the view revision it was asked under (main.ts <c>PolledMap</c>).</summary>
    private sealed record PolledMap(JsonElement Map, int ViewRev);

    private async Task<PolledMap> FetchWorldMapAsync()
    {
        int rev = _viewRev;
        using var doc = _api is { } api ? await api.GetWorldMapAsync(_showAll) : await _source!.GetWorldMapAsync();
        return new PolledMap(doc.RootElement.Clone(), rev);
    }

    /// <summary>The poll's callback: an error that is not a lost session marks the connection lost.</summary>
    private void OnWorldMap(PolledMap? polled, Exception? error)
    {
        if (_stop.IsCancellationRequested || _leaving) return;
        if (error is not null)
        {
            if (AnimaApi.IsAuthError(error)) return;   // the login comes back (OnUnauthorized)
            Log($"worldmap poll failed: {error.Message} — next in {(_poll?.IntervalMs(WorldmapKey) ?? 0) / 1000:0} s");
            _figures?.MarkPollFailed();
            if (_conn.Lost()) _hud?.SetState("connection", ConnectionState.LostValue);
            return;
        }
        if (polled is not null) ApplyWorldMap(polled);
    }

    /// <summary>
    /// main.ts <c>applyWorldMap</c>, the parts this client has: drop a map of an older view; re-sync the details
    /// when the map names another revision; the figures, the pins and the selection follow the map; connection and
    /// clock only on change; a placed location the world has not taken in forces a details re-sync and is revealed.
    /// </summary>
    private void ApplyWorldMap(PolledMap p)
    {
        if (p.ViewRev != _viewRev || _viewSwitchBusy || _figures is null) return;
        var map = p.Map;
        try
        {
            if (_locSync is not null && _locSync.Differs(LocationsSync.MapRev(map))) _ = _locSync.SyncAsync();
            _figures.PollSeconds = (_poll?.IntervalMs(WorldmapKey) ?? PollSpec.Worldmap3d.IntervalMs) / 1000.0;
            _figures.ApplyPolled(map);
            var clock = ConnectionState.ClockOf(map);
            if (_conn.Ok(clock))
            {
                _hud?.SetState("connection", ConnectionState.OkValue);
                _hud?.SetState("clock", clock);
            }
            if (_selected is not null) Select(_selected);   // refreshSelection(map)
            if (_interactive && _builder is not null && _builder.FreshOf(map).Count > 0)
            {
                // Discovery needs details even when the endpoint revision has not changed.
                _ = _locSync?.SyncAsync(force: true);
                _ = RevealAsync(map);
            }
        }
        catch (Exception e)
        {
            Log($"worldmap apply failed: {e.Message}");
            if (!AnimaApi.IsAuthError(e) && _conn.Lost()) _hud?.SetState("connection", ConnectionState.LostValue);
        }
    }

    /// <summary><c>revealLocations(map)</c>: one at a time; a run of an older view mounts nothing.</summary>
    private async Task<int> RevealAsync(JsonElement map)
    {
        if (_revealBusy || _builder is null) return 0;
        _revealBusy = true;
        int rev = _viewRev;
        try
        {
            int added = await _builder.RevealAsync(map, () => rev == _viewRev && !_stop.IsCancellationRequested);
            if (added > 0) _placeRows = null;
            SyncPlaceLabels();
            return added;
        }
        catch (Exception e)
        {
            Log($"reveal failed: {e.Message}");
            return 0;
        }
        finally
        {
            _revealBusy = false;
        }
    }

    /// <summary>
    /// main.ts <c>applyShowAll(on)</c> — the admin's "show all locations", applied live: the flag and the view
    /// revision move BEFORE the request (a poll in flight of the old view is dropped), the other view's map is
    /// fetched and the world is reconciled against it: what it no longer carries goes (the avatar's own place
    /// stays), what it adds is revealed. A failed request rolls the flag back and says so in a toast.
    /// </summary>
    private async Task ApplyShowAllAsync(bool on)
    {
        if (!IsAdmin || on == _showAll || _viewSwitchBusy || _api is null || _builder is null || _figures is null) return;
        _viewSwitchBusy = true;
        try
        {
            _showAll = on;
            _viewRev++;
            JsonElement map;
            try
            {
                using var doc = await _api.GetWorldMapAsync(on);
                map = doc.RootElement.Clone();
            }
            catch (Exception e)
            {
                _showAll = !on;
                _viewRev++;
                Log($"show all: switch failed: {e.Message}");
                _hud?.SendUi("toast", JsonValue.Create("The view could not be switched."), JsonValue.Create(true));
                return;
            }
            if (_stop.IsCancellationRequested) return;
            _figures.ApplyPolled(map);
            var dropped = _builder.DropVanished(map);
            if (dropped.Count > 0)
            {
                if (_openView.OpenId is { } open && dropped.Contains(open)) CloseOpenLocation();
                // A view switch closes information that may describe a removed place.
                SetInfo(null);
            }
            _placeRows = null;
            if (_selected is not null) Select(_selected);
            int rev = _viewRev;
            int added = await _builder.RevealAsync(map, () => rev == _viewRev && !_stop.IsCancellationRequested);
            _placeRows = null;
            SyncPlaceLabels();
            Log($"show all locations {(on ? "ON" : "off")}: {dropped.Count} dropped, {added} revealed");
        }
        catch (Exception e)
        {
            Log($"show all: switch failed: {e.Message}");
            _hud?.SendUi("toast", JsonValue.Create("The view could not be switched."), JsonValue.Create(true));
        }
        finally
        {
            _viewSwitchBusy = false;
        }
    }

    /// <summary>
    /// <c>applyScatterPrefs(prefs)</c> from the HUD's menu: checked again here (<see cref="ScatterPrefs.Check"/> — a
    /// malformed message must not invert the band), then the scatter LOD of the standing scatter layer. The
    /// undergrowth keeps its own fixed distances (ground.ts leaves it alone too); the world props' tiers are set
    /// once at build in this client (no live prop LOD yet), so they are not touched.
    /// </summary>
    private void ApplyScatterPrefs(JsonArray args)
    {
        if (args.Count == 0 || args[0] is not JsonObject p)
        {
            Log("applyScatterPrefs: no prefs object — ignored");
            return;
        }
        var check = ScatterPrefs.Check(HudUi.Num(p, "scatterNearM"), HudUi.Num(p, "scatterFarM"), HudUi.Num(p, "scatterCullM"));
        if (check.Prefs is not { } prefs)
        {
            Log($"applyScatterPrefs refused ({check.Error}): {p.ToJsonString()}");
            return;
        }
        _scatterPrefs = prefs;
        _scatter?.Field.SetLod(ScatterPrefs.LodCfgOf(prefs));
        Log($"scatter detail distances {prefs.ScatterNearM}/{prefs.ScatterFarM}/{prefs.ScatterCullM} m"
            + (_scatter is null ? " (kept for a scatter layer; none is drawn without --scatter)" : " applied"));
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

    private string SyncLine()
        => $"poll every {(_poll?.IntervalMs(WorldmapKey) ?? 0) / 1000:0} s ({_conn.Connection})"
           + (_hub is not null ? $", {_hub.Describe()}" : ", no push stream")
           + (_locSync is not null ? $", locations rev {_locSync.Rev}" : "")
           + (_showAll ? ", SHOW ALL" : "");

    /// <summary>
    /// A request answered 401 (api.ts <c>auth:required</c>): back to the login screen like <see cref="BackToTitleAsync"/>,
    /// but WITHOUT a logout call — the session is gone already; server and user stay prefilled (the launcher file).
    /// </summary>
    private void OnUnauthorized()
    {
        if (_leaving) return;
        _leaving = true;
        Log("session ended (HTTP 401) — back to the login screen, no logout call");
        StopSync();
        _stop.Cancel();
        _hud?.Suspend();
        _loginNotice = "Your session has ended — please log in again.";
        _api?.ForgetCookies();
        _api?.Dispose();
        _api = null;
        _source = null;
        GetTree().ReloadCurrentScene();
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
        StopSync();
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
        hud.Handlers["setShowAll"] = args =>
        {
            if (args.Count > 0 && args[0] is JsonValue v && v.TryGetValue<bool>(out var on)) _ = ApplyShowAllAsync(on);
        };
        hud.Handlers["applyScatterPrefs"] = ApplyScatterPrefs;
        // Hud.tsx: a new speakable line of this room → npcs.say(speaker, text); unknown names are ignored.
        hud.Handlers["sayBubble"] = args =>
        {
            if (Arg(args, 0) is { } who && Arg(args, 1) is { } text) _tags?.Say(who, text);
        };
        // The browser sets a marker that survives ONE page reload, so the next boot skips the title gate (a
        // character take-over reloads the page). This client never reloads a page: there is nothing to mark.
        hud.Handlers["markResume"] = _ => Log("markResume: acknowledged — the native client has no page reload to resume after");
        // Scene-owned fields the chat, plaque and menu read (minimum viable set).
        hud.SetState("mode", "overview");
        hud.SetState("connection", "ok");
        hud.SetState("clock", "");
        hud.SetState("selected", null);
        hud.SetState("openView", null);
        hud.SetState("info", null);
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
        // The sync layer's clock: due timers (trailing polls, stream deadlines and retries, the 120-s location
        // re-sync), then the poll core's 1-s tick.
        _timers.Pump();
        if (_poll is not null && Time.GetTicksMsec() >= _nextTickMs)
        {
            _nextTickMs += PollSchedule.TickMs;
            if (_nextTickMs < Time.GetTicksMsec()) _nextTickMs = Time.GetTicksMsec() + PollSchedule.TickMs;
            _poll.Tick();
        }
        if (_hoverPending)
        {
            _hoverPending = false;
            Hover(_hoverAt);
        }
        // npcs.tick: a bubble whose reading time is up goes.
        _tags?.Expire();
        // The performance readout: measured and sent only while the HUD shows it (HudUiState.perfOn).
        if (_hud is { } hudNow && _perf.Frame(hudNow.Active && hudNow.Ui.PerfOn, delta, _world) is { } perf) hudNow.SendPerf(perf);
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

    /// <summary>
    /// A place for the event pins and the location labels (main.ts <c>places.get(id)</c>): centre x/z, the ground
    /// datum (<c>tile.center.y</c>) and <c>tile.height</c> — the built group's, else the ground under the row's pin
    /// (<c>footprintCentre</c>) and <c>buildPlace</c>'s reading height.
    /// </summary>
    private (double X, double GroundY, double Z, double Height)? PlaceOf(string id)
    {
        if (_builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group))
            return (slot.Group.Position.X, slot.Group.Position.Y, slot.Group.Position.Z, slot.Height);
        if (RowsOfPlaces().GetValueOrDefault(id) is not { IsPlaced: true } row || _builder?.Height is not { } h) return null;
        var (isBuilding, nature) = LocationView.Kind(row);
        return (row.PosX!.Value, h.GroundAt(row.PosX.Value, row.PosZ!.Value), row.PosZ.Value,
                EventPinRule.DefaultPlaceHeight(isBuilding, nature, LocationView.DetectStyle(row)));
    }

    /// <summary>The location labels follow the world's places and their latest rows.</summary>
    private void SyncPlaceLabels()
    {
        if (_placeLabels is null || _builder is null) return;
        _placeLabels.Sync(_builder.Known, RowsOfPlaces());
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
        StopSync();
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
