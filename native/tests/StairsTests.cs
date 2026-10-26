using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// client3d/src/game/stairs.ts on the native world flights — the hand cases of client3d/scripts/smoke_walk_math.mjs
/// ("stairChain", "stairY", "stairLegTo / stairLegs", "rideStep"), copied verbatim: no shared vector file carries this
/// module yet (see the Task 30 report). The flight is the § 0 hand calculation: at [2, −2], dir +x, run 15 · 0.26 =
/// 3.9, width 1.2; foot landing [1.5, 0.01, −2] on storey 0, head landing [6.4, 3.09, −2] on storey 1.
/// </summary>
public class StairsTests
{
    private static StairLanding L(int level, double x, double y, double z) => new() { Level = level, Pos = new Vec3(x, y, z) };

    private static StairLink Flight(StairLanding foot, StairLanding head, P2 at, P2 dir, double runM = 3.9, double widthM = 1.2)
        => new() { Id = 0, Foot = foot, Head = head, At = at, Dir = dir, RunM = runM, WidthM = widthM, Footprint = Array.Empty<P2>() };

    // smoke "stairChain": A 0 → 1, B 1 → 2 (the runs do not matter to the chain).
    private static readonly StairLink A = Flight(L(0, 1.5, 0.01, -2), L(1, 6.4, 3.09, -2), new P2(2, -2), new P2(1, 0));
    private static readonly StairLink B = Flight(L(1, 1.5, 3.09, 2), L(2, 6.4, 6.09, 2), new P2(2, 2), new P2(1, 0));

    [Fact]
    public void ChainWalksNearThenFarEnd()
    {
        Assert.Equal(new[] { A.Foot, A.Head }, Stairs.Chain(new[] { A }, 0, 1)!);              // 0 → 1 walks foot then head
        Assert.Equal(new[] { A.Head, A.Foot }, Stairs.Chain(new[] { A }, 1, 0)!);              // 1 → 0 walks head then foot
        var up2 = Stairs.Chain(new[] { A, B }, 0, 2)!;
        Assert.Equal(new[] { A.Foot, A.Head, B.Foot, B.Head }, up2);                           // 0 → 2 chains both flights
        Assert.Equal(new[] { 3.09, 3.09 }, new[] { up2[1].Pos.Y, up2[2].Pos.Y });              // the landing pair on storey 1
        Assert.Equal(new[] { B.Head, B.Foot, A.Head, A.Foot }, Stairs.Chain(new[] { A, B }, 2, 0)!);
        Assert.Equal(new[] { A.Foot, A.Head, B.Foot, B.Head }, Stairs.Chain(new[] { B, A }, 0, 2)!);   // unordered list
        var a2 = Flight(L(0, -1.5, 0.01, 4), L(1, -6.4, 3.09, 4), new P2(-2, 4), new P2(-1, 0));
        Assert.Equal(new[] { A.Foot, A.Head }, Stairs.Chain(new[] { A, a2 }, 0, 1)!);          // the first one wins
        Assert.Equal(new[] { a2.Foot, a2.Head }, Stairs.Chain(new[] { a2, A }, 0, 1)!);        // …list order, not geometry
        Assert.Null(Stairs.Chain(new[] { A }, 0, 2));                                          // a missing link: no chain
        Assert.Null(Stairs.Chain(new[] { B }, 2, 0));
        Assert.Null(Stairs.Chain(Array.Empty<StairLink>(), 0, 1));
        Assert.Empty(Stairs.Chain(new[] { A }, 1, 1)!);                                        // same storey walks nowhere
        Assert.Empty(Stairs.Chain(Array.Empty<StairLink>(), 0, 0)!);
        var c = Flight(L(-1, 1.5, -2.91, 0), L(0, 6.4, 0.01, 0), new P2(2, 0), new P2(1, 0));
        Assert.Equal(new[] { c.Foot, c.Head, A.Foot, A.Head }, Stairs.Chain(new[] { c, A }, -1, 1)!);   // the basement
    }

    // smoke "stairY": t = (x − 2) / 3.9, y = 0.01 + t · 3.08; the gate across is half the width, 0.6.
    private static readonly StairLink FlightA = A;

    [Fact]
    public void StairYIsTheRampAlongTheRun()
    {
        Assert.Equal(0.01, Stairs.StairY(FlightA, 2, -2));
        Assert.Equal(1.0366666666666666, Stairs.StairY(FlightA, 3.3, -2)!.Value, 1e-12);
        Assert.Equal(1.55, Stairs.StairY(FlightA, 3.95, -2)!.Value, 1e-12);
        Assert.Equal(3.09, Stairs.StairY(FlightA, 5.9, -2)!.Value, 1e-12);
        Assert.Equal(3.09, Stairs.StairY(FlightA, 6.4, -2));                                   // the head landing, clamped
        Assert.Equal(0.01, Stairs.StairY(FlightA, 1.0, -2));                                   // the foot landing, clamped
        Assert.Equal(1.55, Stairs.StairY(FlightA, 3.95, -1.5)!.Value, 1e-12);                  // half a step width inside
        Assert.Equal(1.55, Stairs.StairY(FlightA, 3.95, -2.5)!.Value, 1e-12);
        Assert.Null(Stairs.StairY(FlightA, 3.95, -1.25));                                      // a quarter width past the rim
        Assert.Null(Stairs.StairY(FlightA, 3.95, 0));
        var b = Flight(L(1, 2, 3.09, 1.5), L(2, 2, 6.09, 6.4), new P2(2, 2), new P2(0, 1));
        Assert.Equal(4.59, Stairs.StairY(b, 2, 3.95)!.Value, 1e-12);                           // a flight along +z
        Assert.Null(Stairs.StairY(b, 2.61, 3.95));
        var longDir = Flight(FlightA.Foot, FlightA.Head, FlightA.At, new P2(2, 0));
        Assert.Equal(1.55, Stairs.StairY(longDir, 3.95, -2)!.Value, 1e-12);                    // dir need not be unit
        Assert.Null(Stairs.StairY(Flight(FlightA.Foot, FlightA.Head, FlightA.At, FlightA.Dir, runM: 0), 3.95, -2));
        Assert.Null(Stairs.StairY(Flight(FlightA.Foot, FlightA.Head, FlightA.At, new P2(0, 0)), 3.95, -2));
    }

    // smoke "the RIDE": a stack — S0 the § 0 flight, S1 a copy one storey up over the same run.
    private static readonly StairLink S0 = FlightA;
    private static readonly StairLink S1 = Flight(L(1, 1.5, 3.09, -2), L(2, 6.4, 6.09, -2), new P2(2, -2), new P2(1, 0));

    [Fact]
    public void LegsArePickedByLanding()
    {
        var up = Stairs.LegTo(new[] { S0, S1 }, S0.Head)!;
        Assert.Equal(0.01, up.Flight.Foot.Pos.Y);
        Assert.Equal(0.01, up.Start.Pos.Y);
        Assert.Equal(3.09, up.End.Pos.Y);
        var upper = Stairs.LegTo(new[] { S0, S1 }, S1.Head)!;
        Assert.Equal(3.09, upper.Flight.Foot.Pos.Y);
        Assert.Equal(3.09, upper.Start.Pos.Y);
        var down = Stairs.LegTo(new[] { S0, S1 }, S0.Foot)!;
        Assert.Equal(0.01, down.End.Pos.Y);
        Assert.Equal(3.09, down.Start.Pos.Y);
        Assert.Equal(3.09, down.Flight.Head.Pos.Y);
        Assert.Null(Stairs.LegTo(new[] { S0, S1 }, L(0, 99, 0, 0)));

        var chain = Stairs.Chain(new[] { S0, S1 }, 0, 2)!;
        Assert.Equal(4, chain.Count);
        var legs = Stairs.Legs(new[] { S0, S1 }, chain);
        Assert.Equal(2, legs.Count);
        Assert.Equal(3.09, legs[0].Flight.Head.Pos.Y);
        Assert.Equal(6.09, legs[1].Flight.Head.Pos.Y);                                         // the UPPER flight
        Assert.Equal(3.09, legs[1].Start.Pos.Y);
        var downLegs = Stairs.Legs(new[] { S0, S1 }, Stairs.Chain(new[] { S0, S1 }, 2, 0)!);
        Assert.Equal(2, downLegs.Count);
        Assert.Equal(6.09, downLegs[0].Flight.Head.Pos.Y);
        Assert.Equal(3.09, downLegs[0].End.Pos.Y);
        Assert.Equal(0.01, downLegs[1].End.Pos.Y);
        Assert.Empty(Stairs.Legs(new[] { S0 }, new[] { S1.Foot, S1.Head }));
    }

    [Fact]
    public void RideArmsAtTheStartAndHandsOverAtTheEnd()
    {
        Assert.Equal(0.4, Stairs.RideArriveM);
        Assert.True(Stairs.RideArriveM < 0.5);
        var ride = new StairRide { Legs = Stairs.Legs(new[] { S0, S1 }, Stairs.Chain(new[] { S0, S1 }, 0, 2)!) };
        RideStepResult At(double x, double y, double z)
        {
            var step = Stairs.RideStep(ride, x, y, z);
            ride.Leg = step.Leg;
            ride.Armed = step.Armed;
            return step;
        }
        var room = At(0, 0.01, -2);
        Assert.Null(room.Y);
        Assert.Equal((0, false, false), (room.Leg, room.Armed, room.Done));
        var foot = At(1.5, 0.01, -2);
        Assert.True(foot.Armed);
        Assert.Equal(0.01, foot.Y);
        Assert.Equal(1.55, At(3.95, 1.55, -2).Y!.Value, 1e-12);
        var mid = At(6.4, 3.09, -2);
        Assert.Equal((1, false, false), (mid.Leg, mid.Armed, mid.Done));
        Assert.Null(mid.Y);
        Assert.Null(At(3.95, 3.09, -2).Y);                                                     // the walk back lifts nobody
        var foot2 = At(1.5, 3.09, -2);
        Assert.True(foot2.Armed);
        Assert.Equal(3.09, foot2.Y);
        Assert.Equal(4.59, At(3.95, 4.59, -2).Y!.Value, 1e-12);
        var end = At(6.4, 6.09, -2);
        Assert.True(end.Done);
        Assert.Null(end.Y);

        var solo = new StairRide { Legs = new[] { Stairs.LegTo(new[] { S0, S1 }, S0.Head)! }, Armed = true };
        Assert.Equal(1.55, Stairs.RideStep(solo, 3.95, 1.55, -2).Y!.Value, 1e-12);
        Assert.Null(Stairs.RideStep(solo, 3.95, 1.55, -1.0).Y);
        // Not in the smoke (a native addition, stairs.ts' own comment): only an ARMED leg can end — a figure standing on the
        // head landing of a leg it never started (unarmed) keeps the leg, answers nothing and is not done.
        var unarmed = new StairRide { Legs = new[] { Stairs.LegTo(new[] { S0, S1 }, S0.Head)! } };
        var early = Stairs.RideStep(unarmed, 6.4, 3.09, -2);
        Assert.Equal((0, false, false, (double?)null), (early.Leg, early.Armed, early.Done, early.Y));
        var descent = new StairRide { Legs = new[] { Stairs.LegTo(new[] { S0, S1 }, S0.Foot)! }, Armed = true };
        Assert.Equal(1.55, Stairs.RideStep(descent, 3.95, 1.55, -2).Y!.Value, 1e-12);
        Assert.True(Stairs.RideStep(descent, 1.5, 0.01, -2).Done);
    }
}
