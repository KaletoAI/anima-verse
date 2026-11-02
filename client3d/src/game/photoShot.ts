/** Upload an already encoded JPEG and hand its framing to the shared photo dialog. */
import { apiUpload } from '@anima/player-ui/api';
import type { PhotoView } from '@anima/player-ui';
import { uiActions } from '../hud/bus';

export async function uploadPhotoShot(jpeg: Blob, view: PhotoView): Promise<void> {
  const file = new File([jpeg], 'photo.jpg', { type: 'image/jpeg' });
  const result = await apiUpload<{ image_id?: string }>('/chat/me/upload-image?purpose=scene_photo', file);
  if (!result?.image_id) throw new Error('Upload returned no image ID');
  uiActions.openScreenshotPhoto?.({
    imageId: result.image_id,
    imageUrl: `/chat/me/upload-image/${encodeURIComponent(result.image_id)}`,
    view,
  });
}
