using System.Collections.Generic;
using AnimaNative.Figures;
using AnimaNative.Photo;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

public partial class Main
{
    private PhotoMode? _photo;
    private bool InPhoto => _photo?.Active == true;

    private bool HandlePhotoInput(InputEvent input)
    {
        if (_photo is null)
        {
            if (input is not InputEventKey { Pressed:true, Echo:false, Keycode:Key.F2 }
                || !_interactive || Leaving || !ControlBootReady || _camera is null || _api is null) return false;
            _photo=new PhotoMode {
                Name="PhotoMode", Camera=_camera, View=CurrentPhotoView, Markers=PhotoMarkers,
                Upload=(bytes,ct)=>_api.UploadPhotoAsync(bytes,ct),
                Screenshot=(id,url,view)=>_hud?.OpenScreenshotPhoto(id,url,view),
                Toast=EmbodyToast, Log=Log, Changed=PhotoChanged
            };
            AddChild(_photo);
        }
        if (Leaving) { _photo.Cancel(); return false; }
        bool handled=_photo.HandleInput(input,_hud?.Ui.Typing==true);
        if (handled) GetViewport().SetInputAsHandled();
        return handled;
    }

    private void PhotoChanged(bool active)
    {
        if (_figures is not null) _figures.PhotoMode=active;
        if (_builder is not null) _builder.PhotoMode=active;
        if (_avatarPosition is not null) _avatarPosition.Suspended=active;
        if (_avatarRooms is not null) _avatarRooms.Suspended=active;
        if (_avatarOffers is not null) _avatarOffers.Suspended=active;
        if (active)
        {
            _avatarOffers?.Places.ClearHover(); _avatarRooms?.Picking.Clear();
            _hoverAt=null; _hoverPending=false;
            OcclusionMaterials.Update(Vector3.Zero,null,false,false);
            AvatarFigure()?.SetFirstPerson(false);
            if (AvatarFigure() is { } figure) figure.FirstPersonViewYaw=null;
            Input.SetDefaultCursorShape(Input.CursorShape.Arrow);
        }
        else { PoseEmbody(); _hoverAt=GetViewport().GetMousePosition(); _hoverPending=true; }
    }

    private IEnumerable<Node3D> PhotoMarkers()
    {
        if (_pins is not null) yield return _pins;
        if (_avatarOffers is not null) yield return _avatarOffers.Places;
        if (_builder is not null)
            foreach (var slot in _builder.Slots.Values)
            {
                if (slot.Storeys.DoorMarks is { } doors) yield return doors;
                if (slot.Storeys.BoundaryMarks is { } boundary) yield return boundary;
            }
        if (_figures is null) yield break;
        if (_figures.WalkTarget is { } walk) yield return walk;
        foreach (var figure in _figures.Figures.Values)
        {
            if (figure.Portrait is { } portrait) yield return portrait.Root;
            if (figure.TravelLine is { } line) yield return line;
        }
    }

    private PhotoView CurrentPhotoView()
    {
        var camera=_camera!;
        var basis=camera.GlobalBasis.Orthonormalized();
        var subjects=new List<PhotoSubject>();
        if (_figures is not null)
            foreach (var figure in _figures.Figures.Values)
                if (IsInstanceValid(figure) && figure.IsVisibleInTree() && figure.Portrait is null
                    && figure.Body is { } body && body.IsVisibleInTree()) subjects.Add(new(figure.CharacterName,V3(figure.Lens)));
        var size=camera.GetViewport().GetVisibleRect().Size;
        return PhotoView.Build(V3(camera.GlobalPosition),V3(-basis.Z),V3(basis.X),V3(basis.Y),
            camera.Fov,(double)size.X/size.Y,camera.Near,camera.Far,subjects,
            _builder?.PhotoFloorY(camera.GlobalPosition) ?? 0);
    }
}
