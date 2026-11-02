using System;
using System.IO;

namespace AnimaNative.Hud;

/// <summary>Task 91: bound the previous CEF session's log before CEF opens it. One backup per selected path.</summary>
public static class CefLogging
{
    public const string Severity = "warning";
    public const long MaxBytes = 20L * 1024 * 1024;

    public static string Prepare(string userDir, string binaryDir, bool editor)
    {
        string path = Path.Combine(userDir, "debug.log");
        if (!editor)
        {
            string logs = Path.Combine(binaryDir, "logs");
            try
            {
                Directory.CreateDirectory(logs);
                // An existing directory inside an AppImage can be read-only too.
                using var probe = new FileStream(Path.Combine(logs, Guid.NewGuid().ToString("N") + ".tmp"),
                    FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose);
                path = Path.Combine(logs, "cef-debug.log");
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            if (File.Exists(path) && new FileInfo(path).Length > MaxBytes) File.Move(path, path + ".1", true);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        return path;
    }
}
