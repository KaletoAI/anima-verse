using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/overview_hud.json against the C# ports <see cref="Bubble"/>,
/// <see cref="BootProgress"/>, <see cref="InfoPanel"/> and <see cref="ScatterPrefs"/>
/// (hand derivations: client3d/scripts/smoke_walk_math.mjs, sections "Speech bubbles",
/// "Location info panel", "Scatter detail distances: typing"; TS sources:
/// client3d/src/game/bubble.ts, boot.ts, infoPanel.ts, prefs.ts).
///
/// <code>
///   TS fn               C#                         shape translation
///   bubbleText          Bubble.Text
///   bubbleMs            Bubble.Ms
///   bootProgress        BootProgress.Of            stage list (the smoke's convention) → IEnumerable&lt;string&gt;;
///                                                  → {percent, label}
///   infoPanelData       InfoPanel.Build            location / character / event rows → the payload parsers
///                                                  (InfoLocation/InfoCharacter/InfoEvent.FromJson); roomOf
///                                                  object → dictionary; view {openable, open} | null → InfoView?;
///                                                  avatar {locationId, pos {x,z} | null} | null → InfoAvatar?;
///                                                  the result IS the HUD's InfoPanelData JsonObject
///   checkScatterPrefs   ScatterPrefs.Check         a JSON number → double, anything else (the TS `typeof !==
///                                                  'number'`) → null; → {ok, prefs | error}
///   scatterLodCfgOf     ScatterPrefs.LodCfgOf      {scatterNearM, scatterFarM, scatterCullM} → ScatterPrefs;
///                                                  ScatterLodCfg → {nearM, farM, cullM}
/// </code>
/// </summary>
public class OverviewHudVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("overview_hud"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["bubbleText"] = a => JsonValue.Create(Bubble.Text(Str(Arity(a, 1, 1)[0]))),
        ["bubbleMs"] = a => JsonValue.Create(Bubble.Ms(Str(Arity(a, 1, 1)[0]))),
        ["bootProgress"] = a =>
        {
            var p = BootProgress.Of(List(Arity(a, 1, 1)[0]).Select(Str));
            return new JsonObject { ["percent"] = p.Percent, ["label"] = p.Label };
        },
        ["infoPanelData"] = a => InfoPanel.Build(
            InfoLocation.FromJson(Element(Arity(a, 6, 6)[0])),
            List(a[1]).Select(n => InfoCharacter.FromJson(Element(n))).ToList(),
            List(a[2]).Select(n => InfoEvent.FromJson(Element(n))).ToList(),
            RoomOf(a[3]),
            ViewOrNull(a[4]),
            AvatarOrNull(a[5])),
        ["checkScatterPrefs"] = a => CheckJson(ScatterPrefs.Check(
            NumberOrNull(Arity(a, 3, 3)[0]), NumberOrNull(a[1]), NumberOrNull(a[2]))),
        ["scatterLodCfgOf"] = a =>
        {
            var cfg = ScatterPrefs.LodCfgOf(Prefs(Arity(a, 1, 1)[0]));
            return new JsonObject { ["nearM"] = cfg.NearM, ["farM"] = cfg.FarM, ["cullM"] = cfg.CullM };
        },
    };

    // ---- shapes -------------------------------------------------------------------------------

    private static JsonArray List(JsonNode? node)
        => node as JsonArray ?? throw new ArgumentException($"expected an array, got {VectorCompare.Show(node)}");

    /// <summary>A payload row as the <see cref="JsonElement"/> the native client parses server JSON into.</summary>
    private static JsonElement Element(JsonNode? node)
        => node is JsonObject ? JsonSerializer.SerializeToElement(node)
            : throw new ArgumentException($"expected an object, got {VectorCompare.Show(node)}");

    /// <summary>The smoke's <c>roomOf</c> object (a <c>Map</c> in TS): character name → room name or id.</summary>
    private static Dictionary<string, string> RoomOf(JsonNode? node)
        => node is JsonObject o
            ? o.ToDictionary(kv => kv.Key, kv => Str(kv.Value), StringComparer.Ordinal)
            : throw new ArgumentException($"expected a roomOf object, got {VectorCompare.Show(node)}");

    private static InfoView? ViewOrNull(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonObject o || o.Count != 2)
            throw new ArgumentException($"expected a view {{openable, open}}, got {VectorCompare.Show(node)}");
        return new InfoView(Bool(o["openable"]), Bool(o["open"]));
    }

    private static InfoAvatar? AvatarOrNull(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonObject o || o.Count != 2)
            throw new ArgumentException($"expected an avatar {{locationId, pos}}, got {VectorCompare.Show(node)}");
        (double X, double Z)? pos = null;
        if (o["pos"] is JsonObject p)
            pos = (VectorCompare.Num(p["x"]), VectorCompare.Num(p["z"]));
        else if (o["pos"] is not null)
            throw new ArgumentException($"expected an avatar pos {{x, z}} | null, got {VectorCompare.Show(o["pos"])}");
        return new InfoAvatar(Str(o["locationId"]), pos);
    }

    /// <summary>The TS <c>typeof raw === 'number'</c>: a JSON number, else null (C#'s "not a number").</summary>
    private static double? NumberOrNull(JsonNode? node) => VectorCompare.TryNum(node, out double d) ? d : null;

    private static ScatterPrefs Prefs(JsonNode? node)
        => node is JsonObject o && o.Count == 3
            ? new ScatterPrefs(VectorCompare.Num(o["scatterNearM"]), VectorCompare.Num(o["scatterFarM"]),
                               VectorCompare.Num(o["scatterCullM"]))
            : throw new ArgumentException($"expected ScatterPrefs, got {VectorCompare.Show(node)}");

    private static JsonObject CheckJson(ScatterPrefsCheck c)
        => c.Prefs is ScatterPrefs p
            ? new JsonObject
            {
                ["ok"] = true,
                ["prefs"] = new JsonObject
                {
                    ["scatterNearM"] = p.ScatterNearM, ["scatterFarM"] = p.ScatterFarM, ["scatterCullM"] = p.ScatterCullM,
                },
            }
            : new JsonObject { ["ok"] = false, ["error"] = c.Error };

    private static bool Bool(JsonNode? node)
        => node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? el.ValueKind == JsonValueKind.True
            : throw new ArgumentException($"expected a boolean, got {VectorCompare.Show(node)}");

    public static TheoryData<string> Cases => VectorFile.Labels("overview_hud");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    // ---- JS semantics the vectors cannot tell apart (kept beside them, see the report) --------

    [Fact]
    public void ConstantsMatchTheTsModules()
    {
        Assert.Equal(140, Bubble.MaxChars);
        Assert.Equal(3500, Bubble.BaseMs);
        Assert.Equal(55, Bubble.MsPerChar);
        Assert.Equal(12000, Bubble.MaxMs);
        Assert.Equal(new[] { "world", "scenes", "tiles", "visible", "figures", "arrival" }, BootProgress.Stages);
        Assert.Equal(new ScatterPrefs(35, 45, 120), ScatterPrefs.Defaults);
        Assert.Equal(5, ScatterPrefs.MinM);
        Assert.Equal(2000, ScatterPrefs.MaxM);
    }

    /// <summary>JS <c>Math.round</c> rounds a half UP (towards +∞), .NET's default is to even.</summary>
    [Theory]
    [InlineData(0.5, 1)]
    [InlineData(2.5, 3)]
    [InlineData(-0.5, 0)]
    [InlineData(-2.5, -2)]
    [InlineData(0.49999999999999994, 0)]
    [InlineData(4503599627370495.5, 4503599627370496)]
    public void JsRoundIsHalfUp(double x, double expected) => Assert.Equal(expected, JsSemantics.Round(x));

    /// <summary>
    /// JS <c>trim()</c> and <c>\s</c> are WhiteSpace + LineTerminator: they include U+FEFF, which
    /// .NET's <see cref="char.IsWhiteSpace(char)"/> does not, and exclude U+0085 (NEL), which it does.
    /// </summary>
    [Fact]
    public void BubbleWhitespaceIsTheJsSet()
    {
        Assert.Equal("a b", Bubble.Text("\uFEFF a\u00A0\u2028b \u3000"));
        Assert.Equal("\u0085a\u0085", Bubble.Text("\u0085a\u0085"));
        Assert.Equal(3500 + 55 * 3, Bubble.Ms("\u0085a\u0085"));
    }

    /// <summary>Lengths and the cut count UTF-16 code units, as JS <c>length</c>/<c>slice</c> do.</summary>
    [Fact]
    public void BubbleCountsUtf16Units()
    {
        string emoji = "\U0001F600"; // two UTF-16 code units
        Assert.Equal(3500 + 55 * 2, Bubble.Ms(emoji));
        string line = new string('a', 138) + emoji + "b";      // 141 units: the cut at 139 splits the pair
        Assert.Equal(new string('a', 138) + "\uD83D" + "…", Bubble.Text(line));
    }

    /// <summary>
    /// <c>roomOf.get(c.name) === r.name</c>: a room without a name matches every character that has
    /// no room (undefined === undefined) — kept as the TS does it.
    /// </summary>
    [Fact]
    public void UnnamedRoomMatchesLikeTheTs()
    {
        var loc = new InfoLocation("L", "Home", null, null, false, null, null,
                                   new[] { new InfoRoom("r1", null) });
        var chars = new[] { new InfoCharacter("A", null, null, null, null), new InfoCharacter("B", null, null, null, null) };
        var data = InfoPanel.Build(loc, chars, Array.Empty<InfoEvent>(),
                                   new Dictionary<string, string> { ["A"] = "elsewhere" }, null, null);
        Assert.Equal("[{\"name\":\"\",\"who\":[\"B\"]}]", data["rooms"]!.ToJsonString());
    }

    /// <summary>The panel data goes over the bridge unchanged: exactly the HUD's InfoPanelData keys, in order.</summary>
    [Fact]
    public void InfoPanelHasTheHudShape()
    {
        var loc = new InfoLocation("L1", "Home", "A house.", "", false, 0, 0, new[] { new InfoRoom("r1", "Kitchen") });
        var data = InfoPanel.Build(loc,
            new[] { new InfoCharacter("A", "cooking", "calm", "Harbor", "14:30") },
            new[] { new InfoEvent("danger", "Fire") },
            new Dictionary<string, string> { ["A"] = "r1" },
            new InfoView(true, false),
            new InfoAvatar("L2", (3, 4)));
        Assert.Equal(
            "{\"id\":\"L1\",\"name\":\"Home\",\"description\":\"A house.\","
            + "\"rooms\":[{\"name\":\"Kitchen\",\"who\":[\"A\"]}],"
            + "\"present\":[{\"name\":\"A\",\"activity\":\"cooking\",\"mood\":\"calm\",\"travelTo\":\"Harbor\",\"eta\":\"14:30\"}],"
            + "\"events\":[{\"danger\":true,\"text\":\"Fire\"}],"
            + "\"travel\":{\"distanceM\":5},\"view\":{\"openable\":true,\"open\":false}}",
            data.ToJsonString());
    }

    /// <summary>A non-finite number is refused like an empty field (<c>Number.isFinite</c>).</summary>
    [Fact]
    public void NonFiniteScatterPrefIsNoNumber()
    {
        Assert.Equal("number", ScatterPrefs.Check(double.NaN, 45, 120).Error);
        Assert.Equal("number", ScatterPrefs.Check(20, double.PositiveInfinity, 120).Error);
        Assert.Equal("number", ScatterPrefs.Check(20, 45, null).Error);
    }
}
