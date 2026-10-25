using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
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
///   --bench                     run the camera drive once the world has loaded
///   --size=WxH                  window size (bench default 1920x1080)
///   --vsync=on|off              keep V-sync during the bench (default off)
///   --quit-after-bench          exit after the result file is written
///   --scatter                   draw the scatter AND the undergrowth (default off = the browser's &amp;scatter=0)
///   --check                     offline self-test from native/fixtures, then quit
///   --check-bench               offline bench smoke: fixture world + a 2 s drive, then quit
/// </summary>
public sealed record CliOptions(string Server, string? User, string? Goto, bool Check)
{
    public const string DefaultServer = "http://localhost:8000";
    public static readonly Vector2I DefaultBenchSize = new(1920, 1080);

    public bool Bench { get; init; }
    public bool CheckBench { get; init; }
    public bool QuitAfterBench { get; init; }
    /// <summary>Both scatter layers on (<c>--scatter</c>); off by default, like the S2 runs (<c>&amp;scatter=0</c>).</summary>
    public bool Scatter { get; init; }
    /// <summary>true = keep V-sync during the bench run (<c>--vsync=on</c>).</summary>
    public bool Vsync { get; init; }
    /// <summary>Explicit <c>--size</c>; null = the project default (the bench uses <see cref="DefaultBenchSize"/>).</summary>
    public Vector2I? Size { get; init; }

    public static CliOptions FromGodot() => Parse(OS.GetCmdlineUserArgs());

    public static CliOptions Parse(IEnumerable<string> args)
    {
        string server = DefaultServer;
        string? user = null, gotoQuery = null;
        bool check = false, bench = false, checkBench = false, quit = false, vsync = false, scatter = false;
        Vector2I? size = null;
        foreach (var raw in args)
        {
            var arg = raw.Trim();
            if (arg == "--check") check = true;
            else if (arg == "--bench") bench = true;
            else if (arg == "--check-bench") checkBench = true;
            else if (arg == "--quit-after-bench") quit = true;
            else if (arg == "--scatter") scatter = true;
            else if (TryValue(arg, "--server", out var v)) server = v.TrimEnd('/');
            else if (TryValue(arg, "--user", out v)) user = v;
            else if (TryValue(arg, "--goto", out v)) gotoQuery = v;
            else if (TryValue(arg, "--size", out v)) size = ParseSize(v);
            else if (TryValue(arg, "--vsync", out v))
                vsync = v switch
                {
                    "on" => true,
                    "off" => false,
                    _ => throw new ArgumentException($"--vsync must be on or off, got '{v}'"),
                };
            else if (arg.StartsWith("--password", StringComparison.Ordinal))
                throw new ArgumentException("--password is not accepted; type it into the login screen");
            else GD.PushWarning($"[cli] ignoring unknown argument '{arg}'");
        }
        if (!Uri.TryCreate(server, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            throw new ArgumentException($"--server must be an http(s) URL, got '{server}'");
        return new CliOptions(server, string.IsNullOrWhiteSpace(user) ? null : user,
                              string.IsNullOrWhiteSpace(gotoQuery) ? null : gotoQuery, check)
        {
            Bench = bench,
            CheckBench = checkBench,
            QuitAfterBench = quit,
            Scatter = scatter,
            Vsync = vsync,
            Size = size,
        };
    }

    private static Vector2I ParseSize(string v)
    {
        var m = Regex.Match(v, @"^(\d{2,5})x(\d{2,5})$");
        if (!m.Success) throw new ArgumentException($"--size must be WIDTHxHEIGHT, got '{v}'");
        int w = int.Parse(m.Groups[1].Value), h = int.Parse(m.Groups[2].Value);
        if (w < 64 || h < 64) throw new ArgumentException($"--size is too small: '{v}'");
        return new Vector2I(w, h);
    }

    private static bool TryValue(string arg, string name, out string value)
    {
        value = "";
        if (!arg.StartsWith(name + "=", StringComparison.Ordinal)) return false;
        value = arg[(name.Length + 1)..];
        return true;
    }
}
