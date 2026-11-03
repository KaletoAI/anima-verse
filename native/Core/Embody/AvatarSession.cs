using System.Text.Json;

namespace AnimaNative.Embody;

/// <summary>Avatar controllers stay suspended during identity changes and spectator sessions.</summary>
public static class AvatarSession
{
    public static bool Suspended(JsonElement? map, bool changing = false, bool hasRememberedAvatar = false)
    {
        if (changing) return true;
        if (map is not { ValueKind: JsonValueKind.Object } root) return !hasRememberedAvatar;
        if (root.TryGetProperty("avatar_released", out var released) && released.ValueKind == JsonValueKind.True) return true;
        bool hasAvatar = root.TryGetProperty("avatar", out var avatar) && avatar.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(avatar.GetString());
        // A known session may recover temporary absence, but never an intentional release.
        return !hasAvatar && !hasRememberedAvatar;
    }
}
