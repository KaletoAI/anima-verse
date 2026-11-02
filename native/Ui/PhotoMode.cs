using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Photo;
using Godot;

namespace AnimaNative.Ui;

/// <summary>Explicit-user-action capture, cancellation and restore-before-upload lifecycle.</summary>
public partial class PhotoMode : Node
{
    public OverviewCamera Camera { get; set; } = null!;
    public Func<PhotoView> View { get; set; } = null!;
    public Func<IEnumerable<Node3D>> Markers { get; set; } = () => [];
    public Func<byte[],CancellationToken,Task<string>> Upload { get; set; } = null!;
    public Action<string,string,PhotoView> Screenshot { get; set; } = null!;
    public Action<string> Toast { get; set; } = _ => { };
    public Action<string> Log { get; set; } = _ => { };
    public Action<bool> Changed { get; set; } = _ => { };
    // The offline check supplies an image at the real FramePostDraw boundary on the dummy renderer.
    internal Func<Image>? Readback { get; set; }
    public bool Active => Camera.Photo.Active;
    public bool Busy { get; private set; }
    public Task Pending { get; private set; } = Task.CompletedTask;
    private CancellationTokenSource? _shot;
    private TaskCompletionSource<(Image Image,PhotoView View)>? _frame;
    private readonly Dictionary<CanvasLayer,bool> _layers = new();
    private readonly Dictionary<CanvasItem,bool> _items = new();
    private readonly Dictionary<Node3D,bool> _markers = new();
    private CanvasLayer? _hintLayer;
    private Label? _hint;

    public bool HandleInput(InputEvent input, bool typing)
    {
        if (input is InputEventKey key)
        {
            if (key.Keycode == Key.F11) return false;
            bool toggle=key.Keycode==Key.F2, escape=key.Keycode==Key.Escape;
            if ((toggle || ((Active || Busy) && escape)) && key.Pressed)
            {
                if (typing || key.CtrlPressed || key.MetaPressed || key.AltPressed) return false;
                if (!key.Echo)
                {
                    if (Active || Busy) Cancel(); else Enter();
                }
                return true;
            }
            if (Active && key.Keycode==Key.Space)
            {
                if (key.Pressed && !key.Echo && !Busy && !key.CtrlPressed && !key.MetaPressed && !key.AltPressed)
                { Busy=true; Pending=ShootAsync(); }
                return true;
            }
        }
        if (!Active) return false;
        Camera.PhotoInput(input);
        return true;
    }

    public void Enter()
    {
        if (Active || Busy) return;
        Camera.EnterPhoto(); Changed(true);
        _hintLayer ??= MakeHint();
        _hintLayer.Visible=true;
        RenderingServer.FramePreDraw += BeforeDraw;
        RenderingServer.FramePostDraw += AfterDraw;
        HideCanvas(GetTree().Root);
        UpdateHint();
    }

    private CanvasLayer MakeHint()
    {
        var layer=new CanvasLayer { Name="PhotoHint", Layer=100 };
        AddChild(layer);
        _hint=new Label { Position=new(16,16), MouseFilter=Control.MouseFilterEnum.Ignore };
        layer.AddChild(_hint);
        return layer;
    }

    public void Cancel()
    {
        _shot?.Cancel(); _frame?.TrySetCanceled(); _frame=null;
        RestoreMode();
    }

    private void RestoreMode()
    {
        if (!Active) return;
        RenderingServer.FramePreDraw -= BeforeDraw;
        RenderingServer.FramePostDraw -= AfterDraw;
        RestoreMarkers();
        Camera.LeavePhoto();
        foreach (var (layer,visible) in _layers) if (IsInstanceValid(layer)) layer.Visible=visible;
        foreach (var (item,visible) in _items) if (IsInstanceValid(item)) item.Visible=visible;
        _layers.Clear(); _items.Clear();
        if (_hintLayer is not null) _hintLayer.Visible=false;
        Changed(false);
    }

    private void HideCanvas(Node root, bool covered=false)
    {
        foreach (var child in root.GetChildren())
        {
            if (child is SubViewport || child==_hintLayer) continue;
            bool next=covered;
            if (child is CanvasLayer layer)
            {
                _layers.TryAdd(layer,layer.Visible); layer.Visible=false; next=true;
            }
            else if (!covered && child is CanvasItem item)
            {
                _items.TryAdd(item,item.Visible); item.Visible=false; next=true;
            }
            HideCanvas(child,next);
        }
    }

    private void BeforeDraw()
    {
        if (!Active) return;
        HideCanvas(GetTree().Root);
        foreach (var marker in Markers().Distinct())
            if (IsInstanceValid(marker)) { _markers.TryAdd(marker,marker.Visible); marker.Visible=false; }
    }

    private void RestoreMarkers()
    {
        foreach (var (node,visible) in _markers) if (IsInstanceValid(node)) node.Visible=visible;
        _markers.Clear();
    }

    private void AfterDraw()
    {
        var frame=_frame; _frame=null;
        try
        {
            if (frame is not null)
            {
                var view=View();
                var image=Readback?.Invoke() ?? GetViewport().GetTexture().GetImage();
                if (image is null || image.IsEmpty()) { image?.Dispose(); throw new InvalidOperationException("Photo capture failed"); }
                if (!frame.TrySetResult((image,view))) image.Dispose();
            }
        }
        catch (Exception e) { frame?.TrySetException(e); }
        finally { RestoreMarkers(); }
    }

    private async Task ShootAsync()
    {
        _shot=new CancellationTokenSource();
        var ct=_shot.Token;
        int width=0,height=0,bytes=0,names=0;
        long? uploadStart=null;
        string outcome="failed";
        try
        {
            _frame=new(); var frameTask=_frame.Task;
            UpdateHint();
            var frame=await frameTask;
            using var image=frame.Image;
            var encoded=await Task.Run(() => Encode(image));
            width=encoded.Width; height=encoded.Height; bytes=encoded.Bytes.Length; names=frame.View.visible.Count;
            ct.ThrowIfCancellationRequested();
            RestoreMode();
            uploadStart=Stopwatch.GetTimestamp();
            var id=await Upload(encoded.Bytes,ct);
            ct.ThrowIfCancellationRequested();
            Screenshot(id,AnimaApi.PhotoImageUrl(id),frame.View);
            outcome="ok";
        }
        catch (Exception e)
        {
            RestoreMode();
            if (ct.IsCancellationRequested) outcome="cancelled";
            else Toast($"Photo could not be taken: {e.Message}");
        }
        finally
        {
            double uploadMs=uploadStart is { } start ? Stopwatch.GetElapsedTime(start).TotalMilliseconds : 0;
            Log($"photo: {width}x{height}, {bytes} bytes, visible={names}, upload={uploadMs:0.#} ms, {outcome}");
            _shot.Dispose(); _shot=null; Busy=false; UpdateHint();
        }
    }

    internal static (byte[] Bytes,int Width,int Height) Encode(Image image)
    {
        int w=image.GetWidth(), h=image.GetHeight();
        double scale=Math.Min(1,2048d/Math.Max(w,h));
        if (scale<1) image.Resize(Math.Max(1,(int)Math.Round(w*scale,MidpointRounding.AwayFromZero)),
            Math.Max(1,(int)Math.Round(h*scale,MidpointRounding.AwayFromZero)),Image.Interpolation.Lanczos);
        var bytes=image.SaveJpgToBuffer(.9f);
        if (bytes.Length==0) throw new InvalidOperationException("Photo capture failed");
        return (bytes,image.GetWidth(),image.GetHeight());
    }

    private void UpdateHint()
    {
        if (_hint is null) return;
        _hint.Visible=Active && !Busy;
        _hint.Text=$"Photo mode · WASD move · Q/E down/up · Drag to look · Wheel speed {Camera.Photo.Speed:0.0} m/s · Shift ×3 · Space shot · F2/Esc leave";
    }

    public override void _Process(double delta)
    {
        if (!Active) return;
        HideCanvas(GetTree().Root); UpdateHint();
    }

    public override void _ExitTree() => Cancel();
}
