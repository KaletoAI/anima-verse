using System;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>Task 48 / E7-T3: npcs.eyeOf/lensOf and the avatar's headless first-person body.</summary>
public partial class Figure
{
    private bool _firstPerson;
    public FirstPersonBodyModifier? FirstPersonBody { get; private set; }
    /// <summary>Task 48: first-person view heading; standing-facing applies the strict 60° dead zone.</summary>
    public double? FirstPersonViewYaw { get; set; }
    public bool HasFirstPersonBody => FirstPersonBody is not null;
    public bool IsFirstPerson => _firstPerson;
    /// <summary>Actual drawn height is known before pool assignment, including normalized models.</summary>
    private double EyeBodyHeight => BodyHeight > 0 ? BodyHeight : PoolHeight ?? HeightM;
    public Vector3 Eye => GlobalPosition + Vector3.Up * (float)CameraFraming.EyeHeight(EyeBodyHeight);
    public Vector3 Lens => FirstPersonBody?.Eye ?? Eye;
    /// <summary>Skeleton hooks reassert the lens after the final posed head, including secondary motion.</summary>
    public event Action? HeadPosed;

    private void InitFirstPersonBody()
    {
        FirstPersonBody = null;
        if (Skeleton is { } skeleton)
        {
            int head = -1, crown = -1;
            for (int i = 0; i < skeleton.GetBoneCount(); i++)
            {
                string key = BoneNames.Norm(skeleton.GetBoneName(i));
                if (key == "head" && head < 0) head = i;
                if (key == "headtop_end" && crown < 0) crown = i;
            }
            if (head >= 0)
            {
                var frame = GlobalTransform.AffineInverse() * skeleton.GlobalTransform;
                var headRest = frame * skeleton.GetBoneGlobalRest(head);
                Vector3? top = crown >= 0 ? (frame * skeleton.GetBoneGlobalRest(crown)).Origin : null;
                var h = headRest.Origin;
                var rest = CameraFraming.RestEyePoint(new Vec3(h.X, h.Y, h.Z),
                    top is Vector3 t ? new Vec3(t.X,t.Y,t.Z) : null, EyeBodyHeight);
                var offset = headRest.Basis.Orthonormalized().Inverse() * (new Vector3((float)rest.X, (float)rest.Y, (float)rest.Z) - h);
                FirstPersonBody = new FirstPersonBodyModifier { Name = "FirstPersonBody", Head = head, EyeOffset = offset,
                    Posed = () => HeadPosed?.Invoke() };
                skeleton.AddChild(FirstPersonBody);
                // The modifier must remain last: secondary motion may be installed/reconfigured later too.
                skeleton.MoveChild(FirstPersonBody, -1);
            }
        }
        SetFirstPerson(_firstPerson);
    }

    /// <summary>figures.ts setFirstPerson: rigs with a head keep their body; other models/portraits hide whole.</summary>
    public void SetFirstPerson(bool on)
    {
        _firstPerson = on;
        if (FirstPersonBody is { } head && IsInstanceValid(head))
        {
            head.Enabled = on;
            if (!on) head.RestoreHead();
            if (Skeleton is { } skel) skel.MoveChild(head, -1);
        }
        if (Secondary is { } secondary) secondary.FirstPersonHead = on ? FirstPersonBody?.Head ?? -1 : -1;
        if (Body is { } body) body.Visible = !on || FirstPersonBody is not null;

    }
}
