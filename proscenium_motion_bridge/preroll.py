"""Physics pre-roll and timeline restoration, preserving 0.9.1 buffer semantics."""
from __future__ import annotations
import json
import bpy

def _physics_cache_snapshot(scene) -> dict:
    rigidbody_world = getattr(scene, "rigidbody_world", None)
    point_cache = getattr(rigidbody_world, "point_cache", None)
    if point_cache is None:
        return {"present": False}
    return {
        "present": True,
        "frame_start": int(point_cache.frame_start),
    }


def _timeline_snapshot(scene) -> dict:
    return {
        "frame_start": int(scene.frame_start),
        "frame_current": int(scene.frame_current),
        "use_preview_range": bool(scene.use_preview_range),
        "frame_preview_start": int(scene.frame_preview_start),
        "frame_preview_end": int(scene.frame_preview_end),
    }


def _restore_timeline_snapshot(scene, snapshot: dict) -> bool:
    if not snapshot or "frame_start" not in snapshot:
        return False
    scene.frame_start = int(snapshot["frame_start"])
    scene.use_preview_range = bool(snapshot.get("use_preview_range", scene.use_preview_range))
    if "frame_preview_start" in snapshot:
        scene.frame_preview_start = int(snapshot["frame_preview_start"])
    if "frame_preview_end" in snapshot:
        scene.frame_preview_end = int(snapshot["frame_preview_end"])
    scene.frame_set(int(snapshot.get("frame_current", scene.frame_start)))
    bpy.context.view_layer.update()
    return True


def _restore_saved_timeline(scene, settings) -> str:
    if not settings.timeline_snapshot_json:
        return "NONE"
    try:
        snapshot = json.loads(settings.timeline_snapshot_json)
    except json.JSONDecodeError:
        return "INVALID"
    restored = _restore_timeline_snapshot(scene, snapshot)
    settings.timeline_snapshot_json = ""
    return "RESTORED" if restored else "SKIPPED"


def _extend_preroll_timeline(scene, preroll_start: int) -> dict:
    preroll_start = int(preroll_start)
    # Scene.frame_start is hard-clamped to 0 by Blender 5.1.  A negative
    # preview range is not clamped, remains draggable in the Timeline, and the
    # rigid-body point cache independently accepts the same negative start.
    scene.frame_start = min(int(scene.frame_start), preroll_start)
    scene.use_preview_range = True
    scene.frame_preview_start = min(int(scene.frame_preview_start), preroll_start)
    scene.frame_preview_end = max(int(scene.frame_preview_end), int(scene.frame_end))
    rigidbody_world = getattr(scene, "rigidbody_world", None)
    point_cache = getattr(rigidbody_world, "point_cache", None)
    cache_status = "NO_RIGID_BODY_WORLD"
    if point_cache is not None:
        if bool(getattr(point_cache, "is_baked", False)):
            cache_status = "BAKED_CACHE"
        else:
            point_cache.frame_start = min(int(point_cache.frame_start), preroll_start)
            cache_status = "EXTENDED"
    scene.frame_set(preroll_start)
    bpy.context.view_layer.update()
    return {
        "timeline_start": preroll_start,
        "scene_start": int(scene.frame_start),
        "cache_status": cache_status,
    }


def _restore_physics_cache_snapshot(scene, snapshot: dict) -> bool:
    if not snapshot or not snapshot.get("present"):
        return False
    rigidbody_world = getattr(scene, "rigidbody_world", None)
    point_cache = getattr(rigidbody_world, "point_cache", None)
    if point_cache is None or bool(getattr(point_cache, "is_baked", False)):
        return False
    point_cache.frame_start = int(snapshot["frame_start"])
    return True


def _restore_saved_physics_cache(scene, settings) -> str:
    if not settings.physics_cache_snapshot_json:
        return "NONE"
    try:
        snapshot = json.loads(settings.physics_cache_snapshot_json)
    except json.JSONDecodeError:
        return "INVALID"
    restored = _restore_physics_cache_snapshot(scene, snapshot)
    settings.physics_cache_snapshot_json = ""
    if restored:
        return "RESTORED"
    return "SKIPPED"


def _evaluate_physics_preroll(
    scene,
    preroll_start: int,
    motion_start: int,
    progress=None,
) -> dict:
    timeline_result = _extend_preroll_timeline(scene, preroll_start)
    rigidbody_world = getattr(scene, "rigidbody_world", None)
    point_cache = getattr(rigidbody_world, "point_cache", None)
    if point_cache is None:
        if progress is not None:
            progress(1.0, "未检测到刚体世界，已跳过物理预热")
        return {"status": "NO_RIGID_BODY_WORLD", "evaluated_frames": 0}
    if bool(getattr(point_cache, "is_baked", False)):
        if progress is not None:
            progress(1.0, "检测到已烘焙缓存，未覆盖")
        return {"status": "BAKED_CACHE", "evaluated_frames": 0}

    evaluated = 0
    total_frames = max(1, int(motion_start) - int(preroll_start) + 1)
    for frame in range(int(preroll_start), int(motion_start) + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        evaluated += 1
        if progress is not None:
            progress(
                evaluated / total_frames,
                f"预热物理帧 {frame}/{motion_start}",
            )
    scene.frame_set(preroll_start)
    bpy.context.view_layer.update()
    return {
        "status": "EVALUATED",
        "evaluated_frames": evaluated,
        "timeline_start": timeline_result["timeline_start"],
    }
