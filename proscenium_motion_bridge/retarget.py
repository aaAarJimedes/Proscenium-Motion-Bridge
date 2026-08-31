from __future__ import annotations

from dataclasses import dataclass

import bpy
from mathutils import Matrix, Quaternion, Vector

from .mapping import MappingResult


@dataclass(frozen=True)
class BakeResult:
    action: bpy.types.Action
    frame_start: int
    frame_end: int
    keyed_channels: int


def _rotation_property(pose_bone) -> str:
    if pose_bone.rotation_mode == "QUATERNION":
        return "rotation_quaternion"
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _set_basis_rotation(pose_bone, rotation: Quaternion) -> None:
    if pose_bone.rotation_mode == "QUATERNION":
        pose_bone.rotation_quaternion = rotation
    elif pose_bone.rotation_mode == "AXIS_ANGLE":
        axis, angle = rotation.to_axis_angle()
        pose_bone.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
    else:
        pose_bone.rotation_euler = rotation.to_euler(pose_bone.rotation_mode)


def _bone_depth(bone) -> int:
    depth = 0
    current = bone.parent
    while current is not None:
        depth += 1
        current = current.parent
    return depth


def _frame_range(source) -> tuple[int, int]:
    animation_data = source.animation_data
    action = animation_data.action if animation_data else None
    if action is None:
        raise RuntimeError("官方骨架没有可烘焙的活动 Action")
    start, end = action.frame_range
    return int(start), int(end)


def _rest_invariants(source, target, pair, source_rest_override):
    source_pose_bone = source.pose.bones[pair.source]
    target_bone = target.data.bones[pair.target]
    source_edit_rest_world = source.matrix_world @ source_pose_bone.bone.matrix_local
    if source_rest_override and pair.source in source_rest_override:
        override_world = source.matrix_world @ source_rest_override[pair.source]
        source_rest_world = Matrix.LocRotScale(
            source_edit_rest_world.translation,
            override_world.to_quaternion(),
            (1.0, 1.0, 1.0),
        )
    else:
        source_rest_world = source_edit_rest_world
    target_rest_world = target.matrix_world @ target_bone.matrix_local
    source_rest_q = source_rest_world.to_quaternion()
    target_rest_q = target_rest_world.to_quaternion()
    axes = (pair.axes or "XYZ").upper()
    return {
        "pair": pair,
        "source_pose_bone": source_pose_bone,
        "source_rest_world": source_rest_world,
        "target_rest_world": target_rest_world,
        "rotation_offset": source_rest_q.inverted() @ target_rest_q,
        "location_frame": target_rest_q.inverted() @ source_rest_q,
        "target_rest_rotation_inverse": target_rest_world.to_3x3().inverted(),
        "rotation": pair.channels in {"ROT", "LOC_ROT"},
        "location": pair.channels in {"LOC", "LOC_ROT"},
        "axes": {axis for axis in axes if axis in "XYZ"},
    }


def bake_retarget(
    scene,
    source,
    target,
    result: MappingResult,
    *,
    source_rest_override: dict[str, Matrix] | None,
    location_scale: float,
    world_location: bool,
) -> BakeResult:
    """Bake Proscenium motion without reading or mutating another add-on.

    Rotation transfers the source world delta from its own rest frame onto
    the target rest frame, then back-solves the target bone basis through its
    current parent. Location is transferred either as a world-space rest
    delta or as a source-basis channel rotated into the target rest frame.
    """
    frame_start, frame_end = _frame_range(source)
    if frame_end < frame_start:
        raise RuntimeError("官方动作帧范围无效")

    valid_pairs = [
        pair
        for pair in result.pairs
        if pair.source in source.pose.bones and pair.target in target.pose.bones
    ]
    if not valid_pairs:
        raise RuntimeError("没有可烘焙的有效骨骼对")

    by_target: dict[str, list[dict]] = {}
    for pair in valid_pairs:
        by_target.setdefault(pair.target, []).append(
            _rest_invariants(source, target, pair, source_rest_override)
        )
    target_names = sorted(
        by_target,
        key=lambda name: _bone_depth(target.data.bones[name]),
    )

    animation_data = target.animation_data_create()
    action = bpy.data.actions.new("PMB_Retarget_Output")
    animation_data.action = action
    animation_data.use_nla = False

    for target_name in target_names:
        pose_bone = target.pose.bones[target_name]
        pose_bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()

    target_world_rotation_inverse = target.matrix_world.to_quaternion().inverted()
    last_quaternion: dict[str, Quaternion] = {}
    keyed_channels = 0

    hidden_state = []
    for obj in (source, target):
        hidden_state.append((obj, bool(obj.hide_viewport), bool(obj.hide_get())))
        obj.hide_viewport = False
        obj.hide_set(False)

    try:
        # The uncaptured first pass settles driven/MCH parent chains. Only the
        # second pass at frame_start writes keys.
        passes = [(frame_start, False)] + [
            (frame, True) for frame in range(frame_start, frame_end + 1)
        ]
        for frame, capture in passes:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            previous_depth = None

            for target_name in target_names:
                target_bone = target.data.bones[target_name]
                depth = _bone_depth(target_bone)
                if previous_depth is not None and depth != previous_depth:
                    bpy.context.view_layer.update()
                previous_depth = depth

                pose_bone = target.pose.bones[target_name]
                rows = by_target[target_name]
                parent_pose = (
                    target.pose.bones.get(target_bone.parent.name)
                    if target_bone.parent is not None
                    else None
                )
                parent_rotation = (
                    parent_pose.matrix.to_quaternion()
                    if parent_pose is not None
                    else Quaternion()
                )
                relative_rest = (
                    target_bone.parent.matrix_local.inverted() @ target_bone.matrix_local
                    if target_bone.parent is not None
                    else target_bone.matrix_local
                )

                rotation_written = False
                for row in rows:
                    if not row["rotation"]:
                        continue
                    source_pose_world_q = (
                        source.matrix_world @ row["source_pose_bone"].matrix
                    ).to_quaternion()
                    desired_world_q = source_pose_world_q @ row["rotation_offset"]
                    desired_armature_q = target_world_rotation_inverse @ desired_world_q
                    basis_q = (
                        relative_rest.to_quaternion().inverted()
                        @ parent_rotation.inverted()
                        @ desired_armature_q
                    )
                    previous_q = last_quaternion.get(target_name)
                    if previous_q is not None and previous_q.dot(basis_q) < 0.0:
                        basis_q = Quaternion((-basis_q.w, -basis_q.x, -basis_q.y, -basis_q.z))
                    last_quaternion[target_name] = basis_q.copy()
                    _set_basis_rotation(pose_bone, basis_q)
                    rotation_written = True

                location_written = False
                location = Vector((0.0, 0.0, 0.0))
                for row in rows:
                    if not row["location"]:
                        continue
                    if world_location:
                        source_head_world = (
                            source.matrix_world @ row["source_pose_bone"].matrix
                        ).translation
                        world_delta = source_head_world - row["source_rest_world"].translation
                        filtered = Vector((
                            world_delta.x if "X" in row["axes"] else 0.0,
                            world_delta.y if "Y" in row["axes"] else 0.0,
                            world_delta.z if "Z" in row["axes"] else 0.0,
                        ))
                        contribution = row["target_rest_rotation_inverse"] @ (
                            filtered * location_scale
                        )
                        location = contribution
                        location_written = bool(row["axes"])
                    else:
                        contribution = (
                            row["location_frame"] @ row["source_pose_bone"].location
                        ) * location_scale
                        if "X" in row["axes"]:
                            location.x = contribution.x
                            location_written = True
                        if "Y" in row["axes"]:
                            location.y = contribution.y
                            location_written = True
                        if "Z" in row["axes"]:
                            location.z = contribution.z
                            location_written = True
                if location_written:
                    pose_bone.location = location

                if not capture:
                    continue
                if rotation_written:
                    pose_bone.keyframe_insert(
                        _rotation_property(pose_bone),
                        frame=frame,
                        group=target_name,
                    )
                    keyed_channels += 1
                if location_written:
                    pose_bone.keyframe_insert("location", frame=frame, group=target_name)
                    keyed_channels += 1

            bpy.context.view_layer.update()
    except Exception:
        if animation_data.action == action:
            animation_data.action = None
        if action.users == 0:
            bpy.data.actions.remove(action)
        raise
    finally:
        for obj, hide_viewport, hide_get in hidden_state:
            obj.hide_viewport = hide_viewport
            obj.hide_set(hide_get)

    for fcurve in _iter_action_fcurves(action):
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"
        fcurve.update()
    scene.frame_set(frame_start)
    bpy.context.view_layer.update()
    return BakeResult(action, frame_start, frame_end, keyed_channels)


def _iter_action_fcurves(action):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        yield from legacy
        return
    slots = list(getattr(action, "slots", ()) or ())
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            channelbags = getattr(strip, "channelbags", None)
            if channelbags is not None:
                try:
                    for channelbag in channelbags:
                        yield from channelbag.fcurves
                    continue
                except TypeError:
                    pass
            channelbag_method = getattr(strip, "channelbag", None)
            if callable(channelbag_method):
                for slot in slots:
                    try:
                        channelbag = channelbag_method(slot)
                    except Exception:
                        channelbag = None
                    if channelbag is not None:
                        yield from channelbag.fcurves
