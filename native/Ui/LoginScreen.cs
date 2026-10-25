using System;
using System.Threading.Tasks;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// Minimal login: server address, user, password, button, error/status label.
/// Server and user are pre-filled from the launcher file or the command line
/// (<see cref="LauncherStore"/>); the address is normalised as typed
/// (<see cref="LauncherSettings.NormalizeServer"/>). The submit callback gets the
/// password once; the field is cleared right after, and the password is written
/// nowhere — only the caller stores server and user after a successful login.
/// </summary>
public partial class LoginScreen : Control
{
    private readonly LineEdit _server = new() { PlaceholderText = "Server (host:port or http(s)://host:port)", CustomMinimumSize = new Vector2(280, 0) };
    private readonly LineEdit _user = new() { PlaceholderText = "User", CustomMinimumSize = new Vector2(280, 0) };
    private readonly LineEdit _password = new() { PlaceholderText = "Password", Secret = true };
    private readonly Button _button = new() { Text = "Log in" };
    private readonly Label _status = new() { AutowrapMode = TextServer.AutowrapMode.WordSmart, CustomMinimumSize = new Vector2(280, 0) };

    /// <summary>(normalised server URL, user, password) → task; an exception's message lands in the status label.</summary>
    public Func<string, string, string, Task>? Submit { get; set; }

    /// <summary>Godot script classes need a parameterless constructor; call <see cref="Setup"/> after it.</summary>
    public LoginScreen() { }

    public LoginScreen Setup(string? server, string? user)
    {
        SetAnchorsPreset(LayoutPreset.FullRect);
        var center = new CenterContainer();
        center.SetAnchorsPreset(LayoutPreset.FullRect);
        AddChild(center);
        var box = new VBoxContainer();
        box.AddThemeConstantOverride("separation", 8);
        center.AddChild(box);
        box.AddChild(new Label { Text = "Anima Verse — native client (spike)" });
        box.AddChild(_server);
        box.AddChild(_user);
        box.AddChild(_password);
        box.AddChild(_button);
        box.AddChild(_status);
        _server.Text = server ?? "";
        _user.Text = user ?? "";
        _button.Pressed += () => _ = OnSubmit();
        _server.TextSubmitted += text => (_user.Text.Length > 0 ? _password : _user).GrabFocus();
        _password.TextSubmitted += text => _ = OnSubmit();
        _user.TextSubmitted += text => _password.GrabFocus();
        return this;
    }

    public override void _Ready()
    {
        if (_server.Text.Length == 0) _server.GrabFocus();
        else if (_user.Text.Length > 0) _password.GrabFocus();
        else _user.GrabFocus();
    }

    public void ShowStatus(string text, bool error)
    {
        _status.Text = text;
        _status.Modulate = error ? new Color(1f, 0.45f, 0.4f) : Colors.White;
    }

    private async Task OnSubmit()
    {
        if (Submit is null || _button.Disabled) return;
        var server = LauncherSettings.NormalizeServer(_server.Text);
        var user = _user.Text.Trim();
        var password = _password.Text;
        _password.Text = "";
        if (server is null)
        {
            ShowStatus(_server.Text.Trim().Length == 0
                ? "The server address is required."
                : $"Not a server address: '{_server.Text.Trim()}' (expected host:port or http(s)://host:port).", true);
            _server.GrabFocus();
            return;
        }
        _server.Text = server;
        if (user.Length == 0 || password.Length == 0)
        {
            ShowStatus("User and password are required.", true);
            return;
        }
        _button.Disabled = true;
        ShowStatus("Logging in…", false);
        try
        {
            await Submit(server, user, password);
        }
        catch (Exception e)
        {
            ShowStatus(e.Message, true);
        }
        finally
        {
            _button.Disabled = false;
        }
    }
}
