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
    guarded_frames: int = 0
    max_guard_correction: float = 0.0


@dataclass(frozen=True)
class PlacementContext:
    motion_space: str
    alignment_rotation: Quaternion
    placement_rotation: Quaternion
    baseline_basis: dict[str, Matrix]
    baseline_locations: dict[str, Vector]
    placement_bone: str
    alignment_yaw_degrees: float


@dataclass(frozen=True)
class _ArmGuardChain:
    source_upper: str
    source_forearm: str
    source_hand: str
    target_upper: str
    target_forearm: str
    target_hand: str
    scale_ratio: float
    target_extent_world: float


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


def _rest_bone_world_length(rig, bone_name: str) -> float:
    bone = rig.data.bones[bone_name]
    head = rig.matrix_world @ bone.head_local
    tail = rig.matrix_world @ bone.tail_local
    return (tail - head).length


def _rest_head_world(rig, bone_name: str) -> Vector:
    return rig.matrix_world @ rig.data.bones[bone_name].head_local


def _is_descendant_bone(child, ancestor) -> bool:
    current = child.parent
    while current is not None:
        if current == ancestor:
            return True
        current = current.parent
    return False


def _rest_chain_world_length(rig, upper_name: str, forearm_name: str, hand_name: str) -> float:
    shoulder = _rest_head_world(rig, upper_name)
    elbow = _rest_head_world(rig, forearm_name)
    wrist = _rest_head_world(rig, hand_name)
    return (elbow - shoulder).length + (wrist - elbow).length


def _build_arm_guard_context(source, target, result: MappingResult):
    """Describe two hierarchical FK arms without assuming bone names.

    The source and target roles come from the add-on's own mapping. Descendant
    checks allow ordinary arm/wrist twist helpers while keeping the solver away
    from controls that do not form an actual FK chain.
    """
    by_role = {pair.role: pair for pair in result.pairs}
    chains: list[_ArmGuardChain] = []
    for side in ("left", "right"):
        roles = [f"{side}_upper_arm", f"{side}_forearm", f"{side}_hand"]
        if any(role not in by_role for role in roles):
            return None
        upper_pair, forearm_pair, hand_pair = (by_role[role] for role in roles)
        source_names = (upper_pair.source, forearm_pair.source, hand_pair.source)
        target_names = (upper_pair.target, forearm_pair.target, hand_pair.target)
        if any(name not in source.pose.bones for name in source_names):
            return None
        if any(name not in target.pose.bones for name in target_names):
            return None
        target_upper = target.data.bones[target_names[0]]
        target_forearm = target.data.bones[target_names[1]]
        target_hand = target.data.bones[target_names[2]]
        if not _is_descendant_bone(target_forearm, target_upper):
            return None
        if not _is_descendant_bone(target_hand, target_forearm):
            return None

        source_chain = _rest_chain_world_length(source, *source_names)
        target_chain = _rest_chain_world_length(target, *target_names)
        if source_chain <= 1e-8 or target_chain <= 1e-8:
            return None
        hand_length = _rest_bone_world_length(target, target_names[2])
        chains.append(
            _ArmGuardChain(
                source_upper=source_names[0],
                source_forearm=source_names[1],
                source_hand=source_names[2],
                target_upper=target_names[0],
                target_forearm=target_names[1],
                target_hand=target_names[2],
                scale_ratio=target_chain / source_chain,
                target_extent_world=max(hand_length, target_chain * 0.12),
            )
        )

    source_width = (
        _rest_head_world(source, chains[0].source_upper)
        - _rest_head_world(source, chains[1].source_upper)
    ).length
    target_width = (
        _rest_head_world(target, chains[0].target_upper)
        - _rest_head_world(target, chains[1].target_upper)
    ).length
    ratios = [chain.scale_ratio for chain in chains]
    if source_width > 1e-8 and target_width > 1e-8:
        ratios.append(target_width / source_width)
    # Average shoulder and arm ratios. This is deliberately model-derived:
    # no character-specific offsets or dimensions are embedded in the guard.
    spatial_scale = sum(ratios) / len(ratios)
    return tuple(chains), spatial_scale


def _set_pose_matrix_rotation(pose_bone, rotation: Quaternion) -> None:
    location, _old_rotation, scale = pose_bone.matrix.decompose()
    pose_bone.matrix = Matrix.LocRotScale(location, rotation, scale)


def _aim_pose_bone(pose_bone, endpoint: Vector) -> bool:
    current = pose_bone.tail - pose_bone.head
    desired = endpoint - pose_bone.head
    if current.length_squared <= 1e-12 or desired.length_squared <= 1e-12:
        return False
    delta = current.rotation_difference(desired)
    _set_pose_matrix_rotation(pose_bone, delta @ pose_bone.matrix.to_quaternion())
    return True


def _solve_two_bone_arm(target, chain: _ArmGuardChain, goal_world: Vector) -> tuple[str, ...]:
    """Move one wrist to a reachable goal while preserving its palm rotation."""
    upper = target.pose.bones[chain.target_upper]
    forearm = target.pose.bones[chain.target_forearm]
    hand = target.pose.bones[chain.target_hand]
    goal = target.matrix_world.inverted() @ goal_world
    snapshots = {
        pose_bone.name: pose_bone.matrix_basis.copy()
        for pose_bone in (upper, forearm, hand)
    }

    def restore() -> tuple[str, ...]:
        for bone_name, matrix_basis in snapshots.items():
            target.pose.bones[bone_name].matrix_basis = matrix_basis
        bpy.context.view_layer.update()
        return ()

    shoulder = upper.head.copy()
    elbow = forearm.head.copy()
    wrist = hand.head.copy()
    upper_length = (elbow - shoulder).length
    forearm_length = (wrist - elbow).length
    direction = goal - shoulder
    distance = direction.length
    if upper_length <= 1e-8 or forearm_length <= 1e-8 or distance <= 1e-8:
        return restore()
    direction.normalize()
    minimum = abs(upper_length - forearm_length) + 1e-6
    maximum = upper_length + forearm_length - 1e-6
    reach = max(minimum, min(maximum, distance))
    reachable_goal = shoulder + direction * reach

    pole = (elbow - shoulder) - direction * (elbow - shoulder).dot(direction)
    if pole.length_squared <= 1e-10:
        pole = (upper.matrix.to_3x3() @ Vector((1.0, 0.0, 0.0)))
        pole -= direction * pole.dot(direction)
    if pole.length_squared <= 1e-10:
        fallback = Vector((0.0, 0.0, 1.0))
        if abs(direction.dot(fallback)) > 0.95:
            fallback = Vector((1.0, 0.0, 0.0))
        pole = fallback - direction * fallback.dot(direction)
    pole.normalize()

    along = (
        upper_length * upper_length
        - forearm_length * forearm_length
        + reach * reach
    ) / (2.0 * reach)
    height_squared = max(0.0, upper_length * upper_length - along * along)
    target_elbow = shoulder + direction * along + pole * math.sqrt(height_squared)
    hand_rotation = hand.matrix.to_quaternion().copy()

    if not _aim_pose_bone(upper, target_elbow):
        return restore()
    bpy.context.view_layer.update()
    if not _aim_pose_bone(forearm, reachable_goal):
        return restore()
    bpy.context.view_layer.update()
    _set_pose_matrix_rotation(hand, hand_rotation)
    bpy.context.view_layer.update()
    initial_error = (wrist - reachable_goal).length
    achieved_error = (hand.head - reachable_goal).length
    if achieved_error >= initial_error - 1e-7:
        return restore()
    return chain.target_upper, chain.target_forearm, chain.target_hand


def _apply_end_effector_guard(
    source,
    target,
    guard_context,
    alignment: Quaternion,
    correction_strength: float = 1.0,
):
    """Correct only extra near-contact convergence introduced by proportions."""
    correction_strength = max(0.0, min(3.0, float(correction_strength)))
    if guard_context is None or correction_strength <= 1e-4:
        return (), 0.0
    chains, spatial_scale = guard_context
    source_shoulders = [
        source.matrix_world @ source.pose.bones[chain.source_upper].head
        for chain in chains
    ]
    target_shoulders = [
        target.matrix_world @ target.pose.bones[chain.target_upper].head
        for chain in chains
    ]
    source_center = (source_shoulders[0] + source_shoulders[1]) * 0.5
    target_center = (target_shoulders[0] + target_shoulders[1]) * 0.5
    source_wrists = [
        source.matrix_world @ source.pose.bones[chain.source_hand].head
        for chain in chains
    ]
    target_wrists = [
        target.matrix_world @ target.pose.bones[chain.target_hand].head
        for chain in chains
    ]
    goals = [
        target_center + alignment @ (wrist - source_center) * spatial_scale
        for wrist in source_wrists
    ]

    current_separation = (target_wrists[0] - target_wrists[1]).length
    goal_separation = (goals[0] - goals[1]).length
    hand_extent = sum(chain.target_extent_world for chain in chains) * 0.5
    if hand_extent <= 1e-8:
        return (), 0.0
    deficit = goal_separation - current_separation
    proximity_limit = hand_extent * 2.25
    if deficit <= hand_extent * 0.01 or current_separation >= proximity_limit:
        return (), 0.0

    convergence = min(1.0, deficit / max(hand_extent * 0.5, 1e-8))
    proximity = min(1.0, max(0.0, (proximity_limit - current_separation) / hand_extent))
    strength = min(convergence, proximity)
    strength = strength * strength * (3.0 - 2.0 * strength)
    if strength <= 1e-4:
        return (), 0.0

    corrected: list[str] = []
    max_correction = 0.0
    applied_strength = min(3.0, strength * correction_strength)
    for chain, current, goal in zip(chains, target_wrists, goals):
        # Values above 1.0 intentionally extrapolate beyond the proportional
        # source wrist goal to provide extra clearance for bulky hands/sleeves.
        blended_goal = current.lerp(goal, applied_strength)
        max_correction = max(max_correction, (blended_goal - current).length)
        corrected.extend(_solve_two_bone_arm(target, chain, blended_goal))
    return tuple(dict.fromkeys(corrected)), max_correction


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
    end_effector_guard: bool = True,
    end_effector_guard_strength: float = 1.0,
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
    arm_guard_context = (
        _build_arm_guard_context(source, target, result)
        if end_effector_guard
        else None
    )

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
    guarded_frames = 0
    max_guard_correction = 0.0

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

            corrected_bones, correction = _apply_end_effector_guard(
                source,
                target,
                arm_guard_context,
                alignment_q,
                end_effector_guard_strength,
            )
            if corrected_bones:
                for bone_name in corrected_bones:
                    pose_bone = target.pose.bones[bone_name]
                    last_quaternion[bone_name] = pose_bone.matrix_basis.to_quaternion().copy()
                    if capture:
                        pose_bone.keyframe_insert(
                            _rotation_property(pose_bone),
                            frame=frame,
                            group=bone_name,
                        )
                if capture:
                    guarded_frames += 1
                    max_guard_correction = max(max_guard_correction, correction)
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
    return BakeResult(
        action,
        frame_start,
        frame_end,
        keyed_channels,
        guarded_frames,
        max_guard_correction,
    )


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
