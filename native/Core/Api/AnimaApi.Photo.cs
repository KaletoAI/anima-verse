using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Api;

public sealed partial class AnimaApi
{
    /// <summary>Existing player upload: same authenticated client and server-side upload limit/magic-byte chain.</summary>
    public async Task<string> UploadPhotoAsync(byte[] jpeg, CancellationToken ct = default)
    {
        const string path = "/chat/me/upload-image?purpose=scene_photo";
        using var content = new MultipartFormDataContent();
        using var file = new ByteArrayContent(jpeg);
        file.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(file,"file","photo.jpg");
        using var response = await _http.PostAsync(Relative(path),content,ct);
        using var doc = await ReadJson(response,path);
        if (!doc.RootElement.TryGetProperty("image_id",out var id) || id.ValueKind != System.Text.Json.JsonValueKind.String
            || string.IsNullOrWhiteSpace(id.GetString())) throw new InvalidOperationException("Upload returned no image ID");
        return id.GetString()!;
    }

    public static string PhotoImageUrl(string id) => "/chat/me/upload-image/" + Uri.EscapeDataString(id);
}
