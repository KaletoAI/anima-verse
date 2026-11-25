using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Orders;

/// <summary>
/// The server's POSE transition rules, resolved the way app/core/animation_clips.py <c>resolve_pose_transition</c>
/// resolves them (plan E3 decision 14): the client picks its own entry and exit clips from the phase's pose. Read from
/// the listing <c>GET /assets/animation-clips</c>: <c>transitions</c> (rules <c>{from, to, kind}</c> with pose keys,
/// <c>*</c> or a place group <c>@stand</c> · <c>@seat</c> · <c>@ground</c> · <c>@lie</c>) and <c>pose_groups</c>
/// (pose key → group). Vector shared/test-vectors/pose_transition.json, derived in scripts/smoke_access_auto.py.
/// </summary>
public sealed class PoseTransitions
{
    /// <summary>The wildcard side of a rule (<c>animation_clips.TRANSITION_ANY</c>).</summary>
    public const string Any = "*";

    /// <summary>The groups a rule may name as <c>@group</c> (<c>animation_clips._RULE_GROUPS</c>).</summary>
    public static readonly IReadOnlyList<string> RuleGroups = new[] { "stand", "seat", "ground", "lie" };

    private sealed record Rule(string From, string To, JsonElement Kind);

    private readonly List<Rule> _rules;
    private readonly Dictionary<string, string> _groups;

    private PoseTransitions(List<Rule> rules, Dictionary<string, string> groups)
    {
        _rules = rules;
        _groups = groups;
    }

    /// <summary>
    /// The table of a listing. A row that is no object or lacks <c>from</c>, <c>to</c> or <c>kind</c> is dropped; names
    /// are trimmed and lower-cased. A group outside <see cref="RuleGroups"/> is no group. Missing fields: an empty table.
    /// </summary>
    public static PoseTransitions Parse(JsonElement listing)
    {
        var rules = new List<Rule>();
        var groups = new Dictionary<string, string>(StringComparer.Ordinal);
        if (listing.ValueKind == JsonValueKind.Object)
        {
            if (listing.TryGetProperty("transitions", out var list) && list.ValueKind == JsonValueKind.Array)
                foreach (var r in list.EnumerateArray())
                {
                    if (r.ValueKind != JsonValueKind.Object) continue;
                    var from = Key(r, "from");
                    var to = Key(r, "to");
                    if (from.Length == 0 || to.Length == 0 || !r.TryGetProperty("kind", out var kind)) continue;
                    bool hasKind = kind.ValueKind switch
                    {
                        JsonValueKind.String => kind.GetString()!.Trim().Length > 0,
                        JsonValueKind.Object => true,
                        _ => false,
                    };
                    if (hasKind) rules.Add(new Rule(from, to, kind.Clone()));
                }
            if (listing.TryGetProperty("pose_groups", out var map) && map.ValueKind == JsonValueKind.Object)
                foreach (var p in map.EnumerateObject())
                {
                    if (p.Value.ValueKind != JsonValueKind.String) continue;
                    var g = p.Value.GetString()!.Trim().ToLowerInvariant();
                    if (((IList<string>)RuleGroups).Contains(g)) groups[p.Name.Trim().ToLowerInvariant()] = g;
                }
        }
        return new PoseTransitions(rules, groups);
    }

    /// <summary>
    /// The entry bridge onto <paramref name="poseKey"/>: <c>rule_kind(resolve_pose_transition("walking", poseKey))</c>;
    /// null without a rule, <c>""</c> for a rule whose kind is a per-role map.
    /// </summary>
    public string? EntryKind(string poseKey) => KindOf(ResolvePose("walking", poseKey));

    /// <summary>The exit bridge out of <paramref name="poseKey"/>: <c>resolve_pose_transition(poseKey, "standing")</c>.</summary>
    public string? ExitKind(string poseKey) => KindOf(ResolvePose(poseKey, "standing"));

    /// <summary>
    /// <c>resolve_pose_transition</c>: <see cref="Resolve"/>, then — only when that finds nothing — the target's group
    /// (<c>from → @group</c>), then the source's group (<c>@group → to</c>).
    /// </summary>
    private Rule? ResolvePose(string from, string to)
    {
        var rule = Resolve(from, to);
        if (rule is not null) return rule;
        string toGroup = GroupOf(to), fromGroup = GroupOf(from);
        if (toGroup.Length > 0) rule = Resolve(from, toGroup);
        if (rule is null && fromGroup.Length > 0) rule = Resolve(fromGroup, to);
        return rule;
    }

    /// <summary>
    /// <c>resolve_transition</c>: most specific rule first, independent of the table's order — both named, then
    /// <c>(from, *)</c>, then <c>(*, to)</c>. A switch onto the same pose (or from/to nothing) is no transition.
    /// </summary>
    private Rule? Resolve(string from, string to)
    {
        var src = (from ?? "").Trim().ToLowerInvariant();
        var dst = (to ?? "").Trim().ToLowerInvariant();
        if (src.Length == 0 || dst.Length == 0 || src == dst) return null;
        Rule? wildTo = null, wildFrom = null;
        foreach (var r in _rules)
        {
            if (r.From == src && r.To == dst) return r;
            if (r.From == src && r.To == Any) wildTo ??= r;
            else if (r.From == Any && r.To == dst) wildFrom ??= r;
        }
        return wildTo ?? wildFrom;
    }

    private string GroupOf(string pose)
        => _groups.TryGetValue((pose ?? "").Trim().ToLowerInvariant(), out var g) ? "@" + g : "";

    /// <summary><c>rule_kind(rule)</c> without a role: a per-role map names no clip (<c>""</c>).</summary>
    private static string? KindOf(Rule? rule)
        => rule is null ? null : rule.Kind.ValueKind == JsonValueKind.String ? rule.Kind.GetString()!.Trim().ToLowerInvariant() : "";

    private static string Key(JsonElement row, string name)
        => row.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()!.Trim().ToLowerInvariant() : "";
}
