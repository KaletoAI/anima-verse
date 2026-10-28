using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Godot;
using AnimaNative.Overview;

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
///   --bench-matrix[=A,B,…]      the drive once per variant in ONE process, each pass with one feature switched off at
///                               runtime and a baseline pass between every two variants (drift: each variant against
///                               its two neighbouring baselines) (Task 26b/26c, Bench/BenchSwitches.cs; README "Bench
///                               matrix"); =A,B,… runs only those variants (plus the baselines). Implies --bench for
///                               window, start and quit rules
///   --fog=compute|pass          the distance fog as ONE compute pass (default since Task 26c; needs a GPU, falls back to
///                               the screen pass by itself) or as the screen-texture pass (the fallback)
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
///   --fly=M[,DEG]               after the boot, fly the camera target M metres in a straight line (heading DEG, 0 = +x,
///                               90 = +z; default 0) at 50 m/s and log the terrain streaming (tiles taken/evicted, the
///                               longest frame while streaming); with --offline it then quits (Task 24)
///   --verify                    § B5a: log the full verify table of every mounted location (default: only
///                               locations with a deviation, like the browser without ?verify=1)
///   --msaa=0|2|4|8              3D multisample anti-aliasing; overrides the menu's Graphics tab (Task 26d) for the whole
///                               run (bench reproducibility). Not given: the stored Graphics tab level (default 2x),
///                               a bench run 4x like before the setting existed
///   --check                     offline self-test from native/fixtures, then quit
///   --check verify | --check=verify   only the § B5a section of the self-test (fixture world + S3c world)
///   --check storeys | --check=storeys only the storey section (fixtures/storeys: the switch at runtime, Task 16)
///   --check placement | --check=placement only the room placement section (fixtures/placement: seats, surfaces, storeys,
///                               closed interiors, the fallback pool, Task 29)
///   --check fidelity | --check=fidelity only the model-fidelity section (fixtures/fidelity: cuts, tiers, re-datum, sweep, Task 17)
///   --check props | --check=props     only the props section (fixtures/props: slots, mirrors, lights, doors, ambience, Task 18)
///   --check light | --check=light     only the light section (game-hour stage, hemisphere, shadow fit, MSAA, Task 21)
///   --check fog | --check=fog         only the distance-fog section (the screen pass, factor, colour, Task 22)
///   --check backdrop | --check=backdrop only the backdrop section (payload, strips, heights, tint, Task 22)
///   --check terrain | --check=terrain   only the CDLOD terrain section (field, selection, instances, shader twin, Task 23)
///   --check stream | --check=stream     only the terrain streaming section (fake server: batches, LRU, masks, signatures, Task 24)
///   --check water | --check=water       only the water section (shore, falls, ghosts, prop water, Task 25)
///   --check scatter | --check=scatter   only the scatter section (S3 reference + the worker rebuild, Task 26)
///   --check veil | --check=veil         only the exploration veil section (cells, crossfade, height ramp, shader, Task 26)
///   --check matrix | --check=matrix     only the bench-matrix section (every runtime switch on the fixture world, Task 26b)
///   --check shadow | --check=shadow     only the shadow-caster section (browser caster classes, the 140 m box gate, cluster
///                               budget, scatter hemisphere term, compute-fog default; Task 26c)
///   --check figures | --check=figures only the figure section (whole clip library, set chain, activities, tiers, Task 28)
///   --check secondary | --check=secondary only the secondary-motion section (fixtures/secondary: extents, step trail,
///                               jump/frozen/far, anchor blend, normal correction; Task 33)
///   --check animals | --check=animals only the animals section (fixtures/animals: FBX takes, texture UV, leg chains,
///                               procedural gait, Task 34)
///   --check embody                 embodied camera, first person and scene keys (Task 48)
///   --check residency              live location rings, pins and rollback (Task 44)
///   --check-bench               offline bench smoke: fixture world + a 2 s drive, then quit
/// </summary>
public sealed record CliOptions(string? Server, string? User, string? Goto, bool Check)
{
    public static readonly Vector2I DefaultBenchSize = new(1920, 1080);

    public bool Bench { get; init; }
    /// <summary><c>--bench-matrix[=A,B,…]</c>: null = no matrix; "" = every variant; else the comma list (Task 26b).</summary>
    public string? BenchMatrix { get; init; }
    /// <summary>The distance fog as the compute pass (the default, Task 26c); false = <c>--fog=pass</c>, the screen pass.</summary>
    public bool FogCompute { get; init; } = true;
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
    /// <summary>
    /// <c>--msaa=N</c> as given; null = not given. Given, it wins over the menu's Graphics tab for the whole run;
    /// <see cref="StartMsaa"/> is what the viewport starts with.
    /// </summary>
    public Viewport.Msaa? Msaa { get; init; }

    /// <summary>A bench run without <c>--msaa</c> keeps 4×, the value every earlier bench result was measured at.</summary>
    public const Viewport.Msaa BenchDefaultMsaa = Viewport.Msaa.Msaa4X;

    /// <summary>
    /// The viewport's MSAA at start: <c>--msaa</c>, else 4× for a bench run, else the Graphics tab's default level
    /// (<see cref="GraphicsPrefs.Defaults"/>, 2×) until the stored prefs are read after the login.
    /// </summary>
    public Viewport.Msaa StartMsaa
        => Msaa ?? (Bench ? BenchDefaultMsaa : MsaaOfSamples(GraphicsPrefs.MsaaSamplesOf(GraphicsPrefs.Defaults.AntiAliasing)));

    /// <summary>A sample count (<see cref="GraphicsPrefs.MsaaSamplesOf"/>) → Godot's MSAA mode; 0 and anything unknown = off.</summary>
    public static Viewport.Msaa MsaaOfSamples(int samples) => samples switch
    {
        2 => Viewport.Msaa.Msaa2X,
        4 => Viewport.Msaa.Msaa4X,
        8 => Viewport.Msaa.Msaa8X,
        _ => Viewport.Msaa.Disabled,
    };
    /// <summary><c>--fly=M[,DEG]</c>: the streaming sanity drive (distance in metres, heading in degrees); null = none.</summary>
    public (double Distance, double HeadingDeg)? Fly { get; init; }
    /// <summary><c>--check verify</c>: run only that section of the self-test; null = all of it.</summary>
    public string? CheckOnly { get; init; }

    public static CliOptions FromGodot() => Parse(OS.GetCmdlineUserArgs());

    public static CliOptions Parse(IEnumerable<string> args)
    {
        string? server = null;
        string? user = null, gotoQuery = null;
        bool check = false, bench = false, checkBench = false, quit = false, vsync = false, scatter = true, noHud = false, plainGround = false;
        bool noWater = false, verify = false, fogCompute = true;
        string? matrix = null;
        string? offline = null, checkOnly = null;
        Vector2I? size = null;
        Viewport.Msaa? msaa = null;
        (double, double)? fly = null;
        foreach (var raw in args)
        {
            var arg = raw.Trim();
            if (arg == "--check") check = true;
            else if (TryValue(arg, "--check", out var only)) { check = true; checkOnly = CheckSection(only); }
            else if (check && checkOnly is null && IsSection(arg)) checkOnly = arg;
            else if (arg == "--verify") verify = true;
            else if (arg == "--bench") bench = true;
            else if (arg == "--bench-matrix") { bench = true; matrix = ""; }
            else if (TryValue(arg, "--bench-matrix", out var list))
            {
                bench = true;
                matrix = list;
                AnimaNative.Bench.BenchMatrix.Select(list);   // unknown names refuse the start
            }
            else if (TryValue(arg, "--fog", out var fogMode))
                fogCompute = fogMode switch
                {
                    "compute" => true,
                    "pass" => false,
                    _ => throw new ArgumentException($"--fog must be pass or compute, got '{fogMode}'"),
                };
            else if (arg == "--check-bench") checkBench = true;
            else if (arg == "--quit-after-bench") quit = true;
            else if (arg == "--no-scatter") scatter = false;
            else if (arg == "--scatter") scatter = true;
            else if (arg == "--no-hud") noHud = true;
            else if (arg == "--plain-ground") plainGround = true;
            else if (arg == "--no-water") noWater = true;
            else if (TryValue(arg, "--offline", out var off)) offline = off;
            else if (TryValue(arg, "--fly", out var flyArg)) fly = ParseFly(flyArg);
            else if (TryValue(arg, "--server", out var v))
                server = Ui.LauncherSettings.NormalizeServer(v)
                         ?? throw new ArgumentException($"--server must be an http(s) URL, got '{v}'");
            else if (TryValue(arg, "--user", out v)) user = v;
            else if (TryValue(arg, "--goto", out v)) gotoQuery = v;
            else if (TryValue(arg, "--size", out v)) size = ParseSize(v);
            else if (TryValue(arg, "--msaa", out v)) msaa = ParseMsaa(v);
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
            BenchMatrix = matrix,
            FogCompute = fogCompute,
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
            Msaa = msaa,
            Fly = fly,
        };
    }

    /// <summary><c>--fly=M[,DEG]</c>: a positive distance in metres, an optional heading in degrees (invariant culture).</summary>
    public static (double Distance, double HeadingDeg) ParseFly(string v)
    {
        var parts = v.Split(',');
        var ci = System.Globalization.CultureInfo.InvariantCulture;
        if (parts.Length is < 1 or > 2
            || !double.TryParse(parts[0], System.Globalization.NumberStyles.Float, ci, out var d) || !(d > 0) || !double.IsFinite(d))
            throw new ArgumentException($"--fly must be METRES[,DEGREES] with METRES > 0, got '{v}'");
        double heading = 0;
        if (parts.Length == 2 && (!double.TryParse(parts[1], System.Globalization.NumberStyles.Float, ci, out heading) || !double.IsFinite(heading)))
            throw new ArgumentException($"--fly heading must be a number of degrees, got '{parts[1]}'");
        return (d, heading);
    }

    private static bool IsSection(string v)
        => v is "verify" or "storeys" or "fidelity" or "props" or "light" or "fog" or "backdrop" or "terrain" or "stream" or "water"
             or "scatter" or "veil" or "matrix" or "figures" or "shadow" or "placement" or "walk" or "bridges" or "pairs" or "clips" or "secondary" or "animals" or "travel" or "residency" or "embody";

    private static string CheckSection(string v) => IsSection(v)
        ? v : throw new ArgumentException("--check= knows only 'verify', 'storeys', 'fidelity', 'props', 'light', 'fog', 'backdrop', "
                                          + $"'terrain', 'stream', 'water', 'scatter', 'veil', 'matrix', 'figures', 'shadow', 'placement', 'walk', 'bridges', 'pairs', 'clips', 'secondary', 'animals', 'travel', 'residency' and 'embody', got '{v}'");

    public static Viewport.Msaa ParseMsaa(string v) => v switch
    {
        "0" or "off" => Viewport.Msaa.Disabled,
        "2" => Viewport.Msaa.Msaa2X,
        "4" => Viewport.Msaa.Msaa4X,
        "8" => Viewport.Msaa.Msaa8X,
        _ => throw new ArgumentException($"--msaa must be 0, 2, 4 or 8, got '{v}'"),
    };

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
