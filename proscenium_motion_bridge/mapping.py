from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

from .constants import CANONICAL_REQUIRED_BONES


_DUPLICATE_SUFFIX = re.compile(r"^(.*?)[._](\d{3,})$")


@dataclass(frozen=True)
class BoneRecord:
    name: str
    parent: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class MappingPair:
    source: str
    target: str
    channels: str = "ROT"
    axes: str = "XYZ"
    influence: float = 1.0
    role: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MappingResult:
    pairs: tuple[MappingPair, ...]
    missing: tuple[str, ...]
    critical_missing: tuple[str, ...]
    warnings: tuple[str, ...]
    expected_count: int
    target_profile: str = "MMD"

    @property
    def matched_count(self) -> int:
        return len(self.pairs)


def normalize(name: str | None) -> str:
    value = unicodedata.normalize("NFKC", name or "").strip().lower()
    match = _DUPLICATE_SUFFIX.match(value)
    return match.group(1) if match else value


def is_official_canonical_bones(names) -> bool:
    return CANONICAL_REQUIRED_BONES.issubset(set(names))


def _mmd_aliases(holder) -> list[str]:
    aliases: list[str] = []
    mmd_bone = getattr(holder, "mmd_bone", None)
    if mmd_bone is None:
        return aliases
    for attr in ("name_j", "name_e"):
        value = getattr(mmd_bone, attr, "")
        if isinstance(value, str) and value.strip():
            aliases.append(value.strip())
    return aliases


def records_from_rig(rig) -> tuple[BoneRecord, ...]:
    """Read names, hierarchy, and optional MMD Japanese/English aliases.

    This intentionally uses only public RNA and duck typing, so the pure
    mapping module remains importable in ordinary Python tests.
    """
    records: list[BoneRecord] = []
    pose_bones = getattr(getattr(rig, "pose", None), "bones", None)
    for bone in rig.data.bones:
        aliases = [bone.name]
        aliases.extend(_mmd_aliases(bone))
        pose_bone = pose_bones.get(bone.name) if pose_bones is not None else None
        if pose_bone is not None:
            aliases.extend(_mmd_aliases(pose_bone))
        unique = tuple(dict.fromkeys(alias for alias in aliases if alias))
        records.append(
            BoneRecord(
                name=bone.name,
                parent=bone.parent.name if bone.parent else None,
                aliases=unique,
            )
        )
    return tuple(records)


def _lookup(records: tuple[BoneRecord, ...]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in records:
        for alias in record.aliases:
            result.setdefault(normalize(alias), []).append(record.name)
    return result


def _target_variants(stem: str, side: str | None):
    stem = normalize(stem)
    if side is None:
        yield stem
        return
    side = side.upper()
    short = side.lower()
    word = "left" if side == "L" else "right"
    jp = "左" if side == "L" else "右"
    yield f"{jp}{stem}"
    yield f"{word}{stem}"
    yield f"{word} {stem}"
    for sep in (".", "_", "-", " "):
        yield f"{stem}{sep}{short}"
    yield f"{stem}{short}"
    yield f"{stem}{word}"


def _candidate_score(name: str) -> tuple[int, int, str]:
    key = normalize(name)
    penalties = 0
    for token in ("shadow", "_shadow_", "ik", "捩", "twist", "先", "dummy"):
        if token in key:
            penalties += 10
    if _DUPLICATE_SUFFIX.match(unicodedata.normalize("NFKC", name).lower()):
        penalties += 2
    return penalties, len(name), name


def _find_target(
    lookup: dict[str, list[str]],
    stems: tuple[str, ...],
    side: str | None = None,
) -> str | None:
    for stem in stems:
        for variant in _target_variants(stem, side):
            candidates = lookup.get(normalize(variant), ())
            if candidates:
                return min(candidates, key=_candidate_score)
    return None


def _is_descendant(name: str, ancestor: str, parents: dict[str, str | None]) -> bool:
    current: str | None = name
    seen: set[str] = set()
    while current is not None and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def _depth(name: str, parents: dict[str, str | None]) -> int:
    result = 0
    current = parents.get(name)
    seen: set[str] = set()
    while current is not None and current not in seen:
        result += 1
        seen.add(current)
        current = parents.get(current)
    return result


_HIPS_TARGETS = ("腰", "Waist", "グルーブ", "Groove", "センター", "Center")
_ROOT_XY_TARGETS = (
    "センター",
    "Center",
    "全ての親",
    "ParentNode",
    "グルーブ",
    "Groove",
    "腰",
    "Waist",
)
_ROOT_Z_TARGETS = (
    "グルーブ",
    "Groove",
    "センター",
    "Center",
    "腰",
    "Waist",
    "全ての親",
    "ParentNode",
)

_ROLE_LABELS = {
    "shoulder": "肩",
    "upper_arm": "上臂",
    "forearm": "前臂",
    "hand": "手腕",
    "thigh": "大腿",
    "shin": "小腿",
    "foot": "脚踝",
    "toe": "脚尖",
}


def _resolve_hips_target(
    lookup: dict[str, list[str]],
    parents: dict[str, str | None],
    torso_target: str | None,
    left_thigh: str | None,
    right_thigh: str | None,
) -> str | None:
    candidates: list[str] = []
    for stem in _HIPS_TARGETS:
        candidate = _find_target(lookup, (stem,))
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    def eligible(name: str) -> bool:
        landmarks = [item for item in (torso_target, left_thigh, right_thigh) if item]
        return bool(landmarks) and all(_is_descendant(item, name, parents) for item in landmarks)

    valid = [name for name in candidates if eligible(name)]
    if valid:
        return max(valid, key=lambda name: _depth(name, parents))
    return candidates[0] if candidates else None


def _canonical_source_roles(source_names: set[str]) -> dict[str, str]:
    if not is_official_canonical_bones(source_names):
        return {}
    return {
        "hips": "Hips",
        "spine_low": "Spine1",
        "spine_mid": "Spine2",
        "chest": "Chest",
        # Neck2's world-space delta includes Neck1, which safely compresses
        # the canonical two-neck chain into the usual single MMD neck bone.
        "neck": "Neck2",
        "head": "Head",
        "left_shoulder": "LeftShoulder",
        "left_upper_arm": "LeftArm",
        "left_forearm": "LeftForeArm",
        "left_hand": "LeftHand",
        "right_shoulder": "RightShoulder",
        "right_upper_arm": "RightArm",
        "right_forearm": "RightForeArm",
        "right_hand": "RightHand",
        # SOMA differs from BlendCap BVH here: LeftLeg is the thigh and
        # LeftShin is the lower leg. Never feed this profile through the
        # legacy LeftUpLeg/LeftLeg mapper.
        "left_thigh": "LeftLeg",
        "left_shin": "LeftShin",
        "left_foot": "LeftFoot",
        "left_toe": "LeftToeBase",
        "right_thigh": "RightLeg",
        "right_shin": "RightShin",
        "right_foot": "RightFoot",
        "right_toe": "RightToeBase",
    }


_ARP_SIGNATURE = frozenset(
    {
        "c_root.x",
        "c_spine_01.x",
        "c_spine_03.x",
        "c_arm_fk.l",
        "c_arm_fk.r",
        "c_thigh_fk.l",
        "c_thigh_fk.r",
    }
)


def is_auto_rig_pro_bones(names) -> bool:
    """Return True for an Auto-Rig Pro controller rig.

    MMD characters are often converted to ARP while retaining their MMD mesh
    and naming history.  The deform/mechanism bones on such rigs must not be
    treated as ordinary MMD FK bones: they are constraint outputs.  BlendCap's
    own ARP preset targets the user-facing ``c_*_fk`` controls instead.
    """
    return _ARP_SIGNATURE.issubset(set(names))


def _build_arp_mapping(
    source: dict[str, str],
    target_names: set[str],
    root_motion_mode: str,
) -> MappingResult:
    expected_count = 22 + (2 if root_motion_mode == "FULL" else 0)
    warnings = [
        "检测到 Auto-Rig Pro 控制器；已映射到 c_* FK 控制链并由 BlendCap 切换为 FK，避免写入受约束的内部变形骨"
    ]
    missing: list[str] = []
    critical_missing: list[str] = []
    pairs: list[MappingPair] = []

    def add(
        role: str,
        source_role: str,
        target_name: str,
        *,
        channels: str = "ROT",
        axes: str = "XYZ",
        critical: bool = True,
        label: str | None = None,
    ) -> None:
        if target_name not in target_names:
            readable = label or role
            missing.append(readable)
            if critical:
                critical_missing.append(readable)
            return
        pairs.append(
            MappingPair(
                source=source[source_role],
                target=target_name,
                channels=channels,
                axes=axes,
                role=role,
            )
        )

    # This profile follows BlendCap 1.0.5's verified Auto-Rig Pro preset.
    # Source Spine1/Spine2/Chest are the three SOMA torso segments.
    add("spine_0", "spine_low", "c_spine_01.x", label="ARP 脊柱 1")
    add("spine_1", "spine_mid", "c_spine_02.x", label="ARP 脊柱 2")
    add("spine_2", "chest", "c_spine_03.x", label="ARP 胸部")
    add("neck", "neck", "c_neck.x", label="ARP 颈部")
    add("head", "head", "c_head.x", label="ARP 头部")
    add("hips_rotation", "hips", "c_root.x", label="ARP 骨盆旋转")

    limb_targets = {
        "left_shoulder": "c_shoulder.l",
        "left_upper_arm": "c_arm_fk.l",
        "left_forearm": "c_forearm_fk.l",
        "left_hand": "c_hand_fk.l",
        "left_thigh": "c_thigh_fk.l",
        "left_shin": "c_leg_fk.l",
        "left_foot": "c_foot_fk.l",
        "left_toe": "c_toes_fk.l",
        "right_shoulder": "c_shoulder.r",
        "right_upper_arm": "c_arm_fk.r",
        "right_forearm": "c_forearm_fk.r",
        "right_hand": "c_hand_fk.r",
        "right_thigh": "c_thigh_fk.r",
        "right_shin": "c_leg_fk.r",
        "right_foot": "c_foot_fk.r",
        "right_toe": "c_toes_fk.r",
    }
    for role, target_name in limb_targets.items():
        optional = role.endswith("_shoulder") or role.endswith("_toe")
        add(role, role, target_name, critical=not optional, label=f"ARP {role}")

    if root_motion_mode == "FULL":
        add(
            "root_xy",
            "hips",
            "c_pos",
            channels="LOC",
            axes="XY",
            label="ARP 水平位移控制",
        )
        add(
            "root_z",
            "hips",
            "c_root_master.x",
            channels="LOC",
            axes="Z",
            label="ARP 垂直位移控制",
        )

    return MappingResult(
        pairs=tuple(pairs),
        missing=tuple(missing),
        critical_missing=tuple(critical_missing),
        warnings=tuple(warnings),
        expected_count=expected_count,
        target_profile="AUTO_RIG_PRO",
    )


def build_mapping(source_rig, target_rig, root_motion_mode: str = "FULL") -> MappingResult:
    source_names = {bone.name for bone in source_rig.data.bones}
    source = _canonical_source_roles(source_names)
    warnings: list[str] = []
    missing: list[str] = []
    critical_missing: list[str] = []
    pairs: list[MappingPair] = []

    expected_count = 22 + (2 if root_motion_mode == "FULL" else 0)
    if not source:
        return MappingResult(
            pairs=(),
            missing=("Proscenium kimodo-soma-rp 官方骨架",),
            critical_missing=("官方骨架签名不匹配",),
            warnings=(),
            expected_count=expected_count,
        )

    target_records = records_from_rig(target_rig)
    target_names = {record.name for record in target_records}
    if is_auto_rig_pro_bones(target_names):
        return _build_arp_mapping(source, target_names, root_motion_mode)
    lookup = _lookup(target_records)
    parents = {record.name: record.parent for record in target_records}

    def target(stems: tuple[str, ...], side: str | None = None) -> str | None:
        return _find_target(lookup, stems, side)

    def add(
        role: str,
        source_name: str,
        target_name: str | None,
        *,
        channels: str = "ROT",
        axes: str = "XYZ",
        critical: bool = False,
        label: str | None = None,
    ) -> None:
        readable = label or role
        if target_name is None:
            missing.append(readable)
            if critical:
                critical_missing.append(readable)
            return
        pairs.append(
            MappingPair(
                source=source_name,
                target=target_name,
                channels=channels,
                axes=axes,
                role=role,
            )
        )

    raw_spine_slots = [
        ("lower", target(("下半身", "LowerBody", "Spine"))),
        ("upper", target(("上半身", "UpperBody", "Spine1"))),
        ("upper2", target(("上半身2", "UpperBody2", "Spine2"))),
        ("upper3", target(("上半身3", "UpperBody3", "Spine3"))),
    ]
    spine_slots = []
    seen_spine_targets = set()
    for slot_role, slot_target in raw_spine_slots:
        if slot_target and slot_target not in seen_spine_targets:
            seen_spine_targets.add(slot_target)
            spine_slots.append((slot_role, slot_target))
    source_spine = [source["spine_low"], source["spine_mid"], source["chest"]]
    if not spine_slots:
        missing.append("躯干（下半身/上半身）")
        critical_missing.append("躯干（下半身/上半身）")
    else:
        if len(spine_slots) == 1:
            only_role = spine_slots[0][0]
            chosen_sources = [{
                "lower": source["spine_low"],
                "upper": source["spine_mid"],
                "upper2": source["chest"],
                "upper3": source["chest"],
            }[only_role]]
            warnings.append("目标只有一段躯干骨；已按其下/上半身语义压缩官方躯干链")
        elif len(spine_slots) == 2:
            chosen_sources = [
                source["spine_low"] if spine_slots[0][0] == "lower" else source["spine_mid"],
                source["chest"],
            ]
        else:
            chosen_sources = source_spine
        for index, (source_name, (_slot_role, target_name)) in enumerate(zip(chosen_sources, spine_slots)):
            pairs.append(
                MappingPair(
                    source=source_name,
                    target=target_name,
                    role=f"spine_{index}",
                )
            )
        if len(spine_slots) > len(source_spine):
            warnings.append("目标有额外上半身骨；保持其自然父级继承，不重复叠加旋转")

    limb_targets: dict[str, str | None] = {}
    limb_specs = (
        ("shoulder", ("肩", "Shoulder", "Clavicle"), False),
        ("upper_arm", ("腕", "Arm", "UpperArm"), True),
        ("forearm", ("ひじ", "肘", "Elbow", "ForeArm", "Forearm", "LowerArm"), True),
        ("hand", ("手首", "Wrist", "Hand"), True),
        ("thigh", ("足", "腿", "大腿", "Leg", "UpLeg", "Thigh", "Femur"), True),
        ("shin", ("ひざ", "膝", "Knee", "Shin", "LowerLeg"), True),
        ("foot", ("足首", "足関節", "Ankle", "Foot"), True),
        ("toe", ("つま先", "爪先", "Toe", "ToeBase"), False),
    )
    for side, word in (("L", "left"), ("R", "right")):
        for role, stems, required in limb_specs:
            found = target(stems, side)
            limb_targets[f"{word}_{role}"] = found
            add(
                f"{word}_{role}",
                source[f"{word}_{role}"],
                found,
                critical=required,
                label=f"{'左' if side == 'L' else '右'}{_ROLE_LABELS[role]}",
            )

    neck = target(("首", "Neck"))
    head = target(("頭", "Head"))
    add("neck", source["neck"], neck, critical=True, label="首")
    add("head", source["head"], head, critical=True, label="头")

    torso_landmark = spine_slots[0][1] if spine_slots else None
    hips_target = _resolve_hips_target(
        lookup,
        parents,
        torso_landmark,
        limb_targets.get("left_thigh"),
        limb_targets.get("right_thigh"),
    )
    add("hips_rotation", source["hips"], hips_target, critical=True, label="骨盆旋转")

    if root_motion_mode == "FULL":
        add(
            "root_xy",
            source["hips"],
            target(_ROOT_XY_TARGETS),
            channels="LOC",
            axes="XY",
            critical=True,
            label="中心水平位移",
        )
        add(
            "root_z",
            source["hips"],
            target(_ROOT_Z_TARGETS),
            channels="LOC",
            axes="Z",
            critical=True,
            label="中心垂直位移",
        )

    # Stable order: target parent chains first, then limbs/head/root. BlendCap
    # independently topologically sorts targets during bake, but a stable UI
    # table makes validation and regression reports deterministic.
    unique_keys: set[tuple[str, str, str, str]] = set()
    unique_pairs: list[MappingPair] = []
    for pair in pairs:
        key = (pair.source, pair.target, pair.channels, pair.axes)
        if key in unique_keys:
            continue
        unique_keys.add(key)
        unique_pairs.append(pair)

    rotation_owner: dict[str, str] = {}
    location_axes: dict[str, set[str]] = {}
    for pair in unique_pairs:
        if pair.channels in {"ROT", "LOC_ROT"}:
            previous = rotation_owner.get(pair.target)
            if previous is not None:
                critical_missing.append(
                    f"目标骨 {pair.target} 被多个旋转角色重复驱动（{previous}/{pair.role}）"
                )
            else:
                rotation_owner[pair.target] = pair.role
        if pair.channels in {"LOC", "LOC_ROT"}:
            axes = {axis for axis in pair.axes.upper() if axis in "XYZ"}
            overlap = location_axes.setdefault(pair.target, set()).intersection(axes)
            if overlap:
                critical_missing.append(
                    f"目标骨 {pair.target} 的位移轴重复（{''.join(sorted(overlap))}）"
                )
            location_axes[pair.target].update(axes)

    return MappingResult(
        pairs=tuple(unique_pairs),
        missing=tuple(dict.fromkeys(missing)),
        critical_missing=tuple(dict.fromkeys(critical_missing)),
        warnings=tuple(dict.fromkeys(warnings)),
        expected_count=expected_count,
        target_profile="MMD",
    )
