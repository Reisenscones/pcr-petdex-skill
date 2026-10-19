# Windows 工具与首次准备

## 必需工具

| 工具 | 用途及版本 | 安装入口 |
| --- | --- | --- |
| Windows 10/11 x64 桌面会话 | Win32 窗口、鼠标、菜单、WMI；可用图形驱动/OpenGL 供 SpineViewer 渲染 | 未验证 ARM64、Server 无桌面环境 |
| CPython x64 3.11+ | 构建和运行；建议 3.12 或 3.13，安装 pip、venv、Python Launcher | [Python Windows 下载](https://www.python.org/downloads/windows/) |
| PowerShell 7.4+，命令 `pwsh` | 构建时加载 .NET 8 的 Spine.dll，导出手掌坐标 | [Microsoft 安装说明](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) |
| .NET 8 Desktop Runtime x64 | 标准版 SpineViewerCLI 的 .NET 8 依赖，同时可运行 GUI | [Microsoft .NET 8 下载](https://dotnet.microsoft.com/download/dotnet/8.0)，选 Windows x64 Desktop Runtime |
| SpineViewer **v0.16.34 标准 Windows zip** | 查询动画、固定视区导帧；保留全部 DLL 和 Resources | [固定发行页](https://github.com/ww-rm/SpineViewer/releases/tag/v0.16.34) |
| Python 包 | `numpy>=1.26,<3`、`Pillow>=10,<13`、`zstandard>=0.23,<1` | 附带 requirements.txt |
| Windows PowerShell 5.1 | Windows 自带 powershell.exe，用于 Hook、自启动安装及移除 | 无需另装，不用 pwsh 替换这些入口 |

`dotnet --list-runtimes` 应同时含 `Microsoft.NETCore.App 8.x` 和 `Microsoft.WindowsDesktop.App 8.x`。仅安装其他主版本不能认定依赖齐全。

安装后重开终端，确认 `py -3 --version`（或 `python --version`）、`pwsh --version`、`dotnet --list-runtimes`。没有 Python Launcher 时把后续 `py -3` 换成明确的 Python 3 路径。

SpineViewer 此版本发布包具有 `--fixed-view`、`--fps`、`--drop-last-frame`。直接使用发布 CLI，无需编译原项目 ExportCommand.cs。无需付费 Spine 编辑器、Node.js、FFmpeg、Visual Studio 或 .NET SDK。其他模型加载失败时，先确认 Spine 版本，再针对性更新工具与掌心导出接口。

## 可选工具

- **Codex Desktop**：仅在需要实时任务联动时安装。事件与信任机制以当前客户端为准，见 [集成说明](codex-integration.md)。独立桌宠不需要 Codex。
- **Git**：用于版本管理，制作不依赖 Git 或原仓库访问权限。
- **SpineViewer GUI**：同 zip 提供，可辅助观察动作和骨架。

## 从空目录开始

`$skillPath` 改为当前 skill 所在目录。`D:\SpinePet` 是尚不存在的新项目目录，`D:\SpineMaterial` 是素材目录；这些是示例路径。

```powershell
$skillPath = 'F:\Github\ho-chan-petdex\pcr-petdex-skill'
py -3 "$skillPath\scripts\create_workspace.py" --destination 'D:\SpinePet' --materials 'D:\SpineMaterial'
pwsh -NoProfile -File "$skillPath\scripts\prepare_tools.ps1" -Workspace 'D:\SpinePet'
Set-Location -LiteralPath 'D:\SpinePet'
```

第一个脚本只复制模板及素材并保留子目录，不执行素材目录中的代码。骨骼与 atlas 在 source/spine 根目录可直接构建；原素材位于子目录时，将该组骨骼、atlas 和全部贴图一起整理到根目录，保持 atlas 页相对路径。

准备脚本不自动安装系统工具。先按表安装缺失项，再下载约 10 MB 的标准 zip，检查 SHA-256：

```text
c97f9df5aa653dd85e88d865930fa591b6367b8d7a265a1b5fd068230d418778
```

发行资产与原项目原包摘要一致。已下载可传 `-ViewerArchive 'D:\Downloads\SpineViewer-v0.16.34.zip'`。不要传 SelfContained 或 Linux zip。解压目录为 `.tools/SpineViewer-v0.16.34/`，Spine.dll 与 CLI 同目录。

离线电脑提前准备所有安装包、标准 Viewer zip，以及与目标 Python/Windows x64 匹配的三个包及其依赖 wheel；在目标电脑新建 `.venv`，运行 `pip install --no-index --find-links <wheel目录> -r requirements.txt`。手动展开工具并装 wheel，不用默认联网的 prepare_tools.ps1；不要拷贝其他电脑的虚拟环境。

## 制作后的运行依赖

已构建桌宠只需 Windows、该电脑 Python 环境及 requirements.txt 依赖。SpineViewer、.NET 8、PowerShell 7 仅用于重新处理素材；联动使用 Windows PowerShell 5.1。源码交付附生产 assets、配置、入口和说明，不附 .venv、state 或 Codex 数据库。
