using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The HUD settings kept across starts (<see cref="HudStorage"/>, <c>user://hud_storage.json</c>) — every expected
/// value written by hand from the rules in the class doc and from client3d/src/game/prefs.ts.
/// </summary>
public class HudStorageTests
{
    private const string Lan = "http://192.168.8.244:8000";

    private static HudStorageOp Set(string k, string v) => new(HudStorageOp.Set, k, v);
    private static HudStorageOp Remove(string k) => new(HudStorageOp.Remove, k, null);
    private static readonly HudStorageOp Clear = new(HudStorageOp.Clear, null, null);

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("{ broken")]
    [InlineData("[]")]
    [InlineData("\"servers\"")]
    [InlineData("{\"servers\":{\"http://h:1\":{\"k\":\"v\"}}}")]                  // no version
    [InlineData("{\"version\":2,\"servers\":{\"http://h:1\":{\"k\":\"v\"}}}")]    // a future format
    [InlineData("{\"version\":1,\"servers\":[]}")]
    public void ABrokenOrForeignFileIsEmpty(string? text)
    {
        var s = HudStorage.Parse(text);
        Assert.Equal("{\"version\":1,\"servers\":{}}", s.Serialize());
        Assert.Empty(s.EntriesFor("http://h:1"));
    }

    [Fact]
    public void ParseNormalisesServersAndDropsWhatIsNotAString()
    {
        var s = HudStorage.Parse("{\"version\":1,\"servers\":{"
                                 + "\"192.168.8.244:8000/\":{\"a\":\"1\",\"b\":2,\"c\":null,\"d\":\"x\"},"
                                 + "\"ftp://x\":{\"a\":\"1\"},"
                                 + "\"http://only-numbers:1\":{\"n\":5}}}");
        // "192.168.8.244:8000/" → http:// added, slash dropped; ftp:// is no server; a server left empty goes.
        Assert.Equal("{\"version\":1,\"servers\":{\"http://192.168.8.244:8000\":{\"a\":\"1\",\"d\":\"x\"}}}", s.Serialize());
        Assert.Equal(new Dictionary<string, string> { ["a"] = "1", ["d"] = "x" }, s.EntriesFor(Lan + "/"));
    }

    [Theory]
    [InlineData("192.168.8.244:8000", "http://192.168.8.244:8000")]
    [InlineData(" http://192.168.8.244:8000/ ", "http://192.168.8.244:8000")]
    [InlineData("http://Host.Example:8000", "http://host.example:8000")]   // the origin's host is lower case
    [InlineData("http://host:80/", "http://host")]                         // default port dropped
    [InlineData("https://host:443", "https://host")]
    public void ServerKeyIsTheOrigin(string address, string key)
        => Assert.Equal(key, HudStorage.ServerKey(address));

    [Theory]
    [InlineData("")]
    [InlineData("ftp://x")]
    [InlineData("a b")]
    public void AnUnusableAddressHasNoKey(string address)
    {
        Assert.Null(HudStorage.ServerKey(address));
        var s = new HudStorage();
        Assert.Equal(HudStorageResult.Unchanged, s.Apply(address, Set("k", "v")));
        Assert.Equal("{\"version\":1,\"servers\":{}}", s.Serialize());
    }

    [Fact]
    public void SetRemoveClearPerServer()
    {
        var s = new HudStorage();
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Set("av3d.showAllLocations", "1")));
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Set("b", "x")));
        Assert.Equal(HudStorageResult.Changed, s.Apply("http://other:1", Set("b", "y")));
        Assert.Equal(HudStorageResult.Unchanged, s.Apply(Lan, Set("b", "x")));          // same value
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Set("b", "z")));
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Remove("b")));
        Assert.Equal(HudStorageResult.Unchanged, s.Apply(Lan, Remove("b")));            // already gone
        Assert.Equal("{\"version\":1,\"servers\":{\"http://192.168.8.244:8000\":{\"av3d.showAllLocations\":\"1\"},"
                     + "\"http://other:1\":{\"b\":\"y\"}}}", s.Serialize());
        // clear() empties THIS origin only, like localStorage.clear().
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Clear));
        Assert.Equal(HudStorageResult.Unchanged, s.Apply(Lan, Clear));
        Assert.Equal("{\"version\":1,\"servers\":{\"http://other:1\":{\"b\":\"y\"}}}", s.Serialize());
    }

    [Fact]
    public void RoundTrip()
    {
        var s = new HudStorage();
        s.Apply(Lan, Set("av3d.view.scatter.v1", "{\"scatterNearM\":20,\"scatterFarM\":45,\"scatterCullM\":120}"));
        s.Apply(Lan, Set("q", "Ari \"the bold\" Ünal\n</script>"));
        var again = HudStorage.Parse(s.Serialize());
        Assert.Equal(s.Serialize(), again.Serialize());
        Assert.Equal(s.EntriesFor(Lan), again.EntriesFor(Lan));
    }

    /// <summary>
    /// The cap counts the serialised store in UTF-8 bytes. For one server <c>http://h:1</c> with one entry
    /// <c>k</c> = n × 'a' the file is <c>{"version":1,"servers":{"http://h:1":{"k":"aaa…"}}}</c>, i.e.
    /// <c>{"version":1,</c> 13 + <c>"servers":{</c> 11 + <c>"http://h:1":{</c> 14 + <c>"k":"</c> 5 + n +
    /// <c>"}}}</c> 4 = 47 + n bytes. 262144 − 47 = 262097: n = 262097 fits exactly, 262098 is dropped.
    /// </summary>
    [Fact]
    public void TheCapDropsAWriteThatWouldGrowPast256KB()
    {
        Assert.Equal(262144, HudStorage.MaxBytes);
        var s = new HudStorage();
        Assert.Equal(HudStorageResult.Changed, s.Apply("http://h:1", Set("k", new string('a', 262097))));
        Assert.Equal(262144, s.ByteSize);
        // Growing the same entry by one byte: dropped, the old value stays.
        Assert.Equal(HudStorageResult.TooLarge, s.Apply("http://h:1", Set("k", new string('a', 262098))));
        Assert.Equal(262097, s.EntriesFor("http://h:1")["k"].Length);
        // A new key on top: dropped, and not half-stored.
        Assert.Equal(HudStorageResult.TooLarge, s.Apply("http://h:1", Set("x", "1")));
        Assert.False(s.EntriesFor("http://h:1").ContainsKey("x"));
        // Shrinking always passes.
        Assert.Equal(HudStorageResult.Changed, s.Apply("http://h:1", Set("k", "small")));
        Assert.Equal(HudStorageResult.Changed, s.Apply("http://h:1", Set("x", "1")));
    }

    [Fact]
    public void AFirstWriteTooLargeForTheCapLeavesNoEmptyServer()
    {
        var s = new HudStorage();
        Assert.Equal(HudStorageResult.TooLarge, s.Apply("http://h:1", Set("k", new string('a', 262098))));
        Assert.Equal("{\"version\":1,\"servers\":{}}", s.Serialize());
    }

    [Fact]
    public void TheSessionTokenNeverGoesToDisk()
    {
        var s = new HudStorage();
        Assert.Equal(HudStorageResult.Secret, s.Apply(Lan, Set("k", "xx-tok123-xx"), secret: "tok123"));
        Assert.Equal(HudStorageResult.Secret, s.Apply(Lan, Set("tok123", "v"), secret: "tok123"));
        Assert.Equal("{\"version\":1,\"servers\":{}}", s.Serialize());
        Assert.Equal(HudStorageResult.Changed, s.Apply(Lan, Set("k", "v"), secret: "tok123"));
    }

    [Theory]
    [InlineData("{\"op\":\"set\",\"key\":\"k\",\"value\":\"v\"}", "set", "k", "v")]
    [InlineData("{\"op\":\"set\",\"key\":\"k\",\"value\":\"\"}", "set", "k", "")]
    [InlineData("{\"op\":\"remove\",\"key\":\"k\"}", "remove", "k", null)]
    [InlineData("{\"op\":\"clear\"}", "clear", null, null)]
    public void ParsesTheMirroredCalls(string raw, string op, string? key, string? value)
        => Assert.Equal(new HudStorageOp(op, key, value), HudStorage.ParseOp(raw, out _));

    [Theory]
    [InlineData("nope", "not JSON")]
    [InlineData("[1]", "not an object")]
    [InlineData("{\"op\":\"set\",\"key\":\"k\",\"value\":5}", "set needs a string key and a string value")]
    [InlineData("{\"op\":\"set\",\"value\":\"v\"}", "set needs a string key and a string value")]
    [InlineData("{\"op\":\"remove\"}", "remove needs a string key")]
    [InlineData("{\"op\":\"key\"}", "unknown op 'key'")]
    [InlineData("{}", "unknown op '(none)'")]
    public void RefusesAnythingElse(string raw, string reason)
    {
        Assert.Null(HudStorage.ParseOp(raw, out var why));
        Assert.Equal(reason, why);
    }

    [Fact]
    public void NoEntriesNoSeedScript() => Assert.Equal("", HudStorage.SeedScript(new Dictionary<string, string>()));

    /// <summary>
    /// The seed script keeps every value inside its literal: the default JSON encoder writes quotes, newlines,
    /// <c>&lt;</c>, <c>&gt;</c>, non-ASCII and U+2028 as <c>\uXXXX</c> or <c>\n</c> — so the script is plain ASCII
    /// without a line break or a <c>&lt;/</c>, and the literal reads back as exactly the entries.
    /// </summary>
    [Fact]
    public void SeedScriptEscapesEverythingAValueCanHold()
    {
        var entries = new Dictionary<string, string>
        {
            ["z"] = "plain",
            ["q\"uote"] = "say \"hi\"; alert(1)//",
            ["nl"] = "line1\nline2\r\n",
            ["tag"] = "</script><script>alert(1)</script>",
            ["uni"] = "Ünal \U0001F600 \u2028\u2029 \\ '",
        };
        var script = HudStorage.SeedScript(entries);
        Assert.StartsWith("try { const e = {", script);
        Assert.EndsWith("; for (const k of Object.keys(e)) localStorage.setItem(k, e[k]); } "
                        + "catch (err) { console.warn('[hud storage] seeding localStorage failed', err); } ", script);
        Assert.True(script.All(c => c >= 0x20 && c < 0x7f), "the script is printable ASCII");
        Assert.DoesNotContain("</", script);
        Assert.DoesNotContain("<", script);
        int from = script.IndexOf('{', "try { ".Length);
        int to = script.IndexOf("; for (", System.StringComparison.Ordinal);
        var literal = script[from..to];
        var back = JsonSerializer.Deserialize<Dictionary<string, string>>(literal)!;
        Assert.Equal(entries.OrderBy(e => e.Key), back.OrderBy(e => e.Key));
        // Keys in ordinal order (a stable script for a stable store).
        Assert.Equal(new[] { "nl", "q\"uote", "tag", "uni", "z" }, back.Keys.ToArray());
    }

    [Theory]
    [InlineData("1", true, true)]
    [InlineData("1", false, false)]   // a value left behind by a demoted account
    [InlineData("0", true, false)]
    [InlineData("true", true, false)] // prefs.ts: only the string "1" is on
    public void StartShowAllOnlyForAnAdmin(string stored, bool admin, bool on)
        => Assert.Equal(on, HudStorage.StartShowAll(new Dictionary<string, string> { [HudStorage.ShowAllKey] = stored }, admin));

    [Fact]
    public void StartShowAllWithoutAStoredValueIsOff()
        => Assert.False(HudStorage.StartShowAll(new Dictionary<string, string>(), isAdmin: true));

    // loadScatterPrefs (client3d/src/game/prefs.ts), case by case.
    [Theory]
    [InlineData(null, 35, 45, 120)]
    [InlineData("", 35, 45, 120)]
    [InlineData("nope", 35, 45, 120)]                                                      // not JSON
    [InlineData("[20,45,120]", 35, 45, 120)]                                               // an array is no object
    [InlineData("null", 35, 45, 120)]
    [InlineData("{\"scatterNearM\":20}", 20, 45, 120)]                                     // field by field
    [InlineData("{\"scatterNearM\":\"20\"}", 35, 45, 120)]                                 // a numeric string is no number
    [InlineData("{\"scatterNearM\":100}", 35, 45, 120)]                                    // 100 < 45 fails: all defaults
    [InlineData("{\"scatterNearM\":1,\"scatterFarM\":10,\"scatterCullM\":3000}", 5, 10, 2000)]   // clamped to [5, 2000]
    [InlineData("{\"scatterNearM\":1,\"scatterFarM\":3000,\"scatterCullM\":4000}", 35, 45, 120)] // 2000 = 2000: not climbing
    [InlineData("{\"scatterNearM\":20,\"scatterFarM\":60,\"scatterCullM\":300}", 20, 60, 300)]
    public void LoadScatterPrefs(string? raw, double near, double far, double cull)
        => Assert.Equal(new ScatterPrefs(near, far, cull), ScatterPrefs.Load(raw));
}
