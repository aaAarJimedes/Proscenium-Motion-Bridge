import bpy

from .operators import _animation_present, _is_official_source, blendcap_ready


def _live_armature(obj) -> bool:
    try:
        return bool(obj and obj.type == "ARMATURE" and bpy.data.objects.get(obj.name) == obj)
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _draw_status(layout, settings) -> None:
    if settings.expected_count:
        row = layout.row(align=True)
        row.label(
            text=f"主链 {settings.matched_count}/{settings.expected_count}",
            icon="CHECKMARK" if settings.mapping_valid else "ERROR",
        )
        profile = {
            "AUTO_RIG_PRO": "Auto-Rig Pro 控制链",
            "MMD": "MMD FK 骨架",
        }.get(settings.target_profile, settings.target_profile)
        if profile:
            row.label(text=profile, icon="ARMATURE_DATA")
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
    if settings.next_action and level != "READY":
        layout.label(text=f"下一步：{settings.next_action}", icon="FORWARD")


class BAM_PT_proscenium_motion_bridge(bpy.types.Panel):
    bl_idname = "BAM_PT_proscenium_motion_bridge"
    bl_label = "Proscenium Motion Bridge"
    bl_category = "Proscenium"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.ba_motion_bridge_settings
        dependencies_ready = blendcap_ready()
        proscenium = getattr(context.scene, "proscenium", None)
        generating = bool(proscenium and getattr(proscenium, "is_generating", False))
        previewing = bool(proscenium and getattr(proscenium, "is_previewing", False))

        if not dependencies_ready:
            dependency = layout.row()
            dependency.alert = True
            dependency.label(text="缺少必需重定向引擎：BlendCap 1.0.5", icon="ERROR")

        rigs = layout.box()
        rigs.label(text="1. 选择骨架", icon="ARMATURE_DATA")
        rigs.prop(settings, "source_rig")
        rigs.prop(settings, "target_rig")
        source_ready = _is_official_source(settings.source_rig)
        target_ready = _live_armature(settings.target_rig) and settings.target_rig != settings.source_rig
        states = rigs.row(align=True)
        states.label(
            text="官方源已识别" if source_ready else "等待官方源",
            icon="CHECKMARK" if source_ready else "INFO",
        )
        states.label(
            text="目标已选择" if target_ready else "等待角色目标",
            icon="CHECKMARK" if target_ready else "INFO",
        )

        options = layout.box()
        options.label(text="2. 输出设置", icon="SETTINGS")
        options.prop(settings, "root_motion_mode", expand=True)
        row = options.row(align=True)
        row.prop(settings, "auto_scale")
        row.prop(settings, "world_location")
        options.prop(settings, "follow_proscenium_inplace")
        options.prop(settings, "accept_preview_on_run")

        buffer = options.box()
        buffer.prop(settings, "use_start_buffer", icon="PREVIEW_RANGE")
        if settings.use_start_buffer:
            buffer.prop(settings, "initial_pose_source")
            if settings.initial_pose_source == "ACTION_FRAME":
                buffer.prop(settings, "initial_pose_action")
                buffer.prop(settings, "initial_pose_frame")
            row = buffer.row(align=True)
            row.prop(settings, "settle_frames")
            row.prop(settings, "transition_frames")
            buffer.prop(settings, "evaluate_physics_preroll")
            buffer.label(text="正式动作首帧不移动；缓冲保存在首帧之前", icon="INFO")

        mapping = layout.box()
        mapping.label(text="3. 识别与检查", icon="VIEWZOOM")
        row = mapping.row(align=True)
        row.operator("ba_motion_bridge.prepare_from_proscenium", text="自动识别并检查", icon="VIEWZOOM")
        row.operator("ba_motion_bridge.validate_mapping", text="复查", icon="CHECKMARK")
        _draw_status(mapping, settings)
        if settings.unmatched:
            mapping.label(text=f"可选未匹配：{settings.unmatched}", icon="QUESTION")
        if settings.warnings:
            mapping.label(text=settings.warnings, icon="INFO")

        output = layout.box()
        output.label(text="4. 输出动作", icon="ACTION")
        if generating:
            output.label(text="Proscenium 正在生成，输出暂时锁定", icon="SORTTIME")
        elif previewing:
            output.label(text="当前预览会先被接受，再输出到角色", icon="TIME")
        elif source_ready and _animation_present(settings.source_rig):
            output.label(text="源动作已就绪", icon="CHECKMARK")
        else:
            output.label(text="等待生成或接受源动作", icon="INFO")
        run = output.column()
        run.scale_y = 1.5
        motion_ready = source_ready and _animation_present(settings.source_rig)
        run.enabled = dependencies_ready and not generating and (previewing or motion_ready or settings.source_rig is None)
        run.operator(
            "ba_motion_bridge.accept_and_retarget",
            text="接受并输出到角色" if previewing else "一键输出到角色",
            icon="ACTION",
        )
        output.label(text="静置方向补偿 · 起始缓冲 · 独立 Action · 失败回滚", icon="LOCKED")

        finish = layout.box()
        finish.label(text="5. 结果与恢复", icon="RECOVER_LAST")
        if settings.last_output_action:
            row = finish.row(align=True)
            row.label(text=f"上次输出：{settings.last_output_action}", icon="ACTION")
            row.operator("ba_motion_bridge.activate_output", text="激活", icon="RADIOBUT_ON")
        recovery_pending = bool(
            settings.constraint_snapshot_json
            or settings.previous_target_state_available
            or settings.previous_blendcap_mapping_json
        )
        if recovery_pending:
            finish.operator("ba_motion_bridge.restore_previous_state", text="恢复角色原状态", icon="LOOP_BACK")
        else:
            finish.label(text="当前没有待恢复事务", icon="CHECKMARK")
        row = finish.row(align=True)
        if settings.previous_blendcap_mapping_json:
            row.operator("ba_motion_bridge.restore_previous_mapping", text="仅恢复映射", icon="LOOP_BACK")
        row.operator("ba_motion_bridge.cleanup_temporary", text="清理临时资源", icon="TRASH")


CLASSES = (BAM_PT_proscenium_motion_bridge,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
