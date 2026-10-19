# PCR Petdex Skill

从 Spine 骨骼、图集和贴图制作 Windows 透明桌宠的 Agent Skill。仓库包含制作流程、可复制的运行源码模板、素材构建工具和验证脚本，供 agent 根据用户提供的角色素材创建或扩展桌宠。

本项目从 Ho-chan Petdex 的制作流程中提炼而来。Ho-chan 是参考角色之一；角色通过配置注册，可以更换模型、映射动作并加入自己的角色。新增模型需要检查动画命名、画面范围和拖动锚点。

## 能做什么

- 将 Spine 动画构建为高清无损 WebP 序列，保留动作时长并裁切、去重。
- 制作透明桌面窗口，支持掌心拖动、边缘收纳、右键菜单和角色切换。
- 配置待机、拖动、庆祝、休息、唤醒等动作，以及多段动作拼接。
- 按需接入 Codex 的任务、工具执行与确认状态，也可作为独立桌宠运行。
- 使用附带脚本检查素材、渲染、角色配置和交互行为。

交付形式是可双击启动的源码目录。仓库不包含已构建的角色动画包；使用前需要自行准备 Spine 素材并完成构建。

## 安装到 Codex

在 Windows PowerShell 中，将完整仓库克隆到用户级 skill 目录：

```powershell
$skillsDirectory = Join-Path $HOME '.agents\skills'
New-Item -ItemType Directory -Path $skillsDirectory -Force | Out-Null
git clone https://github.com/Rai-tj/pcr-petdex-skill.git (Join-Path $skillsDirectory 'pcr-petdex-skill')
```

Codex 从 `~/.agents/skills/` 加载用户级 skill。安装后若未出现，重启 Codex；目录发现与调用方式见 [OpenAI 官方 Skills 文档](https://learn.chatgpt.com/docs/build-skills)。也可以下载仓库 ZIP，将其中包含 `SKILL.md` 的完整目录放到该位置，目录名设为 `pcr-petdex-skill`。

使用时在提示词中指定 `$pcr-petdex-skill`，并提供素材目录和输出目录，例如：

```text
使用 $pcr-petdex-skill，根据 D:\SpineMaterial 中的骨骼、atlas 和贴图，
在 D:\MyDesktopPet 创建一个 Windows 桌宠。
先检查真实动画，再配置待机、掌心拖动、庆祝和边缘收纳。
本次只需要独立桌宠。
```

需要联动时，可以补充“接入 Codex 状态联动”。Hook 和自启动是可选项，按需安装。

## 准备素材和环境

每个角色需要：

- 一个 `.skel` 或 Spine 导出的 `.json` 骨骼文件。
- 与骨骼文件同名的 `.atlas` 文件。
- atlas 引用的全部贴图页，保持文件名和相对路径。

`.spine` 编辑器工程不能直接作为导出骨骼使用。准备好素材后，agent 会查询真实动画名、选择参考配方或创建角色配置，再校准视区与掌心位置。

制作环境要求 Windows 10/11 x64、Python x64 3.11+、PowerShell 7.4+、.NET 8 Desktop Runtime x64，以及固定版 SpineViewer v0.16.34。Python 依赖由模板的 `requirements.txt` 定义；具体安装入口和离线准备方式见 [Windows 工具](references/windows-tools.md)。

`prepare_tools.ps1` 可在系统工具已安装后校验并展开 SpineViewer、创建虚拟环境和安装 Python 依赖。它不会安装 Hook、启用自启动或启动桌宠。

## 手动开始

也可以直接使用脚本创建项目。以下命令从本仓库根目录执行，目标目录必须尚不存在：

```powershell
py -3 .\scripts\create_workspace.py --destination 'D:\MyDesktopPet' --materials 'D:\SpineMaterial'
pwsh -NoProfile -File .\scripts\prepare_tools.ps1 -Workspace 'D:\MyDesktopPet'
```

这两步仅准备项目和工具。随后按 [制作流程](references/build-workflow.md) 查询动画、注册角色、调整配置、构建并启动预览。构建和调试在新项目副本中进行，保留本仓库的模板用于后续制作。

## 参考角色

| 参考角色 | 模型 | 角色 ID |
| --- | --- | --- |
| ホウオウ（Ho-chan） | `134731` | `ho-chan` |
| キョウカ（ゴシック） | `139031` | `kyouka-gothic` |

仓库只提供这两个角色的参考配置，不包含其模型、贴图或导出帧。用户提供对应素材后才能构建；其他角色可使用自己的配置，模型差异需要实际校准。

## 仓库结构与文档

| 路径 | 内容 |
| --- | --- |
| [SKILL.md](SKILL.md) | Agent 使用的入口与制作约束 |
| [agents/openai.yaml](agents/openai.yaml) | Skill 名称、简介与默认提示词 |
| [assets/project-template/](assets/project-template/) | 可复制的桌宠源码、参考配置和说明 |
| [assets/template-manifest.json](assets/template-manifest.json) | 模板文件摘要与移植记录 |
| [scripts/](scripts/) | 创建项目、准备工具和静态检查脚本 |
| [Windows 工具](references/windows-tools.md) | 依赖、安装与离线准备 |
| [制作流程](references/build-workflow.md) | 素材组织、动画查询、角色注册、构建和启动 |
| [画面与拖动校准](references/calibration.md) | 固定视区、缩放、掌心锚点和画布 |
| [运行架构](references/runtime-architecture.md) | 窗口、渲染、状态机与事件流 |
| [Codex 集成](references/codex-integration.md) | 可选状态联动、Hook 与自启动 |
| [验收和排错](references/acceptance.md) | 验证方法与常见问题 |

包内自带静态检查，覆盖模板摘要、Python/JSON 语法、编码和本地文档链接。这些检查不代表已在新电脑上完成素材构建或运行验收；制作完成后仍需对目标角色和环境执行相应验证。

## 来源与许可

运行源码模板基于 [GooglePiggy DesktopPet](https://github.com/Myf-ricey/GooglePiggy_DesktopPet) 的 Windows 实现演进，原始 MIT 许可证保留在 [模板 LICENSE](assets/project-template/hochan-desktop-pet/LICENSE)，来源与修改记录见 [UPSTREAM.md](assets/project-template/hochan-desktop-pet/UPSTREAM.md)。

角色素材版权与程序代码许可分别处理。仓库不分发角色骨骼、贴图或导出动画帧；附带的两个中性效果图及参考角色的归属说明见 [ASSET-NOTICE.md](assets/project-template/hochan-desktop-pet/ASSET-NOTICE.md)。使用自己的素材时，应在角色配置中记录实际来源和版权信息。
