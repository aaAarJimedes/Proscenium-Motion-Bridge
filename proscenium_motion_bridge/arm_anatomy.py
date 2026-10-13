"""Read-only diagnostics for calibrated Moonfestival Q MMD elbows.
The local -Z flexion profile is not a universal MMD convention.
"""
import json
import math
import bpy

def inspect_mmd_elbows(target, max_flex_degrees=145.0, tolerance_degrees=2.0):
    """Inspect the evaluated pose after the caller updates the dependency graph.

    Does not change the pose, frame or animation.
    """
    if target is None or target.type != 'ARMATURE':
        raise ValueError('请选择 MMD 角色骨架')
    if not 0 < max_flex_degrees < 180 or not 0 <= tolerance_degrees < 20:
        raise ValueError('关节检查范围无效')
    rows = []
    for side in ('L', 'R'):
        bone = target.pose.bones.get('ひじ.' + side)
        if bone is None or bone.parent is None:
            raise ValueError('需要带父骨骼的 ひじ.L / ひじ.R 肘骨')
        parent = bone.parent
        delta = (bone.bone.matrix_local.inverted() @ parent.bone.matrix_local
                 @ parent.matrix.inverted() @ bone.matrix)
        q = delta.to_quaternion().normalized()
        if q.w < 0:
            q.negate()
        flex = math.degrees(2 * math.atan2(-q.z, q.w))
        off_axis = math.degrees(2 * math.asin(min(1.0, math.hypot(q.x, q.y))))
        issues = []
        if off_axis > tolerance_degrees:
            issues.append('侧向偏离屈伸轴')
        if flex < -tolerance_degrees:
            issues.append('反向屈曲')
        if flex > max_flex_degrees + tolerance_degrees:
            issues.append('屈曲超过设定范围')
        rows.append(dict(side=side, flex_degrees=flex,
                         off_axis_degrees=off_axis, issues=issues))
    return dict(profile='Moonfestival Q MMD / local -Z', target=target.name,
                frame=bpy.context.scene.frame_current, elbows=rows,
                passed=not any(row['issues'] for row in rows),
                limitations='仅检查当前姿态肘部；其他模型须先校准轴。不能代替连续画面、肩腕活动范围和蒙皮接触审查。')

class BAM_OT_inspect_mmd_elbows(bpy.types.Operator):
    bl_idname = 'ba_motion_bridge.inspect_mmd_elbows'
    bl_label = '检查 Q 版肘关节（当前帧）'
    bl_description = '按中秋 Q 版模型的局部 -Z 屈伸轴检查反折与侧弯，生成只读诊断；其他骨架须先校准轴'
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'ba_motion_bridge_settings', None)
        return bool(settings and settings.target_rig and not settings.progress_active)

    def execute(self, context):
        try:
            report = inspect_mmd_elbows(context.scene.ba_motion_bridge_settings.target_rig)
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        name = 'Motion Bridge · 肘关节检查'
        text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        text.clear()
        text.write(json.dumps(report, ensure_ascii=False, indent=2))
        count = sum(bool(row['issues']) for row in report['elbows'])
        self.report({'WARNING'} if count else {'INFO'},
                    f'{count} 条手臂需检查；诊断已写入文本。仅适用已校准 Q 版屈伸轴。')
        return {'FINISHED'}

def register():
    bpy.utils.register_class(BAM_OT_inspect_mmd_elbows)

def unregister():
    bpy.utils.unregister_class(BAM_OT_inspect_mmd_elbows)
