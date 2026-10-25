using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Overview;

/// <summary>
/// The event pins of the overview (client3d/src/game/eventPins.ts <c>pinGlyph</c>/<c>pinY</c>, main.ts
/// <c>updatePins</c>, <c>makePinTexture</c> and the bob in the frame hook), the decisions without a sprite:
///
///   • which locations get a pin: every location with at least one event in <c>events_by_location</c>
///     that is a known place; 🔥 when any event's category is <c>danger</c>, else ❗ (<see cref="PinGlyph"/>);
///   • per poll a pin whose glyph changed (an event turned into a danger) or that is no longer wanted goes, a
///     wanted one without a pin comes, and EVERY wanted pin is placed again (<see cref="Diff"/>) — the place's
///     ground datum can settle after the pin was made (commit 99c16a69);
///   • the sprite: a 96 px canvas with the glyph in a 72 px font at (48, 54) (text centred, baseline
///     'middle'), scaled to 3 m, no depth test, at the place's centre x/z and
///     y = ground datum + place height + 3.5 (<see cref="PinY"/>);
///   • the bob: <c>bob += dt · 2.2</c> once per frame, then every pin <c>y += sin(bob) · 0.008</c>.
/// Vectors: shared/test-vectors/event_pins.json (pinGlyph, pinY; derivations in
/// client3d/scripts/smoke_event_pins.mjs). The rest is inline in main.ts; native/tests/PickingTests.cs derives
/// its cases by hand.
/// </summary>
public static class EventPinRule
{
    public const string Danger = "🔥", Notice = "❗";
    public const int CanvasPx = 96, FontPx = 72;
    /// <summary>The glyph's anchor on the canvas (textAlign centre, textBaseline middle).</summary>
    public const double TextX = 48, TextY = 54;
    /// <summary>Sprite size in metres (<c>pin.scale.setScalar(3)</c>).</summary>
    public const double ScaleM = 3;
    /// <summary><c>PIN_LIFT_M</c>: metres the pin floats above the top of its place.</summary>
    public const double LiftM = 3.5;
    public const double BobRate = 2.2, BobAmplitude = 0.008;

    /// <summary><c>pinGlyph</c>: 🔥 for any <c>danger</c> event, ❗ for other events, null for none or no list.</summary>
    public static string? PinGlyph(IReadOnlyCollection<string?>? categories)
        => categories is null || categories.Count == 0 ? null : categories.Any(c => c == "danger") ? Danger : Notice;

    /// <summary>The wanted pins: location id → glyph, for the locations with events that are known places.</summary>
    public static Dictionary<string, string> Wanted(IEnumerable<KeyValuePair<string, IReadOnlyCollection<string?>>> eventsByLocation,
                                                    Func<string, bool> isPlace)
    {
        var wanted = new Dictionary<string, string>();
        foreach (var (id, categories) in eventsByLocation)
        {
            if (PinGlyph(categories) is not { } glyph || !isPlace(id)) continue;
            wanted[id] = glyph;
        }
        return wanted;
    }

    /// <summary>
    /// One poll's change (main.ts <c>updatePins</c>): a pin goes when it is no longer wanted OR its glyph differs
    /// from the wanted one (<c>wanted.get(id) !== pin.userData.glyph</c>); a wanted id without a pin (after that)
    /// comes. Every wanted id is then placed again by the caller.
    /// </summary>
    public static (List<string> Remove, List<KeyValuePair<string, string>> Add) Diff(IReadOnlyDictionary<string, string> existing,
                                                                                    IReadOnlyDictionary<string, string> wanted)
    {
        var remove = existing.Where(kv => !wanted.TryGetValue(kv.Key, out var g) || g != kv.Value)
                             .Select(kv => kv.Key).ToList();
        var add = wanted.Where(kv => !existing.ContainsKey(kv.Key) || remove.Contains(kv.Key)).ToList();
        return (remove, add);
    }

    /// <summary><c>pinY</c>: the place's ground datum (<c>tile.center.y</c>) + the place's height + 3.5.</summary>
    public static double PinY(double groundY, double placeHeight) => groundY + placeHeight + LiftM;

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
