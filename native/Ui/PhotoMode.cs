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
    public bool Selecting => Camera.Photo.Selecting;
    internal bool SelectionReady => _selection is not null;
    public Task Pending { get; private set; } = Task.CompletedTask;
    private CancellationTokenSource? _shot;
    private TaskCompletionSource<(Image Image,PhotoView View)>? _frame;
    private readonly Dictionary<CanvasLayer,bool> _layers = new();
    private readonly Dictionary<CanvasItem,bool> _items = new();
    private readonly Dictionary<Node3D,bool> _markers = new();
    private CanvasLayer? _hintLayer;
    private Label? _hint;
    private Control? _selectionUi;
    private TextureRect? _frozen;
    private ImageTexture? _frozenTexture;
    private readonly ColorRect[] _dim = new ColorRect[4];
    private Panel? _border;
    private Label? _size;
    private TaskCompletionSource<PhotoRect>? _selection;
    private Vector2? _dragStart;
    private bool _fullRequested, _backToFlight;
    private int _imageWidth, _imageHeight;

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
                    if (Selecting) BackToFlight();
                    else if (Active || Busy) Cancel(); else Enter();
                }
                return true;
            }
            if (Active && key.Keycode==Key.Space)
            {
                if (key.Pressed && !key.Echo && !key.CtrlPressed && !key.MetaPressed && !key.AltPressed && !typing)
                {
                    if (Selecting) { _fullRequested=true; _selection?.TrySetResult(new(0,0,_imageWidth,_imageHeight)); }
                    else if (!Busy) { Busy=true; Pending=ShootAsync(); }
                }
                return true;
            }
        }
        if (!Active) return false;
        if (Selecting)
        {
            Camera.PhotoInput(input);
            if (_selection is not null)
            {
                if (input is InputEventMouseButton { ButtonIndex:MouseButton.Left } b)
                {
                    if (b.Pressed) { _dragStart=b.Position; DrawSelection(b.Position); }
                    else if (_dragStart is not null)
                    { _selection.TrySetResult(SelectionRect(b.Position)); _dragStart=null; }
                }
                else if (input is InputEventMouseMotion m && _dragStart is not null) DrawSelection(m.Position);
            }
            return true;
        }
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
        _selectionUi=new Control { Visible=false,MouseFilter=Control.MouseFilterEnum.Ignore };
        layer.AddChild(_selectionUi);
        _frozen=new TextureRect { ExpandMode=TextureRect.ExpandModeEnum.IgnoreSize,StretchMode=TextureRect.StretchModeEnum.Scale,
            MouseFilter=Control.MouseFilterEnum.Ignore };
        _selectionUi.AddChild(_frozen);
        for (int i=0;i<4;i++)
        {
            _dim[i]=new ColorRect { Color=new(0,0,0,.55f),Visible=false,MouseFilter=Control.MouseFilterEnum.Ignore };
            _selectionUi.AddChild(_dim[i]);
        }
        var style=new StyleBoxFlat { BgColor=Colors.Transparent,BorderColor=new("d4af62") };
        style.SetBorderWidthAll(1);
        _border=new Panel { Visible=false,MouseFilter=Control.MouseFilterEnum.Ignore };
        _border.AddThemeStyleboxOverride("panel",style); _selectionUi.AddChild(_border);
        _size=new Label { MouseFilter=Control.MouseFilterEnum.Ignore }; _border.AddChild(_size);
        _size.Position=new(4,4);
        _hint=new Label { Position=new(16,16), MouseFilter=Control.MouseFilterEnum.Ignore };
        layer.AddChild(_hint);
        return layer;
    }

    public void Cancel()
    {
        _shot?.Cancel(); _frame?.TrySetCanceled(); _frame=null;
        RestoreMode();
    }

    private void BackToFlight()
    {
        _backToFlight=true;
        _shot?.Cancel(); _frame?.TrySetCanceled(); _frame=null;
        _selection?.TrySetCanceled(); _selection=null;
        ClearSelection(); Camera.SetPhotoSelecting(false); UpdateHint();
    }

    private void ClearSelection()
    {
        _selection?.TrySetCanceled(); _selection=null; _dragStart=null;
        if (_selectionUi is not null) _selectionUi.Visible=false;
        if (_frozen is not null) _frozen.Texture=null;
        _frozenTexture?.Dispose(); _frozenTexture=null;
        foreach (var dim in _dim) if (dim is not null) dim.Visible=false;
        if (_border is not null) _border.Visible=false;
    }

    private void RestoreMode()
    {
        ClearSelection();
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
        _backToFlight=false; _fullRequested=false;
        Camera.SetPhotoSelecting(true);
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
            ct.ThrowIfCancellationRequested();
            _imageWidth=image.GetWidth(); _imageHeight=image.GetHeight();
            _selection=new(); var selectionTask=_selection.Task;
            _frozenTexture=ImageTexture.CreateFromImage(image); _frozen!.Texture=_frozenTexture;
            _selectionUi!.Visible=true; ResizeSelection(); UpdateHint();
            if (_fullRequested) _selection.TrySetResult(new(0,0,_imageWidth,_imageHeight));
            var rect=PhotoControl.ShotRect(await selectionTask,_imageWidth,_imageHeight);
            ct.ThrowIfCancellationRequested();
            _selection=null;
            // Freeze controls until mode restoration, but remove the selection hint during encoding.
            UpdateHint();
            var view=frame.View.Crop(rect,_imageWidth,_imageHeight);
            var encoded=await Task.Run(() => Encode(image,rect));
            width=encoded.Width; height=encoded.Height; bytes=encoded.Bytes.Length; names=view.visible.Count;
            ct.ThrowIfCancellationRequested();
            RestoreMode();
            uploadStart=Stopwatch.GetTimestamp();
            var id=await Upload(encoded.Bytes,ct);
            ct.ThrowIfCancellationRequested();
            Screenshot(id,AnimaApi.PhotoImageUrl(id),view);
            outcome="ok";
        }
        catch (Exception e)
        {
            if (!_backToFlight) RestoreMode();
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

    internal static (byte[] Bytes,int Width,int Height) Encode(Image image,PhotoRect? rect=null)
    {
        if (rect is { } crop && crop!=new PhotoRect(0,0,image.GetWidth(),image.GetHeight()))
        {
            using var region=image.GetRegion(new(crop.X,crop.Y,crop.Width,crop.Height));
            return Encode(region);
        }
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
        _hint.Visible=Active && (!Busy || _selection is not null);
        _hint.Text=_selection is not null ? "Drag to select · Click: whole picture · Esc: back"
            : $"Photo mode · WASD move · Q/E down/up · Drag to look · Wheel speed {Camera.Photo.Speed:0.0} m/s · Shift ×3 · Space select photo · F2/Esc leave";
    }

    private PhotoRect SelectionRect(Vector2 end)
    {
        var start=_dragStart!.Value; var size=GetViewport().GetVisibleRect().Size;
        return PhotoControl.SelectionRect(start.X,start.Y,end.X,end.Y,0,0,size.X,size.Y,_imageWidth,_imageHeight);
    }

    private void ResizeSelection()
    {
        var size=GetViewport().GetVisibleRect().Size;
        _selectionUi!.Size=size; _frozen!.Size=size;
    }

    private void DrawSelection(Vector2 end)
    {
        var r=SelectionRect(end); var size=GetViewport().GetVisibleRect().Size;
        float x=(float)r.X/_imageWidth*size.X,y=(float)r.Y/_imageHeight*size.Y;
        float w=(float)r.Width/_imageWidth*size.X,h=(float)r.Height/_imageHeight*size.Y;
        var regions=new Rect2[] { new(0,0,size.X,y),new(0,y+h,size.X,size.Y-y-h),new(0,y,x,h),new(x+w,y,size.X-x-w,h) };
        for (int i=0;i<4;i++) { _dim[i].Position=regions[i].Position; _dim[i].Size=regions[i].Size; _dim[i].Visible=true; }
        _border!.Position=new(x,y); _border.Size=new(w,h); _border.Visible=true;
        _size!.Text=$"{r.Width} × {r.Height} px";
    }

    public override void _Process(double delta)
    {
        if (!Active) return;
        if (_selectionUi?.Visible==true) ResizeSelection();
        HideCanvas(GetTree().Root); UpdateHint();
    }

    public override void _ExitTree() => Cancel();
}
