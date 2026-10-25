using System;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// Loads the BUILDING model of a location and places it.
///
/// Where the numbers come from: the scene recipe's <c>models[]</c> entry with
/// <c>role: "building"</c>. The server composes it from
/// <c>/play/locations/{id}/model/meta</c> (§ A7) — the sidecar <c>rotation</c>
/// becomes <c>fix_euler</c>, <c>offset_x/z</c> move the <c>anchor</c> off the
/// boundary centre, <c>offset_y</c>/<c>walk_y</c> go into <c>bottom_y</c>
/// (app/core/scene_recipe.py, building spec) — and its <c>variants</c> name
/// <c>/play/locations/{id}/model</c>. That is exactly what the browser client
/// places (<c>mountShell</c> → <c>placeModelSpec</c>); reading the meta again
/// here and applying its offsets on top would apply them twice.
///
/// Tier: always <c>full</c> in S1a (the browser swaps to <c>low</c> by camera
/// distance; that is view state for a later task).
/// </summary>
public static class BuildingLoader
{
    public const string Tier = "full";

    public sealed record Result(Node3D Placed, GlbCounts Counts, bool WasCompressed, int Bytes);

    public static async Task<Result?> LoadAsync(IWorldSource source, SceneModelSpec spec)
    {
        var url = spec.PickUrl(Tier);
        if (url.Length == 0) return null;
        var bytes = await source.GetBytesAsync(url);
        bool compressed = GlbMeshoptDecoder.IsCompressed(bytes);
        // Decoding is pure C# + the native lib: keep it off the main thread.
        var plain = await Task.Run(() => GlbLoader.Prepare(bytes));
        var (root, counts) = GlbLoader.Import(plain, url);
        var placed = ModelPlacement.Place(root, spec);
        return new Result(placed, counts, compressed, bytes.Length);
    }
}
