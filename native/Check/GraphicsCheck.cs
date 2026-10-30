using System;
using System.IO;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

/// <summary>Offline shared graphics vectors and the actual viewport's resolution settings and resize signal.</summary>
public static class GraphicsCheck
{
    public static async Task<string> RunAsync(Node host)
    {
        var path = Path.Combine(ProjectSettings.GlobalizePath("res://"), "../shared/test-vectors/graphics_prefs.json");
        var vectors = JsonNode.Parse(File.ReadAllText(path))!["cases"]!.AsArray();
        JsonNode Prefs(GraphicsPrefs p) => JsonNode.Parse(GraphicsPrefs.Save(p))!;
        int count = HitchCheck.Run(host.GetViewport());
        foreach (var c in vectors)
        {
            var a = c!["args"]!.AsArray();
            JsonNode? got = c["fn"]!.GetValue<string>() switch
            {
                "loadGraphicsPrefs" => Prefs(GraphicsPrefs.Load(a[0]?.GetValue<string>())),
                "saveGraphicsPrefs" => JsonValue.Create(GraphicsPrefs.Save(GraphicsPrefs.Load(a[0]!.ToJsonString()))),
                "checkGraphicsPrefs" => Check(GraphicsPrefs.Check(a[0], a[1], a.Count > 2 ? a[2] : null)),
                "autoRenderScale" => JsonValue.Create(GraphicsPrefs.AutoRenderScale(a[0]!.GetValue<double>(), a[1]!.GetValue<double>())),
                "effectiveRenderScale" => JsonValue.Create(GraphicsPrefs.EffectiveRenderScale(GraphicsPrefs.RenderScaleOf(a[0]), a[1]!.GetValue<double>(), a[2]!.GetValue<double>())),
                "msaaSamplesOf" => JsonValue.Create(GraphicsPrefs.MsaaSamplesOf(a[0]!.GetValue<string>())),
                "browserAntialias" => JsonValue.Create(GraphicsPrefs.BrowserAntialias(GraphicsPrefs.Load(a[0]!.ToJsonString()))),
                "pickBrowserAntiAliasing" => JsonValue.Create(GraphicsPrefs.PickBrowserAntiAliasing(a[0]!.GetValue<bool>(), a[1]!.GetValue<string>())),
                "graphicsPrefsConstants" => new JsonObject { ["key"] = GraphicsPrefs.Key,
                    ["levels"] = new JsonArray("off", "2x", "4x"), ["defaults"] = Prefs(GraphicsPrefs.Defaults) },
                _ => throw new InvalidOperationException("unknown graphics vector"),
            };
            Require(c["label"]!.GetValue<string>(), JsonNode.DeepEquals(c["expect"], got));
            count++;
        }
        foreach (var aa in GraphicsPrefs.Levels)
        foreach (var shadows in new[] { true, false })
        foreach (var scale in GraphicsPrefs.RenderScales)
        {
            var prefs = new GraphicsPrefs(aa, shadows, scale);
            Require("prefs round trip", GraphicsPrefs.Load(GraphicsPrefs.Save(prefs)) == prefs);
            var wire = HudProtocol.Parse(new JsonObject { ["v"] = HudProtocol.Version, ["kind"] = "action",
                ["name"] = "applyGraphicsPrefs", ["args"] = new JsonArray(Prefs(prefs)) }.ToJsonString(), out _);
            var p = wire!.Args![0]!;
            Require("bridge graphics round trip", GraphicsPrefs.Check(p["antiAliasing"], p["shadows"], p["renderScale"]).Prefs == prefs);
        }
        var viewport = new SubViewport { Size = new Vector2I(3840, 1080) };
        host.AddChild(viewport);
        var lines = new System.Collections.Generic.List<string>();
        using (var resolution = new RenderResolution(viewport, lines.Add))
        {
            resolution.Apply(null);
            Require("auto uses FSR at ultrawide", viewport.Scaling3DMode == Viewport.Scaling3DModeEnum.Fsr
                && Math.Abs(viewport.Scaling3DScale - 0.7) < 1e-6);
            resolution.Apply(null);
            Require("unchanged settings log once", lines.Count == 1);
            viewport.Size = new Vector2I(1600, 900);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            Require("resize recomputes auto", viewport.Scaling3DMode == Viewport.Scaling3DModeEnum.Bilinear && viewport.Scaling3DScale == 1);
            foreach (var scale in GraphicsPrefs.RenderScales)
            {
                resolution.Apply(scale);
                float expected = (float)(scale ?? 1);
                Require("fixed scale applied", Math.Abs(viewport.Scaling3DScale - expected) < 1e-6
                    && viewport.Scaling3DMode == (expected < 1 ? Viewport.Scaling3DModeEnum.Fsr : Viewport.Scaling3DModeEnum.Bilinear));
            }
            resolution.Apply(0.66);
            viewport.Size = new Vector2I(2560, 1440);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            Require("fixed survives resize", Math.Abs(viewport.Scaling3DScale - 0.66) < 1e-6);
            resolution.Apply(null);
            Require("auto restored", Math.Abs(viewport.Scaling3DScale - 0.75) < 1e-6);
        }
        host.RemoveChild(viewport);
        viewport.Free();
        // The production target is the root Window, whose resize comes from the display server.
        var window = host.GetTree().Root;
        var oldSize = window.Size;
        var oldMode = window.Scaling3DMode;
        float oldScale = window.Scaling3DScale;
        try
        {
            using var resolution = new RenderResolution(window, lines.Add);
            window.Size = new Vector2I(3840, 1080);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            resolution.Apply(null);
            Require("root Window auto applies", window.Scaling3DMode == Viewport.Scaling3DModeEnum.Fsr
                && Math.Abs(window.Scaling3DScale - 0.7) < 1e-6);
            window.Size = new Vector2I(1600, 900);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            Require("root Window resize recomputes auto", window.Scaling3DScale == 1
                && window.Scaling3DMode == Viewport.Scaling3DModeEnum.Bilinear);
        }
        finally
        {
            window.Size = oldSize;
            window.Scaling3DMode = oldMode;
            window.Scaling3DScale = oldScale;
        }
        string? hitch = null;
        HitchLog.Armed = true;
        HitchLog.EndFrame(133, line => hitch = line);
        HitchLog.Armed = false;
        Require("hitch keeps prefix and adds GPU and scale", hitch is not null && hitch.StartsWith("hitch 133 ms: marked ")
            && hitch.Contains(" gc ") && hitch.Contains(" gpu ") && hitch.Contains(" ms, render scale "));
        return $"graphics vectors={count} round_trips=36 bridge=36 viewport=auto/fixed/resize/root-window hitch=gpu/scale";
    }

    private static JsonNode Check(GraphicsPrefsCheck check) => check.Prefs is { } p
        ? new JsonObject { ["ok"] = true, ["prefs"] = JsonNode.Parse(GraphicsPrefs.Save(p)) }
        : new JsonObject { ["ok"] = false, ["error"] = check.Error };

    private static void Require(string label, bool ok)
    {
        if (!ok) throw new InvalidOperationException("graphics: " + label);
    }
}
