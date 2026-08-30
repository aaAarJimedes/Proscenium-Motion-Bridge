import bpy

from .operators import (
    _animation_present,
    _is_official_source,
    blendcap_ready,
    mmd2blendcap_ready,
)


def _live_armature(obj) -> bool:
    try:
        return bool(obj and obj.type == "ARMATURE" and bpy.data.objects.get(obj.name) == obj)
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _draw_dependencies(layout) -> bool:
    ready = blendcap_ready()
    if not ready:
        row = layout.row()
        row.alert = True
        row.label(text="缺少必需引擎：BlendCap", icon="ERROR")
    if not mmd2blendcap_ready():
        layout.label(text="传统 BVH 工作流未启用（可选）", icon="INFO")
    return ready


def _draw_status(layout, settings) -> None:
    if settings.expected_count:
        row = layout.row(align=True)
        row.label(
            text=f"主链 {settings.matched_count}/{settings.expected_count}",
            icon="CHECKMARK" if settings.mapping_valid else "ERROR",
        )
        if settings.auto_scale:
            row.label(text=f"比例 {settings.scale_ratio:.4f}×")
    row = layout.row()
    level = getattr(settings, "status_level", "INFO")
    row.alert = level == "ERROR"
    icon = {"READY": "CHECKMARK", "WARNING": "ERROR", "ERROR": "ERROR"}.get(level, "INFO")
    row.label(text=settings.status_message, icon=icon)
    if settings.critical_missing:
        warning = layout.column(align=True)
        warning.alert = True
        warning.label(text="关键骨缺失：", icon="ERROR")
        for item in settings.critical_missing.split("、")[:8]:
            warning.label(text=f"• {item}")
    next_action = getattr(settings, "next_action", "")
    if next_action and level != "READY":
        layout.label(text=f"下一步：{next_action}", icon="FORWARD")


def draw_bridge(layout, context, compact: bool = False, hosted: bool = False) -> None:
    settings = context.scene.ba_motion_bridge_settings
    dependencies_ready = _draw_dependencies(layout)

    source = settings.source_rig
    target = settings.target_rig
    source_ready = _is_official_source(source)
    target_ready = _live_armature(target) and target != source
    motion_ready = source_ready and _animation_present(source)
    proscenium = getattr(context.scene, "proscenium", None)
    generating = bool(proscenium and getattr(proscenium, "is_generating", False))
    previewing = bool(proscenium and getattr(proscenium, "is_previewing", False))

    rigs = layout.box() if hosted else layout.column(align=True)
    rigs.label(text="输出对象", icon="ARMATURE_DATA")
    rigs.prop(settings, "source_rig")
    rigs.prop(settings, "target_rig")

    state = rigs.column(align=True)
    state.label(text="官方骨架已识别" if source_ready else "等待官方骨架", icon="CHECKMARK" if source_ready else "ERROR")
    if generating:
        state.label(text="正在生成：输出已锁定", icon="SORTTIME")
    elif previewing:
        state.label(text="当前预览可由一键按钮接受", icon="TIME")
    else:
        state.label(text="动作已就绪" if motion_ready else "等待生成/接受动作", icon="CHECKMARK" if motion_ready else "INFO")
    state.label(text="MMD 目标已选择" if target_ready else "请选择 MMD 目标", icon="CHECKMARK" if target_ready else "ERROR")

    row = layout.row(align=True)
    row.operator("ba_motion_bridge.prepare_from_proscenium", text="自动识别并检查", icon="VIEWZOOM")
    row.operator("ba_motion_bridge.validate_mapping", text="复查", icon="CHECKMARK")

    options = layout.box() if hosted else layout.column(align=True)
    options.label(text="输出方式", icon="SETTINGS")
    options.prop(settings, "root_motion_mode", expand=True)
    if hosted:
        options.prop(settings, "follow_proscenium_inplace")
        options.prop(settings, "accept_preview_on_run")
    elif not compact:
        options.prop(settings, "auto_scale")
        options.prop(settings, "world_location")
        options.prop(settings, "follow_proscenium_inplace")
        options.prop(settings, "accept_preview_on_run")

    _draw_status(layout, settings)

    run = layout.column()
    run.scale_y = 1.5
    run.enabled = dependencies_ready and not generating and (previewing or motion_ready or source is None)
    run.operator(
        "ba_motion_bridge.accept_and_retarget",
        text="接受并输出到 MMD" if previewing else "一键输出到 MMD",
        icon="ACTION",
    )
    layout.label(text="自动检查 · 独立 Action · 失败回滚", icon="LOCKED")

    if settings.last_output_action:
        output = layout.row(align=True)
        output.label(text=f"上次输出：{settings.last_output_action}", icon="ACTION")
        output.operator("ba_motion_bridge.activate_output", text="激活", icon="RADIOBUT_ON")

    recovery_pending = bool(
        settings.constraint_snapshot_json
        or settings.previous_target_state_available
        or settings.previous_blendcap_mapping_json
    )
    if recovery_pending and hasattr(bpy.ops.ba_motion_bridge, "restore_previous_state"):
        layout.operator("ba_motion_bridge.restore_previous_state", icon="LOOP_BACK")
    else:
        if settings.constraint_snapshot_json:
            layout.operator("ba_motion_bridge.restore_constraints", icon="CONSTRAINT_BONE")
        if settings.previous_target_state_available:
            layout.operator("ba_motion_bridge.restore_previous_target_animation", icon="LOOP_BACK")
    if not compact:
        if settings.unmatched:
            layout.label(text=f"可选未匹配：{settings.unmatched}", icon="QUESTION")
        if settings.warnings:
            layout.label(text=settings.warnings, icon="INFO")
        if settings.previous_blendcap_mapping_json:
            layout.operator("ba_motion_bridge.restore_previous_mapping", icon="LOOP_BACK")
        layout.operator("ba_motion_bridge.cleanup_temporary", icon="TRASH")


class BAM_PT_proscenium_output(bpy.types.Panel):
    bl_idname = "BAM_PT_proscenium_output"
    bl_label = "MMD 输出 · BA Motion Bridge"
    bl_category = "Proscenium"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "proscenium")

    def draw(self, context):
        draw_bridge(self.layout, context, compact=True, hosted=True)


class BAM_PT_main(bpy.types.Panel):
    bl_idname = "BAM_PT_main"
    bl_label = "Motion Bridge 高级与恢复"
    bl_category = "BA 动画"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_bridge(self.layout, context, compact=False, hosted=False)


CLASSES = (BAM_PT_proscenium_output, BAM_PT_main)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
