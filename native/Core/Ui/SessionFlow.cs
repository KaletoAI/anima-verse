namespace AnimaNative.Ui;

/// <summary>Where the client stands with its session (one value per scene).</summary>
public enum SessionPhase
{
    /// <summary>The login screen: no session.</summary>
    Title,
    /// <summary>Logged in (or resumed): the world loads or stands.</summary>
    Playing,
    /// <summary>This scene is going away (back to the title, a lost session, a rebuild); nothing more happens here.</summary>
    Leaving,
}

/// <summary>What happened.</summary>
public enum SessionEvent
{
    /// <summary>The login screen's login was accepted by the server.</summary>
    LoggedIn,
    /// <summary>The HUD's <c>markResume</c> action: the page is about to reload into the current session.</summary>
    ResumeMarked,
    /// <summary>
    /// The HUD page (<c>hud.html</c>) finished loading in the main frame (gdCEF emits <c>on_page_loaded</c> for the main
    /// frame only, gdbrowser.cpp <c>onLoadEnd</c>) — the handoff's first load, or a reload.
    /// </summary>
    HudPageLoaded,
    /// <summary>"Back to title" / "Log out" (menu, top bar, the failed start's button).</summary>
    BackToTitle,
    /// <summary>A request answered 401: the session is gone.</summary>
    Unauthorized,
}

/// <summary>What the scene has to do about it.</summary>
public enum SessionStep
{
    None,
    /// <summary>A fresh start without a session: the login screen.</summary>
    ShowLogin,
    /// <summary>A start that carries the live session of a rebuild: straight to the world, no login screen, no handoff.</summary>
    ResumeWorld,
    /// <summary><c>markResume</c> is acknowledged (logged); the reload decides, in whichever order the two arrive.</summary>
    Acknowledge,
    /// <summary>The avatar changed: tear this scene down and build the world anew with the SAME session (no logout, no login).</summary>
    Rebuild,
    /// <summary>End the session (status-guarded logout) and go back to the login screen.</summary>
    LogoutToTitle,
    /// <summary>The session is gone already: back to the login screen without a logout call.</summary>
    ExpiredToTitle,
}

/// <summary>
/// The session state of one scene: its phase, and whether the HUD page of this session has had its first load
/// (every later load is a reload).
/// </summary>
public readonly record struct SessionState(SessionPhase Phase, bool HudLoaded);

/// <summary>
/// The native client's session flow as ONE pure decision (no Godot, no I/O), so the rules are testable:
/// <see cref="Start"/> for a new scene, <see cref="Next"/> for each event.
///
/// The character switch. The browser's GameMenu calls <c>markResume()</c> and then <c>location.reload()</c>; the
/// marker makes the reloaded page's boot skip the title gate, and the reload rebuilds the world for the new avatar
/// (client3d main.ts <c>RESUME_KEY</c>). Every reload of the HUD page after its first load means exactly that —
/// "resume with the current session" (a take-over, or a re-login that reloads with the marker); inside CEF there is
/// no other reload path. So the RELOAD is the trigger: the first <c>hud.html</c> load of a session (the handoff's
/// navigation) only sets <see cref="SessionState.HudLoaded"/>, every later one rebuilds. <c>markResume</c> is only
/// acknowledged, and it may arrive before or after the reload (two IPC paths, no order to rely on). A scene started
/// by a rebuild has its page loaded already — that reload was the trigger — so its next reload rebuilds again. The
/// rebuild keeps the session: the HUD page has already reloaded on that very cookie, and a handoff would end it
/// (<c>HudOverlay.HandoffScript</c> logs out what the browser holds).
///
/// Leaving is final for a scene: a back-to-title or a 401 that comes while a rebuild is under way changes nothing
/// more, and the next scene starts from <see cref="Start"/>.
/// </summary>
public static class SessionFlow
{
    /// <summary>
    /// A new scene: with the session a rebuild carried over it plays at once (<see cref="SessionStep.ResumeWorld"/>),
    /// its HUD page already loaded (the reload that triggered the rebuild); otherwise it shows the login screen.
    /// </summary>
    public static (SessionState State, SessionStep Step) Start(bool carriesSession)
        => carriesSession
            ? (new SessionState(SessionPhase.Playing, true), SessionStep.ResumeWorld)
            : (new SessionState(SessionPhase.Title, false), SessionStep.ShowLogin);

    /// <summary>The next state and the step for <paramref name="e"/> in <paramref name="s"/>.</summary>
    public static (SessionState State, SessionStep Step) Next(SessionState s, SessionEvent e)
    {
        var leaving = new SessionState(SessionPhase.Leaving, false);
        switch (s.Phase)
        {
            case SessionPhase.Title:
                return e switch
                {
                    SessionEvent.LoggedIn => (new SessionState(SessionPhase.Playing, false), SessionStep.None),
                    // The login screen's own way back (no session yet: the logout is skipped by its status check).
                    SessionEvent.BackToTitle => (leaving, SessionStep.LogoutToTitle),
                    _ => (s, SessionStep.None),
                };
            case SessionPhase.Playing:
                return e switch
                {
                    SessionEvent.ResumeMarked => (s, SessionStep.Acknowledge),
                    // The handoff's own navigation: the first load of this session's page, not a reload.
                    SessionEvent.HudPageLoaded when !s.HudLoaded => (s with { HudLoaded = true }, SessionStep.None),
                    SessionEvent.HudPageLoaded => (leaving, SessionStep.Rebuild),
                    SessionEvent.BackToTitle => (leaving, SessionStep.LogoutToTitle),
                    SessionEvent.Unauthorized => (leaving, SessionStep.ExpiredToTitle),
                    _ => (s, SessionStep.None),
                };
            default:
                return (s, SessionStep.None);
        }
    }
}
