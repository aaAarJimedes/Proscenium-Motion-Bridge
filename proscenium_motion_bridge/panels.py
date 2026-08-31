import bpy

from .operators import (
    _animation_present,
    _effective_root_motion_mode,
    _is_official_source,
)


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
        proscenium = getattr(context.scene, "proscenium", None)
        generating = bool(proscenium and getattr(proscenium, "is_generating", False))
        previewing = bool(proscenium and getattr(proscenium, "is_previewing", False))

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
        try:
            previous_target = settings.previous_target_rig
        except ReferenceError:
            previous_target = None
        target_conflict = bool(
            settings.previous_target_state_available
            and previous_target
            and settings.target_rig
            and previous_target != settings.target_rig
        )
        if target_conflict:
            conflict = rigs.box()
            conflict.alert = True
            conflict.label(text=f"{previous_target.name} 仍有一个待处理恢复点", icon="ERROR")
            conflict.label(text="“保留”会结束上一角色的一键恢复点", icon="INFO")
            row = conflict.row(align=True)
            restore = row.operator(
                "ba_motion_bridge.resolve_target_switch",
                text="恢复上一角色后切换",
                icon="LOOP_BACK",
            )
            restore.mode = "RESTORE"
            keep = row.operator(
                "ba_motion_bridge.resolve_target_switch",
                text="保留上一角色输出",
                icon="CHECKMARK",
            )
            keep.mode = "KEEP"

        options = layout.box()
        options.label(text="2. 输出设置", icon="SETTINGS")
        options.prop(settings, "root_motion_policy")
        effective_root_motion = _effective_root_motion_mode(context.scene, settings)
        if settings.root_motion_policy == "AUTO":
            options.label(
                text="当前：完整位移" if effective_root_motion == "FULL" else "当前：原地动作",
                icon="INFO",
            )
        if effective_root_motion == "FULL":
            row = options.row(align=True)
            row.prop(settings, "auto_scale")
            row.prop(settings, "world_location")
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
            buffer.label(text="自动显示负帧预览范围，并停在缓冲起点", icon="TIME")

        mapping = layout.box()
        mapping.enabled = not target_conflict
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
        run.enabled = (
            not generating
            and not target_conflict
            and (previewing or motion_ready or settings.source_rig is None)
        )
        run.operator(
            "ba_motion_bridge.accept_and_retarget",
            text="接受并输出到角色" if previewing else "一键输出到角色",
            icon="ACTION",
        )
        output.label(text="内置重定向 · 脚趾轴修正 · 起始缓冲 · 独立 Action", icon="LOCKED")

        finish = layout.box()
        finish.label(text="5. 输出结果", icon="RECOVER_LAST")
        if settings.last_output_action:
            row = finish.row(align=True)
            row.label(text=f"上次输出：{settings.last_output_action}", icon="ACTION")
            row.operator("ba_motion_bridge.activate_output", text="激活", icon="RADIOBUT_ON")
        recovery_pending = bool(
            settings.constraint_snapshot_json
            or settings.previous_target_state_available
        )
        if recovery_pending:
            finish.operator(
                "ba_motion_bridge.restore_previous_state",
                text="撤销本次应用（保留输出 Action）",
                icon="LOOP_BACK",
            )
        else:
            finish.label(text="当前没有待恢复事务", icon="CHECKMARK")
        finish.operator("ba_motion_bridge.cleanup_temporary", text="清理临时资源", icon="TRASH")


CLASSES = (BAM_PT_proscenium_motion_bridge,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
