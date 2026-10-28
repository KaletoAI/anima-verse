using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Embody;

/// <summary>Task 48 / E7-T3: main.ts scene keys consume the same published offers as the HUD chip.</summary>
public sealed record SceneKeyCommand(string Name, bool Ui = false, JsonNode? Argument = null);
public static class SceneKeys
{
    public static string Escape(bool typing, bool overlay, bool menu, JsonObject state)
        => KeyRouting.EscTarget(typing, overlay, menu, Bool(state["elevatorOpen"]));

    /// <summary>Nearest visible offer, then locked entry, then overview + selected avatar. No unconditional chat.</summary>
    public static SceneKeyCommand? Interact(JsonObject state, bool lockedEntry = false)
    {
        double? Dist(string field) => state[field] is JsonObject o && o["dist"] is JsonValue v
            && v.GetValueKind() == JsonValueKind.Number ? v.Deserialize<double>() : null;
        var kind = Offers.NearestOffer(Dist("talkTarget"), Dist("elevator"), Dist("stairs"), Dist("enterOffer"));
        if (kind == "talk") return new("openChat", Ui: true);
        if (kind == "stairs") return new("rideStairs");
        if (kind == "enter") return new("enterLocation");
        if (kind == "elevator" && state["elevator"] is JsonObject lift)
        {
            if (lift["levels"] is JsonArray levels && lift["current"] is JsonValue current && current.TryGetValue<int>(out var at))
            {
                int? sole = null;
                int count = 0;
                foreach (var level in levels)
                    if (level is JsonValue n && n.TryGetValue<int>(out int lv) && lv != at) { count++; sole = lv; }
                if (count == 1) return new("rideElevator", Argument: JsonValue.Create(sole!.Value));
            }
            return new("elevatorOpen", Argument: JsonValue.Create(!Bool(state["elevatorOpen"])));
        }
        if (lockedEntry) return new("enterLocation");
        return state["mode"]?.GetValue<string>() == "overview" && state["selected"] is JsonObject selected && Bool(selected["isAvatar"])
            ? new("enterEmbodied") : null;
    }
    private static bool Bool(JsonNode? value) => value is JsonValue v && v.TryGetValue<bool>(out var on) && on;
}
