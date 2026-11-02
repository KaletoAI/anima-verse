using System;
using System.Text.Json;
using AnimaNative.Figures;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>§ A8c: the hand-derived numbers of smoke_finale_clip.mjs [1]–[7].
/// These catch server-time seeking, repeated-id replay, scaled/frozen clocks and an unclamped seek.</summary>
public sealed class FinaleClipTests
{
    private static FinaleBlock Block(string id, double duration = 1.033)
        => new(id, "fixture-finale", "b", .9, duration);

    [Fact]
    public void NewIdStartsAtZeroRegardlessOfServerElapsed()
    {
        var (play, seen) = FinaleClip.Adopt(null, "", Block("f1"), true);
        Assert.Equal(new FinalePlay("f1", "fixture-finale", "b", 0, 1.033), play);
        Assert.Equal("f1", seen);
        Assert.Equal((play, seen), FinaleClip.Adopt(play, seen, Block("f1") with { ElapsedS = 1.033 }, true));
    }

    [Fact]
    public void FramesFreezeAndFinishThenSameIdNeverRestarts()
    {
        var (play, seen) = FinaleClip.Adopt(null, "", Block("f1"), true);
        var step = FinaleClip.Step(play, .5, false);
        Assert.Equal("fixture-finale__b", step.Clip);
        Assert.Equal(.5, step.T, 9);
        step = FinaleClip.Step(step.Play, .5, true);
        Assert.Equal(.5, step.T, 9);
        step = FinaleClip.Step(step.Play, .5, false);
        Assert.Equal(1, step.T, 9);
        step = FinaleClip.Step(step.Play, .04, false);
        Assert.Equal((null, null, 0d), step);
        Assert.Equal((null, "f1"), FinaleClip.Adopt(step.Play, seen, Block("f1") with { ElapsedS = 3.2 }, true));
        (play, seen) = FinaleClip.Adopt(null, seen, Block("f2"), true);
        Assert.Equal(0, play!.T);
        Assert.Equal("f2", seen);
    }

    [Fact]
    public void SoloUsesPlainKindAndInvalidRoleNormalizesToSolo()
    {
        var solo = FinaleClip.Adopt(null, "", new("s1", "fixture-solo", null, .9, 1.333), true);
        Assert.Equal("fixture-solo", FinaleClip.Step(solo.Play, .1, false).Clip);
        var invalid = FinaleClip.Adopt(null, "", Block("s2") with { Role = "c" }, true);
        Assert.Null(invalid.Play!.Role);
    }

    [Fact]
    public void ActionEndingDropsPlaybackAndMarksLateIdSeen()
    {
        var (play, seen) = FinaleClip.Adopt(null, "", Block("f2"), true);
        Assert.Null(FinaleClip.Adopt(play, seen, null, false).Play);
        Assert.Equal((null, "f3"), FinaleClip.Adopt(null, "", Block("f3"), false));
        Assert.Null(FinaleClip.Adopt(null, "f3", Block("f3"), true).Play);
        // A disappearing payload alone does not stop a locally running finale.
        Assert.Equal(play, FinaleClip.Adopt(play, seen, null, true).Play);
    }

    [Fact]
    public void JunkStartsNothingButNonemptyIdIsConsumed()
    {
        Assert.Equal((null, ""), FinaleClip.Adopt(null, "", Block(""), true));
        foreach (double duration in new[] { 0, -1, double.NaN, double.PositiveInfinity })
            Assert.Equal((null, "f4"), FinaleClip.Adopt(null, "", Block("f4", duration), true));
        Assert.Equal((null, "f5"), FinaleClip.Adopt(null, "", Block("f5") with { Kind = "" }, true));
    }

    [Fact]
    public void SeekStaysOneMillisecondBeforeEndAndNonpositiveDtStands()
    {
        var play = new FinalePlay("x", "k", "a", .9, 1);
        var step = FinaleClip.Step(play, .0995, false);
        Assert.Equal(.999, step.T, 9);
        Assert.Equal(.9995, step.Play!.T, 9);
        Assert.Equal("k__a", step.Clip);
        foreach (double dt in new[] { 0, -1, double.NaN })
            Assert.Equal(.9, FinaleClip.Step(play, dt, false).T, 9);
        Assert.Equal((null, null, 0d), FinaleClip.Step(null, .1, false));
    }

    [Fact]
    public void WorldmapParsesFinaleAndSafelyIgnoresAbsentNullOrNonobjectBlocks()
    {
        using var map = JsonDocument.Parse("""
            {"characters":[
              {"name":"pair","finale":{"id":"f1","kind":"fixture-finale","role":"b","elapsed_s":0.9,"duration_s":1.033}},
              {"name":"solo","finale":{"id":"s1","kind":"fixture-solo","role":null,"elapsed_s":0.9,"duration_s":1.333}},
              {"name":"absent"},{"name":"null","finale":null},{"name":"junk","finale":42},
              {"name":"fields","finale":{"id":23,"kind":[],"role":true,"elapsed_s":"bad","duration_s":{}}}
            ]}
            """);
        var rows = CharacterRow.ParseList(map.RootElement);
        Assert.Equal(Block("f1"), rows[0].Finale);
        Assert.Equal(new FinaleBlock("s1", "fixture-solo", null, .9, 1.333), rows[1].Finale);
        for (int i = 2; i < 5; i++) Assert.Null(rows[i].Finale);
        Assert.Null(FinaleClip.Adopt(null, "", rows[5].Finale, true).Play);
    }
}
