using System.Linq;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Browser smoke_overview_labels.mjs [B], ported without shared vectors: concatenate icons, join only nonempty
/// titles with LF, and key = text + U+0001 + title. Also pin the worldmap boundary's malformed-input filtering.
/// </summary>
public class NameBadgeTests
{
    [Theory]
    [InlineData("null", "", "", "\u0001")]
    [InlineData("[]", "", "", "\u0001")]
    [InlineData("[{\"icon\":\"🔒\",\"title\":\"Private\"}]", "🔒", "Private", "🔒\u0001Private")]
    [InlineData("[{\"icon\":\"🔒\",\"title\":\"A\"},{\"icon\":\"⭐\",\"title\":\"\"}]", "🔒⭐", "A", "🔒⭐\u0001A")]
    public void BrowserSmokeB(string json, string text, string title, string key)
    {
        var badges = OverviewLabels.TagBadges(Parse(json).Badges);
        Assert.Equal(text, badges.Text);
        Assert.Equal(title, badges.Title);
        Assert.Equal(key, badges.Key);
    }

    [Fact]
    public void BrowserSmokeBTitleOnlyChangeChangesKey()
    {
        var first = OverviewLabels.TagBadges(Parse("""[{"icon":"🔒","title":"Private"}]""").Badges);
        var next = OverviewLabels.TagBadges(Parse("""[{"icon":"🔒","title":"Private (state: X)"}]""").Badges);
        Assert.Equal(first.Text, next.Text);
        Assert.NotEqual(first.Key, next.Key);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("null")]
    [InlineData("{}")]
    [InlineData("\"🔒\"")]
    [InlineData("false")]
    [InlineData("3")]
    public void MissingNullAndNonArrayAreEmpty(string? json)
    {
        Assert.Empty(Parse(json).Badges);
        Assert.Equal("\u0001", OverviewLabels.TagBadges(null).Key);
    }

    [Fact]
    public void FiltersInvalidIconsKeepsOrderAndOptionalTitlesWithoutTrimming()
    {
        var row = Parse("""
            [null, false, 5, "🔒", {}, {"icon":null}, {"icon":4}, {"icon":"","title":"Dropped"},
             {"icon":"🔒","title":"Privat"}, {"icon":"💞"}, {"icon":"🔓","title":null},
             {"icon":"⭐","title":3}, {"icon":" ","title":" "}, {"icon":"!","title":"Offen"}]
            """);
        Assert.Equal(new[] { "🔒", "💞", "🔓", "⭐", " ", "!" }, row.Badges.Select(b => b.Icon));
        var badges = OverviewLabels.TagBadges(row.Badges);
        Assert.Equal("🔒💞🔓⭐ !", badges.Text);
        Assert.Equal("Privat\n \nOffen", badges.Title);
    }

    [Fact]
    public void TagRowsUseTheSameParserAndNextPollClearsBadges()
    {
        using var map = JsonDocument.Parse("""{"characters":[{"name":"Ada","badges":[{"icon":"🔒","title":"Private"}]}]}""");
        var character = CharacterRow.ParseList(map.RootElement).Single();
        var tag = OverviewLabels.RowsOf(map.RootElement).Rows.Single();
        Assert.Equal(character.Badges, tag.Badges);
        Assert.Empty(Parse(null).Badges);
        Assert.Empty(OverviewLabels.RowsOf(JsonSerializer.SerializeToElement(new { characters = new[] { new { name = "Ada" } } })).Rows.Single().Badges);
    }

    private static CharacterRow Parse(string? badges)
    {
        using var map = JsonDocument.Parse("{\"characters\":[{\"name\":\"Ada\"" + (badges is null ? "" : ",\"badges\":" + badges) + "}]}");
        return CharacterRow.ParseList(map.RootElement).Single();
    }
}
