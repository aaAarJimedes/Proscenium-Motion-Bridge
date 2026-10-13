"""Factory-scene regression for read-only contact planning and elbow diagnostics.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/contact_diagnostics_test.py and PMB_DIAGNOSTICS_TEST_ALLOW=isolated-factory-test.
Synthetic calibrated arms test the API contract, not real-character visual quality.
"""
from __future__ import annotations

import importlib
import json
import math
import os
from pathlib import Path
import sys
import tomllib

import bpy
from mathutils import Euler, Quaternion, Vector

if not bpy.app.background or os.environ.get('PMB_DIAGNOSTICS_TEST_ALLOW') != 'isolated-factory-test':
    raise RuntimeError('Diagnostics test requires an explicitly authorized background factory scene')

root = Path(__file__).resolve().parents[1]
import_root = Path(os.environ.get('PMB_IMPORT_ROOT', str(root)))
sys.path.insert(0, str(import_root))
addon = importlib.import_module('proscenium_motion_bridge')
from proscenium_motion_bridge.arm_anatomy import inspect_mmd_elbows
from proscenium_motion_bridge.constants import ADDON_VERSION
from proscenium_motion_bridge.proportion import ArmReach, measure_arm


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def rejected(call, message):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(message)


def make_rig():
    rig = bpy.data.objects.new('Calibrated diagnostic fixture', bpy.data.armatures.new('Diagnostic arms'))
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for side, sign in (('L', 1), ('R', -1)):
        upper = rig.data.edit_bones.new('腕.' + side)
        upper.head = (sign, 0, 2)
        upper.tail = (sign, 1, 2)
        twist = rig.data.edit_bones.new('腕捩.' + side)
        twist.head = (sign, .5, 2)
        twist.tail = (sign, .8, 2)
        twist.parent = upper
        fore = rig.data.edit_bones.new('ひじ.' + side)
        fore.head = upper.tail
        fore.tail = (sign, 1.7, 2)
        fore.parent = twist
        fore.roll = .4  # Nonidentity rest rotation must not count as a posed elbow twist.
        hand = rig.data.edit_bones.new('手首.' + side)
        hand.head = fore.tail
        hand.tail = (sign, 2.0, 2)
        hand.parent = fore
    bpy.ops.object.mode_set(mode='OBJECT')
    for bone in rig.pose.bones:
        bone.rotation_mode = 'QUATERNION'
    return rig


def snapshot(rig):
    animation = rig.animation_data
    return (
        bpy.context.scene.frame_current,
        tuple(tuple(row) for row in rig.matrix_world),
        tuple((bone.name, tuple(tuple(row) for row in bone.matrix_basis)) for bone in rig.pose.bones),
        animation.action.name if animation and animation.action else None,
        tuple(sorted(action.name for action in bpy.data.actions)),
    )


def pose_elbow(rig, side, axis, degrees):
    rig.pose.bones['ひじ.' + side].rotation_quaternion = Quaternion(axis, math.radians(degrees))
    bpy.context.view_layer.update()


addon.register()
rig = make_rig()
settings = bpy.context.scene.ba_motion_bridge_settings
settings.target_rig = rig
bpy.context.scene.frame_set(7)
bpy.context.view_layer.update()

manifest = tomllib.loads((import_root / 'proscenium_motion_bridge/blender_manifest.toml').read_text(encoding='utf-8'))
check(ADDON_VERSION == tuple(map(int, manifest['version'].split('.'))), 'Manifest and runtime must agree')
neutral = measure_arm(rig, '腕.L', 'ひじ.L', '手首.L')
check(abs(neutral.upper_length - 1) < 1e-5, 'Upper length')
check(abs(neutral.forearm_length - .7) < 1e-5, 'Forearm length')
check(abs(neutral.hand_length - .3) < 1e-5, 'Hand length')
check(inspect_mmd_elbows(rig)['passed'], 'Nonidentity rest rolls are not pose-axis violations')

parent = bpy.data.objects.new('Placed character root', None)
bpy.context.scene.collection.objects.link(parent)
parent.location = (4, -3, 2)
parent.rotation_euler = Euler((.3, -.2, .9))
parent.scale = (2, 2, 2)
rig.parent = parent
rig.pose.bones['腕.L'].rotation_quaternion = Quaternion((1, 0, 0), .5)
bpy.context.view_layer.update()
scaled = measure_arm(rig, '腕.L', 'ひじ.L', '手首.L')
check(abs(scaled.maximum - 2 * neutral.maximum) < 1e-5, 'Root scale must affect reach')
check((Vector(scaled.shoulder) - rig.matrix_world @ rig.pose.bones['腕.L'].head).length < 1e-5, 'World shoulder')
check(inspect_mmd_elbows(rig)['passed'], 'Placed root and rotated shoulder are not elbow flexion')

reach = ArmReach((0, 0, 0), 1, .7, .3)
for goal in ((0, 4, 0), (0, .1, 0), (0, 1, 0)):
    point, error = reach.project(goal)
    check(reach.minimum <= point.length <= reach.maximum, 'Projected point must be physically reachable')
    check(abs(error - (Vector(goal) - point).length) < 1e-5, 'Projection deviation')
rejected(lambda: ArmReach((0, 0, 0), 1, .1, .2).project((0, 1, 0), margin=.2), 'Reject inverted reach interval')
rejected(lambda: reach.project((0, 0, 0)), 'Reject directionless goal')
rejected(lambda: reach.project((math.nan, 1, 0)), 'Reject nonfinite goal')
rejected(lambda: reach.project((1, 2)), 'Reject wrong-dimensional goal')
rejected(lambda: ArmReach((math.nan, 0, 0), 1, .7, .3), 'Reject nonfinite shoulder')
rejected(lambda: ArmReach((0, 0, 0), -1, .7, .3), 'Reject invalid lengths')
rejected(lambda: measure_arm(None, 'a', 'b', 'c'), 'Reject missing armature')
rejected(lambda: measure_arm(rig, 'missing', 'ひじ.L', '手首.L'), 'Reject missing bones')
rejected(lambda: measure_arm(rig, '腕.L', 'ひじ.R', '手首.R'), 'Reject unrelated bone chains')

pose_elbow(rig, 'L', (0, 0, -1), 60)
check(inspect_mmd_elbows(rig)['passed'], 'Valid flexion should pass')
pose_elbow(rig, 'L', (0, 0, 1), 20)
check('反向屈曲' in inspect_mmd_elbows(rig)['elbows'][0]['issues'], 'Reverse flexion detection')
pose_elbow(rig, 'L', (1, 0, 0), 20)
check('侧向偏离屈伸轴' in inspect_mmd_elbows(rig)['elbows'][0]['issues'], 'Off-axis detection')
pose_elbow(rig, 'L', (0, 0, -1), 160)
check('屈曲超过设定范围' in inspect_mmd_elbows(rig)['elbows'][0]['issues'], 'Excessive flexion detection')
pose_elbow(rig, 'L', (0, 0, -1), 45)

before = snapshot(rig)
for operator, report_name in (
    (bpy.ops.ba_motion_bridge.measure_chibi_reach, 'Motion Bridge Reach - ' + rig.name),
    (bpy.ops.ba_motion_bridge.inspect_mmd_elbows, 'Motion Bridge · 肘关节检查'),
):
    check(operator() == {'FINISHED'}, 'Diagnostic operator failed')
    first = bpy.data.texts[report_name]
    pointer, content, count = first.as_pointer(), first.as_string(), len(bpy.data.texts)
    check(operator() == {'FINISHED'}, 'Repeated diagnostic failed')
    second = bpy.data.texts[report_name]
    check((pointer, content, count) == (second.as_pointer(), second.as_string(), len(bpy.data.texts)), 'Report must update in place')
    json.loads(content)
check(snapshot(rig) == before, 'Diagnostics must preserve pose, frame, action and transforms')

addon.unregister()
check(not hasattr(bpy.types.Scene, 'ba_motion_bridge_settings'), 'Unregister must remove settings')
addon = importlib.reload(addon)
addon.register()
addon.unregister()
print('PMB_CONTACT_DIAGNOSTICS_TEST=' + json.dumps({'status': 'PASS', 'version': manifest['version'], 'synthetic_calibrated_arms_only': True}))
