# 预览文件

| 文件 | 用途 |
| --- | --- |
| `all-states.png` | 全部独立动作总览 |
| `four-states.png` / `four-states.webp` | 待机、悬浮、思考、工具执行对比 |
| `packing-states.png` | 压缩动作展示 |
| `edge-portraits.png` | 四边收纳入口头像 |
| `hi-dpi-comparison.png` | 放大清晰度修复前后对比 |
| `blur-before-*.png` | 清晰度对比使用的修复前原帧 |
| `native-*.png` | 真实程序运行期间，通过实际合成函数保存的状态画面 |
| `characters/<角色 id>/all-states.png` | 各角色完整动作总览 |
| `characters/<角色 id>/packing-states.png` | 按编号排列的压缩动作帧总览，`tools/verify_compaction.py` 刷新 |
| `characters/character-comparison.png` | 两个角色及边缘头像对比 |
| `characters/<角色 id>/native-*.png` | 扩展角色的窗口流程合成画面 |

`native-*.png` 是程序合成画面，并非桌面截图。`tools/verify_skin.py` 可刷新动作总览和四状态动画；`tools/verify_runtime.py` 可刷新原生窗口流程中的状态画面。
