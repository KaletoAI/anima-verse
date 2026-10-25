using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Overview;

/// <summary>
/// Port of <c>bootProgress</c> of client3d/src/game/boot.ts — the data behind the loading
/// screen: <see cref="Percent"/> counts the finished stages (anything that is not a stage
/// counts for nothing), <see cref="Label"/> names the first stage of <see cref="Stages"/> still
/// missing, or <c>"ready"</c>. The HUD's TitleScreen renders both (bus shape
/// <c>{percent, label}</c>). Vectors: shared/test-vectors/overview_hud.json [P1..P3].
/// </summary>
public readonly record struct BootProgress(int Percent, string Label)
{
    /// <summary>The stages in progress order (<c>BOOT_STAGES</c>).</summary>
    public static readonly IReadOnlyList<string> Stages =
        Array.AsReadOnly(new[] { "world", "scenes", "tiles", "visible", "figures", "arrival" });

    /// <summary>The label once every stage is through.</summary>
    public const string Ready = "ready";

    /// <summary>
    /// The progress for the set of finished stages. The step is derived from the stage count and
    /// rounded like JS <c>Math.round</c>, so the last stage lands on exactly 100.
    /// </summary>
    public static BootProgress Of(IEnumerable<string> done)
    {
        var set = done as IReadOnlySet<string> ?? done.ToHashSet(StringComparer.Ordinal);
        int count = 0;
        string label = Ready;
        foreach (var stage in Stages)
        {
            if (set.Contains(stage)) count += 1;
            else if (label == Ready) label = stage;
        }
        return new BootProgress((int)JsSemantics.Round((count * 100.0) / Stages.Count), label);
    }
}
