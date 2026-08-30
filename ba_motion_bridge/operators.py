from __future__ import annotations

import hashlib
import importlib
import json
import re
import statistics

import bpy

from .constants import (
    CANONICAL_MODEL_ID,
    CANONICAL_MODEL_KEY,
    OWNER_KEY,
    OWNER_VALUE,
    TEMPORARY_KEY,
)
from .mapping import MappingResult, build_mapping, is_official_canonical_bones, normalize


def operator_available(path: str) -> bool:
    namespace, name = path.split(".", 1)
    try:
        operator = getattr(getattr(bpy.ops, namespace), name)
        operator.get_rna_type()
    except (AttributeError, KeyError, RuntimeError):
        return False
    return True


def blendcap_ready() -> bool:
    return (
        hasattr(bpy.types.Scene, "blendcap_retarget_source")
        and hasattr(bpy.types.Scene, "blendcap_retarget_target")
        and hasattr(bpy.types.Scene, "blendcap_retarget_pairs")
        and operator_available("blendcap.apply_retarget")
    )


def mmd2blendcap_ready() -> bool:
    return operator_available("mmd2blendcap.apply_retarget_fk_safe")


def _blendcap_classic_engine_module():
    """Return BlendCap's version-locked engine module when available.

    BlendCap 1.0.5 ships the classic depsgraph evaluator behind a module
    switch. It is slower than the fcurve-direct default, but it evaluates
    accepted NLA and MMD TRANSFORM constraints exactly. We change the switch
    only for the synchronous transaction and always restore it afterward.
    """
    modules = [addon.module for addon in bpy.context.preferences.addons]
    base = next((name for name in modules if name.rsplit(".", 1)[-1] == "blendcap"), None)
    if base is None:
        return None
    try:
        module = importlib.import_module(base + ".blendcap.retarget.bake_fk")
    except ImportError:
        return None
    return module if hasattr(module, "USE_FAST_ENGINE") else None


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
    values = [abs(float(value)) for value in obj.scale]
    return max(values) - min(values) <= tolerance * max(max(values), 1.0)


def _auto_source(scene, settings):
    if _is_official_source(settings.source_rig):
        return settings.source_rig

    proscenium = getattr(scene, "proscenium", None)
    candidate = getattr(proscenium, "target_armature", None) if proscenium else None
    if _is_official_source(candidate):
        return candidate

    active = bpy.context.active_object
    if _is_official_source(active):
        return active

    return next((obj for obj in scene.objects if _is_official_source(obj)), None)


def _candidate_result(source, candidate, root_motion_mode: str) -> MappingResult | None:
    if not _is_armature(candidate) or candidate == source:
        return None
    try:
        return build_mapping(source, candidate, root_motion_mode)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return None


def _auto_target(scene, settings, source):
    if _is_armature(settings.target_rig) and settings.target_rig != source:
        return settings.target_rig

    candidates = []
    if blendcap_ready():
        candidates.append(getattr(scene, "blendcap_retarget_target", None))
    candidates.append(bpy.context.active_object)
    candidates.extend(obj for obj in scene.objects if obj.type == "ARMATURE")

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
                candidate.name,
                candidate,
            )
        )
    return min(ranked)[-1] if ranked else None


def _resolve_rigs(scene, settings):
    source = _auto_source(scene, settings)
    if source is not None and settings.source_rig != source:
        settings.source_rig = source
    target = _auto_target(scene, settings, source) if source is not None else None
    if target is not None and settings.target_rig != target:
        settings.target_rig = target
    return source, target


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


def _mapping_payload(source, target, root_motion_mode: str, result: MappingResult) -> dict:
    return {
        "schema": 1,
        "source_object": source.name,
        "source_data": source.data.name,
        "target_object": target.name,
        "target_data": target.data.name,
        "root_motion_mode": root_motion_mode,
        "pairs": [pair.to_dict() for pair in result.pairs],
        "missing": list(result.missing),
        "critical_missing": list(result.critical_missing),
        "warnings": list(result.warnings),
        "expected_count": result.expected_count,
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
    settings.status_message = message


def _json_scalar(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return None


def _serialize_blendcap_pair(pair) -> dict:
    result = {}
    for prop in pair.bl_rna.properties:
        identifier = prop.identifier
        if identifier == "rna_type" or prop.is_readonly or prop.type in {"COLLECTION", "POINTER"}:
            continue
        try:
            value = _json_scalar(getattr(pair, identifier))
        except (AttributeError, RuntimeError, TypeError):
            continue
        if value is not None:
            result[identifier] = value
    return result


_BLENDCAP_TRANSACTION_FIELDS = (
    "blendcap_retarget_source",
    "blendcap_retarget_target",
    "blendcap_retarget_preset",
    "blendcap_retarget_source_prefix",
    "blendcap_retarget_namespace_strip",
    "blendcap_retarget_auto_scale",
    "blendcap_retarget_use_world_location",
    "blendcap_retarget_use_current_pose_as_rest",
    "blendcap_retarget_current_pose_full_matrix",
    "blendcap_retarget_auto_bake_ik",
    "mmd2blendcap_matched",
    "mmd2blendcap_total",
    "mmd2blendcap_unmatched",
    "mmd2blendcap_hips_target",
)


def _capture_blendcap_state(scene, settings) -> dict:
    state = {
        "scene": {
            name: getattr(scene, name)
            for name in _BLENDCAP_TRANSACTION_FIELDS
            if hasattr(scene, name)
        },
        "pairs": [
            _serialize_blendcap_pair(pair)
            for pair in getattr(scene, "blendcap_retarget_pairs", ())
        ],
        "settings": {
            "bridge_owns_current_table": bool(settings.bridge_owns_current_table),
            "previous_blendcap_mapping_json": settings.previous_blendcap_mapping_json,
            "previous_blendcap_source": settings.previous_blendcap_source,
            "previous_blendcap_target": settings.previous_blendcap_target,
        },
    }
    blendcap_props = getattr(scene, "blendcap_props", None)
    if blendcap_props is not None and hasattr(blendcap_props, "use_custom_rest_pose"):
        state["use_custom_rest_pose"] = bool(blendcap_props.use_custom_rest_pose)
    return state


def _restore_blendcap_state(scene, settings, state: dict) -> None:
    scene_values = state.get("scene", {})
    # Pointer updates can internally reload a preset, so restore them and
    # other flags first, rebuild the exact table second, and restore the
    # enum display value last.
    for name, value in scene_values.items():
        if name != "blendcap_retarget_preset":
            _assign_if_present(scene, name, value)
    pairs = getattr(scene, "blendcap_retarget_pairs", None)
    if pairs is not None:
        pairs.clear()
        for row in state.get("pairs", ()):
            item = pairs.add()
            for name, value in row.items():
                _assign_if_present(item, name, value)
    if "blendcap_retarget_preset" in scene_values:
        _assign_if_present(
            scene,
            "blendcap_retarget_preset",
            scene_values["blendcap_retarget_preset"],
        )
    blendcap_props = getattr(scene, "blendcap_props", None)
    if blendcap_props is not None and "use_custom_rest_pose" in state:
        _assign_if_present(
            blendcap_props,
            "use_custom_rest_pose",
            state["use_custom_rest_pose"],
        )
    for name, value in state.get("settings", {}).items():
        setattr(settings, name, value)


def _snapshot_previous_mapping(scene, settings) -> None:
    if settings.bridge_owns_current_table or settings.previous_blendcap_mapping_json:
        return
    pairs = getattr(scene, "blendcap_retarget_pairs", None)
    if pairs is None or len(pairs) == 0:
        return
    settings.previous_blendcap_mapping_json = json.dumps(
        [_serialize_blendcap_pair(pair) for pair in pairs],
        ensure_ascii=False,
    )
    source = getattr(scene, "blendcap_retarget_source", None)
    target = getattr(scene, "blendcap_retarget_target", None)
    settings.previous_blendcap_source = source.name if source else ""
    settings.previous_blendcap_target = target.name if target else ""


def _assign_if_present(owner, name: str, value) -> None:
    if hasattr(owner, name):
        try:
            setattr(owner, name, value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def _write_blendcap_mapping(scene, settings, source, target, result: MappingResult) -> None:
    _snapshot_previous_mapping(scene, settings)

    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    _assign_if_present(scene, "blendcap_retarget_preset", "__UNSAVED__")
    _assign_if_present(scene, "blendcap_retarget_source_prefix", "")
    _assign_if_present(scene, "blendcap_retarget_namespace_strip", "")
    # BlendCap's built-in auto-height scans every target pose bone, which is
    # unstable for MMD rigs containing tall hair, weapons, wings, or effects.
    # We instead put a semantic body-landmark median on the two LOC pairs.
    _assign_if_present(scene, "blendcap_retarget_auto_scale", False)
    _assign_if_present(scene, "blendcap_retarget_use_world_location", settings.world_location)
    _assign_if_present(scene, "blendcap_retarget_use_current_pose_as_rest", False)
    _assign_if_present(scene, "blendcap_retarget_current_pose_full_matrix", False)
    _assign_if_present(scene, "blendcap_retarget_auto_bake_ik", False)

    blendcap_props = getattr(scene, "blendcap_props", None)
    if blendcap_props is not None:
        _assign_if_present(blendcap_props, "use_custom_rest_pose", False)

    scene.blendcap_retarget_pairs.clear()
    for pair in result.pairs:
        item = scene.blendcap_retarget_pairs.add()
        item.source = pair.source
        item.target = pair.target
        item.channels = pair.channels
        item.axes = pair.axes
        item.influence = pair.influence
        if pair.channels == "LOC" and hasattr(item, "loc_scale"):
            item.loc_scale = settings.scale_ratio if settings.auto_scale else 1.0

    _assign_if_present(scene, "mmd2blendcap_matched", result.matched_count)
    _assign_if_present(scene, "mmd2blendcap_total", result.expected_count)
    _assign_if_present(scene, "mmd2blendcap_unmatched", ", ".join(result.missing))
    hips = next((pair.target for pair in result.pairs if pair.role == "hips_rotation"), "")
    _assign_if_present(scene, "mmd2blendcap_hips_target", hips)
    settings.bridge_owns_current_table = True


def _prepare_mapping(scene, settings, write_table: bool):
    source, target = _resolve_rigs(scene, settings)
    if source is None:
        return None, None, None, "未找到带 kimodo-soma-rp 标记的 Proscenium 官方骨架"
    if not _is_official_source(source):
        return source, None, None, "源骨架不是完整的 Proscenium kimodo-soma-rp 官方骨架"
    if target is None:
        return source, None, None, "未找到可映射的 MMD 目标骨架"
    if source == target:
        return source, target, None, "源骨架和目标骨架不能是同一个对象"
    if not _uniform_scale(source) or not _uniform_scale(target):
        return source, target, None, "检测到非等比对象缩放；请先应用缩放，避免位移和骨长失真"

    result = build_mapping(source, target, settings.root_motion_mode)
    settings.scale_ratio = _semantic_scale_ratio(source, target, result)
    payload = _mapping_payload(source, target, settings.root_motion_mode, result)
    signature = _mapping_signature(source, target, payload)
    settings.mapping_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    settings.mapping_signature = signature
    valid = not result.critical_missing
    if valid:
        message = f"高置信度：{result.matched_count}/{result.expected_count} 对主链已映射"
    else:
        message = f"关键骨缺失：{'、'.join(result.critical_missing)}"
    _set_status(settings, result, valid, message)

    if write_table and valid:
        if not blendcap_ready():
            return source, target, result, "BlendCap 未启用，无法写入世界空间重定向表"
        _write_blendcap_mapping(scene, settings, source, target, result)
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
        "left_toe",
        "right_thigh",
        "right_shin",
        "right_foot",
        "right_toe",
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
    suitable = list(getattr(animation_data, "action_suitable_slots", ()) or ())
    if suitable:
        try:
            animation_data.action_slot = suitable[0]
        except (AttributeError, RuntimeError, TypeError):
            pass


def _sample_nla_to_temporary_action(scene, source, state: dict):
    animation_data = source.animation_data
    strips = _effective_nla_strips(animation_data)
    frame_start = max(scene.frame_start, int(min(strip.frame_start for strip in strips)))
    frame_end = min(scene.frame_end, int(max(strip.frame_end for strip in strips)))
    if frame_end < frame_start:
        raise RuntimeError("NLA 条带不在当前场景帧范围内")

    pose_bones = [source.pose.bones[bone.name] for bone in source.data.bones]
    samples: dict[int, dict[str, object]] = {}
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        samples[frame] = {pose_bone.name: pose_bone.matrix_basis.copy() for pose_bone in pose_bones}

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


def _prepare_source_action(scene, source, *, evaluate_nla: bool = False) -> dict:
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
        return state

    strips = _effective_nla_strips(animation_data)
    if not strips:
        raise RuntimeError("官方骨架没有可用 Action 或 NLA 条带")
    if evaluate_nla:
        # BlendCap Classic evaluates the depsgraph, so accepted/combined NLA
        # can stay exactly as authored. No temporary Action is required.
        state["label"] = strips[-1].action.name
        return state
    state["changed"] = True

    # The common Proscenium Accept path creates one unscaled strip whose
    # action range matches the strip range. Bind it directly so BlendCap's
    # fcurve-direct engine reads the exact generated samples.
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
        return state

    try:
        _sample_nla_to_temporary_action(scene, source, state)
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
    bl_label = "自动映射官方骨架 → MMD"
    bl_description = "识别官方 SOMA 骨架语义并在内存中生成 BlendCap 重定向表；不会写 preset 文件"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        source, target, result, error = _prepare_mapping(context.scene, settings, write_table=True)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"已映射 {result.matched_count}/{result.expected_count} 对：{source.name} → {target.name}",
        )
        return {"FINISHED"}


class BAM_OT_validate_mapping(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.validate_mapping"
    bl_label = "检查映射"
    bl_description = "重新检查官方骨架签名、MMD 主链覆盖率、层级和对象缩放"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.ba_motion_bridge_settings
        _source, _target, result, error = _prepare_mapping(context.scene, settings, write_table=False)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_retarget(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.retarget"
    bl_label = "一键重定向到 MMD"
    bl_description = (
        "自动映射并调用 BlendCap 的世界空间 rest-pose bake；先新建独立 Action，"
        "再以可精确恢复的窄范围 FK-safe 事务保护 MMD 腿链"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = scene.ba_motion_bridge_settings
        source, target, result, error = _prepare_mapping(scene, settings, write_table=False)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        if not blendcap_ready():
            self.report({"ERROR"}, "BlendCap 未启用，无法执行世界空间 rest-pose bake")
            return {"CANCELLED"}
        if not _animation_present(source):
            self.report({"ERROR"}, "官方骨架没有活动 Action 或已接受的 NLA 动作")
            return {"CANCELLED"}

        blendcap_state = _capture_blendcap_state(scene, settings)
        classic_module = _blendcap_classic_engine_module()
        previous_engine = getattr(classic_module, "USE_FAST_ENGINE", None) if classic_module else None
        source_state = None
        animation_data = None
        previous_action = None
        previous_action_slot = None
        previous_action_slot_identifier = ""
        previous_action_fake_user = None
        previous_use_nla = False
        before_actions: set[int] = set()
        constraint_rows: list[dict] = []
        disabled_constraints = 0
        created_action = None
        source_motion = "Proscenium_Motion"
        new_snapshot_written = False
        error_message = ""
        success = False
        try:
            if classic_module is not None:
                classic_module.USE_FAST_ENGINE = False
            _write_blendcap_mapping(scene, settings, source, target, result)
            source_state = _prepare_source_action(
                scene,
                source,
                evaluate_nla=classic_module is not None,
            )
            source_motion = source_state["label"]

            animation_data = target.animation_data_create()
            previous_action = animation_data.action
            previous_action_slot = _action_slot(animation_data)
            previous_action_slot_identifier = _action_slot_identifier(previous_action_slot)
            previous_use_nla = bool(animation_data.use_nla)
            if previous_action is not None:
                previous_action_fake_user = bool(previous_action.use_fake_user)
                previous_action.use_fake_user = True

            before_actions = {action.as_pointer() for action in bpy.data.actions}
            _restored, restore_missing = _restore_saved_constraints(settings)
            if restore_missing:
                raise RuntimeError("上次腿链约束快照无法完整恢复；为避免叠加状态，已停止")

            constraint_rows = _mapped_constraint_snapshot(target, result)
            disabled_constraints = _disable_constraint_rows(target, constraint_rows)
            _bind_action(animation_data, None)
            animation_data.use_nla = False

            bake_result = bpy.ops.blendcap.apply_retarget("EXEC_DEFAULT")
            created_action = animation_data.action
            if bake_result != {"FINISHED"} or created_action is None:
                raise RuntimeError(f"BlendCap bake 未完成：{bake_result}")

            created_action.name = f"ACT_{_safe_action_name(target.name)}_{_safe_action_name(source_motion)}_MMD"
            created_action.use_fake_user = True
            created_action[OWNER_KEY] = OWNER_VALUE
            created_action["bam_role"] = "RETARGET_OUTPUT"
            created_action["bam_source_object"] = source.name
            created_action["bam_target_object"] = target.name
            created_action["bam_mapping_signature"] = settings.mapping_signature
            created_action["bam_previous_action"] = previous_action.name if previous_action else ""
            created_action["bam_previous_action_slot"] = previous_action_slot_identifier
            created_action["bam_previous_use_nla"] = bool(previous_use_nla)
            created_action["bam_engine"] = "BlendCap Classic" if classic_module is not None else "BlendCap Fast"
            created_action["bam_disabled_constraint_count"] = disabled_constraints

            settings.constraint_snapshot_json = (
                json.dumps(constraint_rows, ensure_ascii=False) if constraint_rows else ""
            )
            settings.constraint_snapshot_target = target.name if constraint_rows else ""
            settings.constraint_snapshot_target_rig = target if constraint_rows else None
            new_snapshot_written = bool(constraint_rows)
            settings.last_output_action = created_action.name
            settings.previous_target_state_available = True
            settings.previous_target_rig = target
            settings.previous_target_action = previous_action
            settings.previous_target_action_name = previous_action.name if previous_action else ""
            settings.previous_target_action_slot = previous_action_slot_identifier
            settings.previous_target_use_nla = bool(previous_use_nla)
            settings.previous_target_action_fake_user = bool(previous_action_fake_user or False)
            settings.status_message = f"完成：{created_action.name}（原动作已保留）"
            success = True
        except Exception as exc:
            error_message = str(exc)
            if constraint_rows:
                _restore_constraint_rows(target, constraint_rows)
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
            try:
                _restore_blendcap_state(scene, settings, blendcap_state)
            except Exception as restore_exc:
                error_message += f"；BlendCap 映射回滚失败：{restore_exc}"
        finally:
            try:
                if source_state is not None:
                    _restore_source_action(scene, source, source_state)
            finally:
                if classic_module is not None:
                    classic_module.USE_FAST_ENGINE = previous_engine

        if not success:
            self.report({"ERROR"}, f"重定向失败，原动作/NLA/约束已恢复：{error_message}")
            return {"CANCELLED"}

        _activate_target(context, target)
        self.report(
            {"INFO"},
            f"已生成独立动作 {created_action.name}；{result.matched_count} 对骨骼，"
            f"仅关闭 {disabled_constraints} 个已映射腿链/腰取消约束",
        )
        return {"FINISHED"}


class BAM_OT_restore_constraints(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.restore_constraints"
    bl_label = "精确恢复腿链约束"
    bl_description = "按重定向前记录的 owner/name/mute/influence 精确恢复约束，不强制改成默认值"
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
    bl_description = "恢复重定向前的目标 Action、Action Slot 和 NLA 开关；新输出 Action 会继续保留"
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
            self.report({"ERROR"}, f"切回目标动画失败：{exc}")
            return {"CANCELLED"}

        settings.previous_target_state_available = False
        settings.previous_target_rig = None
        settings.previous_target_action = None
        settings.previous_target_action_name = ""
        settings.previous_target_action_slot = ""
        settings.status_message = "已切回重定向前的目标动画；桥接输出仍保留在 Action 数据块中"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_restore_previous_mapping(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.restore_previous_mapping"
    bl_label = "恢复之前的 BlendCap 映射"
    bl_description = "恢复桥接器第一次写表前的内存骨骼对；不会读取或覆盖 preset 文件"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "ba_motion_bridge_settings", None)
        return bool(settings and settings.previous_blendcap_mapping_json and blendcap_ready())

    def execute(self, context):
        scene = context.scene
        settings = scene.ba_motion_bridge_settings
        try:
            rows = json.loads(settings.previous_blendcap_mapping_json)
        except json.JSONDecodeError as exc:
            self.report({"ERROR"}, f"映射备份无效：{exc}")
            return {"CANCELLED"}
        if not isinstance(rows, list):
            self.report({"ERROR"}, "映射备份格式无效")
            return {"CANCELLED"}

        if settings.previous_blendcap_source:
            _assign_if_present(scene, "blendcap_retarget_source", bpy.data.objects.get(settings.previous_blendcap_source))
        if settings.previous_blendcap_target:
            _assign_if_present(scene, "blendcap_retarget_target", bpy.data.objects.get(settings.previous_blendcap_target))
        scene.blendcap_retarget_pairs.clear()
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = scene.blendcap_retarget_pairs.add()
            for name, value in row.items():
                _assign_if_present(item, name, value)
        count = len(scene.blendcap_retarget_pairs)
        settings.previous_blendcap_mapping_json = ""
        settings.previous_blendcap_source = ""
        settings.previous_blendcap_target = ""
        settings.bridge_owns_current_table = False
        settings.mapping_valid = False
        settings.status_message = f"已恢复之前的 BlendCap 映射（{count} 对）"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class BAM_OT_cleanup_temporary(bpy.types.Operator):
    bl_idname = "ba_motion_bridge.cleanup_temporary"
    bl_label = "清理桥接临时资源"
    bl_description = "只移除本插件标记且未被使用的临时 Action/对象；不会删除重定向结果"
    bl_options = {"REGISTER"}

    def execute(self, _context):
        removed_actions = 0
        removed_objects = 0
        for action in tuple(bpy.data.actions):
            if (
                action.get(OWNER_KEY) == OWNER_VALUE
                and action.get(TEMPORARY_KEY) is True
                and action.users == 0
            ):
                bpy.data.actions.remove(action)
                removed_actions += 1
        for obj in tuple(bpy.data.objects):
            if (
                obj.get(OWNER_KEY) == OWNER_VALUE
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
    BAM_OT_auto_map,
    BAM_OT_validate_mapping,
    BAM_OT_retarget,
    BAM_OT_restore_constraints,
    BAM_OT_restore_previous_target_animation,
    BAM_OT_restore_previous_mapping,
    BAM_OT_cleanup_temporary,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
