using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Update;
using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

public class UpdateTests
{
    public const string Local = "20261029090000-1234abcd";
    public const string Newer = "20261029100000-5678abcd";
    private static readonly byte[] Payload = Encoding.UTF8.GetBytes("new image bytes");

    [Theory]
    [InlineData(Local, Newer, true)]
    [InlineData(Local, Local, false)]
    [InlineData(Newer, Local, false)]
    [InlineData(Local, "20261029100000-1234abcd", false)]
    [InlineData(Local, "20261029090000-5678abcd", false)]
    [InlineData(Local + "-dirty", Newer, false)]
    [InlineData("development", Newer, false)]
    [InlineData(Local, Newer + "-dirty", false)]
    [InlineData(Local, Newer + "\n", false)]
    [InlineData(Local, "20260231090000-5678abcd", false)]
    public void OnlyDifferentHashAndLaterCleanCommitIsNewer(string local, string remote, bool expected)
        => Assert.Equal(expected, ReleaseVersion.IsNewer(local, remote));

    [Theory]
    [InlineData("{")]
    [InlineData("[]")]
    [InlineData("{}")]
    [InlineData("null")]
    public async Task UnusableManifestContinuesNormally(string json)
    {
        using var updater = new ClientUpdater(new Transport(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json) }));
        var result = await updater.CheckAsync("https://server", Local);
        Assert.Null(result.Release);
        Assert.NotEmpty(result.Reason);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task MissingOrOfflineContinuesNormally(bool offline)
    {
        using var updater = new ClientUpdater(new Transport(_ => offline ? throw new HttpRequestException("offline") : new HttpResponseMessage(HttpStatusCode.NotFound)));
        Assert.Null((await updater.CheckAsync("https://server", Local)).Release);
    }

    [Fact]
    public async Task ChecksAnonymousStaticUrlAndReturnsNewRelease()
    {
        using var updater = new ClientUpdater(new Transport(r =>
        {
            Assert.Equal("https://server/base/static/native/version.json", r.RequestUri!.AbsoluteUri);
            Assert.Null(r.Headers.Authorization);
            Assert.False(r.Headers.Contains("Cookie"));
            return Manifest();
        }));
        var result = await updater.CheckAsync("https://server/base/", Local);
        Assert.Equal(Newer, result.Release!.Version);
        Assert.Equal("https://server/base/static/native/release.AppImage", result.Release.DownloadUrl.AbsoluteUri);
    }

    [Theory]
    [InlineData("../release.AppImage")]
    [InlineData("https://other/release.AppImage")]
    [InlineData("a%2Fb.AppImage")]
    public async Task ManifestCannotRedirectDownloadOutsideStaticNative(string file)
    {
        using var updater = new ClientUpdater(new Transport(_ => Manifest(file: file)));
        Assert.Null((await updater.CheckAsync("https://server", Local)).Release);
    }

    [Fact]
    public async Task EmbeddedCredentialsAreNeverSent()
    {
        using var updater = new ClientUpdater(new Transport(_ => throw new Exception("request must not be sent")));
        Assert.Null((await updater.CheckAsync("https://user:secret@server", Local)).Release);
    }

    [Theory]
    [InlineData("size")]
    [InlineData("sha")]
    [InlineData("restart")]
    [InlineData("offline")]
    [InlineData("success")]
    public async Task InstallVerifiesBeforeSwapAndRollsBackOnRestartFailure(string outcome)
    {
        var dir = Path.Combine(Path.GetTempPath(), "anima-update-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var image = Path.Combine(dir, "client.AppImage");
        await File.WriteAllTextAsync(image, "old image");
        int restarts = 0;
        double progress = 0;
        try
        {
            using var updater = new ClientUpdater(new Transport(r => r.RequestUri!.AbsolutePath.EndsWith("version.json")
                ? Manifest(size: outcome == "size" ? Payload.Length + 1 : Payload.Length, sha: outcome == "sha" ? new string('0', 64) : null)
                : outcome == "offline" ? throw new HttpRequestException("download offline")
                : new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Payload) }));
            var release = (await updater.CheckAsync("https://server", Local)).Release!;
            var result = await updater.InstallAsync(release, image, new[] { "--", "--user=Name With Spaces" }, (path, args) =>
            {
                restarts++;
                Assert.Equal(image, path);
                Assert.Equal(new[] { "--", "--user=Name With Spaces" }, args);
                Assert.Equal(Payload, File.ReadAllBytes(image));
                if (!OperatingSystem.IsWindows()) Assert.True((File.GetUnixFileMode(image) & UnixFileMode.UserExecute) != 0);
                return outcome != "restart";
            }, p => progress = p);
            Assert.Equal(outcome == "success", result.Success);
            Assert.Equal(outcome is "success" or "restart" ? 1 : 0, restarts);
            if (result.Success) { Assert.Equal(Payload, await File.ReadAllBytesAsync(image)); Assert.Equal(1d, progress); }
            else { Assert.Equal("old image", await File.ReadAllTextAsync(image)); Assert.NotEmpty(result.Reason); }
            Assert.Single(Directory.GetFiles(dir));
        }
        finally { Directory.Delete(dir, true); }
    }

    [Fact]
    public void SkippedReleasePersistsPerServerUntilANewerCommitAppears()
    {
        var settings = new LauncherSettings().SkipUpdate("https://server/", Newer);
        settings = LauncherSettings.Parse(settings.Serialize());
        Assert.True(settings.IsUpdateSkipped("https://server", Newer));
        Assert.True(settings.IsUpdateSkipped("https://server", Local));
        Assert.False(settings.IsUpdateSkipped("https://other", Newer));
        Assert.False(settings.IsUpdateSkipped("https://server", "20261029110000-90abcdef"));
        Assert.DoesNotContain("password", settings.Serialize());
    }

    [Fact]
    public async Task InterruptedManifestContinuesNormally()
    {
        using var updater = new ClientUpdater(new Transport(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new InterruptedStream()) }));
        var result = await updater.CheckAsync("https://server", Local);
        Assert.Null(result.Release);
        Assert.Contains("interrupted", result.Reason);
    }

    [Fact]
    public void RestartArgumentsPreserveEngineFlagsSpacesAndEmptyArguments()
    {
        var raw = Encoding.UTF8.GetBytes("/mounted/client\0--headless\0--rendering-method\0gl_compatibility\0--\0--user=two words\0\0");
        Assert.Equal(new[] { "--headless", "--rendering-method", "gl_compatibility", "--", "--user=two words", "" },
            RestartArguments.FromLinuxCommandLine(raw));
    }

    private static HttpResponseMessage Manifest(string file = "release.AppImage", int? size = null, string? sha = null)
        => new(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(new {
            version = Newer, file, size = size ?? Payload.Length,
            sha256 = sha ?? Convert.ToHexString(SHA256.HashData(Payload)), built_utc = "2026-10-29T10:00:00Z"
        })) };

    private sealed class InterruptedStream : MemoryStream
    {
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
            => throw new IOException("body interrupted");
    }

    private sealed class Transport(Func<HttpRequestMessage, HttpResponseMessage> respond) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(respond(request));
    }
}
