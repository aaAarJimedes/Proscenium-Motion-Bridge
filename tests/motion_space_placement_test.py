from __future__ import annotations

import importlib
import json
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Quaternion, Vector


if not bpy.app.background:
    raise RuntimeError("Motion-space placement test refuses to run in Blender UI")
if os.environ.get("PMB_PLACEMENT_TEST_ALLOW") != "isolated-factory-test":
    raise RuntimeError("Set PMB_PLACEMENT_TEST_ALLOW=isolated-factory-test explicitly")

REPOSITORY = Path(__file__).resolve().parents[1]
IMPORT_ROOT = Path(os.environ.get("PMB_IMPORT_ROOT", str(REPOSITORY)))
MODULE_NAME = os.environ.get("PMB_MODULE", "proscenium_motion_bridge")
sys.path.insert(0, str(IMPORT_ROOT))
mapping = importlib.import_module(MODULE_NAME + ".mapping")
native = importlib.import_module(MODULE_NAME + ".retarget")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def make_rig(name: str, source: bool) -> bpy.types.Object:
    data = bpy.data.armatures.new(name + "Data")
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root_name = "Hips" if source else "Center"
    root = data.edit_bones.new(root_name)
    root.head = (0.0, 0.0, 1.0)
    root.tail = (0.0, 0.0, 1.2)
    arm = data.edit_bones.new("Arm")
    arm.parent = root
    arm.head = (0.0, 0.0, 1.15)
    arm.tail = (0.8, 0.0, 1.15)
    bpy.ops.object.mode_set(mode="OBJECT")
    for pose_bone in rig.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    rig.select_set(False)
    return rig


def animate_source(source: bpy.types.Object) -> None:
    animation_data = source.animation_data_create()
    animation_data.action = bpy.data.actions.new(source.name + "Action")
    hips = source.pose.bones["Hips"]
    arm = source.pose.bones["Arm"]
    forward_local = hips.bone.matrix_local.to_3x3().inverted() @ Vector((0.0, -1.0, 0.0))
    for frame, root_y, arm_angle in ((1, 0.0, 0.0), (2, -1.0, math.radians(30.0))):
        bpy.context.scene.frame_set(frame)
        hips.location = forward_local * (-root_y)
        hips.keyframe_insert("location", frame=frame, group="Hips")
        arm.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), arm_angle)
        arm.keyframe_insert("rotation_quaternion", frame=frame, group="Arm")


RESULT = mapping.MappingResult(
    pairs=(
        mapping.MappingPair("Hips", "Center", channels="LOC", axes="XY", role="root_xy"),
        mapping.MappingPair("Arm", "Arm", channels="ROT", role="left_upper_arm"),
    ),
    missing=(),
    critical_missing=(),
    warnings=(),
    expected_count=2,
)


def pose_world_location(rig, bone_name: str) -> Vector:
    return (rig.matrix_world @ rig.pose.bones[bone_name].matrix).translation.copy()


def pose_world_rotation(rig, bone_name: str) -> Quaternion:
    return (rig.matrix_world @ rig.pose.bones[bone_name].matrix).to_quaternion()


def sample_motion(rig, bone_name: str):
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    location_1 = pose_world_location(rig, "Center")
    rotation_1 = pose_world_rotation(rig, bone_name)
    bpy.context.scene.frame_set(2)
    bpy.context.view_layer.update()
    location_2 = pose_world_location(rig, "Center")
    rotation_2 = pose_world_rotation(rig, bone_name)
    return location_1, location_2, rotation_2 @ rotation_1.inverted()


def source_arm_delta(source):
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    rotation_1 = pose_world_rotation(source, "Arm")
    bpy.context.scene.frame_set(2)
    bpy.context.view_layer.update()
    rotation_2 = pose_world_rotation(source, "Arm")
    return rotation_2 @ rotation_1.inverted()


def assert_quaternion_close(actual, expected, message):
    error = actual.rotation_difference(expected).angle
    check(error < math.radians(0.05), f"{message}: {math.degrees(error):.6f} degrees")


source = make_rig("SomaSource", source=True)
animate_source(source)
source_delta = source_arm_delta(source)

# Object plus parent-Empty placement: target forward is rotated 180 degrees
# and the object is already positioned away from the origin.
target = make_rig("PlacedTarget", source=False)
parent = bpy.data.objects.new("PlacementEmpty", None)
bpy.context.scene.collection.objects.link(parent)
parent.location = (4.0, 5.0, 0.0)
parent.rotation_euler.z = math.radians(90.0)
target.parent = parent
target.rotation_euler.z = math.radians(90.0)
target.scale = (1.5, 1.5, 1.5)
bpy.context.view_layer.update()
object_matrix_before = target.matrix_world.copy()
placement = native.capture_placement_context(source, target, RESULT, "TARGET_PLACEMENT")
check(abs(abs(placement.alignment_yaw_degrees) - 180.0) < 0.01, "180-degree target alignment was not captured")
native.bake_retarget(
    bpy.context.scene,
    source,
    target,
    RESULT,
    source_rest_override=None,
    location_scale=1.5,
    world_location=True,
    motion_space="TARGET_PLACEMENT",
    placement=placement,
)
placed_start, placed_end, placed_arm_delta = sample_motion(target, "Arm")
placed_travel = placed_end - placed_start
check((target.matrix_world.translation - object_matrix_before.translation).length < 1e-6, "target position was overwritten")
check(target.matrix_world.to_quaternion().rotation_difference(object_matrix_before.to_quaternion()).angle < 1e-6, "target orientation was overwritten")
check((target.matrix_world.to_scale() - object_matrix_before.to_scale()).length < 1e-6, "target scale was overwritten")
check((placed_travel - Vector((0.0, 1.5, 0.0))).length < 1e-4, f"forward travel ignored target facing/scale: {tuple(placed_travel)}")
expected_placed_delta = placement.alignment_rotation @ source_delta @ placement.alignment_rotation.inverted()
assert_quaternion_close(placed_arm_delta, expected_placed_delta, "limb motion ignored target facing")

# A manually transformed MMD Center must remain the additive baseline even
# when that same bone receives root-motion location keys.
control_target = make_rig("ControlPlacedTarget", source=False)
center = control_target.pose.bones["Center"]
center.location = (2.0, 3.0, 0.0)
center_rest_q = center.bone.matrix_local.to_quaternion()
center.rotation_quaternion = (
    center_rest_q.inverted()
    @ Quaternion((0.0, 0.0, 1.0), math.radians(180.0))
    @ center_rest_q
)
bpy.context.view_layer.update()
control_baseline_world = pose_world_location(control_target, "Center")
control_placement = native.capture_placement_context(source, control_target, RESULT, "TARGET_PLACEMENT")
native.bake_retarget(
    bpy.context.scene,
    source,
    control_target,
    RESULT,
    source_rest_override=None,
    location_scale=1.0,
    world_location=True,
    motion_space="TARGET_PLACEMENT",
    placement=control_placement,
)
control_start, control_end, control_arm_delta = sample_motion(control_target, "Arm")
control_travel = control_end - control_start
check((control_start - control_baseline_world).length < 1e-4, f"Center baseline location was lost: {tuple(control_start)}")
check(
    (control_travel - Vector((0.0, 1.0, 0.0))).length < 1e-4,
    f"Center-facing travel is wrong: {tuple(control_travel)}; yaw={control_placement.alignment_yaw_degrees}",
)
expected_control_delta = control_placement.alignment_rotation @ source_delta @ control_placement.alignment_rotation.inverted()
assert_quaternion_close(control_arm_delta, expected_control_delta, "Center-facing limb motion is wrong")

# In-place output has no root-motion pair, but limb direction must still use
# the target placement found from the conventional Center control.
in_place_result = mapping.MappingResult(
    pairs=(mapping.MappingPair("Arm", "Arm", channels="ROT", role="left_upper_arm"),),
    missing=(),
    critical_missing=(),
    warnings=(),
    expected_count=1,
)
in_place_target = make_rig("InPlaceTarget", source=False)
in_place_target.location = (-3.0, 6.0, 0.0)
in_place_target.rotation_euler.z = math.radians(90.0)
bpy.context.view_layer.update()
in_place_matrix_before = in_place_target.matrix_world.copy()
in_place_placement = native.capture_placement_context(
    source,
    in_place_target,
    in_place_result,
    "TARGET_PLACEMENT",
)
native.bake_retarget(
    bpy.context.scene,
    source,
    in_place_target,
    in_place_result,
    source_rest_override=None,
    location_scale=1.0,
    world_location=True,
    motion_space="TARGET_PLACEMENT",
    placement=in_place_placement,
)
_in_place_start, _in_place_end, in_place_arm_delta = sample_motion(in_place_target, "Arm")
expected_in_place_delta = (
    in_place_placement.alignment_rotation
    @ source_delta
    @ in_place_placement.alignment_rotation.inverted()
)
assert_quaternion_close(in_place_arm_delta, expected_in_place_delta, "in-place limb direction is wrong")
check(
    (in_place_target.matrix_world.translation - in_place_matrix_before.translation).length < 1e-6,
    "in-place output moved the target object",
)

# Explicit compatibility mode must retain the v0.7 source-world direction.
legacy_target = make_rig("LegacyTarget", source=False)
legacy_target.rotation_euler.z = math.radians(180.0)
bpy.context.view_layer.update()
legacy_placement = native.capture_placement_context(source, legacy_target, RESULT, "SOURCE_WORLD")
native.bake_retarget(
    bpy.context.scene,
    source,
    legacy_target,
    RESULT,
    source_rest_override=None,
    location_scale=1.0,
    world_location=True,
    motion_space="SOURCE_WORLD",
    placement=legacy_placement,
)
legacy_start, legacy_end, legacy_arm_delta = sample_motion(legacy_target, "Arm")
legacy_travel = legacy_end - legacy_start
check((legacy_travel - Vector((0.0, -1.0, 0.0))).length < 1e-4, f"legacy world travel changed: {tuple(legacy_travel)}")
assert_quaternion_close(legacy_arm_delta, source_delta, "legacy world-space limb behavior changed")

print(
    "PMB_PLACEMENT_TEST="
    + json.dumps(
        {
            "status": "PASS",
            "object_parent_yaw": placement.alignment_yaw_degrees,
            "object_forward_travel": list(placed_travel),
            "control_forward_travel": list(control_travel),
            "in_place_yaw": in_place_placement.alignment_yaw_degrees,
            "legacy_world_travel": list(legacy_travel),
            "control_baseline": list(control_start),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
