using System;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using Godot;

namespace AnimaNative.Bench;

/// <summary>
/// Where a bench result goes: ONE stdout line <c>[bench] result {json}</c>
/// (the browser's console line), a file <c>user://bench-&lt;yyyyMMdd-HHmmss&gt;.json</c>
/// (its absolute path is printed), and a panel with selectable text.
/// </summary>
public static class BenchOutput
{
    // Relaxed escaping so the line reads like the browser's JSON.stringify ("godot-forward+", not "\u002B").
    private static readonly JsonSerializerOptions Compact = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    private static readonly JsonSerializerOptions Pretty = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = true,
    };

    public static string Line(JsonObject result) => result.ToJsonString(Compact);

    /// <summary>Prints and writes the result; returns the absolute path of the file.</summary>
    public static string Emit(JsonObject result)
    {
        var line = Line(result);
        GD.Print("[bench] result " + line);
        var userPath = $"user://bench-{DateTime.Now:yyyyMMdd-HHmmss}.json";
        using (var file = Godot.FileAccess.Open(userPath, Godot.FileAccess.ModeFlags.Write))
        {
            if (file is null)
                throw new InvalidOperationException($"cannot write {userPath}: {Godot.FileAccess.GetOpenError()}");
            file.StoreString(result.ToJsonString(Pretty) + "\n");
        }
        var absolute = ProjectSettings.GlobalizePath(userPath);
        GD.Print("[bench] written " + absolute);
        return absolute;
    }

    /// <summary>The result on screen: read-only, selectable text plus Copy / Close.</summary>
    public static void ShowPanel(Node host, JsonObject result, string filePath)
        => ShowText(host, $"Bench result — {filePath}", result.ToJsonString(Pretty), Line(result));

    /// <summary>A titled text on screen (the matrix's summary table): read-only, selectable, Copy / Close.</summary>
    public static void ShowText(Node host, string title, string text, string? copy = null)
    {
        var layer = new CanvasLayer { Name = "BenchResult", Layer = 20 };
        host.AddChild(layer);
        // Pinned to the top-right corner, growing to the left.
        var panel = new PanelContainer
        {
            AnchorLeft = 1, AnchorRight = 1, AnchorTop = 0, AnchorBottom = 0,
            OffsetLeft = -684, OffsetRight = -12, OffsetTop = 12,
            GrowHorizontal = Control.GrowDirection.Begin,
        };
        layer.AddChild(panel);
        var box = new VBoxContainer();
        panel.AddChild(box);
        box.AddChild(new Label { Text = title });
        var edit = new TextEdit
        {
            Text = text,
            Editable = false,
            CustomMinimumSize = new Vector2(660, 480),
        };
        box.AddChild(edit);
        var buttons = new HBoxContainer();
        box.AddChild(buttons);
        var copyButton = new Button { Text = copy is null ? "Copy" : "Copy JSON" };
        copyButton.Pressed += () => DisplayServer.ClipboardSet(copy ?? text);
        buttons.AddChild(copyButton);
        var close = new Button { Text = "Close" };
        close.Pressed += () => layer.QueueFree();
        buttons.AddChild(close);
    }
}
