# Windows 桌宠

准备与素材构建见 [工作区说明](../README.md)。此模板不包含角色图片，需先完成构建。

## 启动

- start-hochan.cmd：正式运行，观察本机已有 Codex 信息；无 Codex 也可独立使用。
- preview-hochan.cmd：独立状态目录、关闭真实观察器，默认待机。右键动作预览可切换。
- 启动器可传 `--character ho-chan`、`--character kyouka-gothic` 或新角色 id。
- 调试可运行 `.venv\Scripts\python.exe hochan_pet.py --no-codex-observer --preview idle --character <id>`；日常启动器使用 pythonw 隐藏控制台。启动错误看 startup-error.log。

新电脑先安装 Python 3.11+ x64，在本目录执行 setup.ps1 创建本机虚拟环境并安装 requirements.txt。完整构建还需要工作区说明所列工具。

## 交互

左键按住拖动，掌心贴着鼠标；左右反向自动翻转。松手恢复当前任务动作。触及四边可收纳为头像，展开恢复角色。右键菜单为设置、动作预览、切换角色、日志、关于、退出。

设置包括 75/100/125/150% 大小、隐藏任务气泡栏及随 Codex 启动。大小与角色选择保存到当前状态目录 pet-settings.json。隐藏任务栏不隐藏权限气泡。休息仅空闲时可进入，点击挥手唤醒。手动预览可从菜单恢复自动状态联动。

## 角色与素材

参考ホウオウ模型 134731 的注册 id 是 ho-chan，主配方为 skin.json。哥特キョウカ模型 139031 注册为 kyouka-gothic。新角色入口见 [角色说明](characters/README.md)。运行资源在 assets/characters/<资源目录>/，临时构建在 build/，正式状态在 state/。

## 可选 Codex 集成

需要任务联动时，在本目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-hooks.ps1'
```

review-hooks.cmd 打开 CLI 后用 `/hooks` 检查并信任当前项目定义，再新开会话或重启客户端。当前机制参考 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。Hook 安装不等于信任完成；它保留其他 Hook，按当前绝对路径注册，移动目录需移除后重新安装。

需要随 Codex 启动时单独执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\install-codex-autostart.ps1'
```

两个脚本均可加 -Remove 移除各自配置。关闭自启动保留当前桌宠，移除 Hook 不删除角色素材。此模板沿用同一个 Startup 快捷方式名，同电脑默认只启用一个此类监测器。

## 来源

软件与原作者信息见 [LICENSE](LICENSE)、[UPSTREAM.md](UPSTREAM.md)。角色素材及中性效果归属见 [ASSET-NOTICE.md](ASSET-NOTICE.md)。本模板未附角色图片，新增角色按实际来源填写配置。模板未重新执行环境或窗口验收。
