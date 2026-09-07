"""Blender layered-action access and deterministic slot binding."""
from __future__ import annotations

def _iter_action_fcurves(action):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        yield from legacy
        return
    slots = list(getattr(action, "slots", ()) or ())
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            yielded = False
            channelbags = getattr(strip, "channelbags", None)
            if channelbags is not None:
                try:
                    for channelbag in channelbags:
                        yield from channelbag.fcurves
                        yielded = True
                except TypeError:
                    yielded = False
            if yielded:
                continue
            channelbag_method = getattr(strip, "channelbag", None)
            if callable(channelbag_method):
                for slot in slots:
                    try:
                        channelbag = channelbag_method(slot)
                    except Exception:
                        channelbag = None
                    if channelbag is not None:
                        yield from channelbag.fcurves
                        yielded = True
            if yielded:
                continue
            strip_fcurves = getattr(strip, "fcurves", None)
            if strip_fcurves is not None:
                yield from strip_fcurves


def _action_slot(animation_data):
    if not hasattr(animation_data, "action_slot"):
        return None
    try:
        return animation_data.action_slot
    except (AttributeError, RuntimeError):
        return None


def _action_slot_identifier(slot) -> str:
    if slot is None:
        return ""
    try:
        return str(slot.identifier)
    except (AttributeError, ReferenceError, RuntimeError):
        return ""


def _find_action_slot(action, identifier: str):
    if action is None or not identifier:
        return None
    for slot in getattr(action, "slots", ()):
        if _action_slot_identifier(slot) == identifier:
            return slot
    return None


def _bind_action(animation_data, action, preferred_slot=None) -> None:
    """Bind a single known slot; fail instead of silently evaluating another take."""
    previous_action = animation_data.action
    previous_slot = _action_slot(animation_data)
    previous_identifier = _action_slot_identifier(previous_slot)
    animation_data.action = action
    if action is None or not hasattr(animation_data, "action_slot"):
        return
    suitable = list(getattr(animation_data, "action_suitable_slots", ()) or ())
    candidates = []
    if preferred_slot is not None:
        candidates.append(preferred_slot)
    if previous_identifier:
        matching = _find_action_slot(action, previous_identifier)
        if matching is not None:
            candidates.append(matching)
    if len(suitable) == 1:
        candidates.append(suitable[0])
    for slot in candidates:
        if slot not in list(getattr(action, "slots", ())):
            continue
        try:
            animation_data.action_slot = slot
            return
        except (AttributeError, RuntimeError, TypeError):
            continue
    if len(suitable) > 1:
        animation_data.action = previous_action
        if previous_slot is not None:
            animation_data.action_slot = previous_slot
        raise RuntimeError("Action 有多个兼容槽位；请先为骨架明确选择动作槽位")
    # Empty and legacy actions have no layered slots to bind.
