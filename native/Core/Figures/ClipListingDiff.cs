using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;

namespace AnimaNative.Figures;

public sealed record ClipListingDiff(bool RevisionChanged, IReadOnlyList<string> AddedKinds,
    IReadOnlyList<string> ChangedUrls, bool TransitionsChanged)
{
    public static ClipListingDiff Compare(JsonObject oldListing, JsonObject newListing)
    {
        static Dictionary<string, JsonNode[]> Kinds(JsonObject listing) =>
            (listing["clips"] as JsonArray ?? new JsonArray()).OfType<JsonObject>()
            .GroupBy(c => (string?)c["kind"] + ((string?)c["role"] is { Length: > 0 } role ? "__" + role : ""))
            .ToDictionary(g => g.Key, g => g.Cast<JsonNode>().ToArray());
        var old = Kinds(oldListing);
        var next = Kinds(newListing);
        return new(!JsonNode.DeepEquals(oldListing["revision"], newListing["revision"]),
            next.Keys.Except(old.Keys).ToArray(),
            next.Keys.Intersect(old.Keys).Where(k => !JsonNode.DeepEquals(
                new JsonArray(old[k].Select(n => n.DeepClone()).ToArray()),
                new JsonArray(next[k].Select(n => n.DeepClone()).ToArray()))).ToArray(),
            !JsonNode.DeepEquals(oldListing["transition_clips"], newListing["transition_clips"]));
    }
}
