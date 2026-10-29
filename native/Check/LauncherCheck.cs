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
        int hud = CheckHudStore();
        return $"launcher file_cases={files} flag_cases={flags} hud_store_cases={hud}";
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

    /// <summary>
    /// <c>user://hud_storage.json</c> through <see cref="HudStorageStore"/> (Task 12), in a temporary directory: a
    /// missing file is empty; a save/load round trip keeps the entries per server (the stored server key is the
    /// origin, so <c>192.168.8.244:8000/</c> finds them) and leaves no <c>.tmp</c>; a broken file reads as empty
    /// and is written over.
    /// </summary>
    private static int CheckHudStore()
    {
        var dir = Path.Combine(Path.GetTempPath(), "anima-native-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "hud_storage.json");
        try
        {
            Expect("hud storage: missing file → empty", HudStorageStore.Load(path).Serialize() == "{\"version\":1,\"servers\":{}}",
                   HudStorageStore.Load(path).Serialize());
            var s = new HudStorage();
            s.Apply("http://192.168.8.244:8000", new HudStorageOp(HudStorageOp.Set, HudStorage.ShowAllKey, "1"));
            s.Apply("http://192.168.8.244:8000", new HudStorageOp(HudStorageOp.Set, "av3d.chat.size", "{\"w\":420}"));
            s.Apply("http://other:9", new HudStorageOp(HudStorageOp.Set, "k", "v"));
            Expect("hud storage: save", HudStorageStore.Save(s, path), "Save returned false");
            Expect("hud storage: no temp file left", !File.Exists(path + ".tmp"), "hud_storage.json.tmp still there");
            var back = HudStorageStore.Load(path);
            var lan = back.EntriesFor("192.168.8.244:8000/");
            Expect("hud storage: round trip per server", back.Serialize() == s.Serialize() && lan.Count == 2
                                                          && lan[HudStorage.ShowAllKey] == "1" && lan["av3d.chat.size"] == "{\"w\":420}",
                   back.Serialize());
            File.WriteAllText(path, "{ not json");
            Expect("hud storage: broken file → empty, then saved over",
                   HudStorageStore.Load(path).Serialize() == "{\"version\":1,\"servers\":{}}"
                   && HudStorageStore.Save(s, path) && HudStorageStore.Load(path).Serialize() == s.Serialize(), File.ReadAllText(path));
            return 4;
        }
        finally
        {
            try { Directory.Delete(dir, recursive: true); } catch (Exception) { /* temp dir: best effort */ }
        }
    }

    private static int CheckFlags()
    {
        var version = CliOptions.Parse(new[] { "--version" });
        Expect("--version exits before launcher setup", version.ShowVersion && !version.Check && !version.Bench, version.ToString());
        var none = CliOptions.Parse(Array.Empty<string>());
        Expect("version is opt-in", !none.ShowVersion, none.ToString());
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
        // Task 15: the § B5a flags — `--check verify` / `--check=verify` pick the section, `--verify` the full table.
        var sections = new[] { CliOptions.Parse(new[] { "--check", "verify" }), CliOptions.Parse(new[] { "--check=verify" }),
                               CliOptions.Parse(new[] { "--check" }), CliOptions.Parse(new[] { "--verify" }) };
        Expect("verify flags", sections[0] is { Check: true, CheckOnly: "verify" } && sections[1] is { Check: true, CheckOnly: "verify" }
                               && sections[2] is { Check: true, CheckOnly: null, Verify: false } && sections[3] is { Check: false, Verify: true },
               string.Join(" | ", sections.Select(o => o.ToString())));
        // Task 16: the storey section, both spellings.
        var storeys = new[] { CliOptions.Parse(new[] { "--check", "storeys" }), CliOptions.Parse(new[] { "--check=storeys" }) };
        Expect("storeys flags", storeys.All(o => o is { Check: true, CheckOnly: "storeys" }), string.Join(" | ", storeys.Select(o => o.ToString())));
        // Task 17: the model-fidelity section, both spellings.
        var fidelity = new[] { CliOptions.Parse(new[] { "--check", "fidelity" }), CliOptions.Parse(new[] { "--check=fidelity" }) };
        Expect("fidelity flags", fidelity.All(o => o is { Check: true, CheckOnly: "fidelity" }), string.Join(" | ", fidelity.Select(o => o.ToString())));
        // Task 18: the props section, both spellings.
        var props = new[] { CliOptions.Parse(new[] { "--check", "props" }), CliOptions.Parse(new[] { "--check=props" }) };
        Expect("props flags", props.All(o => o is { Check: true, CheckOnly: "props" }), string.Join(" | ", props.Select(o => o.ToString())));
        // Task 55: the minimap check section, both spellings.
        var minimap = new[] { CliOptions.Parse(new[] { "--check", "minimap" }), CliOptions.Parse(new[] { "--check=minimap" }) };
        Expect("minimap flags", minimap.All(o => o is { Check: true, CheckOnly: "minimap" }), string.Join(" | ", minimap.Select(o => o.ToString())));
        threw = false;
        try { CliOptions.Parse(new[] { "--check=everything" }); }
        catch (ArgumentException) { threw = true; }
        Expect("--check=everything is refused", threw, "no exception");
        return 12;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"launcher: {what}: {detail}");
    }
}
