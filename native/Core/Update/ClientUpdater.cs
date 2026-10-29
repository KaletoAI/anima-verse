using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Ui;

namespace AnimaNative.Update;

public static class ReleaseVersion
{
    private static readonly Regex Format = new(@"\A(\d{14})-([0-9a-fA-F]{7,40})\z", RegexOptions.CultureInvariant);

    private static (DateTime Time, string Hash)? Parse(string version)
    {
        var m = Format.Match(version);
        return m.Success && DateTime.TryParseExact(m.Groups[1].Value, "yyyyMMddHHmmss", CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var time)
            ? (time, m.Groups[2].Value) : null;
    }

    public static bool IsNewer(string local, string remote)
        => Parse(local) is { } a && Parse(remote) is { } b && b.Time > a.Time
           && !string.Equals(a.Hash, b.Hash, StringComparison.OrdinalIgnoreCase);

    public static bool IsClean(string version) => Parse(version) is not null;
}

public sealed record UpdateRelease(string Version, Uri DownloadUrl, long Size, string Sha256);
public sealed record UpdateCheckResult(UpdateRelease? Release, string Reason);
public sealed record UpdateInstallResult(bool Success, string Reason);

/// <summary>Anonymous update transport and verified same-directory AppImage replacement.</summary>
public sealed class ClientUpdater : IDisposable
{
    private readonly HttpClient _http;

    public ClientUpdater(HttpMessageHandler? transport = null)
    {
        // Keep this client separate from every authenticated API and the browser cookie jar.
        _http = new HttpClient(transport ?? new HttpClientHandler
        {
            UseCookies = false, UseDefaultCredentials = false, AllowAutoRedirect = false
        }) { Timeout = Timeout.InfiniteTimeSpan };
    }

    public async Task<UpdateCheckResult> CheckAsync(string server, string localVersion, CancellationToken cancellation = default)
    {
        try
        {
            var normalized = LauncherSettings.NormalizeServer(server);
            if (normalized is null) return new(null, "invalid server address");
            var baseUri = new Uri(normalized + "/");
            if (baseUri.UserInfo.Length != 0 || baseUri.Query.Length != 0 || baseUri.Fragment.Length != 0)
                return new(null, "update server must have no credentials, query or fragment");
            using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
            stop.CancelAfter(TimeSpan.FromSeconds(5));
            using var response = await _http.GetAsync(new Uri(baseUri, "static/native/version.json"), HttpCompletionOption.ResponseHeadersRead, stop.Token).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();
            await using var body = await response.Content.ReadAsStreamAsync(stop.Token).ConfigureAwait(false);
            using var manifest = new MemoryStream();
            var chunk = new byte[4096];
            int count;
            while ((count = await body.ReadAsync(chunk, stop.Token).ConfigureAwait(false)) != 0)
            {
                if (manifest.Length + count > 16384) return new(null, "update manifest is too large");
                manifest.Write(chunk, 0, count);
            }
            using var json = JsonDocument.Parse(manifest.ToArray());
            var root = json.RootElement;
            var version = root.GetProperty("version").GetString() ?? "";
            var file = root.GetProperty("file").GetString() ?? "";
            var size = root.GetProperty("size").GetInt64();
            var sha = root.GetProperty("sha256").GetString() ?? "";
            var built = root.GetProperty("built_utc").GetString();
            if (!ReleaseVersion.IsClean(version) || !Regex.IsMatch(file, @"\A[A-Za-z0-9][A-Za-z0-9._-]*\.AppImage\z")
                || size <= 0 || !Regex.IsMatch(sha, @"\A[0-9a-fA-F]{64}\z")
                || !DateTimeOffset.TryParse(built, CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
                return new(null, "invalid update manifest");
            return ReleaseVersion.IsNewer(localVersion, version)
                ? new(new(version, new Uri(baseUri, "static/native/" + file), size, sha), "newer release available")
                : new(null, "no newer clean commit (or local development build)");
        }
        catch (Exception e) when (e is HttpRequestException or IOException or OperationCanceledException or JsonException
                                  or InvalidOperationException or KeyNotFoundException or FormatException or UriFormatException)
        {
            return new(null, $"update check unavailable: {e.Message}");
        }
    }

    /// <summary>Probe without modifying the running image; installation also checks directory permissions.</summary>
    public static bool CanReplace(string? appImage)
    {
        if (string.IsNullOrWhiteSpace(appImage) || !Path.IsPathFullyQualified(appImage) || !File.Exists(appImage)) return false;
        try
        {
            if ((File.GetAttributes(appImage) & (FileAttributes.Directory | FileAttributes.ReparsePoint)) != 0) return false;
            // Opening a running ELF for writing yields ETXTBSY even when rename is permitted.
            if (OperatingSystem.IsLinux()) return Access(appImage, 2) == 0;
            using var probe = new FileStream(appImage, FileMode.Open, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete);
            return true;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
    }

    public async Task<UpdateInstallResult> InstallAsync(UpdateRelease release, string appImage, IReadOnlyList<string> args,
        Func<string, IReadOnlyList<string>, bool> restart, Action<double>? progress = null, CancellationToken cancellation = default)
    {
        string? temp = null, backup = null;
        bool swapped = false, retainBackup = false;
        try
        {
            if (!CanReplace(appImage)) return new(false, "The AppImage is not writable.");
            temp = appImage + ".update-" + Guid.NewGuid().ToString("N");
            backup = temp + ".backup";
            using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
            stop.CancelAfter(TimeSpan.FromMinutes(30));
            using var response = await _http.GetAsync(release.DownloadUrl, HttpCompletionOption.ResponseHeadersRead, stop.Token).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            await using (var input = await response.Content.ReadAsStreamAsync(stop.Token).ConfigureAwait(false))
            await using (var output = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 131072, true))
            {
                var buffer = new byte[131072];
                long total = 0;
                int read;
                while ((read = await input.ReadAsync(buffer, stop.Token).ConfigureAwait(false)) != 0)
                {
                    total += read;
                    if (total > release.Size) throw new InvalidDataException("Download size mismatch.");
                    await output.WriteAsync(buffer.AsMemory(0, read), stop.Token).ConfigureAwait(false);
                    hash.AppendData(buffer, 0, read);
                    progress?.Invoke((double)total / release.Size);
                }
                if (total != release.Size) throw new InvalidDataException("Download size mismatch.");
                if (!Convert.ToHexString(hash.GetHashAndReset()).Equals(release.Sha256, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Download SHA-256 mismatch.");
                await output.FlushAsync(stop.Token).ConfigureAwait(false);
                output.Flush(true);
            }
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(temp, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                    | UnixFileMode.GroupRead | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
            cancellation.ThrowIfCancellationRequested();
            // Retain the previous bytes and mode until the replacement process was started.
            File.Copy(appImage, backup);
            File.Move(temp, appImage, true);
            swapped = true;
            if (!restart(appImage, args)) throw new IOException("Could not restart the updated AppImage.");
            return new(true, "Update installed; restarting.");
        }
        catch (Exception e)
        {
            if (swapped && backup is not null)
            {
                try { File.Move(backup, appImage, true); }
                catch (Exception rollback) { retainBackup = true; return new(false, $"{e.Message} Restore failed: {rollback.Message}. Previous image: {backup}"); }
            }
            return new(false, e.Message);
        }
        finally
        {
            TryDelete(temp);
            if (!retainBackup) TryDelete(backup);
        }
    }

    [DllImport("libc", EntryPoint = "access", SetLastError = true)]
    private static extern int Access(string path, int mode);

    private static void TryDelete(string? path)
    {
        try { if (path is not null) File.Delete(path); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }

    public void Dispose() => _http.Dispose();
}
