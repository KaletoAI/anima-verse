/**
 * One rule, used by every instance buffer the scatter refills: upload the
 * PREFIX that was written, not the whole array.
 *
 * THE FINDING (2026-08-24). Every re-binning pass in this client sizes an
 * instance buffer for the entry's whole instance count and then fills the
 * first `count` slots of it — the drawn instances, compacted to the front
 * (`ground.ts binProp`/`binImpostors`, `undergrowth.ts binLayer`). Setting
 * `needsUpdate` on the attribute made three.js call `gl.bufferSubData` with
 * the ENTIRE array, so a wood of 4 000 trees of which 300 are drawn pushed
 * 4 000 matrices (256 kB) across the bus to draw 300 of them. With the view
 * cone in place the gap got wider, not narrower: the cone is precisely a
 * device for lowering `count` while the buffer stays the size it was.
 *
 * `BufferAttribute.addUpdateRange(start, count)` states the range in ARRAY
 * ELEMENTS, not in items and not in bytes (three r185,
 * `WebGLAttributes.updateBuffer` multiplies by `BYTES_PER_ELEMENT`), which is
 * why the caller passes the stride: 16 floats for an instance matrix, 3 for an
 * instance colour.
 *
 * The ranges are CLEARED first every time. three clears them itself after an
 * upload, but only for an attribute it actually uploaded — a buffer marked
 * while its mesh was invisible would otherwise collect ranges from passes
 * nobody ever drew.
 */

/** What this module needs of an attribute — structural, so it needs no `three`
 *  import and a smoke check can hand it a plain object. `BufferAttribute` and
 *  `InstancedBufferAttribute` satisfy it as they are. */
export interface UploadableAttribute {
  clearUpdateRanges(): void;
  addUpdateRange(start: number, count: number): void;
  needsUpdate: boolean;
}

/**
 * Mark the first `used` items of `attr` for upload and nothing behind them.
 *
 * `used = 0` marks nothing at all and does not even set `needsUpdate`: a pass
 * that drew nothing has nothing to send, and an empty update range would be
 * read as "no ranges given" and upload the whole array — the very case this
 * exists to avoid.
 */
export function markInstanceUpload(attr: UploadableAttribute | null | undefined,
                                   used: number, stride: number): void {
  if (!attr) return;
  if (!(used > 0) || !(stride > 0)) return;
  attr.clearUpdateRanges();
  attr.addUpdateRange(0, used * stride);
  attr.needsUpdate = true;
}
