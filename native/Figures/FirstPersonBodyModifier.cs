using System;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// Task 48 / E7-T3: final skeleton modifier, after animation and secondary motion. The head and descendants
/// shrink to .001 for rendering only; Godot restores modifier poses after upload. The lens ignores scale,
/// carrying the metre rest offset with the current head orientation. No material or shader is allocated.
/// </summary>
public partial class FirstPersonBodyModifier : SkeletonModifier3D
{
    public int Head { get; init; }
    public Vector3 EyeOffset { get; init; }
    public bool Enabled { get; set; }
    public Action? Posed { get; init; }
    private Vector3 _headScale = Vector3.One;
    private bool _shrunk;

    public Vector3 Eye
    {
        get
        {
            var skel = GetSkeleton();
            if (skel is null) return Vector3.Zero;
            var pose = skel.GlobalTransform * skel.GetBoneGlobalPose(Head);
            return pose.Origin + pose.Basis.Orthonormalized() * EyeOffset;
        }
    }

    public override void _ProcessModificationWithDelta(double delta) => StepNow();

    /// <summary>One final pose pass; also used by --check embody on a deterministic two-bone fixture.</summary>
    public void StepNow()
    {
        if (!Enabled || GetSkeleton() is not { } skel) return;
        _headScale = skel.GetBonePoseScale(Head);
        _shrunk = true;
        skel.SetBonePoseScale(Head, _headScale * .001f);
        Posed?.Invoke();
    }

    /// <summary>Restore immediately on exit/replacement; do not depend on the next animation update.</summary>
    public void RestoreHead()
    {
        if (_shrunk && GetSkeleton() is { } skel) skel.SetBonePoseScale(Head, _headScale);
        _shrunk = false;
    }
}
