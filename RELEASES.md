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

## Version highlights

- `v0.1.0`：建立 SOMA → MMD 映射、事务恢复与安全输出基线。
- `v0.2.0`：统一 Proscenium 输出入口，增强真实 MMD 骨架重定向与恢复流程。
- `v0.3.1`：更名为 Proscenium Motion Bridge；单面板工作流、Auto-Rig Pro 与静置方向补偿。
- `v0.4.0`：加入可配置初始姿态、静置帧、过渡帧和物理预热缓冲。
- `v0.5.0`：合并根运动策略；支持多角色安全切换与负帧 Preview Range/物理缓存起点。
- `v0.6.0`：采用插件自有映射和原生重定向器，移除 BlendCap 依赖；修复 ToeBase → MMD 脚尖骨轴问题。
- `v0.7.0`：加入输出/重新激活进度反馈，优化窄面板布局、说明文字与多角色重新激活安全性。
