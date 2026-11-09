# Spine Studio

Spine Studio 是一个面向 Windows 的 Spine 资源预览与导出工具。它可以扫描本地 Spine 资源目录，预览骨骼动画，编辑导出时间线，并将动画导出为图片、视频或动图。

## 功能

- 扫描本地目录中的 `.atlas`、`.skel`、`.skel.json` 和 UnityFS 资源
- 支持 Spine 3.5、3.6、3.7、3.8、4.0、4.1、4.2、4.3
- 预览动画、皮肤、插槽和附件
- 编辑导出片段、帧率、画布、缩放、位置、背景和透明度
- 导出 PNG、MP4、MKV、WebM、MOV、GIF、APNG、WebP
- 支持导出队列和项目自动保存
- 使用 OpenGL 加速预览和渲染

## 快速运行

要求 Windows 和 Python 3.10 或更新版本。

直接双击：

```text
run_source.bat
```

首次运行时，脚本会在以下位置创建独立的源码运行环境并安装依赖：

```text
%LOCALAPPDATA%\SpineStudioV2\source-env
```

这个运行环境不写入项目目录，也不需要先构建 EXE。依赖清单见 [`requirements.txt`](requirements.txt)。

也可以手动运行：

```powershell
py -3 -m pip install -r requirements.txt
py -3 main.py
```

## 使用说明

1. 启动程序。
2. 在资源文件夹界面添加包含 Spine 资源的目录。
3. 选择角色、皮肤和动画。
4. 将动画加入时间线。
5. 在导出面板设置格式、画布、帧率和输出选项。
6. 执行单次导出或加入导出队列。

项目不包含任何游戏角色、贴图、骨架或其他样例资源。请只导入你有权使用的资源。

## 目录结构

```text
app/                       Qt 界面、状态管理和导出逻辑
spine_core/                Spine 数据加载与原生运行库封装
tools/                     UnityFS Spine 读取工具
native/spine-runtimes-4.1/ Spine Runtime 4.1 源码和构建文件
lib/                       已编译的 Spine Runtime DLL
assets/                    FFmpeg、Gifsicle、字体和程序图标
main.py                    程序入口
run_source.bat             源码启动脚本
requirements.txt           Python 依赖
```

## 从源码构建

源码运行不需要构建。需要发布 Windows EXE 时，可以使用：

```text
build_onefile.bat
```

PyInstaller 配置位于 `spine_studio.spec` 和 `spine_studio_onefile.spec`。原生 Spine Runtime 的构建脚本位于 `build_spine41.ps1` 和 `native/build/`；这些脚本中的 Visual Studio 路径可能需要根据本机安装位置调整。

## 数据与隐私

程序的设置、自动保存、队列和 UnityFS 缓存默认写入：

```text
%LOCALAPPDATA%\SpineStudioV2
```

请不要把个人资源、导出结果、日志、本机路径或运行环境目录提交到公开仓库。

## 许可证

项目自身的许可证见 [`LICENSE`](LICENSE)。

Spine Runtime 和相关集成代码受单独许可证约束，请同时阅读：

- [`LICENSE-SPINE.txt`](LICENSE-SPINE.txt)
- [`LICENSE-renpy-spine.txt`](LICENSE-renpy-spine.txt)
- [`NOTICE`](NOTICE)

第三方依赖仍由各自的许可证管理。
