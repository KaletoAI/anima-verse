---
name: SetPose
---
Sets the current pose / what the character is doing right now. Use this for any free-text pose that isn't a listed Activity — e.g. "sitting on the couch reading", "leaning against the windowsill", "stretching by the window".

Pass JSON: {"pose": "your pose description"} or just the pose text. Free-text, describe naturally. The pose is matched against existing image variants per character to keep the cache consistent.
