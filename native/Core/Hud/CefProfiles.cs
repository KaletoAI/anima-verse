using System;
using System.Diagnostics;
using System.IO;

namespace AnimaNative.Hud;

/// <summary>Reclaim private profiles abandoned by a crashed process, conservatively around locks.</summary>
public static class CefProfiles
{
    public static int SweepStale(string tempDirectory, DateTime nowUtc)
    {
        int removed = 0;
        try
        {
            string root = Path.GetFullPath(tempDirectory);
            foreach (string path in Directory.EnumerateDirectories(root, "anima-cef-*", SearchOption.TopDirectoryOnly))
            {
                try
                {
                    var directory = new DirectoryInfo(path);
                    if ((directory.Attributes & FileAttributes.ReparsePoint) != 0
                        || directory.LastWriteTimeUtc >= nowUtc.AddHours(-1) || !Unlocked(directory)) continue;
                    // Directory.Delete removes directory symlinks themselves, never their targets.
                    directory.Delete(recursive: true);
                    removed++;
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        return removed;
    }

    private static bool Unlocked(DirectoryInfo directory)
    {
        foreach (var entry in directory.EnumerateFileSystemInfos())
        {
            bool isLock = entry.Name.Contains("lock", StringComparison.OrdinalIgnoreCase);
            if ((entry.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                // Chromium's Linux SingletonLock is a dangling hostname-PID symlink,
                // including while live. Never resolve it (it may point outside temp).
                if (isLock && (entry.Name != "SingletonLock" || !DeadLocalProcess(entry.LinkTarget))) return false;
                continue;
            }
            if (entry is DirectoryInfo child)
            {
                if (isLock || !Unlocked(child)) return false;
            }
            else if (isLock)
            {
                try
                {
                    using var probe = new FileStream(entry.FullName, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                    // Check both .NET share locks and native POSIX byte-range locks.
                    if (OperatingSystem.IsMacOS()) return false;
                    probe.Lock(0, 1);
                    probe.Unlock(0, 1);
                }
                catch (IOException) { return false; }
                catch (UnauthorizedAccessException) { return false; }
            }
        }
        return true;
    }

    private static bool DeadLocalProcess(string? target)
    {
        string prefix = Environment.MachineName + "-";
        if (target is null || !target.StartsWith(prefix, StringComparison.Ordinal)
            || !int.TryParse(target.AsSpan(prefix.Length), out int pid) || pid <= 0) return false;
        try { using var process = Process.GetProcessById(pid); return process.HasExited; }
        catch (ArgumentException) { return true; }
        catch (Exception) { return false; }
    }
}
