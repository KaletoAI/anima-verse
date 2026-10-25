using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The location names of the overview (client3d/src/scene/places.ts <c>buildPlace</c>, the <c>.loc-label</c> CSS):
/// one label per known place that is NOT an area location (<c>!map3d.area_model</c> — buildings, nature sites
/// included), the location's name in a serif, small capitals, 15 px, gold with a dark shadow, centred on the point
/// <see cref="OverviewLabels.LocationLabelLift"/> above the place's ground datum (its height: measured from the model or
/// shell when built, else <c>buildPlace</c>'s reading height). No distance LOD, not depth-tested. The browser hides a
/// label while an open interior fades its tile out (<c>applyTileOcclusion</c>); this client has no such fade yet, so
/// its labels always show.
/// </summary>
public sealed class LocationLabels
{
    private readonly Dictionary<string, PlaceLabel> _labels = new();

    /// <summary>The labels by location id (for the check).</summary>
    public IReadOnlyDictionary<string, PlaceLabel> Labels => _labels;

    /// <summary>
    /// Bring the labels in step with the world's places (<paramref name="known"/>: every place the world took in,
    /// built or not) and their latest rows (name, kind): a place without a row keeps its last label (<c>places</c>
    /// keeps its record), a place the world dropped loses it.
    /// </summary>
    public void Sync(IEnumerable<string> known, IReadOnlyDictionary<string, LocationInfo> rows)
    {
        var keep = new HashSet<string>(known);
        foreach (var id in keep)
        {
            if (!rows.TryGetValue(id, out var row)) continue;
            var (isBuilding, _) = LocationView.Kind(row);
            if (!isBuilding)
            {
                _labels.Remove(id);
                continue;
            }
            if (_labels.TryGetValue(id, out var label)) label.SetName(row.Name);
            else _labels[id] = new PlaceLabel(id, row.Name);
        }
        foreach (var gone in _labels.Keys.Where(id => !keep.Contains(id)).ToList()) _labels.Remove(gone);
    }

    /// <summary>The labels this frame, anchored above their places (<paramref name="placeOf"/> as for the event pins).</summary>
    public IEnumerable<IOverlayLabel> Visible(Func<string, (double X, double GroundY, double Z, double Height)?> placeOf)
    {
        foreach (var (id, label) in _labels)
        {
            if (placeOf(id) is not { } p) continue;
            label.Anchor = new Vector3((float)p.X, (float)(p.GroundY + OverviewLabels.LocationLabelLift(p.Height)), (float)p.Z);
            yield return label;
        }
    }

    /// <summary>One location's name.</summary>
    public sealed class PlaceLabel : IOverlayLabel
    {
        private TextLine _line = new();

        public PlaceLabel(string id, string name)
        {
            Id = id;
            SetName(name, force: true);
        }

        public string Id { get; }
        public string Name { get; private set; } = "";
        public Vector3 Anchor { get; internal set; }
        public Vector2 Size { get; private set; }

        internal void SetName(string name, bool force = false)
        {
            if (!force && name == Name) return;
            Name = name;
            _line = SmallCaps(name);
            Size = name.Length > 0 ? _line.GetSize() : Vector2.Zero;
        }

        /// <summary>
        /// <c>font-variant: small-caps</c> as the browser synthesises it when the font has no small capitals: every
        /// lower-case letter that has a capital is drawn as that capital at 70 % of the size, the rest at full size.
        /// </summary>
        public static TextLine SmallCaps(string text)
        {
            var line = new TextLine();
            int small = (int)Math.Round(LabelStyle.LocSize * LabelStyle.LocSmallCapsScale);
            int i = 0;
            while (i < text.Length)
            {
                bool lower = IsSmall(text, i);
                int j = i;
                while (j < text.Length && IsSmall(text, j) == lower) j += char.IsSurrogatePair(text, j) ? 2 : 1;
                var run = text[i..j];
                line.AddString(lower ? run.ToUpperInvariant() : run, LabelStyle.Serif, lower ? small : LabelStyle.LocSize);
                i = j;
            }
            return line;
        }

        private static bool IsSmall(string s, int i)
            => char.IsLower(s[i]) && char.ToUpperInvariant(s[i]) != s[i];

        public void Draw(CanvasItem canvas, Vector2 topLeft)
        {
            if (Name.Length == 0) return;
            LabelStyle.DrawText(canvas, _line, topLeft, LabelStyle.LocColor, LabelStyle.LocShadow);
        }
    }
}
