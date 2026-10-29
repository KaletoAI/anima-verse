using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Net.Sockets;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

/// <summary>The native title's visible states, focus flow and login errors, without a server or launcher writes.</summary>
public static class LoginLookCheck
{
    public static async Task<string> RunAsync(Node host)
    {
        var screen = new LoginScreen().Setup("192.168.8.244:8000", "Ada");
        host.AddChild(screen);
        try
        {
            var nodes = Descendants(screen).ToArray();
            var inputs = nodes.OfType<LineEdit>().ToArray();
            var server = inputs.Single(i => i.PlaceholderText.StartsWith("Server"));
            var user = inputs.Single(i => i != server && !i.Secret);
            var password = inputs.Single(i => i.Secret);
            var enter = nodes.OfType<Button>().Single(b => b.Text is "Enter world" or "Log in");
            Expect("title", nodes.OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text == "Anima Verse"));
            Expect("subtitle", nodes.OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text == "A world that lives on without you"));
            Expect("gate copy", enter.Text == "Enter world");
            Expect("known server collapsed", !server.IsVisibleInTree());
            Expect("known server summary", nodes.OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text == "Server  192.168.8.244:8000 ·"));
            Expect("prefilled name focuses passphrase", password.HasFocus());
            nodes.OfType<Button>().Single(b => b.Text == "Change").EmitSignal(BaseButton.SignalName.Pressed);
            Expect("change reveals and focuses server", server.IsVisibleInTree() && server.HasFocus());
            server.EmitSignal(LineEdit.SignalName.TextSubmitted, server.Text);
            Expect("server enter skips prefilled name", password.HasFocus());
            user.EmitSignal(LineEdit.SignalName.TextSubmitted, user.Text);
            Expect("name enter focuses passphrase", password.HasFocus());

            var pending = new TaskCompletionSource();
            var submissions = 0;
            screen.Submit = (s, u, p, remember) =>
            {
                submissions++;
                Expect("normalised credentials", s == "http://192.168.8.244:8000" && u == "Ada" && p == "one-use passphrase" && remember);
                return pending.Task;
            };
            user.Text = " Ada ";
            password.Text = "one-use passphrase";
            enter.EmitSignal(BaseButton.SignalName.Pressed);
            Expect("busy copy and disabled", enter.Text == "Opening the gate…" && enter.Disabled);
            Expect("password cleared at submit", password.Text == "");
            enter.EmitSignal(BaseButton.SignalName.Pressed);
            Expect("no duplicate submission", submissions == 1);
            pending.SetException(new ApiException(401, "/auth/login", "private server detail"));
            await Frame(host);
            Expect("rejection copy", HasText(screen, "Sign-in failed — check name and passphrase."));
            Expect("gate restored", !enter.Disabled && enter.Text == "Enter world" && server.Editable);

            foreach (var (exception, expected) in new (Exception, string)[]
            {
                (new ApiException(403, "/auth/login"), "Sign-in failed — check name and passphrase."),
                (new HttpRequestException("Connection refused", new SocketException((int)SocketError.ConnectionRefused)),
                    "The server at 192.168.8.244:8000 is not answering."),
                (new TaskCanceledException("request timed out"), "The server at 192.168.8.244:8000 is not answering."),
                (new TimeoutException("timeout"), "The server at 192.168.8.244:8000 is not answering."),
                (new ApiException(401, "/play/worldmap"), "HTTP 401 on /play/worldmap"),
                (new InvalidOperationException("Keep this message."), "Keep this message.")
            })
            {
                screen.Submit = (_, _, _, _) => Task.FromException(exception);
                password.Text = "retry";
                enter.EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("error: " + exception.GetType().Name, HasText(screen, expected));
                Expect("retry clears password", password.Text == "" && !enter.Disabled);
            }

            screen.ShowBoot(42, "Consulting the map…", null, false);
            Expect("boot hides form", inputs.All(i => !i.IsVisibleInTree()) && !enter.IsVisibleInTree()
                && !nodes.OfType<Button>().Single(b => b.Text == "Change").IsVisibleInTree());
            var bar = nodes.OfType<ProgressBar>().Single(b => b.IsVisibleInTree());
            Expect("boot bar", bar.Value == 42 && !bar.ShowPercentage);
            Expect("boot stage", HasText(screen, "Consulting the map…"));
            var back = nodes.OfType<Button>().Single(b => b.Text == "Back to the title");
            Expect("no back during healthy boot", !back.IsVisibleInTree());
            bool faded = false, returned = false;
            screen.FadeOut(0.05, () => faded = true);
            screen.ShowBoot(100, "Ready", "Start failed", true);
            screen.Back = () => returned = true;
            back.EmitSignal(BaseButton.SignalName.Pressed);
            await host.ToSignal(host.GetTree().CreateTimer(0.1), SceneTreeTimer.SignalName.Timeout);
            Expect("failed boot holds screen", back.IsVisibleInTree() && screen.Modulate.A == 1 && !faded && returned);
        }
        finally { screen.Free(); }

        foreach (var address in new[] { "", "invalid address" })
        {
            var fresh = new LoginScreen().Setup(address, "");
            host.AddChild(fresh);
            try
            {
                var server = Descendants(fresh).OfType<LineEdit>().Single(i => i.PlaceholderText.StartsWith("Server"));
                if (address == "") Expect("no server starts with focused field", server.IsVisibleInTree() && server.HasFocus());
                fresh.Submit = (_, _, _, _) => throw new InvalidOperationException("validation must prevent submit");
                Descendants(fresh).OfType<Button>().Single(b => b.Text == "Enter world").EmitSignal(BaseButton.SignalName.Pressed);
                Expect("invalid server revealed and focused", server.IsVisibleInTree() && server.HasFocus());
                Expect("local validation retained", HasText(fresh, address == "" ? "The server address is required."
                    : "Not a server address: 'invalid address' (expected host:port or http(s)://host:port)."));
            }
            finally { fresh.Free(); }
        }
        await CheckRememberedAsync(host);
        await CheckSnapshotAsync(host);
        await CheckLayoutAsync(host);
        return "loginlook title=ok server=ok focus=ok submit=ok errors=7 boot=ok layout=900p/4K/narrow session=ok backdrop=ok";
    }

    private sealed class AuthFixture : HttpMessageHandler
    {
        public bool Valid = true, Unreachable;
        public int StatusCalls, LoginCalls, LogoutCalls;
        public bool? Remember;
        public TaskCompletionSource? PauseLogout;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (Unreachable) throw new HttpRequestException("fixture unavailable");
            string body;
            switch (path)
            {
                case "/auth/status":
                    StatusCalls++;
                    body = Valid ? "{\"authenticated\":true,\"user\":{\"username\":\"Ada\",\"role\":\"admin\",\"settings\":{\"active_character\":\"Ada Wren\"}}}"
                        : "{\"authenticated\":false,\"user\":null}";
                    break;
                case "/auth/login":
                    LoginCalls++;
                    using (var json = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(ct)))
                        Remember = json.RootElement.GetProperty("remember").GetBoolean();
                    body = "{\"user\":{\"username\":\"Ada\",\"role\":\"admin\"}}";
                    break;
                case "/auth/logout":
                    LogoutCalls++;
                    if (PauseLogout is { } paused) await paused.Task.WaitAsync(ct);
                    body = "{}";
                    break;
                default: throw new InvalidOperationException("unexpected pre-login request: " + path);
            }
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }

    private static async Task CheckRememberedAsync(Node host)
    {
        var dir = ProjectSettings.GlobalizePath("user://task75-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var store = new SessionStore(Path.Combine(dir, "session.json"));
        var fixture = new AuthFixture();
        var accepted = 0;
        const string server = "http://fixture.invalid:8000";
        AnimaApi Api(string url)
        {
            var api = new AnimaApi(url, fixture);
            // A transport fixture has no CookieContainer; simulate the cookie set by /auth/login.
            api.AdoptSession("fixture-token");
            return api;
        }
        LoginScreen Screen()
        {
            var screen = new LoginScreen().Setup(server, "Prefilled", dir);
            host.AddChild(screen);
            return screen;
        }
        async Task Bind(LoginScreen screen)
        {
            await screen.BindSessionAsync(store, Api, (api, answer, fallbackRole) =>
            {
                accepted++;
                Expect("entry has adopted token", api.SessionToken() == "fixture-token");
                Expect("entry receives authoritative user", answer.GetProperty("user").GetProperty("username").GetString() == "Ada");
                screen.ShowBoot(1, "Starting…", null, false);
                api.Dispose();
                return Task.CompletedTask;
            }, Path.Combine(dir, "launcher.json"));
        }
        void Save() => store.Save(new RememberedSession(server, "Old name", "fixture-token", "user"));
        try
        {
            Save();
            var gate = Screen();
            try
            {
                await Bind(gate);
                Expect("valid token gate", HasText(gate, "Signed in as Ada"));
                Expect("gate hides passphrase", !Descendants(gate).OfType<LineEdit>().Single(i => i.Secret).IsVisibleInTree());
                var enter = Descendants(gate).OfType<Button>().Single(b => b.Text == "Enter world");
                Expect("gate enter has default focus", enter.HasFocus());
                Input.ParseInputEvent(new InputEventKey { Keycode = Key.Enter, PhysicalKeycode = Key.Enter, Pressed = true });
                await Frame(host); await Frame(host);
                Input.ParseInputEvent(new InputEventKey { Keycode = Key.Enter, PhysicalKeycode = Key.Enter, Pressed = false });
                await Frame(host); await Frame(host);
                Expect("keyboard enters via shared callback without login", accepted == 1 && fixture.LoginCalls == 0);
                Expect("gate entry becomes loading", HasText(gate, "Starting…") && !HasText(gate, "Signed in as Ada"));
            }
            finally { gate.Free(); }

            Save();
            var signout = Screen();
            try
            {
                await Bind(signout);
                Descendants(signout).OfType<Button>().Single(b => b.Text == "Sign out").EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("signout clears store", store.LoadFor(server) is null && fixture.LogoutCalls == 1);
                Expect("signout restores prefilled form", Descendants(signout).OfType<LineEdit>().Any(i => i.IsVisibleInTree() && i.Text == "Ada"));
            }
            finally { signout.Free(); }

            foreach (var unreachable in new[] { false, true })
            {
                Save(); fixture.Valid = false; fixture.Unreachable = unreachable;
                var invalid = Screen();
                try
                {
                    await Bind(invalid);
                    Expect("invalid/unreachable token clears store", store.LoadFor(server) is null);
                    Expect("invalid token shows form", Descendants(invalid).OfType<LineEdit>().Single(i => i.Secret).IsVisibleInTree());
                    if (unreachable) Expect("unreachable notice", HasText(invalid, "The server at fixture.invalid:8000 is not answering."));
                }
                finally { invalid.Free(); }
            }
            fixture.Unreachable = false; fixture.Valid = true;
            Save();
            var form = Screen();
            try
            {
                // A server mismatch must not send any authenticated request.
                store.Save(new RememberedSession("http://other.invalid", "Other", "other-token", "user"));
                var statusCalls = fixture.StatusCalls;
                await Bind(form);
                Expect("server mismatch never checks token", fixture.StatusCalls == statusCalls);
                var remember = Descendants(form).OfType<CheckBox>().Single();
                Expect("remember defaults on", remember.ButtonPressed && remember.Text == "Stay signed in");
                store.Save(new RememberedSession(server, "Ada", "fixture-token", "admin"));
                remember.ButtonPressed = false;
                var inputs = Descendants(form).OfType<LineEdit>().ToArray();
                inputs.Single(i => !i.Secret && !i.PlaceholderText.StartsWith("Server")).Text = "Ada";
                inputs.Single(i => i.Secret).Text = "one-use";
                Descendants(form).OfType<Button>().Single(b => b.Text == "Enter world").EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("form uses same entry callback", accepted == 2 && fixture.LoginCalls == 1);
                Expect("unchecked sends false and deletes existing entry", fixture.Remember == false && store.LoadFor(server) is null);
            }
            finally { form.Free(); }

            var rememberForm = Screen();
            try
            {
                await Bind(rememberForm);
                Descendants(rememberForm).OfType<LineEdit>().Single(i => i.Secret).Text = "never-store-this";
                Descendants(rememberForm).OfType<Button>().Single(b => b.Text == "Enter world").EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("checked login enters and persists token", accepted == 3 && fixture.Remember == true
                    && store.LoadFor(server) is { User: "Ada", Role: "admin", Token: "fixture-token" });
                Expect("password absent from store", !File.ReadAllText(store.Path).Contains("never-store-this"));
            }
            finally { rememberForm.Free(); }

            var offlineSignout = Screen();
            try
            {
                await Bind(offlineSignout);
                fixture.Unreachable = true;
                Descendants(offlineSignout).OfType<Button>().Single(b => b.Text == "Sign out").EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("offline signout clears store and restores form", store.LoadFor(server) is null
                    && Descendants(offlineSignout).OfType<LineEdit>().Single(i => i.Secret).IsVisibleInTree());
            }
            finally { offlineSignout.Free(); }

            fixture.Unreachable = false;
            Save();
            var delayedSignout = Screen();
            try
            {
                await Bind(delayedSignout);
                fixture.PauseLogout = new TaskCompletionSource();
                Descendants(delayedSignout).OfType<Button>().Single(b => b.Text == "Sign out").EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                var enter = Descendants(delayedSignout).OfType<Button>().Single(b => b.Text == "Enter world");
                var loginsBefore = fixture.LoginCalls;
                Descendants(delayedSignout).OfType<LineEdit>().Single(i => i.Secret).Text = "new-login";
                Expect("signout form waits for account-wide release", enter.Disabled);
                enter.EmitSignal(BaseButton.SignalName.Pressed);
                await Frame(host);
                Expect("no login races pending logout", fixture.LoginCalls == loginsBefore);
                fixture.PauseLogout.SetResult();
                for (var i = 0; i < 100 && enter.Disabled; i++)
                    await host.ToSignal(host.GetTree().CreateTimer(0.01), SceneTreeTimer.SignalName.Timeout);
                Expect("form becomes usable after logout", !enter.Disabled && store.LoadFor(server) is null);
            }
            finally
            {
                fixture.PauseLogout?.TrySetResult();
                delayedSignout.Free();
            }
        }
        finally { Directory.Delete(dir, true); fixture.Dispose(); }
    }

    private static async Task CheckSnapshotAsync(Node host)
    {
        var dir = ProjectSettings.GlobalizePath("user://task75-backdrop-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var path = TitleBackdropMath.PathFor(dir, "http://image.invalid")!;
        using (var image = Image.CreateEmpty(80, 40, false, Image.Format.Rgb8))
        {
            image.Fill(Colors.Beige);
            Expect("fixture image saved", image.SaveJpg(path, 0.85f) == Error.Ok);
        }
        var viewport = new SubViewport { Size = new Vector2I(400, 600) };
        host.AddChild(viewport);
        var screen = new LoginScreen().Setup("http://image.invalid", "Ada", dir);
        viewport.AddChild(screen);
        try
        {
            for (var i = 0; i < 100 && !Descendants(screen).OfType<TextureRect>().Any(t => t.Name == "WorldSnapshot"); i++)
                await host.ToSignal(host.GetTree().CreateTimer(0.01), SceneTreeTimer.SignalName.Timeout);
            await Frame(host); await Frame(host);
            var texture = Descendants(screen).OfType<TextureRect>().Single(t => t.Name == "WorldSnapshot");
            Expect("snapshot cover", texture.Position.X <= 0 && texture.Position.Y <= 0
                && texture.Position.X + texture.Size.X >= 400 && texture.Position.Y + texture.Size.Y >= 600);
            screen.ShowBoot(50, "Loading…", null, false);
            Expect("loading keeps image", texture.IsVisibleInTree());
            screen.ShowBoot(50, "Failed", "failure", true);
            Expect("failure keeps image", texture.IsVisibleInTree());
            // Change server through the same field as the Change link.
            screen.ShowForm("Ada");
            var address = Descendants(screen).OfType<LineEdit>().Single(i => i.PlaceholderText.StartsWith("Server"));
            address.Text = "http://missing.invalid";
            address.EmitSignal(LineEdit.SignalName.TextChanged, address.Text);
            await Frame(host);
            Expect("missing image has no snapshot TextureRect", !Descendants(screen).OfType<TextureRect>().Any(t => t.Name == "WorldSnapshot"));
            var capture = Path.Combine(dir, "must-not-capture.jpg");
            Expect("check run never captures", !await TitleSnapshotCapture.CaptureAsync(host, capture, check: true, bench: false, _ => { }));
            Expect("check capture writes nothing", !File.Exists(capture));
        }
        finally { viewport.Free(); Directory.Delete(dir, true); }
    }

    private static async Task CheckLayoutAsync(Node host)
    {
        var viewport = new SubViewport { Size = new Vector2I(1600, 900) };
        host.AddChild(viewport);
        var screen = new LoginScreen().Setup("192.168.8.244:8000", "Ada");
        viewport.AddChild(screen);
        try
        {
            foreach (var size in new[] { new Vector2I(1600, 900), new Vector2I(3840, 2160), new Vector2I(400, 600) })
            {
                viewport.Size = size;
                await Frame(host);
                await Frame(host);
                var plate = Descendants(screen).OfType<PanelContainer>().Single(p => p.Name == "TitlePlate");
                var rect = plate.GetGlobalRect();
                var center = rect.GetCenter();
                Expect("plate centered " + size, center.DistanceTo((Vector2)size / 2) < 3);
                Expect("plate fits " + size, rect.Position.X >= 0 && rect.Position.Y >= 0 && rect.End.X <= size.X && rect.End.Y <= size.Y);
                if (size.X >= 1600) Expect($"plate scales from 900p {size}: rect={rect} minimum={plate.GetCombinedMinimumSize()} screen={screen.Size}", Math.Abs(rect.Size.X - 430 * size.Y / 900f) < 3);
                foreach (var control in Descendants(plate).OfType<Control>().Where(c => c.IsVisibleInTree() && c is LineEdit or Button))
                    Expect("controls fit inside plate " + size, rect.Grow(1).Encloses(control.GetGlobalRect()));
            }
        }
        finally { viewport.Free(); }
    }

    private static async Task Frame(Node host) => await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
    private static bool HasText(Node screen, string text) => Descendants(screen).OfType<Label>().Any(l => l.IsVisibleInTree() && l.Text == text);

    private static IEnumerable<Node> Descendants(Node parent)
    {
        foreach (var child in parent.GetChildren())
        {
            yield return child;
            foreach (var descendant in Descendants(child)) yield return descendant;
        }
    }

    private static void Expect(string what, bool value)
    {
        if (!value) throw new InvalidOperationException("loginlook: " + what);
    }
}
