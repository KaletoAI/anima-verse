using System;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Sync;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative;

/// <summary>Main, login and session: the launcher values, the login screen, a lost session, back to the title.</summary>
public partial class Main : Node3D
{
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
}
