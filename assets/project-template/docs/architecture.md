# PCR 桌宠代码结构

桌宠仍由 `hochan-desktop-pet/start-hochan.cmd` 启动。运行目录、自启动快捷方式和已安装的 `hooks/codex-hochan-hook.ps1` 入口保持稳定。

## 运行层次

| 模块 | 职责 |
| --- | --- |
| `win32_api.py` | Win32 常量、结构体、函数签名；不读取角色或任务状态 |
| `pcr_pet.py` / `PcrPet` | 原生透明窗口、位图上传、鼠标捕获、屏幕边缘收纳和庆祝特效 |
| `windows_pet.py` / `WindowsPet` | 任务与子代理状态、动作选择、场景合成、权限气泡及任务选择面板 |
| `hochan_pet.py` / `HoChanPet` | 启动入口、角色切换、大小、逐帧手掌锚定和呈现时钟 |
| `context_menu.py` | 唯一的右键菜单实现、设置和日志操作 |

继承关系为 `HoChanPet(ContextMenuMixin, WindowsPet)`，`WindowsPet(PcrPet)`。底层窗口调用上层提供的动作选择、合成与交互方法；高分辨率图像只经过一次像素转换和原生上传。

## 状态与素材

- `codex_bridge.py` 定义项目 `state/` 默认路径、原子写入和事件协议，心跳文件为 `pcr-heartbeat.json`。
- `hooks/codex-hochan-hook.ps1` 是直接处理事件与权限请求的单一入口；显式 `-StateDirectory` 决定状态路径，不借助全局环境变量转发。
- `codex_observer.py` 补充观察任务，`family_store.py` 维护任务关系，`animation_clock.py` 维护各任务的播放进度，`leisure.py` 管理空闲和休息动作。
- `character_catalog.py` 发现 `characters/*/character.json`；配置指定动作映射、生产资源和边缘头像。角色切换保留任务、权限和设置，失败时保留原角色。
- 生产角色资源统一放在 `assets/characters/ho-chan/` 与 `assets/characters/kyouka-gothic/`；各自包含 `animation-resources/` 与 `edge-tail/`。`skin.json` 的 `animation_prefix` 分别为 `hochan`、`kyouka-gothic`，构建与清单保持对应角色的序列目录名。
- v2 动画清单只引用裁切后的 3 倍无损 WebP，同角色内相同图片共用文件。普通逻辑帧按需生成，少量像素修正确保与原 PNG 的 RGBA 值一致；v1 PNG 包保持兼容。`asset_storage.py` 负责缩放、无损存储、去重和安全清理。执行工具、空闲鞠躬和点击反馈的动作键为 `working`、`bow`、`click_feedback`。`sleep_entry` 复用休息动作。
- `source/` 在本地保存源模型和原始帧，不纳入 Git；构建、测试产物、状态、虚拟环境也不随源码提交。运行所需的生产素材保存在 `hochan-desktop-pet/assets/` 并随项目提交。

## 清理范围与验证

移除了旧 GIF 加工／缓存／启动入口、旧更新下载和安装系统、重复菜单、旧角色图片、平台图标、重复特效以及睡眠透明占位层。压缩动作仅保留实际配置，随机选择不依赖重复别名。

`tools/verify_cleanup.py` 检查本地导入、命名、资源引用、构建配置和旧模块残留；现有 `verify_skin.py`、`verify_rendering.py`、`verify_characters.py`、`verify_hooks.py`、`verify_runtime.py`、拖动、大小和压缩验证覆盖实际行为。GUI 验证使用隔离状态；自启动单元验证不修改实际启动设置。

原作者署名与软件来源仅保存在许可证及 `UPSTREAM.md`、`ASSET-NOTICE.md` 中，方便核查真实来源。
