using AnimaNative.Ui;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The session flow (<see cref="SessionFlow"/>), derived from the browser by hand:
///   • GameMenu's take-over = <c>markResume()</c> then <c>location.reload()</c>; the browser's reloaded boot skips the
///     title gate because of the marker → natively: marker THEN reloaded <c>hud.html</c> = rebuild with the session;
///   • the handoff's first <c>hud.html</c> load (no marker) changes nothing;
///   • back to title = logout + reload (main.ts <c>backToTitle</c>), a 401 = the login without a logout;
///   • a scene that is leaving answers nothing more (one teardown per scene).
/// </summary>
public class SessionFlowTests
{
    private static readonly SessionState Title = new(SessionPhase.Title, false);
    private static readonly SessionState Playing = new(SessionPhase.Playing, false);
    private static readonly SessionState Marked = new(SessionPhase.Playing, true);
    private static readonly SessionState Leaving = new(SessionPhase.Leaving, false);

    [Fact]
    public void AFreshStartShowsTheLogin()
        => Assert.Equal((Title, SessionStep.ShowLogin), SessionFlow.Start(carriesSession: false));

    [Fact]
    public void ARebuiltSceneResumesWithoutLogin()
        => Assert.Equal((Playing, SessionStep.ResumeWorld), SessionFlow.Start(carriesSession: true));

    [Fact]
    public void CharacterSwitchRebuildsWithoutLogin()
    {
        // login → the handoff's first hud.html → markResume → the reloaded hud.html
        var (s, step) = SessionFlow.Next(Title, SessionEvent.LoggedIn);
        Assert.Equal((Playing, SessionStep.None), (s, step));
        (s, step) = SessionFlow.Next(s, SessionEvent.HudPageLoaded);
        Assert.Equal((Playing, SessionStep.None), (s, step));
        (s, step) = SessionFlow.Next(s, SessionEvent.ResumeMarked);
        Assert.Equal((Marked, SessionStep.Acknowledge), (s, step));
        (s, step) = SessionFlow.Next(s, SessionEvent.HudPageLoaded);
        Assert.Equal((Leaving, SessionStep.Rebuild), (s, step));
        // The next scene carries the session: straight to the world.
        Assert.Equal((Playing, SessionStep.ResumeWorld), SessionFlow.Start(carriesSession: true));
    }

    [Fact]
    public void APageReloadWithoutTheMarkerKeepsTheWorld()
        => Assert.Equal((Playing, SessionStep.None), SessionFlow.Next(Playing, SessionEvent.HudPageLoaded));

    [Fact]
    public void TheMarkerAloneIsOnlyAcknowledged()
    {
        Assert.Equal((Marked, SessionStep.Acknowledge), SessionFlow.Next(Playing, SessionEvent.ResumeMarked));
        // A second markResume before the reload is the same acknowledgement, not a second rebuild.
        Assert.Equal((Marked, SessionStep.Acknowledge), SessionFlow.Next(Marked, SessionEvent.ResumeMarked));
    }

    [Fact]
    public void BackToTitleLogsOut()
    {
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Playing, SessionEvent.BackToTitle));
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Marked, SessionEvent.BackToTitle));
        // The login screen's own "back" (no session yet): the status check skips the logout.
        Assert.Equal((Leaving, SessionStep.LogoutToTitle), SessionFlow.Next(Title, SessionEvent.BackToTitle));
    }

    [Fact]
    public void ALostSessionGoesToTheLoginWithoutLogout()
    {
        Assert.Equal((Leaving, SessionStep.ExpiredToTitle), SessionFlow.Next(Playing, SessionEvent.Unauthorized));
        // A 401 between the marker and the reload: the session is dead, a rebuild could not resume it.
        Assert.Equal((Leaving, SessionStep.ExpiredToTitle), SessionFlow.Next(Marked, SessionEvent.Unauthorized));
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
        => Assert.Equal((Marked, SessionStep.None), SessionFlow.Next(Marked, SessionEvent.LoggedIn));
}
