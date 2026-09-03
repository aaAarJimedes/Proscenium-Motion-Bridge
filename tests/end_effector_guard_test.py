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
    raise RuntimeError("End-effector guard test refuses to run in Blender UI")
if os.environ.get("PMB_GUARD_TEST_ALLOW") != "isolated-factory-test":
    raise RuntimeError("Set PMB_GUARD_TEST_ALLOW=isolated-factory-test explicitly")

REPOSITORY = Path(__file__).resolve().parents[1]
IMPORT_ROOT = Path(os.environ.get("PMB_IMPORT_ROOT", str(REPOSITORY)))
MODULE_NAME = os.environ.get("PMB_MODULE", "proscenium_motion_bridge")
sys.path.insert(0, str(IMPORT_ROOT))
addon = importlib.import_module(MODULE_NAME)
mapping = importlib.import_module(MODULE_NAME + ".mapping")
native = importlib.import_module(MODULE_NAME + ".retarget")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def make_rig(
    name: str,
    shoulder_half: float,
    upper_length: float,
    forearm_length: float,
    *,
    intermediate_twists: bool = False,
):
    data = bpy.data.armatures.new(name + "Data")
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        shoulder = Vector((sign * shoulder_half, 0.0, 1.5))
        elbow = shoulder + Vector((sign * upper_length, 0.0, 0.0))
        wrist = elbow + Vector((sign * forearm_length, 0.0, 0.0))
        hand_end = wrist + Vector((sign * 0.12, 0.0, 0.0))
        upper = data.edit_bones.new(side + "Arm")
        upper.head, upper.tail = shoulder, elbow
        upper_parent = upper
        if intermediate_twists:
            upper_twist = data.edit_bones.new(side + "ArmTwist")
            upper_twist.head = shoulder.lerp(elbow, 0.45)
            upper_twist.tail = shoulder.lerp(elbow, 0.70)
            upper_twist.parent = upper
            upper_parent = upper_twist
        forearm = data.edit_bones.new(side + "ForeArm")
        forearm.head, forearm.tail = elbow, wrist
        forearm.parent = upper_parent
        hand_parent = forearm
        if intermediate_twists:
            wrist_twist = data.edit_bones.new(side + "WristTwist")
            wrist_twist.head = elbow.lerp(wrist, 0.50)
            wrist_twist.tail = elbow.lerp(wrist, 0.75)
            wrist_twist.parent = forearm
            hand_parent = wrist_twist
        hand = data.edit_bones.new(side + "Hand")
        hand.head, hand.tail = wrist, hand_end
        hand.parent = hand_parent
    bpy.ops.object.mode_set(mode="OBJECT")
    for pose_bone in rig.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    rig.select_set(False)
    return rig


def pose_arm(rig, side: str, elbow: Vector, wrist: Vector) -> None:
    check(native._aim_pose_bone(rig.pose.bones[side + "Arm"], elbow), "Could not pose upper arm")
    bpy.context.view_layer.update()
    check(native._aim_pose_bone(rig.pose.bones[side + "ForeArm"], wrist), "Could not pose forearm")
    bpy.context.view_layer.update()


def wrist_separation(rig) -> float:
    left = rig.matrix_world @ rig.pose.bones["LeftHand"].head
    right = rig.matrix_world @ rig.pose.bones["RightHand"].head
    return (left - right).length


RESULT = mapping.MappingResult(
    pairs=tuple(
        mapping.MappingPair(source, target, role=role)
        for source, target, role in (
            ("LeftArm", "LeftArm", "left_upper_arm"),
            ("LeftForeArm", "LeftForeArm", "left_forearm"),
            ("LeftHand", "LeftHand", "left_hand"),
            ("RightArm", "RightArm", "right_upper_arm"),
            ("RightForeArm", "RightForeArm", "right_forearm"),
            ("RightHand", "RightHand", "right_hand"),
        )
    ),
    missing=(),
    critical_missing=(),
    warnings=(),
    expected_count=6,
)

source = make_rig("Source", 0.60, 0.45, 0.40)
pose_arm(source, "Left", Vector((0.34, 0.30, 1.35)), Vector((0.12, 0.16, 1.18)))
pose_arm(source, "Right", Vector((-0.34, 0.30, 1.35)), Vector((-0.12, 0.16, 1.18)))


def exercise_target(name: str, yaw_degrees: float, correction_strength: float = 1.0):
    target = make_rig(name, 0.35, 0.40, 0.38, intermediate_twists=True)
    target.location = (2.0, -3.0, 0.0)
    target.rotation_euler.z = math.radians(yaw_degrees)
    bpy.context.view_layer.update()
    local_elbows = (Vector((0.20, 0.25, 1.34)), Vector((-0.20, 0.25, 1.34)))
    local_wrists = (Vector((0.03, 0.12, 1.15)), Vector((-0.03, 0.12, 1.15)))
    inverse = target.matrix_world.inverted()
    for side, elbow, wrist in zip(("Left", "Right"), local_elbows, local_wrists):
        pose_arm(target, side, inverse @ (target.matrix_world @ elbow), inverse @ (target.matrix_world @ wrist))
    before = wrist_separation(target)
    hand_rotations = {
        side: (target.matrix_world @ target.pose.bones[side + "Hand"].matrix).to_quaternion()
        for side in ("Left", "Right")
    }
    context = native._build_arm_guard_context(source, target, RESULT)
    corrected, maximum = native._apply_end_effector_guard(
        source,
        target,
        context,
        Quaternion((0.0, 0.0, 1.0), math.radians(yaw_degrees)),
        correction_strength,
    )
    after = wrist_separation(target)
    for side in ("Left", "Right"):
        current = (target.matrix_world @ target.pose.bones[side + "Hand"].matrix).to_quaternion()
        error = current.rotation_difference(hand_rotations[side]).angle
        check(error < math.radians(0.01), f"{side} palm rotation changed by {math.degrees(error)} degrees")
    check(len(corrected) == 6, f"Unexpected corrected bones: {corrected}")
    check(after > before + 0.02, f"Wrist separation was not restored: {before} -> {after}")
    check(maximum > 0.02, f"Correction was unexpectedly small: {maximum}")
    local_wrists_after = tuple(
        target.matrix_world.inverted() @ (target.matrix_world @ target.pose.bones[side + "Hand"].head)
        for side in ("Left", "Right")
    )
    return target, before, after, local_wrists_after


neutral, neutral_before, neutral_after, neutral_wrists = exercise_target("NeutralTarget", 0.0)
rotated, rotated_before, rotated_after, rotated_wrists = exercise_target("RotatedTarget", 137.0)
strong, strong_before, strong_after, _strong_wrists = exercise_target("StrongTarget", 0.0, 2.0)
for neutral_wrist, rotated_wrist in zip(neutral_wrists, rotated_wrists):
    check((neutral_wrist - rotated_wrist).length < 1e-5, "Target placement changed local guard result")
check(strong_after > neutral_after + 0.02, "Higher correction strength did not add clearance")

addon.register()
check(bpy.context.scene.ba_motion_bridge_settings.use_end_effector_guard, "Guard is not enabled by default")
check(
    abs(bpy.context.scene.ba_motion_bridge_settings.end_effector_guard_strength - 1.0) < 1e-6,
    "Guard strength does not default to 1.0",
)

print(
    "PMB_END_EFFECTOR_GUARD_TEST="
    + json.dumps(
        {
            "status": "PASS",
            "neutral": [neutral_before, neutral_after],
            "rotated": [rotated_before, rotated_after],
            "strong": [strong_before, strong_after],
            "rotation_invariant": True,
            "default_enabled": True,
            "default_strength": 1.0,
        },
        sort_keys=True,
    )
)
