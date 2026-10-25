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

namespace AnimaNative.Tests;

/// <summary>
/// Shape adapters between the TS shapes of the five scene vector files (scene_place, scene_primitives,
/// scene_verify, scene_view, scene_models) and the C# types of <c>AnimaNative.Scene</c>. They translate
/// shapes only and never reinterpret a value.
///
/// Payload pieces (a model spec, a plate, a wall, an extra, a style) are not mapped field by field: they
/// go through the native payload parser (<see cref="ScenePayload.Parse"/> / <see cref="ScenePayload.ParseModel"/>),
/// so every vector case also proves that the parser hands the port what the TS function reads.
/// </summary>
internal static class SceneVectorAdapters
{
    // ---- JSON plumbing ------------------------------------------------------------------------

    /// <summary>A JSON node as a parsed <see cref="JsonElement"/> (the parser's input type).</summary>
    public static JsonElement Element(JsonNode? node)
        => JsonDocument.Parse(node?.ToJsonString() ?? "null").RootElement.Clone();

    /// <summary>A model spec through the native parser.</summary>
    public static SceneModelSpec Spec(JsonNode? node) => ScenePayload.ParseModel(Element(node));

    /// <summary>A one-piece scene through the native parser: <c>{"&lt;key&gt;": [piece], "style": style}</c>.</summary>
    public static ScenePayload SceneOf(string key, JsonNode? piece, JsonNode? style = null)
    {
        var o = new JsonObject { [key] = new JsonArray(piece?.DeepClone()) };
        if (style is not null) o["style"] = style.DeepClone();
        return ScenePayload.Parse(Element(o));
    }

    public static bool Bool(JsonNode? node)
        => node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? el.ValueKind == JsonValueKind.True
            : throw new ArgumentException($"expected a boolean, got {VectorCompare.Show(node)}");

    public static double Num(JsonNode? node) => VectorCompare.Num(node);

    /// <summary>A key of an object argument, null when absent (JS <c>undefined</c>).</summary>
    public static JsonNode? Key(JsonNode? obj, string key)
        => obj is JsonObject o && o.TryGetPropertyValue(key, out var v) ? v : null;

    // ---- shapes -------------------------------------------------------------------------------

    /// <summary><c>[x, y, z]</c> → <see cref="Vec3"/>.</summary>
    public static Vec3 V3(JsonNode? node)
        => node is JsonArray a && a.Count == 3
            ? new Vec3(Num(a[0]), Num(a[1]), Num(a[2]))
            : throw new ArgumentException($"expected [x, y, z], got {VectorCompare.Show(node)}");

    /// <summary><c>{x, y, z}</c> → <see cref="Vec3"/>.</summary>
    public static Vec3 XYZ(JsonNode? node)
        => new(Num(Key(node, "x")), Num(Key(node, "y")), Num(Key(node, "z")));

    /// <summary><c>{x, z}</c> → <see cref="P2"/>.</summary>
    public static P2 XZ(JsonNode? node) => new(Num(Key(node, "x")), Num(Key(node, "z")));

    /// <summary><c>[x, z]</c> → <see cref="P2"/>.</summary>
    public static P2 Pt(JsonNode? node) => ScatterVectorAdapters.Point(node);

    public static JsonArray Arr(Vec3 v) => new(v.X, v.Y, v.Z);

    public static JsonObject Obj(Vec3 v) => new() { ["x"] = v.X, ["y"] = v.Y, ["z"] = v.Z };

    public static JsonArray RingJson(IEnumerable<P2> ring)
        => new(ring.Select(p => (JsonNode?)new JsonArray(p.X, p.Z)).ToArray());

    public static JsonArray Nums(IEnumerable<double> values) => new(values.Select(v => (JsonNode?)v).ToArray());
}
