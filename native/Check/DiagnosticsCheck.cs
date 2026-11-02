using System;
using System.IO;
using AnimaNative.Hud;
using AnimaNative.Sync;

namespace AnimaNative.Check;

/// <summary>Task 91: fixed /proc fixtures and real temporary log files; no world storage.</summary>
public static class DiagnosticsCheck
{
    public static void Run()
    {
        void Need(bool ok, string what) { if (!ok) throw new InvalidOperationException("diagnostics: " + what); }
        var line = BootDiagnostics.Describe(8, "1.25 2.00 3.00 1/432 1234\n",
            "MemTotal:       8388608 kB\nMemFree: 12 kB\nMemAvailable:   2097152 kB\n",
            2500, 10000);
        Need(line == "boot machine: cpus=8 load1=1.25 mem_available=2048 MiB mem_total=8192 MiB process_cpu=2500 ms wall=10000 ms cpu/wall=0.25", "load/memory units and process CPU delta");
        Need(BootDiagnostics.Describe(2, "broken", "MemTotal: broken", 0, 0)
            == "boot machine: cpus=2 process_cpu=0 ms wall=0 ms cpu/wall=0.00", "unavailable/malformed proc fields omitted");
        Need(BootDiagnostics.Describe(2, "", "", 0, 0)
            == "boot machine: cpus=2 process_cpu=0 ms wall=0 ms cpu/wall=0.00", "empty proc files omitted");
        string root = Path.Combine(Path.GetTempPath(), "anima-logs-" + Guid.NewGuid().ToString("N"));
        try
        {
            foreach (bool editor in new[] { true, false })
            {
                string user = Path.Combine(root, editor ? "editor" : "export", "cef");
                string binary = Path.Combine(root, "bin"); Directory.CreateDirectory(binary);
                string path = CefLogging.Prepare(user, binary, editor);
                Need(path == (editor ? Path.Combine(user, "debug.log") : Path.Combine(binary, "logs", "cef-debug.log")), "editor/export path");
                File.WriteAllText(path + ".1", "older");
                using (var file = File.Create(path)) file.SetLength(CefLogging.MaxBytes);
                CefLogging.Prepare(user, binary, editor);
                Need(new FileInfo(path).Length == CefLogging.MaxBytes && File.ReadAllText(path + ".1") == "older", "threshold inclusive");
                using (var file = File.OpenWrite(path)) { file.SetLength(CefLogging.MaxBytes + 1); file.WriteByte(73); }
                CefLogging.Prepare(user, binary, editor);
                Need(!File.Exists(path) && new FileInfo(path + ".1").Length == CefLogging.MaxBytes + 1, "oversize rotates, replacing one backup");
                File.WriteAllText(path, "new"); CefLogging.Prepare(user, binary, editor);
                Need(File.ReadAllText(path) == "new", "small active log preserved");
            }
            string blocked = Path.Combine(root, "readonly-image"); File.WriteAllText(blocked, "file, not a directory");
            string fallback = Path.Combine(root, "appimage-user", "cef");
            Need(CefLogging.Prepare(fallback, blocked, false) == Path.Combine(fallback, "debug.log"), "AppImage/nonwritable binary uses user data");
            Need(CefLogging.Severity == "warning", "warnings retained without info bridge spam");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
