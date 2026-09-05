# Release archive

下表记录本项目可恢复的全部原始 Blender 扩展包。GitHub Release 中的资产文件名、字节数和 SHA256 必须与此表一致。

| Tag | Release asset | Bytes | SHA256 |
| --- | --- | ---: | --- |
| `v0.1.0` | `ba_motion_bridge-0.1.0.zip` | 19,347 | `60dfc5f602a21f886c4ff0951c1f40447c128bd5d8da71bb54174f1ca7240ab6` |
| `v0.2.0` | `ba_motion_bridge-0.2.0.zip` | 24,473 | `b6b72edd51a6a092cc924c6d8b1ad329e8c07bf0eb09bc4dece9a0818b610d5a` |
| `v0.3.1` | `proscenium_motion_bridge-0.3.1.zip` | 27,597 | `81ca536bb76cc5424baa8a370f21963cd62b2aa6b099b76dab62b753091d6bae` |
| `v0.4.0` | `proscenium_motion_bridge-0.4.0.zip` | 30,934 | `6b035f9377fa2a2aa7ce81913479bb0682b9a24d3cd4e68cc9f5c7dca64b0e82` |
| `v0.5.0` | `proscenium_motion_bridge-0.5.0.zip` | 32,922 | `d000a5733e85a608e460675472f46e77b126bda3f9543b2d42c0b0ace7456cee` |
| `v0.6.0` | `proscenium_motion_bridge-0.6.0.zip` | 32,284 | `9a9d5994ced9df1d3d20b183f28d218014215b7945c75aaa3bbc7d60b2dfaed8` |
| `v0.7.0` | `proscenium_motion_bridge-0.7.0.zip` | 35,338 | `aa9e260c0006b9c3177e0b975e7926c54bfe0502735e6b710bfb28639d5692ac` |
| `v0.8.0` | `proscenium_motion_bridge-0.8.0.zip` | 37,628 | `86c6817e43319d365c622a80c2985435d212e75ad456c7591cd482b17d538911` |
| `v0.8.1` | `proscenium_motion_bridge-0.8.1.zip` | 37,987 | `3f7735c16f6ede1aeeecf15bd4ee5088cc606ef608db694cf03a3a27a8379b88` |
| `v0.9.0` | `proscenium_motion_bridge-0.9.0.zip` | 40,849 | `9e83d8eb458f979b84a6813a7aa39e5a7750f7d936b1e821414e494c04d65ea3` |
| `v0.9.1` | `proscenium_motion_bridge-0.9.1.zip` | 41,239 | `3a2cb625f549a0ee2e75ec71856916b4478eee264055c48ddd5ad312015c127e` |
| `v0.9.2` | `proscenium_motion_bridge-0.9.2.zip` | 42,101 | `87670b2ab65e20eaeba96094a3b6e9fd1111728e6653911f8162ae4f5ec0c41d` |

## Version highlights

- `v0.1.0`：建立 SOMA → MMD 映射、事务恢复与安全输出基线。
- `v0.2.0`：统一 Proscenium 输出入口，增强真实 MMD 骨架重定向与恢复流程。
- `v0.3.1`：更名为 Proscenium Motion Bridge；单面板工作流、Auto-Rig Pro 与静置方向补偿。
- `v0.4.0`：加入可配置初始姿态、静置帧、过渡帧和物理预热缓冲。
- `v0.5.0`：合并根运动策略；支持多角色安全切换与负帧 Preview Range/物理缓存起点。
- `v0.6.0`：采用插件自有映射和原生重定向器，移除 BlendCap 依赖；修复 ToeBase → MMD 脚尖骨轴问题。
- `v0.7.0`：加入输出/重新激活进度反馈，优化窄面板布局、说明文字与多角色重新激活安全性。
- `v0.8.0`：新增目标初始布置动作空间；全身动作与根位移跟随角色朝向，保留对象/父级及 MMD 根控制骨的位置、旋转和等比缩放，同时提供旧版世界方向兼容模式。
- `v0.8.1`：修复对象或父级经过旋转时静置方向校正重复应用朝向、导致四肢姿态扭曲的问题；优先使用专用根布置控制，避免旧动作污染布置朝向。
- `v0.9.0`：新增默认开启的“肢端防穿模”；按每套骨架的肩宽、臂长和手骨尺度检测近距离额外收拢，以保留肘弯平面和手掌朝向的双骨 IK 稳定腕点，并支持角色旋转与腕捩中间骨。
- `v0.9.1`：把“肢端防穿模”改为同一行的复选框与 `0.25–3.00` 幅度值；`1.00` 保持标准比例修正，更高数值为宽袖、大手等目标增加可调安全间距。
- `v0.9.2`：把“缓冲帧”明确为正式首帧前的负帧总边距，过渡帧改为包含在缓冲内并自动截断；旧工程按原“静置 + 过渡”的实际总长度迁移，同时修复关闭顺序物理预热时的输出异常。
