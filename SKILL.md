---
name: pcr-petdex-skill
description: 从 Spine 的 skel 或 JSON 骨骼、atlas 和贴图，在 Windows 上制作 PCR 风格透明桌宠，支持动作映射、高清素材构建、掌心拖动、边缘收纳、角色切换和可选 Codex 状态联动。附带本项目运行源码模板，适用于从零制作或扩展同类桌宠；不用于 ChatGPT Work 内置宠物。
---

# 从 Spine 到 Windows 桌宠

目标：一台 Windows x64 电脑、用户提供的 Spine 素材和本 skill，即可沿用附带框架制作接近 Ho-chan Petdex 的桌宠。同模型加参考配置可复现其动作和交互；换模型时保留相同行为，按实际骨架调整画面与掌心。不能承诺任意模型无需校准即可呈现相同效果。

本 skill 自带 `assets/project-template/`，包含透明窗口、渲染、状态机、角色配置、构建及可选联动代码。无需原仓库或原作者电脑；不包含角色骨骼、贴图、已导出的角色图片、虚拟环境、运行状态或 SpineViewer 二进制。工具准备默认需要网络，离线方式见工具参考。

## 工作流程

1. **确定输入和交付。** 找到骨骼、同名 atlas、atlas 引用的全部贴图，确定输出目录；缺省交付可双击启动的源码目录。需要任务状态联动才接入 Codex，需要随 Codex 启动才启用自启动。不要改成 Work 宠物、网页或视频。
2. **准备工具和源码。** 阅读 [Windows 工具](references/windows-tools.md)，在新目录运行 `scripts/create_workspace.py` 复制模板和素材，再按需要运行 `scripts/prepare_tools.ps1` 准备依赖。交付说明列出工具与命令，不复制其他电脑的 `.venv`。
3. **查询动作、选择配置。** 按 [制作流程](references/build-workflow.md) 查询真实动画名与时长。同素材复刻使用参考配置；其他素材先创建角色配置，无法匹配时显式编辑。不要凭文件名前缀猜时长，或无说明地以待机代替缺失动作。
4. **固定坐标、构建素材。** 阅读 [画面与拖动校准](references/calibration.md)，保持统一原点、比例和时间轴。选好动作和画布再执行 `build_skin.py`；同时生成逐帧掌心坐标、无损 WebP 清单和四边头像。不必先导出全部原始 PNG。
5. **调整交互。** 沿用运行框架；改动时参照 [运行架构](references/runtime-architecture.md)。保留透明度预乘、独立呈现时钟、后台解码、同次提交窗口位置与像素等约束。
6. **按需联动。** 需要 Codex 联动时阅读 [Codex 集成](references/codex-integration.md)。安装器只管理自身配置；若当前 Codex 要求用户信任 Hook，说明准确入口，保留人工信任步骤，不修改信任数据库。
7. **验收与交付。** 按 [验收和排错](references/acceptance.md) 检查动作、拖动、菜单、DPI、边缘和联动，给出命令及实际完成的检查。用户限制不做环境验证时，只做获准的静态检查；不要创建虚拟机、模拟干净系统或声称已在新电脑验证。

## 参考配置

| 模型 | 构建角色 id | 配置 | 生产目录 |
| --- | --- | --- | --- |
| ホウオウ `134731` | `ho-chan` | `hochan-desktop-pet/skin.json` | `assets/characters/ho-chan/` |
| キョウカ（ゴシック）`139031` | `kyouka-gothic` | `hochan-desktop-pet/characters/kyouka-gothic/skin.json` | `assets/characters/kyouka-gothic/` |

模板注册配置不代表素材已构建。仅提供一个模型时只构建对应角色；菜单保留未构建角色为禁用项。新增角色可在自己配置中修改动作，不必改菜单代码。

## 不可丢失的制作约束

- 本框架逻辑宽度是 640，骨骼原点是 `(410,570)`，镜像绕 `x=410`。扩画布只向下补透明空间。不要逐帧居中或按各动作边界单独缩放。
- 参考配置按 60 FPS、3 倍分辨率采样。保留原动作总时长，用分段均匀采样避免 16/17 ms 舍入造成跳帧。单次、循环动作分别处理终点，拼接明确接缝策略。
- 拖动每帧必须有 `drag_anchor`。槽 `handB` 和偏移 `[24,7.5]` 仅对匹配骨架有意义；网格附件不能直接套用 region attachment 公式。
- 事件先进入状态机，窗口线程持有任务状态，后台观察器只返回事件。工具事件前保持思考，结束庆祝一次；权限决定来自用户实际选择。
- 构建和调试修改工作区副本，保持 skill 模板不变。不将个人 Codex 数据、IPC、启动项或本机路径写入分享模板。

## 资源和来源

- `scripts/create_workspace.py`：标准库脚本，复制模板和素材到不存在的目标目录。
- `scripts/prepare_tools.ps1`：检查工具，校验并展开固定版 SpineViewer，创建应用 Python 环境并安装依赖。不安装 Hook、自启动或启动桌宠。
- `assets/project-template/`：制作时复制的源码和配置；仅在需要修改实现时阅读。
- `assets/template-manifest.json`：文件摘要和移植调整，供完整性核查。
- `scripts/check_package.py`：不运行桌宠的包完整性、Python/JSON 语法、编码和本地链接检查。
- 模板内 LICENSE、UPSTREAM.md、ASSET-NOTICE.md：原始归属。用户素材沿用实际来源，新增角色不得默认标成 Cygames。

本 skill 提炼自 Ho-chan Petdex 当前工作区。本次仅做结构、语法和包完整性检查，未创建虚拟机、模拟新电脑、重新构建素材或执行运行验收。后续使用时记录当次实际完成的检查。
