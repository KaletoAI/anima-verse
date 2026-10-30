using AnimaNative.Hud;
using Xunit;

namespace AnimaNative.Tests;

public class HudTextTests
{
    [Fact]
    public void PrintableCharactersIncludingEveryVirtualKeyCollisionAreText()
    {
        foreach (char c in " .,\u002d!\"#$%&'()*+/[\\]_`{|}~öåüÄÖÜßAZaz09")
            Assert.True(HudText.IsTextKey(c, false, false, false), $"U+{(int)c:X4}");
        Assert.True(HudText.IsTextKey(0x1f642, false, false, false));
    }

    [Theory]
    [InlineData(0u)] // Special keys (arrows, Home/End, F-keys) have no Unicode.
    [InlineData(8u)] // Backspace
    [InlineData(9u)] // Tab
    [InlineData(13u)] // Enter
    [InlineData(27u)] // Escape
    [InlineData(127u)] // Delete
    [InlineData(159u)] // C1 control
    [InlineData(0xd800u)]
    [InlineData(0x110000u)]
    public void ControlsAndInvalidScalarsAreNotText(uint unicode)
        => Assert.False(HudText.IsTextKey(unicode, false, false, false));

    [Fact]
    public void ShortcutsStayKeysButAltGrProducesText()
    {
        foreach (char c in "acvxz.")
        {
            Assert.False(HudText.IsTextKey(c, true, false, false));
            Assert.False(HudText.IsTextKey(c, false, true, false));
            Assert.False(HudText.IsTextKey(c, false, false, true));
        }
        Assert.True(HudText.IsTextKey('@', true, true, false));
        Assert.True(HudText.IsTextKey('€', true, true, false));
        Assert.False(HudText.IsTextKey('@', true, true, true));
    }
}
