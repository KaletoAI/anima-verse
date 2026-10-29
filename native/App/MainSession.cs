using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Overview;
using AnimaNative.Sync;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative;

/// <summary>
/// Main, login and session: the launcher values, the login screen, the session flow (<see cref="SessionFlow"/>: a
/// character switch rebuilds with the live session, a lost session and back to the title end on the login screen).
/// </summary>
public partial class Main : Node3D
{
    /// <summary>The session a rebuild hands to the next scene (survives the scene reload, taken once).</summary>
    private sealed record CarriedSession(string Server, string Token, string Role, bool BackdropCaptured);
    private static CarriedSession? _carried;

    /// <summary>
    /// The start of an online scene (<see cref="SessionFlow.Start"/>): the login screen, or — after a character
    /// switch — the world at once with the session the old scene carried over.
    /// </summary>
    private void StartSession(LauncherSettings launch)
    {
        var carried = _carried;
        _carried = null;
        var (state, step) = SessionFlow.Start(carried is not null);
        _session = state;
        if (step == SessionStep.ResumeWorld) _ = ResumeAsync(carried!, launch);
        else ShowLogin(launch);
    }

    /// <summary>One session event through <see cref="SessionFlow.Next"/>, then what it says to do.</summary>
    private void OnSession(SessionEvent e)
    {
        var (next, step) = SessionFlow.Next(_session, e);
        _session = next;
        switch (step)
        {
            case SessionStep.Acknowledge:
                Log("markResume: acknowledged — the HUD page's reload rebuilds the world (in either order)");
                break;
            case SessionStep.Rebuild:
                RebuildWithSession();
                break;
            case SessionStep.LogoutToTitle:
                _ = BackToTitleAsync();
                break;
            case SessionStep.ExpiredToTitle:
                ExpireSession();
                break;
        }
    }

    /// <summary>
    /// The character switch (GameMenu: <c>switchCharacter</c> → <c>markResume</c> → <c>location.reload()</c>), native
    /// side: the world that stands belongs to the character just left, so it is rebuilt from scratch — the same scene
    /// reload as back to the title, but WITHOUT a logout and without the login screen. The live session goes to the
    /// next scene (<see cref="ResumeAsync"/>); the HUD page has already reloaded on that very cookie, so there is no
    /// handoff either (it would end the session the browser holds).
    /// </summary>
    private void RebuildWithSession()
    {
        var token = _api?.SessionToken();
        if (_api is null || token is null)
        {
            Log("character switch: no live session to carry over — back to the title");
            _ = BackToTitleAsync();
            return;
        }
        Log("character switch: the HUD page reloaded — rebuilding the world with the live session (no login)");
        _carried = new CarriedSession(_api.BaseUri.ToString(), token, _role, _backdropCaptured);
        StopSync();
        _stop.Cancel();
        _api.Dispose();
        _api = null;
        _source = null;
        GetTree().ReloadCurrentScene();
    }

    /// <summary>
    /// The scene after a character switch: the carried session in a fresh API (no login request), the role it had,
    /// the loading screen at once, then the normal world load. The HUD page is already up on the same session.
    /// </summary>
    private AnimaApi CreateCachedApi(string server)
        => new(server, cache: _diskCacheEnabled ? new AnimaNative.Cache.DiskCache(
            CacheRoot, new Uri(server)) : null);

    private async Task ResumeAsync(CarriedSession carried, LauncherSettings launch)
    {
        _api = CreateCachedApi(carried.Server);
        _api.AdoptSession(carried.Token);
        _role = carried.Role;
        _backdropCaptured = carried.BackdropCaptured;
        _source = _api;
        _api.Unauthorized += () => Callable.From(OnUnauthorized).CallDeferred();
        Log($"session carried over (role '{_role}') on {_api.BaseUri} — rebuilding the world without a login");
        _loading = AddLoginScreen(launch, out _loadingLayer);
        ReadStoredStart();
        await LoadWorldAsync();
    }

    /// <summary>
    /// main.ts at boot, from the HUD settings kept across starts (<see cref="HudStorage"/>): the admin's "show all
    /// locations" picks the view the boot fetches (an admin only), the scatter detail distances the scatter LOD, the
    /// Graphics tab the anti-aliasing and the shadows. The HUD page reads the same entries from its seeded localStorage,
    /// so both sides start alike.
    /// </summary>
    private void ReadStoredStart()
    {
        if (_api is null) return;
        var stored = _hud?.StoredEntries(_api.BaseUri) ?? HudStorageStore.Load().EntriesFor(_api.BaseUri.ToString());
        ReadStoredAudioStart(stored);
        _showAll = HudStorage.StartShowAll(stored, IsAdmin);
        _scatterPrefs = ScatterPrefs.Load(stored.GetValueOrDefault(HudStorage.ScatterPrefsKey));
        Log($"stored HUD settings: {stored.Count} entries; start view {(_showAll ? "show all locations" : "known locations")}, "
            + $"scatter {_scatterPrefs.ScatterNearM}/{_scatterPrefs.ScatterFarM}/{_scatterPrefs.ScatterCullM} m");
        // The Graphics tab (Task 26d): nothing stored = 2×, shadows on. A bench run keeps its CLI picture.
        if (!_options!.Bench) ApplyGraphics(GraphicsPrefs.Load(stored.GetValueOrDefault(GraphicsPrefs.Key)), "stored");
    }

    /// <summary>The login screen on its own layer above everything (it doubles as the loading screen).</summary>
    private LoginScreen AddLoginScreen(LauncherSettings launch, out CanvasLayer layer)
    {
        layer = new CanvasLayer { Name = "LoginLayer", Layer = 10 };
        AddChild(layer);
        var login = new LoginScreen().Setup(launch.Server, launch.User);
        layer.AddChild(login);
        login.Back = () => OnSession(SessionEvent.BackToTitle);
        return login;
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

    private void ShowLogin(LauncherSettings launch)
    {
        var login = AddLoginScreen(launch, out var layer);
        login.EnableUpdates(BuildInfo.Version, Log);
        if (_loginNotice is { } notice)
        {
            login.ShowStatus(notice, true);
            _loginNotice = null;
        }
        _ = login.BindSessionAsync(SavedSessionStore(), CreateCachedApi,
            (api, answer, fallbackRole) => EnterWorldAsync(api, answer, fallbackRole, login, layer));
    }

    private static SessionStore SavedSessionStore() => new(ProjectSettings.GlobalizePath(LoginScreen.SessionPath));

    private static void DeleteSavedSession()
    {
        if (!SavedSessionStore().Delete()) GD.PushWarning("[native] session: cannot delete remembered session");
    }

    /// <summary>One world-entry tail for a fresh password login and a validated remembered session.</summary>
    private async Task EnterWorldAsync(AnimaApi api, JsonElement answer, string fallbackRole, LoginScreen login, CanvasLayer layer)
    {
        _api?.Dispose();
        _api = api;
        _role = RoleOf(answer) is { Length: > 0 } role ? role : fallbackRole;
        _source = api;
        SessionAvatar().RememberLogin(answer);
        Log($"session accepted (role '{_role}') on {api.BaseUri}");
        OnSession(SessionEvent.LoggedIn);
        api.Unauthorized += () => Callable.From(OnUnauthorized).CallDeferred();
        _loading = login;
        _loadingLayer = layer;
        ReadStoredStart();
        _hud?.Start(api.BaseUri, api.SessionToken());
        await LoadWorldAsync();
    }

    /// <summary><c>user.role</c> of the login answer (app/routes/auth.py), "" when absent.</summary>
    private static string RoleOf(JsonElement answer)
        => answer.ValueKind == JsonValueKind.Object && answer.TryGetProperty("user", out var u)
           && u.ValueKind == JsonValueKind.Object ? Str(u, "role") ?? "" : "";

    /// <summary>A request answered 401 (api.ts <c>auth:required</c>), deferred to the main loop.</summary>
    private void OnUnauthorized() => OnSession(SessionEvent.Unauthorized);

    /// <summary>
    /// The session died: back to the login screen like <see cref="BackToTitleAsync"/>, but WITHOUT a logout call —
    /// the session is gone already; server and user stay prefilled (the launcher file).
    /// </summary>
    private void ExpireSession()
    {
        DeleteSavedSession();
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
        DeleteSavedSession();
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
