using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;
using CoreVec3 = AnimaNative.Overview.Vec3;

namespace AnimaNative.World;

/// <summary>
/// One door prop of a mounted scene (sceneRecipe.ts <c>SwingingDoor</c>): the placed group (origin on the hinge,
/// <c>measure: "fit"</c>), the payload's swing sign, the threshold it belongs to, and — when the model carries a
/// <c>leaf</c> node and the payload a <c>leaf_bbox</c> — the pivot the leaf turns in.
/// </summary>
public sealed class DoorProp
{
    public required Node3D Group { get; set; }
    public required int Swing { get; init; }
    public required P2 At { get; init; }
    public required int Level { get; init; }
    public required string[] Rooms { get; init; }
    public required float BaseYaw { get; set; }
    public double Angle { get; set; }
    public Node3D? SwingNode { get; set; }
    public Vector3 SwingAxis { get; set; }
    public (CoreVec3 Min, CoreVec3 Max)? LeafBox { get; init; }
    public FixDeg Fix { get; init; }
}

/// <summary>
/// The door props: <c>registerDoorProp</c> + <c>hangLeafPivot</c> + <c>retargetDoorProp</c> of sceneRecipe.ts. WHERE the
/// leaf turns is <see cref="LeafPivot.Compute"/> (scene_models.json [L]); this only inserts the pivot node between the
/// leaf and its parent (below the fix, inside the scaled root — raw model coordinates are the right ones) with the leaf
/// keeping its place. WHEN a door stands open is <see cref="DoorSwing"/>: view state that needs an avatar (E7) — in the
/// overview no one stands in front of any door, so every door eases to (and stays) shut.
/// </summary>
public static class DoorProps
{
    /// <summary>The node name Blender gives the door leaf it cut out (spec § 6).</summary>
    public const string LeafNode = "leaf";
    public const string LeafPivotNode = "leaf_pivot";

    /// <summary>
    /// <c>registerDoorProp</c>: a spec with <c>door</c> whose <c>opening</c> names a doorway joins the list; everything is
    /// READ from the payload (sign ±1 — anything else is +1 — the threshold, its storey and rooms). Null otherwise.
    /// </summary>
    public static DoorProp? Register(ScenePayload scene, SceneModelSpec spec, Node3D group)
    {
        if (spec.Door is not { } door) return null;
        if (door.Opening < 0 || door.Opening >= scene.Doorways.Count) return null;
        var way = scene.Doorways[door.Opening];
        var leafBox = door.LeafBox;
        var fix = new FixDeg(spec.FixX, spec.FixY, spec.FixZ);
        var hung = leafBox is { } lb ? HangLeafPivot(group, lb.Min, lb.Max, fix) : null;
        return new DoorProp
        {
            Group = group, Swing = door.Swing == -1 ? -1 : 1, At = way.AtWorld, Level = way.Level,
            Rooms = way.Rooms.Where(r => r.Length > 0).ToArray(), BaseYaw = group.Rotation.Y,
            SwingNode = hung?.Node, SwingAxis = hung?.Axis ?? Vector3.Up, LeafBox = leafBox, Fix = fix,
        };
    }

    /// <summary>
    /// <c>hangLeafPivot</c>: the placed model's <c>leaf</c> node into a pivot group on its hinge edge; null when the model
    /// has no such node (the whole group swings). A leaf that already hangs in a pivot is re-seated, never wrapped twice.
    /// </summary>
    public static (Node3D Node, Vector3 Axis)? HangLeafPivot(Node3D group, CoreVec3 min, CoreVec3 max, FixDeg fix)
    {
        var leaf = Find(group, LeafNode);
        if (leaf?.GetParent() is not Node3D parent) return null;
        var spec = LeafPivot.Compute(min, max, fix);
        var axis = new Vector3((float)spec.Axis.X, (float)spec.Axis.Y, (float)spec.Axis.Z);
        Node3D pivot;
        if (parent.Name == LeafPivotNode)
        {
            pivot = parent;
            leaf.Position += pivot.Position;
            pivot.Basis = Basis.Identity;
        }
        else
        {
            pivot = new Node3D { Name = LeafPivotNode };
            parent.AddChild(pivot);
            parent.RemoveChild(leaf);
            pivot.AddChild(leaf);
        }
        pivot.Position = new Vector3((float)spec.Point.X, (float)spec.Point.Y, (float)spec.Point.Z);
        leaf.Position -= pivot.Position;
        return (pivot, axis);
    }

    /// <summary><c>retargetDoorProp</c>: a tier swap replaced the group — the leaf pivot is hung again on the fresh mesh, the angle carries over.</summary>
    public static void Retarget(DoorProp door, Node3D next)
    {
        door.Group = next;
        var hung = door.LeafBox is { } lb ? HangLeafPivot(next, lb.Min, lb.Max, door.Fix) : null;
        door.SwingNode = hung?.Node;
        door.SwingAxis = hung?.Axis ?? Vector3.Up;
        door.BaseYaw = next.Rotation.Y;
        Show(door);
    }

    /// <summary>
    /// One frame of the swing (main.ts' door loop): the target from the avatar's distance (<see cref="DoorSwing.DoorDistance"/>
    /// on the avatar's storey) — +∞ in the overview, so the target is 0 — eased at 3 rad/s.
    /// </summary>
    public static void Tick(DoorProp door, double dt, double avatarDistM = double.PositiveInfinity, bool enterable = true)
    {
        double target = DoorSwing.DoorTargetAngle(avatarDistM, enterable, door.Swing);
        double next = DoorSwing.EaseAngle(door.Angle, target, dt);
        if (next == door.Angle) return;
        door.Angle = next;
        Show(door);
    }

    /// <summary>The angle onto the node that turns: the leaf pivot about its axis, else the whole group about y.</summary>
    public static void Show(DoorProp door)
    {
        if (door.SwingNode is { } pivot && GodotObject.IsInstanceValid(pivot))
            pivot.Basis = door.Angle == 0 ? Basis.Identity : new Basis(door.SwingAxis.Normalized(), (float)door.Angle);
        else if (GodotObject.IsInstanceValid(door.Group))
            door.Group.Rotation = new Vector3(door.Group.Rotation.X, door.BaseYaw + (float)door.Angle, door.Group.Rotation.Z);
    }

    private static Node3D? Find(Node n, string name)
    {
        if (n is Node3D n3 && n.Name == name) return n3;
        foreach (var c in n.GetChildren())
            if (Find(c, name) is { } hit) return hit;
        return null;
    }
}
