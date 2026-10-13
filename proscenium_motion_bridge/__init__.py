_needs_reload = "bpy" in locals()

import bpy

from . import arm_anatomy, operators, panels, properties

if _needs_reload:
    import importlib

    for name in ['constants', 'mapping', 'action_access', 'rig_state', 'preroll', 'retarget', 'proportion', 'arm_anatomy', 'properties', 'operators', 'panels']:
        importlib.reload(importlib.import_module("." + name, __package__))


def register():
    properties.register()
    operators.register()
    arm_anatomy.register()
    panels.register()


def unregister():
    panels.unregister()
    arm_anatomy.unregister()
    operators.unregister()
    properties.unregister()
