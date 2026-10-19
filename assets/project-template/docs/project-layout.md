# 目录约定

- .tools/SpineViewer-v0.16.34：构建工具，需下载，运行无需携带。
- source/spine：用户提供的骨骼、atlas 与贴图。
- source/reference-frames：可选原始研究导出，生产构建不依赖它。
- hochan-desktop-pet：独立应用源码、角色配置及启动入口。
- hochan-desktop-pet/assets：effects 是附带中性效果；characters 由素材构建生成。
- hochan-desktop-pet/tools：构建、掌心导出、回归与性能工具。部分回归依赖两套参考角色齐全。
- hochan-desktop-pet/preview：实际制作时生成的预览，不包含在模板中。
- hochan-desktop-pet/build、state、.venv：本次工作区产物和本机运行状态，不作为分享模板。

模板中的配置文件并非已构建角色包。先准备工具和源素材，再完整构建对应角色。不要删除 source 来解决构建缺素材错误，也不要复制其他电脑的 .venv 或 Codex 状态。
