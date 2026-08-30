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
    self.status_message = "骨架或位移模式已变化，请重新自动映射"


class BAM_PG_settings(bpy.types.PropertyGroup):
    source_rig: PointerProperty(
        name="官方动作骨架",
        description="Proscenium kimodo-soma-rp 官方骨架；可包含活动 Action 或 NLA 动作",
        type=bpy.types.Object,
        poll=_armature_poll,
        update=_invalidate_mapping,
    )
    target_rig: PointerProperty(
        name="MMD 目标骨架",
        description="要接收动作的 MMD Tools 骨架",
        type=bpy.types.Object,
        poll=_armature_poll,
        update=_invalidate_mapping,
    )
    root_motion_mode: EnumProperty(
        name="整体位移",
        items=ROOT_MOTION_ITEMS,
        default="FULL",
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
    accept_preview_on_run: BoolProperty(
        name="一键时接受当前预览",
        description="Proscenium 正在预览时，先执行 Accept，再立即重定向到 MMD；Accept 成功后即使重定向失败，生成结果也会保留",
        default=True,
    )
    follow_proscenium_inplace: BoolProperty(
        name="跟随 Proscenium 原地模式",
        description="一键输出时根据 Proscenium Preview 的 In-place 开关自动选择完整位移或原地动作",
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
    next_action: StringProperty(default="先生成官方骨架动作，再选择 MMD 目标", options={"HIDDEN"})
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
    mapping_json: StringProperty(default="", options={"HIDDEN"})
    mapping_signature: StringProperty(default="", options={"HIDDEN"})
    bridge_owns_current_table: BoolProperty(default=False, options={"HIDDEN"})
    previous_blendcap_mapping_json: StringProperty(default="", options={"HIDDEN"})
    previous_blendcap_state_json: StringProperty(default="", options={"HIDDEN"})
    previous_blendcap_source: StringProperty(default="", options={"HIDDEN"})
    previous_blendcap_target: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_json: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_target: StringProperty(default="", options={"HIDDEN"})
    constraint_snapshot_target_rig: PointerProperty(
        type=bpy.types.Object,
        poll=_armature_poll,
        options={"HIDDEN"},
    )
    last_output_action: StringProperty(default="", options={"HIDDEN"})
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
