# Spine Windows 桌宠工作区

此目录是 PCR Petdex skill 附带的源码模板。角色素材由使用者提供；先构建资源，再启动桌宠。无需访问原仓库。

## 准备

构建工具：Windows 10/11 x64、Python 3.11+ x64（建议 3.12/3.13）、PowerShell 7.4+、.NET 8 Desktop Runtime x64、SpineViewer v0.16.34 标准 Windows zip。Python 依赖见 [requirements.txt](hochan-desktop-pet/requirements.txt)。Windows 自带 PowerShell 5.1 用于可选 Hook 与自启动。

详细安装入口和命令在制作此工作区的 skill 的 references/windows-tools.md 中。prepare_tools.ps1 可校验并展开固定版本 Viewer、创建本机 Python 环境并安装依赖；不安装系统工具、Hook 或自启动。

## 素材与构建

将一个 .skel 或 Spine .json、同 basename 的 .atlas 和全部贴图放 source/spine；保留 atlas 引用的相对路径。同 basename 不同时放两种骨骼格式。

从此工作区根目录运行：

```powershell
& '.\.tools\SpineViewer-v0.16.34\SpineViewerCLI.exe' query '.\source\spine\134731.skel' --animation
& '.\hochan-desktop-pet\.venv\Scripts\python.exe' '.\hochan-desktop-pet\tools\build_skin.py' --character ho-chan
& '.\hochan-desktop-pet\preview-hochan.cmd' --character ho-chan
```

上述用于ホウオウ模型 134731，角色 id 为 ho-chan。139031 使用 kyouka-gothic。只有一个模型只构建对应角色，未构建配置在菜单中禁用。新角色先配置 characters/<id>/character.json 与 skin.json，再按真实动画映射构建。

构建不依赖 source/reference-frames 的旧 manifest。所有生产帧按统一坐标生成，包含高清 WebP、逐帧掌心、四边头像及资源清单。

## 使用与交付

详见 [应用说明](hochan-desktop-pet/README.md)、[角色配置](hochan-desktop-pet/characters/README.md)、[架构](docs/architecture.md)、[目录](docs/project-layout.md)。

start-hochan.cmd 正式启动，preview-hochan.cmd 使用独立状态并关闭真实观察器。运行已构建桌宠只需本机 Python 环境和运行依赖。复制到其他电脑后重新创建 .venv，不复制原电脑的状态、虚拟环境或启动项。源码交付包含运行代码、生产 assets、配置和许可；单文件 exe 打包另行处理。

本模板保留原项目验收脚本，部分要求原两套角色资源齐全，不应直接对缺素材模板运行全套。模板移植只做静态检查，未重新进行环境复现或运行验收。
