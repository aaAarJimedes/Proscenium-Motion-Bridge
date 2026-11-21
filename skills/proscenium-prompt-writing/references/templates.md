# 单动作 Clip 示例

每个代码块仅包含要粘贴的 Motion Prompt。帧数、手动关键帧和注释在代码块外。以下时间仅为示例；服从实际工程 FPS。

## Clip 01 向前走两步 · 30 FPS · 本地 1–60 · 2s · 165/1000 字符

```text
A person takes two measured steps forward with relaxed shoulders, small natural arm swings, and balanced weight transfer, continuing smoothly into the next movement.
```

手动关键帧：1 沿用实际起姿；30 第一步落脚；60 第二步承重。注：完整位移，精确终点用 Root Path。

## Clip 02 向右转身 · 30 FPS · 本地 1–45 · 1.5s · 189/1000 字符

```text
The person pivots to their right in two small steps, leading with the head while the torso follows, keeping both hands close to the waist and finishing with weight supported over both feet.
```

手动关键帧：1 沿用上一段末姿；22 换重心；45 到目标朝向。注：完整位移；不额外增加停顿。

## Clip 03 唇边撩发到耳后 · 30 FPS · 本地 1–75 · 2.5s · 358/1000 字符

```text
The person starts with the right fingertips beside the lips and sweeps the raised right hand directly upward beside the cheek, past the temple, and behind the right ear in one continuous hair-tucking gesture. The right elbow stays bent and the hand never drops below chin level or detours across the chest. The left forearm remains lifted with its palm open.
```

手动关键帧：1 沿用上一段实际唇边起姿；26 右脸颊上方；48 太阳穴外侧；75 耳后。注：原地动作；RightHand 位置目标逐帧采样并随头部移动，掌向和手指另修。

## Clip 04 单一搅拌动作 · 30 FPS · 本地 1–120 · 4s · 303/1000 字符

```text
A person continuously stirs a bowl with the right hand using three small even circles, keeping the spoon gripped and the left hand steady on the bowl rim. The shoulders stay low, the elbows remain soft, and the feet stay planted with subtle weight transfer. The spoon remains inside the bowl at the end.
```

手动关键帧：1 实际持握；40、80、120 各完成一圈。注：双手目标分别对应搅拌轨迹和碗沿；此段不放下勺子、不转身。

需要单帧 Pose 时，单独交付一个标明“Generate Pose”的静态姿势代码块；不要混在 Motion Clip 的可复制区内。
