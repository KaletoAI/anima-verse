using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Overview;

/// <summary>
/// The event pins of the overview (client3d/src/main.ts <c>updatePins</c>, <c>makePinTexture</c> and the
/// bob in the frame hook), the decisions without a sprite:
///
///   • which locations get a pin: every location with at least one event in <c>events_by_location</c>
///     that is a known place; 🔥 when any event's category is <c>danger</c>, else ❗;
///   • per poll a pin that is no longer wanted goes, a new one comes, an EXISTING one is kept as it is —
///     main.ts skips ids it already has, so a ❗ that becomes a 🔥 keeps its ❗ (mirrored, see the report);
///   • the sprite: a 96 px canvas with the glyph in a 72 px font at (48, 54) (text centred, baseline
///     'middle'), scaled to 3 m, no depth test, at the place's centre x/z and y = <c>height + 3.5</c> —
///     main.ts uses <c>setY</c>, so the y is ABSOLUTE, not above the ground datum (mirrored, see the report);
///   • the bob: <c>bob += dt · 2.2</c> once per frame, then every pin <c>y += sin(bob) · 0.008</c>.
/// No shared vector: main.ts carries this inline; native/tests/EventPinRuleTests.cs derives its cases by hand.
/// </summary>
public static class EventPinRule
{
    public const string Danger = "🔥", Notice = "❗";
    public const int CanvasPx = 96, FontPx = 72;
    /// <summary>The glyph's anchor on the canvas (textAlign centre, textBaseline middle).</summary>
    public const double TextX = 48, TextY = 54;
    /// <summary>Sprite size in metres (<c>pin.scale.setScalar(3)</c>).</summary>
    public const double ScaleM = 3;
    public const double LiftM = 3.5;
    public const double BobRate = 2.2, BobAmplitude = 0.008;

    /// <summary>🔥 for any <c>danger</c> event, ❗ for other events, null for none.</summary>
    public static string? GlyphFor(IReadOnlyCollection<string?> categories)
        => categories.Count == 0 ? null : categories.Any(c => c == "danger") ? Danger : Notice;

    /// <summary>The wanted pins: location id → glyph, for the locations with events that are known places.</summary>
    public static Dictionary<string, string> Wanted(IEnumerable<KeyValuePair<string, IReadOnlyCollection<string?>>> eventsByLocation,
                                                    Func<string, bool> isPlace)
    {
        var wanted = new Dictionary<string, string>();
        foreach (var (id, categories) in eventsByLocation)
        {
            if (!isPlace(id) || GlyphFor(categories) is not { } glyph) continue;
            wanted[id] = glyph;
        }
        return wanted;
    }

    /// <summary>One poll's change: the pins to remove (no longer wanted) and to add (wanted, not there yet).</summary>
    public static (List<string> Remove, List<KeyValuePair<string, string>> Add) Diff(IEnumerable<string> existing,
                                                                                    IReadOnlyDictionary<string, string> wanted)
    {
        var have = existing.ToList();
        var remove = have.Where(id => !wanted.ContainsKey(id)).ToList();
        var add = wanted.Where(kv => !have.Contains(kv.Key)).ToList();
        return (remove, add);
    }

    /// <summary>The pin's y when it is placed: ABSOLUTE <c>height + 3.5</c> (main.ts <c>setY</c>).</summary>
    public static double PinY(double placeHeight) => placeHeight + LiftM;

    /// <summary>One frame of the bob: the new phase and the y step every pin makes.</summary>
    public static (double Bob, double Dy) BobStep(double bob, double dt)
    {
        double next = bob + dt * BobRate;
        return (next, Math.Sin(next) * BobAmplitude);
    }

    /// <summary>
    /// <c>buildPlace</c>'s reading height of a place before a model or far shell measured it (client3d
    /// src/scene/places.ts): area → 3 for a forest style, else 0.3; a building styled as nature → 3 for a
    /// forest, else 0.6; any other building → 4.
    /// </summary>
    public static double DefaultPlaceHeight(bool isBuilding, bool natureSite, string style)
        => !isBuilding ? (style == "forest" ? 3 : 0.3)
         : natureSite ? (style == "forest" ? 3 : 0.6) : 4;
}
