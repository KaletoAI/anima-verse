using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Ui;
using AnimaNative.Update;
using Godot;

namespace AnimaNative.Check;

/// <summary>Offline update proof. Only uniquely named temporary images and launcher files are modified.</summary>
public static class UpdateCheck
{
    private const string Local = "20261029090000-1234abcd", Newer = "20261029100000-5678abcd";
    private static readonly byte[] Bytes = Encoding.UTF8.GetBytes("fixture AppImage bytes\n");

    public static async Task<string> RunAsync(Node host)
    {
        var originalArgs = RestartArguments.Current();
        if (DisplayServer.GetName() == "headless") Expect("engine arguments retained", originalArgs.Contains("--headless"));
        Expect("check arguments retained", originalArgs.Contains("--check") || originalArgs.Any(a => a.StartsWith("--check=")));
        int comparisons = 0, installs = 0;
        foreach (var (local, remote, expected) in new[]
        {
            (Local, Local, false), (Local, Newer, true), (Newer, Local, false),
            (Local + "-dirty", Newer, false), ("development", Newer, false),
            (Local, "20261029100000-1234abcd", false), (Local, "20261029090000-5678abcd", false),
            (Local, "garbled", false), (Local, "offline", false)
        })
        {
            using var updater = Updater(remote);
            var result = await updater.CheckAsync("https://fixture.invalid", local);
            Expect("comparison " + remote, (result.Release is not null) == expected);
            comparisons++;
        }
        var dir = Path.Combine(Path.GetTempPath(), "anima-update-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            foreach (var scenario in new[] { "size", "sha", "offline-download", "restart", "success" })
            {
                var image = Path.Combine(dir, "client.AppImage");
                await File.WriteAllTextAsync(image, "old fixture bytes");
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(image, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                using var updater = Updater(Newer, scenario);
                var release = (await updater.CheckAsync("https://fixture.invalid", Local)).Release!;
                var restarts = 0;
                double progress = 0;
                var result = await updater.InstallAsync(release, image, new[] { "--", "--user=two words" }, (path, args) =>
                {
                    restarts++;
                    Expect("restart path and arguments", path == image && args.SequenceEqual(new[] { "--", "--user=two words" }));
                    Expect("verified bytes before restart", File.ReadAllBytes(image).SequenceEqual(Bytes));
                    if (!OperatingSystem.IsWindows()) Expect("executable before restart", (File.GetUnixFileMode(image) & UnixFileMode.UserExecute) != 0);
                    return scenario != "restart";
                }, value => progress = value);
                Expect("install " + scenario, result.Success == (scenario == "success"));
                Expect("restart count", restarts == (scenario is "success" or "restart" ? 1 : 0));
                Expect("directory cleanup", Directory.GetFiles(dir).Length == 1);
                if (result.Success)
                {
                    Expect("swapped bytes", File.ReadAllBytes(image).SequenceEqual(Bytes));
                    Expect("progress", progress == 1);
                }
                else
                {
                    Expect("old image retained", File.ReadAllText(image) == "old fixture bytes");
                    Expect("failure reason", result.Reason.Length > 0);
                    if (!OperatingSystem.IsWindows()) Expect("old mode retained", (File.GetUnixFileMode(image) & UnixFileMode.UserExecute) == 0);
                }
                File.Delete(image);
                installs++;
            }
            var uiCases = await CheckUiAsync(host, dir);
            return $"update comparisons={comparisons} installs={installs} ui_cases={uiCases}";
        }
        finally { Directory.Delete(dir, true); }
    }

    private static async Task<int> CheckUiAsync(Node host, string dir)
    {
        var launcher = Path.Combine(dir, "launcher.json");
        var logs = new List<string>();
        var screen = new LoginScreen().Setup("https://fixture.invalid", "");
        host.AddChild(screen);
        try
        {
            screen.EnableUpdates(Local, logs.Add, Updater(Newer), launcher);
            await host.ToSignal(host.GetTree().CreateTimer(0.05), SceneTreeTimer.SignalName.Timeout);
            Expect("notice before login", Descendants(screen).OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text.Contains($"A new version is available ({Newer})")));
            Expect("one check log", logs.Count == 1);
            Descendants(screen).OfType<Button>().Single(b => b.Text == "Later").EmitSignal(BaseButton.SignalName.Pressed);
            Expect("skip persisted", LauncherStore.Load(launcher).IsUpdateSkipped("https://fixture.invalid", Newer));
        }
        finally { screen.Free(); }
        var skipped = new LoginScreen().Setup("https://fixture.invalid", "");
        host.AddChild(skipped);
        try
        {
            skipped.EnableUpdates(Local, _ => { }, Updater(Newer), launcher);
            await host.ToSignal(host.GetTree().CreateTimer(0.05), SceneTreeTimer.SignalName.Timeout);
            Expect("skip hides notice", !Descendants(skipped).OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text.Contains("A new version is available")));
        }
        finally { skipped.Free(); }
        Expect("newer than skip returns", !LauncherStore.Load(launcher).IsUpdateSkipped("https://fixture.invalid", "20261029110000-90abcdef"));
        File.Delete(launcher);
        return 4;
    }

    private static IEnumerable<Node> Descendants(Node parent)
    {
        foreach (var child in parent.GetChildren())
        {
            yield return child;
            foreach (var descendant in Descendants(child)) yield return descendant;
        }
    }

    private static ClientUpdater Updater(string remote, string scenario = "success")
        => new(new FixtureTransport(request =>
        {
            Expect("anonymous", request.Headers.Authorization is null && !request.Headers.Contains("Cookie"));
            if (remote == "offline") throw new HttpRequestException("fixture offline");
            if (request.RequestUri!.AbsolutePath == "/static/native/version.json")
            {
                var json = remote == "garbled" ? "{" : JsonSerializer.Serialize(new
                {
                    version = remote, file = "fixture.AppImage", size = Bytes.Length + (scenario == "size" ? 1 : 0),
                    sha256 = scenario == "sha" ? new string('0', 64) : Convert.ToHexString(SHA256.HashData(Bytes)),
                    built_utc = "2026-10-29T10:00:00Z"
                });
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json) };
            }
            Expect("download path", request.RequestUri.AbsoluteUri == "https://fixture.invalid/static/native/fixture.AppImage");
            if (scenario == "offline-download") throw new HttpRequestException("fixture download offline");
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Bytes) };
        }));

    private sealed class FixtureTransport(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(response(request));
    }

    private static void Expect(string what, bool value)
    {
        if (!value) throw new InvalidOperationException("update: " + what);
    }
}
