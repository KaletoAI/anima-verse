using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;

namespace AnimaNative.Scene;

/// <summary>What the glyph rule reads of a place entry (<c>PlaceEntry</c>: slots in world metres, room, flags).</summary>
public sealed record PlaceEntryView(IReadOnlyList<Vec3> Slots, string RoomId, bool Fixed, bool HasAnchor, bool Diorama);

/// <summary>One offered place of <c>GET /play/places</c>.</summary>
public sealed record PlaceOffer(string Id, string Group, double Free, IReadOnlyList<int> FreeSlots);

/// <summary>One ring to draw.</summary>
public readonly record struct GlyphRow(string PlaceId, int Colour, Vec3 Position);

/// <summary>Renderer-independent ring dimensions and material settings.</summary>
public readonly record struct GlyphParams(int Colour, double InnerRadius, double OuterRadius, int Segments, double Lift,
                                          int RenderOrder, double RotationX, double Opacity, bool Transparent,
                                          bool DepthTest, bool DepthWrite, int Side);

/// <summary>
/// The place slots and their glyph rings — <c>slotFor</c> (client3d/src/scene/placeSlot.ts) and
/// <c>glyphRows</c>/<c>glyphParameters</c> (client3d/src/scene/placeGlyphs.ts), checked against
/// shared/test-vectors/scene_models.json [S]/[Y].
/// </summary>
public static class PlaceSlots
{
    public const int ColourSeat = 0xf2cd6e, ColourLie = 0x8fb3ff, ColourGround = 0x9fd48a, ColourStand = 0xd9d0bd;

    /// <summary>Geometry-only join. Only Core's exact placement provenance selects semantic offers.</summary>
    public static List<JsonElement> PropActionsFor(PlaceEntry entry, IEnumerable<JsonElement> offers)
        => entry.Fixed ? offers.Where(o => o.TryGetProperty("target", out var target)
            && World.Json.Str(target, "room_id") == entry.RoomId
            && World.Json.Str(target, "placement_id") == entry.PlacementId
            && World.Json.Str(target, "variant_uid") == entry.VariantUid).ToList() : new();
    private const int ColourUnknown = 0x9a9a9a;
    private const double RingInnerM = 0.25, RingOuterM = 0.32, RingLiftM = 0.03;
    private const int RingRenderOrder = 20;

    private static int GlyphColour(string group) => group switch
    {
        "seat" => ColourSeat, "lie" => ColourLie, "ground" => ColourGround, "stand" => ColourStand, _ => ColourUnknown,
    };

    /// <summary>
    /// <c>slotFor</c>: a numbered slot (out of range = slot 0), or the mean of all slots for a pair
    /// (<paramref name="slot"/> null = <c>'pair'</c>); null when there are no slots.
    /// </summary>
    public static Vec3? SlotFor(IReadOnlyList<Vec3> slots, int? slot)
    {
        if (slots.Count == 0) return null;
        if (slot is not { } s)
        {
            double x = slots[0].X, y = slots[0].Y, z = slots[0].Z;
            for (int i = 1; i < slots.Count; i++) { x += slots[i].X; y += slots[i].Y; z += slots[i].Z; }
            double k = 1.0 / slots.Count;
            return new Vec3(x * k, y * k, z * k);
        }
        return slots[s >= 0 && s < slots.Count ? s : 0];
    }

    public static GlyphParams GlyphParameters(string group)
        => new(GlyphColour(group), RingInnerM, RingOuterM, 32, RingLiftM, RingRenderOrder, -Math.PI / 2, 0.85, true, false, false, 2);

    /// <summary>
    /// <c>glyphRows</c>: one ring per FREE slot of every offered place, skipping the avatar's own place, a place on
    /// a prop with an anchor (its mesh is the target) and a diorama place whose room's diorama is mounted.
    /// </summary>
    public static List<GlyphRow> GlyphRows(IReadOnlyDictionary<string, PlaceEntryView>? entries, IReadOnlyList<PlaceOffer> offers,
                                           string skipPlaceId = "", IReadOnlySet<string>? dioramaRooms = null)
    {
        var rows = new List<GlyphRow>();
        if (entries is null) return rows;
        foreach (var offer in offers)
        {
            if (offer.Id == skipPlaceId || offer.Free <= 0) continue;
            if (!entries.TryGetValue(offer.Id, out var entry) || (entry.Fixed && entry.HasAnchor)
                || (entry.Diorama && dioramaRooms is not null && dioramaRooms.Contains(entry.RoomId))) continue;
            foreach (var i in offer.FreeSlots)
                if (i >= 0 && i < entry.Slots.Count)
                {
                    var p = entry.Slots[i];
                    rows.Add(new GlyphRow(offer.Id, GlyphColour(offer.Group), new Vec3(p.X, p.Y + RingLiftM, p.Z)));
                }
        }
        return rows;
    }
}
