using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>One clip's outcome of <see cref="FootLockMeasure.Relock"/> (footLockMeasure.ts <c>RelockReport</c>).</summary>
public sealed record RelockReport
{
    public required string Clip { get; init; }
    /// <summary><c>"rig"</c> (rebuilt on this rig) or <c>"imported"</c>.</summary>
    public required string Used { get; init; }
    /// <summary>Why the import was kept: no foot bones / no full contact / imported holds better.</summary>
    public string? Reason { get; init; }
    public double DriftCm { get; init; }
    public double RebuiltDriftCm { get; init; }
    public double ImportedDriftCm { get; init; }
    public double PinnedCm { get; init; }
    public double LiftCm { get; init; }
    /// <summary><c>"no leg bones"</c> when the clip was measured but no foot pinned.</summary>
    public string? PinReason { get; init; }
    /// <summary>End of the path in use, clip frame (x, z), cm at the nominal scale.</summary>
    public (double X, double Z) Travel { get; init; }
    /// <summary>ψ at the end in degrees (0 = no turn); null when none was measured (<see cref="TurnReason"/>).</summary>
    public double? TurnDeg { get; init; }
    public string? TurnReason { get; init; }
}

/// <summary>
/// THE FOOT LOCK PER RIG — client3d/src/scene/footLockMeasure.ts <c>relockRootPaths</c> on a Godot-free probe
/// (<see cref="ProbeRig"/> + <see cref="RigPose"/> in place of three's skeleton clone and mixer). Vectors
/// shared/test-vectors/foot_lock_measure.json (hand derivations: client3d/scripts/smoke_foot_lock_measure.mjs).
///
/// Per clip that carries a travel: the travel rebuilt on the rig's own skeleton (<see cref="FootLock"/>) where it
/// drifts at least <see cref="RelockMinGainCm"/> less than the import, the planted feet pinned by leg IK
/// (<see cref="LegPin"/>, DOWN + HOLD, written as new UpLeg/Leg/Foot tracks), the bridge's height measured
/// (<see cref="BridgeLiftSpec"/>), and last the pelvis turn taken out of the hips tracks and stored
/// (<see cref="RootTurn"/>). Units: the probe measures in template units, <c>unitsPerCm = 1 / (100 · scale)</c>.
/// The rig is never mutated; the clips are (tracks replaced, stores set), exactly like three's clips and WeakMaps.
/// </summary>
public static class FootLockMeasure
{
    /// <summary>How much LESS the rebuilt path must drift than the imported one before it replaces it, cm.</summary>
    public const double RelockMinGainCm = 0.1;
    /// <summary>Sample rate for a clip without a hips position track, fps.</summary>
    public const double FallbackFps = 30;
    /// <summary>Below this |ψ| on every sample a clip has no turn to hand over, rad.</summary>
    public const double TurnNoneRad = 1e-6;

    private static readonly string[] ToeEnds = { "lefttoe_end", "righttoe_end", "lefttoeend", "righttoeend" };
    private const string ImportedBetter = "imported holds better";

    private sealed record Leg(string Ankle, string Ball, string Upper, string Lower);

    private static readonly Leg[] Legs =
    {
        new("LeftFoot", "LeftToeBase", "leftupleg", "leftleg"),
        new("RightFoot", "RightToeBase", "rightupleg", "rightleg"),
    };

    private sealed record LegBones(int Upper, int Lower, int Foot);

    private sealed record LegFrame(V3 Hip, V3 Knee, V3 Ankle, Quat WUpperParent, Quat WUpper, Quat WLowerParent, Quat WLower,
                                   Quat WFootParent, Quat WFoot, Quat[] Local);

    private sealed record TurnFrame(V3 Left, V3 Right, Affine Hips, Affine Parent);

    private static string F1(double v) => v.ToString("F1", CultureInfo.InvariantCulture);

    /// <summary>The sample times: the keys of the clip's hips POSITION track (≥ 2), or a uniform 30 fps over the duration.</summary>
    public static double[] SampleTimes(ProbeClip clip)
    {
        var hips = clip.Tracks.FirstOrDefault(t => t.Prop == "position" && BoneNames.Norm(t.Node).EndsWith("hips", StringComparison.Ordinal));
        if (hips is not null && hips.Times.Length >= 2) return hips.Times.Select(t => (double)t).ToArray();
        int n = Math.Max(2, (int)Math.Floor(clip.Duration * FallbackFps + 0.5) + 1);
        return Enumerable.Range(0, n).Select(i => clip.Duration * i / (n - 1)).ToArray();
    }

    private static (double X, double Z) TravelEndCm(RootPath path, double unitsPerCm)
    {
        int n = path.Times.Length;
        if (n == 0) return (0, 0);
        var end = BridgeTravel.TravelAt(path, path.Times[n - 1]);
        return (end.X / unitsPerCm, end.Z / unitsPerCm);
    }

    /// <summary>The ONE summary line of a model (footLockMeasure.ts <c>summaryLine</c>).</summary>
    public static string SummaryLine(IReadOnlyList<RelockReport> reports)
    {
        static string TurnPart(RelockReport r)
        {
            if (r.TurnDeg is { } d) return Math.Abs(d) < 0.05 ? "" : $", turn {F1(d)}°";
            return r.TurnReason is not null ? $", turn: none ({r.TurnReason})" : "";
        }
        var parts = reports.Select(r =>
        {
            string head;
            if (r.Used == "rig") head = $"{r.Clip} {F1(r.RebuiltDriftCm)} cm (imported {F1(r.ImportedDriftCm)})";
            else if (r.Reason == ImportedBetter) head = $"{r.Clip} imported {F1(r.ImportedDriftCm)} cm (rig {F1(r.RebuiltDriftCm)})";
            else return $"{r.Clip} imported ({r.Reason}){TurnPart(r)}";
            if (r.PinReason is not null) return $"{head}, not pinned ({r.PinReason}){TurnPart(r)}";
            if (r.PinnedCm < 0.05 && r.LiftCm < 0.05) return $"{head}{TurnPart(r)}";
            return $"{head}, held {F1(r.PinnedCm)} cm, lifted {F1(r.LiftCm)} cm → {F1(r.DriftCm)} cm{TurnPart(r)}";
        });
        return $"foot lock per rig — {string.Join(", ", parts)}";
    }

    /// <summary>
    /// <c>relockRootPaths(clips, template, unitsPerCm, log, options)</c>: every clip with a <see cref="ProbeClip.Path"/>
    /// re-locked, pinned, lifted and turned on <paramref name="rig"/>; returns one report per such clip and logs ONE
    /// summary line when any was measured. <paramref name="turn"/> false = the options' <c>{ turn: false }</c>.
    /// </summary>
    public static List<RelockReport> Relock(IReadOnlyList<ProbeClip> clips, ProbeRig rig, double unitsPerCm,
                                            Action<string>? log = null, bool turn = true)
    {
        var todo = clips.Where(c => c.Path is not null).ToList();
        var reports = new List<RelockReport>();
        if (todo.Count == 0 || !(unitsPerCm > 0)) return reports;

        var pose = new RigPose(rig);
        var byKey = rig.BonesByKey();
        int Key(string k) => byKey.TryGetValue(k, out int i) ? i : -1;
        var points = FootLock.ContactPoints.Select(p => Key(p.ToLowerInvariant())).ToArray();

        if (points.Any(b => b < 0))
        {
            foreach (var clip in todo)
                reports.Add(new RelockReport
                {
                    Clip = clip.Name, Used = "imported", Reason = "no foot bones",
                    Travel = TravelEndCm(clip.Path!, unitsPerCm), TurnDeg = null,
                });
            log?.Invoke(SummaryLine(reports));
            return reports;
        }
        var legs = LegBonesOf(rig, byKey);
        // The turn's bones and its pivot, the hips' REST point — read before the probe is posed by any clip.
        int hipsBone = Key("hips");
        if (hipsBone < 0) hipsBone = byKey.Where(e => e.Key.EndsWith("hips", StringComparison.Ordinal)).Select(e => e.Value).DefaultIfEmpty(-1).First();
        int leftUp = Key("leftupleg"), rightUp = Key("rightupleg");
        bool hasTurnBones = hipsBone >= 0 && leftUp >= 0 && rightUp >= 0;
        V3? pivotWorld = hasTurnBones ? pose.WorldPosition(hipsBone) : null;
        V3? pivotLocal = pivotWorld is { } pw ? RigMath.Apply(RigMath.Inverse(rig.Root), pw) : null;

        // Rest heights, cm: each point's bind-pose height over the lowest foot point (the four and the toe ends).
        var restY = points.Select(b => pose.WorldPosition(b).Y).ToArray();
        var toeEnds = ToeEnds.Select(Key).Where(i => i >= 0).ToArray();
        double floorY = restY.Concat(toeEnds.Select(b => pose.WorldPosition(b).Y)).Min();
        var rest = new Dictionary<string, double>();
        for (int i = 0; i < points.Length; i++) rest[FootLock.ContactPoints[i]] = (restY[i] - floorY) / unitsPerCm;
        var footPoints = points.Concat(toeEnds).ToArray();
        double floorCm = floorY / unitsPerCm;

        V3 CmOf(int b)
        {
            var p = pose.WorldPosition(b);
            return new V3(p.X / unitsPerCm, p.Y / unitsPerCm, p.Z / unitsPerCm);
        }
        Dictionary<string, List<V3>> EmptyTracks() => FootLock.ContactPoints.ToDictionary(p => p, _ => new List<V3>());
        void ReadPoints(Dictionary<string, List<V3>> into)
        {
            for (int i = 0; i < points.Length; i++)
            {
                var p = CmOf(points[i]);
                into[FootLock.ContactPoints[i]].Add(new V3(p.X, p.Y - floorCm, p.Z));
            }
        }
        static Dictionary<string, V3[]> Frozen(Dictionary<string, List<V3>> t) => t.ToDictionary(e => e.Key, e => e.Value.ToArray());

        void StoreLift(ProbeClip clip, double[] times, double firstContactS)
        {
            double lowest = double.PositiveInfinity;
            pose.Pose(clip, times[^1]);
            foreach (int b in footPoints) lowest = Math.Min(lowest, pose.WorldPosition(b).Y);
            if (double.IsFinite(lowest)) clip.Lift = new BridgeLiftSpec(floorY - lowest, firstContactS);
        }

        foreach (var clip in todo)
        {
            var imported = clip.Path!;
            var times = SampleTimes(clip);
            double span = times[^1] - times[0];
            double fps = span > 0 ? (times.Length - 1) / span : FallbackFps;

            var tracksL = EmptyTracks();
            var legFrames = Legs.Select(_ => new List<LegFrame>()).ToArray();
            var turnFrames = new List<TurnFrame>();
            (double? Deg, string? Reason) HandTurnOver()
            {
                if (!hasTurnBones || pivotWorld is null || pivotLocal is null) return (null, "no hip bones");
                if (!turn) return (null, "switched off");
                return (BakeTurn(clip, times, turnFrames, rig.Nodes[hipsBone].Name, pivotWorld.Value, pivotLocal.Value), null);
            }
            foreach (double t in times)
            {
                pose.Pose(clip, t);
                ReadPoints(tracksL);
                if (hasTurnBones)
                    turnFrames.Add(new TurnFrame(pose.WorldPosition(leftUp), pose.WorldPosition(rightUp), pose.World(hipsBone),
                                                 pose.World(rig.Nodes[hipsBone].Parent)));
                if (legs is not null)
                    for (int s = 0; s < legs.Length; s++)
                    {
                        var leg = legs[s];
                        legFrames[s].Add(new LegFrame(
                            CmOf(leg.Upper), CmOf(leg.Lower), CmOf(leg.Foot),
                            pose.WorldRotation(rig.Nodes[leg.Upper].Parent), pose.WorldRotation(leg.Upper),
                            pose.WorldRotation(rig.Nodes[leg.Lower].Parent), pose.WorldRotation(leg.Lower),
                            pose.WorldRotation(rig.Nodes[leg.Foot].Parent), pose.WorldRotation(leg.Foot),
                            new[] { pose.LocalRotation(leg.Upper), pose.LocalRotation(leg.Lower), pose.LocalRotation(leg.Foot) }));
                    }
            }
            var tracks = Frozen(tracksL);
            var ground = FootLock.GroundHeights(tracks, rest);
            var weights = FootLock.ContactWeights(tracks, ground, fps);
            var importedCm = times.Select(t =>
            {
                var o = BridgeTravel.TravelAt(imported, t);
                return (o.X / unitsPerCm, o.Z / unitsPerCm);
            }).ToList();
            bool anyFull = weights.Values.Any(w => Enumerable.Range(0, Math.Max(0, w.Length - 1)).Any(f => Math.Min(w[f], w[f + 1]) >= FootLock.Full));
            if (!anyFull)
            {
                StoreLift(clip, times, clip.Duration);
                var (deg, why) = HandTurnOver();
                reports.Add(new RelockReport
                {
                    Clip = clip.Name, Used = "imported", Reason = "no full contact",
                    Travel = TravelEndCm(imported, unitsPerCm), TurnDeg = deg, TurnReason = why,
                });
                continue;
            }
            var path = FootLock.FootLockPath(tracks, weights);
            double rebuiltDriftCm = FootLock.MaxPlantedDrift(tracks, weights, path);
            double importedDriftCm = FootLock.MaxPlantedDrift(tracks, weights, importedCm);
            bool useRig = rebuiltDriftCm < importedDriftCm - RelockMinGainCm;
            var inUse = useRig ? path : importedCm;
            (double X, double Z) travel;
            if (useRig)
            {
                var xz = new float[path.Count * 2];
                for (int i = 0; i < path.Count; i++)
                {
                    xz[i * 2] = (float)(path[i].X * unitsPerCm);
                    xz[i * 2 + 1] = (float)(path[i].Z * unitsPerCm);
                }
                clip.Path = new RootPath(times.Select(t => (float)t).ToArray(), xz);
                travel = path[^1];
            }
            else travel = TravelEndCm(imported, unitsPerCm);

            double driftCm = useRig ? rebuiltDriftCm : importedDriftCm;
            double pinnedCm = 0, liftCm = 0;
            var playedWeights = weights;
            if (legs is not null && PinLegs(clip, times, rig, legs, legFrames, tracks, ground, rest, weights, inUse, fps))
            {
                var afterL = EmptyTracks();
                foreach (double t in times)
                {
                    pose.Pose(clip, t);
                    ReadPoints(afterL);
                }
                var after = Frozen(afterL);
                driftCm = FootLock.MaxPlantedDrift(after, weights, inUse);
                playedWeights = FootLock.ContactWeights(after, ground, fps);
                foreach (var leg in Legs)
                {
                    var a = after[leg.Ankle];
                    var o = tracks[leg.Ankle];
                    for (int f = 0; f < a.Length; f++)
                    {
                        double dx = a[f].X - o[f].X, dz = a[f].Z - o[f].Z;
                        pinnedCm = Math.Max(pinnedCm, Math.Sqrt(dx * dx + dz * dz));
                        liftCm = Math.Max(liftCm, Math.Abs(a[f].Y - o[f].Y));
                    }
                }
            }
            StoreLift(clip, times, FirstFullContact(playedWeights, times, clip.Duration));
            var (turnDeg, turnWhy) = HandTurnOver();
            reports.Add(new RelockReport
            {
                Clip = clip.Name, Used = useRig ? "rig" : "imported", Reason = useRig ? null : ImportedBetter,
                PinReason = legs is null ? "no leg bones" : null,
                DriftCm = driftCm, RebuiltDriftCm = rebuiltDriftCm, ImportedDriftCm = importedDriftCm,
                PinnedCm = pinnedCm, LiftCm = liftCm, Travel = travel, TurnDeg = turnDeg, TurnReason = turnWhy,
            });
        }
        log?.Invoke(SummaryLine(reports));
        return reports;
    }

    /// <summary>Both legs' chains (UpLeg → … → Leg → … → Foot), or null when a bone is missing.</summary>
    private static LegBones[]? LegBonesOf(ProbeRig rig, Dictionary<string, int> byKey)
    {
        var output = new List<LegBones>();
        foreach (var leg in Legs)
        {
            if (!byKey.TryGetValue(leg.Upper, out int upper) || !byKey.TryGetValue(leg.Lower, out int lower)
                || !byKey.TryGetValue(leg.Ankle.ToLowerInvariant(), out int foot)
                || !rig.IsBelow(lower, upper) || !rig.IsBelow(foot, lower)) return null;
            output.Add(new LegBones(upper, lower, foot));
        }
        return output.ToArray();
    }

    /// <summary>Clip time of the first sample with any contact point in FULL contact, or the duration.</summary>
    private static double FirstFullContact(Dictionary<string, double[]> weights, double[] times, double duration)
    {
        for (int f = 0; f < times.Length; f++)
            if (weights.Values.Any(w => f < w.Length && w[f] >= FootLock.Full)) return times[f];
        return duration;
    }

    /// <summary>
    /// THE TURN of one clip: ψ per sample from the UpLegs, the hips tracks rewritten on the sample times with the pose
    /// turned by −ψ about the vertical through the hips' rest point, the turn stored; ψ at the end in degrees (0, and
    /// the clip untouched, when it never turns).
    /// </summary>
    private static double BakeTurn(ProbeClip clip, double[] times, List<TurnFrame> frames, string hipsName, V3 pivotWorld, V3 pivotLocal)
    {
        int n = times.Length;
        var yaw = BridgeHeading.HeadingTrack(frames.Select(f => f.Left).ToList(), frames.Select(f => f.Right).ToList());
        if (!yaw.Any(y => Math.Abs(y) > TurnNoneRad)) return 0;
        var pos = new float[n * 3];
        var quat = new float[n * 4];
        var toPivot = Affine.Translation(-pivotWorld.X, 0, -pivotWorld.Z);
        var fromPivot = Affine.Translation(pivotWorld.X, 0, pivotWorld.Z);
        Quat? prev = null;
        for (int f = 0; f < n; f++)
        {
            // local' = parent⁻¹ · G · hipsWorld, G = the turn by −ψ about the pivot's vertical.
            var g = fromPivot.Times(RigMath.RotationY(-yaw[f])).Times(toPivot);
            var local = RigMath.Inverse(frames[f].Parent).Times(g).Times(frames[f].Hips);
            var (p, q, _) = RigMath.Decompose(local);
            if (prev is { } pq && RigMath.Dot(q, pq) < 0) q = new Quat(-q.X, -q.Y, -q.Z, -q.W);
            prev = q;
            pos[f * 3] = (float)p.X; pos[f * 3 + 1] = (float)p.Y; pos[f * 3 + 2] = (float)p.Z;
            quat[f * 4] = (float)q.X; quat[f * 4 + 1] = (float)q.Y; quat[f * 4 + 2] = (float)q.Z; quat[f * 4 + 3] = (float)q.W;
        }
        var keyTimes = times.Select(t => (float)t).ToArray();
        clip.ReplaceTrack(hipsName, "position", keyTimes, pos);
        clip.ReplaceTrack(hipsName, "quaternion", keyTimes, quat);
        clip.Turn = new RootTurn(keyTimes, yaw, pivotLocal);
        return yaw[n - 1] * 180 / Math.PI;
    }

    /// <summary>
    /// THE LEG PIN of one clip: per leg the DOWN and HOLD weights, per held run the held point and its anchor, per frame
    /// the IK — written as new UpLeg/Leg/Foot tracks on the sample times. Returns whether any frame was moved.
    /// </summary>
    private static bool PinLegs(ProbeClip clip, double[] times, ProbeRig rig, LegBones[] legs, List<LegFrame>[] legFrames,
                                Dictionary<string, V3[]> tracks, Dictionary<string, double> ground, Dictionary<string, double> rest,
                                Dictionary<string, double[]> weights, IReadOnlyList<(double X, double Z)> path, double fps)
    {
        int n = times.Length;
        var keyTimes = times.Select(t => (float)t).ToArray();
        bool pinned = false;
        for (int s = 0; s < Legs.Length; s++)
        {
            var leg = Legs[s];
            var frames = legFrames[s];
            var ankle = tracks[leg.Ankle];
            var ball = tracks[leg.Ball];
            var sole = LegPin.SoleDown(ankle.Select(p => p.Y).ToList(), ball.Select(p => p.Y).ToList(), rest[leg.Ankle] - rest[leg.Ball]);
            double[] FootWeight(Dictionary<string, double[]> w)
            {
                var a = w.TryGetValue(leg.Ankle, out var wa) ? wa : Array.Empty<double>();
                var b = w.TryGetValue(leg.Ball, out var wb) ? wb : Array.Empty<double>();
                return Enumerable.Range(0, n).Select(f => sole[f] ? Math.Max(f < a.Length ? a[f] : 0, f < b.Length ? b[f] : 0) : 0).ToArray();
            }
            var down = LegPin.PinRuns(FootWeight(weights), fps);
            if (!down.Any(w => w > 0)) continue;
            double ga = ground.TryGetValue(leg.Ankle, out var g1) ? g1 : double.NaN;
            double gb = ground.TryGetValue(leg.Ball, out var g2) ? g2 : double.NaN;
            var lift = Enumerable.Range(0, n).Select(f =>
            {
                double v = Math.Min(ankle[f].Y - ga, ball[f].Y - gb);
                return double.IsFinite(v) ? v : 0;
            }).ToArray();
            var lowered = new Dictionary<string, V3[]>
            {
                [leg.Ankle] = ankle.Select((q, f) => new V3(q.X, q.Y - down[f] * lift[f], q.Z)).ToArray(),
                [leg.Ball] = ball.Select((q, f) => new V3(q.X, q.Y - down[f] * lift[f], q.Z)).ToArray(),
            };
            var after = FootLock.ContactWeights(lowered, ground, fps);
            var hold = LegPin.PinRuns(FootWeight(after), fps);
            var anchor = new (double X, double Z)?[n];
            var pivot = new double[n];
            (double X, double Z) PivotAt(int f, double sBall)
                => (ankle[f].X + sBall * (ball[f].X - ankle[f].X), ankle[f].Z + sBall * (ball[f].Z - ankle[f].Z));
            for (int f = 0; f < n;)
            {
                if (!(hold[f] > 0)) { f++; continue; }
                int a = f;
                while (f + 1 < n && hold[f + 1] > 0) f++;
                int b = f++;
                double ca = 0, cb = 0;
                for (int g = a; g <= b; g++)
                {
                    if (hold[g] < FootLock.Full) continue;
                    ca += after[leg.Ankle][g];
                    cb += after[leg.Ball][g];
                }
                double sBall = ca + cb > 0 ? cb / (ca + cb) : 0;
                double sx = 0, sz = 0;
                int k = 0;
                for (int g = a; g <= b; g++)
                {
                    pivot[g] = sBall;
                    if (hold[g] < FootLock.Full) continue;
                    var pt = PivotAt(g, sBall);
                    sx += pt.X + path[g].X;
                    sz += pt.Z + path[g].Z;
                    k++;
                }
                if (k > 0) for (int g = a; g <= b; g++) anchor[g] = (sx / k, sz / k);
            }
            var values = new[] { new float[n * 4], new float[n * 4], new float[n * 4] };
            var prev = new Quat?[3];
            bool changed = false;
            for (int g = 0; g < n; g++)
            {
                var fr = frames[g];
                var local = fr.Local;
                double w = anchor[g] is not null ? hold[g] : 0;
                var at = anchor[g] ?? (0, 0);
                if (w > 0 || down[g] > 0)
                {
                    var pt = PivotAt(g, pivot[g]);
                    var target = new V3(fr.Ankle.X + w * (at.X - path[g].X - pt.X),
                                        fr.Ankle.Y - down[g] * lift[g],
                                        fr.Ankle.Z + w * (at.Z - path[g].Z - pt.Z));
                    var ik = LegPin.TwoBoneIk(fr.Hip, fr.Knee, fr.Ankle, target, fr.Knee);
                    var du = ik.Upper.ToThree();
                    var dl = ik.Lower.ToThree();
                    var dul = dl * du;
                    local = new[]
                    {
                        fr.WUpperParent.Inverse() * (du * fr.WUpper),
                        (du * fr.WLowerParent).Inverse() * (dul * fr.WLower),
                        (dul * fr.WFootParent).Inverse() * fr.WFoot,
                    };
                    changed = true;
                }
                for (int i = 0; i < 3; i++)
                {
                    var q = local[i];
                    if (prev[i] is { } pq && RigMath.Dot(q, pq) < 0) q = new Quat(-q.X, -q.Y, -q.Z, -q.W);
                    values[i][g * 4] = (float)q.X; values[i][g * 4 + 1] = (float)q.Y; values[i][g * 4 + 2] = (float)q.Z; values[i][g * 4 + 3] = (float)q.W;
                    prev[i] = q;
                }
            }
            if (!changed) continue;
            pinned = true;
            var bones = legs[s];
            clip.ReplaceTrack(rig.Nodes[bones.Upper].Name, "quaternion", keyTimes, values[0]);
            clip.ReplaceTrack(rig.Nodes[bones.Lower].Name, "quaternion", keyTimes, values[1]);
            clip.ReplaceTrack(rig.Nodes[bones.Foot].Name, "quaternion", keyTimes, values[2]);
        }
        return pinned;
    }
}
