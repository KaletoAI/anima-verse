using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check</c>, launcher part (Task 5 of Phase 3): the Godot side of
/// <c>user://launcher.json</c> — <see cref="LauncherStore"/> reading and writing
/// through <see cref="Godot.FileAccess"/> — in a temporary directory (never the
/// real user dir), plus the start flags that feed it (<see cref="CliOptions.Parse"/>).
/// The pure parsing/normalising rules are the xUnit tests in
/// native/tests/LauncherSettingsTests.cs.
/// </summary>
public static class LauncherCheck
{
    public static string Run()
    {
        int files = CheckStore();
        int flags = CheckFlags();
        return $"launcher file_cases={files} flag_cases={flags}";
    }

    private static int CheckStore()
    {
        var dir = Path.Combine(Path.GetTempPath(), "anima-native-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "launcher.json");
        try
        {
            var empty = LauncherStore.Load(path);
            Expect("missing file → defaults", empty == new LauncherSettings(), empty.ToString());

            var s = new LauncherSettings { Server = "http://192.168.8.244:8000", User = "demo", Fullscreen = true };
            Expect("save", LauncherStore.Save(s, path), "Save returned false");
            Expect("no temp file left", !File.Exists(path + ".tmp"), "launcher.json.tmp still there");
            var back = LauncherStore.Load(path);
            Expect("round trip", back == s, back.ToString());
            using (var doc = JsonDocument.Parse(File.ReadAllText(path)))
            {
                var keys = string.Join(",", doc.RootElement.EnumerateObject().Select(p => p.Name).OrderBy(k => k));
                Expect("file keys", keys == "fullscreen,server,user", keys);
            }

            var toggled = LauncherStore.Update(x => x with { Fullscreen = false }, path);
            var reread = LauncherStore.Load(path);
            Expect("update keeps the other fields", reread == toggled && reread.Server == s.Server && reread.User == "demo"
                                                    && !reread.Fullscreen, reread.ToString());

            File.WriteAllText(path, "{ not json");
            var broken = LauncherStore.Load(path);
            Expect("broken file → defaults", broken == new LauncherSettings(), broken.ToString());
            Expect("save over a broken file", LauncherStore.Save(s, path) && LauncherStore.Load(path) == s, File.ReadAllText(path));
            return 5;
        }
        finally
        {
            try { Directory.Delete(dir, recursive: true); } catch (Exception) { /* temp dir: best effort */ }
        }
    }

    private static int CheckFlags()
    {
        var none = CliOptions.Parse(Array.Empty<string>());
        Expect("no flags: no server, no user", none.Server is null && none.User is null, none.ToString());
        var typed = CliOptions.Parse(new[] { "--server=192.168.8.244:8000/", "--user=demo" });
        Expect("--server in user form is normalised", typed.Server == "http://192.168.8.244:8000", typed.Server ?? "null");
        Expect("--user", typed.User == "demo", typed.User ?? "null");
        bool threw = false;
        try { CliOptions.Parse(new[] { "--server=ftp://x" }); }
        catch (ArgumentException) { threw = true; }
        Expect("--server=ftp://x is refused", threw, "no exception");
        var bench = CliOptions.Parse(new[] { "--server=http://h:8000", "--bench", "--goto=harbour", "--quit-after-bench", "--size=1920x1080" });
        Expect("bench flags unchanged", bench.Bench && bench.QuitAfterBench && bench.Goto == "harbour"
                                        && bench.Size == new Vector2I(1920, 1080) && bench.Server == "http://h:8000", bench.ToString());
        return 5;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"launcher: {what}: {detail}");
    }
}
