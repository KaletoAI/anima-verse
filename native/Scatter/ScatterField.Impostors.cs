using System;
using System.Linq;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>Task 38 (E4-T3): the far half of browser <c>binProp</c>. The shared frame/quad/yaw arithmetic is already
/// green against impostors.json. This adapter only composes the Godot basis and uploads the written prefix.</summary>
public partial class ScatterField
{
    private readonly IImpostorSource _impostors;
    private QuadMesh? _impostorQuad;
    private bool _impostorsEnabled = true;
    /// <summary>Task 40: matrix switch, persistent across LOD ticks and newly sampled entries; restore re-bins immediately.</summary>
    public bool ImpostorsEnabled
    {
        get => _impostorsEnabled;
        set
        {
            _impostorsEnabled = value;
            foreach (var p in Props.Concat(_retiring))
                if (!value) HideImpostor(p);
                else if (_lodCam is { } cam) BinImpostors(p, cam);
        }
    }

    private void BinImpostors(Prop p, (double X, double Y, double Z) cam)
    {
        if (!_impostorsEnabled) { HideImpostor(p); return; }
        if (p.LoUrl.Length == 0) return;
        double dx = cam.X - p.SphereCenter.X, dy = cam.Y - p.SphereCenter.Y, dz = cam.Z - p.SphereCenter.Z;
        double distance = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        if (distance - p.SphereRadius > ScatterLod.ImpostorFarM || distance + p.SphereRadius <= _cfg.CullM)
        {
            HideImpostor(p);
            return;
        }
        if (p.Bake is null)
        {
            p.Bake = _impostors.Acquire(p.LoUrl);
            if (p.Bake is null) return;
            _impostorQuad ??= new QuadMesh { Size = Vector2.One };
            p.Impostor = NewMultiMesh(_impostorQuad, p.BaseCount, p.Box);
            p.ImpostorBuf = new float[p.BaseCount * 12];
            p.ImpostorNode = new MultiMeshInstance3D
            {
                Name = $"ScatterImpostor_{p.Row}_{p.VariantPos}", Multimesh = p.Impostor,
                MaterialOverride = ScatterShaders.Impostor(p.Bake.Texture),
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off, Visible = false,
                Layers = World.HemiUniforms.Layer,
            };
            AddChild(p.ImpostorNode);
        }
        var q = ScatterLod.ImpostorQuad(p.TargetH, p.Bake.Frame);
        double cull2 = _cfg.CullM * _cfg.CullM, far2 = ScatterLod.ImpostorFarM * ScatterLod.ImpostorFarM;
        int n = 0;
        for (int i = 0; i < p.BaseCount; i++)
        {
            double px = p.Pos[i * 3], py = p.Pos[i * 3 + 1], pz = p.Pos[i * 3 + 2];
            dx = px - cam.X; dy = py - cam.Y; dz = pz - cam.Z;
            double d2 = dx * dx + dy * dy + dz * dz;
            if (!(d2 > cull2 && d2 <= far2)
                || !ScatterLod.InViewCone(dx, dz, _cone.FwdX, _cone.FwdZ, _cone.CosHalf)
                || !ScatterLod.ImpostorVisible(i, Math.Sqrt(d2), _cfg)) continue;
            double yaw = ScatterLod.ImpostorYaw(px, pz, cam.X, cam.Z);
            double c = Math.Cos(yaw), s = Math.Sin(yaw);
            int at = n++ * 12;
            var b = p.ImpostorBuf!;
            // Godot's row-major 3x4 buffer: translate * rotY * scale; the vertical column stays (0,h,0).
            b[at] = (float)(c * q.W); b[at + 1] = 0; b[at + 2] = (float)s; b[at + 3] = (float)px;
            b[at + 4] = 0; b[at + 5] = (float)q.H; b[at + 6] = 0; b[at + 7] = (float)(py + q.CentreY);
            b[at + 8] = (float)(-s * q.W); b[at + 9] = 0; b[at + 10] = (float)c; b[at + 11] = (float)pz;
        }
        p.ImpostorN = n;
        p.Impostor!.VisibleInstanceCount = n;
        p.ImpostorNode!.Visible = n > 0;
        // One upload of the whole allocation (MultimeshSetBuffer needs all of it; rows past n are hidden by the visible
        // count). No dirty ledger as for the mesh slots: the camera yaw changes every row on every LOD pass anyway.
        if (n > 0) RenderingServer.MultimeshSetBuffer(p.Impostor.GetRid(), p.ImpostorBuf!);
    }

    private static void HideImpostor(Prop p)
    {
        p.ImpostorN = 0;
        if (p.Impostor is not null) p.Impostor.VisibleInstanceCount = 0;
        if (p.ImpostorNode is not null) p.ImpostorNode.Visible = false;
    }
    private void DropImpostor(Prop p)
    {
        p.ImpostorNode?.QueueFree();
        if (p.Bake is not null) _impostors.Release(p.LoUrl);
        p.Bake = null;
        p.ImpostorN = 0;
    }

    public override void _ExitTree()
    {
        foreach (var p in Props) { p.Disposed = true; DropImpostor(p); }
        foreach (var p in _retiring) { p.Disposed = true; DropImpostor(p); }
    }
}
