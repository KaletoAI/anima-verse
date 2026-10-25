using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>What one placement's texture slots put on its meshes (the browser's <c>rec.slotMats</c>).</summary>
public sealed class SlotHandle
{
    public sealed record Entry(MeshInstance3D Mesh, int Surface, string Slot, string Kind, string Image);

    public List<Entry> Entries { get; } = new();
    public List<MirrorPanes.Pane> Mirrors { get; } = new();
    /// <summary>The picture loads of this placement (await them to see the textures land).</summary>
    public List<Task> Loads { get; } = new();
    public int Pictures => Entries.Count(e => e.Kind == "image");
    public int Glass => Entries.Count(e => e.Kind == "glass");
    /// <summary>Pictures that arrived and were written / that failed and left the surface as modelled.</summary>
    public int Landed, Failed;
}

/// <summary>
/// The texture slots of a placed prop (§ B2 v5), the native twin of packages/scene-render <c>applySlotMaterials</c>:
/// the DECISION is <see cref="SlotFill.Fill"/> (vector-checked); this class writes it — always as a per-placement
/// surface override, never onto the cached template's material (the hall's poster must not hang in the kitchen).
///
///   • picture: the image loads asynchronously (not cached by URL, like the browser — a texture belongs to its
///     placement); on arrival the surface's CURRENT material takes it with a white tint: a StandardMaterial3D is
///     duplicated for this placement, a cut clone (CutMaterials ShaderMaterial, if the cut ran first) gets the
///     parameters written. A picture that never arrives leaves the surface exactly as modelled.
///   • glass: GLASS_PRESET — alpha 0.3, roughness 0.06, metallic 0, two-sided (StandardMaterial3D has no
///     transmission field; the browser writes transmission only onto a physical material either).
///   • mirror: <see cref="MirrorPanes.Attach"/>.
/// Runs BEFORE the cuts (sceneRecipe.ts <c>fillSlots</c> first): CutMaterials reads the override and cuts the slot
/// material, so the picture / glass / mirror ride into the cut clones.
/// </summary>
public static class SlotMaterials
{
    public static SlotHandle? Apply(Node3D placed, SceneModelSpec spec, Func<string, Task<ImageTexture?>> loadPicture,
                                    MirrorPanes? mirrors, Action<string> log)
    {
        if (spec.Slots.Count == 0 || SceneModels.IsPlaceholder(placed)) return null;
        var handle = new SlotHandle();
        var pictures = new Dictionary<string, List<SlotHandle.Entry>>();
        foreach (var mi in Walk(placed).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is null) continue;
            for (int s = 0; s < mi.Mesh.GetSurfaceCount(); s++)
            {
                var src = mi.GetSurfaceOverrideMaterial(s) ?? mi.Mesh.SurfaceGetMaterial(s);
                if (src is null) continue;
                if (SlotFill.Fill(src.ResourceName, spec.Slots) is not { } fill) continue;
                var entry = new SlotHandle.Entry(mi, s, fill.Slot, fill.Kind, fill.Image);
                switch (fill.Kind)
                {
                    case "glass":
                        if (src is not StandardMaterial3D std) { log($"slot \"{fill.Slot}\": glass needs a standard material, got {src.GetClass()}"); continue; }
                        mi.SetSurfaceOverrideMaterial(s, Glass(std));
                        handle.Entries.Add(entry);
                        break;
                    case "mirror":
                        if (mirrors?.Attach(mi, s, fill.Slot, log) is { } pane)
                        {
                            handle.Mirrors.Add(pane);
                            handle.Entries.Add(entry);
                        }
                        break;
                    default:
                        if (!pictures.TryGetValue(fill.Image, out var list)) pictures[fill.Image] = list = new List<SlotHandle.Entry>();
                        list.Add(entry);
                        handle.Entries.Add(entry);
                        break;
                }
            }
        }
        foreach (var (url, entries) in pictures) handle.Loads.Add(LoadPicture(url, entries, loadPicture, handle, log));
        return handle.Entries.Count > 0 ? handle : null;
    }

    /// <summary>The glass clone of a source material (GLASS_PRESET on this placement's own copy).</summary>
    public static StandardMaterial3D Glass(StandardMaterial3D src)
    {
        var m = (StandardMaterial3D)src.Duplicate();
        m.Transparency = BaseMaterial3D.TransparencyEnum.Alpha;
        var c = m.AlbedoColor;
        m.AlbedoColor = new Color(c.R, c.G, c.B, (float)SlotFill.GlassOpacity);
        m.Roughness = (float)SlotFill.GlassRoughness;
        m.Metallic = (float)SlotFill.GlassMetalness;
        m.CullMode = BaseMaterial3D.CullModeEnum.Disabled;
        return m;
    }

    private static async Task LoadPicture(string url, List<SlotHandle.Entry> entries, Func<string, Task<ImageTexture?>> load,
                                          SlotHandle handle, Action<string> log)
    {
        ImageTexture? tex;
        try { tex = await load(url); }
        catch (Exception e) { tex = null; log($"slot picture {url}: {e.Message} — the surface stays as modelled"); }
        if (tex is null) { handle.Failed++; return; }
        foreach (var e in entries)
            if (GodotObject.IsInstanceValid(e.Mesh)) WritePicture(e.Mesh, e.Surface, tex);
        handle.Landed++;
    }

    /// <summary>
    /// Hang <paramref name="tex"/> on what the surface draws now: a cut clone takes the parameters (its generated code
    /// always samples <c>texture_albedo</c>), a standard material is duplicated for this placement (or written if it
    /// already is this placement's own copy). The tint goes white, its alpha stays.
    /// </summary>
    public static void WritePicture(MeshInstance3D mesh, int surface, Texture2D tex)
    {
        var over = mesh.GetSurfaceOverrideMaterial(surface);
        switch (over)
        {
            case ShaderMaterial sm:
                var a = sm.GetShaderParameter("albedo");
                float alpha = a.VariantType == Variant.Type.Color ? a.AsColor().A : 1f;
                sm.SetShaderParameter("texture_albedo", tex);
                sm.SetShaderParameter("albedo_texture_size", new Vector2I(tex.GetWidth(), tex.GetHeight()));
                sm.SetShaderParameter("albedo", new Color(1, 1, 1, alpha));
                break;
            case StandardMaterial3D own when own.HasMeta(OwnMeta):
                own.AlbedoTexture = tex;
                own.AlbedoColor = new Color(1, 1, 1, own.AlbedoColor.A);
                break;
            default:
                if ((over ?? mesh.Mesh?.SurfaceGetMaterial(surface)) is not StandardMaterial3D src) return;
                var m = (StandardMaterial3D)src.Duplicate();
                m.SetMeta(OwnMeta, true);
                m.AlbedoTexture = tex;
                m.AlbedoColor = new Color(1, 1, 1, m.AlbedoColor.A);
                mesh.SetSurfaceOverrideMaterial(surface, m);
                break;
        }
    }

    /// <summary>Marks a picture clone this placement owns (written again instead of duplicated).</summary>
    private const string OwnMeta = "anima_slot_clone";

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}
