using AnimaNative.Props;
using Xunit;

namespace AnimaNative.Tests;

public class PropActionMotionTests
{
    // Start 90 + clip turn 90 = 180. Only errors above five degrees override it.
    [Theory]
    [InlineData(180.0, 180.0, false)]
    [InlineData(0.0, 0.0, true)]
    [InlineData(null, 180.0, false)]
    [InlineData(-180.0, 180.0, false)]
    [InlineData(-175.0, 180.0, false)]
    [InlineData(-174.9, -174.9, true)]
    public void CancelDepartureEndsWithClipTurn(double? standYaw, double expected, bool mismatch)
    {
        var result = PropActionMotion.HandBackYaw(90 + 90, standYaw);
        Assert.Equal(expected, result.YawDeg);
        Assert.Equal(mismatch, result.Mismatch);
    }
}
