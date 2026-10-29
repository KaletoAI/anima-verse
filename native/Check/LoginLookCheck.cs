using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
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
            screen.Submit = (s, u, p) =>
            {
                submissions++;
                Expect("normalised credentials", s == "http://192.168.8.244:8000" && u == "Ada" && p == "one-use passphrase");
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
                screen.Submit = (_, _, _) => Task.FromException(exception);
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
                fresh.Submit = (_, _, _) => throw new InvalidOperationException("validation must prevent submit");
                Descendants(fresh).OfType<Button>().Single(b => b.Text == "Enter world").EmitSignal(BaseButton.SignalName.Pressed);
                Expect("invalid server revealed and focused", server.IsVisibleInTree() && server.HasFocus());
                Expect("local validation retained", HasText(fresh, address == "" ? "The server address is required."
                    : "Not a server address: 'invalid address' (expected host:port or http(s)://host:port)."));
            }
            finally { fresh.Free(); }
        }
        await CheckLayoutAsync(host);
        return "loginlook title=ok server=ok focus=ok submit=ok errors=7 boot=ok layout=900p/4K/narrow";
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
