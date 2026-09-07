_needs_reload = "bpy" in locals()

import bpy

from . import operators, panels, properties

if _needs_reload:
    import importlib

    for name in ['constants', 'mapping', 'action_access', 'rig_state', 'preroll', 'retarget', 'properties', 'operators', 'panels']:
        importlib.reload(importlib.import_module("." + name, __package__))


def register():
    properties.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    properties.unregister()
