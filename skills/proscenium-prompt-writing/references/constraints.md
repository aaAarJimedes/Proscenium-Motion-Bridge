# Implementable constraints next to the clip

Use a compact table with local frame, body state, hand/foot state, and contact event. Give start, one or more meaningful intermediate waypoints, and end only where needed. These are **manual keyframes** by default. Do not add a pose-generation prompt for every row.

| Need | Control | Important limit |
| --- | --- | --- |
| Actual previous end pose | Copy the evaluated accepted pose into source keys at local frame 1 | Reusing the same wording or a pending preview is not pose continuity |
| Facing/silhouette | Pose anchor | A full-body anchor can constrain more joints than intended |
| Ground route | Root Path or root keys | Disable preview path snapping before adding a curve if it would overwrite authored root keys; check installed behavior |
| Hand/foot position | Supported canonical hand/foot effector | Target is joint origin, not fingertips; position does not prescribe wrist orientation or finger curl |
| Grip and prop release | Prop attachment plus matching hand contact animation in Blender | A generated skeleton does not create or attach the prop |

## Continuous paths

For a hand that must stay raised, pinning only the first and last frames leaves the middle unconstrained. Plan an animated hand target through explicit waypoints, and ensure the installed sampler sends the intervening frames when a continuous restriction is needed. In the documented Proscenium workflow, location keys become constraint frames; baking those target locations per frame removes unsampled gaps. Verify the actual request rather than asserting that three anchors control the whole curve.

For lips → cheek → temple → behind ear: start at the previous accepted wrist position, preserve the wrist-to-fingertip offset, keep a skin clearance, and carry the target with the head/body where appropriate. Check the world-space result during head motion. Use wrist orientation and finger keys separately. Avoid a world-static hand target during a turning body gesture.

At handoff, evaluate contact again on the target rig: retargeting changes limb proportions. A general anti-penetration guard can conflict with a specific contact; inspect its effect and use targeted correction rather than increasing every guard indiscriminately.

## Support and timing

Pin a foot only over its real support interval. Release it for a step. Preserve knee bending plane, limit reach, and inspect for hip compensation/foot slide. A shared seam needs both pose and velocity continuity. A smooth crossfade may still damage a grip or planted foot; protect those intervals, then refine the contact after retiming.

When an intermediate action ends, let the next one begin promptly. Do not allocate a mandatory still hold to each endpoint. Budget any desired pause explicitly in frames. Resampling a 30-FPS design in a 24-FPS scene without rescaling length makes every beat 25% longer.

## Repeated-failure response

If a restriction still fails: verify the accepted starting pose and active source action; inspect the enabled prompt range and sampled targets; check reachable distance and conflicting anchors; compare canonical and retargeted output. Then fix the failed layer. Do not claim success from text changes alone, promise exact fingers from a hand-position pin, or continue blind generation retries.
