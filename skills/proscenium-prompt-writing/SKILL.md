---
name: proscenium-prompt-writing
description: Write directly pasteable Proscenium/Kimodo motion or pose prompts, with one physical action per clip and precise start, path, contact, and end constraints. Use for Chinese or English action ideas, clip splitting, keyframe plans, root motion, or Motion Bridge handoff. Each submitted prompt is limited to 1000 characters. Not for Blender execution, camera, lighting, or audio.
---

# Proscenium prompt writing

Deliver the exact text to paste and the controls needed to make that action specific. A **clip is one generation unit, one dominant physical action, and one motion prompt**. A long film is a sequence of numbered clips, never a larger “Clip” containing several unrelated prompt blocks.

## Delivery contract

- For one action, return one fenced `text` block containing only the final English prompt. No `prompt:`, quotes, character counts, YAML, comments, alternatives, or explanations inside it.
- For a sequence, give each clip its own heading with the action name, FPS, local frame range, duration, and verified character count. Put exactly one motion prompt block below it.
- Put that clip's keyframes and constraints immediately below its block, in concise Chinese prose or a small table. Do not collect anchors for all clips into a second distant plan. Omit irrelevant controls and repeated handoff boilerplate.
- Default keyframe instructions describe **manual poses**, not additional Generate Pose prompts. Label them “手动关键帧”; they are instructions to implement, not something the prompt parser will execute. For an explicitly requested pose-generation task, return the pose prompt as its own clearly named delivery unit.
- Do not include `mode`, `motion_summary`, `purpose`, `generation_notes`, `validation`, or a YAML production-plan wrapper in ordinary user-facing prompt output. Use structured data only when the user or a verified plugin importer requires it.
- When the user asks for files, provide one UTF-8 `.txt` per clip containing only the prompt and one readable guide. A clip manifest may support validation/export; do not tell the user to paste JSON into a text-only field.

## Compose each clip

1. Read the actual scene FPS, generation range and previous pose when supplied. Otherwise state a reasonable FPS assumption once. Use the active model's verified duration limit; a user-specified ten-second maximum applies to this project, not every model.
2. Identify one physical action. Preparation and follow-through belong together when they are the mechanics of that action; changes of goal, contact state or gesture normally need a new clip. “Stir → put down → wipe → turn” is four clips. “Hand rises along cheek to tuck hair” is one continuous gesture. Do not split it at every waypoint.
3. Specify the starting state, active limb, direct path/direction, tempo or count, essential support state, and ending state. Add only cues that change the output. Read [prompt-grammar.md](references/prompt-grammar.md) for difficult constraints or repeated failures.
4. Keep contact facts in the action text when they matter: holding a spatula, steadying a bowl, keeping the free palm raised. Exact placement and attachment still require actual constraints; do not strip away the action's physical meaning to make it shorter.
5. Preserve user restrictions, including useful explicit negatives such as “never drops below chin level.” Prefer a positive path plus a short prohibition for the observed error. Do not produce a separate negative-prompt list or imply the model guarantees compliance.
6. An intermediate clip ends ready for the next action, with residual motion where appropriate. Do not add “settles, holds, pauses” to every clip. Reserve deliberate holds for storytelling or the final shot; don't equate motherly warmth with uniformly slow movement.

## Frames and continuity

Local frames are `1–N`; duration is `N / effective_fps` where effective_fps = fps / fps_base. If global placement is useful, label it separately. A shared seam sample may be reused internally by NLA, but must not silently subtract a frame from every delivery clip. Distinguish playable frame count from the number of interpolation intervals.

Use the previous **accepted, evaluated last pose** as the next clip's first manual anchor. Identical text does not guarantee identical poses. Check support foot, root position/facing, wrist orientation, held prop, and ongoing velocity. When root travel is required use `FULL`; use `IN_PLACE` for stationary work or external placement. Root position and orientation are separate requirements.

For precision, read [constraints.md](references/constraints.md). Match text and controls before generation. If repeated output violates a correctly expressed path, inspect/strengthen actual constraints or plan local animation cleanup; don't keep rewriting synonyms.

## 1000-character gate

Every literal motion or pose prompt must be nonempty and at most **1000 characters**, including spaces and punctuation. Prefer a compact, complete description, usually 120–450 characters; do not remove essential restrictions to hit a soft target. Use plain English punctuation and one line. Recount after every edit with `scripts/count_prompt.py`.

For a sequence manifest, use `scripts/export_clips.py manifest.json output_directory` to validate unique clip IDs, FPS, frames, prompt limits, and anchor ranges, and export only clean prompt files. This validator cannot prove one-action semantics or contact accuracy; inspect those yourself.

Before delivery check: one action and one paste block per clip; settings and manual anchors unambiguously outside; frames and counts measured; no contradictory contact or facing states; no arbitrary inter-clip pauses; requested restrictions retained. See [templates.md](references/templates.md) only for relevant examples.
