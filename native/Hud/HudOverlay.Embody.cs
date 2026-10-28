using System;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using Godot;

namespace AnimaNative.Hud;

/// <summary>Task 48 / E7-T3: capture-phase browser key rules, before CEF can close its modal.</summary>
public partial class HudOverlay
{
    /// <summary>Task 51: scene offers read by the same F/picker resolution as the HUD; callers never mutate this value.</summary>
    public JsonNode? SceneOwned(string field) => _state.Get(field);
    public Action? SceneEscape { get; set; }
    /// <summary>Later entry wiring can explain a locked neighbour even when it publishes no visible offer.</summary>
    public Func<bool>? LockedEntry { get; set; }

    /// <summary>
    /// One keydown from _Input; public for the offline check. Escape cancels pending control even while
    /// typing, then closes exactly one layer. F reads scene-owned offers; Enter remains unbound.
    /// </summary>
    public bool RouteSceneKey(InputEventKey key)
    {
        if (!key.Pressed) return false;
        if (key.Keycode == Key.Escape)
        {
            SceneEscape?.Invoke();
            string target = KeyRouting.EscTarget(Ui.Typing, Ui.OverlayOpen, Ui.MenuOpen,
                _state.Get("elevatorOpen") is JsonValue v && v.TryGetValue<bool>(out bool open) && open);
            if (target == "ignore") return false;
            if (target == "elevator") SetState("elevatorOpen", false);
            else if (target == "menu") SendUi("closeMenu");
            else if (_state.Get("mode")?.GetValue<string>() == "embodied") InvokeSceneAction("exitEmbodied");
            return true;
        }
        if (!KeyRouting.KeyForScene(Ui.Typing, Ui.OverlayOpen) || key.CtrlPressed || key.AltPressed || key.MetaPressed) return false;
        if (key.Keycode == Key.M) { SendUi("toggleMenu"); return true; }
        if (key.Keycode != Key.F) return false;
        var state = new JsonObject();
        foreach (var field in new[] { "mode", "selected", "talkTarget", "stairs", "elevator", "elevatorOpen", "enterOffer" })
            state[field] = _state.Get(field)?.DeepClone();
        var command = SceneKeys.Interact(state, LockedEntry?.Invoke() == true);
        if (command is { Ui: true }) SendUi(command.Name);
        else if (command?.Name == "elevatorOpen") SetState(command.Name, command.Argument);
        else if (command is not null) InvokeSceneAction(command.Name, command.Argument);
        return true;
    }

    private void InvokeSceneAction(string name, JsonNode? argument = null)
    {
        if (Handlers.TryGetValue(name, out var action)) action(argument is null ? new JsonArray() : new JsonArray(argument.DeepClone()));
    }
}
