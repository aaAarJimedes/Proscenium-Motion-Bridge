from __future__ import annotations

from dataclasses import dataclass
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .mapping import MappingResult


@dataclass(frozen=True)
class BakeResult:
    action: bpy.types.Action
    frame_start: int
    frame_end: int
    keyed_channels: int


@dataclass(frozen=True)
class PlacementContext:
    motion_space: str
    alignment_rotation: Quaternion
    placement_rotation: Quaternion
    baseline_basis: dict[str, Matrix]
    baseline_locations: dict[str, Vector]
    placement_bone: str
    alignment_yaw_degrees: float


_TARGET_PLACEMENT = "TARGET_PLACEMENT"
_FORWARD = Vector((0.0, -1.0, 0.0))
_UP = Vector((0.0, 0.0, 1.0))
_PLACEMENT_BONE_NAMES = (
    "全ての親",
    "全親",
    "parentnode",
    "c_pos",
    "c_traj",
    "c_root_master.x",
)
_FALLBACK_PLACEMENT_BONE_NAMES = (
    "センター",
    "center",
    "グルーブ",
    "groove",
)


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


def _mapped_channel_targets(result: MappingResult) -> tuple[set[str], set[str]]:
    rotation_targets: set[str] = set()
    location_targets: set[str] = set()
    for pair in result.pairs:
        if pair.channels in {"ROT", "LOC_ROT"}:
            rotation_targets.add(pair.target)
        if pair.channels in {"LOC", "LOC_ROT"}:
            location_targets.add(pair.target)
    return rotation_targets, location_targets


def _horizontal_heading(rotation: Quaternion) -> float | None:
    forward = rotation @ _FORWARD
    forward.z = 0.0
    if forward.length_squared <= 1e-12:
        return None
    forward.normalize()
    return math.atan2(forward.y, forward.x)


def _yaw_between(source_rotation: Quaternion, target_rotation: Quaternion) -> Quaternion:
    source_heading = _horizontal_heading(source_rotation)
    target_heading = _horizontal_heading(target_rotation)
    if source_heading is None or target_heading is None:
        return Quaternion()
    angle = math.atan2(
        math.sin(target_heading - source_heading),
        math.cos(target_heading - source_heading),
    )
    return Quaternion(_UP, angle)


def _placement_bone_name(target, result: MappingResult) -> str:
    lookup = {bone.name.casefold(): bone.name for bone in target.data.bones}
    # Prefer a dedicated world/placement control. Unlike Center/Groove, this
    # bone is normally not animated by a previous retarget output, so its
    # evaluated pose is a stable statement of the user's scene placement.
    for candidate in _PLACEMENT_BONE_NAMES:
        name = lookup.get(candidate.casefold())
        if name is not None:
            return name

    # Minimal rigs may only expose the mapped horizontal root. Keep that
    # useful fallback, but do not let it outrank a dedicated placement bone.
    for pair in result.pairs:
        if pair.role == "root_xy" and pair.target in target.pose.bones:
            return pair.target
    for candidate in _FALLBACK_PLACEMENT_BONE_NAMES:
        name = lookup.get(candidate.casefold())
        if name is not None:
            return name
    return ""


def capture_placement_context(
    source,
    target,
    result: MappingResult,
    motion_space: str = _TARGET_PLACEMENT,
) -> PlacementContext:
    """Freeze target placement before its previous animation is unbound.

    Object/parent transforms are already represented by ``matrix_world``.
    An evaluated MMD/ARP placement control adds a world-space yaw delta; root
    locations are captured separately so retargeted motion can be additive.
    """
    rotation_targets, location_targets = _mapped_channel_targets(result)
    target_names = rotation_targets | location_targets
    baseline_basis = {
        name: target.pose.bones[name].matrix_basis.copy()
        for name in target_names
        if name in target.pose.bones
    }
    baseline_locations = {
        name: target.pose.bones[name].location.copy()
        for name in location_targets
        if name in target.pose.bones
    }

    placement_bone = _placement_bone_name(target, result)
    placement_rotation = Quaternion()
    if motion_space == _TARGET_PLACEMENT and placement_bone:
        pose_bone = target.pose.bones[placement_bone]
        rest_world_q = (target.matrix_world @ pose_bone.bone.matrix_local).to_quaternion()
        pose_world_q = (target.matrix_world @ pose_bone.matrix).to_quaternion()
        pose_delta_q = pose_world_q @ rest_world_q.inverted()
        placement_rotation = _yaw_between(
            target.matrix_world.to_quaternion(),
            pose_delta_q @ target.matrix_world.to_quaternion(),
        )

    target_facing = placement_rotation @ target.matrix_world.to_quaternion()
    alignment_rotation = (
        _yaw_between(source.matrix_world.to_quaternion(), target_facing)
        if motion_space == _TARGET_PLACEMENT
        else Quaternion()
    )
    _axis, angle = alignment_rotation.to_axis_angle()
    signed_angle = math.atan2(
        2.0 * (alignment_rotation.w * alignment_rotation.z),
        1.0 - 2.0 * alignment_rotation.z * alignment_rotation.z,
    )
    if abs(angle) <= 1e-12:
        signed_angle = 0.0
    return PlacementContext(
        motion_space=motion_space,
        alignment_rotation=alignment_rotation,
        placement_rotation=placement_rotation,
        baseline_basis=baseline_basis,
        baseline_locations=baseline_locations,
        placement_bone=placement_bone,
        alignment_yaw_degrees=math.degrees(signed_angle),
    )


def _rest_invariants(source, target, pair, source_rest_override, placement):
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
    if placement.motion_space == _TARGET_PLACEMENT:
        target_rest_world = Matrix.LocRotScale(
            target_rest_world.translation,
            placement.placement_rotation @ target_rest_world.to_quaternion(),
            target_rest_world.to_scale(),
        )
    source_rest_q = source_rest_world.to_quaternion()
    target_rest_q = target_rest_world.to_quaternion()
    axes = (pair.axes or "XYZ").upper()
    return {
        "pair": pair,
        "source_pose_bone": source_pose_bone,
        "source_rest_world": source_rest_world,
        "target_rest_world": target_rest_world,
        "source_rest_rotation": source_rest_q,
        "source_rest_rotation_inverse": source_rest_q.inverted(),
        "target_rest_rotation": target_rest_q,
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
    motion_space: str = _TARGET_PLACEMENT,
    placement: PlacementContext | None = None,
    progress=None,
) -> BakeResult:
    """Bake Proscenium motion without reading or mutating another add-on.

    Target-placement mode rotates world-space pose and root-motion deltas into
    the target's initial horizontal facing, preserves its object transform,
    and adds root motion on top of captured MMD/ARP placement controls.
    Source-world mode retains the v0.7 behavior for compatibility.
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

    if placement is None:
        placement = capture_placement_context(source, target, result, motion_space)
    use_target_placement = placement.motion_space == _TARGET_PLACEMENT
    alignment_q = placement.alignment_rotation
    alignment_q_inverse = alignment_q.inverted()

    by_target: dict[str, list[dict]] = {}
    for pair in valid_pairs:
        by_target.setdefault(pair.target, []).append(
            _rest_invariants(source, target, pair, source_rest_override, placement)
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
        pose_bone.matrix_basis = (
            placement.baseline_basis.get(target_name, Matrix.Identity(4)).copy()
            if use_target_placement
            else Matrix.Identity(4)
        )
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
        if progress is not None:
            progress(0.0, "初始化目标骨架")
        # The uncaptured first pass settles driven/MCH parent chains. Only the
        # second pass at frame_start writes keys.
        passes = [(frame_start, False)] + [
            (frame, True) for frame in range(frame_start, frame_end + 1)
        ]
        for frame, capture in passes:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            if capture and progress is not None:
                frame_count = max(1, frame_end - frame_start + 1)
                progress(
                    (frame - frame_start + 1) / frame_count,
                    f"烘焙动作帧 {frame}/{frame_end}",
                )
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
                location_frame_world = target.matrix_world @ (
                    parent_pose.matrix @ relative_rest
                    if parent_pose is not None
                    else target_bone.matrix_local
                )
                target_location_world_inverse = location_frame_world.to_3x3().inverted()

                rotation_written = False
                for row in rows:
                    if not row["rotation"]:
                        continue
                    source_pose_world_q = (
                        source.matrix_world @ row["source_pose_bone"].matrix
                    ).to_quaternion()
                    if use_target_placement:
                        source_delta_q = source_pose_world_q @ row["source_rest_rotation_inverse"]
                        desired_world_q = (
                            alignment_q
                            @ source_delta_q
                            @ alignment_q_inverse
                            @ row["target_rest_rotation"]
                        )
                    else:
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
                location = (
                    placement.baseline_locations.get(target_name, Vector()).copy()
                    if use_target_placement
                    else Vector()
                )
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
                        if use_target_placement:
                            filtered = alignment_q @ filtered
                        contribution = (
                            target_location_world_inverse
                            if use_target_placement
                            else row["target_rest_rotation_inverse"]
                        ) @ (filtered * location_scale)
                        if use_target_placement:
                            location += contribution
                        else:
                            location = contribution
                        location_written = bool(row["axes"])
                    else:
                        if use_target_placement:
                            source_local = row["source_pose_bone"].location
                            source_world = row["source_rest_rotation"] @ source_local
                            filtered = Vector((
                                source_world.x if "X" in row["axes"] else 0.0,
                                source_world.y if "Y" in row["axes"] else 0.0,
                                source_world.z if "Z" in row["axes"] else 0.0,
                            ))
                            contribution = target_location_world_inverse @ (
                                (alignment_q @ filtered) * location_scale
                            )
                            location += contribution
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
