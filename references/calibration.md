# 画面、时间轴和掌心校准

## 固定视区

参考逻辑画布是 640×640，骨骼根在 `(410,570)`；Spine 源坐标通过下式转换为逻辑坐标：

```text
pixel_x = 320 + (world_x - center_x) * scale
pixel_y = 320 + (center_y - world_y) * scale
```

参考参数为 `center_x=-225, center_y=625, scale=0.4, supersampling=3`。世界原点 `(0,0)` 正好映射到 `(410,570)`。实际以 1920×1920、视角缩放 1.2 导出，再存高清裁切帧；逻辑坐标仍是 640 的单位。

**同素材复刻保留这些参数。** 新模型先检查根骨位置和全动作可见边界；需要改变比例时，在保持根骨映射到 `(410,570)` 的条件下重新算 view center。例如根骨 `(root_x,root_y)` 时：

```text
center_x = root_x - (410-320)/scale
center_y = root_y + (570-320)/scale
```

不要仅改 body_anchor：构建器会检查该值，镜像、气泡和屏幕几何也有对应约定。需要不同原点时必须一起修改运行几何，属于框架调整。

所有动作共用 view。自动 bounds 会让每个动作得到不同画布与基线，后续再逐帧裁切/等高缩放会产生站立位置漂移。生产资源可裁掉透明像素，但必须通过清单的 `hires.origin` 恢复原坐标，这和逐帧重新居中不同。

## 宽动作与下扩画布

逐帧检查透明边界；构建器在可见边界触及画布边缘或整帧透明时会报错。先判定是否真实越界，必要时扩大视野并统一重建，不能只把报错检查删掉。

模板支持 `render_size:[640,H]`，`640 <= H <=1280`，仅向下补透明空间。例如哥特角色伞落地用 `[640,704]`。扩高 `delta=H-640` 时，导出视角调整为：

```text
export_center_y = center_y - delta/(2*scale)
export_width = 640*supersampling
export_height = H*supersampling
```

因此原画布左上角和骨骼原点不变。不要将 640×704 又压回 640×640；子角色也保持相同比例。扩高仍裁切左右/上方时，统一降低 scale，并按上式保持原点；不同源动作本来有根骨位移时应保留有意义的位移，不靠每帧自动对齐消除。

## 时间轴和拼接

- 每个源动作时长通过 CLI query 获取，配置的 duration_seconds 必须与单段或 sequence 总和相符。
- 60 FPS 导出不等于改变动作速度。整数 duration_ms 通过相邻累计时间取差来分配，总和保持一致。
- 清单 `timing:uniform_segments` 和 segments 中的 frame_count/duration_ms 让运行时按连续时间均匀选帧；不能仅用累计的 16/17 ms 做 60Hz 下标。
- 循环动作删除重复/完整时长端点，避免末帧和下一循环首帧停顿。单次动作保留收尾。CLI 的 drop-last-frame 处理不完整末帧，构建器还会判断实际完整时长端点，两者不能混为一谈。
- sequence 每段独立导出后按顺序拼接。仅在确认中间末帧会复位为待机且导致闪帧时用 drop_join_endpoints；不要删掉所有连接处末帧。
- 压缩随机候选来自实际 packing_XX 键，别名不参与加权。每个动作完整播放后再选下一段，允许连续选到相同动作。

## 手掌逐帧坐标

悬浮动作名由 `animations.left.animation` 指定，目前掌心导出支持单个悬浮动画，不支持把 left 设成 sequence。参考配置：

```json
"drag_anchor": {"slot":"handB", "palm_offset":[24.0,7.5]}
```

`export_hand_anchors.ps1` 每帧读取该槽的 region attachment 八个 Offset 值，求局部四角均值，加掌心局部偏移，再用槽所在骨骼矩阵转换到世界坐标，最后按固定视区转成逻辑像素：

```text
local = average(attachment.Offset vertices) + palm_offset
world_x = bone.WorldX + bone.A*local_x + bone.B*local_y
world_y = bone.WorldY + bone.C*local_x + bone.D*local_y
```

槽名 handB 与 `[24,7.5]` 是原角色的实测值。更换模型先通过骨架检查选择实际被鼠标抓住的手；在输出帧上画坐标十字或放大观察，调整偏移直至落在掌心，检查整个动作循环，不只首帧。偏移沿手部局部坐标，不能当作屏幕固定偏移。

若槽不存在、帧中没有附件或附件是 mesh，停止用当前公式；检查实际 attachment 类型。可选择可追踪的 region 槽，或扩展导出器从网格/明确的骨骼局部点取世界坐标，并在完整动作中验证。只写一个固定屏幕点不能复现掌心锁定。

## 运行时拖动约束

1. `drag_anchor` 是与导出动画相同采样率、相同时间点的逐帧坐标，数量严格等于 left 帧数。
2. 悬浮画面围绕首帧手掌补偿：`hand_lock_offset = first_anchor-current_anchor`，镜像时 x 偏移反号。按亚像素精度处理，避免整数取整造成鼠标不动而窗口抖动。
3. 镜像绕根骨 x=410，像素中心坐标公式是 `x'=639-x+180`。高精度裁切图通过对应镜像规则恢复原点，不能简单将裁切图放回原 x。
4. 物理坐标比例是 `monitor_DPI/96 * size_percent/100`，窗口左上角是 `round(cursor-anchor*ratio)`。只缩角色、不缩掌心和命中区域会产生 DPI 偏差。
5. 拖动首帧预热；解码与缩放不在鼠标消息里完成。鼠标移动时用已显示帧的坐标，同时提交已显示位图和新窗口位置，不能先 SetWindowPos 再换帧。
6. 反向移动超过 12 逻辑像素并持续 60ms 才转向，减少手部轻微回摆的抖动。
7. 松手先恢复当前任务动作，按该角色可见 alpha 边界中心及手动偏移定位，并在同一次 UpdateLayeredWindow 提交位置与首帧。参考 `visible_frame_center` 保留向左/右约 ±43 和 y=30 的实测补偿；换角色时需根据手感校准，这不是所有模型通用的常数。

## 头像与清晰度

portrait_crop 使用 idle 帧的逻辑坐标；原主角色缺省 `[365,392,458,474]`，哥特角色 `[356,389,466,480]`。裁切头部后生成圆形头像及四张 68×68 边缘图。头像必须处在屏幕边缘实际露出的窄条内，不能只把图放在隐藏画布中心。

缩放先转 Pillow 的 RGBa 预乘模式再 LANCZOS，转回 RGBA。上传 Win32 前再转换为预乘 BGRA；区分这些处理阶段，避免透明边缘黑边/白边或重复预乘。保留 3 倍无损 WebP，放大时采样高清资源，不放大已缩小的逻辑帧。不同帧裁切图缩放要锚定同一全局采样网格，否则小数 DPI 下纹理会轻微游动。
