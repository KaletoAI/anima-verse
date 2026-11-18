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
    private static readonly ECDsa ReleaseKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
    private static readonly string PublicKey = Convert.ToBase64String(ReleaseKey.ExportSubjectPublicKeyInfo());

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
        using var updater = new ClientUpdater(new Transport(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json) }), PublicKey);
        var result = await updater.CheckAsync("https://server", Local);
        Assert.Null(result.Release);
        Assert.NotEmpty(result.Reason);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task MissingOrOfflineContinuesNormally(bool offline)
    {
        using var updater = new ClientUpdater(new Transport(_ => offline ? throw new HttpRequestException("offline") : new HttpResponseMessage(HttpStatusCode.NotFound)), PublicKey);
        Assert.Null((await updater.CheckAsync("https://server", Local)).Release);
    }

    [Fact]
    public async Task ChecksAnonymousStaticUrlAndReturnsNewRelease()
    {
        var requested = new System.Collections.Generic.List<string>();
        using var updater = new ClientUpdater(new Transport(r =>
        {
            requested.Add(r.RequestUri!.AbsoluteUri);
            Assert.Null(r.Headers.Authorization);
            Assert.False(r.Headers.Contains("Cookie"));
            return Signed(r);
        }), PublicKey);
        var result = await updater.CheckAsync("https://server/base/", Local);
        Assert.Equal(new[] { "https://server/base/static/native/version.json", "https://server/base/static/native/version.json.sig" }, requested);
        Assert.Equal(Newer, result.Release!.Version);
        Assert.Equal("https://server/base/static/native/release.AppImage", result.Release.DownloadUrl.AbsoluteUri);
    }

    [Theory]
    [InlineData("no-key")]
    [InlineData("other-key")]
    [InlineData("missing")]
    [InlineData("garbage")]
    [InlineData("oversized")]
    [InlineData("tampered")]
    [InlineData("built-only")]
    public async Task OnlyAManifestSignedWithTheBakedKeyIsOffered(string scenario)
    {
        using var otherKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var key = scenario switch
        {
            "no-key" => "",
            "other-key" => Convert.ToBase64String(otherKey.ExportSubjectPublicKeyInfo()),
            _ => PublicKey
        };
        var honestSha = Convert.ToHexString(SHA256.HashData(Payload));
        using var updater = new ClientUpdater(new Transport(r => r.RequestUri!.AbsolutePath.EndsWith(".sig")
            ? (scenario switch
            {
                "missing" => new HttpResponseMessage(HttpStatusCode.NotFound),
                "garbage" => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[] { 0x30, 0x02, 0x01 }) },
                "oversized" => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[UpdateSignature.MaxSignatureBytes + 1]) },
                // "tampered": the signature covers the honest SHA-256, the served manifest names another one.
                _ => Signature(Payload.Length, honestSha)
            })
            : scenario == "tampered" ? Manifest(sha: new string('a', 64))
            : scenario == "built-only" ? Manifest(built: "2030-01-01T00:00:00Z")
            : Manifest()), key);
        var result = await updater.CheckAsync("https://server", Local);
        // built_utc is not part of the signed bytes, so changing it alone keeps the release valid.
        Assert.Equal(scenario == "built-only", result.Release is not null);
        Assert.NotEmpty(result.Reason);
    }

    [Fact]
    public void CanonicalBytesMatchThePublisher()
    {
        // The worked example of scripts/smoke_update_signing.py: sha256 is lowercased, size is plain decimal.
        var bytes = UpdateSignature.Canonical("20261029090000-1234abcd", "AnimaNative-20261029090000-1234abcd-x86_64.AppImage", 16,
            "3A2F0E5C6D1B4A7988C0D2E4F6A8B0C1D3E5F7091B2D4F6081A3C5E7092B4D6F");
        Assert.Equal("anima-native-update-v1\nversion=20261029090000-1234abcd\nfile=AnimaNative-20261029090000-1234abcd-x86_64.AppImage\nsize=16\n"
            + "sha256=3a2f0e5c6d1b4a7988c0d2e4f6a8b0c1d3e5f7091b2d4f6081a3c5e7092b4d6f\n", Encoding.UTF8.GetString(bytes));
    }

    [Theory]
    [InlineData("../release.AppImage")]
    [InlineData("https://other/release.AppImage")]
    [InlineData("a%2Fb.AppImage")]
    public async Task ManifestCannotRedirectDownloadOutsideStaticNative(string file)
    {
        // Correctly signed, so only the file-name rule can refuse it.
        using var updater = new ClientUpdater(new Transport(r => r.RequestUri!.AbsolutePath.EndsWith(".sig")
            ? Signature(Payload.Length, Convert.ToHexString(SHA256.HashData(Payload)), file) : Manifest(file: file)), PublicKey);
        Assert.Null((await updater.CheckAsync("https://server", Local)).Release);
    }

    [Fact]
    public async Task EmbeddedCredentialsAreNeverSent()
    {
        using var updater = new ClientUpdater(new Transport(_ => throw new Exception("request must not be sent")), PublicKey);
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
            // "size"/"sha": a correctly SIGNED manifest whose values the downloaded bytes do not match.
            var size = outcome == "size" ? Payload.Length + 1 : Payload.Length;
            var sha = outcome == "sha" ? new string('0', 64) : Convert.ToHexString(SHA256.HashData(Payload));
            using var updater = new ClientUpdater(new Transport(r => r.RequestUri!.AbsolutePath.EndsWith("version.json")
                ? Manifest(size: size, sha: sha)
                : r.RequestUri.AbsolutePath.EndsWith("version.json.sig") ? Signature(size, sha)
                : outcome == "offline" ? throw new HttpRequestException("download offline")
                : new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Payload) }), PublicKey);
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
    public async Task InstallReverifiesTheSignatureBeforeDownloading()
    {
        var dir = Path.Combine(Path.GetTempPath(), "anima-update-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var image = Path.Combine(dir, "client.AppImage");
        await File.WriteAllTextAsync(image, "old image");
        try
        {
            using var updater = new ClientUpdater(new Transport(r => r.RequestUri!.AbsolutePath.EndsWith("version.json") ? Manifest()
                : r.RequestUri.AbsolutePath.EndsWith(".sig") ? Signature(Payload.Length, Convert.ToHexString(SHA256.HashData(Payload)))
                : throw new Exception("a forged release must not be downloaded")), PublicKey);
            var release = (await updater.CheckAsync("https://server", Local)).Release!;
            var forged = release with { Sha256 = new string('b', 64) };
            var result = await updater.InstallAsync(forged, image, Array.Empty<string>(), (_, _) => throw new Exception("must not restart"));
            Assert.False(result.Success);
            Assert.Contains("signature", result.Reason);
            Assert.Equal("old image", await File.ReadAllTextAsync(image));
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
        using var updater = new ClientUpdater(new Transport(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new InterruptedStream()) }), PublicKey);
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

    [Fact]
    public void RestartArgumentsDropAppRunsLogFilePairs()
    {
        // AppRun's own pair (and two accumulated by older restarts) go; the engine/client split stays.
        var raw = Encoding.UTF8.GetBytes("/mounted/client\0--log-file\0/logs/b.engine.log\0--log-file\0/logs/a.engine.log\0--headless\0--\0--log-file\0client value\0");
        Assert.Equal(new[] { "--headless", "--", "--log-file", "client value" },
            RestartArguments.FromLinuxCommandLine(raw));
        var dangling = Encoding.UTF8.GetBytes("/mounted/client\0--log-file\0");
        Assert.Equal(new[] { "--log-file" }, RestartArguments.FromLinuxCommandLine(dangling));
    }

    private static HttpResponseMessage Manifest(string file = "release.AppImage", int? size = null, string? sha = null, string built = "2026-10-29T10:00:00Z")
        => new(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(new {
            version = Newer, file, size = size ?? Payload.Length,
            sha256 = sha ?? Convert.ToHexString(SHA256.HashData(Payload)), built_utc = built
        })) };

    /// <summary>The release key's DER signature over the canonical fields, as publish_appimage.py writes it.</summary>
    private static HttpResponseMessage Signature(long size, string sha, string file = "release.AppImage")
        => new(HttpStatusCode.OK) { Content = new ByteArrayContent(ReleaseKey.SignData(UpdateSignature.Canonical(Newer, file, size, sha),
            HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence)) };

    /// <summary>The default signed release: manifest and its matching signature.</summary>
    private static HttpResponseMessage Signed(HttpRequestMessage request)
        => request.RequestUri!.AbsolutePath.EndsWith(".sig") ? Signature(Payload.Length, Convert.ToHexString(SHA256.HashData(Payload))) : Manifest();

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
