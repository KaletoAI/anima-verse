using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/scene_models.json against the model-side ports (hand derivations and the JSON
/// wrapper conventions: client3d/scripts/smoke_scene_models.mjs).
///
/// <code>
///   TS fn                          C#                                    TS source
///   pickModelVariant               ModelVariants.PickModelVariant        scene-render types.ts
///   variantMatchesPlain            PickModelVariant == PickVariant        (smoke wrapper)
///   variantContained               PickModelVariant != variants.low       (smoke wrapper)
///   variantScatter / variantCounts PickModelVariant per index             (smoke wrappers)
///   leafPivot                      LeafPivot.Compute                     scene-render leafPivot.ts
///   storeyGroundLift               StoreyGround.Lift                     scene-render storeyGround.ts
///   storeyGroundRelift             StoreyGround.Relift
///   tileDatumStep                  StoreyGround.TileDatumStep            sampler n → () => n, null → none
///   markerLiftPoint                StoreyGround.MarkerLiftPoint          client3d game/placement.ts
///   markerLiftPointInvalidAnchor   MarkerLiftPoint(at, (NaN, 2))          (smoke wrapper)
///   slotFor                        PlaceSlots.SlotFor                    client3d scene/placeSlot.ts; 'pair' → null
///   buildGlyphs                    PlaceSlots.GlyphRows                  client3d scene/placeGlyphs.ts
///   glyphParameters                PlaceSlots.GlyphParameters
///   surfaceHeightAt                SurfaceHeight.At                      scene-render surface.ts
///   highestSurfaceAt               SurfaceHeight.Highest
///   plateLook/wallLook/extraLook   MaterialLooks.*                       client3d scene/materialLooks.ts
///   placeholderLook                MaterialLooks.PlaceholderLook          (payload piece + style → ScenePayload)
///   recipeHex                      MaterialLooks.RecipeHex
///   neutralizeLook                 MaterialLooks.NeutralizeLook
///   surfaceFinish                  MaterialLooks.SurfaceFinish           scene-render materials.ts
///   cutPlaneFor                    DepthCutMath.CutPlane                 scene-render depthCutMath.ts (cutPlaneData)
///   clipKeepsPoint                 ClipMath.ClipKeepsPoint               scene-render clipMath.ts
///   cutoutDiscardsPoint            ClipMath.CutoutDiscardsPoint
///   cutoutPadding                  ClipMath.CutoutPadding                non-number declared → null
/// </code>
/// </summary>
public class SceneModelsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scene_models"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pickModelVariant"] = a => ModelVariants.PickModelVariant(Spec(Arity(a, 2, 2)[0]), Str(a[1])),
        ["variantMatchesPlain"] = a =>
        {
            var s = Spec(Arity(a, 2, 2)[0]);
            return ModelVariants.PickModelVariant(s, Str(a[1])) == ModelVariants.PickVariant(s.Variants, Str(a[1]));
        },
        ["variantContained"] = a =>
        {
            var s = Spec(Arity(a, 2, 2)[0]);
            return ModelVariants.PickModelVariant(s, Str(a[1])) != s.Variants.GetValueOrDefault("low");
        },
        ["variantScatter"] = a =>
        {
            var s = Spec(Arity(a, 2, 2)[0]);
            return new JsonArray(VectorCompare.NumList(a[1]).Select(v => (JsonNode?)ModelVariants.PickModelVariant(s with { Variant = v }, "full")).ToArray());
        },
        ["variantCounts"] = a =>
        {
            var s = Spec(Arity(a, 2, 2)[0]);
            var urls = VectorCompare.NumList(a[1]).Select(v => ModelVariants.PickModelVariant(s with { Variant = v }, "full")).ToList();
            return Nums(new[] { 0, 1, 2 }.Select(v => (double)urls.Count(u => u == ModelVariants.PickModelVariant(s with { Variant = v }, "full"))));
        },
        ["leafPivot"] = a =>
        {
            Arity(a, 1, 2);
            var fix = Arg(a, 1) is { } f ? new FixDeg(Opt(Key(f, "x")), Opt(Key(f, "y")), Opt(Key(f, "z"))) : (FixDeg?)null;
            var p = LeafPivot.Compute(V3(Key(a[0], "min")), V3(Key(a[0], "max")), fix);
            return new JsonObject { ["point"] = Arr(p.Point), ["axis"] = Arr(p.Axis) };
        },
        ["storeyGroundLift"] = a => StoreyGround.Lift(VectorCompare.NumOrNull(Arity(a, 5, 5)[0]), Num(a[1]), Num(a[2]), Num(a[3]), Sampler(a[4])),
        ["storeyGroundRelift"] = a =>
        {
            var s = StoreyGround.Relift(Num(Arity(a, 6, 6)[0]), VectorCompare.NumOrNull(a[1]), Num(a[2]), Num(a[3]), Num(a[4]), Sampler(a[5]));
            return new JsonObject { ["lift"] = s.Lift, ["delta"] = s.Delta };
        },
        ["tileDatumStep"] = a =>
        {
            var s = StoreyGround.TileDatumStep(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Sampler(a[3]));
            return new JsonObject { ["datum"] = s.Datum, ["delta"] = s.Delta };
        },
        ["markerLiftPoint"] = a =>
        {
            Arity(a, 1, 2);
            var p = StoreyGround.MarkerLiftPoint(XZ(a[0]), Arg(a, 1) is { } an ? XZ(an) : null);
            return new JsonObject { ["x"] = p.X, ["z"] = p.Z };
        },
        ["markerLiftPointInvalidAnchor"] = a =>
        {
            var p = StoreyGround.MarkerLiftPoint(XZ(Arity(a, 1, 1)[0]), new P2(double.NaN, 2));
            return new JsonObject { ["x"] = p.X, ["z"] = p.Z };
        },
        ["slotFor"] = a =>
        {
            var slots = ((JsonArray)Arity(a, 2, 2)[0]!).Select(V3).ToList();
            int? slot = a[1] is JsonValue v && v.TryGetValue(out JsonElement e) && e.ValueKind == JsonValueKind.String
                ? (Str(a[1]) == "pair" ? null : throw new ArgumentException("slot string must be 'pair'"))
                : ScatterVectorAdapters.Int(a[1]);
            return PlaceSlots.SlotFor(slots, slot) is { } p ? Arr(p) : null;
        },
        ["buildGlyphs"] = a =>
        {
            Arity(a, 2, 4);
            Dictionary<string, PlaceEntryView>? entries = a[0] is JsonObject eo
                ? eo.ToDictionary(kv => kv.Key, kv => new PlaceEntryView(
                    ((JsonArray)Key(kv.Value, "slots")!).Select(V3).ToList(), Str(Key(kv.Value, "roomId")),
                    Key(kv.Value, "fixed") is { } fx && Bool(fx), Key(kv.Value, "anchor") is not null,
                    Key(kv.Value, "diorama") is { } d && Bool(d)))
                : null;
            var offers = ((JsonArray)a[1]!).Select(o => new PlaceOffer(Str(Key(o, "id")), Str(Key(o, "group")), Num(Key(o, "free")),
                ((JsonArray)Key(o, "free_slots")!).Select(ScatterVectorAdapters.Int).ToList())).ToList();
            var rows = PlaceSlots.GlyphRows(entries, offers, Arg(a, 2) is { } sk ? Str(sk) : "",
                                            Arg(a, 3) is JsonArray rooms ? rooms.Select(Str).ToHashSet() : new HashSet<string>());
            return new JsonArray(rows.Select(r => (JsonNode?)new JsonObject
            {
                ["placeId"] = r.PlaceId, ["colour"] = r.Colour, ["position"] = Obj(r.Position),
            }).ToArray());
        },
        ["glyphParameters"] = a =>
        {
            var g = PlaceSlots.GlyphParameters(Str(Arity(a, 1, 1)[0]));
            return new JsonObject
            {
                ["colour"] = g.Colour, ["innerRadius"] = g.InnerRadius, ["outerRadius"] = g.OuterRadius, ["segments"] = g.Segments,
                ["lift"] = g.Lift, ["renderOrder"] = g.RenderOrder, ["rotationX"] = g.RotationX, ["opacity"] = g.Opacity,
                ["transparent"] = g.Transparent, ["depthTest"] = g.DepthTest, ["depthWrite"] = g.DepthWrite, ["side"] = g.Side,
            };
        },
        ["surfaceHeightAt"] = a =>
        {
            Arity(a, 4, 5);
            return SurfaceHeight.At(Surface(a[0]), Placement(a[1]), Num(a[2]), Num(a[3]), Arg(a, 4) is { } l ? Num(l) : 0);
        },
        ["highestSurfaceAt"] = a =>
        {
            var list = ((JsonArray)Arity(a, 3, 3)[0]!).Select(p => new PlacedSurface(Str(Key(p, "id")), Placement(Key(p, "spec")),
                Surface(Key(p, "surface")), Num(Key(p, "lift")), Num(Key(p, "level")), Str(Key(p, "roomId")))).ToList();
            return SurfaceHeight.Highest(list, Num(a[1]), Num(a[2]));
        },
        ["plateLook"] = a =>
        {
            var s = SceneOf("plates", Arity(a, 2, 2)[0], a[1]);
            return Look(MaterialLooks.PlateLook(s.Plates.Single(), s));
        },
        ["wallLook"] = a =>
        {
            var s = SceneOf("walls", Arity(a, 2, 2)[0], a[1]);
            return Look(MaterialLooks.WallLook(s.Walls.Single(), s));
        },
        ["extraLook"] = a =>
        {
            var s = SceneOf("extras", Arity(a, 2, 2)[0], a[1]);
            return Look(MaterialLooks.ExtraLook(s.Extras.Single(), s));
        },
        ["placeholderLook"] = a =>
        {
            Arity(a, 0, 0);
            return Look(MaterialLooks.PlaceholderLook());
        },
        ["recipeHex"] = a => MaterialLooks.RecipeHex(StrOrNull(Arity(a, 1, 1)[0])),
        ["neutralizeLook"] = a =>
        {
            var n = MaterialLooks.NeutralizeLook(Num(Arity(a, 3, 3)[0]), Bool(a[1]), Bool(a[2]));
            var o = new JsonObject { ["metalness"] = n.Metalness };
            if (n.EnvMapIntensity is { } e) o["envMapIntensity"] = e;
            return o;
        },
        ["surfaceFinish"] = a =>
        {
            var f = MaterialLooks.SurfaceFinish(Element(Arity(a, 1, 1)[0]));
            var o = new JsonObject { ["roughness"] = f.Roughness, ["metalness"] = f.Metalness };
            if (f.EmissiveIntensity is { } e) o["emissiveIntensity"] = e;
            return o;
        },
        ["cutPlaneFor"] = a =>
        {
            Arity(a, 1, 2);
            var cut = a[0];
            var plane = cut is null ? null : DepthCutMath.CutPlane(Key(cut, "normal") is { } n ? V3(n) : null,
                Num(Key(cut, "constant")), Arg(a, 1) is { } m ? VectorCompare.NumList(m).ToArray() : null);
            return plane is { } p ? new JsonObject { ["normal"] = Arr(p.Normal), ["constant"] = p.Constant } : null;
        },
        ["clipKeepsPoint"] = a => ClipMath.ClipKeepsPoint(Pt(Arity(a, 2, 2)[0]), Ring(a[1])),
        ["cutoutDiscardsPoint"] = a =>
        {
            Arity(a, 2, 4);
            return ClipMath.CutoutDiscardsPoint(Pt(a[0]), ((JsonArray)a[1]!).Select(r => (IReadOnlyList<P2>)Ring(r)).ToList(),
                Arg(a, 2) is { } p ? Num(p) : 0, Arg(a, 3) is not { } en || Bool(en));
        },
        ["cutoutPadding"] = a =>
        {
            Arity(a, 2, 2);
            double? declared = VectorCompare.TryNum(a[0], out var d) ? d : null;
            return ClipMath.CutoutPadding(declared, Num(a[1]));
        },
    };

    private static double? Opt(JsonNode? n) => n is null ? null : Num(n);

    /// <summary>The smoke's <c>sample(n)</c>: a number becomes the constant sampler, null/absent none.</summary>
    private static Func<double, double, double>? Sampler(JsonNode? n) => n is null ? null : (_, _) => Num(n);

    private static SceneSurface Surface(JsonNode? s) => new(
        Num(Key(s, "step")), Pt(Key(s, "origin")), ScatterVectorAdapters.Int(Key(s, "cols")), ScatterVectorAdapters.Int(Key(s, "rows")),
        ((JsonArray)Key(s, "values")!).Select(v => v is null ? (double?)null : Num(v)).ToArray(),
        V3(Key(s, "box_min")), V3(Key(s, "box_max")), V3(Key(s, "extent_snapped")));

    private static SurfacePlacement Placement(JsonNode? p) => new(
        Pt(Key(p, "anchor")), Opt(Key(p, "yaw_deg")) ?? double.NaN, Opt(Key(p, "bottom_y")) ?? double.NaN,
        Opt(Key(p, "max_m")) ?? double.NaN, Str(Key(p, "measure")));

    private static JsonObject Look(RecipeLookParams l) => new()
    {
        ["color"] = l.Color, ["transparent"] = l.Transparent, ["opacity"] = l.Opacity, ["side"] = l.Side,
        ["roughness"] = l.Roughness, ["metalness"] = l.Metalness,
    };

    public static TheoryData<string> Cases => VectorFile.Labels("scene_models");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
