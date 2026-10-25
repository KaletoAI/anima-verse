using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The session flow (<see cref="SessionFlow"/>), derived from the browser by hand:
///   • GameMenu's take-over = <c>markResume()</c> then <c>location.reload()</c>, a re-login reloads with the marker —
///     inside CEF every reload of the HUD page after its first load means "resume with the current session";
///   • so natively the RELOAD rebuilds (with the session), in either order with <c>markResume</c>, which is only
///     acknowledged; the handoff's own navigation to <c>hud.html</c> is the first load, not a reload;
///   • a scene started by a rebuild has its page loaded already (that reload was the trigger);
///   • back to title = logout + reload (main.ts <c>backToTitle</c>), a 401 = the login without a logout;
///   • a scene that is leaving answers nothing more (one teardown per scene), the login screen ignores the HUD.
/// </summary>
public class SessionFlowTests
{
    private static readonly SessionState Title = new(SessionPhase.Title, false);
    private static readonly SessionState Fresh = new(SessionPhase.Playing, false);   // logged in, HUD page not loaded yet
    private static readonly SessionState Up = new(SessionPhase.Playing, true);       // the HUD page has had its first load
    private static readonly SessionState Leaving = new(SessionPhase.Leaving, false);

    [Fact]
    public void AFreshStartShowsTheLogin()
        => Assert.Equal((Title, SessionStep.ShowLogin), SessionFlow.Start(carriesSession: false));

    [Fact]
    public void ARebuiltSceneResumesWithItsPageAlreadyLoaded()
        => Assert.Equal((Up, SessionStep.ResumeWorld), SessionFlow.Start(carriesSession: true));

    [Fact]
    public void TheHandoffsFirstLoadIsNoReload()
    {
        // login → the handoff navigates /health → hud.html: one main-frame load of hud.html.
        var (s, step) = SessionFlow.Next(Title, SessionEvent.LoggedIn);
        Assert.Equal((Fresh, SessionStep.None), (s, step));
        (s, step) = SessionFlow.Next(s, SessionEvent.HudPageLoaded);
        Assert.Equal((Up, SessionStep.None), (s, step));
    }

    [Fact]
    public void MarkerThenReloadRebuilds()
    {
        var (s, step) = SessionFlow.Next(Up, SessionEvent.ResumeMarked);
        Assert.Equal((Up, SessionStep.Acknowledge), (s, step));
        (s, step) = SessionFlow.Next(s, SessionEvent.HudPageLoaded);
        Assert.Equal((Leaving, SessionStep.Rebuild), (s, step));
    }

    [Fact]
    public void ReloadThenMarkerRebuildsOnce()
    {
        // The reload's load event wins the race: it rebuilds alone; the late marker reaches the leaving scene …
        var (s, step) = SessionFlow.Next(Up, SessionEvent.HudPageLoaded);
        Assert.Equal((Leaving, SessionStep.Rebuild), (s, step));
        Assert.Equal((Leaving, SessionStep.None), SessionFlow.Next(s, SessionEvent.ResumeMarked));
        // … or the rebuilt scene, where it is only acknowledged — no second rebuild.
        var (rebuilt, _) = SessionFlow.Start(carriesSession: true);
        Assert.Equal((Up, SessionStep.Acknowledge), SessionFlow.Next(rebuilt, SessionEvent.ResumeMarked));
    }

    [Fact]
    public void TheMarkerAloneIsOnlyAcknowledged()
    {
        Assert.Equal((Up, SessionStep.Acknowledge), SessionFlow.Next(Up, SessionEvent.ResumeMarked));
        // Before the page's first load as well (nothing to rebuild yet, and the first load stays the first load).
        var (s, step) = SessionFlow.Next(Fresh, SessionEvent.ResumeMarked);
        Assert.Equal((Fresh, SessionStep.Acknowledge), (s, step));
        Assert.Equal((Up, SessionStep.None), SessionFlow.Next(s, SessionEvent.HudPageLoaded));
    }

    [Fact]
    public void ASecondSwitchAfterARebuildRebuildsAgain()
    {
        var (s, _) = SessionFlow.Start(carriesSession: true);
        Assert.Equal((Leaving, SessionStep.Rebuild), SessionFlow.Next(s, SessionEvent.HudPageLoaded));
    }

    [Fact]
    public void BackToTitleLogsOut()
    {
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Up, SessionEvent.BackToTitle));
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Fresh, SessionEvent.BackToTitle));
        // The login screen's own "back" (no session yet): the status check skips the logout.
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Title, SessionEvent.BackToTitle));
    }

    [Fact]
    public void ALostSessionGoesToTheLoginWithoutLogout()
    {
        Assert.Equal((Leaving, SessionStep.ExpiredToTitle), SessionFlow.Next(Up, SessionEvent.Unauthorized));
        Assert.Equal((Leaving, SessionStep.ExpiredToTitle), SessionFlow.Next(Fresh, SessionEvent.Unauthorized));
    }

    [Theory]
    [InlineData(SessionEvent.LoggedIn)]
    [InlineData(SessionEvent.ResumeMarked)]
    [InlineData(SessionEvent.HudPageLoaded)]
    [InlineData(SessionEvent.BackToTitle)]
    [InlineData(SessionEvent.Unauthorized)]
    public void ALeavingSceneAnswersNothing(SessionEvent e)
        => Assert.Equal((Leaving, SessionStep.None), SessionFlow.Next(Leaving, e));

    [Theory]
    [InlineData(SessionEvent.ResumeMarked)]
    [InlineData(SessionEvent.HudPageLoaded)]
    [InlineData(SessionEvent.Unauthorized)]
    public void TheLoginScreenIgnoresSessionEvents(SessionEvent e)
        => Assert.Equal((Title, SessionStep.None), SessionFlow.Next(Title, e));

    [Fact]
    public void ALoginWhilePlayingChangesNothing()
        => Assert.Equal((Up, SessionStep.None), SessionFlow.Next(Up, SessionEvent.LoggedIn));
}
