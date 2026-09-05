import bpy
import textwrap

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


def _text_width(context, *, inset: int = 0) -> int:
    region_width = int(getattr(getattr(context, "region", None), "width", 280) or 280)
    return max(14, min(54, int((region_width - 28 - inset) / 11)))


def _draw_wrapped(layout, context, text: str, *, icon: str = "NONE", inset: int = 0) -> None:
    lines = textwrap.wrap(
        str(text or ""),
        width=_text_width(context, inset=inset),
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    for index, line in enumerate(lines):
        layout.label(text=line, icon=icon if index == 0 else "BLANK1")


def _draw_status(layout, settings, context) -> None:
    if settings.expected_count:
        layout.label(
            text=f"主链 {settings.matched_count}/{settings.expected_count}",
            icon="CHECKMARK" if settings.mapping_valid else "ERROR",
        )
        profile = {
            "AUTO_RIG_PRO": "Auto-Rig Pro 控制链",
            "MMD": "MMD FK 骨架",
        }.get(settings.target_profile, settings.target_profile)
        if profile:
            layout.label(text=profile, icon="ARMATURE_DATA")
        if settings.auto_scale:
            layout.label(text=f"位移比例 {settings.scale_ratio:.4f}×", icon="EMPTY_ARROWS")

    level = getattr(settings, "status_level", "INFO")
    status = layout.column(align=True)
    status.alert = level == "ERROR"
    icon = {"READY": "CHECKMARK", "WARNING": "ERROR", "ERROR": "ERROR"}.get(level, "INFO")
    _draw_wrapped(status, context, settings.status_message, icon=icon, inset=12)

    if settings.critical_missing:
        warning = layout.column(align=True)
        warning.alert = True
        warning.label(text="关键骨缺失：", icon="ERROR")
        for item in settings.critical_missing.split("、")[:8]:
            warning.label(text=f"• {item}")
    if settings.next_action and level != "READY":
        _draw_wrapped(layout, context, f"下一步：{settings.next_action}", icon="FORWARD")


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

        if settings.progress_active:
            progress_box = layout.box()
            progress_box.label(text="正在处理，请勿重复点击", icon="SORTTIME")
            progress_box.progress(
                factor=settings.progress_value,
                type="BAR",
                text=settings.progress_message or "正在处理…",
            )

        rigs = layout.box()
        rigs.label(text="1. 选择骨架", icon="ARMATURE_DATA")
        rigs.label(text="Proscenium 官方源")
        rigs.prop(settings, "source_rig", text="")
        rigs.label(text="角色目标骨架")
        rigs.prop(settings, "target_rig", text="")
        source_ready = _is_official_source(settings.source_rig)
        target_ready = _live_armature(settings.target_rig) and settings.target_rig != settings.source_rig
        rigs.label(
            text="官方源已识别" if source_ready else "等待官方源",
            icon="CHECKMARK" if source_ready else "INFO",
        )
        rigs.label(
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
            _draw_wrapped(
                conflict,
                context,
                f"{previous_target.name} 仍有一个待处理恢复点",
                icon="ERROR",
            )
            _draw_wrapped(conflict, context, "“保留”会结束上一角色的一键恢复点", icon="INFO")
            restore = conflict.operator(
                "ba_motion_bridge.resolve_target_switch",
                text="恢复上一角色后切换",
                icon="LOOP_BACK",
            )
            restore.mode = "RESTORE"
            keep = conflict.operator(
                "ba_motion_bridge.resolve_target_switch",
                text="保留上一角色输出",
                icon="CHECKMARK",
            )
            keep.mode = "KEEP"

        options = layout.box()
        options.label(text="2. 输出设置", icon="SETTINGS")
        options.label(text="根运动处理")
        options.prop(settings, "root_motion_policy", text="")
        effective_root_motion = _effective_root_motion_mode(context.scene, settings)
        if settings.root_motion_policy == "AUTO":
            options.label(
                text="当前：完整位移" if effective_root_motion == "FULL" else "当前：原地动作",
                icon="INFO",
            )
        if effective_root_motion == "FULL":
            options.prop(settings, "auto_scale")
            options.prop(settings, "world_location")
        options.label(text="动作空间")
        options.prop(settings, "motion_space", text="")
        if settings.motion_space == "TARGET_PLACEMENT":
            _draw_wrapped(options, context, "保留角色布置；动作前方跟随角色初始朝向", icon="ORIENTATION_GLOBAL")
        else:
            _draw_wrapped(options, context, "兼容旧行为：动作方向保持官方骨架世界坐标", icon="INFO")
        guard_row = options.row(align=True)
        guard_row.prop(settings, "use_end_effector_guard", icon="CON_KINEMATIC")
        if settings.use_end_effector_guard:
            guard_row.prop(settings, "end_effector_guard_strength", text="幅度")
            _draw_wrapped(options, context, "1.00 为标准；仍穿模时逐步提高，动作偏硬时降低", icon="INFO")
        options.prop(settings, "accept_preview_on_run")

        buffer = options.box()
        buffer.prop(settings, "use_start_buffer", icon="PREVIEW_RANGE")
        if settings.use_start_buffer:
            buffer.label(text="初始姿态来源")
            buffer.prop(settings, "initial_pose_source", text="")
            if settings.initial_pose_source == "ACTION_FRAME":
                buffer.label(text="初始姿态 Action")
                buffer.prop(settings, "initial_pose_action", text="")
                buffer.prop(settings, "initial_pose_frame")
            buffer.prop(settings, "buffer_frames")
            buffer.prop(settings, "transition_frames")
            buffer.prop(settings, "evaluate_physics_preroll")
            buffer_frames = max(0, int(settings.buffer_frames))
            transition_frames = min(buffer_frames, max(0, int(settings.transition_frames)))
            settle_frames = buffer_frames - transition_frames
            _draw_wrapped(
                buffer,
                context,
                f"负帧总边距 {buffer_frames} 帧：静置 {settle_frames} 帧 + 过渡 {transition_frames} 帧",
                icon="INFO",
            )
            _draw_wrapped(buffer, context, "正式动作首帧不移动；过渡帧包含在缓冲帧内", icon="TIME")
            _draw_wrapped(buffer, context, "自动显示负帧预览范围，并停在缓冲起点", icon="TIME")

        mapping = layout.box()
        mapping.enabled = not target_conflict
        mapping.label(text="3. 识别与检查", icon="VIEWZOOM")
        mapping.operator(
            "ba_motion_bridge.prepare_from_proscenium",
            text="自动选择骨架、建立映射并检查",
            icon="VIEWZOOM",
        )
        mapping.operator("ba_motion_bridge.validate_mapping", text="只复查当前映射", icon="CHECKMARK")
        _draw_wrapped(
            mapping,
            context,
            "自动检查会寻找可信目标；复查不会更换当前选择。",
            icon="INFO",
        )
        _draw_status(mapping, settings, context)
        if settings.unmatched:
            _draw_wrapped(mapping, context, f"可选未匹配：{settings.unmatched}", icon="QUESTION")
        if settings.warnings:
            _draw_wrapped(mapping, context, settings.warnings, icon="INFO")

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
            and not settings.progress_active
            and not target_conflict
            and (previewing or motion_ready or settings.source_rig is None)
        )
        run.operator(
            "ba_motion_bridge.accept_and_retarget",
            text="接受并输出到角色" if previewing else "一键输出到角色",
            icon="ACTION",
        )
        _draw_wrapped(
            output,
            context,
            "Accept（若有预览）→ 检查映射 → 烘焙独立 Action → 写入负帧缓冲。",
            icon="INFO",
        )
        _draw_wrapped(
            output,
            context,
            "内置重定向 · 脚趾轴修正 · 失败自动回滚",
            icon="LOCKED",
        )

        finish = layout.box()
        finish.label(text="5. 输出结果", icon="RECOVER_LAST")
        if settings.last_output_action:
            output_action = bpy.data.actions.get(settings.last_output_action)
            output_target = str(output_action.get("bam_target_object", "")) if output_action else ""
            finish.label(text="上次输出 Action")
            _draw_wrapped(finish, context, settings.last_output_action, icon="ACTION")
            if output_target:
                _draw_wrapped(finish, context, f"原目标：{output_target}", icon="ARMATURE_DATA")
            activate = finish.operator(
                "ba_motion_bridge.activate_output",
                text="重新激活并预热物理",
                icon="RADIOBUT_ON",
            )
            activate.action_name = settings.last_output_action
            activate.target_name = output_target
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
            _draw_wrapped(
                finish,
                context,
                "恢复原 Action、约束、IK/FK 和时间轴；输出 Action 不会被删除。",
                icon="INFO",
            )
        else:
            finish.label(text="当前没有待恢复事务", icon="CHECKMARK")
        finish.operator("ba_motion_bridge.cleanup_temporary", text="清理临时资源", icon="TRASH")
        _draw_wrapped(
            finish,
            context,
            "只清理插件标记的未使用临时数据，不删除输出 Action。",
            icon="INFO",
        )


CLASSES = (BAM_PT_proscenium_motion_bridge,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
