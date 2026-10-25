using System;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// THE placement routine of the contract (§ B2), a port of
/// <c>placeModelSpec</c> (packages/scene-render/src/place.ts). Same chain,
/// same order, same measurements:
///
///   outer (anchor/bottom_y, uniform scale)
///     └ yaw (rotation.y = +rad(yaw_deg), § A1.1 sign)
///         └ fit (non-uniform scale, `measure: "fit"` only)
///             └ fix (orientation fix, Euler YXZ, position = −centre)
///                 └ source
///
/// Godot and three.js share the frame (right-handed, y up) and the rotation
/// sense, and Godot's <c>EulerOrder.Yxz</c> composes Ry·Rx·Rz like three's
/// 'YXZ'. Box measurement mirrors three's <c>Box3.setFromObject</c> (default,
/// non-precise): every mesh's LOCAL AABB transformed into the measuring frame
/// and merged.
/// </summary>
public static class ModelPlacement
{
    private static double Rad(double deg) => deg * Math.PI / 180.0;
    private static double Snap(double deg) => Math.Round(deg / 90.0) * 90.0;

    private static Basis Euler(double x, double y, double z, EulerOrder order)
        => Basis.FromEuler(new Vector3((float)Rad(x), (float)Rad(y), (float)Rad(z)), order);

    public static Node3D Place(Node3D source, SceneModelSpec spec)
    {
        bool fit = spec.Measure == "fit";
        var snapped = Euler(Snap(spec.FixX), Snap(spec.FixY), Snap(spec.FixZ), EulerOrder.Yxz);
        var exact = Euler(spec.FixX, spec.FixY, spec.FixZ, EulerOrder.Yxz);
        var yaw = new Basis(Vector3.Up, (float)Rad(spec.YawDeg));

        // Object size under the fix rounded to 90° (the axis assignment counts,
        // the fine angle does not).
        var sObj = Measure(source, new Transform3D(snapped, Vector3.Zero)).Size;
        // Building fill measure: after the yaw, fix still rounded.
        var sYaw = Measure(source, new Transform3D(yaw * snapped, Vector3.Zero)).Size;

        // Seating datum: the box of the object BEFORE the yaw, exact fix.
        var bFix = Measure(source, new Transform3D(exact, Vector3.Zero));
        var cFix = bFix.GetCenter();
        var fixPos = fit ? new Vector3(-bFix.Position.X, -bFix.Position.Y, -cFix.Z) : -cFix;
        var fixXf = new Transform3D(exact, fixPos);

        var fitScale = Vector3.One;
        if (fit)
        {
            float sx = (float)((spec.SizeM?[0] is > 0 ? spec.SizeM[0] : 1) / (sObj.X > 0 ? sObj.X : 1));
            float sy = (float)((spec.SizeM?[1] is > 0 ? spec.SizeM[1] : 1) / (sObj.Y > 0 ? sObj.Y : 1));
            fitScale = new Vector3(sx, sy, sx);
        }
        var fitXf = new Transform3D(Basis.FromScale(fitScale), Vector3.Zero);
        var yawXf = new Transform3D(yaw, Vector3.Zero);

        float scale = 1f;
        if (!fit)
        {
            double extent = spec.Measure switch
            {
                "yawed_xz" => Math.Max(sYaw.X, sYaw.Z),
                "xz" => Math.Max(sObj.X, sObj.Z),
                _ => Math.Max(sObj.X, Math.Max(sObj.Y, sObj.Z)),
            };
            if (!(extent > 0)) extent = 1;
            scale = (float)((spec.MaxM > 0 ? spec.MaxM : 1) / extent);
        }
        var outerBasis = Basis.FromScale(new Vector3(scale, scale, scale));
        var bOut = Measure(source, new Transform3D(outerBasis, Vector3.Zero) * yawXf * fitXf * fixXf);
        var outerPos = new Vector3((float)spec.AnchorX, (float)(spec.BottomY - bOut.Position.Y), (float)spec.AnchorZ);

        var fixNode = new Node3D { Name = "Fix", Transform = fixXf };
        fixNode.AddChild(source);
        var fitNode = new Node3D { Name = "Fit", Transform = fitXf };
        fitNode.AddChild(fixNode);
        var yawNode = new Node3D { Name = "Yaw", Transform = yawXf };
        yawNode.AddChild(fitNode);
        var outer = new Node3D { Name = $"Placed_{spec.Role}_{spec.Id}", Transform = new Transform3D(outerBasis, outerPos) };
        outer.AddChild(yawNode);
        return outer;
    }

    /// <summary>
    /// AABB of every mesh under <paramref name="node"/> (its own transform
    /// included), expressed in the frame that <paramref name="parent"/> maps into.
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
