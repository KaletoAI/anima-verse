using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Embody;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

public sealed record PlaceHit(string Id,Vector3 Slot,bool Diorama);

/// <summary>
/// Task 52 / E7-T7: embodied free-slot rings and room-diorama triangle picks with the 0.6 m gate.
/// Ownership ledger: this node owns its ring children; meshes/materials below are shared immutable resources.
/// Hover owns only MaterialOverlay overrides, records/restores their prior values, and shares ONE spot material
/// and shader for every diorama surface. No shader is allocated by Sync, Hit, Hover or an instance constructor.
/// Clear restores live borrowed nodes before freeing owned children; drop/mode exit/teardown call it explicitly.
/// </summary>
public partial class PlaceTargets : Node3D
{
    private static readonly ArrayMesh RingMesh=BuildRing();
    private static readonly Dictionary<int,StandardMaterial3D> RingMaterials=new();
    private static readonly Shader SpotShader=new() { Code="""
        shader_type spatial;
        render_mode unshaded, blend_add, depth_draw_never, cull_disabled;
        uniform vec3 spot;
        uniform bool enabled = false;
        varying vec3 world_at;
        void vertex() { world_at = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
        void fragment() {
            float d = length(world_at.xz - spot.xz);
            if (!enabled || d > 0.6) discard;
            ALBEDO = vec3(0.45, 0.35, 0.13);
            ALPHA = 0.5 * (1.0 - smoothstep(0.0, 0.6, d));
        }
        """ };
    private static readonly ShaderMaterial SpotMaterial=new() { Shader=SpotShader };
    private readonly List<(MeshInstance3D Mesh,string Id)> _rings=new();
    private readonly List<(MeshInstance3D Mesh,Material? Old)> _overlays=new();
    private readonly List<MeshInstance3D> _diorama=new();
    private readonly List<(string Id,Vector3 Point)> _free=new();
    private string _signature="";
    public int RingCount => _rings.Count;
    public IReadOnlyList<Vector3> Rings => _rings.Select(r=>r.Mesh.Position).ToArray();
    public bool HasHover { get; private set; }
    public static Material SharedSpotMaterial => SpotMaterial;
    private static IEnumerable<MeshInstance3D> Meshes(Node root)
    {
        if(root is MeshInstance3D m) yield return m;
        foreach(var c in root.GetChildren()) foreach(var mesh in Meshes(c)) yield return mesh;
    }

    public void Sync(LocationSlot tile,string room,IReadOnlyList<PlaceOffer> offers,string skip)
    {
        var nodes=tile.Placements.Where(p=>p.Spec.Role=="room" && p.Spec.RoomId==room && !p.Placeholder && p.Node is not null
            && GodotObject.IsInstanceValid(p.Node) && p.Node.IsVisibleInTree()).Select(p=>p.Node!).ToArray();
        var mounted=nodes.Length>0 ? new HashSet<string>{room} : new HashSet<string>();
        var rows=tile.Places.GlyphRows(room,offers,skip,mounted);
        var free=new List<(string Id,Vector3 Point)>();
        if(tile.Places.Markers.TryGetValue(room,out var entries)) foreach(var offer in offers)
        {
            if(offer.Free<=0 || !entries.TryGetValue(offer.Id,out var e) || e.Fixed || e.Anchor is not null || !e.Diorama) continue;
            foreach(int i in offer.FreeSlots) if(i>=0 && i<e.Slots.Length)
                free.Add((offer.Id,new((float)e.Slots[i].X,(float)e.Slots[i].Y,(float)e.Slots[i].Z)));
        }
        string signature=$"{tile.Group.GetInstanceId()}:{tile.MeshVersion}:{room}:"+string.Join(";",rows)
            +string.Join(";",free)+string.Join(";",nodes.Select(n=>n.GetInstanceId()));
        if(signature==_signature) return;
        Clear(); _signature=signature; _free.AddRange(free);
        foreach(var node in nodes) _diorama.AddRange(Meshes(node));
        foreach(var row in rows)
        {
            if(!RingMaterials.TryGetValue(row.Colour,out var material))
            {
                material=new StandardMaterial3D { ShadingMode=BaseMaterial3D.ShadingModeEnum.Unshaded,
                    Transparency=BaseMaterial3D.TransparencyEnum.Alpha,CullMode=BaseMaterial3D.CullModeEnum.Disabled,
                    NoDepthTest=true,DepthDrawMode=BaseMaterial3D.DepthDrawModeEnum.Disabled,
                    AlbedoColor=new Color((uint)(row.Colour<<8)|0xd9),RenderPriority=20 };
                RingMaterials.Add(row.Colour,material);
            }
            var ring=new MeshInstance3D { Name="PlaceRing",Mesh=RingMesh,MaterialOverride=material,
                CastShadow=GeometryInstance3D.ShadowCastingSetting.Off,
                Position=new((float)row.Position.X,(float)row.Position.Y,(float)row.Position.Z) };
            ring.SetMeta(LocationFade.OverlayMeta,true); AddChild(ring); _rings.Add((ring,row.PlaceId));
        }
    }
    public PlaceHit? Hit(Vec3 origin,Vec3 direction)
    {
        var o=new Vector3((float)origin.X,(float)origin.Y,(float)origin.Z);
        var d=new Vector3((float)direction.X,(float)direction.Y,(float)direction.Z).Normalized();
        double best=double.PositiveInfinity; Vector3? point=null;
        foreach(var mesh in _diorama)
            if(GodotObject.IsInstanceValid(mesh) && mesh.IsVisibleInTree() && MeshRay.Static(mesh,o,d) is { } t && t<best)
            { best=t; point=o+d*(float)t; }
        if(point is { } hit)
        {
            string? id=PlacePick.PickablePlaceFor(new(hit.X,hit.Z),_free.GroupBy(p=>p.Id)
                .Select(g=>new PickPlace(g.Key,g.Select(p=>new P2(p.Point.X,p.Point.Z)).ToArray())),PlacePick.PlacePickRadiusM);
            if(id is not null)
            {
                var p=_free.Where(p=>p.Id==id).MinBy(p=>(p.Point.X-hit.X)*(p.Point.X-hit.X)+(p.Point.Z-hit.Z)*(p.Point.Z-hit.Z));
                return new(id,p.Point,true);
            }
        }
        best=double.PositiveInfinity; PlaceHit? ringHit=null;
        foreach(var (mesh,id) in _rings)
            if(MeshRay.Static(mesh,o,d) is { } t && t<best) { best=t; ringHit=new(id,mesh.Position,false); }
        return ringHit;
    }
    public void Hover(PlaceHit? hit)
    {
        ClearHover(); HasHover=hit is not null;
        if(hit is not { Diorama:true }) return;
        HoverMeshes(_diorama,hit.Slot);
    }
    public void HoverMeshes(IEnumerable<MeshInstance3D> meshes,Vector3 spot)
    {
        ClearHover(); HasHover=true;
        SpotMaterial.SetShaderParameter("spot",spot); SpotMaterial.SetShaderParameter("enabled",true);
        foreach(var mesh in meshes)
        {
            if(!GodotObject.IsInstanceValid(mesh)) continue;
            _overlays.Add((mesh,mesh.MaterialOverlay)); mesh.MaterialOverlay=SpotMaterial;
        }
    }
    public void ClearHover()
    {
        foreach(var (mesh,old) in _overlays) if(GodotObject.IsInstanceValid(mesh)) mesh.MaterialOverlay=old;
        _overlays.Clear(); SpotMaterial.SetShaderParameter("enabled",false); HasHover=false;
    }
    public void Clear()
    {
        ClearHover();
        foreach(var (mesh,_) in _rings) { mesh.Visible=false; mesh.QueueFree(); }
        _rings.Clear(); _diorama.Clear(); _free.Clear(); _signature="";
    }
    public override void _ExitTree() => Clear();
    private static ArrayMesh BuildRing()
    {
        var vertices=new Vector3[32*6];
        for(int i=0;i<32;i++)
        {
            Vector3 At(int j,double r) => new((float)(Math.Cos(j*Math.Tau/32)*r),0,(float)(Math.Sin(j*Math.Tau/32)*r));
            int k=i*6; vertices[k]=At(i,.32); vertices[k+1]=At(i,.25); vertices[k+2]=At(i+1,.32);
            vertices[k+3]=At(i,.25); vertices[k+4]=At(i+1,.25); vertices[k+5]=At(i+1,.32);
        }
        var arrays=new Godot.Collections.Array(); arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex]=vertices;
        var mesh=new ArrayMesh(); mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles,arrays); return mesh;
    }
}
