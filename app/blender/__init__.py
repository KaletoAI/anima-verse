"""Headless Blender as a local refinement stage for generated 3D models.

Blender runs as a SUBPROCESS on this server — no gateway, no GPU, no LLM. It
never produces models; it measures and repairs what the img2mesh backends
deliver (scale, origin, axes, LOD, UV bakes, rig names).

``runner.run()`` is the only entry point; the scripts under ``scripts/`` are
plain bpy programs that know nothing about this application (Blender ships its
own Python — the app's venv is NOT importable there).
"""
