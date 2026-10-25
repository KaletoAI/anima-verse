using System;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Bench;
using AnimaNative.Check;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Entry scene. Online: login screen → world build → free camera at the anchor;
/// with <c>--bench</c> the camera drive starts once the world and the first
/// figures have loaded (Task S2). With <c>-- --check</c> / <c>-- --check-bench</c>:
/// the offline self-tests, then quit with their exit code.
/// </summary>
public partial class Main : Node3D
{
    private CliOptions? _options;
    private AnimaApi? _api;
    private Label? _status;
    private FlyCamera? _camera;
    private FigureManager? _figures;
    private readonly CancellationTokenSource _stop = new();
    private int _focus = -1;

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
        ShowLogin();
    }

    /// <summary><c>--size=WxH</c> (a bench run defaults to 1920x1080), centred on the current screen.</summary>
    private void ApplyWindowSize()
    {
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
        _camera = new FlyCamera { Name = "Camera" };
        AddChild(_camera);
        _camera.Current = true;
        _camera.LookAtAnchor(Vector3.Zero);

        var hud = new CanvasLayer { Name = "Hud" };
        AddChild(hud);
        _status = new Label { Position = new Vector2(12, 8), Modulate = new Color(0.1f, 0.1f, 0.1f) };
        hud.AddChild(_status);
    }

    private void ShowLogin()
    {
        var layer = new CanvasLayer { Name = "LoginLayer", Layer = 10 };
        AddChild(layer);
        var login = new LoginScreen().Setup(_options!.Server, _options.User);
        layer.AddChild(login);
        login.Submit = async (user, password) =>
        {
            _api?.Dispose();
            _api = new AnimaApi(_options.Server);
            using (await _api.LoginAsync(user, password)) { }
            layer.QueueFree();
            await LoadWorldAsync();
        };
    }

    private async Task LoadWorldAsync()
    {
        SetStatus("Loading world…");
        try
        {
            MeshoptNative.EnsureLoaded();
            var world = new Node3D { Name = "World" };
            AddChild(world);
            var builder = new WorldBuilder(_api!, Log, strict: false);
            var stats = await builder.BuildAsync(world, _options!.Goto);
            Anchor = stats.Anchor;
            _camera!.LookAtAnchor(stats.Anchor.Position + new Vector3(0, 1.5f, 0));
            Log("world " + stats.Summary());
            var worldStatus = $"{stats.Buildings} buildings, {stats.Tiles} tiles, {stats.Primitives} primitives"
                              + (stats.Failures > 0 ? $", {stats.Failures} locations failed (see log)" : "");
            SetStatus(worldStatus + "   —   loading figures…");

            _figures = new FigureManager(_api!, builder.Height!, Log, strict: false);
            world.AddChild(_figures);
            await _figures.InitAsync();
            _ = _figures.PollLoopAsync(_stop.Token);
            var timer = new Godot.Timer { WaitTime = 1.0, Autostart = true };
            AddChild(timer);
            timer.Timeout += () => SetStatus($"{worldStatus}, {FigureLine()}"
                                             + "   —   drag: orbit, wheel: zoom, WASD: move, F: next figure");
            if (_options.Bench)
            {
                await _figures.FirstPollDone;
                StartBench(builder);
            }
        }
        catch (Exception e)
        {
            GD.PrintErr($"[native] world load failed: {e}");
            SetStatus("World load failed: " + e.Message);
            if (_options!.Bench && _options.QuitAfterBench) GetTree().Quit(1);
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
                                               _options!.Goto, _options.Vsync);
        Log($"bench starts ({settings.Path.Keyframes.Length} keyframes)");
        AddChild(new BenchRunner(_camera!, settings, result =>
        {
            var file = BenchOutput.Emit(result);
            BenchOutput.ShowPanel(this, result, file);
            if (_options.QuitAfterBench) GetTree().Quit(0);
        }));
    }

    private string FigureLine()
    {
        var s = _figures!.Stats;
        return $"{s.Figures} figures ({s.GlbFigures} models, {s.Placeholders} placeholders), "
               + $"{s.ClipsLoaded} clips" + (s.UnboundClips > 0 ? $", {s.UnboundClips} unbound" : "");
    }

    /// <summary>F: the camera follows the next figure (name order); WASD lets go.</summary>
    public override void _UnhandledInput(InputEvent e)
    {
        if (e is not InputEventKey { Pressed: true, Echo: false, Keycode: Key.F } || _figures is null || _camera is null)
            return;
        var list = _figures.Ordered();
        if (list.Count == 0) return;
        _focus = (_focus + 1) % list.Count;
        _camera.Follow = list[_focus];
        _camera.Distance = 8f;
        Log($"camera → {list[_focus].CharacterName} ({list[_focus].Rule})");
    }

    public override void _ExitTree() => _stop.Cancel();

    private void SetStatus(string text)
    {
        if (_status is not null) _status.Text = text;
    }

    private static void Log(string line) => GD.Print("[native] " + line);
}
