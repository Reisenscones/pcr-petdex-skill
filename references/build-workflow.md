# 从素材到可运行桌宠

## 目录与素材

```text
SpinePet/
  .tools/SpineViewer-v0.16.34/SpineViewerCLI.exe
  source/spine/                    用户骨骼、atlas、全部贴图
  source/reference-frames/         可选研究导出，并非构建依赖
  hochan-desktop-pet/
    .venv/                        在目标电脑创建
    skin.json                     ホウオウ配方
    characters/*/character.json    注册描述
    characters/*/skin.json         其他配方
    tools/                        素材构建、掌心导出、验收工具
    assets/characters/             构建后的运行素材
    assets/effects/                附带中性庆祝效果
    hooks/, *.py, *.cmd, *.ps1     运行与可选集成
```

先按 [Windows 工具](windows-tools.md) 创建项目与依赖。每个模型需一个 .skel 或 Spine .json，以及同 basename 的 .atlas。.spine 编辑器工程不能直接改后缀当骨骼。atlas 所有贴图页必须可解析，页名不必与模型同名。骨骼和 atlas 放 source/spine 根目录，贴图按 atlas 相对路径组织。

## 查询真实动画

```powershell
Set-Location -LiteralPath 'D:\SpinePet'
& '.\.tools\SpineViewer-v0.16.34\SpineViewerCLI.exe' query '.\source\spine\134731.skel' --animation
```

JSON 换成实际 .json。输出 TSV 是动画名和秒数，保存供映射核对；构建器每次重新查询，不依赖历史 manifest。同 basename 同时留 .skel 和 .json 会被拒绝。

观察待机、拖动、庆祝、技能再选择动作。研究时可用自动 bounds 导帧，生产必须统一 fixed view。无需先导出模型所有动作。

## 同素材复刻

提供 134731 全部素材时直接用原配方：

```powershell
& '.\hochan-desktop-pet\.venv\Scripts\python.exe' '.\hochan-desktop-pet\tools\build_skin.py' --character ho-chan
```

模型 134731 的角色 id 为 ho-chan；模型 139031 的角色 id 为 kyouka-gothic。提供后者时：

```powershell
& '.\hochan-desktop-pet\.venv\Scripts\python.exe' '.\hochan-desktop-pet\tools\build_skin.py' --character kyouka-gothic
```

只有一个模型只运行对应命令，两套都有则分别运行。模板未内置角色图片；未构建角色菜单禁用。启动先选记忆中有效角色，再选已构建参考主角色或其他首个可用角色。

## 新角色注册

相同动画体系可用脚手架：

```powershell
& '.\hochan-desktop-pet\.venv\Scripts\python.exe' '.\hochan-desktop-pet\tools\add_character.py' --id new-pet --name '新角色' --model 123456 --template ho-chan --source-url '素材实际来源' --copyright '素材实际版权声明'
```

--model 是骨骼 basename，不带扩展名。工具按真实时长和唯一后缀匹配；不唯一则停止，不覆盖已有角色。--template kyouka-gothic 可用另一配方，仍需人工观察。

命名体系不同时，手工建立 characters/new-pet/character.json，复制参考配方到同级 skin.json 再编辑：

```json
{
  "id": "new-pet",
  "name": "新角色",
  "model": "123456",
  "skin": "skin.json",
  "asset_dir": "assets/characters/new-pet/animation-resources",
  "order": 2,
  "source_url": "素材实际来源",
  "copyright": "素材实际版权声明"
}
```

| 运行键 | 行为 | 原主角色来源 |
| --- | --- | --- |
| idle | 空闲循环 | 07_idle |
| left | 双向拖动共用悬浮动作 | 000000_balloon_flying_loop |
| reading | 思考 | 07_walk |
| working | 工具执行 | 07_run |
| jump | 庆祝一次回待机 | 134701_joyResult，loop false |
| question | 等待确认/中断 | 000000_dear_idol |
| packing_01... | 压缩中完整动作随机播放，可重复 | 两种 standBy、两种技能 |
| bow | 空闲随机单次动作 | 000000_stamina_karin_ojigi |
| sleep_body | 休息循环 | 000000_noWeapon_idle |
| wake | 点击唤醒一次 | 000000_friend_hightouch |
| edge_reveal | 边缘展开一次 | 000000_dear_smile |
| sleep_entry、click_feedback | 复用休息和唤醒 | aliases 指向对应键 |

至少一个 packing_XX。配置使用真实动画名与总时长；缺动作明确替代语义或补素材，不虚构读书/睡卧动画。animation_prefix 改为自己的稳定英文 id。

单段用 animation、duration_seconds、label、可选 loop。拼接用 sequence 替代 animation，时长为各段之和。哥特角色压缩为 139001_skill2、139001_skill1 + 139001_skill1_1、139001_skill1 + 139001_skill1_2；后两项 drop_join_endpoints:true，画布 [640,704]。这是特定模型处理，不是通用要求。

## 构建

按 [画面与拖动校准](calibration.md) 确认视区和掌心后：

```powershell
& '.\hochan-desktop-pet\.venv\Scripts\python.exe' '.\hochan-desktop-pet\tools\build_skin.py' --character new-pet
```

构建依次查询动画/时长、按固定视区和 60 FPS/3 倍分辨率导出、处理循环与拼接终点、记录分段采样、检查透明边界、无损 WebP 裁切去重、导出逐帧掌心、生成别名与四边头像、写 v2 清单。原始 PNG 留在 build/skin-*，不参与运行。

首轮完整构建，之后可加 --only left jump。视角、FPS、画布改变后完整重建，不混旧帧。--output-dir 是高级 staging 功能，不替代角色注册。

生产输出为角色 animation-resources 下的清单与 WebP，同级 edge-tail 下四张头像。segments、hires.origin、logical_corrections、drag_anchor 都有运行作用，不删除。

## 启动和交付

```powershell
& '.\hochan-desktop-pet\preview-hochan.cmd' --character new-pet
```

预览用独立状态目录并关闭 Codex 观察器，右键切动作；正式运行双击 start-hochan.cmd。无 Codex 也能独立使用。调试用 .venv/Scripts/python.exe hochan_pet.py ... 看异常，日常用 pythonw。

源码交付保留运行源码、配置、生产 assets、许可证与说明；不必交付原始素材、Viewer、build。其他电脑先创建本机 Python 环境、安装 requirements.txt。单文件 exe 打包属于额外需求，当前交付是可双击启动的源码目录。
