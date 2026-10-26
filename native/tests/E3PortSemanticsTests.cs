using AnimaNative.Ground;
using AnimaNative.Water;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// JS value rules the E3 ports must mirror where no vector case reaches them (found while porting against the
/// E3 vectors). Each expectation is what the TS function returns, derived from the ECMAScript rule named.
/// </summary>
public class E3PortSemanticsTests
{
    /// <summary><c>tileKeyAt(256, -0, -0)</c>: <c>Math.floor(-0 / 256)</c> is −0, and a template literal prints −0 as "0".</summary>
    [Fact]
    public void TileKeyOfNegativeZeroIsZero() => Assert.Equal("0,0", LayerCut.TileKeyAt(256, -0.0, -0.0));

    /// <summary><c>waterTintRgb('# 12345')</c>: the regex wants six hex digits right after '#', so the default #3f7fb8.</summary>
    [Fact]
    public void TintWithInnerSpaceIsTheDefault()
        => Assert.Equal((63 / 255.0, 127 / 255.0, 184 / 255.0), WaterShade.TintRgb("# 12345"));

    /// <summary><c>'﻿#002e57'.trim()</c> drops U+FEFF (ECMA-262 WhiteSpace), so the tint is read.</summary>
    [Fact]
    public void TintTrimsTheJsWhiteSpaceSet()
        => Assert.Equal((0.0, 46 / 255.0, 87 / 255.0), WaterShade.TintRgb("﻿#002e57"));
}
