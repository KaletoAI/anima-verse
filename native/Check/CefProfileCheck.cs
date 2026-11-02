using System;
using System.IO;
using AnimaNative.Hud;

namespace AnimaNative.Check;

/// <summary>Task 101: stale profile cleanup must preserve fresh, locked and symlinked directories.</summary>
public static class CefProfileCheck
{
    public static int Run()
    {
        string root = Directory.CreateTempSubdirectory("task101-profiles-").FullName;
        string outside = Directory.CreateTempSubdirectory("task101-outside-").FullName;
        int n = 0;
        void Is(string label, bool value) { n++; if (!value) throw new InvalidOperationException("CEF profiles " + label); }
        try
        {
            var now = DateTime.UtcNow;
            string Profile(string name, bool old = true)
            {
                string dir = Path.Combine(root, "anima-cef-" + name);
                Directory.CreateDirectory(dir);
                Directory.SetLastWriteTimeUtc(dir, old ? now.AddHours(-2) : now);
                return dir;
            }
            var old = Profile("old");
            var unrelated = Path.Combine(root, "another-app-profile");
            Directory.CreateDirectory(unrelated); Directory.SetLastWriteTimeUtc(unrelated, now.AddHours(-2));
            var fresh = Profile("fresh", false);
            var boundary = Profile("boundary"); Directory.SetLastWriteTimeUtc(boundary, now.AddHours(-1));
            var locked = Profile("locked");
            var lockPath = Path.Combine(locked, "SingletonLock");
            using var held = new FileStream(lockPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None);
            Directory.SetLastWriteTimeUtc(locked, now.AddHours(-2));
            File.WriteAllText(Path.Combine(outside, "keep"), "outside");
            Directory.SetLastWriteTimeUtc(outside, now.AddHours(-2));
            var link = Path.Combine(root, "anima-cef-link"); Directory.CreateSymbolicLink(link, outside);
            var nested = Profile("nested"); Directory.CreateSymbolicLink(Path.Combine(nested, "external"), outside);
            Directory.SetLastWriteTimeUtc(nested, now.AddHours(-2));
            var live = Profile("live");
            File.CreateSymbolicLink(Path.Combine(live, "SingletonLock"), $"{Environment.MachineName}-{Environment.ProcessId}");
            Directory.SetLastWriteTimeUtc(live, now.AddHours(-2));
            var unknown = Profile("unknown");
            File.CreateSymbolicLink(Path.Combine(unknown, "SingletonLock"), "unknown-host-1234");
            Directory.SetLastWriteTimeUtc(unknown, now.AddHours(-2));
            var dead = Profile("dead");
            using (var exited = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("/bin/true") { UseShellExecute = false })!)
            {
                exited.WaitForExit();
                File.CreateSymbolicLink(Path.Combine(dead, "SingletonLock"), $"{Environment.MachineName}-{exited.Id}");
            }
            Directory.SetLastWriteTimeUtc(dead, now.AddHours(-2));
            var released = Profile("released");
            File.WriteAllText(Path.Combine(released, "lockfile"), "");
            Directory.SetLastWriteTimeUtc(released, now.AddHours(-2));
            int removed = CefProfiles.SweepStale(root, now);
            Is("old unlocked removed", !Directory.Exists(old));
            Is("fresh and exact one-hour boundary kept", Directory.Exists(fresh) && Directory.Exists(boundary));
            Is("held lock kept", Directory.Exists(locked));
            Is("live process lock kept", Directory.Exists(live));
            Is("unknown lock kept", Directory.Exists(unknown));
            Is("dead process lock removed", !Directory.Exists(dead));
            Is("released regular lock removed", !Directory.Exists(released));
            Is("unrelated profile kept", Directory.Exists(unrelated));
            Is("root symlink kept", Directory.Exists(link));
            Is("nested link never traversed", File.ReadAllText(Path.Combine(outside, "keep")) == "outside");
            Is("nested profile removed without following link", !Directory.Exists(nested));
            Is("count matches removals", removed == 4);
            return n;
        }
        finally { Directory.Delete(root, true); Directory.Delete(outside, true); }
    }
}
