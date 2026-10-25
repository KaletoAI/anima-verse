using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Godot;

namespace AnimaNative;

/// <summary>
/// Start parameters. They come from the command line only — after Godot's own
/// arguments and a literal <c>--</c> (<c>OS.GetCmdlineUserArgs()</c>). None is
/// required: the launcher remembers server and user name in
/// <c>user://launcher.json</c> (<see cref="Ui.LauncherStore"/>), and a flag given
/// here wins over the remembered value for this start. There is no .env; the
/// password is never accepted here (it is typed into the login screen and kept
/// in memory only for the one login request).
///
///   --server=URL                pre-fills the server field (http(s); "host:port" gets http://)
///   --user=NAME                 pre-fills the user field
///   --goto=ID|NAME              bench anchor: location id or name substring
///   --bench                     run the camera drive once the world has loaded
///   --size=WxH                  window size (bench default 1920x1080)
///   --vsync=on|off              keep V-sync during the bench (default off)
///   --quit-after-bench          exit after the result file is written
///   --no-scatter                hide the scatter AND the undergrowth (default on, like the browser; = &amp;scatter=0)
///   --plain-ground              the S1a one-colour terrain instead of the browser's ground surfaces (Task S3b)
///   --no-hud                    no React HUD over the world (default: the HUD via gdCEF when native/cef_artifacts is linked)
///   --no-water                  no water (the terrain's water variant off; = &amp;water=0)
///   --offline=DIR               build the world from a payload dump (native/tools/dump_payloads.py) instead of a
///                               server: no login, no HUD; prints the world/scatter/figure summary lines, then quits
///                               (with --bench: runs the drive, then quits)
///   --verify                    § B5a: log the full verify table of every mounted location (default: only
///                               locations with a deviation, like the browser without ?verify=1)
///   --check                     offline self-test from native/fixtures, then quit
///   --check verify | --check=verify   only the § B5a section of the self-test (fixture world + S3c world)
///   --check-bench               offline bench smoke: fixture world + a 2 s drive, then quit
/// </summary>
public sealed record CliOptions(string? Server, string? User, string? Goto, bool Check)
{
    public static readonly Vector2I DefaultBenchSize = new(1920, 1080);

    public bool Bench { get; init; }
    public bool CheckBench { get; init; }
    public bool QuitAfterBench { get; init; }
    /// <summary>Both scatter layers on — the default, like the browser; <c>--no-scatter</c> = the browser's <c>&amp;scatter=0</c>.</summary>
    public bool Scatter { get; init; }
    /// <summary><c>--plain-ground</c>: keep the plain vertex-colour terrain (no layer masks, no surface textures).</summary>
    public bool PlainGround { get; init; }
    /// <summary><c>--no-hud</c>: skip the gdCEF HUD overlay (Task S4) even when the extension is linked.</summary>
    public bool NoHud { get; init; }
    /// <summary><c>--no-water</c>: no water lift / water variant — the browser bench's <c>&amp;water=0</c> (Task S3c).</summary>
    public bool NoWater { get; init; }
    /// <summary><c>--offline=DIR</c>: the payload dump to build from (Task S3c), null = online.</summary>
    public string? Offline { get; init; }
    /// <summary>true = keep V-sync during the bench run (<c>--vsync=on</c>).</summary>
    public bool Vsync { get; init; }
    /// <summary>Explicit <c>--size</c>; null = the project default (the bench uses <see cref="DefaultBenchSize"/>).</summary>
    public Vector2I? Size { get; init; }
    /// <summary><c>--verify</c>: the full § B5a table per mounted location (the browser's <c>?verify=1</c>).</summary>
    public bool Verify { get; init; }
    /// <summary><c>--check verify</c>: run only that section of the self-test; null = all of it.</summary>
    public string? CheckOnly { get; init; }

    public static CliOptions FromGodot() => Parse(OS.GetCmdlineUserArgs());

    public static CliOptions Parse(IEnumerable<string> args)
    {
        string? server = null;
        string? user = null, gotoQuery = null;
        bool check = false, bench = false, checkBench = false, quit = false, vsync = false, scatter = true, noHud = false, plainGround = false;
        bool noWater = false, verify = false;
        string? offline = null, checkOnly = null;
        Vector2I? size = null;
        foreach (var raw in args)
        {
            var arg = raw.Trim();
            if (arg == "--check") check = true;
            else if (TryValue(arg, "--check", out var only)) { check = true; checkOnly = CheckSection(only); }
            else if (check && checkOnly is null && arg == "verify") checkOnly = "verify";
            else if (arg == "--verify") verify = true;
            else if (arg == "--bench") bench = true;
            else if (arg == "--check-bench") checkBench = true;
            else if (arg == "--quit-after-bench") quit = true;
            else if (arg == "--no-scatter") scatter = false;
            else if (arg == "--scatter") scatter = true;
            else if (arg == "--no-hud") noHud = true;
            else if (arg == "--plain-ground") plainGround = true;
            else if (arg == "--no-water") noWater = true;
            else if (TryValue(arg, "--offline", out var off)) offline = off;
            else if (TryValue(arg, "--server", out var v))
                server = Ui.LauncherSettings.NormalizeServer(v)
                         ?? throw new ArgumentException($"--server must be an http(s) URL, got '{v}'");
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
        return new CliOptions(server, string.IsNullOrWhiteSpace(user) ? null : user,
                              string.IsNullOrWhiteSpace(gotoQuery) ? null : gotoQuery, check)
        {
            Bench = bench,
            CheckBench = checkBench,
            QuitAfterBench = quit,
            Scatter = scatter,
            NoHud = noHud,
            PlainGround = plainGround,
            NoWater = noWater,
            Offline = string.IsNullOrWhiteSpace(offline) ? null : offline,
            Vsync = vsync,
            Size = size,
            Verify = verify,
            CheckOnly = checkOnly,
        };
    }

    private static string CheckSection(string v) => v == "verify"
        ? v : throw new ArgumentException($"--check= knows only 'verify', got '{v}'");

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
