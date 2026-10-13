"""Measured contact planning for rigs with non-human/chibi proportions.

No scene mutations. Coordinates and distances are world-space, including root
scale. Call from the desired pose after dependency-graph evaluation.
"""
from dataclasses import dataclass
import math
from mathutils import Vector


@dataclass(frozen=True)
class ArmReach:
    shoulder: tuple
    upper_length: float
    forearm_length: float
    hand_length: float

    def __post_init__(self):
        if len(self.shoulder) != 3 or not all(math.isfinite(v) for v in self.shoulder):
            raise ValueError('shoulder must contain three finite coordinates')
        if not all(math.isfinite(v) and v > 1e-8
                   for v in (self.upper_length, self.forearm_length, self.hand_length)):
            raise ValueError('Arm has zero or invalid world-space length')

    @property
    def maximum(self):
        return self.upper_length + self.forearm_length

    @property
    def minimum(self):
        return abs(self.upper_length - self.forearm_length)

    def project(self, goal, margin=0.02):
        """Return reachable goal and requested overshoot; never silently hide it."""
        if not 0 <= margin < .5:
            raise ValueError('margin must be in [0, .5)')
        point=Vector(goal)
        if len(point) != 3 or not all(math.isfinite(v) for v in point):
            raise ValueError('goal must contain three finite coordinates')
        origin=Vector(self.shoulder);delta=point-origin;distance=delta.length
        if distance < 1e-10:
            raise ValueError('goal at shoulder has no direction')
        lower=self.minimum+self.maximum*margin
        upper=self.maximum*(1-margin)
        if lower > upper:
            raise ValueError('margin leaves no reachable interval for these arm proportions')
        reach=max(lower,min(upper,distance))
        return origin+delta*(reach/distance), abs(reach-distance)


def measure_arm(armature, upper_name, forearm_name, hand_name):
    if armature is None or armature.type != 'ARMATURE':
        raise ValueError('Expected an armature')
    bones=armature.pose.bones
    missing=[n for n in (upper_name,forearm_name,hand_name) if n not in bones]
    if missing:
        raise ValueError('Missing arm bones: '+', '.join(missing))
    matrix=armature.matrix_world
    upper,fore,hand=(bones[n] for n in (upper_name,forearm_name,hand_name))
    if upper not in fore.parent_recursive or fore not in hand.parent_recursive:
        raise ValueError('Arm bones must form an upper-arm, forearm, hand chain')
    shoulder,elbow,wrist,tip=(matrix@p for p in (upper.head,fore.head,hand.head,hand.tail))
    lengths=((elbow-shoulder).length,(wrist-elbow).length,(tip-wrist).length)
    if not all(math.isfinite(v) and v>1e-8 for v in lengths):
        raise ValueError('Arm has zero or invalid world-space length')
    return ArmReach(tuple(shoulder),*lengths)
