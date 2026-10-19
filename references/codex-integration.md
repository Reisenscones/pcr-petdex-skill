# 可选 Codex 联动与自启动

先让预览正常，再集成实际客户端。以下是模板的实现和配置流程；未来客户端变更时，以 [OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks) 核对事件、配置入口、信任和权限返回格式。2026-10-19 查阅的官方说明要求对非托管 Hook 的具体定义审核并信任，CLI 入口为 `/hooks`；定义改变后需重新审核。不得替用户直接写入信任记录。

## 事件链路

```text
Codex 生命周期
  → Windows PowerShell Hook（JSON stdin）
  → 项目 state 中的事件/权限 IPC
  → 后台观察器回传事件
  → GUI 状态机与任务关系
  → 对应角色动作、子角色、权限气泡
```

| 事件 | 模板行为 |
| --- | --- |
| SessionStart / SessionEnd | 初始化/收束会话，空闲 |
| UserPromptSubmit | 思考 reading |
| PreToolUse / PostToolUse | 工具 working |
| PreCompact | packing_XX 完整动作随机播放 |
| PostCompact / Stop | 庆祝一次后待机 |
| Interrupt | 中断姿态 |
| PermissionRequest | question 与允许/拒绝气泡 |
| SubagentStart / SubagentStop | 增加或结束对应子角色 |

只读观察器从本机已有 Codex 生命周期信息补充活动与完成。普通 task_started 不能当成工具调用，旧轮次不能覆盖新轮次。只读观察与 Hook 事件仍需去重和排序，不能简单让后到文件总获胜。

## 安装 Hook

用户要求实际联动时，在生成的应用目录运行：

```powershell
Set-Location -LiteralPath 'D:\SpinePet\hochan-desktop-pet'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-hooks.ps1'
```

默认写 `$env:CODEX_HOME/hooks.json`，未设置时为用户 .codex/hooks.json；只注册当前项目 hooks/codex-hochan-hook.ps1 的十二个事件。安装前备份，保留其他配置与 Hook，重复安装不累加，移除只删匹配当前入口的处理器。该安装器可按需启用 hooks 功能，不安装自启动。

双击 review-hooks.cmd 打开可用的 Codex CLI，在 `/hooks` 中检查并信任指向本项目的定义，再新开会话或完整重启 Codex Desktop。CLI 不可用时先找到当前客户端提供的审查入口，不把“配置写成功”当作“联动已启用”。启动 start-hochan.cmd，在真实任务中观察事件；客户端没有暴露某事件时应说明该能力尚未接通。

源码中 Hook 文件保留 UTF-8 BOM，以兼容 PowerShell 5.1 的中文解析。仅通知事件写本地状态并返回空 JSON，不调用模型、不注入上下文。

权限请求读取新鲜的 pcr-heartbeat.json，创建 request 文件；桌宠收到对应轮次后显示气泡，只有用户点击才返回 allow 或 deny。桌宠未运行时把决定交回 Codex 原有确认流程。不能因为等待超时、气泡不可见或正在制作 skill 而默认批准。正常工具调用本就无需审批时，不应期待出现权限气泡。

卸载当前项目 Hook：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-hooks.ps1' -Remove
```

移动项目先移除旧路径注册，换位置后再安装与审查。不要把旧电脑 hooks.json 整体复制到新电脑。

## 随 Codex 启动

仅在用户需要时：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-codex-autostart.ps1'
```

此安装器创建当前用户 Startup 下的快捷方式，启动无控制台的 codex_autostart.py。每三秒检查真实 Codex 桌面主进程，排除普通 ChatGPT、CLI/服务和 renderer；应用更新后路径需按识别规则继续匹配。

检测到 Codex 后拉起正式桌宠，已运行不重复拉起。用户手动退出后，本次应用生命周期内不再重启；下一次打开 Codex 才启动。关闭 Codex 保留桌宠。

从 Codex 内启动后台监测器时，模板通过 WMI 加 CREATE_BREAKAWAY_FROM_JOB 脱离调用者作业；不能直接改成普通 Start-Process，否则 Codex 退出可能连带回收监测器与桌宠。窗口隐藏，日志与心跳写项目 state。

关闭自启动：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-codex-autostart.ps1' -Remove
```

这只关闭此模板对应监测器和启动入口，保留当前桌宠及 Hook。模板沿用原应用名与固定快捷方式名，同电脑默认只启用一个此类自启动；需要多个独立发行版时，应同时命名空间化快捷方式、进程单例和安装器识别规则，避免互相覆盖。
