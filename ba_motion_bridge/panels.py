import bpy

from .operators import blendcap_ready, mmd2blendcap_ready


def draw_bridge(layout, context, compact: bool = False) -> None:
    settings = context.scene.ba_motion_bridge_settings
    layout.prop(settings, "source_rig")
    layout.prop(settings, "target_rig")
    layout.prop(settings, "root_motion_mode")

    if not compact:
        options = layout.column(align=True)
        options.prop(settings, "auto_scale")
        options.prop(settings, "world_location")

    dependencies = layout.row(align=True)
    dependencies.label(
        text="BlendCap",
        icon="CHECKMARK" if blendcap_ready() else "ERROR",
    )
    dependencies.label(
        text="MMD2BlendCap",
        icon="CHECKMARK" if mmd2blendcap_ready() else "ERROR",
    )

    row = layout.row(align=True)
    row.operator("ba_motion_bridge.auto_map", text="自动映射", icon="BONE_DATA")
    row.operator("ba_motion_bridge.validate_mapping", text="检查", icon="CHECKMARK")

    if settings.expected_count:
        icon = "CHECKMARK" if settings.mapping_valid else "ERROR"
        layout.label(
            text=f"主链：{settings.matched_count}/{settings.expected_count}",
            icon=icon,
        )
        if settings.auto_scale:
            layout.label(text=f"主链位移比例：{settings.scale_ratio:.4f}", icon="FULLSCREEN_ENTER")
    layout.label(text=settings.status_message, icon="INFO")
    if settings.critical_missing:
        warning = layout.row()
        warning.alert = True
        warning.label(text=f"关键缺失：{settings.critical_missing}", icon="ERROR")
    elif settings.unmatched and not compact:
        layout.label(text=f"可选未匹配：{settings.unmatched}", icon="QUESTION")
    if settings.warnings and not compact:
        layout.label(text=settings.warnings, icon="INFO")

    retarget = layout.column()
    retarget.scale_y = 1.35
    retarget.operator("ba_motion_bridge.retarget", icon="ACTION")
    layout.label(text="新建独立 Action；不写 preset、不覆盖原动作", icon="LOCKED")

    if settings.previous_blendcap_mapping_json and not compact:
        layout.operator(
            "ba_motion_bridge.restore_previous_mapping",
            icon="LOOP_BACK",
        )
    if settings.constraint_snapshot_json:
        layout.operator("ba_motion_bridge.restore_constraints", icon="CONSTRAINT_BONE")
    if settings.previous_target_state_available:
        layout.operator(
            "ba_motion_bridge.restore_previous_target_animation",
            icon="LOOP_BACK",
        )
    if not compact:
        layout.operator("ba_motion_bridge.cleanup_temporary", icon="TRASH")


class BAM_PT_main(bpy.types.Panel):
    bl_idname = "BAM_PT_main"
    bl_label = "Motion Bridge 详细"
    bl_category = "BA 动画"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_bridge(self.layout, context, compact=False)


CLASSES = (BAM_PT_main,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
