using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Overview;

/// <summary>The part of a map character's <c>travel</c> block (§ A11) a name tag reads (TS <c>TagTravel</c>).</summary>
/// <param name="StartsInS">
/// <c>starts_in_s</c> as JS would test it: null for absent / null / any falsy value, otherwise the number (a truthy
/// non-number is kept as 1 — only its truthiness matters).
/// </param>
/// <param name="EtaHhmm"><c>eta_hhmm</c> when it is a string, else null.</param>
public readonly record struct TagTravel(double? StartsInS, string? EtaHhmm)
{
    /// <summary>The <c>travel</c> value of a map character row: null when absent or JSON null (JS falsy).</summary>
    public static TagTravel? FromJson(JsonElement row)
    {
        if (row.ValueKind != JsonValueKind.Object || !row.TryGetProperty("travel", out var t)) return null;
        if (t.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False) return null;
        if (t.ValueKind != JsonValueKind.Object) return new TagTravel(null, null);   // a truthy non-object: under way
        double? starts = null;
        if (t.TryGetProperty("starts_in_s", out var s))
        {
            starts = s.ValueKind switch
            {
                JsonValueKind.Number => s.GetDouble(),
                JsonValueKind.True => 1,
                JsonValueKind.String when s.GetString()!.Length > 0 => 1,
                _ => null,
            };
        }
        string? eta = t.TryGetProperty("eta_hhmm", out var e) && e.ValueKind == JsonValueKind.String ? e.GetString() : null;
        return new TagTravel(starts, eta);
    }
}

/// <summary>One character's tag inputs from a world-map payload.</summary>
public sealed record TagRow(string Name, string Activity, TagTravel? Travel);

/// <summary>
/// Port of client3d/src/scene/nameTags.ts — the rules behind a character's name tag and a location's name on the
/// overview map. Vectors: shared/test-vectors/overview_labels.json [V/T/N/A/L] (hand derivations in
/// client3d/scripts/smoke_overview_labels.mjs). The text runs JS semantics: a falsy <c>starts_in_s</c> is null, 0 or
/// NaN; an <c>eta_hhmm</c> is shown when it is a non-empty string.
/// </summary>
public static class OverviewLabels
{
    /// <summary>Name tags show only while the camera is closer to its target than this (m).</summary>
    public const double TagMaxCamDist = 55;
    /// <summary>A model figure's tag hangs this far above the top of its head (m).</summary>
    public const double TagAboveHeadM = 0.45;
    /// <summary>A portrait sprite (no model) carries its tag this far BELOW its root (m).</summary>
    public const double TagPortraitY = -0.15;
    /// <summary>A location's name floats this far above the top of its place (m).</summary>
    public const double LocationLabelLiftM = 2.2;
    /// <summary>The walker in front of a travelling character's name.</summary>
    public const string Walker = "🚶";

    /// <summary><c>tagVisible</c>: not hidden, not the camera's own first-person body, camera closer than 55 m (strict).</summary>
    public static bool TagVisible(double camDist, bool hidden, bool ownFirstPerson)
        => !hidden && !ownFirstPerson && camDist < TagMaxCamDist;

    /// <summary><c>tagTravelling</c>: a travel block exists and its start does not lie ahead.</summary>
    public static bool TagTravelling(TagTravel? travel)
        => travel is { } t && !Truthy(t.StartsInS);

    /// <summary><c>tagName</c>: "🚶 HH:MM name" (the clock only when the server rendered one) while under way, else the name.</summary>
    public static string TagName(string name, TagTravel? travel)
    {
        if (!TagTravelling(travel)) return name;
        string eta = travel!.Value.EtaHhmm is { Length: > 0 } hhmm ? " " + hhmm : "";
        return $"{Walker}{eta} {name}";
    }

    /// <summary><c>tagAnchorY</c>: 0.45 m over a model figure of <paramref name="figureHeight"/> m, −0.15 for a portrait (null).</summary>
    public static double TagAnchorY(double? figureHeight)
        => figureHeight is { } h ? h + TagAboveHeadM : TagPortraitY;

    /// <summary><c>locationLabelLift</c>: the label's height above the place's ground datum.</summary>
    public static double LocationLabelLift(double placeHeight) => placeHeight + LocationLabelLiftM;

    /// <summary>
    /// The tag inputs of every named character of a <c>/play/worldmap</c> payload: name, <c>activity || ''</c>
    /// (npcs.ts), the travel block; and the payload's <c>avatar</c> name ("" when absent).
    /// </summary>
    public static (List<TagRow> Rows, string Avatar) RowsOf(JsonElement map)
    {
        var rows = new List<TagRow>();
        string avatar = "";
        if (map.ValueKind != JsonValueKind.Object) return (rows, avatar);
        if (map.TryGetProperty("avatar", out var a) && a.ValueKind == JsonValueKind.String) avatar = a.GetString()!;
        if (!map.TryGetProperty("characters", out var chars) || chars.ValueKind != JsonValueKind.Array) return (rows, avatar);
        foreach (var c in chars.EnumerateArray())
        {
            if (c.ValueKind != JsonValueKind.Object) continue;
            string name = c.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String ? n.GetString()! : "";
            if (name.Length == 0) continue;
            string activity = c.TryGetProperty("activity", out var act) && act.ValueKind == JsonValueKind.String ? act.GetString()! : "";
            rows.Add(new TagRow(name, activity, TagTravel.FromJson(c)));
        }
        return (rows, avatar);
    }

    private static bool Truthy(double? v) => v is { } d && d != 0 && !double.IsNaN(d);
}
