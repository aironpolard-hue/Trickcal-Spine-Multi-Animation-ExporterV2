# 贡献指南

感谢你为 Spine Studio 提交改进。

## 开始之前

- 请先阅读 `README.md`、`NOTICE` 和各第三方许可证文件。
- 不要提交游戏资源、个人文件、导出结果、日志、虚拟环境或构建产物。
- 不要提交 API Key、密码、令牌、私钥或包含本机用户名的调试输出。
- 提交前请检查新增文本文件中是否存在绝对路径和本机目录。

## 开发环境

推荐直接双击 `run_source.bat`。它会在用户本地创建源码运行环境。

也可以手动安装依赖：

```powershell
py -3 -m pip install -r requirements.txt
py -3 main.py
```

## 修改要求

- 保持现有 Python、Qt 和 Spine Runtime 结构，不要无关重构。
- 用户可见行为变更请同步更新 `README.md`。
- 新增第三方库时，请更新 `requirements.txt` 和 `NOTICE`。
- 不要把生成的 `build/`、`dist/`、`release/`、`native/out/` 或 `__pycache__/` 加入提交。
- 原生 Runtime 改动必须说明对应版本、构建方式和许可证影响。

## 提交前检查

```powershell
py -3 -m compileall app spine_core tools main.py
```

然后使用 `run_source.bat` 启动程序，至少手动检查程序能启动、资源目录可以添加、预览窗口可以显示。

提交信息应简洁描述改动内容。一个提交尽量只解决一个问题。
