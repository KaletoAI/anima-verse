using System;

namespace AnimaNative.Scatter;

/// <summary>Task 38 (E4-T3): the baked image's height in model heights and its width/height ratio.</summary>
public readonly record struct ImpostorFrame(double SpanH, double Aspect);
/// <summary>Task 38 (E4-T3): the standing quad's dimensions and centre above the sampled ground point.</summary>
public readonly record struct ImpostorQuad(double W, double H, double CentreY);

/// <summary>Task 38 (E4-T3): import-free <c>scatterLod.ts</c> impostor arithmetic. Geometry is consumed by both
/// the bake camera and the runtime quad; <c>shared/test-vectors/impostors.json</c> is the parity gate.</summary>
public static partial class ScatterLod
{
    public const double ImpostorFarM = 400, ImpostorTailFactor = 0.25, ImpostorWindowCellM = 64;
    public const int ImpostorWindowSpanMax = 32;
    public const double ImpostorElevRad = 10 * Math.PI / 180, ImpostorBakePad = 1.05;

    /// <summary>The sampler's half-span; reach follows the corner of this window, capped at 400 m.</summary>
    public static int ImpostorWindowSpan(double cullM) => !double.IsFinite(cullM) || cullM <= 0 ? 1
        : (int)Math.Max(1, Math.Min(Math.Ceiling(cullM / ImpostorWindowCellM), ImpostorWindowSpanMax));
    public static double ImpostorReachM(double cullM)
        => Math.Min(Math.Sqrt(2) * (ImpostorWindowSpan(cullM) + 1) * ImpostorWindowCellM, ImpostorFarM);
    public static bool ImpostorInWindow(double distM, ScatterLodCfg cfg) => distM > cfg.CullM && distM <= ImpostorFarM;

    /// <summary>Continues the mesh's 0.25 share; reaches 0.0625 at the window corner and holds that floor.</summary>
    public static double ImpostorShare(double distM, ScatterLodCfg cfg)
    {
        if (!ImpostorInWindow(distM, cfg)) return 0;
        double span = ImpostorReachM(cfg.CullM) - cfg.CullM;
        if (!(span > 0)) return MinShare * ImpostorTailFactor;
        double t = Math.Min((distM - cfg.CullM) / span, 1);
        return MinShare * (1 - t * (1 - ImpostorTailFactor));
    }
    public static bool ImpostorVisible(int index, double distM, ScatterLodCfg cfg)
    {
        double share = ImpostorShare(distM, cfg);
        return share >= 1 || (share > 0 && InstanceHash(index) < share);
    }

    /// <summary>Turns +Z toward the camera about Y only; height deliberately is not an input.</summary>
    public static double ImpostorYaw(double px, double pz, double camX, double camZ) => Math.Atan2(camX - px, camZ - pz);
    public static ImpostorFrame? ImpostorFrame(double heightM, double radiusM)
    {
        if (!(heightM > 0) || !(radiusM > 0)) return null;
        double halfW = radiusM * ImpostorBakePad;
        double halfH = (heightM / 2 * Math.Cos(ImpostorElevRad) + radiusM * Math.Sin(ImpostorElevRad)) * ImpostorBakePad;
        if (!(halfH > 0)) return null;
        return new(2 * halfH / heightM, halfW / halfH);
    }
    public static ImpostorQuad ImpostorQuad(double targetH, ImpostorFrame frame)
    {
        double h = targetH * frame.SpanH;
        return new(h * frame.Aspect, h, targetH * Math.Cos(ImpostorElevRad) / 2);
    }
    public static (double X, double Y, double Z)[] ImpostorCorners(
        double cx, double cy, double cz, double w, double h, double camX, double camZ)
    {
        double yaw = ImpostorYaw(cx, cz, camX, camZ);
        double rx = Math.Cos(yaw) * w / 2, rz = -Math.Sin(yaw) * w / 2;
        double top = cy + h / 2, bottom = cy - h / 2;
        return new[] { (cx - rx, bottom, cz - rz), (cx + rx, bottom, cz + rz),
            (cx + rx, top, cz + rz), (cx - rx, top, cz - rz) };
    }

    /// <summary>Only a successfully loaded degenerate model is refused; transient failures retry next contact.</summary>
    public static string ImpostorBakeVerdict(string attempt) => attempt == "baked" ? "store" : attempt == "unbakeable" ? "refuse" : "retry";
}
