# Motion semantics and precision

Write a skeleton-neutral English motion annotation: **start state + dominant action + active limb and direct route + supporting body behavior + end state**. Use character-local left/right. Keep time in the frame settings and world coordinates in the constraint instructions.

A clip may contain related verbs describing one mechanic, such as reaching and closing fingers on a handle. It should not switch to a different task such as carrying the object away. Use a change of intent or contact as the split criterion, not verb counting. Two repetitions of one gesture can remain one clip; keyframes carry their timing.

## Strong wording that remains useful

For a lip-to-ear gesture, “moves the hand to the ear” leaves the route unspecified. Say it starts raised beside the lips, slides upward beside the cheek to the temple, sweeps behind the ear, and never drops below chin level. Keep the left hand's current role explicit. Do not add a return to neutral unless requested.

For a prop, specify which hand grips which part and what the other hand does. For release, place the prop before opening the grip; do not make it vanish as the next clip begins. For a turn, establish head-leading, foot support and final facing without claiming an exact angle is guaranteed by words.

## Expressiveness without excess slowness

Translate warmth into observable choices: practiced economical movement, low shoulders, relaxed elbows, asymmetric open palms, a small listening head tilt, and a soft transfer of weight. Vary timing: decisive practical work, brief attentive reaction, then a readable welcome. Smiles, blinks, gaze and finger details need downstream animation unless the selected model supports them. A maternal impression is a creative interpretation, not an attribute guaranteed by skeletal motion.

Avoid camera, lighting, rendering, sound, narrative motivation, garment descriptions unrelated to motion, bone names, coordinates and IK commands inside prompt text. Meaningful props and contact verbs are allowed.

## Compression

Retain action, starting limb/contact state, direct route, critical restrictions, count, and endpoint. Remove synonyms and decorative mood words first. Move precise positions to constraints while preserving their semantic intent in prose. Split only at a real action boundary. Never truncate at 1000 characters. A necessary 500-character prompt is preferable to an ambiguous 100-character one.

## Official basis

[Proscenium usage](https://github.com/animatica-ai/animatica-blender-plugin/blob/main/docs/usage.md) distinguishes prompt blocks, keyframes, root paths and effector pins. The one-action clip card format is this skill's delivery convention; it is not an official file format. [Official skill](https://github.com/animatica-ai/animatica-blender-plugin/blob/main/skills/proscenium/SKILL.md) explains asynchronous generation and anchor sampling. Verify the installed version before describing exact API behavior.
