import type { ClipListing } from './clipSets'

export interface TransitionPose { key: string; animation: string; solo: boolean; group?: string }

const isFbx = (url: string) => /\.fbx(?:\?|$)/i.test(url)
const poseKind = (poses: TransitionPose[], pose: string) =>
  poses.find((p) => p.key === (pose === 'walking' ? 'standing' : pose))?.animation

/** Matches pose_transition.pose_clip, including walking's standing condition. */
export function transitionClip(poses: TransitionPose[], listing: ClipListing, pose: string, set: string, role = '') {
  const matches = listing.clips.filter((c) => c.kind === poseKind(poses, pose) && (c.role || '') === role && isFbx(c.url))
  return matches.find((c) => (c.set || '') === set) || matches.find((c) => !c.set)
}

export function transitionOptions(poses: TransitionPose[], listing: ClipListing) {
  return [{ pose: 'walking', role: '' }, ...poses.filter((p) => p.animation && p.key !== 'walking').flatMap((p) => {
    const roles = p.solo ? [''] : [...new Set(listing.clips.filter((c) => c.kind === p.animation && c.role
      && isFbx(c.url)).map((c) => c.role!))].sort()
    return roles.map((role) => ({ pose: p.key, role }))
  })]
}

export function transitionSets(poses: TransitionPose[], listing: ClipListing, pose: string, role: string) {
  return [...new Set(listing.clips.filter((c) => c.kind === poseKind(poses, pose) && (c.role || '') === role
    && isFbx(c.url)).map((c) => c.set || ''))]
}
