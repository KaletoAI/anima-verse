using System;

namespace AnimaNative.Overview;

/// <summary>
/// The ONE open detail view of the overview (client3d/src/main.ts, "The open detail view: ONE explicit
/// singleton"): exactly one location shows its interior; opening another closes the current one; there
/// is no auto-reopen. The overview auto-close rule and its numbers are client3d/src/game/openView.ts
/// (<c>CLOSE_CAM_DIST</c>, <c>CLOSE_TARGET_FOOTPRINTS</c>, <c>CLOSE_TARGET_MIN_M</c>, <c>closeTargetDist</c>,
/// <c>openViewShouldClose</c>), vector-checked against shared/test-vectors/overview_labels.json [D, C]
/// (derivations in client3d/scripts/smoke_overview_labels.mjs). The singleton, <c>OPEN_FLY_DIST</c> and the badge
/// are inline in main.ts; native/tests/PickingTests.cs derives those cases by hand.
/// </summary>
public sealed class OpenView
{
    /// <summary>Camera farther out than this closes the open view (overview only).</summary>
    public const double CloseCamDist = 60;
    /// <summary>Target panned this many footprint widths off the open location closes it…</summary>
    public const double CloseTargetFootprints = 3;
    /// <summary>…but never fewer metres than this.</summary>
    public const double CloseTargetMinM = 12;
    /// <summary>"Look inside" / "Zoom in" fly in to at most this distance.</summary>
    public const double OpenFlyDist = 15;

    /// <summary>The open location, or null.</summary>
    public string? OpenId { get; private set; }

    /// <summary><c>openLocation(id)</c>: a no-op when it is open already or cannot be opened; otherwise it
    /// becomes THE open one and the previously open one (returned, may be null) closes.</summary>
    public bool TryOpen(string id, bool openable, out string? closed)
    {
        closed = null;
        if (OpenId == id || !openable) return false;
        closed = OpenId;
        OpenId = id;
        return true;
    }

    /// <summary><c>closeOpenLocation()</c>: the id that closed, or null when nothing was open.</summary>
    public string? Close()
    {
        var was = OpenId;
        OpenId = null;
        return was;
    }

    /// <summary><c>closeTargetDist(tile)</c> = max(12, 3 · footprint width) metres.</summary>
    public static double CloseTargetDist(double width) => Math.Max(CloseTargetMinM, width * CloseTargetFootprints);

    /// <summary>
    /// <c>openViewShouldClose</c>: the camera is farther out than 60 m, or the target stands farther than
    /// <see cref="CloseTargetDist"/> from the open location's centre, measured on the ground plane
    /// (<c>Math.hypot(target.x − center.x, target.z − center.z)</c>). Both strictly greater.
    /// </summary>
    public static bool ShouldClose(double camDist, double targetX, double targetZ, double centreX, double centreZ,
                                   double width)
    {
        double off = double.Hypot(targetX - centreX, targetZ - centreZ);   // JS Math.hypot
        return camDist > CloseCamDist || off > CloseTargetDist(width);
    }

    /// <summary><c>flyInDist()</c>: never farther than where the camera is already going.</summary>
    public static double FlyInDist(double targetDist) => Math.Min(targetDist, OpenFlyDist);

    /// <summary><c>refreshOpenBadge</c>: the badge shows the open location's name (untrimmed) when it is not
    /// blank by JS <c>trim()</c> (the ECMAScript white-space set, <see cref="JsSemantics.IsWhiteSpace"/>).</summary>
    public static string? BadgeName(string? name)
    {
        if (name is null) return null;
        foreach (char c in name)
            if (!JsSemantics.IsWhiteSpace(c)) return name;
        return null;
    }
}
