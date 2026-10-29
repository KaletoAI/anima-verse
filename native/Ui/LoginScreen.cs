using System;
using System.Net.Http;
using System.Threading.Tasks;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// Native port of the browser title plate: server address, name, passphrase and the gate.
/// Server and user are pre-filled from the launcher file or the command line
/// (<see cref="LauncherStore"/>); the address is normalised as typed
/// (<see cref="LauncherSettings.NormalizeServer"/>). The submit callback gets the
/// password once; the field is cleared right after, and the password is written
/// nowhere — only the caller stores server and user after a successful login.
///
/// After the login the same screen is the LOADING screen (the browser's TitleScreen in its loading state):
/// <see cref="ShowBoot"/> replaces the fields with a bar, the current stage in words and the trouble line;
/// <see cref="FadeOut"/> takes it away once the world is visible. A failed start keeps it, with a button back to
/// the title.
/// </summary>
public partial class LoginScreen : Control
{
    private readonly LineEdit _server = new() { PlaceholderText = "Server (host:port or http(s)://host:port)", CustomMinimumSize = new Vector2(280, 0) };
    private readonly LineEdit _user = new();
    private readonly LineEdit _password = new() { PlaceholderText = "Password", Secret = true };
    private readonly Button _button = new() { Text = "Enter world" };
    private readonly Label _status = new() { AutowrapMode = TextServer.AutowrapMode.WordSmart, Visible = false };
    private readonly ProgressBar _bar = new() { MinValue = 0, MaxValue = 100, ShowPercentage = false, CustomMinimumSize = new Vector2(0, 8), Visible = false };
    private readonly Label _stage = new() { Visible = false, HorizontalAlignment = HorizontalAlignment.Center, AutowrapMode = TextServer.AutowrapMode.WordSmart };
    private readonly Button _back = new() { Text = "Back to the title", Visible = false };
    private readonly VBoxContainer _fields = new();
    private readonly VBoxContainer _credentials = new();
    private readonly CheckBox _remember = new() { Text = "Stay signed in", ButtonPressed = true };
    private readonly Label _gateUser = new() { Visible = false, HorizontalAlignment = HorizontalAlignment.Center };
    private readonly Button _signOut = new() { Text = "Sign out", Visible = false };
    private bool _gate;
    private readonly HBoxContainer _serverLine = new();
    private readonly Label _serverSummary = new() { SizeFlagsHorizontal = SizeFlags.ExpandFill, AutowrapMode = TextServer.AutowrapMode.WordSmart };
    private readonly Button _changeServer = new() { Text = "Change" };
    private Control _serverField = null!;
    private bool _booting;
    private bool _fading;
    private Tween? _fade;

    /// <summary>The failed start's button (Main goes back to the title).</summary>
    public Action? Back { get; set; }

    /// <summary>(normalised server URL, user, password, remember) → task; an exception's message lands in the status label.</summary>
    public Func<string, string, string, bool, Task>? Submit { get; set; }

    /// <summary>Godot script classes need a parameterless constructor; call <see cref="Setup"/> after it.</summary>
    public LoginScreen() { }

    public LoginScreen Setup(string? server, string? user, string? backdropRoot = null)
    {
        SetAnchorsPreset(LayoutPreset.FullRect);
        BuildPlate();
        _back.Pressed += () => Back?.Invoke();
        _server.Text = server ?? "";
        _user.Text = user ?? "";
        _serverField.Visible = string.IsNullOrWhiteSpace(server);
        _serverLine.Visible = !_serverField.Visible;
        _serverSummary.Text = $"Server  {ServerAddress(_server.Text)} ·";
        _backdropRoot = backdropRoot ?? ProjectSettings.GlobalizePath("user://backdrop");
        _ = LoadBackdropAsync();
        _server.TextChanged += text =>
        {
            CancelSessionCheck();
            if (_gate) ShowForm(_user.Text);
            _ = LoadBackdropAsync();
        };
        _signOut.Pressed += () => _ = SignOutAsync();
        _changeServer.Pressed += RevealServer;
        _button.Pressed += () => _ = OnSubmit();
        _server.TextSubmitted += text => (_user.Text.Length > 0 ? _password : _user).GrabFocus();
        _password.TextSubmitted += text => _ = OnSubmit();
        _user.TextSubmitted += text => _password.GrabFocus();
        return this;
    }

    public override void _Ready()
    {
        GetWindow().Title = "Anima Verse";
        ResizePlate();
        Resized += ResizePlate;
        _plate.MinimumSizeChanged += ResizePlate;
        _plate.Modulate = new Color(1, 1, 1, 0);
        _entrance = CreateTween();
        _entrance.TweenProperty(_plate, "modulate:a", 1.0f, 0.35).SetTrans(Tween.TransitionType.Sine).SetEase(Tween.EaseType.Out);
        if (_gate) _button.GrabFocus();
        else if (_server.Text.Length == 0) _server.GrabFocus();
        else if (_user.Text.Length > 0) _password.GrabFocus();
        else _user.GrabFocus();
    }

    public void ShowStatus(string text, bool error)
    {
        _status.Text = text;
        _status.Visible = text.Length > 0;
        _status.AddThemeColorOverride("font_color", error ? new Color("e0765f") : Muted);
        _status.AddThemeFontOverride("font", error ? ThemeDB.FallbackFont : _italic);
    }

    /// <summary>
    /// The loading state: bar at <paramref name="percent"/>, the stage in words, the note (or nothing) below; the
    /// login fields go. <paramref name="failed"/> offers the way back to the title.
    /// </summary>
    public void ShowBoot(int percent, string stage, string? note, bool failed)
    {
        _booting = true;
        _fields.Visible = _serverLine.Visible = _updateBox.Visible = false;
        _bar.Visible = _stage.Visible = true;
        _bar.Value = percent;
        _stage.Text = stage;
        ShowStatus(note ?? "", failed);
        _status.AddThemeColorOverride("font_color", new Color("dc8a6e"));
        _back.Visible = failed;
        if (failed && _fading)
        {
            // A failure after the fade began brings the screen back (TitleScreen: a failed start holds it).
            _fading = false;
            _fade?.Kill();
            _fade = null;
            Modulate = Colors.White;
        }
        if (failed)
        {
            _entrance?.Kill();
            _plate.Modulate = Colors.White;
        }
    }

    /// <summary>Fade out over <paramref name="seconds"/>, then <paramref name="done"/> (TitleScreen's FADE_MS = 900).</summary>
    public void FadeOut(double seconds, Action done)
    {
        if (_fading) return;
        _fading = true;
        var tween = _fade = CreateTween();
        tween.TweenProperty(this, "modulate:a", 0.0f, seconds);
        tween.Finished += () =>
        {
            if (_fading) done();
        };
    }

    private async Task OnSubmit()
    {
        if ((!_gate && Submit is null) || _button.Disabled || _checkingSession || _installing || _signingOut) return;
        var server = LauncherSettings.NormalizeServer(_server.Text);
        var user = _user.Text.Trim();
        var password = _password.Text;
        _password.Text = "";
        if (server is null)
        {
            ShowStatus(_server.Text.Trim().Length == 0
                ? "The server address is required."
                : $"Not a server address: '{_server.Text.Trim()}' (expected host:port or http(s)://host:port).", true);
            RevealServer();
            return;
        }
        if (!_gate) _server.Text = server;
        if (!_gate && (user.Length == 0 || password.Length == 0))
        {
            ShowStatus("User and password are required.", true);
            return;
        }
        var remember = _remember.ButtonPressed;
        _button.Disabled = _remember.Disabled = _signOut.Disabled = true;
        _button.Text = "Opening the gate…";
        _changeServer.Disabled = true;
        _server.Editable = false;
        ShowStatus("", false);
        try
        {
            await FinishUpdateCheckAsync();
            EndUpdateChecks();
            if (_gate) await EnterRememberedAsync();
            else await Submit!(server, user, password, remember);
        }
        catch (Exception e)
        {
            if (IsInstanceValid(this))
            {
                _loginStarted = false;
                _server.Editable = true;
                _updateCheck = CheckServerAsync();
                ShowStatus(e switch
                {
                    ApiException { Status: 401 or 403, Path: "/auth/login" } => "Sign-in failed — check name and passphrase.",
                    HttpRequestException or TimeoutException or OperationCanceledException => $"The server at {ServerAddress(server)} is not answering.",
                    _ => e.Message,
                }, true);
            }
        }
        finally
        {
            // The submit runs the whole start; the screen may have faded out and been freed meanwhile.
            if (IsInstanceValid(this))
            {
                _button.Disabled = _remember.Disabled = _signOut.Disabled = _changeServer.Disabled = false;
                _button.Text = "Enter world";
            }
        }
    }

    private void RevealServer()
    {
        if (_booting) return;
        if (_gate) ShowForm(_user.Text);
        _serverLine.Visible = false;
        _serverField.Visible = true;
        _server.GrabFocus();
    }

    private static string ServerAddress(string server)
        => Uri.TryCreate(LauncherSettings.NormalizeServer(server), UriKind.Absolute, out var uri)
            ? uri.Authority + uri.AbsolutePath.TrimEnd('/') : server.Trim();
}
