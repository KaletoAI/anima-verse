using System;
using System.IO;
using System.Text.Json;

namespace AnimaNative.Ui;

/// <summary>One explicitly remembered session. Never includes a password; diagnostic text excludes the token.</summary>
public sealed record RememberedSession(string Server, string User, string Token, string Role)
{
    public override string ToString() => $"RememberedSession {{ Server = {Server}, User = {User}, Role = {Role} }}";
}

/// <summary>The private session.json file; callers supply the globalized user path. IO failures are cache misses.</summary>
public sealed class SessionStore
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private const UnixFileMode PrivateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
    public string Path { get; }
    public SessionStore(string path) => Path = System.IO.Path.GetFullPath(path);

    public RememberedSession? LoadFor(string server)
    {
        try
        {
            var entry = JsonSerializer.Deserialize<RememberedSession>(File.ReadAllText(Path), Json);
            var normalized = LauncherSettings.NormalizeServer(server);
            return entry is not null && normalized is not null
                && LauncherSettings.NormalizeServer(entry.Server) == normalized
                && !string.IsNullOrWhiteSpace(entry.User) && !string.IsNullOrWhiteSpace(entry.Token) && entry.Role is not null
                ? entry with { Server = normalized } : null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or ArgumentException) { return null; }
    }

    public bool Save(RememberedSession entry)
    {
        string tmp = Path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
            var options = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
            if (OperatingSystem.IsLinux()) options.UnixCreateMode = PrivateMode;
            using (var file = new FileStream(tmp, options))
            {
                // Set before writing any secret, including when replacing an older, less private file.
                if (OperatingSystem.IsLinux()) File.SetUnixFileMode(tmp, PrivateMode);
                JsonSerializer.Serialize(file, entry, Json);
                file.Flush(flushToDisk: true);
            }
            File.Move(tmp, Path, overwrite: true);
            return true;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
        finally { try { File.Delete(tmp); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { } }
    }

    public bool Delete()
    {
        try { File.Delete(Path); return true; }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
    }

    public bool DeleteFor(string server) => LoadFor(server) is null || Delete();
}
