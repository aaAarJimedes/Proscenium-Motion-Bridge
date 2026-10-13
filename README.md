# Proscenium Motion Bridge

Blender 扩展，用于把 Proscenium / Animatica 标准骨架动作重定向到 MMD 与 Auto-Rig Pro 角色。

`main` 包含 0.10.2 开发源码；当前正式发行包仍为 [v0.10.0](https://github.com/aaAarJimedes/Proscenium-Motion-Bridge/releases/tag/v0.10.0)。0.10.1 / 0.10.2 的源码同步不表示它们已完成正式发行验收。

正式发行前还需验证对应安装包与已启用配置，并在代表性真实模型上检查连续动作、肩腕活动、蒙皮和道具接触。详见 [发布说明](docs/GITHUB_DELIVERY.md)。

## 0.10.2 开发更新

新增「检查 Q 版肘关节（当前帧）」与 `arm_anatomy.inspect_mmd_elbows`。针对本次中秋三套 Q 版 MMD 模型已校准的局部 -Z 屈伸轴，检查反向屈曲、侧向偏轴和过度屈曲，重复更新同一个 Blender 文本报告，不改动姿态、帧或动作。其他骨架必须先校准轴，不能照搬这个配置。

本次动画修复采用正向单轴肘部求解、肩部姿态和原有扭骨转掌。插件提供诊断，不自动修改重定向结果。手腕角度下降不等于动作自然；还要检查肩部、蒙皮、道具接触和连续中间帧。

## 0.10.1 开发更新

面板新增「测量 Q 版 / MMD 接触范围」。先选择目标骨架，点击后会在 Blender 文本数据中得到 `Motion Bridge Reach - 骨架名` 报告，包含当前帧世界空间肩点、上臂、前臂与手掌长度。重复点击更新同一报告，不修改动画。目前按钮针对日文 `.R/.L` 手臂骨名；Python API 可传入自定义骨名。测量帮助安排桌面与道具位置，不能替代实际接触画面验收。

## 0.10.0 更新

拆分骨架状态恢复、Action 槽位访问、物理预滚动模块；烘焙和操作符共享 Action 读取。修复备用槽位选择代码不可达的问题，多个不明确的兼容槽位会回滚并提示选择。保持 0.9.1 的静置帧＋过渡帧规则，未重新引入此前回退的 0.9.2 缓冲含义。

项目最初以 **BA Motion Bridge** 发布（v0.1.0–v0.2.0），自 v0.3.1 起更名为 **Proscenium Motion Bridge**。已发布历史版本保存在原有 Git 标签与同一个 GitHub 发布楼中，发布楼保留原始 Blender 扩展 ZIP。

## 安装

1. 从 GitHub Releases 下载所需版本的 ZIP，不要解压。
2. 在 Blender 5.1 或更高版本中打开“偏好设置 → 扩展”。
3. 从磁盘安装 ZIP，然后启用 **Proscenium Motion Bridge**。

## 开发

当前插件源码位于 `proscenium_motion_bridge/`。版本清单与发布资产哈希见 `RELEASES.md`。

`tools/build_latest.py` 在本工作区默认输出到 `Agent Delivery/Motion_Bridge/Proscenium/`，外部检出默认输出到 `dist/`；可用 `--output-dir` 指定独立验证目录。构建开发包不会自动发布。

回归测试使用 Blender 5.1+ 的独立工厂场景。分别设置对应环境变量为 `isolated-factory-test`，再运行 `blender --background --factory-startup --python-exit-code 1 --python <脚本>`：

| 脚本 | 环境变量 | 验证范围 |
| --- | --- | --- |
| `tests/contact_diagnostics_test.py` | `PMB_DIAGNOSTICS_TEST_ALLOW` | 手臂比例、可达范围、肘轴诊断、报告复用和姿态保护 |
| `tests/end_effector_guard_test.py` | `PMB_GUARD_TEST_ALLOW` | 末端保护、幅度和旋转不变性 |
| `tests/motion_space_placement_test.py` | `PMB_PLACEMENT_TEST_ALLOW` | 根运动、对象/父级朝向和原地模式 |

这些合成骨架测试不能代替实际模型、蒙皮接触和连续动画的视觉验收。直接调用测量/肘诊断 Python API 前，应先更新依赖图；肘诊断仅适用于已校准的局部 -Z 屈伸轴。

## 许可

GPL-3.0-or-later。
