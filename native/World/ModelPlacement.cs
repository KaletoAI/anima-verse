using System;
using System.Collections.Generic;
using AnimaNative.Scene;
using Godot;
using CoreVec3 = AnimaNative.Overview.Vec3;

namespace AnimaNative.World;

/// <summary>
/// THE placement routine of the contract (§ B2) on the Godot side, the twin of <c>placeModelSpec</c>
/// (packages/scene-render/src/place.ts). The arithmetic is the Core's <see cref="PlaceTransform"/> (checked
/// against shared/test-vectors/scene_place.json); this class only measures the source and builds the chain:
///
///   outer (anchor/bottom_y, uniform scale)
///     └ yaw (rotation.y = +rad(yaw_deg), § A1.1 sign)
///         └ fit (non-uniform scale, <c>measure: "fit"</c> only)
///             └ fix (orientation fix, position = −centre)
///                 └ source
///
/// No Godot Euler is involved: the fix basis is <see cref="Mat3.EulerYxz"/> (three's 'YXZ' = Ry·Rx·Rz, the same
/// matrix the vectors pin through <c>placeTransform</c> and <c>leafPivot</c>), the yaw <see cref="Mat3.RotY"/>.
/// Measurement mirrors three's <c>Box3.setFromObject</c> (non-precise) per mesh: each mesh's LOCAL AABB with its
/// matrix into the fix frame, kept separate (a merged hull would move the seat of an asymmetric multi-mesh prop).
/// </summary>
public static class ModelPlacement
{
    /// <summary>A Core rotation as a Godot basis (columns = the images of the unit axes).</summary>
    public static Basis ToBasis(Mat3 m)
        => new(new Vector3((float)m.M00, (float)m.M10, (float)m.M20),
               new Vector3((float)m.M01, (float)m.M11, (float)m.M21),
               new Vector3((float)m.M02, (float)m.M12, (float)m.M22));

    public static Vector3 ToGodot(CoreVec3 v) => new((float)v.X, (float)v.Y, (float)v.Z);

    public static Node3D Place(Node3D source, SceneModelSpec spec)
    {
        var t = PlaceTransform.Compute(spec, MeshBoxes(source));
        const double d = Math.PI / 180;
        var fixXf = new Transform3D(ToBasis(Mat3.EulerYxz(spec.FixX * d, spec.FixY * d, spec.FixZ * d)), ToGodot(t.FixPos));
        var fixNode = new Node3D { Name = "Fix", Transform = fixXf };
        fixNode.AddChild(source);
        var fitNode = new Node3D { Name = "Fit", Transform = new Transform3D(Basis.FromScale(ToGodot(t.FitScale)), Vector3.Zero) };
        fitNode.AddChild(fixNode);
        var yawNode = new Node3D { Name = "Yaw", Transform = new Transform3D(ToBasis(Mat3.RotY(Js.Or(spec.YawDeg, 0) * d)), Vector3.Zero) };
        yawNode.AddChild(fitNode);
        float s = (float)t.OuterScale;
        var outer = new Node3D
        {
            Name = $"Placed_{spec.Role}_{spec.Id}",
            Transform = new Transform3D(Basis.FromScale(new Vector3(s, s, s)), ToGodot(t.OuterPos)),
        };
        outer.AddChild(yawNode);
        return outer;
    }

    /// <summary>Every mesh's local AABB and its matrix into <paramref name="source"/>'s parent frame (its own transform included).</summary>
    public static List<MeshBox> MeshBoxes(Node3D source)
    {
        var boxes = new List<MeshBox>();
        CollectBoxes(source, source.Transform, boxes);
        return boxes;
    }

    private static void CollectBoxes(Node node, Transform3D xf, List<MeshBox> boxes)
    {
        Aabb? local = node switch
        {
            MeshInstance3D mi when mi.Mesh is not null => mi.Mesh.GetAabb(),
            ImporterMeshInstance3D imi when imi.Mesh is not null => imi.Mesh.GetMesh()?.GetAabb(),
            _ => null,
        };
        if (local is { } l)
        {
            var b = xf.Basis;
            var o = xf.Origin;
            boxes.Add(new MeshBox(new CoreVec3(l.Position.X, l.Position.Y, l.Position.Z),
                                  new CoreVec3(l.End.X, l.End.Y, l.End.Z),
                                  new double[] { b.X.X, b.X.Y, b.X.Z, 0, b.Y.X, b.Y.Y, b.Y.Z, 0, b.Z.X, b.Z.Y, b.Z.Z, 0, o.X, o.Y, o.Z, 1 }));
        }
        foreach (var child in node.GetChildren())
            if (child is Node3D c) CollectBoxes(c, xf * c.Transform, boxes);
    }

    /// <summary>
    /// AABB of every mesh under <paramref name="node"/> (its own transform included), expressed in the frame that
    /// <paramref name="parent"/> maps into — a measuring helper for checks and stats, not part of the placement.
    /// </summary>
    public static Aabb Measure(Node3D node, Transform3D parent)
    {
        Aabb? box = null;
        Walk(node, parent * node.Transform, ref box);
        return box ?? new Aabb();
    }

    private static void Walk(Node node, Transform3D xf, ref Aabb? box)
    {
        Aabb? local = node switch
        {
            MeshInstance3D mi when mi.Mesh is not null => mi.Mesh.GetAabb(),
            ImporterMeshInstance3D imi when imi.Mesh is not null => imi.Mesh.GetMesh()?.GetAabb(),
            _ => null,
        };
        if (local is { } l)
        {
            var world = xf * l;
            box = box is { } b ? b.Merge(world) : world;
        }
        foreach (var child in node.GetChildren())
            if (child is Node3D c) Walk(c, xf * c.Transform, ref box);
    }
}
