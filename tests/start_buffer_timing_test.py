from __future__ import annotations

import importlib
import json
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion


if not bpy.app.background:
    raise RuntimeError("Start-buffer timing test refuses to run in Blender UI")
if os.environ.get("PMB_BUFFER_TEST_ALLOW") != "isolated-factory-test":
    raise RuntimeError("Set PMB_BUFFER_TEST_ALLOW=isolated-factory-test explicitly")

REPOSITORY = Path(__file__).resolve().parents[1]
IMPORT_ROOT = Path(os.environ.get("PMB_IMPORT_ROOT", str(REPOSITORY)))
MODULE_NAME = os.environ.get("PMB_MODULE", "proscenium_motion_bridge")
sys.path.insert(0, str(IMPORT_ROOT))
mapping = importlib.import_module(MODULE_NAME + ".mapping")
bridge_ops = importlib.import_module(MODULE_NAME + ".operators")
properties = importlib.import_module(MODULE_NAME + ".properties")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


RESULT = mapping.MappingResult(
    pairs=(mapping.MappingPair("SourceBone", "Bone", channels="ROT", role="test"),),
    missing=(),
    critical_missing=(),
    warnings=(),
    expected_count=1,
)


def make_case(name: str, buffer_frames: int, transition_frames: int) -> tuple[dict, list[int]]:
    data = bpy.data.armatures.new(name + "Data")
    target = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(target)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("Bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="POSE")
    pose_bone = target.pose.bones["Bone"]
    pose_bone.rotation_mode = "QUATERNION"
    action = bpy.data.actions.new(name + "Action")
    target.animation_data_create().action = action
    for frame, angle in ((1, 60.0), (10, 90.0)):
        bpy.context.scene.frame_set(frame)
        pose_bone.rotation_quaternion = Quaternion((0.0, 0.0, 1.0), math.radians(angle))
        pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group="Bone")
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    result = bridge_ops._insert_start_buffer(
        bpy.context.scene,
        target,
        action,
        RESULT,
        {"Bone": Matrix.Identity(4)},
        buffer_frames,
        transition_frames,
    )
    keyed_frames = sorted(
        {
            int(round(point.co.x))
            for fcurve in bridge_ops._iter_action_fcurves(action)
            for point in fcurve.keyframe_points
        }
    )
    check(bool(action.use_frame_range), "Formal action range was not enabled")
    check(int(action.frame_start) == 1, f"Formal start moved: {action.frame_start}")
    check(int(action.frame_end) == 10, f"Formal end moved: {action.frame_end}")
    return result, keyed_frames


total_case, total_keys = make_case("TotalBuffer", 30, 20)
check(total_case["preroll_start"] == -29, total_case)
check(total_case["inserted_frames"] == 30, total_case)
check(total_case["buffer_frames"] == 30, total_case)
check(total_case["settle_frames"] == 10, total_case)
check(total_case["transition_frames"] == 20, total_case)
check(set(range(-29, 1)).issubset(total_keys), total_keys)

clamped_case, clamped_keys = make_case("ClampedTransition", 10, 20)
check(clamped_case["preroll_start"] == -9, clamped_case)
check(clamped_case["settle_frames"] == 0, clamped_case)
check(clamped_case["transition_frames"] == 10, clamped_case)
check(set(range(-9, 1)).issubset(clamped_keys), clamped_keys)

static_case, static_keys = make_case("StaticBuffer", 12, 0)
check(static_case["preroll_start"] == -11, static_case)
check(static_case["settle_frames"] == 12, static_case)
check(static_case["transition_frames"] == 0, static_case)
check(set(range(-11, 1)).issubset(static_keys), static_keys)

properties.register()
settings = bpy.context.scene.ba_motion_bridge_settings
settings.settle_frames = 12
settings.transition_frames = 18
if "buffer_frames" in settings:
    del settings["buffer_frames"]
if properties._BUFFER_SCHEMA_KEY in settings:
    del settings[properties._BUFFER_SCHEMA_KEY]
properties._migrate_buffer_settings(bpy.context.scene)
check(settings.buffer_frames == 30, f"Legacy total was not preserved: {settings.buffer_frames}")

print(
    "PMB_START_BUFFER_TEST="
    + json.dumps(
        {
            "status": "PASS",
            "total": total_case,
            "clamped": clamped_case,
            "static": static_case,
            "legacy_migrated_total": settings.buffer_frames,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
