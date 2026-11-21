using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The per-strand hair of a figure (figureRuntime.ts <c>prepareStrandHair</c> / <c>setStrandHair</c> /
/// <c>setStrandBlocked</c>, figures.ts <c>Figure.strand*</c>): the manager hands the source of a FULL-tier model
/// (<see cref="SetStrandSource"/>, after <see cref="SetBody"/>), <see cref="PrepareStrandHair"/> binds the record once it
/// has loaded, the budget (<see cref="FigureManager.TickStrandHair"/>) switches it on and off. While it runs the hair
/// chains are dropped from the motion (<see cref="StrandRules.WithoutHairGroups"/>); a first-person body never runs it.
/// </summary>
public partial class Figure
{
    /// <summary>The source of the current body (null: low tier, no <c>hair_strands</c>, a pool model or portrait).</summary>
    public StrandHairSource? StrandSource { get; private set; }
    /// <summary>The bound handle, null before <see cref="PrepareStrandHair"/> succeeded.</summary>
    public StrandHairModifier? StrandHair { get; private set; }
    private bool _strandRefused;
    private bool _strandOn;
    /// <summary>Why the binding was refused (the log line), null otherwise.</summary>
    public string? StrandRefusal { get; private set; }
    /// <summary>Where the refusal is logged (the manager's log).</summary>
    public Action<string>? StrandLog { get; set; }

    /// <summary>Runs per strand now.</summary>
    public bool StrandRunning => _strandOn;
    /// <summary>What the figure budget adds up (<c>strandCostMs</c>): the measured EMA, the whole budget without a handle.</summary>
    public double StrandCostMs => StrandHair?.Driver.CostMs ?? StrandBudget.Limits.BudgetMs;

    /// <summary>The payload the secondary motion runs on: without the hair groups while the strands run.</summary>
    private MotionPayload? EffectiveMotion => _strandOn ? StrandRules.WithoutHairGroups(Motion) : Motion;

    /// <summary>A new body's source (null = none); the old handle is released first.</summary>
    public void SetStrandSource(StrandHairSource? source)
    {
        DropStrandHair();
        StrandSource = source;
        _strandRefused = false;
        StrandRefusal = null;
    }

    /// <summary>
    /// <c>prepareStrandHair</c>: bind the record once it has loaded (the first call starts the download): true when a
    /// handle is ready; false without a source, at the low tier, while loading, or for good when the record is none or
    /// does not belong to the mesh (logged once).
    /// </summary>
    public bool PrepareStrandHair()
    {
        if (StrandHair is not null) return true;
        if (_strandRefused || LoadedTier != FigureTier.Full || StrandSource is not { } src || Skeleton is null || Body is null) return false;
        var (state, record) = src.Record();
        if (state == StrandRecordState.Pending) return false;
        StrandHairModifier? handle = null;
        string why = "no record";
        if (record is not null) handle = StrandHairModifier.TryCreate(Body, Skeleton, this, src.Primitives, record, out why);
        if (handle is null)
        {
            _strandRefused = true;
            StrandRefusal = why;
            if (record is not null)
                StrandLog?.Invoke($"[figures] {record.ItemId}: the hair mesh does not carry the strand binding of record "
                                  + $"{record.FitSha256[..Math.Min(12, record.FitSha256.Length)]} ({why}) — the hair stays on its chains");
            return false;
        }
        handle.Manual = SecondaryManual;
        StrandHair = handle;
        GarmentPush?.KeepOrder();
        return true;
    }

    /// <summary><c>setStrandHair</c>: on only with a ready handle and not in first person; the chains leave the motion
    /// while it runs and come back when it stops (the next secondary tick sees the changed revision).</summary>
    public void SetStrandHair(bool on)
    {
        bool want = on && StrandHair is not null && !IsFirstPerson;
        if (want == _strandOn || StrandHair is not { } handle) return;
        _strandOn = want;
        handle.SetEnabled(want);
        // figureRuntime.ts setStrandHair: the strand-run hair leaves the GPU push while it runs (excludeMesh).
        GarmentPush?.Exclude(handle.Mesh, want);
    }

    private void DropStrandHair()
    {
        if (_strandOn && StrandHair is { } running) GarmentPush?.Exclude(running.Mesh, false);
        StrandHair?.Release();
        StrandHair = null;
        _strandOn = false;
    }

    /// <summary>This frame's freeze / manual stepping for the strand modifier (from the secondary tick).</summary>
    private void TickStrand()
    {
        if (StrandHair is not { } handle) return;
        handle.Frozen = SecondaryFrozen;
        handle.Manual = SecondaryManual;
    }
}
