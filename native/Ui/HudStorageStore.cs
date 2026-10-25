using Godot;

namespace AnimaNative.Ui;

/// <summary>
/// The file side of <see cref="HudStorage"/>: <c>user://hud_storage.json</c> (Linux:
/// <c>~/.local/share/godot/app_userdata/Anima Native/hud_storage.json</c>), the HUD page's mirrored
/// <c>localStorage</c> per server origin. A missing or unreadable file reads as empty; a write goes to a temporary
/// file first and is then renamed over the old one (as <see cref="LauncherStore"/> does), so a crash mid-write cannot
/// leave half a file. Never a cookie, never the session token (see <see cref="HudStorage"/>).
/// </summary>
public static class HudStorageStore
{
    public const string DefaultPath = "user://hud_storage.json";

    public static HudStorage Load(string path = DefaultPath)
    {
        if (!FileAccess.FileExists(path)) return HudStorage.Parse(null);
        using var file = FileAccess.Open(path, FileAccess.ModeFlags.Read);
        if (file is null)
        {
            GD.PushWarning($"[native] hud storage: cannot read {path} ({FileAccess.GetOpenError()}) — starting empty");
            return HudStorage.Parse(null);
        }
        return HudStorage.Parse(file.GetAsText());
    }

    /// <summary>Writes <paramref name="store"/>; false (and a warning) when the file cannot be written.</summary>
    public static bool Save(HudStorage store, string path = DefaultPath)
    {
        var tmp = path + ".tmp";
        using (var file = FileAccess.Open(tmp, FileAccess.ModeFlags.Write))
        {
            if (file is null)
            {
                GD.PushWarning($"[native] hud storage: cannot write {tmp} ({FileAccess.GetOpenError()})");
                return false;
            }
            file.StoreString(store.Serialize());
        }
        var err = DirAccess.RenameAbsolute(ProjectSettings.GlobalizePath(tmp), ProjectSettings.GlobalizePath(path));
        if (err != Error.Ok)
        {
            GD.PushWarning($"[native] hud storage: cannot replace {path} ({err})");
            return false;
        }
        return true;
    }
}
