using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/slot_materials.json against <see cref="SlotFill"/> (hand derivations: scripts/smoke_slot_materials.mjs;
/// TS source packages/scene-render/src/slotMaterials.ts). The slots map goes through the payload parser
/// (<see cref="ScenePayload.ParseModel"/> of <c>{"slots": …}</c>), the reader the client runs on a model spec.
/// </summary>
public class SlotMaterialsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("slot_materials"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["slotFill"] = a =>
        {
            Arity(a, 2, 2);
            var slots = a[1] is null ? null : Spec(new JsonObject { ["slots"] = a[1]!.DeepClone() }).Slots;
            return SlotFill.Fill(Str(a[0]), slots) is { } f
                ? new JsonObject { ["slot"] = f.Slot, ["kind"] = f.Kind, ["image"] = f.Image } : null;
        },
        ["glassPreset"] = a =>
        {
            Arity(a, 0, 0);
            return new JsonObject
            {
                ["opacity"] = SlotFill.GlassOpacity, ["roughness"] = SlotFill.GlassRoughness,
                ["metalness"] = SlotFill.GlassMetalness, ["transmission"] = SlotFill.GlassTransmission,
            };
        },
        ["materialPresets"] = a => { Arity(a, 0, 0); return new JsonArray(SlotFill.MaterialPresets.Select(p => (JsonNode?)p).ToArray()); },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("slot_materials");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
