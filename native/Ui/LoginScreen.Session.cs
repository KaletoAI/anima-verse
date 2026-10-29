using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.Ui;

/// <summary>Title-only authentication; both a password login and the remembered gate transfer to one entry callback.</summary>
public partial class LoginScreen
{
    public const string SessionPath = "user://session.json";
    private SessionStore? _sessionStore;
    private Func<string, AnimaApi>? _createApi;
    private Func<AnimaApi, JsonElement, string, Task>? _accepted;
    private AnimaApi? _titleApi;
    private JsonElement _gateAnswer;
    private RememberedSession? _remembered;
    private CancellationTokenSource? _sessionStop;
    private int _sessionGeneration;
    private bool _checkingSession, _signingOut;
    private string _sessionLauncherPath = LauncherStore.DefaultPath;

    /// <summary>Check only the current launcher's matching saved token; no world requests before Enter world.</summary>
    public async Task BindSessionAsync(SessionStore store, Func<string, AnimaApi> createApi,
        Func<AnimaApi, JsonElement, string, Task> accepted, string launcherPath = LauncherStore.DefaultPath)
    {
        _sessionStore = store;
        _createApi = createApi;
        _accepted = accepted;
        _sessionLauncherPath = launcherPath;
        Submit = LoginAndEnterAsync;
        var saved = store.LoadFor(_server.Text);
        if (saved is null) return;
        var generation = ++_sessionGeneration;
        _sessionStop = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        _checkingSession = _button.Disabled = true;
        ShowStatus("Checking session…", false);
        var api = createApi(saved.Server);
        try
        {
            api.AdoptSession(saved.Token);
            using var answer = await api.GetAuthStatusAsync(_sessionStop.Token);
            if (!IsInsideTree() || generation != _sessionGeneration) return;
            var root = answer.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("authenticated", out var authenticated)
                || authenticated.ValueKind != JsonValueKind.True)
            {
                ForgetStoredSession();
                ShowForm(_user.Text);
                return;
            }
            _remembered = saved with { User = AnswerUser(root, "username") ?? saved.User, Role = AnswerUser(root, "role") ?? saved.Role };
            _gateAnswer = root.Clone();
            _titleApi = api;
            _user.Text = _remembered.User;
            _gate = true;
            _credentials.Visible = false;
            _gateUser.Text = $"Signed in as {_remembered.User}";
            _gateUser.Visible = _signOut.Visible = true;
            ShowStatus("", false);
            _button.GrabFocus();
        }
        catch (Exception)
        {
            if (!IsInsideTree() || generation != _sessionGeneration) return;
            // Offline starts deliberately drop the saved token: the next attempt is an explicit login.
            ForgetStoredSession();
            ShowForm(_user.Text);
            ShowStatus($"The server at {ServerAddress(saved.Server)} is not answering.", true);
        }
        finally
        {
            if (api != _titleApi) api.Dispose();
            if (IsInstanceValid(this) && generation == _sessionGeneration)
            {
                _checkingSession = false;
                _button.Disabled = _installing || _signingOut;
            }
        }
    }

    private async Task LoginAndEnterAsync(string server, string user, string password, bool remember)
    {
        _titleApi?.Dispose();
        var api = _titleApi = _createApi!(server);
        using var answer = await api.LoginAsync(user, password, remember);
        LauncherStore.Update(s => s with { Server = server, User = user }, _sessionLauncherPath);
        if (remember && api.SessionToken() is { } token)
        {
            var saved = new RememberedSession(server, AnswerUser(answer.RootElement, "username") ?? user,
                token, AnswerUser(answer.RootElement, "role") ?? "");
            if (!_sessionStore!.Save(saved)) GD.PushWarning("[native] session: cannot save remembered session");
        }
        else if (!_sessionStore!.DeleteFor(server)) GD.PushWarning("[native] session: cannot delete remembered session");
        _titleApi = null; // Main now owns the live API, including while its world load awaits.
        await _accepted!(api, answer.RootElement, "");
    }

    private async Task EnterRememberedAsync()
    {
        var api = _titleApi ?? throw new InvalidOperationException("The remembered session is no longer available.");
        var saved = _remembered!;
        LauncherStore.Update(s => s with { Server = saved.Server, User = saved.User }, _sessionLauncherPath);
        _titleApi = null;
        await _accepted!(api, _gateAnswer, saved.Role);
    }

    private async Task SignOutAsync()
    {
        if (!_gate || _signOut.Disabled) return;
        _signingOut = true;
        _signOut.Disabled = _button.Disabled = true;
        ForgetStoredSession();
        var api = _titleApi;
        _titleApi = null;
        // Return to the form immediately, including when the server cannot answer.
        ShowForm(_user.Text);
        ShowStatus("Signing out…", false);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        try
        {
            if (api is not null && await api.IsAuthenticatedAsync(timeout.Token)) await api.LogoutAsync(timeout.Token);
        }
        catch (Exception) { /* Best effort: the local session has already been removed. */ }
        finally
        {
            api?.ForgetCookies(); api?.Dispose();
            if (IsInstanceValid(this) && IsInsideTree())
            {
                _signingOut = false;
                _button.Disabled = _checkingSession || _installing;
                _signOut.Disabled = false;
                ShowStatus("", false);
            }
        }
    }

    public void ShowForm(string user)
    {
        _gate = false;
        _remembered = null;
        _booting = false;
        _fields.Visible = _credentials.Visible = _serverLine.Visible = true;
        _gateUser.Visible = _signOut.Visible = _bar.Visible = _stage.Visible = _back.Visible = false;
        _user.Text = user;
        _password.Text = "";
        ShowStatus("", false);
        if (IsInsideTree()) (_user.Text.Length > 0 ? _password : _user).GrabFocus();
    }

    private void ForgetStoredSession()
    {
        if (_sessionStore?.Delete() == false) GD.PushWarning("[native] session: cannot delete remembered session");
    }

    private void CancelSessionCheck()
    {
        _sessionGeneration++;
        _checkingSession = false;
        _sessionStop?.Cancel();
        _sessionStop?.Dispose();
        _sessionStop = null;
        _titleApi?.Dispose();
        _titleApi = null;
        if (!_booting && !_loginStarted) _button.Disabled = _installing || _signingOut;
    }

    private static string? AnswerUser(JsonElement answer, string key)
        => answer.ValueKind == JsonValueKind.Object && answer.TryGetProperty("user", out var user)
            && user.ValueKind == JsonValueKind.Object && user.TryGetProperty(key, out var value)
            && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
}
