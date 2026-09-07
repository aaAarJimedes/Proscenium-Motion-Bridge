## 0.10.0 更新

拆分骨架状态恢复、Action 槽位访问、物理预滚动模块；烘焙和操作符共享 Action 读取。修复备用槽位选择代码不可达的问题，多个不明确的兼容槽位会回滚并提示选择。保持 0.9.1 的静置帧＋过渡帧规则，未重新引入此前回退的 0.9.2 缓冲含义。

# Proscenium Motion Bridge

Blender 扩展，用于把 Proscenium / Animatica 标准骨架动作重定向到 MMD 与 Auto-Rig Pro 角色。

项目最初以 **BA Motion Bridge** 发布（v0.1.0–v0.2.0），自 v0.3.1 起更名为 **Proscenium Motion Bridge**。每个历史版本都保存在对应的 Git 标签和 GitHub Release 中，Release 附带原始 Blender 扩展 ZIP。

## 安装

1. 从 GitHub Releases 下载所需版本的 ZIP，不要解压。
2. 在 Blender 5.1 或更高版本中打开“偏好设置 → 扩展”。
3. 从磁盘安装 ZIP，然后启用 **Proscenium Motion Bridge**。

## 开发

当前插件源码位于 `proscenium_motion_bridge/`。版本清单与发布资产哈希见 `RELEASES.md`。

## 许可

GPL-3.0-or-later。
