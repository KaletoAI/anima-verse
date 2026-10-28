using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>Task 51: a visible mesh hit plus its owning connection; all boxes of one flight share the target.</summary>
public sealed record VerticalHit(LocationSlot Slot,VerticalTarget Target,MeshInstance3D Mesh);

/// <summary>
/// Task 51 / E7-T6: triangle picks over the mounted recipe extras, before ground/location picks. Recipe meshes
/// carry connection metadata so merged materials cannot make a whole house a stair target. Hover clones only
/// Material resources (Duplicate(false)); Shader resources remain shared. Ownership: this handle restores overrides
/// and disposes its clones on hover change, drop/remount, mode exit and Main teardown. No mounted nodes retained.
/// </summary>
public sealed class VerticalPicking(WorldBuilder world,Func<LocationSlot,IEnumerable<VerticalTarget>> usable) : IDisposable
{
    public const string KindMeta="vertical_kind", FlightMeta="vertical_flight";
    private VerticalHit? _hover;
    public bool HasHover => _hover is not null;
    private readonly List<(MeshInstance3D Mesh,int Surface,Material? Old,Material Clone)> _clones=new();
    private static IEnumerable<MeshInstance3D> Meshes(Node root)
    {
        if(root is MeshInstance3D mesh && mesh.HasMeta(KindMeta)) yield return mesh;
        foreach(var child in root.GetChildren()) foreach(var m in Meshes(child)) yield return m;
    }
    private static VerticalTarget Target(MeshInstance3D m) => new(m.GetMeta(KindMeta).AsString(),m.GetMeta(FlightMeta).AsInt32());
    public VerticalHit? Hit(Vec3 origin,Vec3 dir)
    {
        var o=new Vector3((float)origin.X,(float)origin.Y,(float)origin.Z);
        var d=new Vector3((float)dir.X,(float)dir.Y,(float)dir.Z).Normalized();
        VerticalHit? best=null; double distance=double.PositiveInfinity;
        foreach(var slot in world.Slots.Values)
        {
            if(!GodotObject.IsInstanceValid(slot.Group)) continue;
            var targets=usable(slot).ToHashSet(); if(targets.Count==0) continue;
            foreach(var mesh in Meshes(slot.Group))
            {
                var target=Target(mesh);
                if(!mesh.IsVisibleInTree() || !targets.Contains(target)) continue;
                if(MeshRay.Static(mesh,o,d) is { } t && t<distance) { distance=t; best=new(slot,target,mesh); }
            }
        }
        return best;
    }

    /// <summary>Revalidate every frame even for a stationary pointer: offers, visibility or the mounted group may change.</summary>
    public void Hover(VerticalHit? hit)
    {
        if(hit is not null && (!world.Slots.TryGetValue(hit.Slot.Loc.Id,out var slot) || slot!=hit.Slot || !usable(slot).Contains(hit.Target))) hit=null;
        if(_hover?.Slot==hit?.Slot && _hover?.Target==hit?.Target) return;
        Clear(); if(hit is null) return;
        _hover=hit;
        foreach(var mesh in Meshes(hit.Slot.Group).Where(m=>Target(m)==hit.Target))
        {
            if(mesh.Mesh is not { } resource) continue;
            for(int i=0;i<resource.GetSurfaceCount();i++)
            {
                var old=mesh.GetSurfaceOverrideMaterial(i);
                if(mesh.GetActiveMaterial(i) is not { } source) continue;
                var clone=(Material)source.Duplicate(false);
                if(clone is ShaderMaterial sm) sm.SetShaderParameter("hover_light",.35f);
                else if(clone is BaseMaterial3D standard)
                { standard.EmissionEnabled=true; standard.Emission=new Color(.35f,.3f,.16f); }
                mesh.SetSurfaceOverrideMaterial(i,clone); _clones.Add((mesh,i,old,clone));
            }
        }
    }
    public void Clear()
    {
        foreach(var (mesh,surface,old,clone) in _clones)
        {
            if(GodotObject.IsInstanceValid(mesh)) mesh.SetSurfaceOverrideMaterial(surface,old);
            clone.Dispose();
        }
        _clones.Clear(); _hover=null;
    }
    public void Dispose() => Clear();
}
