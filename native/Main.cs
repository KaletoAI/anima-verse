using System;
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
using AnimaNative.Scatter;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Entry scene. Online: login screen → world build → free camera at the anchor;
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
    private FlyCamera? _camera;
    private FigureManager? _figures;
    private ScatterLayer? _scatter;
    private string _groundSummary = "ground[plain]";
    private string _waterSummary = "water[none]";
    private bool _waterDrawn;
    private readonly CancellationTokenSource _stop = new();
    private int _focus = -1;
    private HudOverlay? _hud;
    private string? _selected;
    private int _selectedPoll = -1;
    private Vector2? _pressAt;

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
            _camera!.LookAtAnchor(stats.Anchor.Position() + new Vector3(0, 1.5f, 0));
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
                              ? "   —   drag: orbit, wheel: zoom, WASD: move, click a figure: plaque, F/Enter: chat, M: menu"
                              : "   —   drag: orbit, wheel: zoom, WASD: move, F: next figure"));
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

    /// <summary>
    /// F: the camera follows the next figure (name order); WASD lets go. With the
    /// HUD up, F belongs to the chat (HudOverlay answers it first) and a click on a
    /// figure selects it for the plaque — only clicks the HUD did not take arrive here.
    /// </summary>
    public override void _UnhandledInput(InputEvent e)
    {
        if (_hud?.Active == true && e is InputEventMouseButton { ButtonIndex: MouseButton.Left } click)
        {
            if (click.Pressed) _pressAt = click.Position;
            else if (_pressAt is { } at && at.DistanceTo(click.Position) < 6f) PickAt(click.Position);
            if (!click.Pressed) _pressAt = null;
            return;
        }
        if (e is not InputEventKey { Pressed: true, Echo: false, Keycode: Key.F } || _figures is null || _camera is null)
            return;
        var list = _figures.Ordered();
        if (list.Count == 0) return;
        _focus = (_focus + 1) % list.Count;
        _camera.Follow = list[_focus];
        _camera.Distance = 8f;
        Log($"camera → {list[_focus].CharacterName} ({list[_focus].Rule})");
    }

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
        hud.Handlers["clearSelection"] = _ => Select(null);
        hud.Handlers["closeOpenView"] = _ => hud.SetState("openView", null);   // no open location views in the spike
        hud.Handlers["setVolumes"] = _ => { };                                  // no audio in the spike
        hud.Handlers["backToTitle"] = args => { _ = BackToTitleAsync(); };
        // Scene-owned fields the chat, plaque and menu read (minimum viable set).
        hud.SetState("mode", "overview");
        hud.SetState("connection", "ok");
        hud.SetState("clock", "");
        hud.SetState("selected", null);
        hud.SetState("openView", null);
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

    /// <summary>A click the HUD did not take: the figure under it gets the plaque, a miss clears it.</summary>
    private void PickAt(Vector2 click)
    {
        if (_figures is null || _camera is null) return;
        var candidates = _figures.Figures.Values
            .Where(f => IsInstanceValid(f) && !_camera.IsPositionBehind(f.GlobalPosition))
            .Select(f => new FigurePick.Candidate(
                f.CharacterName,
                _camera.UnprojectPosition(f.GlobalPosition),
                _camera.UnprojectPosition(f.GlobalPosition + new Vector3(0, (float)f.HeightM, 0)),
                _camera.GlobalPosition.DistanceTo(f.GlobalPosition)));
        Select(FigurePick.Pick(candidates, click));
    }

    /// <summary>The plaque's "Zoom to": the camera follows that figure.</summary>
    private void ZoomTo(string? name)
    {
        if (name is null || _figures is null || _camera is null) return;
        if (!_figures.Figures.TryGetValue(name, out var fig)) return;
        _camera.Follow = fig;
        _camera.Distance = 8f;
        Log($"camera → {name} (HUD zoomTo)");
    }

    /// <summary>The menu's "Back to title": end the shared session, back to the login screen.</summary>
    private async Task BackToTitleAsync()
    {
        Log("back to title");
        _stop.Cancel();
        if (_hud is not null) await _hud.LeaveAsync();
        try { if (_api is not null) await _api.LogoutAsync(); }
        catch (Exception e) { Log($"logout: {e.Message}"); }
        GetTree().ReloadCurrentScene();
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
