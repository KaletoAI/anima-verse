using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Overview;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// World-placeable room items mounted under a near location's tile group (<c>GET /play/locations/{id}/items</c>):
/// each item renders as its cached GLB mesh (scaled so its longest AABB edge equals <see cref="WorldItem.SizeM"/>,
/// bottom at anchor Y, turned by <see cref="WorldItem.Yaw"/>) or as a camera-facing billboard card (or small neutral
/// placeholder quad when neither model nor image exists), wearing a soft warm aura only in the avatar's confirmed room.
/// Ownership ledger: every mesh, material duplicate, aura ShaderMaterial and decoded card ImageTexture created by this
/// layer is tracked in <see cref="_owned"/> and disposed on removal / <see cref="Unmount"/>; <see cref="ModelCache"/>
/// templates are never mutated or freed.
/// </summary>
public partial class ItemsLayer : Node3D
{
    public const float BaseAuraIntensity = 0.28f;
    public const float HoverAuraIntensity = 0.58f;
    private const double MinPlaceholderM = 0.10;
    private const double MaxPlaceholderM = 0.22;
    private const double MinPickHalfExtentM = 0.025;

    private static Shader? _auraShader;
    private static bool _auraShaderChecked;

    private sealed class Entry
    {
        public required (string RoomId, string ItemId) Key;
        public required WorldItem Item;
        public required Node3D Root;
        public Node3D? Visual;
        public MeshInstance3D? CardMesh;
        public Aabb LocalModelBox;
        public bool IsCard;
        public double CardWidth;
        public double CardHeight;
        public ShaderMaterial? Aura;
        public readonly List<Material> SurfaceMaterials = new();
        public readonly List<Resource> Resources = new();
        public int LoadToken;
        public bool Disposed;
    }

    private readonly Dictionary<(string RoomId, string ItemId), Entry> _entries = new();
    private readonly HashSet<Resource> _owned = new();
    private readonly HashSet<Task> _pending = new();

    private LocationSlot? _slot;
    private ModelCache? _models;
    private Func<string, Task<ImageTexture?>>? _loadPicture;
    private string? _confirmedRoom;
    private (string RoomId, string ItemId)? _hovered;
    private bool _mounted;
    private int _mountGeneration;

    public int ItemCount => _entries.Count;
    public int OwnedResourceCount => _owned.Count;
    public string? ConfirmedRoom => _confirmedRoom;
    public bool IsMounted => _mounted;

    public IReadOnlyList<WorldItem> Items => _entries.Values.Select(e => e.Item).ToArray();
    public IReadOnlyList<Node3D> ItemNodes => _entries.Values.Select(e => e.Root).ToArray();

    public Node3D? GetItemNode(string roomId, string itemId)
        => _entries.TryGetValue((roomId, itemId), out var e) ? e.Root : null;

    /// <summary>The item's visual AABB in its own unrotated frame (origin at the item anchor).</summary>
    public Aabb? LocalItemAabb(string roomId, string itemId)
    {
        if (!_entries.TryGetValue((roomId, itemId), out var e) || e.Visual is null || !GodotObject.IsInstanceValid(e.Visual))
            return null;
        return ModelPlacement.Measure(e.Visual, Transform3D.Identity);
    }

    public void Mount(LocationSlot slot, ModelCache models, Func<string, Task<ImageTexture?>>? loadPicture = null)
        => Mount(slot.Group, models, loadPicture, slot);

    public void Mount(Node3D tileParent, ModelCache models, Func<string, Task<ImageTexture?>>? loadPicture = null, LocationSlot? slot = null)
    {
        if (_mounted) Unmount();
        _mountGeneration++;
        _slot = slot;
        _models = models;
        _loadPicture = loadPicture;
        _mounted = true;
        if (GetParent() != tileParent)
        {
            GetParent()?.RemoveChild(this);
            tileParent.AddChild(this);
        }
    }

    public Task Apply(IReadOnlyList<WorldItem> items)
    {
        if (!_mounted || _models is null) return Task.CompletedTask;

        var incoming = new Dictionary<(string RoomId, string ItemId), WorldItem>(items.Count);
        foreach (var item in items)
            incoming[(item.RoomId, item.ItemId)] = item;

        foreach (var key in _entries.Keys.Where(k => !incoming.ContainsKey(k)).ToArray())
        {
            ReleaseEntry(_entries[key]);
            _entries.Remove(key);
        }

        foreach (var (key, item) in incoming)
        {
            if (_entries.TryGetValue(key, out var existing))
            {
                bool shapeChanged = existing.Item.ModelUrl != item.ModelUrl
                                    || existing.Item.ImageUrl != item.ImageUrl
                                    || Math.Abs(existing.Item.SizeM - item.SizeM) > 1e-6;
                existing.Item = item;
                if (shapeChanged)
                {
                    RebuildEntryVisual(existing);
                }
                else
                {
                    UpdateEntryTransform(existing);
                    ApplyEntryAura(existing);
                }
            }
            else
            {
                var root = new Node3D { Name = NodeName($"Item_{item.RoomId}_{item.ItemId}") };
                AddChild(root);
                var created = new Entry
                {
                    Key = key,
                    Item = item,
                    Root = root,
                };
                _entries[key] = created;
                RebuildEntryVisual(created);
            }
        }

        SyncVisibility();
        return WhenIdleAsync();
    }

    public Task WhenIdleAsync() => _pending.Count == 0 ? Task.CompletedTask : Task.WhenAll(_pending.ToArray());

    public void SetConfirmedRoom(string? roomId)
    {
        if (_confirmedRoom == roomId) return;
        _confirmedRoom = roomId;
        foreach (var entry in _entries.Values) ApplyEntryAura(entry);
    }

    public void SetHovered(string? roomId, string? itemId)
    {
        (string RoomId, string ItemId)? next = roomId is not null && itemId is not null ? (roomId, itemId) : null;
        if (_hovered == next) return;
        var prev = _hovered;
        _hovered = next;
        if (prev is { } p && _entries.TryGetValue(p, out var oldEntry)) ApplyEntryAura(oldEntry);
        if (next is { } n && _entries.TryGetValue(n, out var newEntry)) ApplyEntryAura(newEntry);
    }

    /// <summary>Re-seat items when the tile's terrain datum or storey-0 floor heights change.</summary>
    public void Relift()
    {
        if (!_mounted) return;
        foreach (var entry in _entries.Values) UpdateEntryTransform(entry);
    }

    /// <summary>Follow the mounted location's interior crossfade and active storey filter.</summary>
    public void SyncVisibility()
    {
        if (!_mounted) return;
        foreach (var entry in _entries.Values)
        {
            if (!GodotObject.IsInstanceValid(entry.Root)) continue;
            bool visible = true;
            if (_slot is { } slot)
            {
                string canonical = slot.RoomIdOf(entry.Item.RoomId) ?? entry.Item.RoomId;
                if (slot.Storeys.Rooms.TryGetValue(canonical, out var rg))
                {
                    bool indoorHidden = !rg.Outdoor && slot.Fade.Interior is { Visible: false };
                    visible = rg.Node.Visible && !indoorHidden;
                }
                else if (slot.Scene is { } scene && !LocationView.IsOutdoor(scene, canonical) && slot.Fade.Interior is { Visible: false })
                {
                    visible = false;
                }
            }
            if (entry.Root.Visible != visible) entry.Root.Visible = visible;
        }
    }

    /// <summary>Nearest item hit by the world-space ray, or null.</summary>
    public WorldItem? Hit(Vec3 origin, Vec3 direction) => HitDetail(origin, direction)?.Item;

    public WorldItem? Hit(Vector3 origin, Vector3 direction)
        => HitDetail(new Vec3(origin.X, origin.Y, origin.Z), new Vec3(direction.X, direction.Y, direction.Z))?.Item;

    public (WorldItem Item, double Distance)? HitDetail(Vec3 origin, Vec3 direction, Func<WorldItem, bool>? predicate = null)
    {
        if (!_mounted || _entries.Count == 0) return null;
        double len = Math.Sqrt(direction.X * direction.X + direction.Y * direction.Y + direction.Z * direction.Z);
        if (len <= 1e-12) return null;
        var dir = new Vec3(direction.X / len, direction.Y / len, direction.Z / len);

        WorldItem? best = null;
        double bestT = double.PositiveInfinity;

        foreach (var entry in _entries.Values)
        {
            if (entry.Disposed || !GodotObject.IsInstanceValid(entry.Root)) continue;
            if (!entry.Root.Visible || (entry.Root.IsInsideTree() && !entry.Root.IsVisibleInTree())) continue;
            if (predicate is not null && !predicate(entry.Item)) continue;

            var (min, max) = WorldPickBounds(entry);
            if (RayMath.RayBox(origin, dir, min, max) is double t && t < bestT)
            {
                bestT = t;
                best = entry.Item;
            }
        }

        return best is null ? null : (best, bestT);
    }

    public bool IsInConfirmedRoom(string itemRoomId)
    {
        if (string.IsNullOrEmpty(_confirmedRoom) || string.IsNullOrEmpty(itemRoomId)) return false;
        if (_slot is { } slot)
        {
            string a = slot.RoomIdOf(itemRoomId) ?? itemRoomId;
            string b = slot.RoomIdOf(_confirmedRoom) ?? _confirmedRoom;
            return a.Length > 0 && a == b;
        }
        return itemRoomId == _confirmedRoom;
    }

    /// <summary>World-space anchor (bottom center) of an item in this layer.</summary>
    public Vec3 WorldAnchorOf(WorldItem item)
    {
        double ly = LocalBottomY(item);
        if (_slot is { } slot && GodotObject.IsInstanceValid(slot.Group))
        {
            var g = slot.Group.Position;
            var frame = new TileFrame(new Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y);
            return SceneView.TileToWorld(frame, item.X, item.Z, ly);
        }
        var xf = IsInsideTree() ? GlobalTransform : ChainFromRoot(this);
        var p = xf * new Vector3((float)item.X, (float)ly, (float)item.Z);
        return new Vec3(p.X, p.Y, p.Z);
    }

    public void Unmount()
    {
        _mountGeneration++;
        _mounted = false;
        _hovered = null;
        foreach (var entry in _entries.Values) ReleaseEntry(entry);
        _entries.Clear();
        if (_owned.Count > 0)
        {
            foreach (var res in _owned.ToArray()) res.Dispose();
            _owned.Clear();
        }
        _slot = null;
        _models = null;
        _loadPicture = null;
        if (IsInstanceValid(this)) GetParent()?.RemoveChild(this);
    }

    public override void _ExitTree()
    {
        if (!_mounted && _entries.Count == 0 && _owned.Count == 0) return;
        _mountGeneration++;
        _mounted = false;
        _hovered = null;
        foreach (var entry in _entries.Values) ReleaseEntry(entry);
        _entries.Clear();
        foreach (var res in _owned.ToArray()) res.Dispose();
        _owned.Clear();
    }

    private void RebuildEntryVisual(Entry entry)
    {
        int token = ++entry.LoadToken;
        int gen = _mountGeneration;
        ReleaseVisualOnly(entry);
        UpdateEntryTransform(entry);

        if (entry.Item.ModelUrl is { Length: > 0 } modelUrl && _models is { } cache)
        {
            // Keep an immediate placeholder card while the GLB loads so the entry always has a pickable node.
            BuildCardVisual(entry, withImageLoad: false);
            TrackTask(LoadGlbVisualAsync(entry, modelUrl, cache, token, gen));
        }
        else
        {
            BuildCardVisual(entry, withImageLoad: true);
        }
    }

    private async Task LoadGlbVisualAsync(Entry entry, string modelUrl, ModelCache cache, int token, int gen)
    {
        var template = await cache.GetAsync(modelUrl);
        if (!_mounted || gen != _mountGeneration || entry.Disposed || entry.LoadToken != token) return;

        if (template is null)
        {
            // Fall back to the image card (or neutral placeholder) if the GLB failed to load.
            ReleaseVisualOnly(entry);
            BuildCardVisual(entry, withImageLoad: true);
            return;
        }

        ReleaseVisualOnly(entry);
        entry.IsCard = false;
        UpdateEntryTransform(entry);

        var instance = ModelCache.Instance(template);
        var rawBox = ModelPlacement.Measure(instance, Transform3D.Identity);
        double maxEdge = Math.Max(rawBox.Size.X, Math.Max(rawBox.Size.Y, rawBox.Size.Z));
        double sizeM = entry.Item.SizeM > 0 ? entry.Item.SizeM : 0.25;
        double scale = maxEdge > 1e-6 ? sizeM / maxEdge : 1.0;

        double cx = rawBox.Position.X + rawBox.Size.X * 0.5;
        double cz = rawBox.Position.Z + rawBox.Size.Z * 0.5;
        double minY = rawBox.Position.Y;

        var aura = CreateAuraMaterial(entry, billboard: false);
        PrepareGlbMeshes(entry, instance);

        float s = (float)scale;
        var holder = new Node3D
        {
            Name = "Model",
            Scale = new Vector3(s, s, s),
            Position = new Vector3((float)(-cx * scale), (float)(-minY * scale), (float)(-cz * scale)),
        };
        holder.AddChild(instance);
        entry.Root.AddChild(holder);
        entry.Visual = holder;
        entry.LocalModelBox = ModelPlacement.Measure(holder, Transform3D.Identity);
        entry.Aura = aura;
        ApplyEntryAura(entry);
    }

    private void PrepareGlbMeshes(Entry entry, Node root)
    {
        if (root is MeshInstance3D mi)
        {
            mi.CastShadow = GeometryInstance3D.ShadowCastingSetting.Off;
            mi.SetMeta(LocationFade.OverlayMeta, true);
            if (mi.Mesh is { } mesh)
            {
                int count = mesh.GetSurfaceCount();
                for (int i = 0; i < count; i++)
                {
                    var src = mi.GetSurfaceOverrideMaterial(i) ?? mesh.SurfaceGetMaterial(i);
                    Material dup = src is not null
                        ? Own(entry, (Material)src.Duplicate())
                        : Own(entry, new StandardMaterial3D
                        {
                            AlbedoColor = new Color(0.82f, 0.78f, 0.72f, 1f),
                            Roughness = 0.85f,
                        });
                    mi.SetSurfaceOverrideMaterial(i, dup);
                    entry.SurfaceMaterials.Add(dup);
                }
            }
        }
        else if (root is GeometryInstance3D gi)
        {
            gi.CastShadow = GeometryInstance3D.ShadowCastingSetting.Off;
            gi.SetMeta(LocationFade.OverlayMeta, true);
        }

        foreach (var child in root.GetChildren())
            PrepareGlbMeshes(entry, child);
    }

    private void BuildCardVisual(Entry entry, bool withImageLoad)
    {
        entry.IsCard = true;
        UpdateEntryTransform(entry);

        bool hasImage = withImageLoad && entry.Item.ImageUrl is { Length: > 0 };
        double sizeM = entry.Item.SizeM > 0 ? entry.Item.SizeM : 0.25;
        double h = hasImage ? Math.Max(0.05, sizeM) : Math.Clamp(sizeM, MinPlaceholderM, MaxPlaceholderM);
        double w = h;

        var quad = Own(entry, new QuadMesh { Size = new Vector2((float)w, (float)h) });
        var mat = Own(entry, new StandardMaterial3D
        {
            BillboardMode = BaseMaterial3D.BillboardModeEnum.Enabled,
            BillboardKeepScale = true,
            ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
            Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
            CullMode = BaseMaterial3D.CullModeEnum.Disabled,
            AlbedoColor = hasImage
                ? new Color(0.92f, 0.89f, 0.82f, 0.95f)
                : new Color(0.78f, 0.73f, 0.64f, 0.85f),
        });

        var aura = CreateAuraMaterial(entry, billboard: true);
        entry.Aura = aura;
        entry.SurfaceMaterials.Add(mat);

        var meshInst = new MeshInstance3D
        {
            Name = hasImage ? "Card" : "Placeholder",
            Mesh = quad,
            MaterialOverride = mat,
            CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
            Position = new Vector3(0, (float)(h * 0.5), 0),
        };
        meshInst.SetMeta(LocationFade.OverlayMeta, true);

        var holder = new Node3D { Name = "CardHolder" };
        holder.AddChild(meshInst);
        entry.Root.AddChild(holder);
        entry.Visual = holder;
        entry.CardMesh = meshInst;
        entry.CardWidth = w;
        entry.CardHeight = h;
        ApplyEntryAura(entry);

        if (hasImage && _loadPicture is { } loader && entry.Item.ImageUrl is { } imageUrl)
        {
            int token = entry.LoadToken;
            int gen = _mountGeneration;
            TrackTask(LoadCardTextureAsync(entry, quad, mat, imageUrl, loader, h, token, gen));
        }
    }

    private async Task LoadCardTextureAsync(
        Entry entry,
        QuadMesh quad,
        StandardMaterial3D mat,
        string url,
        Func<string, Task<ImageTexture?>> loader,
        double heightM,
        int token,
        int gen)
    {
        var tex = await loader(url);
        if (tex is null) return;
        if (!_mounted || gen != _mountGeneration || entry.Disposed || entry.LoadToken != token || !entry.Resources.Contains(mat))
        {
            tex.Dispose();
            return;
        }
        Own(entry, tex);
        mat.AlbedoTexture = tex;
        mat.AlbedoColor = Colors.White;
        int tw = tex.GetWidth(), th = tex.GetHeight();
        if (tw > 0 && th > 0)
        {
            double aspect = Math.Clamp((double)tw / th, 0.25, 3.0);
            double widthM = heightM * aspect;
            quad.Size = new Vector2((float)widthM, (float)heightM);
            entry.CardWidth = widthM;
        }
    }

    private ShaderMaterial? CreateAuraMaterial(Entry entry, bool billboard)
    {
        var shader = GetAuraShader();
        if (shader is null) return null;
        var mat = Own(entry, new ShaderMaterial { Shader = shader });
        mat.SetShaderParameter("billboard", billboard);
        mat.SetShaderParameter("intensity", BaseAuraIntensity);
        return mat;
    }

    private void ApplyEntryAura(Entry entry)
    {
        bool show = IsInConfirmedRoom(entry.Item.RoomId);
        if (entry.Aura is { } aura)
        {
            float want = _hovered == entry.Key ? HoverAuraIntensity : BaseAuraIntensity;
            aura.SetShaderParameter("intensity", want);
        }
        var nextPass = show ? entry.Aura : null;
        foreach (var mat in entry.SurfaceMaterials)
            mat.NextPass = nextPass;
    }

    private void UpdateEntryTransform(Entry entry)
    {
        if (!GodotObject.IsInstanceValid(entry.Root)) return;
        double bottomY = LocalBottomY(entry.Item);
        var pos = new Vector3((float)entry.Item.X, (float)bottomY, (float)entry.Item.Z);
        var basis = entry.IsCard
            ? Basis.Identity
            : ModelPlacement.ToBasis(Mat3.RotY(entry.Item.Yaw * Math.PI / 180.0));
        entry.Root.Transform = new Transform3D(basis, pos);
    }

    private double LocalBottomY(WorldItem item)
    {
        double floorLocalY = 0;
        if (_slot?.Scene is { } scene)
        {
            string canonical = _slot.RoomIdOf(item.RoomId) ?? item.RoomId;
            Figures.RoomFloor? roomFloor = null;
            foreach (var kv in _slot.Stands.RoomFloors)
                if (kv.Key == canonical || kv.Key == item.RoomId) { roomFloor = kv.Value; break; }

            if (roomFloor?.Declared is double declared)
            {
                floorLocalY = declared;
            }
            else
            {
                int level = _slot.Stands.RoomLevels.TryGetValue(canonical, out int lv) ? lv
                    : _slot.Storeys.Rooms.TryGetValue(canonical, out var rg) ? rg.Level : 0;
                double baseY = scene.FloorY(level);
                double lift = 0;
                if (level == 0 && _slot.Stands.WorldGround is { } groundAt)
                {
                    var g = _slot.Group.Position;
                    var frame = new TileFrame(new Vec3(g.X, g.Y, g.Z), _slot.Group.Rotation.Y);
                    var w = SceneView.TileToWorld(frame, item.X, item.Z);
                    lift = StoreyGround.Lift(0, w.X, w.Z, g.Y, groundAt);
                }
                floorLocalY = baseY + lift;
            }
        }
        return floorLocalY + item.Y;
    }

    private (Vec3 Min, Vec3 Max) WorldPickBounds(Entry entry)
    {
        var worldXf = entry.Root.IsInsideTree() ? entry.Root.GlobalTransform : ChainFromRoot(entry.Root);
        if (entry.IsCard)
        {
            var o = worldXf.Origin;
            double halfW = Math.Max(MinPickHalfExtentM, entry.CardWidth * 0.5);
            double h = Math.Max(MinPickHalfExtentM * 2, entry.CardHeight);
            return (new Vec3(o.X - halfW, o.Y, o.Z - halfW), new Vec3(o.X + halfW, o.Y + h, o.Z + halfW));
        }

        var localBox = entry.LocalModelBox.Size != Vector3.Zero
            ? entry.LocalModelBox
            : new Aabb(new Vector3(-0.1f, 0, -0.1f), new Vector3(0.2f, 0.2f, 0.2f));
        var worldBox = worldXf * localBox;
        var c = worldBox.GetCenter();
        double hx = Math.Max(MinPickHalfExtentM, worldBox.Size.X * 0.5);
        double hy = Math.Max(MinPickHalfExtentM, worldBox.Size.Y * 0.5);
        double hz = Math.Max(MinPickHalfExtentM, worldBox.Size.Z * 0.5);
        return (new Vec3(c.X - hx, c.Y - hy, c.Z - hz), new Vec3(c.X + hx, c.Y + hy, c.Z + hz));
    }

    private static Transform3D ChainFromRoot(Node3D node)
    {
        var xf = Transform3D.Identity;
        for (Node? cur = node; cur is not null; cur = cur.GetParent())
            if (cur is Node3D n3) xf = n3.Transform * xf;
        return xf;
    }

    private T Own<T>(Entry entry, T resource) where T : Resource
    {
        _owned.Add(resource);
        entry.Resources.Add(resource);
        return resource;
    }

    private void ReleaseVisualOnly(Entry entry)
    {
        foreach (var mat in entry.SurfaceMaterials) mat.NextPass = null;
        entry.SurfaceMaterials.Clear();
        entry.Aura = null;
        entry.CardMesh = null;
        entry.LocalModelBox = default;

        if (entry.Visual is { } vis && GodotObject.IsInstanceValid(vis))
        {
            StripNodeResources(vis);
            vis.GetParent()?.RemoveChild(vis);
            vis.Free();
        }
        entry.Visual = null;

        foreach (var res in entry.Resources)
        {
            _owned.Remove(res);
            res.Dispose();
        }
        entry.Resources.Clear();
    }

    private void ReleaseEntry(Entry entry)
    {
        entry.Disposed = true;
        entry.LoadToken++;
        ReleaseVisualOnly(entry);
        if (GodotObject.IsInstanceValid(entry.Root))
        {
            entry.Root.GetParent()?.RemoveChild(entry.Root);
            entry.Root.Free();
        }
    }

    private static void StripNodeResources(Node node)
    {
        if (node is MeshInstance3D mi)
        {
            if (mi.Mesh is { } m)
            {
                int count = m.GetSurfaceCount();
                for (int i = 0; i < count; i++) mi.SetSurfaceOverrideMaterial(i, null);
            }
            mi.MaterialOverride = null;
            mi.MaterialOverlay = null;
            mi.Mesh = null;
        }
        foreach (var child in node.GetChildren())
            StripNodeResources(child);
    }

    private void TrackTask(Task task)
    {
        _pending.Add(task);
        _ = ForgetTaskAsync(task);
    }

    private async Task ForgetTaskAsync(Task task)
    {
        try { await task; }
        finally { _pending.Remove(task); }
    }

    private static Shader? GetAuraShader()
    {
        if (_auraShaderChecked) return _auraShader;
        _auraShaderChecked = true;
        Shader? shader = null;
        if (ResourceLoader.Exists("res://World/ItemAura.gdshader"))
            shader = GD.Load<Shader>("res://World/ItemAura.gdshader");
        if (shader is null)
        {
            string diskPath = ProjectSettings.GlobalizePath("res://World/ItemAura.gdshader");
            if (File.Exists(diskPath))
                shader = new Shader { Code = File.ReadAllText(diskPath) };
        }
        if (shader is not null && !ShaderSafety.Ok(shader, "item_aura"))
            shader = null;
        _auraShader = shader;
        return _auraShader;
    }

    private static string NodeName(string raw)
    {
        var chars = raw.ToCharArray();
        for (int i = 0; i < chars.Length; i++)
            if (chars[i] is '.' or ':' or '@' or '/' or '"' or '%') chars[i] = '_';
        return new string(chars);
    }
}
