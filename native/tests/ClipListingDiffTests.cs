using System.Text.Json.Nodes;
using AnimaNative.Figures;
using Xunit;

namespace AnimaNative.Tests;

public class ClipListingDiffTests
{
    private static JsonObject Listing(string revision, string clips = "[]", string transitions = "[]")
        => JsonNode.Parse($$"""{"revision":"{{revision}}","clips":{{clips}},"transition_clips":{{transitions}}}""")!.AsObject();

    [Fact] public void SameRevisionNoChange()
        => Assert.False(ClipListingDiff.Compare(Listing("a"), Listing("a")).RevisionChanged);
    [Fact] public void AddedKindListed()
        => Assert.Equal(new[] { "wave" }, ClipListingDiff.Compare(Listing("a"), Listing("b", """[{"kind":"wave","url":"/wave?v=1"}]""")).AddedKinds);
    [Fact] public void ChangedUrlListed()
        => Assert.Equal(new[] { "walk" }, ClipListingDiff.Compare(
            Listing("a", """[{"kind":"walk","url":"/walk?v=1"}]"""),
            Listing("b", """[{"kind":"walk","url":"/walk?v=2"}]""")).ChangedUrls);
    [Fact] public void TransitionsChangedFlag()
        => Assert.True(ClipListingDiff.Compare(Listing("a"), Listing("b", transitions: """[{"from":"idle","to":"walk","kind":"step"}]""")).TransitionsChanged);
    [Fact] public void PairRolesAndSetsAreDistinct()
        => Assert.Equal(new[] { "pair__a" }, ClipListingDiff.Compare(
            Listing("a", """[{"kind":"pair","role":"a","set":"x","url":"/a?v=1"},{"kind":"pair","role":"b","url":"/b"}]"""),
            Listing("b", """[{"kind":"pair","role":"a","set":"x","url":"/a?v=2"},{"kind":"pair","role":"b","url":"/b"}]""")).ChangedUrls);
    [Fact]
    public void AlternativeAdditionsAndUpdatesAreIndexedSeparatelyFromBase()
    {
        var old = Listing("a", """[{"kind":"pair","role":"b","url":"/base"}]""");
        var next = (JsonObject)old.DeepClone();
        next["alt_clips"] = JsonNode.Parse("""[{"kind":"pair","role":"b","alt":"wave","url":"/wave?v=1"}]""");
        Assert.Equal(new[] { "pair__b~wave" }, ClipListingDiff.Compare(old, next).AddedKinds);
        var changed = (JsonObject)next.DeepClone();
        changed["alt_clips"]![0]!["url"] = "/wave?v=2";
        Assert.Equal(new[] { "pair__b~wave" }, ClipListingDiff.Compare(next, changed).ChangedUrls);
    }
}
