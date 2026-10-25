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
    /// <summary>Not in the view: indoor specs of a closed location (they hang in the invisible interior group).</summary>
    public int Interior;
    /// <summary>Indoor specs of the open location in a room of another storey.</summary>
    public int Storey;
    /// <summary>A shell building of the OPEN location: the crossfade takes it to opacity 0 (roofParts hidden).</summary>
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
/// Not ported (counted nowhere, view-only): picture/glass slot materials (<c>fillSlots</c>), the room clip and
/// the depth cut (<c>clip_outline</c>, <c>cut_plane</c>), door swinging, prop lights.
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
                                                 Node3D parent, double lift, ModelStats stats, RecipeMaterials? phMaterials)
    {
        var url = ModelVariants.PickModelVariant(spec, tier);
        ModelCache.Template? template = url.Length > 0 ? await cache.GetAsync(url) : null;
        if (template is null)
        {
            if (spec.PlaceholderDims is { } d && phMaterials is not null)
            {
                var ph = Placeholder(d, phMaterials);
                ph.Position = new Vector3((float)spec.AnchorX, (float)(spec.BottomY + lift), (float)spec.AnchorZ);
                ph.Rotation = new Vector3(0, (float)(spec.YawDeg * Math.PI / 180.0), 0);
                parent.AddChild(ph);
                stats.Placeholders++;
                return ph;
            }
            stats.Missing++;
            return null;
        }
        var placed = ModelPlacement.Place(ModelCache.Instance(template), spec);
        if (lift != 0) placed.Position += new Vector3(0, (float)lift, 0);
        parent.AddChild(placed);
        stats.Placed[kind]++;
        stats.Vertices += template.Counts.Vertices;
        stats.Indices += template.Counts.Indices;
        if (template.Compressed) stats.Compressed++;
        if (tier == "low") stats.Low++;
        else stats.Full++;
        return placed;
    }

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

    /// <summary>
    /// The cutouts of an open plan-hull / ground model (<c>applyCutouts</c>, § B1). THE BROWSER DISCARDS PER FRAGMENT
    /// in a shader (packages/scene-render/src/cutouts.ts), so a per-triangle cut is NOT what the browser decides and
    /// this stays an APPROXIMATION until the fragment twin lands (Task 17): every triangle whose CENTROID the
    /// vector-checked fragment predicate <see cref="ClipMath.CutoutDiscardsPoint"/> discards (same polygon filter and
    /// limits, same half-open parity) is dropped from a per-placement copy of the mesh. Large triangles at a cutout's
    /// edge therefore come out differently; GLB padding (<c>interior_cutout_padding_m</c>) is not read natively, so the
    /// padding is 0. Returns the triangles removed.
    /// </summary>
    public static int ApplyCutouts(Node3D placed, (double X, double Z)[][] cutouts)
    {
        var polys = cutouts.Select(c => (IReadOnlyList<P2>)c.Select(p => new P2(p.X, p.Z)).ToList()).ToList();
        if (ClipMath.CutoutPolygons(polys).Count == 0) return 0;
        int removed = 0;
        foreach (var mi in Walk(placed).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is not ArrayMesh mesh) continue;
            // From the mesh's frame into the location frame (the cutouts' frame): the placed chain up to `placed`
            // plus `placed` itself (it hangs directly in the location group).
            var xf = placed.Transform * RelativeTo(mi, placed);
            var cut = new ArrayMesh();
            for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            {
                var arrays = mesh.SurfaceGetArrays(s);
                var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
                var idx = arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
                if (idx.Length == 0) idx = Enumerable.Range(0, verts.Length).ToArray();
                var keep = new List<int>(idx.Length);
                for (int i = 0; i + 2 < idx.Length; i += 3)
                {
                    var c = xf * ((verts[idx[i]] + verts[idx[i + 1]] + verts[idx[i + 2]]) / 3f);
                    if (ClipMath.CutoutDiscardsPoint(new P2(c.X, c.Z), polys)) { removed++; continue; }
                    keep.Add(idx[i]); keep.Add(idx[i + 1]); keep.Add(idx[i + 2]);
                }
                if (keep.Count == 0) continue;
                arrays[(int)Mesh.ArrayType.Index] = keep.ToArray();
                cut.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
                cut.SurfaceSetMaterial(cut.GetSurfaceCount() - 1, mi.GetActiveMaterial(s) ?? mesh.SurfaceGetMaterial(s));
            }
            mi.Mesh = cut;
        }
        return removed;
    }

    private static Transform3D RelativeTo(Node3D node, Node3D ancestor)
    {
        var xf = Transform3D.Identity;
        for (Node? n = node; n is not null && n != ancestor; n = n.GetParent())
            if (n is Node3D n3) xf = n3.Transform * xf;
        return xf;
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}
