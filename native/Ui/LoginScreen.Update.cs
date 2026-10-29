using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Update;
using Godot;

namespace AnimaNative.Ui;

public partial class LoginScreen
{
    private readonly VBoxContainer _updateBox = new() { Visible = false };
    private readonly Label _updateNotice = new() { AutowrapMode = TextServer.AutowrapMode.WordSmart, CustomMinimumSize = new Vector2(280, 0) };
    private readonly Button _updateNow = new() { Text = "Update now" };
    private readonly Button _updateLater = new() { Text = "Later" };
    private readonly ProgressBar _updateBar = new() { MinValue = 0, MaxValue = 100, Visible = false };
    private ClientUpdater? _updater;
    private Action<string>? _updateLog;
    private string _launcherPath = LauncherStore.DefaultPath;
    private string _localVersion = "", _checkedServer = "";
    private UpdateRelease? _release;
    private CancellationTokenSource? _updateStop;
    private Godot.Timer? _updateDebounce;
    private Task _updateCheck = Task.CompletedTask;
    private bool _installing, _loginStarted;
    private double _downloadProgress;
    private int _updateGeneration;

    /// <summary>Enable the anonymous pre-login check; ownership of the transport passes to this screen.</summary>
    public void EnableUpdates(string localVersion, Action<string> log, ClientUpdater? updater = null, string launcherPath = LauncherStore.DefaultPath)
    {
        _launcherPath = launcherPath;
        _localVersion = localVersion;
        _updateLog = log;
        _updater = updater ?? new ClientUpdater();
        _updateBox.AddChild(_updateNotice);
        _updateBox.AddChild(_updateNow);
        _updateBox.AddChild(_updateLater);
        _updateBox.AddChild(_updateBar);
        ((VBoxContainer)_button.GetParent()).AddChild(_updateBox);
        _updateNow.Pressed += () => _ = InstallUpdateAsync();
        _updateLater.Pressed += () =>
        {
            if (_release is not { } release) return;
            LauncherStore.Update(s => s.SkipUpdate(_checkedServer, release.Version), _launcherPath);
            _updateBox.Visible = false;
        };
        _updateDebounce = new Godot.Timer { OneShot = true, WaitTime = 0.4 };
        AddChild(_updateDebounce);
        _updateDebounce.Timeout += () => _updateCheck = CheckServerAsync();
        _server.TextChanged += _ =>
        {
            _updateGeneration++;
            _updateStop?.Cancel();
            _release = null;
            _updateBox.Visible = false;
            _updateDebounce.Start();
        };
        _updateCheck = CheckServerAsync();
    }

    private async Task CheckServerAsync()
    {
        var server = LauncherSettings.NormalizeServer(_server.Text);
        if (_updater is null || server is null || _loginStarted || _installing) return;
        _checkedServer = server;
        var generation = ++_updateGeneration;
        _updateStop?.Cancel();
        _updateStop?.Dispose();
        _updateStop = new CancellationTokenSource();
        var result = await _updater.CheckAsync(server, _localVersion, _updateStop.Token);
        if (!IsInstanceValid(this) || !IsInsideTree() || generation != _updateGeneration || _loginStarted) return;
        _updateLog?.Invoke($"update: {result.Reason}");
        if (result.Release is not { } release || LauncherStore.Load(_launcherPath).IsUpdateSkipped(server, release.Version)) return;
        _release = release;
        _updateNow.Visible = ClientUpdater.CanReplace(System.Environment.GetEnvironmentVariable("APPIMAGE"));
        _updateNotice.Text = $"Update available ({release.Version})"
            + (_updateNow.Visible ? "" : $" — download from {release.DownloadUrl}");
        _updateLater.Visible = true;
        _updateBox.Visible = true;
    }

    private async Task FinishUpdateCheckAsync()
    {
        if (_updater is null) return;
        // A click on Log in flushes the typing debounce, so the anonymous check always precedes login.
        if (_updateDebounce is { } timer && !timer.IsStopped())
        {
            timer.Stop();
            _updateCheck = CheckServerAsync();
        }
        await _updateCheck;
    }

    private void EndUpdateChecks()
    {
        _loginStarted = true;
        _updateGeneration++;
        _updateDebounce?.Stop();
        _updateStop?.Cancel();
        _updateBox.Visible = false;
    }

    private async Task InstallUpdateAsync()
    {
        if (_updater is null || _release is not { } release || _installing || _loginStarted) return;
        var image = System.Environment.GetEnvironmentVariable("APPIMAGE");
        if (!ClientUpdater.CanReplace(image))
        {
            _updateNotice.Text = $"Update available ({release.Version}) — download from {release.DownloadUrl}";
            _updateNow.Visible = false;
            return;
        }
        string[] args;
        try { args = RestartArguments.Current(); }
        catch (Exception e)
        {
            _updateNotice.Text = $"Update failed: {e.Message} You can continue to log in.";
            return;
        }
        _installing = true;
        _updateNow.Disabled = _updateLater.Disabled = _button.Disabled = true;
        _server.Editable = _user.Editable = _password.Editable = false;
        _updateBar.Visible = true;
        _downloadProgress = 0;
        _updateNotice.Text = "Downloading update…";
        var result = await _updater.InstallAsync(release, image!, args, RestartAppImage,
            value => Interlocked.Exchange(ref _downloadProgress, value), _updateStop?.Token ?? default);
        if (!IsInstanceValid(this) || !IsInsideTree()) return;
        _installing = false;
        _updateLog?.Invoke($"update: {result.Reason}");
        if (result.Success) { GetTree().Quit(); return; }
        _updateNotice.Text = $"Update failed: {result.Reason} You can log in and try again later.";
        _updateBar.Visible = false;
        _updateNow.Disabled = _updateLater.Disabled = _button.Disabled = false;
        _server.Editable = _user.Editable = _password.Editable = true;
    }

    private static bool RestartAppImage(string image, System.Collections.Generic.IReadOnlyList<string> args)
    {
        var start = new ProcessStartInfo(image) { UseShellExecute = false };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        // Mount paths from the old AppImage must not leak into the new runtime.
        foreach (var key in new[] { "APPIMAGE", "APPDIR", "ARGV0" }) start.Environment.Remove(key);
        using var process = Process.Start(start);
        return process is not null;
    }

    public override void _Process(double delta)
    {
        if (_installing) _updateBar.Value = Volatile.Read(ref _downloadProgress) * 100;
    }

    public override void _ExitTree()
    {
        _updateGeneration++;
        _updateStop?.Cancel();
        _updateStop?.Dispose();
        _updater?.Dispose();
    }
}
