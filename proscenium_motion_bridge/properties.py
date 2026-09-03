import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from .constants import ROOT_MOTION_ITEMS


def _armature_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _invalidate_mapping(self, _context):
    self.mapping_signature = ""
    self.mapping_valid = False
    self.status_level = "INFO"
    self.status_code = "MAPPING_STALE"
    self.next_action = "点击“自动识别并检查”"
    self.status_message = "骨架、位移或动作空间已变化，请重新自动映射"


class BAM_PG_settings(bpy.types.PropertyGroup):
    source_rig: PointerProperty(
        name="Proscenium 源骨架",
        description="Proscenium kimodo-soma-rp 官方骨架；可包含活动 Action 或 NLA 动作",
        type=bpy.types.Object,
        poll=_armature_poll,
        update=_invalidate_mapping,
    )
    target_rig: PointerProperty(
        name="角色目标骨架",
        description="要接收动作的 MMD FK 骨架或 Auto-Rig Pro 控制器骨架",
        type=bpy.types.Object,
        poll=_armature_poll,
        update=_invalidate_mapping,
    )
    root_motion_mode: EnumProperty(
        name="整体位移",
        items=ROOT_MOTION_ITEMS,
        default="FULL",
        update=_invalidate_mapping,
        options={"HIDDEN"},
    )
    root_motion_policy: EnumProperty(
        name="根运动",
        description="自动跟随 Proscenium 的 In-place 状态，或明确强制输出完整位移/原地动作",
        items=(
            ("AUTO", "自动跟随 Proscenium", "根据 Proscenium 的 In-place 开关自动决定"),
            ("FULL", "完整位移", "传递角色整体移动；可设置世界空间和体型比例"),
            ("IN_PLACE", "原地动作", "不传递 Hips 的水平整体位移"),
        ),
        default="AUTO",
        update=_invalidate_mapping,
    )
    motion_space: EnumProperty(
        name="动作空间",
        description="决定动作方向是跟随角色当前布置，还是保持 Proscenium 官方骨架的世界方向",
        items=(
            (
                "TARGET_PLACEMENT",
                "跟随目标初始布置",
                "保留角色当前位置与水平朝向；前进、侧移和肢体动作都相对角色自身方向",
            ),
            (
                "SOURCE_WORLD",
                "保持官方世界方向",
                "兼容 0.7 及更早行为；动作继续沿官方骨架的世界坐标方向",
            ),
        ),
        default="TARGET_PLACEMENT",
        update=_invalidate_mapping,
    )
    auto_scale: BoolProperty(
        name="主链体型比例",
        description="用髋-头、髋-足和肩-腕等人体主链 landmark 的中位数缩放位移，忽略发饰和武器骨",
        default=True,
    )
    world_location: BoolProperty(
        name="世界空间位移",
        description="在世界空间读取官方骨架的 Hips 位移，兼容对象层变换",
        default=True,
    )
    use_end_effector_guard: BoolProperty(
        name="肢端防穿模",
        description="当不同体型使双手在近距离动作中额外收拢时，自动用双骨 IK 稳定腕点；按当前骨架比例计算，不使用特定角色偏移",
        default=True,
    )
    accept_preview_on_run: BoolProperty(
        name="一键时接受当前预览",
        description="Proscenium 正在预览时，先执行 Accept，再立即重定向到角色；Accept 成功后即使重定向失败，生成结果也会保留",
        default=True,
    )
    follow_proscenium_inplace: BoolProperty(
        name="跟随 Proscenium 原地模式",
        description="一键输出时根据 Proscenium Preview 的 In-place 开关自动选择完整位移或原地动作",
        default=True,
        options={"HIDDEN"},
    )
    use_start_buffer: BoolProperty(
        name="启用起始缓冲",
        description="在正式动作首帧之前生成静置与平滑过渡，并顺序求值该区间供裙发物理预热；正式动作时间码保持不变",
        default=True,
    )
    initial_pose_source: EnumProperty(
        name="初始姿态来源",
        description="选择起始缓冲使用的角色姿态",
        items=(
            ("CURRENT", "当前角色姿态", "使用点击重定向时目标骨架当前帧的姿态"),
            ("REST", "目标 Rest Pose", "使用目标骨架的静置姿态（Matrix Basis 归零）"),
            ("ACTION_FRAME", "指定 Action 帧", "从指定目标 Action 的某一帧读取初始姿态"),
        ),
        default="CURRENT",
    )
    initial_pose_action: PointerProperty(
        name="初始姿态 Action",
        description="从这个 Action 的指定帧读取主体控制骨姿态；不会修改该 Action",
        type=bpy.types.Action,
    )
    initial_pose_frame: IntProperty(
        name="姿态帧",
        description="读取所选初始姿态 Action 的帧号",
        default=1,
        min=-1048574,
        max=1048574,
    )
    settle_frames: IntProperty(
        name="静置帧",
        description="保持初始姿态、让裙发刚体稳定的帧数；设为 0 可跳过",
        default=10,
        min=0,
        max=1000,
    )
    transition_frames: IntProperty(
        name="过渡帧",
        description="从初始姿态逐帧平滑进入正式动作首帧的帧数；设为 0 可跳过",
        default=20,
        min=0,
        max=1000,
    )
    evaluate_physics_preroll: BoolProperty(
        name="顺序预热物理",
        description="重定向完成后从缓冲起点逐帧求值到正式首帧；不会擅自清除已经烘焙的物理缓存",
        default=True,
    )
    mapping_valid: BoolProperty(default=False, options={"HIDDEN"})
    status_level: EnumProperty(
        items=(
            ("INFO", "Info", ""),
            ("READY", "Ready", ""),
            ("WARNING", "Warning", ""),
            ("ERROR", "Error", ""),
            ("BUSY", "Busy", ""),
        ),
        default="INFO",
        options={"HIDDEN"},
    )
    status_code: StringProperty(default="NOT_READY", options={"HIDDEN"})
    next_action: StringProperty(default="先生成官方骨架动作，再选择角色目标", options={"HIDDEN"})
    source_origin: StringProperty(default="", options={"HIDDEN"})
    target_origin: StringProperty(default="", options={"HIDDEN"})
    source_candidates: StringProperty(default="", options={"HIDDEN"})
    target_candidates: StringProperty(default="", options={"HIDDEN"})
    matched_count: IntProperty(default=0, min=0, options={"HIDDEN"})
    expected_count: IntProperty(default=0, min=0, options={"HIDDEN"})
    critical_missing: StringProperty(default="", options={"HIDDEN"})
    unmatched: StringProperty(default="", options={"HIDDEN"})
    warnings: StringProperty(default="", options={"HIDDEN"})
    scale_ratio: FloatProperty(default=1.0, min=0.0001, options={"HIDDEN"})
    status_message: StringProperty(default="尚未映射", options={"HIDDEN"})
    target_profile: StringProperty(default="", options={"HIDDEN"})
    mapping_json: StringProperty(default="", options={"HIDDEN"})
    mapping_signature: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_json: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_target: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_target_rig: PointerProperty(
        type=bpy.types.Object,
        poll=_armature_poll,
        options={"HIDDEN"},
    )
    last_output_action: StringProperty(default="", options={"HIDDEN"})
    progress_active: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    progress_value: FloatProperty(
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    progress_message: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    previous_target_state_available: BoolProperty(default=False, options={"HIDDEN"})
    previous_target_rig: PointerProperty(
        type=bpy.types.Object,
        poll=_armature_poll,
        options={"HIDDEN"},
    )
    previous_target_action: PointerProperty(type=bpy.types.Action, options={"HIDDEN"})
    previous_target_action_name: StringProperty(default="", options={"HIDDEN"})
    previous_target_action_slot: StringProperty(default="", options={"HIDDEN"})
    previous_target_use_nla: BoolProperty(default=False, options={"HIDDEN"})
    previous_target_action_fake_user: BoolProperty(default=False, options={"HIDDEN"})
    target_switch_snapshot_json: StringProperty(default="", options={"HIDDEN"})
    target_switch_snapshot_target: StringProperty(default="", options={"HIDDEN"})
    physics_cache_snapshot_json: StringProperty(default="", options={"HIDDEN"})
    timeline_snapshot_json: StringProperty(default="", options={"HIDDEN"})


CLASSES = (BAM_PG_settings,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ba_motion_bridge_settings = PointerProperty(type=BAM_PG_settings)


def unregister():
    if hasattr(bpy.types.Scene, "ba_motion_bridge_settings"):
        del bpy.types.Scene.ba_motion_bridge_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
