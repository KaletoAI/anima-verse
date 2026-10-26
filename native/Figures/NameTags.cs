using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// The name tags of the overview (client3d/src/scene/npcs.ts: the CSS2D label of every figure, <c>say</c>, the tag
/// part of <c>update</c> and <c>tick</c>): per figure a centred column [speech bubble, name, activity] over the head.
///
///   • TEXT per poll — the name with the travel prefix (<see cref="OverviewLabels.TagName"/>), the activity
///     (<c>activity || ''</c>, an empty line takes no room), the avatar's name in gold.
///   • ANCHOR — the figure's root + <see cref="OverviewLabels.TagAnchorY"/> of <see cref="Figure.TagHeight"/> (a model's
///     height; a portrait has none, so its tag sits below the sprite).
///   • VISIBILITY per frame — <see cref="OverviewLabels.TagVisible"/> with the camera's eased distance; a hidden
///     figure hides its tag; there is no first-person body in this client yet (E7).
///   • BUBBLE — <c>say(name, text)</c>: unknown names are ignored, a new line replaces the old one, the text is
///     <see cref="Bubble.Text"/>, it stays <see cref="Bubble.Ms"/> ms (checked every frame, <c>now ≥ until</c>
///     hides it). Box: padding 5/9 px, 1 px border, radius 10, 11 px text on 1.35 lines, centred, at most 22ch
///     wide (border box) and wrapping inside it.
/// </summary>
public sealed class NameTags
{
    private readonly FigureManager _figures;
    private readonly Func<double> _nowMs;
    private readonly Dictionary<string, Tag> _tags = new();

    /// <summary>The camera's eased distance to its target (engine.ts <c>dist</c>) — the tag rule's input.</summary>
    public Func<double> CamDist { get; set; } = () => 0;

    public NameTags(FigureManager figures, Func<double> nowMs)
    {
        _figures = figures;
        _nowMs = nowMs;
    }

    /// <summary>The tags by character name (for the check).</summary>
    public IReadOnlyDictionary<string, Tag> Tags => _tags;

    /// <summary>
    /// A poll (npcs.ts <c>update</c>, the label part): a tag per figure on the map with the row's texts; the tags of
    /// figures that left go with them.
    /// </summary>
    public void Apply(JsonElement map)
    {
        var (rows, avatar) = OverviewLabels.RowsOf(map);
        foreach (var row in rows)
        {
            if (!_figures.Figures.ContainsKey(row.Name)) continue;
            if (!_tags.TryGetValue(row.Name, out var tag)) _tags[row.Name] = tag = new Tag(row.Name);
            tag.SetText(OverviewLabels.TagName(row.Name, row.Travel), row.Activity, row.Name == avatar);
        }
        foreach (var gone in _tags.Keys.Where(n => !_figures.Figures.ContainsKey(n)).ToList()) _tags.Remove(gone);
    }

    /// <summary><c>say(name, text)</c>: the HUD's <c>sayBubble</c>. False when the name has no figure or the text is blank.</summary>
    public bool Say(string name, string text)
    {
        if (!_tags.TryGetValue(name, out var tag) || !_figures.Figures.ContainsKey(name)) return false;
        var shown = Bubble.Text(text);
        if (shown.Length == 0) return false;
        tag.SetBubble(shown, _nowMs() + Bubble.Ms(text));
        return true;
    }

    /// <summary>The tick's bubble sweep: a bubble whose time is up goes (<c>now ≥ bubbleUntil</c>).</summary>
    public void Expire()
    {
        double now = _nowMs();
        foreach (var tag in _tags.Values) tag.ExpireAt(now);
    }

    /// <summary>The tags that show this frame (the overlay's source), anchored over their figures.</summary>
    public IEnumerable<IOverlayLabel> Visible()
    {
        double camDist = CamDist();
        foreach (var (name, tag) in _tags)
        {
            if (!_figures.Figures.TryGetValue(name, out var fig) || !GodotObject.IsInstanceValid(fig) || !fig.IsInsideTree()) continue;
            if (!OverviewLabels.TagVisible(camDist, hidden: !fig.IsVisibleInTree(), ownFirstPerson: false)) continue;
            tag.Anchor = fig.GlobalPosition + new Vector3(0, (float)OverviewLabels.TagAnchorY(fig.TagHeight), 0);
            yield return tag;
        }
    }

    /// <summary>One figure's label column.</summary>
    public sealed class Tag : IOverlayLabel
    {
        private TextLine _name = new(), _activity = new();
        private TextParagraph? _bubble;
        private Vector2 _bubbleBox, _size;

        public Tag(string character) => Character = character;

        public string Character { get; }
        public string NameText { get; private set; } = "";
        public string ActivityText { get; private set; } = "";
        public bool IsAvatar { get; private set; }
        public string BubbleText { get; private set; } = "";
        public double BubbleUntilMs { get; private set; }
        /// <summary>The bubble's border box (0 × 0 without a bubble) and its line count.</summary>
        public Vector2 BubbleBoxSize => _bubbleBox;
        public int BubbleLines => _bubble?.GetLineCount() ?? 0;
        public Vector3 Anchor { get; internal set; }
        public Vector2 Size => _size;

        internal void SetText(string name, string activity, bool avatar)
        {
            if (name == NameText && activity == ActivityText && avatar == IsAvatar && _size != Vector2.Zero) return;
            NameText = name;
            ActivityText = activity;
            IsAvatar = avatar;
            _name = LabelStyle.Line(name, LabelStyle.SansSemiBold, LabelStyle.NameSize);
            _activity = LabelStyle.Line(activity, LabelStyle.Sans, LabelStyle.ActivitySize);
            Layout();
        }

        internal void SetBubble(string text, double untilMs)
        {
            BubbleText = text;
            BubbleUntilMs = untilMs;
            float maxBox = BubbleMaxWidth();
            float maxText = maxBox - 2 * (LabelStyle.BubblePadX + LabelStyle.BubbleBorder);
            float oneLine = LabelStyle.Line(text, LabelStyle.Sans, LabelStyle.BubbleSize).GetSize().X;
            // Shrink-to-fit under max-width: one line when it fits, else the full 22ch with the text wrapped.
            float textWidth = Math.Min(oneLine, maxText);
            var para = new TextParagraph
            {
                Width = textWidth + 0.5f,   // the measured line must not wrap on rounding
                BreakFlags = TextServer.LineBreakFlag.Mandatory | TextServer.LineBreakFlag.WordBound,
                Alignment = HorizontalAlignment.Center,
            };
            para.AddString(text, LabelStyle.Sans, LabelStyle.BubbleSize);
            _bubble = para;
            float boxW = textWidth + 2 * (LabelStyle.BubblePadX + LabelStyle.BubbleBorder);
            float boxH = para.GetLineCount() * LabelStyle.BubbleLineHeight + 2 * (LabelStyle.BubblePadY + LabelStyle.BubbleBorder);
            _bubbleBox = new Vector2(boxW, boxH);
            Layout();
        }

        internal void ExpireAt(double nowMs)
        {
            if (_bubble is null || BubbleUntilMs == 0 || nowMs < BubbleUntilMs) return;
            _bubble = null;
            BubbleText = "";
            BubbleUntilMs = 0;
            _bubbleBox = Vector2.Zero;
            Layout();
        }

        /// <summary><c>22ch</c>: 22 advances of "0" in the bubble font.</summary>
        public static float BubbleMaxWidth()
            => LabelStyle.BubbleMaxCh * LabelStyle.Sans.GetStringSize("0", HorizontalAlignment.Left, -1, LabelStyle.BubbleSize).X;

        /// <summary>The flex column: widest item wide, the items' heights stacked (an empty line is 0 high).</summary>
        private void Layout()
        {
            var name = NameText.Length > 0 ? _name.GetSize() : Vector2.Zero;
            var act = ActivityText.Length > 0 ? _activity.GetSize() : Vector2.Zero;
            float w = Math.Max(Math.Max(name.X, act.X), _bubbleBox.X);
            float h = name.Y + act.Y + (_bubble is not null ? _bubbleBox.Y + LabelStyle.BubbleMarginBottom : 0);
            _size = new Vector2(w, h);
        }

        public void Draw(CanvasItem canvas, Vector2 topLeft)
        {
            float y = topLeft.Y;
            if (_bubble is { } para)
            {
                var box = new Rect2(topLeft.X + (_size.X - _bubbleBox.X) / 2, y, _bubbleBox);
                canvas.DrawStyleBox(LabelStyle.BubbleBox, box);
                var rid = canvas.GetCanvasItem();
                float lineTop = box.Position.Y + LabelStyle.BubbleBorder + LabelStyle.BubblePadY;
                float textLeft = box.Position.X + LabelStyle.BubbleBorder + LabelStyle.BubblePadX;
                for (int i = 0; i < para.GetLineCount(); i++)
                {
                    // CSS half-leading: the glyph box sits in the middle of its 1.35 line.
                    float glyphH = para.GetLineSize(i).Y;
                    var at = new Vector2(textLeft, lineTop + i * LabelStyle.BubbleLineHeight + (LabelStyle.BubbleLineHeight - glyphH) / 2);
                    para.DrawLine(rid, at, i, LabelStyle.BubbleText);
                }
                y += _bubbleBox.Y + LabelStyle.BubbleMarginBottom;
            }
            if (NameText.Length > 0)
            {
                var s = _name.GetSize();
                LabelStyle.DrawText(canvas, _name, new Vector2(topLeft.X + (_size.X - s.X) / 2, y),
                                    IsAvatar ? LabelStyle.AvatarColor : LabelStyle.NameColor, LabelStyle.NameShadow);
                y += s.Y;
            }
            if (ActivityText.Length > 0)
            {
                var s = _activity.GetSize();
                LabelStyle.DrawText(canvas, _activity, new Vector2(topLeft.X + (_size.X - s.X) / 2, y),
                                    LabelStyle.ActivityColor, LabelStyle.ActivityShadow);
            }
        }
    }
}
