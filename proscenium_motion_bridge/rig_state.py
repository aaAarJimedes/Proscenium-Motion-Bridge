"""Capture and restore only rig controls owned by the retarget operation."""
from __future__ import annotations
import json
import bpy
from .mapping import MappingResult, normalize
_TARGET_SWITCH_KEYS = ("IK_FK", "ik_fk_switch")

def _constraint_by_identity(target, row: dict):
    pose_bone = target.pose.bones.get(row.get("owner", ""))
    if pose_bone is None:
        return None
    constraint = pose_bone.constraints.get(row.get("constraint", ""))
    if constraint is not None and row.get("type") and constraint.type != row["type"]:
        return None
    return constraint


def _restore_constraint_rows(target, rows: list[dict]) -> tuple[int, int]:
    restored = 0
    missing = 0
    for row in rows:
        constraint = _constraint_by_identity(target, row)
        if constraint is None:
            missing += 1
            continue
        try:
            constraint.mute = bool(row["mute"])
            constraint.influence = float(row["influence"])
            restored += 1
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            missing += 1
    return restored, missing


def _restore_saved_constraints(settings) -> tuple[int, int]:
    if not settings.constraint_snapshot_json:
        return 0, 0
    try:
        target = settings.constraint_snapshot_target_rig
    except ReferenceError:
        target = None
    if target is None:
        target = bpy.data.objects.get(settings.constraint_snapshot_target)
    if target is None or target.type != "ARMATURE":
        return 0, 1
    try:
        rows = json.loads(settings.constraint_snapshot_json)
    except json.JSONDecodeError:
        return 0, 1
    if not isinstance(rows, list):
        return 0, 1
    restored, missing = _restore_constraint_rows(target, rows)
    if missing == 0:
        settings.constraint_snapshot_json = ""
        settings.constraint_snapshot_target = ""
        settings.constraint_snapshot_target_rig = None
    return restored, missing


def _mapped_constraint_snapshot(target, result: MappingResult) -> list[dict]:
    by_role = {pair.role: pair.target for pair in result.pairs}
    leg_roles = {
        "left_thigh",
        "left_shin",
        "left_foot",
        "right_thigh",
        "right_shin",
        "right_foot",
    }
    leg_bones = {by_role[role] for role in leg_roles if role in by_role}
    hips = by_role.get("hips_rotation")

    path_bones: set[str] = set()
    for role in ("left_thigh", "right_thigh"):
        current = by_role.get(role)
        seen: set[str] = set()
        while current and current not in seen:
            path_bones.add(current)
            if current == hips:
                break
            seen.add(current)
            bone = target.data.bones.get(current)
            current = bone.parent.name if bone and bone.parent else None

    rows: list[dict] = []
    for pose_bone in target.pose.bones:
        for constraint in pose_bone.constraints:
            selected = constraint.type == "IK" and pose_bone.name in leg_bones
            if constraint.type == "TRANSFORM" and pose_bone.name in path_bones:
                fingerprint = normalize(
                    " ".join(
                        (
                            pose_bone.name,
                            constraint.name,
                            getattr(constraint, "subtarget", "") or "",
                        )
                    )
                )
                selected = any(
                    token in fingerprint
                    for token in ("cancel", "キャンセル", "腰キャンセル", "waist cancel", "waist_cancel")
                )
            if not selected:
                continue
            rows.append(
                {
                    "owner": pose_bone.name,
                    "constraint": constraint.name,
                    "type": constraint.type,
                    "mute": bool(constraint.mute),
                    "influence": float(constraint.influence),
                }
            )
    return rows


def _disable_constraint_rows(target, rows: list[dict]) -> int:
    disabled = 0
    for row in rows:
        constraint = _constraint_by_identity(target, row)
        if constraint is None:
            continue
        if not constraint.mute and constraint.influence > 1e-6:
            disabled += 1
        constraint.mute = True
        constraint.influence = 0.0
    return disabled


def _target_switch_snapshot(target) -> list[dict]:
    """Capture rig-level FK/IK properties changed by the native bake setup."""
    rows: list[dict] = []
    for pose_bone in target.pose.bones:
        for key in _TARGET_SWITCH_KEYS:
            if key not in pose_bone.keys():
                continue
            value = pose_bone[key]
            if not isinstance(value, (bool, int, float)):
                continue
            rows.append({"owner": pose_bone.name, "key": key, "value": float(value)})
    return rows


def _restore_target_switch_rows(target, rows: list[dict]) -> tuple[int, int]:
    restored = 0
    missing = 0
    for row in rows:
        pose_bone = target.pose.bones.get(row.get("owner", ""))
        key = row.get("key", "")
        if pose_bone is None or key not in pose_bone.keys():
            missing += 1
            continue
        try:
            pose_bone[key] = float(row["value"])
            restored += 1
        except (KeyError, RuntimeError, TypeError, ValueError):
            missing += 1
    try:
        bpy.context.view_layer.update()
    except (AttributeError, RuntimeError):
        pass
    return restored, missing


def _restore_saved_target_switches(settings, target) -> tuple[int, int]:
    if not settings.target_switch_snapshot_json:
        return 0, 0
    if settings.target_switch_snapshot_target and settings.target_switch_snapshot_target != target.name:
        return 0, 1
    try:
        rows = json.loads(settings.target_switch_snapshot_json)
    except json.JSONDecodeError:
        return 0, 1
    if not isinstance(rows, list):
        return 0, 1
    restored, missing = _restore_target_switch_rows(target, rows)
    if missing == 0:
        settings.target_switch_snapshot_json = ""
        settings.target_switch_snapshot_target = ""
    return restored, missing


def _force_target_fk_switches(target) -> int:
    changed = 0
    for pose_bone in target.pose.bones:
        for key in _TARGET_SWITCH_KEYS:
            if key not in pose_bone.keys():
                continue
            try:
                if abs(float(pose_bone[key]) - 1.0) > 1e-6:
                    pose_bone[key] = 1.0
                    changed += 1
            except (RuntimeError, TypeError, ValueError):
                pass
    try:
        bpy.context.view_layer.update()
    except (AttributeError, RuntimeError):
        pass
    return changed

