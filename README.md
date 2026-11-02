# KMenu Manager

KMenu Manager 是一款基于 Python 和 PySide6 开发的 KDE 第三方软件菜单管理工具，面向 Arch Linux 和 KDE Plasma 6。

## 主要功能

- 扫描指定目录中的第三方 Linux 软件。
- 识别 AppImage 等应用程序并提取应用元数据和图标。
- 为第三方软件创建 KDE 应用菜单入口。
- 管理应用分类和菜单图标。
- 管理自定义扫描目录。
- 删除由本程序管理的菜单入口，不删除原始软件文件。
- 异步刷新 KDE 应用菜单缓存。

## 运行环境

- Linux x86_64
- KDE Plasma 6
- Python 3
- PySide6
- KDE `kbuildsycoca6` 命令

## 从源码运行

确保系统已安装 Python 3 和 PySide6。

进入项目目录：

```bash
cd ~/Projects/kmenu-manager
python -m kmenu_manager
cd ~/Projects/kmenu-manager && cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2026 MaochuanLi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
