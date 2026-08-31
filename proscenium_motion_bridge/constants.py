ADDON_VERSION = (0, 4, 0)

TOOL_ID = "proscenium_motion_bridge"
TOOL_NAME = "Proscenium Motion Bridge"
OWNER_KEY = "bam_owner"
OWNER_VALUE = TOOL_ID
OWNER_VALUES = frozenset({TOOL_ID, "ba_motion_bridge"})
TEMPORARY_KEY = "bam_temporary"

CANONICAL_MODEL_KEY = "proscenium_canonical_model"
CANONICAL_MODEL_ID = "kimodo-soma-rp"

CANONICAL_REQUIRED_BONES = frozenset(
    {
        "Hips",
        "Spine1",
        "Spine2",
        "Chest",
        "Neck1",
        "Neck2",
        "Head",
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "RightShoulder",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "LeftLeg",
        "LeftShin",
        "LeftFoot",
        "LeftToeBase",
        "RightLeg",
        "RightShin",
        "RightFoot",
        "RightToeBase",
    }
)

ROOT_MOTION_ITEMS = (
    (
        "FULL",
        "完整位移",
        "把 Hips 的水平移动和上下起伏分别传给 MMD 中心/グルーブ骨",
    ),
    (
        "IN_PLACE",
        "原地动作",
        "只传旋转，不传角色整体位移",
    ),
)
