# Proscenium Motion Bridge 使用指南

适用版本：Blender 5.1.2、Proscenium Motion Bridge 0.8.0、Proscenium 0.4.0、MMD Tools 4.5.13。BlendCap、BlendCap Motion Bridge 与 BA Animation Workflow 都不是本插件依赖。

## 为什么先用官方骨架

Proscenium 对自己的 `kimodo-soma-rp` 30 骨骨架最稳定。直接让模型理解每个 MMD 角色的日文名、IK、捩骨、影骨、裙发骨和自定义层级，会把“生成动作”和“适配角色”两个不确定问题混在一起。

推荐链路把它们分开：

```text
自然语言 / 关键姿势 / Root Path
  → Proscenium 官方 kimodo-soma-rp
  → Preview
  → 接受并输出到角色（Proscenium Motion Bridge 0.8.0）
  → 独立 RETARGET Action
  → BA Workflow CLEAN / CORR
```

BlendCap Motion Bridge 针对常见 BVH：`LeftUpLeg=大腿`、`LeftLeg=小腿`。官方 SOMA 则是 `LeftLeg=大腿`、`LeftShin=小腿`。因此官方骨架必须使用 Proscenium Motion Bridge，不能点击传统 Detect。

统一界面没有合并插件。BA Animation Workflow、Proscenium Motion Bridge 与 BlendCap Motion Bridge 仍是三个可独立安装、升级和排错的技术包；Proscenium 也仍是独立第三方插件。Bridge 只在 `Proscenium` 标签注册一个面板，通过公开操作符调用 Accept。

## 五分钟上手

1. 在角色工程副本中打开 `N → BA 动画`，选择项目目录并点击工作台顶部的“一键初始化动画工程”。
2. 用 MMD Tools 导入角色，确认目标是 MMD 人体主 Armature 或 Auto-Rig Pro 控制器 Armature；然后切到 `N → Proscenium`。
3. 连接/刷新模型，选择 `kimodo-soma-rp` 并导入官方骨架。每次重启 Blender 后通常需要重新连接。
4. 在 Proscenium Timeline 创建 Prompt Block，生成并检查 Preview；暂时不要离开 `Proscenium` 标签。
5. 在同一标签唯一的 `Proscenium Motion Bridge` 面板选择官方源骨架与角色目标。面板从上到下就是实际工作流顺序，无需切换面板。
6. 在唯一的“根运动”选择器中选择：

   - `自动跟随 Proscenium`：读取 Proscenium 的 In-place 开关；
   - `完整位移`：身体旋转 + Root XY/Z，共 24 对；此时才显示体型比例与世界空间位移；
   - `原地动作`：不传 Root 位移，共 22 对。

   “动作空间”默认选择 `跟随目标初始布置`：目标人物提前移动、转向或放在父级 Empty 下时，动作的前后左右会跟随人物自身朝向；MMD `全ての親／センター` 等根控制骨的现有位置也会作为叠加基线保留。仅在复现 0.7 及更早版本时选择 `保持官方世界方向`。

7. 点“自动识别并检查”。没有关键缺失且显示 `24/24` 或 `22/22` 才继续；需要时可点“复查”。
8. Preview 满意后直接点“接受并输出到角色”。Bridge 会先 Accept，再自动检查并重定向；动作已 Accept 时按钮显示“一键输出到角色”。
9. 完成后目标骨架使用独立新 Action。先播放检查骨盆、肩肘、膝盖和脚底，再回到 `BA 动画` 建立 CORR 修正层。

输出期间，面板顶部和 Blender 状态栏会依次显示源动作准备、逐帧重定向、起始缓冲、物理预热与保存恢复点；重新激活旧输出时也会显示绑定与物理预热进度。进度无论成功或失败都会清理，不会留下永久“处理中”状态。

面板按窄 N 栏设计：骨架字段、映射按钮与恢复按钮纵向排列，长状态和 Action 名自动换行。每个操作按钮悬停时会说明它会修改什么、保留什么；按钮下方的短说明用于无需悬停即可判断用途。

生成进行中时输出按钮会锁定。若 Accept 成功而后续重定向失败，已接受的动作仍保留；按状态提示修正目标后，再点“一键输出到 MMD”，不需要重新生成。

## 初始姿态与起始缓冲

“输出设置”中的“启用起始缓冲”提供三种初始姿态来源：

- `当前角色姿态`：使用点击输出时目标骨架当前帧的姿态；
- `目标 Rest Pose`：将映射主体骨的 Matrix Basis 归零；
- `指定 Action 帧`：从用户选择的目标 Action 与帧号读取初始姿态，不修改该 Action。

静置帧与过渡帧均可设为 0–1000。插件保持正式动作原首帧不动，把缓冲键写在首帧之前：静置段保持初始姿态，过渡段用 Smoothstep 与四元数 SLERP 逐帧进入正式首姿。裙骨、发骨等非映射次级骨不会被写关键帧。

Action 的自定义正式范围仍从真正首帧开始，因此 NLA 和导出不会包含边距；预滚动关键帧保留在范围之外，供刚体从非穿模状态顺序求值。Blender 5.1 的场景起点硬限制为 0，因此插件会自动启用可为负值的 Preview Range，把预览起点和未烘焙 Rigid Body World 缓存起点设为负的预滚动起点，逐帧求值后把当前帧停在那里。MMD Tools 烘焙直接读取刚体缓存起点，因此可从负帧正确开始；恢复角色原状态时会还原原时间轴、Preview Range 与缓存起点。

若检测到已经烘焙的旧缓存，插件不会擅自清除，会完成主体输出并显示警告；应先释放旧缓存，再重新激活输出或重新烘焙包含预滚动区的物理。

## 默认主链映射

| 官方 SOMA | MMD 目标语义 |
|---|---|
| `Hips` ROT | `腰`（按腿与躯干共同祖先解析） |
| `Hips` LOC XY | `センター` |
| `Hips` LOC Z | `グルーブ`，无则按可用根骨降级 |
| `Spine1` | `下半身` |
| `Spine2` | `上半身` |
| `Chest` | `上半身2` |
| `Neck2` | `首` |
| `Head` | `頭` |
| `Shoulder / Arm / ForeArm / Hand` | `肩 / 腕 / ひじ / 手首` |
| `Leg / Shin / Foot / ToeBase` | `足 / ひざ / 足首 / つま先` |

Auto-Rig Pro 目标会切换到专用控制器 profile：肩、上臂、前臂、手、腿与脚分别写入 `c_shoulder.*`、`c_arm_fk.*`、`c_forearm_fk.*`、`c_hand_fk.*`、`c_thigh_fk.*`、`c_leg_fk.*` 与 `c_foot_fk.*`，不会给 `arm.*`、`forearm.*` 等内部机制骨打关键帧。输出期间手脚控制器切到 FK，恢复角色原状态时精确还原原来的 IK/FK 数值。

目标少一段脊柱时，Bridge 会保留最有意义的世界旋转累积，而不是把同一目标骨重复驱动。缺少大腿、小腿、脚、上臂、前臂、手、颈、头、骨盆或必要 Root 骨时会拒绝执行。

`Jaw`、眼睛和官方骨架的手部末端点不是完整 MMD 表情/手指链，默认不映射。表情、手指、武器接触、裙摆和头发放到 CORR、Shape Key 或物理流程处理。

## 为什么能处理不同 Rest Pose

Bridge 使用自有的依赖图世界空间 bake 和内部 SOMA 映射表，并为肢体构造只存在于本次烘焙内存中的源静置旋转覆盖。它移除源/目标静置方向之间的 swing、保留局部 Y 轴 twist（bone roll），从而避免 T-Pose 源把目标 A-Pose 的下垂角度再次带入端枪动作。场景中的源姿势不会被修改，也不需要启用 BlendCap。

`ToeBase → つま先` 是例外：两者表达的部位接近，但静置骨轴可能分别朝向脚背和脚尖。插件不会把脚趾纳入肢体的绝对骨轴对齐，而是传递“相对源 ToeBase Rest Pose 的旋转增量”到目标つま先的自身 Rest Pose。这样源骨静置朝上时不会把目标脚尖一起上翘，同时仍保留动作中的脚趾弯曲。

因此可处理：

- T-Pose 到 A-Pose；
- 不同 bone roll 和局部轴；
- 目标中间的捩骨或辅助骨；
- 源/目标脊柱段数不同；
- Proscenium Accept 后只有 NLA、没有活动 Action。

源和目标对象必须是等比缩放。检测到非等比缩放会停止，避免位置和骨长失真。

Root 位移比例取髋—头、髋—左右脚、肩—左右手等身体 landmark 比值的中位数，不扫描全部 MMD 骨，因此光环、武器、翅膀和长发不会污染身高。

## 目标初始布置与动作方向

`跟随目标初始布置` 会在输出前冻结角色的布置锚点：Armature 对象及父级的最终世界矩阵，以及可用的 MMD/ARP 根控制骨基线。插件只取两套骨架之间的水平朝向差，不把角色的俯仰或侧倾混入重力方向。

- 全身旋转增量会转入目标人物自己的朝向，因此转身 180° 的人物仍会朝自身前方走、向自身左右伸手；
- Root XY 随目标朝向旋转，Root Z 始终保持世界竖直；
- 已布置的对象位置、旋转、等比缩放不会被写关键帧或拉回原点；
- `全ての親／センター／グルーブ` 等根控制骨的已有位移作为基线，输出根运动叠加在其上；
- 原地动作虽然不输出 Root 位移，肢体动作方向仍会跟随目标朝向。

`保持官方世界方向` 完整保留旧行为：动作增量沿 Proscenium 官方骨架的世界坐标方向输出。它适合已有工程兼容，不建议用于已经在场景中转向的角色。

## 非破坏与恢复按钮

### 独立输出 Action

输出命名类似：

```text
ACT_星野_二年级__arm_<源动作>_MMD
```

它带 Fake User 和 `bam_role=RETARGET_OUTPUT`。原目标 Action 不改关键帧；原 Action Slot 与 NLA 开关会记录下来。

### 恢复之前的状态

重定向时只处理：

- 已映射大腿/膝/脚/脚趾骨上的 IK；
- 大腿到骨盆路径中名称明确表示“腰取消/cancel”的 TRANSFORM。

每项保存 owner、constraint name、type、mute 和 influence。手臂、裙发、附件和物理约束不会被批量关闭。

单一面板的“恢复角色原状态”会按当前可用快照一次恢复约束、IK/FK，以及自重定向前的目标 Action/Action Slot/NLA/Fake User 状态。新输出 Action 仍保留，可在 Dope Sheet/Action Editor 再次选用或点“激活”。

选择另一目标角色而上一角色仍有恢复点时，骨架区只临时显示两个明确按钮：“恢复上一角色后切换”会先精确恢复旧角色；“保留上一角色输出”会保留其当前输出和约束状态，并明确结束旧角色的一键恢复点。处理后即可继续对新角色自动映射，不再以报错阻断。

Bridge 的 SOMA 映射表、目标解析和烘焙器都属于插件自身，不存在借用或归还 BlendCap 映射表，因此自 0.6.0 起已移除“仅恢复映射”按钮。安装、禁用或卸载 BlendCap 都不会改变本插件的重定向结果。

### 清理桥接临时资源

只删除带 `bam_owner=proscenium_motion_bridge`（或旧版兼容值 `ba_motion_bridge`）、`bam_temporary=true` 的临时数据。不会删除 RETARGET_OUTPUT、用户 Action、MMD preset 或工程文件。

## 常见状态与排错

### 未找到官方骨架

- 在 `N → Proscenium` 点“导入官方骨架”；
- 不要手动复制标记到自定义骨架；Bridge 同时检查完整骨名签名。

### 关键骨缺失

- 确认选的是 MMD 人体 Armature，不是枪械、光环或服装辅助 Armature；
- 在 MMD Tools 中检查日文/英文 bone metadata；
- 不要把 IK 控制骨当主 FK 骨改名以绕过检查。

### 没有活动 Action 或已接受 NLA

- 在 Proscenium 预览阶段保留活动 Action，或点击 Accept；
- NLA 必须启用，Track/Strip 不能 mute，Strip influence 必须大于 0；
- Proscenium 0.4.0 Accept 会把 influence 强制设为 1。

### 脚滑或穿地

Bridge 解决骨架语义和 rest pose，不等于完整脚锁：

1. 生成提示词写清步数、方向、停止与平衡结束姿势；
2. 用 Proscenium Root Path 与 Foot Pins；
3. 重定向后在 CORR 层修脚底接触、骨盆高度和膝盖方向。

### 重定向失败

失败事务会自动恢复源 Action/NLA/帧、目标 Action/Slot/NLA、约束、IK/FK、物理缓存起点与时间轴状态。若提示“上次约束快照无法完整恢复”，通常是目标骨架或约束在上次运行后被删除/改名；先恢复角色副本或手动确认缺失项，再继续。

## 已验证边界

既有真实星野 MMD 骨架回归结果为 24/24、世界旋转误差 0°、6 个精确约束快照和 0 个临时 Action 残留。独立引擎通过无 BlendCap 的 24 对全链合成回归（上臂方向误差 0°）以及骨轴冲突脚趾回归（中性首帧 0°、动作增量约 20°）。0.7.0 另覆盖正常输出、故障回滚、重新激活、缓冲写入的进度生命周期，以及 280px 级窄面板的长 Action/状态换行。发布前仍应在角色工程副本中用实际动作目测脚底和端枪姿态。

这证明管线和数据安全，不等于证明任意自然语言动作的艺术质量。实际 Hosted 生成仍受提示词、关键姿势、模型能力和额度影响；用固定 10–15 秒黄金动作记录脚滑、穿模与人工修复时间，才能评价最终生产效率。
