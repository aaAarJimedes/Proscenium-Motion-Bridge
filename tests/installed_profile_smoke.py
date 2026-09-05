from __future__ import annotations

import importlib
import json
from pathlib import Path
import tomllib

import addon_utils
import bpy


if not bpy.app.background:
    raise RuntimeError("Installed-profile smoke refuses to run in Blender UI")

enabled = sorted(addon.module for addon in bpy.context.preferences.addons)
matches = [
    name
    for name in enabled
    if name.rsplit(".", 1)[-1].lower() == "proscenium_motion_bridge"
]
if len(matches) != 1:
    raise RuntimeError(f"Expected one enabled Proscenium Motion Bridge module, got {matches}")

module_name = matches[0]
state = tuple(bool(value) for value in addon_utils.check(module_name))
if state != (True, True):
    raise RuntimeError(f"Installed extension is not enabled and loaded: {state}")

module = importlib.import_module(module_name)
constants = importlib.import_module(module_name + ".constants")
if tuple(constants.ADDON_VERSION) != (0, 9, 2):
    raise RuntimeError(f"Unexpected runtime version: {constants.ADDON_VERSION}")

manifest_path = Path(module.__file__).resolve().parent / "blender_manifest.toml"
manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("version") != "0.9.2":
    raise RuntimeError(f"Unexpected installed manifest version: {manifest.get('version')}")

if not hasattr(bpy.types.Scene, "ba_motion_bridge_settings"):
    raise RuntimeError("Scene settings were not registered")
settings = bpy.context.scene.ba_motion_bridge_settings
if settings.motion_space != "TARGET_PLACEMENT":
    raise RuntimeError(f"Unexpected default motion space: {settings.motion_space}")
if not settings.use_end_effector_guard:
    raise RuntimeError("End-effector guard is not enabled by default")
if abs(settings.end_effector_guard_strength - 1.0) > 1e-6:
    raise RuntimeError(f"Unexpected end-effector guard strength: {settings.end_effector_guard_strength}")
if settings.buffer_frames != 30:
    raise RuntimeError(f"Unexpected default total buffer: {settings.buffer_frames}")
if settings.transition_frames != 20:
    raise RuntimeError(f"Unexpected default transition: {settings.transition_frames}")

try:
    bpy.ops.ba_motion_bridge.accept_and_retarget.get_rna_type()
except (AttributeError, KeyError, RuntimeError) as exc:
    raise RuntimeError(f"Main output operator is unavailable: {exc}") from exc

if not hasattr(bpy.types, "BAM_PT_proscenium_motion_bridge"):
    raise RuntimeError("Single Motion Bridge panel was not registered")

print(
    "PMB_INSTALLED_PROFILE_SMOKE="
    + json.dumps(
        {
            "status": "PASS",
            "module": module_name,
            "state": state,
            "version": manifest["version"],
            "motion_space": settings.motion_space,
            "end_effector_guard": settings.use_end_effector_guard,
            "end_effector_guard_strength": settings.end_effector_guard_strength,
            "buffer_frames": settings.buffer_frames,
            "transition_frames": settings.transition_frames,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
