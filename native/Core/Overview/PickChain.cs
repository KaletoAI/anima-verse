using System;

namespace AnimaNative.Overview;

/// <summary>What a click does to the HUD's <c>info</c> field.</summary>
public enum InfoChange
{
    /// <summary>The click was taken before the location pick (a figure): the panel stays as it is.</summary>
    Unchanged,
    /// <summary>Nothing under the pointer: <c>info = null</c>.</summary>
    Clear,
    /// <summary>A location under the pointer: <c>info = infoPanelData(…)</c> of <see cref="PickOutcome.InfoLocationId"/>.</summary>
    Show,
}

/// <summary>
/// The outcome of one click: the new <c>selected</c> (null = cleared) and the change of <c>info</c>.
/// </summary>
public readonly record struct PickOutcome(string? Selected, InfoChange Info, string? InfoLocationId);

/// <summary>
/// The click chain of the browser's overview (client3d/src/scene/engine.ts <c>pointerup</c> →
/// main.ts <c>engine.pickFigure</c> → object actions → <c>engine.onPick</c>) as one
/// decision over the two hits the scene computed:
///
///   1. a FIGURE under the pointer eats the click: <c>selected = it</c>, the info panel stays;
///   2. no figure: <c>selected = null</c>. The browser then asks, in this order, a seatable prop or a
///      free place glyph (→ place menu), then a stair or lift (→ climb). Each action can end the chain;
///   3. the LOCATION under the pointer: <c>info = infoPanelData(it)</c>; nothing → <c>info = null</c>.
///
/// So a click on empty ground clears both the selection and the panel, a click on a figure inside a
/// location never opens that location's panel.
/// </summary>
public static class PickChain
{
    public static PickOutcome Resolve(string? figureHit, string? locationHit, Func<bool>? pickAction = null)
    {
        if (figureHit is not null) return new PickOutcome(figureHit, InfoChange.Unchanged, null);
        // Object actions precede the location panel; empty ground never issues a walk.
        if (pickAction?.Invoke() == true) return new PickOutcome(null, InfoChange.Unchanged, null);
        return locationHit is null
            ? new PickOutcome(null, InfoChange.Clear, null)
            : new PickOutcome(null, InfoChange.Show, locationHit);
    }
}
