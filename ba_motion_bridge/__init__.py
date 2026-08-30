_needs_reload = "bpy" in locals()

import bpy

from . import operators, panels, properties

if _needs_reload:
    import importlib

    properties = importlib.reload(properties)
    operators = importlib.reload(operators)
    panels = importlib.reload(panels)


def register():
    properties.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    properties.unregister()
