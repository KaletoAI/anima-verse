using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/graphics_prefs.json against the C# port <see cref="GraphicsPrefs"/> (hand derivations:
/// client3d/scripts/smoke_graphics_prefs.mjs; TS source: client3d/src/game/prefs.ts).
///
/// <code>
///   TS fn                     C#                                     shape translation
///   loadGraphicsPrefs         GraphicsPrefs.Load                     string | null; → {antiAliasing, shadows}
///   checkGraphicsPrefs        GraphicsPrefs.Check                    two raw JSON values; → {ok, prefs} | {ok, error}
///   saveGraphicsPrefs         GraphicsPrefs.Save                     {antiAliasing, shadows} → GraphicsPrefs
///   msaaSamplesOf             GraphicsPrefs.MsaaSamplesOf
///   browserAntialias          GraphicsPrefs.BrowserAntialias         {antiAliasing, shadows} → GraphicsPrefs
///   pickBrowserAntiAliasing   GraphicsPrefs.PickBrowserAntiAliasing
///   graphicsPrefsConstants    Key / Levels / Defaults                the smoke adapter's {key, levels, defaults}
/// </code>
/// </summary>
public class GraphicsPrefsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("graphics_prefs"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["autoRenderScale"] = a => JsonValue.Create(GraphicsPrefs.AutoRenderScale(a[0]!.GetValue<double>(), a[1]!.GetValue<double>())),
        ["effectiveRenderScale"] = a => JsonValue.Create(GraphicsPrefs.EffectiveRenderScale(GraphicsPrefs.RenderScaleOf(a[0]), a[1]!.GetValue<double>(), a[2]!.GetValue<double>())),
        ["loadGraphicsPrefs"] = a => PrefsJson(GraphicsPrefs.Load(a[0]?.GetValue<string>())),
        ["checkGraphicsPrefs"] = a => CheckJson(GraphicsPrefs.Check(a[0], a[1], a.Count > 2 ? a[2] : null)),
        ["saveGraphicsPrefs"] = a => JsonValue.Create(GraphicsPrefs.Save(Prefs(a[0]))),
        ["msaaSamplesOf"] = a => JsonValue.Create(GraphicsPrefs.MsaaSamplesOf(a[0]!.GetValue<string>())),
        ["browserAntialias"] = a => JsonValue.Create(GraphicsPrefs.BrowserAntialias(Prefs(a[0]))),
        ["pickBrowserAntiAliasing"] = a => JsonValue.Create(GraphicsPrefs.PickBrowserAntiAliasing(
            a[0]!.GetValue<bool>(), a[1]!.GetValue<string>())),
        ["graphicsPrefsConstants"] = _ =>
        {
            var levels = new JsonArray();
            foreach (var l in GraphicsPrefs.Levels) levels.Add(l);
            return new JsonObject { ["key"] = GraphicsPrefs.Key, ["levels"] = levels, ["defaults"] = PrefsJson(GraphicsPrefs.Defaults) };
        },
    };

    /// <summary>A vector's TS <c>GraphicsPrefs</c> object (always well-formed in the file).</summary>
    private static GraphicsPrefs Prefs(JsonNode? node)
    {
        var o = node!.AsObject();
        return new GraphicsPrefs(o["antiAliasing"]!.GetValue<string>(), o["shadows"]!.GetValue<bool>(), GraphicsPrefs.RenderScaleOf(o["renderScale"]));
    }

    private static JsonObject PrefsJson(GraphicsPrefs p) => new() { ["antiAliasing"] = p.AntiAliasing, ["shadows"] = p.Shadows, ["renderScale"] = GraphicsPrefs.RenderScaleJson(p.RenderScale) };

    private static JsonObject CheckJson(GraphicsPrefsCheck c) => c.Prefs is { } p
        ? new JsonObject { ["ok"] = true, ["prefs"] = PrefsJson(p) }
        : new JsonObject { ["ok"] = false, ["error"] = c.Error };

    public static TheoryData<string> Cases => VectorFile.Labels("graphics_prefs");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>What the scene stores reads back as the same prefs (save ∘ load is the identity on every pair).</summary>
    [Fact]
    public void SaveLoadRoundTrip()
    {
        foreach (var aa in GraphicsPrefs.Levels)
            foreach (var on in new[] { true, false })
            foreach (var scale in GraphicsPrefs.RenderScales)
            {
                var p = new GraphicsPrefs(aa, on, scale);
                Assert.Equal(p, GraphicsPrefs.Load(GraphicsPrefs.Save(p)));
            }
    }
}
