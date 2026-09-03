from __future__ import annotations

import hashlib
import json
import re
import statistics
import time

import bpy
from bpy.props import EnumProperty, StringProperty
from mathutils import Matrix, Quaternion, Vector

from .constants import (
    CANONICAL_MODEL_ID,
    CANONICAL_MODEL_KEY,
    OWNER_KEY,
    OWNER_VALUE,
    OWNER_VALUES,
    TEMPORARY_KEY,
)
from .mapping import MappingResult, build_mapping, is_official_canonical_bones, normalize
from .retarget import bake_retarget, capture_placement_context


class _OperationProgress:
    """Mirror long synchronous work to Blender's status bar and this panel."""

    def __init__(self, context, settings, title: str):
        self.context = context
        self.settings = settings
        self.title = title
        self.window_manager = context.window_manager
        self.window = getattr(context, "window", None)
        self.started = False
        self.last_draw = 0.0

    def begin(self, message: str) -> None:
        self.started = True
        self.settings.progress_active = True
        self.settings.progress_value = 0.0
        self.settings.progress_message = message
        self.window_manager.progress_begin(0, 1000)
        if self.window is not None:
            try:
                self.window.cursor_modal_set("WAIT")
            except (AttributeError, RuntimeError):
                pass
        self._redraw(force=True)

    def update(self, factor: float, message: str = "") -> None:
        if not self.started:
            return
        factor = max(0.0, min(1.0, float(factor)))
        self.settings.progress_value = factor
        if message:
            self.settings.progress_message = message
        self.window_manager.progress_update(round(factor * 1000))
        now = time.monotonic()
        self._redraw(force=factor >= 1.0 or now - self.last_draw >= 0.08)

    def stage(self, start: float, end: float, prefix: str = ""):
        span = max(0.0, float(end) - float(start))

        def callback(factor: float, message: str = "") -> None:
            label = f"{prefix}：{message}" if prefix and message else (message or prefix)
            self.update(float(start) + span * max(0.0, min(1.0, float(factor))), label)

        return callback

    def end(self) -> None:
        if not self.started:
            return
        try:
            self.window_manager.progress_end()
        finally:
            if self.window is not None:
                try:
                    self.window.cursor_modal_restore()
                except (AttributeError, RuntimeError):
                    pass
            self.settings.progress_active = False
            self.settings.progress_value = 0.0
            self.settings.progress_message = ""
            self.started = False
            self._redraw(force=True)

    def _redraw(self, *, force: bool = False) -> None:
        for window in getattr(self.window_manager, "windows", ()):
            screen = getattr(window, "screen", None)
            for area in getattr(screen, "areas", ()) if screen is not None else ():
                if area.type in {"VIEW_3D", "STATUSBAR"}:
                    area.tag_redraw()
        if force and self.window is not None:
            self.last_draw = time.monotonic()
            try:
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except (AttributeError, RuntimeError):
                pass


def operator_available(path: str) -> bool:
    namespace, name = path.split(".", 1)
    try:
        operator = getattr(getattr(bpy.ops, namespace), name)
        operator.get_rna_type()
    except (AttributeError, KeyError, RuntimeError):
        return False
    return True


def _is_armature(obj) -> bool:
    return obj is not None and obj.type == "ARMATURE" and obj.name in bpy.context.scene.objects


def _is_official_source(obj) -> bool:
    if not _is_armature(obj):
        return False
    names = {bone.name for bone in obj.data.bones}
    return (
        obj.get(CANONICAL_MODEL_KEY) == CANONICAL_MODEL_ID
        and is_official_canonical_bones(names)
    )


def _animation_present(obj) -> bool:
    animation_data = getattr(obj, "animation_data", None)
    if animation_data is None:
        return False
    if animation_data.action is not None:
        return True
    return bool(_effective_nla_strips(animation_data))


def _effective_nla_strips(animation_data) -> list:
    if animation_data is None or not bool(animation_data.use_nla):
        return []
    tracks = [track for track in animation_data.nla_tracks if not bool(getattr(track, "mute", False))]
    solo_tracks = [track for track in tracks if bool(getattr(track, "is_solo", False))]
    if solo_tracks:
        tracks = solo_tracks
    return [
        strip
        for track in tracks
        for strip in track.strips
        if strip.action is not None
        and not bool(getattr(strip, "mute", False))
        and float(getattr(strip, "influence", 1.0)) > 1e-6
    ]


def _uniform_scale(obj, tolerance: float = 1e-5) -> bool:
    values = [float(value) for value in obj.scale]
    if min(values) <= 1e-8:
        return False
    if float(obj.matrix_world.to_3x3().determinant()) <= 1e-10:
        return False
    return max(values) - min(values) <= tolerance * max(max(values), 1.0)


def _is_mmd_candidate(obj) -> bool:
    if not _is_armature(obj):
        return False
    metadata = 0
    for bone in obj.data.bones:
        holders = (bone, obj.pose.bones.get(bone.name))
        for holder in holders:
            mmd_bone = getattr(holder, "mmd_bone", None) if holder is not None else None
            if mmd_bone is None:
                continue
            if any(getattr(mmd_bone, attr, "") for attr in ("name_j", "name_e")):
                metadata += 1
                break
    if metadata >= 4:
        return True
    names = {bone.name for bone in obj.data.bones}
    if len({"センター", "下半身", "上半身", "首", "頭"}.intersection(names)) >= 4:
        return True
    current = obj
    seen = set()
    while current is not None and current.as_pointer() not in seen:
        seen.add(current.as_pointer())
        if getattr(current, "mmd_type", "NONE") == "ROOT":
            return True
        current = current.parent
    return False


def _auto_source(scene, settings):
    settings.source_candidates = ""
    if _is_official_source(settings.source_rig):
        settings.source_origin = "已明确选择"
        return settings.source_rig

    proscenium = getattr(scene, "proscenium", None)
    candidate = getattr(proscenium, "target_armature", None) if proscenium else None
    if _is_official_source(candidate):
        settings.source_origin = "Proscenium 当前骨架"
        return candidate

    active = bpy.context.active_object
    if _is_official_source(active):
        settings.source_origin = "活动对象"
        return active

    candidates = [obj for obj in scene.objects if _is_official_source(obj)]
    if len(candidates) == 1:
        settings.source_origin = "场景唯一官方骨架"
        return candidates[0]
    if len(candidates) > 1:
        settings.source_candidates = "、".join(sorted(obj.name for obj in candidates))
    settings.source_origin = ""
    return None


def _candidate_result(source, candidate, root_motion_mode: str) -> MappingResult | None:
    if not _is_armature(candidate) or candidate == source:
        return None
    try:
        return build_mapping(source, candidate, root_motion_mode)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return None


def _auto_target(scene, settings, source):
    if _is_armature(settings.target_rig) and settings.target_rig != source:
        settings.target_origin = "已明确选择"
        settings.target_candidates = ""
        return settings.target_rig

    preferred = (
        ("活动对象", bpy.context.active_object),
    )
    for origin, candidate in preferred:
        result = _candidate_result(source, candidate, settings.root_motion_mode)
        if result is not None and not result.critical_missing and _is_mmd_candidate(candidate):
            settings.target_origin = origin
            settings.target_candidates = ""
            return candidate

    candidates = [obj for obj in scene.objects if obj.type == "ARMATURE" and _is_mmd_candidate(obj)]

    unique = []
    seen: set[int] = set()
    for candidate in candidates:
        if candidate is None or candidate == source:
            continue
        pointer = candidate.as_pointer()
        if pointer in seen:
            continue
        seen.add(pointer)
        unique.append(candidate)

    ranked = []
    for candidate in unique:
        result = _candidate_result(source, candidate, settings.root_motion_mode)
        if result is None:
            continue
        ranked.append(
            (
                len(result.critical_missing),
                -result.matched_count,
                candidate,
            )
        )
    if not ranked:
        settings.target_origin = ""
        settings.target_candidates = ""
        return None
    best_score = min((row[0], row[1]) for row in ranked)
    best = [row[-1] for row in ranked if (row[0], row[1]) == best_score]
    if len(best) == 1:
        settings.target_origin = "场景唯一最佳匹配"
        settings.target_candidates = ""
        return best[0]
    settings.target_origin = ""
    settings.target_candidates = "、".join(sorted(obj.name for obj in best))
    return None


def _resolve_rigs(scene, settings):
    source = _auto_source(scene, settings)
    if source is not None and settings.source_rig != source:
        settings.source_rig = source
    target = _auto_target(scene, settings, source) if source is not None else None
    if target is not None and settings.target_rig != target:
        settings.target_rig = target
    return source, target


def _proscenium_previewing(scene) -> bool:
    props = getattr(scene, "proscenium", None)
    return bool(props and getattr(props, "is_previewing", False))


def _effective_root_motion_mode(scene, settings) -> str:
    policy = getattr(settings, "root_motion_policy", "AUTO")
    if policy in {"FULL", "IN_PLACE"}:
        return policy
    props = getattr(scene, "proscenium", None)
    if props is None or not hasattr(props, "inplace"):
        return getattr(settings, "root_motion_mode", "FULL")
    return "IN_PLACE" if bool(props.inplace) else "FULL"


def _sync_proscenium_inplace(scene, settings) -> None:
    desired = _effective_root_motion_mode(scene, settings)
    if settings.root_motion_mode != desired:
        settings.root_motion_mode = desired


def _rig_fingerprint(rig) -> list[dict]:
    result = []
    for bone in rig.data.bones:
        matrix = tuple(round(float(value), 6) for row in bone.matrix_local for value in row)
        result.append(
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "matrix": matrix,
            }
        )
    return result


def _mapping_payload(
    source,
    target,
    root_motion_mode: str,
    motion_space: str,
    result: MappingResult,
) -> dict:
    return {
        "schema": 3,
        "source_object": source.name,
        "source_data": source.data.name,
        "target_object": target.name,
        "target_data": target.data.name,
        "root_motion_mode": root_motion_mode,
        "motion_space": motion_space,
        "pairs": [pair.to_dict() for pair in result.pairs],
        "missing": list(result.missing),
        "critical_missing": list(result.critical_missing),
        "warnings": list(result.warnings),
        "expected_count": result.expected_count,
        "target_profile": result.target_profile,
    }


def _mapping_signature(source, target, payload: dict) -> str:
    signature_payload = {
        "source": _rig_fingerprint(source),
        "target": _rig_fingerprint(target),
        "mapping": payload,
    }
    encoded = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rest_head_world(rig, bone_name: str):
    bone = rig.data.bones.get(bone_name)
    if bone is None:
        return None
    return rig.matrix_world @ bone.head_local


def _semantic_scale_ratio(source, target, result: MappingResult) -> float:
    by_role = {pair.role: pair for pair in result.pairs if pair.channels == "ROT"}
    landmark_pairs = (
        ("hips_rotation", "head"),
        ("hips_rotation", "left_foot"),
        ("hips_rotation", "right_foot"),
        ("left_shoulder", "left_hand"),
        ("right_shoulder", "right_hand"),
    )
    ratios: list[float] = []
    for first_role, second_role in landmark_pairs:
        first = by_role.get(first_role)
        second = by_role.get(second_role)
        if first is None or second is None:
            continue
        source_a = _rest_head_world(source, first.source)
        source_b = _rest_head_world(source, second.source)
        target_a = _rest_head_world(target, first.target)
        target_b = _rest_head_world(target, second.target)
        if any(value is None for value in (source_a, source_b, target_a, target_b)):
            continue
        source_distance = (source_b - source_a).length
        target_distance = (target_b - target_a).length
        if source_distance > 1e-6 and target_distance > 1e-6:
            ratio = target_distance / source_distance
            if 0.01 <= ratio <= 100.0:
                ratios.append(ratio)
    return float(statistics.median(ratios)) if ratios else 1.0


def _set_status(settings, result: MappingResult, valid: bool, message: str) -> None:
    settings.mapping_valid = valid
    settings.matched_count = result.matched_count
    settings.expected_count = result.expected_count
    settings.critical_missing = "、".join(result.critical_missing)
    settings.unmatched = "、".join(result.missing)
    settings.warnings = "；".join(result.warnings)
    settings.target_profile = result.target_profile
    settings.status_message = message
    settings.status_level = "READY" if valid else "ERROR"
    settings.status_code = "MAPPING_READY" if valid else "MAPPING_INCOMPLETE"
    settings.next_action = "点击“一键输出到角色”" if valid else "补齐目标关键骨或重新选择角色骨架"


def _set_failure(settings, code: str, message: str, next_action: str) -> None:
    settings.mapping_valid = False
    settings.mapping_signature = ""
    settings.matched_count = 0
    settings.expected_count = 0
    settings.critical_missing = ""
    settings.unmatched = ""
    settings.warnings = ""
    settings.target_profile = ""
    settings.status_level = "ERROR"
    settings.status_code = code
    settings.status_message = message
    settings.next_action = next_action


def _prepare_mapping(scene, settings):
    source, target = _resolve_rigs(scene, settings)
    if source is None:
        if settings.source_candidates:
            message = f"检测到多个官方骨架：{settings.source_candidates}"
            next_action = "在“官方动作骨架”中明确选择本次 Proscenium 骨架"
        else:
            message = "未找到带 kimodo-soma-rp 标记的 Proscenium 官方骨架"
            next_action = "连接 Proscenium 并导入官方骨架"
        _set_failure(settings, "SOURCE_NOT_FOUND", message, next_action)
        return None, None, None, message
    if not _is_official_source(source):
        message = "源骨架不是完整的 Proscenium kimodo-soma-rp 官方骨架"
        _set_failure(settings, "SOURCE_INVALID", message, "重新导入官方骨架，不要使用自定义或传统 BVH 骨架")
        return source, None, None, message
    proscenium = getattr(scene, "proscenium", None)
    if (
        proscenium is not None
        and bool(getattr(proscenium, "is_generating", False))
        and getattr(proscenium, "target_armature", None) == source
    ):
        message = "Proscenium 正在生成；已阻止输出上一条旧动作"
        _set_failure(settings, "GENERATION_BUSY", message, "等待本次生成完成并预览/接受")
        return source, None, None, message
    if target is None:
        if settings.target_candidates:
            message = f"多个角色骨架同分：{settings.target_candidates}"
            next_action = "在“角色目标骨架”中明确选择要写入的角色"
        else:
            message = "未找到可映射的 MMD/Auto-Rig Pro 目标骨架"
            next_action = "选择角色的人体 Armature"
        _set_failure(settings, "TARGET_AMBIGUOUS", message, next_action)
        return source, None, None, message
    if source == target:
        message = "源骨架和目标骨架不能是同一个对象"
        _set_failure(settings, "SAME_RIG", message, "重新选择角色目标骨架")
        return source, target, None, message
    if not _uniform_scale(source) or not _uniform_scale(target):
        message = "检测到非等比、零值或镜像对象缩放；已阻止可能失真的重定向"
        _set_failure(settings, "NON_UNIFORM_SCALE", message, f"在角色副本中选择 {source.name if not _uniform_scale(source) else target.name}，Ctrl+A → Scale")
        return source, target, None, message

    result = build_mapping(source, target, settings.root_motion_mode)
    settings.scale_ratio = _semantic_scale_ratio(source, target, result)
    payload = _mapping_payload(
        source,
        target,
        settings.root_motion_mode,
        settings.motion_space,
        result,
    )
    signature = _mapping_signature(source, target, payload)
    settings.mapping_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    settings.mapping_signature = signature
    valid = not result.critical_missing
    if valid:
        message = f"必需主链完整：{result.matched_count}/{result.expected_count} 对已映射"
    else:
        message = f"关键骨缺失：{'、'.join(result.critical_missing)}"
    _set_status(settings, result, valid, message)

    return source, target, result, None if valid else message


def _safe_action_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u3040-\u30ff\u3400-\u9fff]+", "_", value).strip("_")
    return cleaned[:48] or "MMD"


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


_TARGET_SWITCH_KEYS = ("IK_FK", "ik_fk_switch")


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


_DIRECTION_ALIGNED_ROLES = frozenset(
    {
        "left_shoulder",
        "left_upper_arm",
        "left_forearm",
        "left_hand",
        "left_thigh",
        "left_shin",
        "left_foot",
        "right_shoulder",
        "right_upper_arm",
        "right_forearm",
        "right_hand",
        "right_thigh",
        "right_shin",
        "right_foot",
    }
)


def _twist_about_bone_y(rotation: Quaternion) -> Quaternion:
    """Extract the twist component around Blender bone-local +Y."""
    twist = Quaternion((rotation.w, 0.0, rotation.y, 0.0))
    if twist.magnitude < 1e-8:
        return Quaternion()
    twist.normalize()
    return twist


def _build_source_rest_override(
    source,
    target,
    result: MappingResult,
    placement=None,
) -> dict[str, Matrix]:
    """Build source rest matrices with selected limb direction swing removed.

    The canonical source rests in a T-pose while many converted MMD/ARP rigs
    rest with their arms sloping down. Ordinary delta transfer preserves that
    direction offset, which rotates a two-handed gun pose inward and causes
    the arms to cross. For limb pairs we retain only the offset's local-Y
    twist (bone roll); torso/head/hips use the ordinary source edit rest.
    ToeBase is deliberately excluded: SOMA uses it for the foot dorsum while
    MMD つま先 represents the forward toe tip. Strict delta-from-rest transfer
    keeps MMD toes neutral instead of copying SOMA's upward rest direction.
    """
    rotation_pairs = []
    seen_sources = set()
    for pair in result.pairs:
        if pair.channels not in {"ROT", "LOC_ROT"} or pair.source in seen_sources:
            continue
        if pair.source not in source.pose.bones or pair.target not in target.data.bones:
            continue
        seen_sources.add(pair.source)
        rotation_pairs.append(pair)
    source_world_q = source.matrix_world.to_quaternion()
    source_world_q_inv = source_world_q.inverted()
    target_world_q = target.matrix_world.to_quaternion()
    placement_alignment_inverse = Quaternion()
    if placement is not None and placement.motion_space == "TARGET_PLACEMENT":
        placement_alignment_inverse = placement.alignment_rotation.inverted()
    overrides: dict[str, Matrix] = {}
    for pair in rotation_pairs:
        source_bone = source.data.bones[pair.source]
        target_bone = target.data.bones[pair.target]
        source_rest_world_q = source_world_q @ source_bone.matrix_local.to_quaternion()
        target_rest_world_q = target_world_q @ target_bone.matrix_local.to_quaternion()
        # Limb rest-direction matching is a shape correction, not scene
        # placement. Compare both rigs in the source-facing frame; otherwise
        # the target object's yaw is included here and then applied a second
        # time by bake_retarget's target-placement alignment.
        comparable_target_rest_q = placement_alignment_inverse @ target_rest_world_q
        if pair.role in _DIRECTION_ALIGNED_ROLES:
            rest_offset = source_rest_world_q.inverted() @ comparable_target_rest_q
            roll_twist = _twist_about_bone_y(rest_offset)
            override_world_q = comparable_target_rest_q @ roll_twist.inverted()
        else:
            override_world_q = source_rest_world_q

        override_arm_q = source_world_q_inv @ override_world_q
        overrides[pair.source] = Matrix.LocRotScale(
            source_bone.matrix_local.translation,
            override_arm_q,
            source_bone.matrix_local.to_scale(),
        )
    return overrides


def _activate_target(context, target) -> None:
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except (AttributeError, RuntimeError):
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        context.view_layer.objects.active = target
    except (AttributeError, RuntimeError):
        pass


def _iter_action_fcurves(action):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        yield from legacy
        return
    slots = list(getattr(action, "slots", ()) or ())
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            yielded = False
            channelbags = getattr(strip, "channelbags", None)
            if channelbags is not None:
                try:
                    for channelbag in channelbags:
                        yield from channelbag.fcurves
                        yielded = True
                except TypeError:
                    yielded = False
            if yielded:
                continue
            channelbag_method = getattr(strip, "channelbag", None)
            if callable(channelbag_method):
                for slot in slots:
                    try:
                        channelbag = channelbag_method(slot)
                    except Exception:
                        channelbag = None
                    if channelbag is not None:
                        yield from channelbag.fcurves
                        yielded = True
            if yielded:
                continue
            strip_fcurves = getattr(strip, "fcurves", None)
            if strip_fcurves is not None:
                yield from strip_fcurves


def _action_slot(animation_data):
    if not hasattr(animation_data, "action_slot"):
        return None
    try:
        return animation_data.action_slot
    except (AttributeError, RuntimeError):
        return None


def _action_slot_identifier(slot) -> str:
    if slot is None:
        return ""
    try:
        return str(slot.identifier)
    except (AttributeError, ReferenceError, RuntimeError):
        return ""


def _find_action_slot(action, identifier: str):
    if action is None or not identifier:
        return None
    for slot in getattr(action, "slots", ()):
        if _action_slot_identifier(slot) == identifier:
            return slot
    return None


def _bind_action(animation_data, action, preferred_slot=None) -> None:
    animation_data.action = action
    if action is None or not hasattr(animation_data, "action_slot"):
        return
    if preferred_slot is not None:
        try:
            animation_data.action_slot = preferred_slot
            return
        except (AttributeError, RuntimeError, TypeError):
            pass


def _mapped_target_channels(result: MappingResult) -> tuple[set[str], set[str]]:
    rotation_targets: set[str] = set()
    location_targets: set[str] = set()
    for pair in result.pairs:
        if pair.channels in {"ROT", "LOC_ROT"}:
            rotation_targets.add(pair.target)
        if pair.channels in {"LOC", "LOC_ROT"}:
            location_targets.add(pair.target)
    return rotation_targets, location_targets


def _snapshot_pose_basis(target, bone_names: set[str]) -> dict[str, Matrix]:
    return {
        name: target.pose.bones[name].matrix_basis.copy()
        for name in bone_names
        if name in target.pose.bones
    }


def _capture_buffer_initial_pose(
    scene,
    settings,
    target,
    result: MappingResult,
    placement=None,
) -> dict[str, Matrix]:
    """Read the user-selected initial pose without changing target animation state."""
    rotation_targets, location_targets = _mapped_target_channels(result)
    bone_names = rotation_targets | location_targets
    if settings.initial_pose_source == "REST":
        rest_pose = {name: Matrix.Identity(4) for name in bone_names if name in target.pose.bones}
        if placement is not None and placement.motion_space == "TARGET_PLACEMENT":
            for name in location_targets:
                if name not in rest_pose:
                    continue
                rest_pose[name].translation = placement.baseline_locations.get(name, Vector()).copy()
            if placement.placement_bone in rest_pose:
                baseline = placement.baseline_basis.get(placement.placement_bone)
                if baseline is not None:
                    rest_pose[placement.placement_bone] = baseline.copy()
        return rest_pose

    animation_data = target.animation_data_create()
    if settings.initial_pose_source == "CURRENT":
        bpy.context.view_layer.update()
        return _snapshot_pose_basis(target, bone_names)

    action = settings.initial_pose_action
    if action is None:
        raise RuntimeError("起始缓冲选择了“指定 Action 帧”，但尚未选择初始姿态 Action")

    previous_frame = scene.frame_current
    previous_action = animation_data.action
    previous_slot = _action_slot(animation_data)
    previous_use_nla = bool(animation_data.use_nla)
    try:
        _bind_action(animation_data, action)
        animation_data.use_nla = False
        scene.frame_set(settings.initial_pose_frame)
        bpy.context.view_layer.update()
        return _snapshot_pose_basis(target, bone_names)
    finally:
        _bind_action(animation_data, previous_action, previous_slot)
        animation_data.use_nla = previous_use_nla
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()


def _interpolate_basis(initial: Matrix, final: Matrix, factor: float) -> Matrix:
    factor = max(0.0, min(1.0, float(factor)))
    initial_location, initial_rotation, initial_scale = initial.decompose()
    final_location, final_rotation, final_scale = final.decompose()
    # Smoothstep keeps both ends still and avoids injecting an abrupt velocity
    # into skirt/hair rigid bodies at either boundary.
    smooth = factor * factor * (3.0 - 2.0 * factor)
    return Matrix.LocRotScale(
        initial_location.lerp(final_location, smooth),
        initial_rotation.slerp(final_rotation, smooth),
        initial_scale.lerp(final_scale, smooth),
    )


def _rotation_property(pose_bone) -> str:
    if pose_bone.rotation_mode == "QUATERNION":
        return "rotation_quaternion"
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _insert_start_buffer(
    scene,
    target,
    action,
    result: MappingResult,
    initial_pose: dict[str, Matrix],
    settle_frames: int,
    transition_frames: int,
    progress=None,
) -> dict:
    """Add hidden pre-roll keys while preserving the formal motion range."""
    settle_frames = max(0, int(settle_frames))
    transition_frames = max(0, int(transition_frames))
    total_frames = settle_frames + transition_frames
    raw_start, raw_end = (float(value) for value in action.frame_range)
    motion_start = int(round(raw_start))
    motion_end = int(round(raw_end))
    if total_frames <= 0:
        return {
            "motion_start": motion_start,
            "motion_end": motion_end,
            "preroll_start": motion_start,
            "inserted_frames": 0,
        }

    rotation_targets, location_targets = _mapped_target_channels(result)
    target_names = rotation_targets | location_targets
    scene.frame_set(motion_start)
    bpy.context.view_layer.update()
    first_pose = _snapshot_pose_basis(target, target_names)
    missing = sorted(name for name in target_names if name not in initial_pose or name not in first_pose)
    if missing:
        raise RuntimeError("起始缓冲无法读取目标骨姿态：" + "、".join(missing[:8]))

    preroll_start = motion_start - total_frames
    transition_start = motion_start - transition_frames
    if progress is not None:
        progress(0.0, "准备首帧缓冲")
    for frame in range(preroll_start, motion_start):
        factor = 0.0
        if transition_frames > 0 and frame >= transition_start:
            factor = (frame - transition_start) / float(transition_frames)
        for bone_name in target_names:
            pose_bone = target.pose.bones[bone_name]
            pose_bone.matrix_basis = _interpolate_basis(
                initial_pose[bone_name],
                first_pose[bone_name],
                factor,
            )
            if bone_name in rotation_targets:
                pose_bone.keyframe_insert(_rotation_property(pose_bone), frame=frame, group=bone_name)
            if bone_name in location_targets:
                pose_bone.keyframe_insert("location", frame=frame, group=bone_name)
        if progress is not None:
            progress(
                (frame - preroll_start + 1) / max(1, total_frames),
                f"写入缓冲帧 {frame}/{motion_start - 1}",
            )

    for fcurve in _iter_action_fcurves(action):
        for point in fcurve.keyframe_points:
            if point.co.x < motion_start:
                point.interpolation = "LINEAR"
        fcurve.update()

    # Blender's custom Action range is the logical trim: pre-roll keys remain
    # available for physics evaluation, while NLA/export sees the real motion
    # starting at its original first frame.
    if hasattr(action, "use_frame_range"):
        action.use_frame_range = True
        action.frame_start = motion_start
        action.frame_end = motion_end
    scene.frame_set(motion_start)
    bpy.context.view_layer.update()
    return {
        "motion_start": motion_start,
        "motion_end": motion_end,
        "preroll_start": preroll_start,
        "inserted_frames": total_frames,
    }


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
    suitable = list(getattr(animation_data, "action_suitable_slots", ()) or ())
    if suitable:
        try:
            animation_data.action_slot = suitable[0]
        except (AttributeError, RuntimeError, TypeError):
            pass


def _sample_nla_to_temporary_action(scene, source, state: dict, progress=None):
    animation_data = source.animation_data
    strips = _effective_nla_strips(animation_data)
    frame_start = max(scene.frame_start, int(min(strip.frame_start for strip in strips)))
    frame_end = min(scene.frame_end, int(max(strip.frame_end for strip in strips)))
    if frame_end < frame_start:
        raise RuntimeError("NLA 条带不在当前场景帧范围内")

    pose_bones = [source.pose.bones[bone.name] for bone in source.data.bones]
    samples: dict[int, dict[str, object]] = {}
    frame_count = max(1, frame_end - frame_start + 1)
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        samples[frame] = {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in pose_bones}
        if progress is not None:
            progress(
                0.5 * (frame - frame_start + 1) / frame_count,
                f"采样 NLA 帧 {frame}/{frame_end}",
            )

    before_actions = {action.as_pointer() for action in bpy.data.actions}
    try:
        _bind_action(animation_data, None)
        animation_data.use_nla = False
        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)
            for pose_bone in pose_bones:
                location, rotation, scale = samples[frame][pose_bone.name].decompose()
                pose_bone.location = location
                pose_bone.rotation_mode = "QUATERNION"
                pose_bone.rotation_quaternion = rotation
                pose_bone.scale = scale
                pose_bone.keyframe_insert("rotation_quaternion", frame=frame)
                if pose_bone.name == "Hips":
                    pose_bone.keyframe_insert("location", frame=frame)
            if progress is not None:
                progress(
                    0.5 + 0.5 * (frame - frame_start + 1) / frame_count,
                    f"转换 NLA 帧 {frame}/{frame_end}",
                )

        temporary = animation_data.action
        if temporary is None:
            raise RuntimeError("无法为 NLA 创建临时求值 Action")
        temporary.name = "BAM_TMP_Proscenium_NLA_Evaluated"
        temporary[OWNER_KEY] = OWNER_VALUE
        temporary[TEMPORARY_KEY] = True
        for fcurve in _iter_action_fcurves(temporary):
            for point in fcurve.keyframe_points:
                point.interpolation = "LINEAR"
        state["temporary_action"] = temporary
        state["label"] = "Proscenium_NLA"
        return temporary
    except Exception:
        _bind_action(
            animation_data,
            state.get("previous_action"),
            state.get("previous_action_slot"),
        )
        animation_data.use_nla = bool(state.get("previous_use_nla"))
        for action in tuple(bpy.data.actions):
            if action.as_pointer() not in before_actions and action.users == 0:
                bpy.data.actions.remove(action)
        raise


def _prepare_source_action(scene, source, *, evaluate_nla: bool = False, progress=None) -> dict:
    animation_data = source.animation_data
    state = {
        "previous_action": animation_data.action,
        "previous_action_slot": _action_slot(animation_data),
        "previous_use_nla": bool(animation_data.use_nla),
        "previous_frame": scene.frame_current,
        "rotation_modes": {pose_bone.name: pose_bone.rotation_mode for pose_bone in source.pose.bones},
        "pose_matrices": {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in source.pose.bones},
        "temporary_action": None,
        "changed": False,
        "label": animation_data.action.name if animation_data.action else "Proscenium_NLA",
    }
    if animation_data.action is not None:
        # A Proscenium preview is the active Action. Do not accidentally
        # combine it with older accepted NLA tracks during depsgraph bake.
        if animation_data.use_nla:
            animation_data.use_nla = False
            state["changed"] = True
        if progress is not None:
            progress(1.0, "活动 Action 已就绪")
        return state

    strips = _effective_nla_strips(animation_data)
    if not strips:
        raise RuntimeError("官方骨架没有可用 Action 或 NLA 条带")
    if evaluate_nla:
        # A caller may opt into direct depsgraph evaluation of accepted NLA.
        state["label"] = strips[-1].action.name
        return state
    state["changed"] = True

    # The common Proscenium Accept path creates one unscaled strip whose
    # action range matches the strip range. Bind it directly so the native
    # engine reads the exact generated samples.
    strip = strips[0]
    action_start, action_end = strip.action.frame_range
    direct = (
        len(strips) == 1
        and abs(float(strip.scale) - 1.0) < 1e-6
        and abs(float(strip.frame_start) - float(action_start)) < 1e-4
        and abs(float(strip.frame_end) - float(action_end)) < 1e-4
        and abs(float(strip.action_frame_start) - float(action_start)) < 1e-4
        and abs(float(strip.action_frame_end) - float(action_end)) < 1e-4
    )
    if direct:
        animation_data.use_nla = False
        _bind_action(animation_data, strip.action)
        state["label"] = strip.action.name
        if progress is not None:
            progress(1.0, "已直接读取接受后的 NLA Action")
        return state

    try:
        _sample_nla_to_temporary_action(scene, source, state, progress=progress)
        return state
    except Exception:
        _restore_source_action(scene, source, state)
        raise


def _restore_source_action(scene, source, state: dict) -> None:
    if state.get("changed"):
        _bind_action(
            source.animation_data,
            state.get("previous_action"),
            state.get("previous_action_slot"),
        )
        source.animation_data.use_nla = bool(state.get("previous_use_nla"))
    for name, mode in state.get("rotation_modes", {}).items():
        pose_bone = source.pose.bones.get(name)
        if pose_bone is not None:
            pose_bone.rotation_mode = mode
    try:
        scene.frame_set(int(state.get("previous_frame", scene.frame_start)))
        for name, matrix in state.get("pose_matrices", {}).items():
            pose_bone = source.pose.bones.get(name)
            if pose_bone is not None:
                pose_bone.matrix_basis = matrix
        bpy.context.view_layer.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    temporary = state.get("temporary_action")
    if temporary is not None and temporary.users == 0:
        bpy.data.actions.remove(temporary)


class BAM_OT_auto_map(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.auto_map"
    bl_label = "自动映射官方骨架 → 角色"
    bl_description = (
        "检查 kimodo-soma-rp 官方骨架签名，识别 MMD 或 Auto-Rig Pro 主控制链，"
        "计算位移比例并建立仅由本插件管理的内部映射表"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        source, target, result, error = _prepare_mapping(context.scene, settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"已映射 {result.matched_count}/{result.expected_count} 对：{source.name} → {target.name}",
        )
        return {"FINISHED"}


class BAM_OT_prepare_from_proscenium(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.prepare_from_proscenium"
    bl_label = "自动准备角色输出"
    bl_description = (
        "优先读取 Proscenium 当前官方骨架；在未手动指定时自动选择最可信的 MMD/Auto-Rig Pro 目标，"
        "然后检查骨架签名、完整主链、重复目标、对象缩放和位移比例"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = scene.ba_motion_bridge_settings
        proscenium = getattr(scene, "proscenium", None)
        hosted_source = getattr(proscenium, "target_armature", None) if proscenium else None
        if _is_official_source(hosted_source) and settings.source_rig != hosted_source:
            settings.source_rig = hosted_source
            settings.source_origin = "Proscenium 当前骨架"
        _sync_proscenium_inplace(scene, settings)
        source, target, result, error = _prepare_mapping(scene, settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        settings.status_message = (
            f"已准备：{source.name} → {target.name}；"
            f"主链 {result.matched_count}/{result.expected_count}"
        )
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_validate_mapping(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.validate_mapping"
    bl_label = "检查映射"
    bl_description = (
        "不更换当前源和目标，只重新验证官方骨架签名、目标类型、主链覆盖率、"
        "重复通道、骨架层级和非等比对象缩放"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        _source, _target, result, error = _prepare_mapping(context.scene, settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_retarget(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.retarget"
    bl_label = "一键重定向到角色"
    bl_description = (
        "使用插件自有的世界空间 Rest Pose 求解器逐帧烘焙；生成独立 Action、"
        "修正 ToeBase/つま先轴差异、写入可选负帧缓冲，并保存可精确恢复的目标状态"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = scene.ba_motion_bridge_settings
        _sync_proscenium_inplace(scene, settings)
        source, target, result, error = _prepare_mapping(scene, settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        if not _animation_present(source):
            _set_failure(settings, "MOTION_MISSING", "官方骨架没有活动 Action 或已接受的 NLA 动作", "在 Proscenium 生成并接受动作")
            self.report({"ERROR"}, "官方骨架没有活动 Action 或已接受的 NLA 动作")
            return {"CANCELLED"}
        if settings.previous_target_state_available:
            try:
                baseline_target = settings.previous_target_rig
            except ReferenceError:
                baseline_target = None
            if baseline_target is not None and baseline_target != target:
                message = f"恢复基线属于 {baseline_target.name}；已阻止把同一会话切到 {target.name}"
                _set_failure(settings, "BASELINE_TARGET_CONFLICT", message, "在骨架区选择恢复上一角色或保留上一输出")
                self.report({"ERROR"}, message)
                return {"CANCELLED"}

        source_state = None
        animation_data = None
        previous_action = None
        previous_action_slot = None
        previous_action_slot_identifier = ""
        previous_action_fake_user = None
        previous_use_nla = False
        before_actions: set[int] = set()
        constraint_rows: list[dict] = []
        switch_rows_before_attempt = _target_switch_snapshot(target)
        physics_cache_before_attempt = _physics_cache_snapshot(scene)
        timeline_before_attempt = _timeline_snapshot(scene)
        disabled_constraints = 0
        created_action = None
        initial_pose: dict[str, Matrix] = {}
        buffer_result = None
        physics_result = {"status": "DISABLED", "evaluated_frames": 0}
        placement = None
        source_motion = "Proscenium_Motion"
        new_snapshot_written = False
        error_message = ""
        success = False
        operation_progress = _OperationProgress(context, settings, "输出角色动作")
        operation_progress.begin("准备源动作")
        try:
            source_state = _prepare_source_action(
                scene,
                source,
                evaluate_nla=False,
                progress=operation_progress.stage(0.02, 0.14, "准备源动作"),
            )
            source_motion = source_state["label"]
            operation_progress.update(0.16, "保存目标状态并切换 FK")

            animation_data = target.animation_data_create()
            previous_action = animation_data.action
            previous_action_slot = _action_slot(animation_data)
            previous_action_slot_identifier = _action_slot_identifier(previous_action_slot)
            previous_use_nla = bool(animation_data.use_nla)
            if previous_action is not None:
                previous_action_fake_user = bool(previous_action.use_fake_user)
                previous_action.use_fake_user = True

            placement = capture_placement_context(
                source,
                target,
                result,
                settings.motion_space,
            )

            if settings.use_start_buffer and (settings.settle_frames + settings.transition_frames) > 0:
                initial_pose = _capture_buffer_initial_pose(
                    scene,
                    settings,
                    target,
                    result,
                    placement,
                )

            before_actions = {action.as_pointer() for action in bpy.data.actions}
            _restored, restore_missing = _restore_saved_constraints(settings)
            if restore_missing:
                raise RuntimeError("上次腿链约束快照无法完整恢复；为避免叠加状态，已停止")

            constraint_rows = _mapped_constraint_snapshot(target, result)
            disabled_constraints = _disable_constraint_rows(target, constraint_rows)
            _bind_action(animation_data, None)
            animation_data.use_nla = False
            _force_target_fk_switches(target)

            source_rest_override = _build_source_rest_override(source, target, result, placement)
            bake_result = bake_retarget(
                scene,
                source,
                target,
                result,
                source_rest_override=source_rest_override,
                location_scale=settings.scale_ratio if settings.auto_scale else 1.0,
                world_location=bool(settings.world_location),
                motion_space=settings.motion_space,
                placement=placement,
                progress=operation_progress.stage(0.18, 0.76, "重定向"),
            )
            created_action = bake_result.action
            operation_progress.update(0.78, "整理输出 Action")

            created_action.name = f"ACT_{_safe_action_name(target.name)}_{_safe_action_name(source_motion)}_MMD"
            created_action.use_fake_user = True
            created_action[OWNER_KEY] = OWNER_VALUE
            created_action["bam_role"] = "RETARGET_OUTPUT"
            created_action["bam_source_object"] = source.name
            created_action["bam_target_object"] = target.name
            created_action["bam_mapping_signature"] = settings.mapping_signature
            created_action["bam_target_profile"] = result.target_profile
            created_action["bam_previous_action"] = previous_action.name if previous_action else ""
            created_action["bam_previous_action_slot"] = previous_action_slot_identifier
            created_action["bam_previous_use_nla"] = bool(previous_use_nla)
            created_action["bam_engine"] = "Proscenium Motion Bridge Native"
            created_action["bam_motion_space"] = settings.motion_space
            created_action["bam_placement_bone"] = placement.placement_bone if placement else ""
            created_action["bam_alignment_yaw_degrees"] = (
                placement.alignment_yaw_degrees if placement else 0.0
            )
            created_action["bam_disabled_constraint_count"] = disabled_constraints

            if settings.use_start_buffer and (settings.settle_frames + settings.transition_frames) > 0:
                buffer_result = _insert_start_buffer(
                    scene,
                    target,
                    created_action,
                    result,
                    initial_pose,
                    settings.settle_frames,
                    settings.transition_frames,
                    progress=operation_progress.stage(0.79, 0.90, "起始缓冲"),
                )
                created_action["bam_motion_frame_start"] = buffer_result["motion_start"]
                created_action["bam_motion_frame_end"] = buffer_result["motion_end"]
                created_action["bam_preroll_frame_start"] = buffer_result["preroll_start"]
                created_action["bam_preroll_settle_frames"] = int(settings.settle_frames)
                created_action["bam_preroll_transition_frames"] = int(settings.transition_frames)
                created_action["bam_initial_pose_source"] = settings.initial_pose_source
                if settings.evaluate_physics_preroll:
                    physics_result = _evaluate_physics_preroll(
                        scene,
                        buffer_result["preroll_start"],
                        buffer_result["motion_start"],
                        progress=operation_progress.stage(0.91, 0.98, "物理预热"),
                    )
                else:
                    _extend_preroll_timeline(scene, buffer_result["preroll_start"])
                created_action["bam_physics_preroll_status"] = physics_result["status"]
                created_action["bam_physics_preroll_frames"] = int(physics_result["evaluated_frames"])
                created_action["bam_timeline_frame_start"] = int(buffer_result["preroll_start"])
            else:
                operation_progress.update(0.98, "跳过起始缓冲")

            operation_progress.update(0.99, "保存恢复点与输出信息")
            settings.constraint_snapshot_json = (
                json.dumps(constraint_rows, ensure_ascii=False) if constraint_rows else ""
            )
            settings.constraint_snapshot_target = target.name if constraint_rows else ""
            settings.constraint_snapshot_target_rig = target if constraint_rows else None
            new_snapshot_written = bool(constraint_rows)
            settings.last_output_action = created_action.name
            if not settings.previous_target_state_available:
                settings.target_switch_snapshot_json = json.dumps(
                    switch_rows_before_attempt, ensure_ascii=False
                )
                settings.target_switch_snapshot_target = target.name
                settings.physics_cache_snapshot_json = json.dumps(
                    physics_cache_before_attempt, ensure_ascii=False
                )
                settings.timeline_snapshot_json = json.dumps(
                    timeline_before_attempt, ensure_ascii=False
                )
                settings.previous_target_state_available = True
                settings.previous_target_rig = target
                settings.previous_target_action = previous_action
                settings.previous_target_action_name = previous_action.name if previous_action else ""
                settings.previous_target_action_slot = previous_action_slot_identifier
                settings.previous_target_use_nla = bool(previous_use_nla)
                settings.previous_target_action_fake_user = bool(previous_action_fake_user or False)
            settings.status_level = "READY"
            settings.status_code = "RETARGET_COMPLETE"
            settings.next_action = "预览结果；需要回到角色原状态时点击恢复按钮"
            buffer_note = ""
            if buffer_result is not None:
                buffer_note = (
                    f"；预览范围从 {buffer_result['preroll_start']} 预滚动到正式首帧 "
                    f"{buffer_result['motion_start']}，当前停在 {buffer_result['preroll_start']}"
                )
                if physics_result["status"] == "BAKED_CACHE":
                    buffer_note += "；检测到已烘焙旧物理缓存，未自动预热"
                    settings.status_level = "WARNING"
                    settings.status_code = "RETARGET_COMPLETE_PHYSICS_CACHE_BAKED"
                    settings.next_action = "释放旧物理缓存后重新激活输出，或重新烘焙包含预滚动区的物理"
                elif physics_result["status"] == "NO_RIGID_BODY_WORLD":
                    buffer_note += "；尚未检测到刚体世界"
                    settings.status_level = "WARNING"
                    settings.status_code = "RETARGET_COMPLETE_NO_RIGID_BODY_WORLD"
                    settings.next_action = "先用 MMD Tools 建立刚体世界，再点“激活”以写入负帧缓存起点"
                elif physics_result["status"] == "EVALUATED":
                    buffer_note += f"；物理预热 {physics_result['evaluated_frames']} 帧"
            settings.status_message = (
                f"完成：{created_action.name}；{result.target_profile}；"
                f"暂时关闭 {disabled_constraints} 个相关约束{buffer_note}"
            )
            success = True
        except Exception as exc:
            error_message = str(exc)
            if constraint_rows:
                _restore_constraint_rows(target, constraint_rows)
            _restored_switches, missing_switches = _restore_target_switch_rows(
                target, switch_rows_before_attempt
            )
            if missing_switches:
                error_message += f"；{missing_switches} 个 IK/FK 状态无法恢复"
            _restore_physics_cache_snapshot(scene, physics_cache_before_attempt)
            _restore_timeline_snapshot(scene, timeline_before_attempt)
            failed_action = animation_data.action if animation_data is not None else None
            if animation_data is not None:
                try:
                    _bind_action(animation_data, previous_action, previous_action_slot)
                    animation_data.use_nla = previous_use_nla
                except (AttributeError, RuntimeError, TypeError):
                    pass
            if previous_action is not None and previous_action_fake_user is not None:
                previous_action.use_fake_user = previous_action_fake_user
            if (
                failed_action is not None
                and failed_action != previous_action
                and failed_action.as_pointer() not in before_actions
                and failed_action.users == 0
            ):
                bpy.data.actions.remove(failed_action)
            if new_snapshot_written:
                settings.constraint_snapshot_json = ""
                settings.constraint_snapshot_target = ""
                settings.constraint_snapshot_target_rig = None
        finally:
            if source_state is not None:
                _restore_source_action(scene, source, source_state)
            operation_progress.end()

        if not success:
            _set_failure(
                settings,
                "RETARGET_FAILED",
                f"重定向失败；原动作/NLA/约束已恢复：{error_message}",
                "按错误提示修正后重试；已接受的 Proscenium 动作不会丢失",
            )
            self.report({"ERROR"}, f"重定向失败，原动作/NLA/约束已恢复：{error_message}")
            return {"CANCELLED"}

        _activate_target(context, target)
        if buffer_result is not None:
            scene.frame_set(int(buffer_result["preroll_start"]))
            bpy.context.view_layer.update()
        self.report(
            {"INFO"},
            f"已生成独立动作 {created_action.name}；{result.matched_count} 对骨骼，"
            f"仅关闭 {disabled_constraints} 个已映射腿链/腰取消约束",
        )
        return {"FINISHED"}


class BAM_OT_accept_and_retarget(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.accept_and_retarget"
    bl_label = "接受并一键输出到角色"
    bl_description = (
        "若 Proscenium 正在预览则先 Accept；随后自动识别骨架、验证完整主链、"
        "用内置引擎生成独立 Action，并按设置写入负帧起始缓冲；进度显示在状态栏和本面板"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "ba_motion_bridge_settings")

    def execute(self, context):
        scene = context.scene
        settings = scene.ba_motion_bridge_settings
        proscenium = getattr(scene, "proscenium", None)
        hosted_source = getattr(proscenium, "target_armature", None) if proscenium else None
        if _is_official_source(hosted_source) and settings.source_rig != hosted_source:
            settings.source_rig = hosted_source
            settings.source_origin = "Proscenium 当前骨架"
        _sync_proscenium_inplace(scene, settings)
        accepted = False
        if settings.accept_preview_on_run and _proscenium_previewing(scene):
            if not operator_available("proscenium.accept"):
                self.report({"ERROR"}, "Proscenium Accept 未注册，请重启或重新启用插件")
                return {"CANCELLED"}
            try:
                accept_result = bpy.ops.proscenium.accept("EXEC_DEFAULT")
            except (AttributeError, RuntimeError) as exc:
                self.report({"ERROR"}, f"接受 Proscenium 预览失败：{exc}")
                return {"CANCELLED"}
            if accept_result != {"FINISHED"}:
                self.report({"ERROR"}, f"Proscenium Accept 未完成：{accept_result}")
                return {"CANCELLED"}
            accepted = True
        try:
            result = bpy.ops.ba_motion_bridge.retarget("EXEC_DEFAULT")
        except (AttributeError, RuntimeError) as exc:
            suffix = "；已接受的 Proscenium 动作仍保留" if accepted else ""
            self.report({"ERROR"}, f"角色输出失败：{exc}{suffix}")
            return {"CANCELLED"}
        if result != {"FINISHED"}:
            suffix = "；已接受的 Proscenium 动作仍保留" if accepted else ""
            self.report({"ERROR"}, f"角色输出未完成：{result}{suffix}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            "已接受预览并输出独立角色 Action" if accepted else "已输出独立角色 Action",
        )
        return {"FINISHED"}


class BAM_OT_activate_output(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.activate_output"
    bl_label = "激活上次角色输出"
    bl_description = (
        "把上次生成的独立 Action 重新绑定到当前目标，切换必要的 FK 状态，"
        "并从负帧缓冲起点逐帧预热未烘焙物理"
    )
    bl_options = {"REGISTER", "UNDO"}

    action_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    target_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        name = getattr(properties, "action_name", "")
        target_name = getattr(properties, "target_name", "")
        details = []
        if name:
            details.append(f"Action：{name}")
        if target_name:
            details.append(f"原目标：{target_name}")
        suffix = "\n" + "\n".join(details) if details else ""
        return (
            "重新绑定上次输出 Action，恢复输出所需的 FK 状态；若存在负帧缓冲，"
            "会逐帧预热未烘焙物理，且不会删除当前或旧 Action" + suffix
        )

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        return bool(settings and settings.last_output_action)

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        action = bpy.data.actions.get(settings.last_output_action)
        recorded_target_name = str(action.get("bam_target_object", "")) if action is not None else ""
        try:
            configured_target = settings.target_rig
        except ReferenceError:
            configured_target = None
        target = bpy.data.objects.get(recorded_target_name) if recorded_target_name else configured_target
        if recorded_target_name and target is None:
            self.report({"ERROR"}, f"输出 Action 记录的原目标 {recorded_target_name} 已不存在")
            return {"CANCELLED"}
        if action is None or not _is_armature(target):
            self.report({"ERROR"}, "上次输出 Action 或目标骨架已不存在")
            return {"CANCELLED"}
        animation_data = target.animation_data_create()
        operation_progress = _OperationProgress(context, settings, "重新激活输出")
        operation_progress.begin("绑定输出 Action")
        try:
            _bind_action(animation_data, action)
            animation_data.use_nla = False
            _force_target_fk_switches(target)
            operation_progress.update(0.12, "已绑定 Action，准备时间轴")
            motion_start = int(action.get("bam_motion_frame_start", context.scene.frame_start))
            preroll_start = int(action.get("bam_preroll_frame_start", motion_start))
            if preroll_start < motion_start:
                _evaluate_physics_preroll(
                    context.scene,
                    preroll_start,
                    motion_start,
                    progress=operation_progress.stage(0.15, 0.96, "重新预热"),
                )
            else:
                context.scene.frame_set(motion_start)
                operation_progress.update(0.96, "动作没有负帧缓冲，已定位首帧")
        except (AttributeError, RuntimeError, TypeError) as exc:
            self.report({"ERROR"}, f"激活输出失败：{exc}")
            return {"CANCELLED"}
        finally:
            operation_progress.end()
        _activate_target(context, target)
        settings.status_message = f"已激活输出：{action.name}"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_restore_constraints(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.restore_constraints"
    bl_label = "精确恢复腿链约束"
    bl_description = (
        "按重定向前记录的骨骼、约束名称、mute 和 influence 精确恢复腿链/腰取消约束；"
        "不会重置未参与映射的手臂、裙发、附件或物理约束"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        return bool(settings and settings.constraint_snapshot_json)

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        restored, missing = _restore_saved_constraints(settings)
        if missing:
            self.report({"ERROR"}, f"恢复了 {restored} 个约束，另有 {missing} 个已不存在；快照已保留")
            return {"CANCELLED"}
        settings.status_message = f"已精确恢复 {restored} 个腿链/腰取消约束"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_restore_previous_target_animation(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.restore_previous_target_animation"
    bl_label = "切回之前的目标动画"
    bl_description = (
        "把目标切回重定向前的 Action、Action Slot、NLA 与 IK/FK 状态，同时恢复时间轴和物理缓存起点；"
        "新输出 Action 仍作为数据块保留"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        return bool(settings and settings.previous_target_state_available)

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        try:
            target = settings.previous_target_rig
        except ReferenceError:
            target = None
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "之前的目标骨架已不存在，无法切回")
            return {"CANCELLED"}

        previous_action = settings.previous_target_action
        if previous_action is None and settings.previous_target_action_name:
            previous_action = bpy.data.actions.get(settings.previous_target_action_name)
        if previous_action is None and settings.previous_target_action_name:
            self.report({"ERROR"}, "之前的目标 Action 已不存在，恢复状态已保留")
            return {"CANCELLED"}

        animation_data = target.animation_data_create()
        current_action = animation_data.action
        if current_action is not None and current_action != previous_action:
            current_action.use_fake_user = True
        preferred_slot = _find_action_slot(previous_action, settings.previous_target_action_slot)
        try:
            _bind_action(animation_data, previous_action, preferred_slot)
            animation_data.use_nla = bool(settings.previous_target_use_nla)
            if previous_action is not None:
                previous_action.use_fake_user = bool(settings.previous_target_action_fake_user)
            restored_switches, missing_switches = _restore_saved_target_switches(settings, target)
            if missing_switches:
                raise RuntimeError(f"{missing_switches} 个 IK/FK 状态无法精确恢复")
            physics_restore = _restore_saved_physics_cache(context.scene, settings)
            timeline_restore = _restore_saved_timeline(context.scene, settings)
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
            self.report({"ERROR"}, f"切回目标动画失败：{exc}")
            return {"CANCELLED"}

        settings.previous_target_state_available = False
        settings.previous_target_rig = None
        settings.previous_target_action = None
        settings.previous_target_action_name = ""
        settings.previous_target_action_slot = ""
        switch_note = f"，恢复 {restored_switches} 个 IK/FK 状态" if restored_switches else ""
        physics_note = "，恢复物理缓存起点" if physics_restore == "RESTORED" else ""
        if physics_restore in {"INVALID", "SKIPPED"}:
            physics_note = "，物理缓存起点未改动"
        timeline_note = "，恢复原时间轴" if timeline_restore == "RESTORED" else ""
        if timeline_restore in {"INVALID", "SKIPPED"}:
            timeline_note = "，原时间轴未改动"
        settings.status_message = (
            f"已切回重定向前的目标动画{switch_note}{physics_note}{timeline_note}；桥接输出仍保留在 Action 数据块中"
        )
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_restore_previous_state(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.restore_previous_state"
    bl_label = "恢复角色原状态"
    bl_description = (
        "一次撤销本次桥接对角色状态的应用：恢复腿链约束、IK/FK、原 Action/NLA、"
        "时间轴和物理缓存起点；不会删除已生成的输出 Action"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        return bool(
            settings
            and (
                settings.constraint_snapshot_json
                or settings.previous_target_state_available
            )
        )

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        restored = []
        steps = (
            (bool(settings.constraint_snapshot_json), "ba_motion_bridge.restore_constraints", "约束"),
            (bool(settings.previous_target_state_available), "ba_motion_bridge.restore_previous_target_animation", "目标动画"),
        )
        for needed, path, label in steps:
            if not needed:
                continue
            namespace, name = path.split(".", 1)
            try:
                result = getattr(getattr(bpy.ops, namespace), name)("EXEC_DEFAULT")
            except (AttributeError, RuntimeError) as exc:
                _set_failure(settings, "RESTORE_FAILED", f"恢复{label}失败：{exc}", "不要继续重定向；先检查详细恢复项")
                self.report({"ERROR"}, settings.status_message)
                return {"CANCELLED"}
            if result != {"FINISHED"}:
                _set_failure(settings, "RESTORE_FAILED", f"恢复{label}未完成：{result}", "不要继续重定向；先检查详细恢复项")
                self.report({"ERROR"}, settings.status_message)
                return {"CANCELLED"}
            restored.append(label)
        settings.status_level = "READY"
        settings.status_code = "BASELINE_RESTORED"
        settings.next_action = "可继续选择或生成新的候选动作"
        settings.status_message = f"已恢复角色原状态：{'、'.join(restored)}；输出 Action 仍保留"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_resolve_target_switch(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.resolve_target_switch"
    bl_label = "处理上一角色恢复点"
    bl_description = (
        "切换目标角色前处理上一角色的恢复点：可先恢复上一角色的动画/约束/时间轴，"
        "也可明确保留当前输出并放弃该恢复点"
    )
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        items=(
            ("RESTORE", "恢复上一角色后切换", "恢复上一角色的 Action、约束、IK/FK、时间轴和缓存起点"),
            ("KEEP", "保留上一角色输出", "保留当前桥接输出和禁用约束，放弃对上一角色的一键恢复点"),
        )
    )

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        if not settings or not settings.previous_target_state_available:
            return False
        try:
            previous_target = settings.previous_target_rig
            target = settings.target_rig
        except ReferenceError:
            return False
        return bool(previous_target and target and previous_target != target)

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        target = settings.target_rig
        previous_target = settings.previous_target_rig
        previous_name = previous_target.name if previous_target else "上一角色"
        target_name = target.name if target else "新角色"

        if self.mode == "RESTORE":
            result = bpy.ops.ba_motion_bridge.restore_previous_state("EXEC_DEFAULT")
            if result != {"FINISHED"}:
                self.report({"ERROR"}, f"恢复 {previous_name} 未完成：{result}")
                return {"CANCELLED"}
            settings.target_rig = target
            settings.mapping_valid = False
            settings.status_level = "INFO"
            settings.status_code = "TARGET_SWITCH_RESOLVED"
            settings.next_action = "点击“自动识别并检查”"
            settings.status_message = f"已恢复 {previous_name}；现在可安全输出到 {target_name}"
        else:
            previous_action = settings.previous_target_action
            if previous_action is not None:
                previous_action.use_fake_user = bool(settings.previous_target_action_fake_user)
            settings.constraint_snapshot_json = ""
            settings.constraint_snapshot_target = ""
            settings.constraint_snapshot_target_rig = None
            settings.previous_target_state_available = False
            settings.previous_target_rig = None
            settings.previous_target_action = None
            settings.previous_target_action_name = ""
            settings.previous_target_action_slot = ""
            settings.target_switch_snapshot_json = ""
            settings.target_switch_snapshot_target = ""
            settings.physics_cache_snapshot_json = ""
            settings.timeline_snapshot_json = ""
            settings.mapping_valid = False
            settings.status_level = "INFO"
            settings.status_code = "TARGET_SWITCH_OUTPUT_KEPT"
            settings.next_action = "点击“自动识别并检查”"
            settings.status_message = f"已保留 {previous_name} 的桥接输出；现在可输出到 {target_name}"

        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_cleanup_temporary(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.cleanup_temporary"
    bl_label = "清理桥接临时资源"
    bl_description = (
        "只删除带 Proscenium Motion Bridge 所有权与 temporary 标记的未使用临时 Action/对象；"
        "不会删除输出 Action、用户动作、模型、贴图、预设或工程文件"
    )
    bl_options = {"REGISTER"}

    def execute(self, _context):
        removed_actions = 0
        removed_objects = 0
        for action in tuple(bpy.data.actions):
            if (
                action.get(OWNER_KEY) in OWNER_VALUES
                and action.get(TEMPORARY_KEY) is True
                and action.users == 0
            ):
                bpy.data.actions.remove(action)
                removed_actions += 1
        for obj in tuple(bpy.data.objects):
            if (
                obj.get(OWNER_KEY) in OWNER_VALUES
                and obj.get(TEMPORARY_KEY) is True
            ):
                # Objects linked to a temporary collection normally have a
                # collection user. Ownership tags make this exact enough to
                # unlink safely; untagged/user objects are never candidates.
                bpy.data.objects.remove(obj, do_unlink=True)
                removed_objects += 1
        self.report({"INFO"}, f"已清理 {removed_objects} 个对象、{removed_actions} 个 Action；未触碰输出动作")
        return {"FINISHED"}


CLASSES = (
    BAM_OT_prepare_from_proscenium,
    BAM_OT_auto_map,
    BAM_OT_validate_mapping,
    BAM_OT_retarget,
    BAM_OT_accept_and_retarget,
    BAM_OT_activate_output,
    BAM_OT_restore_constraints,
    BAM_OT_restore_previous_target_animation,
    BAM_OT_restore_previous_state,
    BAM_OT_resolve_target_switch,
    BAM_OT_cleanup_temporary,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
