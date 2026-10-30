using System.Text;

namespace AnimaNative.Hud;

/// <summary>Printable text bypasses gdCEF's character-code/virtual-key collisions while the HUD types.</summary>
public static class HudText
{
    // Ctrl+Alt is AltGr on some layouts; either modifier alone remains a shortcut.
    public static bool IsTextKey(long unicode, bool ctrl, bool alt, bool meta)
        => unicode >= 32 && unicode <= 0x10ffff && Rune.IsValid((int)unicode)
           && !Rune.IsControl(new Rune((int)unicode)) && !meta && ctrl == alt;
}
