using System.Text.Json;

namespace AnimaNative.Sync;

/// <summary>
/// The HUD's <c>connection</c> and <c>clock</c> fields as <c>applyWorldMap</c> and the poll's error branch of
/// client3d/src/main.ts write them: a good poll publishes <c>{connection: 'ok', clock}</c> only when either
/// changed; a failed fetch or apply that is NOT an expired session publishes <c>{connection: 'lost'}</c> once.
/// An expired session changes nothing here — it opens the login instead.
/// </summary>
public sealed class ConnectionState
{
    public const string OkValue = "ok", LostValue = "lost";

    public string Connection { get; private set; } = OkValue;
    public string Clock { get; private set; } = "";

    /// <summary>A good poll: true when the HUD has to be told (the connection came back or the clock moved).</summary>
    public bool Ok(string clock)
    {
        if (Connection == OkValue && Clock == clock) return false;
        Connection = OkValue;
        Clock = clock;
        return true;
    }

    /// <summary>A failed poll (not an auth failure): true the first time.</summary>
    public bool Lost()
    {
        if (Connection == LostValue) return false;
        Connection = LostValue;
        return true;
    }

    /// <summary>
    /// <c>map.game_time?.label_display ?? map.game_time?.label ?? ''</c> — JS <c>??</c> falls through on a missing
    /// or null value only, so an EMPTY <c>label_display</c> is taken as it is (the spike fell through on "").
    /// </summary>
    public static string ClockOf(JsonElement map)
    {
        if (map.ValueKind != JsonValueKind.Object || !map.TryGetProperty("game_time", out var gt)
            || gt.ValueKind != JsonValueKind.Object) return "";
        if (Text(gt, "label_display") is { } display) return display;
        return Text(gt, "label") ?? "";
    }

    private static string? Text(JsonElement o, string key)
    {
        if (!o.TryGetProperty(key, out var v) || v.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        return v.ValueKind == JsonValueKind.String ? v.GetString() : v.GetRawText();
    }
}
