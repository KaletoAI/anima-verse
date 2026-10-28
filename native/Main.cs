using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Check;
using AnimaNative.Figures;
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
///
/// One class in five files: this one holds the state, the start, the window, the stage and the frame
/// hook; <c>App/MainSession.cs</c> the login and the session (launcher, lost session, back to the title),
/// <c>App/MainWorld.cs</c> the world build with its boot stages (and the bench and offline runs),
/// <c>App/MainSync.cs</c> the polling (worldmap poll, push stream, location re-sync, show all) and
/// <c>App/MainHud.cs</c> the HUD wiring (game actions, selection, picking, info panel, open view).
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
    private ShadowCasterGate? _shadowGate;
    private FigureManager? _figures;
    private ScatterLayer? _scatter;
    /// <summary>The terrain streaming of the world (Task 24): anchor, loaders, signatures, the streaming probe.</summary>
    private TerrainStreamer? _streamer;
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
    /// <summary>The avatar's room (its worldmap row), for the door marks' lock look; and what the locks were last synced at.</summary>
    private string _avatarRoom = "";
    private string _lockRoom = "";
    private int _lockVersion = -1;
    /// <summary>The info panel as last published (main.ts keeps the click's snapshot; only view.open is patched).</summary>
    private JsonObject? _info;
    /// <summary>Normal play: not a bench drive, not an offline dump (those keep the built world static).</summary>
    private bool _interactive;
    private Vector2? _hoverAt;
    private bool _hoverPending;
    private (int Serial, Dictionary<string, LocationInfo> Rows)? _placeRows;
    /// <summary>Where this scene stands with its session (<see cref="SessionFlow"/>); Leaving = it is going away.</summary>
    private SessionState _session;
    private bool Leaving => _session.Phase == SessionPhase.Leaving;
    /// <summary>The window is set up once per PROCESS: back to the title reloads this scene and must not undo F11.</summary>
    private static bool _windowApplied;

    /// <summary>The bench anchor of the current world (S2 drives its path relative to it).</summary>
    public AnchorInfo? Anchor { get; private set; }

    public override void _Ready()
    {
        Ui.HitchLog.Init();
        _ = RunAsync();
    }

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
            int code = await CheckRunner.RunAsync(this, _options.CheckOnly);
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
            _source = new FixtureSource(System.IO.Path.GetFullPath(dump)) { OffThread = true };
            Log($"offline source: {((FixtureSource)_source).Dir}");
            await LoadWorldAsync();
            return;
        }
        if (!_options.NoHud) AttachHud();
        var launch = Launcher();
        ApplyStoredFullscreen(launch.Fullscreen);
        _windowApplied = true;
        StartSession(launch);
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

    /// <summary>
    /// The browser engine's stage (StageAmbience: sky background, hemisphere ambient, sun + fill, driven by the world
    /// clock and the room ambience), the 3D anti-aliasing (<see cref="CliOptions.StartMsaa"/>; the stored Graphics tab follows after the login), the overview camera and the
    /// distance fog under it (<see cref="DistanceFog"/>).
    /// </summary>
    private void BuildStage()
    {
        _stage = StageAmbience.Build(this, () => _builder?.Ground?.WaterMaterial);
        // Task 26c: the browser's 140 m shadow box — only casters inside it carry the sun's caster layer.
        _shadowGate = new ShadowCasterGate();
        _shadowGate.Attach(this);
        _stage.Gate = _shadowGate;
        GetViewport().Msaa3D = _options!.StartMsaa;
        _camera = new OverviewCamera { Name = "Camera" };
        AddChild(_camera);
        _camera.Current = true;
        _camera.JumpTo(Vector3.Zero, OverviewControl.InitialDist);
        // engine.ts `scene.fog`: the distance fog as one screen pass under the camera, its colour the stage's sky.
        // Task 26b/26c: the compute twin rides on the camera too and fogs the frame by default (--fog=pass: the screen pass).
        _stage.Fog = DistanceFog.Attach(_camera, compute: true);
        _stage.Fog.UseCompute = _options.FogCompute;
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

    public override void _ExitTree()
    {
        StopSync();
        _stop.Cancel();
        _shadowGate?.Detach();
        World.VeilUniforms.Reset();
        World.HemiUniforms.Reset();
        _builder?.Models?.FreeAll();
        if (_hud is not null && IsInstanceValid(_hud))
        {
            // The overlay outlives this scene.
            _hud.Handlers.Clear();
            _hud.PageLoaded = null;
        }
        _api?.Dispose();
    }

    public override void _Process(double delta)
    {
        // delta is the frame that just ended: log it if it was a hitch, with what the heavy main-thread steps reported.
        Ui.HitchLog.EndFrame(delta * 1000, Log);
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
        // main.ts' frame hook: the crossfade of every openable location and the neighbour occlusion — in every run
        // with a world (the measuring runs too: the avatar's location fades in at their start, as in the browser).
        if (_builder is not null && _camera is not null && _world is not null)
        {
            SyncLocks();
            _builder.TickView(delta, _camera.GlobalPosition);
            TickLights(delta);
            TickVeil(delta);
        }
        // The overview auto-close of main.ts' frame hook (no auto-reopen). The measuring runs keep their world.
        if (_interactive && _openView.OpenId is { } open && _camera is not null)
        {
            var slot = _builder?.Slots.GetValueOrDefault(open);
            var target = _camera.Target;
            if (!ResidencyRebuildHoldsOpen(open) && (slot is null || !IsInstanceValid(slot.Group)
                || OpenView.ShouldClose(_camera.Distance, target.X, target.Z, slot.Group.Position.X, slot.Group.Position.Z, slot.Width)))
            {
                Log($"open view {open} closes (camera {_camera.Distance:0.#} m)");
                CloseOpenLocation();
            }
        }
    }

    private static string? Arg(JsonArray args, int i)
        => args.Count > i && args[i] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static string? Str(JsonObject o, string key)
        => o[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static string? Str(JsonElement o, string key)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    private void SetStatus(string text)
    {
        if (_status is not null) _status.Text = text;
    }

    private static void Log(string line) => GD.Print("[native] " + line);
}
