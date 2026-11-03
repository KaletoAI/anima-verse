using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Figures;
using Xunit;

namespace AnimaNative.Tests;

public class AltClipLibraryTests
{
    [Fact]
    public void ListingAppendsAlternativesWithTheirOwnSetFlagsAndCalibration()
    {
        using var listing = JsonDocument.Parse("""
            {"clips":[{"kind":"pair","role":"b","url":"/base"}],"alt_clips":[
              {"kind":"pair","role":"b","alt":"wave","set":"custom","url":"/alt","loop":false,
               "root_motion":{"mode":"keep"},"height_offsets_cm":{"ground":3,"seat":4},"orientation":{"shift_cm":[5,6]}},
              {"kind":"group","role":"e","alt":"arm-down","url":"/group","root_motion":{"mode":"strip"}},
              {"kind":"solo~wave","alt":"ignored","url":"/solo"},null,{"kind":"bad","url":""}
            ]}
            """);
        var entries = ClipLibraryRules.ParseEntries(listing.RootElement);
        Assert.Equal(new[] { "pair__b", "pair__b~wave", "group__e~arm-down", "solo~wave" }, entries.Select(e => e.Kind));
        var alt = entries[1];
        Assert.Equal("/alt", alt.Url);
        Assert.Equal("custom", alt.Set);
        Assert.False(alt.Loops);
        Assert.True(alt.RootMotion);
        Assert.True(alt.KeepFacing);
        Assert.Equal(new ClipHeightOffsets(3, 4, 0) { Shift = new ClipShift(5, 6) }, alt.HeightOffsets);
        Assert.True(entries[2].Loops);
        Assert.False(entries[2].RootMotion);
        Assert.False(entries[2].KeepFacing);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"clips\":null,\"alt_clips\":42}")]
    public void MissingOrMalformedListsAreEmpty(string json)
    {
        using var listing = JsonDocument.Parse(json);
        Assert.Empty(ClipLibraryRules.ParseEntries(listing.RootElement));
    }
}

public class PairAltSelectionTests
{
    [Theory]
    [InlineData(true, true, "group__e~wave")]
    [InlineData(false, true, "group__e")]
    [InlineData(false, false, null)]
    public void AlternativeUsesOwnBaseOnlyWhenUnavailable(bool haveAlt, bool haveBase, string? expected)
    {
        var row = new PairInteraction("p", "group", "e", new Dictionary<string, string>(),
            new PairAnchor(10, 22, Math.PI / 2, "seat"), 3, 2, true, 1) { Alt = "wave" };
        var play = PairPlay.Adopt(null, row, 1, out _)!;
        bool Usable(string name) => name == "group__e~wave" ? haveAlt : name == "group__e" && haveBase;
        Assert.Equal("group__e", play.Base);
        Assert.Equal(expected, play.ResolveClip(Usable));
        Assert.Equal(1, play.Advance(0), 9);
        Assert.Equal(row.Anchor, play.Anchor);
        Assert.Equal("group__e~wave", play.Clip); // fallback does not change the poll's request
    }

    [Fact]
    public void SameIdAlternativeChangeRetainsEntryBlend()
    {
        var row = new PairInteraction("p", "pair", "b", new Dictionary<string, string>(), new PairAnchor(10, 22, 0, null), 3, 2, true, 1);
        var play = PairPlay.Adopt(null, row, 1, out _)!;
        play.Blend = (new PairPose(1, 2, 3, 0), 4);
        var alt = PairPlay.Adopt(play, row with { Alt = "wave" }, 2, out var fresh)!;
        Assert.True(fresh);
        Assert.Equal(play.Blend, alt.Blend);
        Assert.Equal(3, alt.ClipT);
        Assert.Equal("pair__b~wave", alt.Clip);
        Assert.Equal("pair__b", alt.Base);
    }
}
