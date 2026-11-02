// Usage: node client3d/scripts/smoke_photo_shot.mjs
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { loadHudRealm } from './load_hud_realm.mjs';
assert.ok(existsSync('client3d/src/game/photoShot.ts'), 'browser photo upload helper exists');
const realm = loadHudRealm();
const { uploadPhotoShot } = realm.load('client3d/src/game/photoShot.ts');
const view = { visible: [{ name: 'Bob', screen_x: .2, screen_y: .4, depth_m: 3 }], camera: { pitch_deg: -30, height_m: 2, fov_deg: 70 } };
const jpeg = new Blob(['jpeg'], { type: 'image/jpeg' });
const requests = [], opened = [];
realm.uiActions.openScreenshotPhoto = value => opened.push(value);
const saved = globalThis.fetch;
try {
  globalThis.fetch = async (url, init) => {
    requests.push([url, init]);
    return new Response(JSON.stringify({ image_id: '012345abcdef.jpg', filename: 'photo.jpg' }), { status: 200 });
  };
  await uploadPhotoShot(jpeg, view);
  assert.equal(requests[0][0], '/chat/me/upload-image?purpose=scene_photo');
  assert.equal(requests[0][1].credentials, 'same-origin');
  assert.equal(requests[0][1].method, 'POST');
  const file = requests[0][1].body.get('file');
  assert.equal(file.type, 'image/jpeg');
  assert.match(file.name, /\.jpg$/);
  assert.equal(await file.text(), 'jpeg');
  assert.deepEqual(opened, [{ imageId: '012345abcdef.jpg', imageUrl: '/chat/me/upload-image/012345abcdef.jpg', view }]);
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Upload refused' }), { status: 403 });
  await assert.rejects(uploadPhotoShot(jpeg, view), /Upload refused/);
  assert.equal(opened.length, 1, 'failed upload does not open a dialog');
  globalThis.fetch = async () => new Response(JSON.stringify({}), { status: 200 });
  await assert.rejects(uploadPhotoShot(jpeg, view), /image/i);
  assert.equal(opened.length, 1, 'missing upload id does not open a dialog');
} finally { globalThis.fetch = saved; }
console.log('photo shot: PASS (multipart JPEG, view handoff, upload refusal, missing id)');
