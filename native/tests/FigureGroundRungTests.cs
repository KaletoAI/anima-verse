using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The three floor rungs of the tile ground ladder that have NO shared vector yet — <c>plateCeiling</c>,
/// <c>recipeFloorAt</c>, <c>declaredFloorAt</c> (client3d/src/game/ground.ts). Every case below is the hand case of
/// client3d/scripts/smoke_walk_math.mjs with its numbers copied verbatim (section "ground — ONE floor", "THE
/// STAIRWELL", "a DECLARED walk height"); the derivations live there. Extracting them into a vector file is the open
/// follow-up named in the Task 29 report.
/// </summary>
public class FigureGroundRungTests
{
    private static P2[] R(params (double X, double Z)[] pts) => pts.Select(p => new P2(p.X, p.Z)).ToArray();

    private static readonly P2[] KaiHouse = R((-4.5, -4.5), (6, -4.5), (6, 1.5), (-0.5, 1.5), (-0.5, 6), (-4.5, 6), (-4.5, -1),
                                              (-6.22, -1), (-6.25, -3.11), (-4.53, -3.13));
    private static readonly P2[] KaiBedroom = R((-6.25, -3.11), (-4.53, -3.13), (-4.5, -4.5), (6, -4.5), (6, 1.5), (-0.5, 1.5),
                                                (-4.5, 1.5), (-4.5, -1), (-6.22, -1));
    private static readonly WalkPlate[] KaiPlates = { new(2.88, KaiHouse), new(2.90, KaiBedroom) };

    [Fact]
    public void PlateCeiling()
    {
        Assert.Equal(1.2, FigureGround.PlateCeiling(null), 9);
        Assert.Equal(0.90, FigureGround.PlateCeiling(-0.30), 9);
        Assert.Equal(4.4, FigureGround.PlateCeiling(3.2), 9);
        Assert.Equal(1.2, FigureGround.PlateCeiling(0), 9);
    }

    [Fact]
    public void RecipeFloorOnStoreyZeroIsNone()
    {
        double ceiling = FigureGround.PlateCeiling(-0.30);
        Assert.Null(FigureGround.RecipeFloorAt(KaiPlates, 0.75, -1.5, ceiling));
        Assert.Null(FigureGround.RecipeFloorAt(KaiPlates, -2.5, 3.75, ceiling));
        Assert.Null(FigureGround.RecipeFloorAt(KaiPlates, -5.8, -2.0, ceiling));
        Assert.Null(FigureGround.RecipeFloorAt(KaiPlates, 3.7, 4.6, ceiling));
        Assert.Null(FigureGround.RecipeFloorAt(KaiPlates, 6.9, -6.5, ceiling));
        Assert.Equal(2.90, FigureGround.RecipeFloorAt(KaiPlates, 0.75, -1.5, 4.0));
        Assert.Equal(2.88, FigureGround.RecipeFloorAt(KaiPlates, -2, 4.0, 4.0));
        Assert.Null(FigureGround.RecipeFloorAt(new List<WalkPlate>(), 0, 0, 1.2));
        Assert.Null(FigureGround.RecipeFloorAt(null, 0, 0, 1.2));
    }

    [Fact]
    public void RecipeFloorHoleIsNotFloor()
    {
        var hole = R((2, -2.6), (6.85, -2.6), (6.85, -1.4), (2, -1.4));
        var contour = R((-8, -8), (8, -8), (8, 8), (-8, 8));
        var hall = R((1, -4), (5, -4), (5, 0), (1, 0));
        var cut = new[] { new WalkPlate(3.08, contour, new[] { hole }), new WalkPlate(3.10, hall, new[] { hole }) };
        const double up = 4.5;
        Assert.Null(FigureGround.RecipeFloorAt(cut, 3.0, -2.0, up));
        Assert.Equal(3.10, FigureGround.RecipeFloorAt(cut.Select(p => p with { Holes = new List<IReadOnlyList<P2>>() }), 3.0, -2.0, up));
        Assert.Equal(3.10, FigureGround.RecipeFloorAt(cut, 3.0, -1.0, up));
        Assert.Equal(3.10, FigureGround.RecipeFloorAt(cut, 3.0, -3.0, up));
        Assert.Equal(3.10, FigureGround.RecipeFloorAt(cut, 1.9, -2.0, up));
        Assert.Equal(3.08, FigureGround.RecipeFloorAt(cut, 6.9, -2.0, up));
        Assert.Null(FigureGround.RecipeFloorAt(cut, 6.0, -2.0, up));
        Assert.Equal(3.08, FigureGround.RecipeFloorAt(new[] { new WalkPlate(3.08, contour, new List<IReadOnlyList<P2>>()),
                                                              new WalkPlate(3.10, hall, new[] { hole }) }, 3.0, -2.0, up));
        Assert.Equal(3.08, FigureGround.RecipeFloorAt(new[] { new WalkPlate(3.08, contour) }, 3.0, -2.0, up));
    }

    [Fact]
    public void DeclaredFloor()
    {
        var hut = R((-27.56, 10.43), (-19.8, 10.23), (-18.64, 15.37), (-24.15, 16.61), (-26.81, 13.67));
        const double hutWalk = 0.00 + 0.02 + (-0.30) + 0.35;   // diorama bottom_y −0.28 + walk_y 0.35
        var lake = new[] { new DeclaredFloor("d5535ee7", hutWalk, hut) };
        Assert.Equal(0.07, FigureGround.DeclaredFloorAt(lake, -21.28, 13.12)!.Value, 9);
        Assert.Equal(0.08, FigureGround.DeclaredFloorAt(lake, -21.28, 13.12)!.Value + FigureGround.WalkClearanceM, 9);
        Assert.Equal(0.18, FigureGround.StandY(FigureGround.DeclaredFloorAt(lake, -21.28, 13.12)!.Value + FigureGround.WalkClearanceM, 0.18), 9);
        Assert.Equal(0.08, FigureGround.StandY(FigureGround.DeclaredFloorAt(lake, -21.28, 13.12)!.Value + FigureGround.WalkClearanceM, 0.0), 9);
        Assert.Null(FigureGround.DeclaredFloorAt(lake, 0, 0));
        Assert.Null(FigureGround.DeclaredFloorAt(new List<DeclaredFloor>(), -21.28, 13.12));
        Assert.Null(FigureGround.DeclaredFloorAt(null, -21.28, 13.12));
        Assert.Equal(0.0, FigureGround.DeclaredFloorAt(new[] { new DeclaredFloor("a", 0, hut) }, -21.28, 13.12));
        var big = R((-10, -10), (10, -10), (10, 10), (-10, 10));
        var small = R((-1, -1), (1, -1), (1, 1), (-1, 1));
        Assert.Equal(0.16, FigureGround.DeclaredFloorAt(new[] { new DeclaredFloor("zone", 0.09, big), new DeclaredFloor("hut", 0.16, small) }, 0, 0));
        Assert.Equal(0.16, FigureGround.DeclaredFloorAt(new[] { new DeclaredFloor("hut", 0.16, small), new DeclaredFloor("zone", 0.09, big) }, 0, 0));
        Assert.Equal(0.09, FigureGround.DeclaredFloorAt(new[] { new DeclaredFloor("zone", 0.09, big), new DeclaredFloor("hut", 0.16, small) }, 5, 5));
        Assert.Null(FigureGround.DeclaredFloorAt(new[] { new DeclaredFloor("x", 5, R((0, 0), (1, 1))) }, 0.5, 0.5));
    }
}
