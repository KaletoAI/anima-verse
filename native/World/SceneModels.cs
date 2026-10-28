using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Gltf;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>What the model specs (recipe <c>models[]</c> + world props) turned into, per kind.</summary>
public sealed class ModelStats
{
    public static readonly string[] Kinds = { "building", "room", "prop", "door", "window", "world" };
    public readonly Dictionary<string, int> Placed = Kinds.ToDictionary(k => k, _ => 0);
    /// <summary>Placed as the grey placeholder box (no URL or not loadable, <c>placeholder_dims</c> present).</summary>
    public int Placeholders;
    /// <summary>No mesh and no placeholder (the browser's <c>verify.skip</c>).</summary>
    public int Missing;
    /// <summary>Not mounted: indoor specs of a far-ring location (<c>mountDetail</c> runs for the near ring only).</summary>
    public int Interior;
    /// <summary>
    /// Indoor specs in a room of another storey than the one shown at the build (mounted all the same since Task 16 —
    /// counted in <see cref="Placed"/> / <see cref="Placeholders"/> / <see cref="Missing"/> too; their room group
    /// hides them until the switch shows their storey).
    /// </summary>
    public int Storey;
    /// <summary>A shell building of the OPEN location (mounted; the crossfade takes it to opacity 0, roofParts hidden).</summary>
    public int Faded;
    /// <summary>World props beyond the landmark cull (360 m from the camera, <c>worldPropLodCfg</c>).</summary>
    public int Culled;
    public int Vertices, Indices, Compressed;
    public int Full, Low;

    public int Total => Placed.Values.Sum();

    public string Summary()
        => $"models[{string.Join(" ", Kinds.Select(k => $"{k}={Placed[k]}"))} placeholders={Placeholders} missing={Missing} "
           + $"interior={Interior} storey={Storey} faded={Faded} culled={Culled} full={Full} low={Low}]";
}

/// <summary>
/// Places the model specs of a scene recipe (§ B1 <c>models[]</c>) and the world props (§ A9a) the way the
/// browser's <c>mountModels</c> / <c>worldProps.mount</c> do:
///
///   • the URL from <c>pickModelVariant(spec, tier)</c> (<see cref="ModelVariants.PickModelVariant"/>) (the model variant first, then the tier, missing tier →
///     the best existing one), loaded once per URL (<see cref="ModelCache"/>);
///   • <c>place()</c> (§ B2, <see cref="ModelPlacement"/> — <c>measure: "fit"</c> door/window models included);
///   • a spec without a loadable mesh but with <c>placeholder_dims</c> keeps its place as a grey box
///     (<c>buildPlaceholder</c>: origin at the bottom centre, yaw +rad), otherwise it is missing;
///   • the storey-0 terrain lift (§ A16.9 <c>reliftPlacement</c> / <c>storeyGroundLift</c>): a non-building
///     spec on level 0 moves by <c>ground(anchor) − datum</c>, the datum being the ground under the pin.
/// The room clip, the area cutouts and the depth cut ride on the placement afterwards (<see cref="CutMaterials"/>,
/// <see cref="WorldBuilder.CutPlacement"/>); the texture slots, door props and prop lights before and after them
/// (<see cref="SlotMaterials"/>, <see cref="DoorProps"/>, <see cref="PropLightPool"/>, WorldBuilder.Props.cs).
/// </summary>
public static class SceneModels
{
    /// <summary>The kind a spec is counted as.</summary>
    public static string KindOf(SceneModelSpec spec)
        => spec.Role == "building" ? "building"
         : spec.Role == "room" ? "room"
         : spec.Id.StartsWith("door:", StringComparison.Ordinal) ? "door"
         : spec.Id.StartsWith("window:", StringComparison.Ordinal) ? "window"
         : "prop";

    /// <summary>
    /// One placement in the location frame of <paramref name="parent"/> (null when nothing stands).
    /// <paramref name="lift"/> is the § A16.9 terrain lift already computed for it.
    /// </summary>
    public static async Task<Node3D?> PlaceAsync(ModelCache cache, SceneModelSpec spec, string tier, string kind,
                                                 Node3D parent, double lift, ModelStats stats, RecipeMaterials? phMaterials, Func<bool>? alive = null)
    {
        var url = ModelVariants.PickModelVariant(spec, tier);
        ModelCache.Template? template = url.Length > 0 ? await cache.GetAsync(url) : null;
        // Task 44: fetch may finish after a residency step was invalidated or its world was freed.
        if (alive is not null && !alive()) throw new OperationCanceledException("Residency placement invalidated");
        if (template is null)
        {
            if (spec.PlaceholderDims is { } d && phMaterials is not null)
            {
                var ph = Placeholder(d, phMaterials);
                ph.Position = new Vector3((float)spec.AnchorX, (float)(spec.BottomY + lift), (float)spec.AnchorZ);
                ph.Rotation = new Vector3(0, (float)(spec.YawDeg * Math.PI / 180.0), 0);
                // buildPlaceholder: receiveShadow only — three's castShadow default false (Task 26c).
                CastNone(ph);
                parent.AddChild(ph);
                stats.Placeholders++;
                return ph;
            }
            stats.Missing++;
            return null;
        }
        var placed = ModelPlacement.Place(ModelCache.Instance(template), spec);
        if (lift != 0) placed.Position += new Vector3(0, (float)lift, 0);
        if (kind != "building") CastNone(placed);
        parent.AddChild(placed);
        stats.Placed[kind]++;
        stats.Vertices += template.Counts.Vertices;
        stats.Indices += template.Counts.Indices;
        if (template.Compressed) stats.Compressed++;
        if (tier == "low") stats.Low++;
        else stats.Full++;
        return placed;
    }

    /// <summary>
    /// The browser's caster classes (Task 26c): only a location's BUILDING model casts by construction
    /// (<c>applySceneBuilding</c>: <c>castShadow = true</c>); recipe placements (props, doors, windows, rooms), world
    /// props (worldProps.ts) and stand-in boxes keep three's default <c>castShadow = false</c>. The crossfade then turns
    /// everything outside an interior to the shell's flag (<see cref="LocationFade"/>, tiles.ts <c>applyTileFade</c>).
    /// </summary>
    public static void CastNone(Node root)
    {
        if (root is GeometryInstance3D g) g.CastShadow = GeometryInstance3D.ShadowCastingSetting.Off;
        foreach (var c in root.GetChildren()) CastNone(c);
    }

    /// <summary>A placement that is the grey stand-in box, not a mesh (<see cref="Placeholder"/>).</summary>
    public static bool IsPlaceholder(Node3D node) => node.Name.ToString().StartsWith("Placeholder", StringComparison.Ordinal);

    /// <summary><c>buildPlaceholder</c>: the box of <see cref="PrimitiveMath.PlaceholderBox"/> (each side at least 1 cm), its origin at the bottom face's centre.</summary>
    public static Node3D Placeholder((double W, double D, double H) dims, RecipeMaterials materials)
    {
        var b = PrimitiveMath.PlaceholderBox(dims.W, dims.D, dims.H);
        var root = new Node3D { Name = "Placeholder" };
        root.AddChild(new MeshInstance3D
        {
            Name = "Box",
            Mesh = new BoxMesh { Size = ModelPlacement.ToGodot(b.Size), Material = materials.Get(RecipeMaterials.Placeholder) },
            Position = ModelPlacement.ToGodot(b.Offset),
        });
        return root;
    }
}
