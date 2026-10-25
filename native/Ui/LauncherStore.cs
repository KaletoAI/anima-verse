using System;
using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// The file side of <see cref="LauncherSettings"/>: <c>user://launcher.json</c>
/// (Linux: <c>~/.local/share/godot/app_userdata/Anima Native/launcher.json</c>),
/// read and written through Godot's <see cref="FileAccess"/>. Holds server, user
/// name and window mode — never the password. A missing or unreadable file reads
/// as the defaults; a write goes to a temporary file first and is then renamed
/// over the old one, so a crash mid-write cannot leave half a file.
/// </summary>
public static class LauncherStore
{
    public const string DefaultPath = "user://launcher.json";

    public static LauncherSettings Load(string path = DefaultPath)
    {
        if (!FileAccess.FileExists(path)) return LauncherSettings.Parse(null);
        using var file = FileAccess.Open(path, FileAccess.ModeFlags.Read);
        if (file is null)
        {
            GD.PushWarning($"[native] launcher: cannot read {path} ({FileAccess.GetOpenError()}) — empty fields");
            return LauncherSettings.Parse(null);
        }
        return LauncherSettings.Parse(file.GetAsText());
    }

    /// <summary>Writes <paramref name="settings"/>; false (and a warning) when the file cannot be written.</summary>
    public static bool Save(LauncherSettings settings, string path = DefaultPath)
    {
        var tmp = path + ".tmp";
        using (var file = FileAccess.Open(tmp, FileAccess.ModeFlags.Write))
        {
            if (file is null)
            {
                GD.PushWarning($"[native] launcher: cannot write {tmp} ({FileAccess.GetOpenError()})");
                return false;
            }
            file.StoreString(settings.Serialize());
        }
        var err = DirAccess.RenameAbsolute(ProjectSettings.GlobalizePath(tmp), ProjectSettings.GlobalizePath(path));
        if (err != Error.Ok)
        {
            GD.PushWarning($"[native] launcher: cannot replace {path} ({err})");
            return false;
        }
        return true;
    }

    /// <summary>Read, change, write — the other fields keep what the file holds.</summary>
    public static LauncherSettings Update(Func<LauncherSettings, LauncherSettings> change, string path = DefaultPath)
    {
        var next = change(Load(path));
        Save(next, path);
        return next;
    }
}
