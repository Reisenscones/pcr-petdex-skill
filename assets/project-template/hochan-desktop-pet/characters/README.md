# 添加与切换角色

右键桌宠 → **切换角色**：选择“ホウオウ”或“キョウカ（ゴシック）”。选择立即应用到主角色、子角色和四边头像，并保存在当前状态目录的 `pet-settings.json`；重启后继续使用。显示大小和任务状态保留。拖动或边缘过渡期间暂不可切换。

本目录每个子目录的 `character.json` 注册一个角色。菜单每次打开都会重新扫描，新增角色不需要修改 Python 菜单代码。未完成构建的角色会显示为禁用状态；语法错误或尚未写完的配置不会影响其他角色。

## 添加同来源的 Spine 角色

1. 将一个 `.skel` 或 Spine `.json` 骨骼、同 basename 的 `.atlas` 和 atlas 引用的全部贴图放入工作区 `source/spine/`；贴图保留 atlas 内的相对路径，不要求与骨骼同名。同 basename 不要同时放两种骨骼格式。
2. 在工作区根目录运行（替换 id、名称和模型文件名）：

```powershell
.\hochan-desktop-pet\.venv\Scripts\python.exe .\hochan-desktop-pet\tools\add_character.py --id new-character --name "新角色" --model 123456 --source-url "素材实际来源" --copyright "素材实际版权声明"
.\hochan-desktop-pet\.venv\Scripts\python.exe .\hochan-desktop-pet\tools\build_skin.py --character new-character
```

脚手架使用“ホウオウ”的配置作为模板，读取新模型的真实动画名和时长，自动匹配通用动作以及同名后缀的庆祝、技能动作。无法唯一匹配时会报错，不会猜测覆盖已有角色。可通过 `--template <角色 id>` 使用其他已有角色作为模板。

如果动画命名无法自动匹配，在新角色目录中创建 `character.json`，将参考角色实际引用的配方复制为新目录的 `skin.json`。修改注册文件的 `id`、`name`、`model`、`asset_dir`、`source_url`、`copyright`，并设置 `skin: "skin.json"`；修改新配方的 `name`、`animation_prefix` 和动作映射。Ho-chan 配方位于应用根目录 `skin.json`，不能只复制其注册目录后继续引用 `../../skin.json`，否则会修改共享参考配方。

3. 检查新目录中的 `skin.json`。模型的武器长度和动作范围不同，自动映射后仍需逐帧检查；`animations` 可选择更合适的动作，`portrait_crop` 配置头像裁切范围，`drag_anchor` 配置手掌骨骼与局部偏移。
4. 构建成功后重新打开“切换角色”菜单即可选择。也可用 `start-hochan.cmd --character new-character` 或 `preview-hochan.cmd --character new-character` 启动。

当前角色均使用 640×640 的逻辑坐标基准、骨骼原点 `(410, 570)`、3 倍分辨率导出和预乘透明度缩放。`skin.json` 的 `fps: 60` 控制从 Spine 原生采样的帧率，缺省为 30，动作总时长保持不变；掌心坐标按同一帧率导出。可用 `render_size` 向下扩展透明画布，骨骼原点、显示尺寸和 UI 坐标不变。新增角色需保持相同逻辑坐标约定；不要逐帧单独居中或等高缩放。悬浮动画必须包含导出的逐帧掌心坐标。

原两套角色均构建后，可用 `tools/verify_characters.py` 检查帧、高清素材、掌心坐标与实时切换；它包含参考角色的固定断言。仅构建一个新角色时，使用 `tools/verify_runtime.py --character <id>` 验证该角色的完整窗口流程。性能测量支持 `tools/profile_runtime.py --character <id> --size-percent 150`。

## 配置与输出

`character.json` 指定稳定的英文 `id`、显示 `name`、源文件 `model`、相对配置文件 `skin` 和相对于桌宠目录的 `asset_dir`。`order` 控制菜单顺序；`source_url` 和 `copyright` 记录素材归属。

所有角色资源统一放在 `assets/characters/`，每个角色目录中的 `animation-resources/` 保存动画，同级 `edge-tail/` 保存头像。ホウオウ（模型 `134731`）的配置目录、内部 id 和资源目录统一为 `ho-chan`；キョウカ（ゴシック，模型 `139031`）统一为 `kyouka-gothic`。这是从零创建项目的模板，不沿用原项目中与角色名不符的旧 id。

`skin.json` 的 `animation_prefix` 决定 WebP 序列目录名：ホウオウ使用 `hochan_<动作键>`，哥特キョウカ使用 `kyouka-gothic_<动作键>`，例如 `kyouka-gothic_wake`。新角色的脚手架会将前缀设为自己的 `id`，构建时按此前缀输出。新角色构建报告为 `build/skin-report-<id>.json`；原角色仍使用 `build/skin-report.json`。

生产包只保存 3 倍无损 WebP，格式 v2 的每帧用 `hires.file` 引用高清裁切图，普通逻辑帧由运行时按需生成。`logical_corrections` 保存与原普通帧缩放舍入有关的少量像素修正。重复图片共用文件，但每帧仍保留自己的时长、原点和掌心坐标。构建脚本为新图片使用带内容摘要的文件名，局部重建不会覆盖其他动作仍在引用的旧图片。加载器同时支持旧版带普通 PNG 的 v1 包。

压缩动作菜单按编号显示。ホウオウ保留“压缩 1～4”；キョウカ（ゴシック）只使用三组：

1. 压缩 1：`139001_skill2`。
2. 压缩 2：`139001_skill1` 接 `139001_skill1_1`。
3. 压缩 3：`139001_skill1` 接 `139001_skill1_2`。

拼接动作在 `skin.json` 中以 `sequence` 数组按顺序声明，替代单段的 `animation` 字段；`duration_seconds` 为各段时长之和。`loop: false` 保留单次动作末帧；若中间片段的最后一个采样点复位为待机姿势，设置 `drop_join_endpoints: true` 去掉拼接处的该端点。当前两组 `skill1` 拼接均使用此设置，60 FPS 导出的三组压缩动作均为 161 帧、2667 ms。完整源 PNG 不修改。构建时使用统一视角渲染并依序拼接 PNG，同时保留 3 倍素材；清单的 `segments` 记录各段来源、起始帧、原始及保留帧数、端点处理和时长，`timing: uniform_segments` 保持各段内均匀采样，避免整数毫秒时长量化造成重帧。运行时按实际配置的压缩动作数量随机选择，兼容别名不参与重复抽选。以后增加压缩动作只需添加 `packing_XX` 配置并构建。

`139001_skill1_1` 的伞会降到默认画布之外。第二个角色使用 `render_size: [640, 704]`，向下增加 64 像素透明空间，所有动作继续使用与待机相同的视角和人物原点；预览开始、结束时不再通过上移人物避开裁切。旧的 640×640 PNG 在解码时仅向下补透明，高清帧保留其逻辑原点。子角色沿用同样的固定缩放比例，不将扩展后的画布压回正方形。完整源序列仍保存在工作区 `source/reference-frames/139031/`。`tools/verify_compaction.py` 可验证帧数、接缝、站立高度和菜单数量，`tools/verify_characters.py` 验证原生预览与自动返回时的窗口位置。

角色素材来自 [redive.estertion.win](https://redive.estertion.win/)，版权归 Cygames 所有（© Cygames）。使用其他来源的素材时，通过 `--source-url`、`--copyright` 记录实际来源，并同步维护素材声明。
