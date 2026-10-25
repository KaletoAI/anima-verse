using System;
using System.Collections.Generic;
using Godot;

namespace AnimaNative;

/// <summary>
/// Start parameters. They come from the command line only — after Godot's own
/// arguments and a literal <c>--</c> (<c>OS.GetCmdlineUserArgs()</c>). There is
/// no .env and no config file: the server URL is the one thing the client has to
/// know, and the password is never accepted here (it is typed into the login
/// screen and kept in memory only for the one login request).
///
///   --server=http://host:8000   base URL of the Anima server (default localhost)
///   --user=NAME                 pre-fills the login field
///   --goto=ID|NAME              bench anchor: location id or name substring
///   --check                     offline self-test from native/fixtures, then quit
/// </summary>
public sealed record CliOptions(string Server, string? User, string? Goto, bool Check)
{
    public const string DefaultServer = "http://localhost:8000";

    public static CliOptions FromGodot() => Parse(OS.GetCmdlineUserArgs());

    public static CliOptions Parse(IEnumerable<string> args)
    {
        string server = DefaultServer;
        string? user = null, gotoQuery = null;
        bool check = false;
        foreach (var raw in args)
        {
            var arg = raw.Trim();
            if (arg == "--check") check = true;
            else if (TryValue(arg, "--server", out var v)) server = v.TrimEnd('/');
            else if (TryValue(arg, "--user", out v)) user = v;
            else if (TryValue(arg, "--goto", out v)) gotoQuery = v;
            else if (arg.StartsWith("--password", StringComparison.Ordinal))
                throw new ArgumentException("--password is not accepted; type it into the login screen");
            else GD.PushWarning($"[cli] ignoring unknown argument '{arg}'");
        }
        if (!Uri.TryCreate(server, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            throw new ArgumentException($"--server must be an http(s) URL, got '{server}'");
        return new CliOptions(server, string.IsNullOrWhiteSpace(user) ? null : user,
                              string.IsNullOrWhiteSpace(gotoQuery) ? null : gotoQuery, check);
    }

    private static bool TryValue(string arg, string name, out string value)
    {
        value = "";
        if (!arg.StartsWith(name + "=", StringComparison.Ordinal)) return false;
        value = arg[(name.Length + 1)..];
        return true;
    }
}
