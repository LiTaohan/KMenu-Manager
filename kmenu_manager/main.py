#!/usr/bin/env python3
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from .scan_dialog import ScanDialog
from .scanner import scan
from .menu_cache import MenuCacheRefresher

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QComboBox,
    QVBoxLayout, QHBoxLayout, QFormLayout, QMessageBox,
    QSplitter, QGroupBox, QLineEdit, QFileDialog,
    QDialog, QDialogButtonBox, QSizePolicy
)

HOME = Path.home()
MENU_DIR = HOME / ".local/share/applications"
CONFIG_DIR = HOME / ".config/app-menu-manager"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

CATEGORIES = [
    ("互联网", "Network;"),
    ("即时通讯", "Network;InstantMessaging;"),
    ("音频和视频", "AudioVideo;"),
    ("视频播放器", "AudioVideo;Video;"),
    ("音乐播放器", "AudioVideo;Audio;Player;"),
    ("开发", "Development;"),
    ("图形", "Graphics;"),
    ("游戏", "Game;"),
    ("办公", "Office;"),
    ("教育", "Education;"),
    ("科学", "Science;"),
    ("系统工具", "System;"),
    ("工具", "Utility;"),
    ("其他", "Other;"),
]


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(
        prefix="settings-", suffix=".tmp", dir=CONFIG_DIR
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
        os.replace(temp, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def read_desktop(path):
    data = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                data[key] = value
    except OSError:
        pass
    return data


def write_categories(path, categories):
    lines = path.read_text(encoding="utf-8").splitlines()
    output = []
    replaced = False

    for line in lines:
        if line.startswith("Categories="):
            output.append("Categories=" + categories)
            replaced = True
        else:
            output.append(line)

    if not replaced:
        output.append("Categories=" + categories)

    content = "\n".join(output) + "\n"
    fd, temp = tempfile.mkstemp(
        prefix="desktop-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def category_for(name, source="", generic="", comment=""):
    text = " ".join((name, source, generic, comment)).casefold()

    rules = [
        ("Network;InstantMessaging;", (
            "qq", "telegram", "wechat", "微信", "即时通讯",
            "discord", "messenger"
        )),
        ("Network;", (
            "flclash", "clash", "vpn", "proxy", "浏览器",
            "browser", "firefox", "chrome", "network"
        )),
        ("AudioVideo;Audio;Player;", (
            "voicefox", "music player", "音乐播放器",
            "音乐", "spotify", "音频播放器"
        )),
        ("AudioVideo;Video;", (
            "红果", "短剧", "video player", "视频播放器",
            "视频", "vlc", "mpv"
        )),
        ("Development;", (
            "vscode", "visual studio code", "pycharm",
            "开发", "ide", "developer"
        )),
        ("Graphics;", (
            "gimp", "krita", "blender", "inkscape",
            "图像", "绘图", "图片编辑"
        )),
        ("Game;", (
            "steam", "lutris", "游戏", "game"
        )),
        ("Office;", (
            "libreoffice", "office", "办公", "writer",
            "spreadsheet"
        )),
        ("Education;", (
            "education", "教育", "学习", "课程"
        )),
    ]

    for category, keywords in rules:
        if any(word in text for word in keywords):
            return category

    return "Utility;"


def category_label(value):
    for label, stored in CATEGORIES:
        if stored == value:
            return label
    return f"其他（{value}）"


class DirectoryDialog(QDialog):
    def __init__(self, directories, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫描目录管理")
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "配置以后扫描第三方软件时要检查的目录："
        ))

        self.list = QListWidget()
        for directory in directories:
            self.list.addItem(directory)
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        add_button = QPushButton("添加目录")
        remove_button = QPushButton("移除选中目录")
        add_button.clicked.connect(self.add_directory)
        remove_button.clicked.connect(self.remove_directory)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        layout.addLayout(buttons)

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def add_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择扫描目录")
        if path:
            existing = [
                self.list.item(i).text()
                for i in range(self.list.count())
            ]
            if path not in existing:
                self.list.addItem(path)

    def remove_directory(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def directories(self):
        return [
            self.list.item(i).text()
            for i in range(self.list.count())
        ]


class Manager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("第三方软件管理器")
        self.resize(960, 620)

        self.settings = load_settings()
        self.apps = []
        self.menu_cache = MenuCacheRefresher(self)
        self.menu_cache.refresh_finished.connect(
            self.on_menu_cache_refresh_finished
        )

        if not isinstance(self.settings.get("categories"), dict):
            self.settings["categories"] = {}

        if not isinstance(self.settings.get("scan_dirs"), list):
            self.settings["scan_dirs"] = [
                str(HOME / "Applications")
            ]

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        title = QLabel("第三方软件管理器")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "管理 KDE 开始菜单入口 · 支持分类记忆与软件搜索"
        )
        subtitle.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索软件名称……")
        self.search.textChanged.connect(self.filter_apps)
        layout.addWidget(self.search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.list_widget.currentRowChanged.connect(self.show_app)
        self.list_widget.itemSelectionChanged.connect(
            self.update_delete_button
        )
        splitter.addWidget(self.list_widget)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        group = QGroupBox("软件信息")
        form = QFormLayout(group)

        self.name_label = QLabel("请选择左侧软件")
        self.source_label = QLabel("—")
        self.source_label.setWordWrap(True)
        self.source_label.setMinimumWidth(0)
        self.source_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        self.exec_label = QLabel("—")
        self.exec_label.setWordWrap(True)
        self.exec_label.setMinimumWidth(0)
        self.exec_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )
        self.current_label = QLabel("—")

        self.category_combo = QComboBox()
        for label, value in CATEGORIES:
            self.category_combo.addItem(label, value)

        form.addRow("软件名称：", self.name_label)
        form.addRow("文件位置：", self.source_label)
        form.addRow("启动命令：", self.exec_label)
        form.addRow("当前分类：", self.current_label)
        form.addRow("设置分类：", self.category_combo)

        self.icon_preview = QLabel("暂无图标")
        self.icon_preview.setFixedSize(96, 96)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet(
            "border: 1px solid palette(mid); border-radius: 8px;"
        )
        form.addRow("当前图标：", self.icon_preview)

        panel_layout.addWidget(group)

        icon_buttons = QHBoxLayout()
        self.update_icon_button = QPushButton("更新为扫描图标")
        self.choose_icon_button = QPushButton("选择本地图标")
        self.reset_icon_button = QPushButton("恢复默认图标")

        self.update_icon_button.clicked.connect(self.update_scan_icon)
        self.choose_icon_button.clicked.connect(self.choose_local_icon)
        self.reset_icon_button.clicked.connect(self.reset_icon)

        icon_buttons.addWidget(self.update_icon_button)
        icon_buttons.addWidget(self.choose_icon_button)
        icon_buttons.addWidget(self.reset_icon_button)
        panel_layout.addLayout(icon_buttons)

        auto_button = QPushButton("根据软件信息推荐分类")
        auto_button.clicked.connect(self.suggest_category)
        panel_layout.addWidget(auto_button)

        panel_layout.addStretch()

        self.save_button = QPushButton("保存分类")
        self.save_button.clicked.connect(self.save_current)
        panel_layout.addWidget(self.save_button)

        splitter.addWidget(panel)
        splitter.setSizes([340, 600])

        bottom = QHBoxLayout()
        self.status_label = QLabel("准备就绪")

        scan_button = QPushButton("扫描软件")
        scan_button.clicked.connect(self.open_scan_dialog)
        bottom.addWidget(scan_button)

        directory_button = QPushButton("扫描目录管理")
        directory_button.clicked.connect(self.manage_directories)

        refresh_button = QPushButton("刷新列表")
        refresh_button.clicked.connect(self.refresh)

        self.delete_button = QPushButton("删除选中入口")
        self.delete_button.setEnabled(False)

        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(directory_button)
        bottom.addWidget(refresh_button)
        bottom.addWidget(self.delete_button)
        self.delete_button.clicked.connect(self.delete_selected_entries)
        layout.addLayout(bottom)

        self.refresh()

    def update_delete_button(self):
        selected = self.list_widget.selectedItems()
        self.delete_button.setEnabled(bool(selected))
        count = len(selected)
        self.delete_button.setText(
            f"删除选中入口（{count}）" if count else "删除选中入口"
        )

    def delete_selected_entries(self):
        selected = self.list_widget.selectedItems()
        if not selected:
            return

        apps = []
        for item in selected:
            row = self.list_widget.row(item)
            if 0 <= row < len(self.apps):
                apps.append(self.apps[row])

        if not apps:
            return

        names = "\\n".join(f"• {app['name']}" for app in apps)

        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除以下 {len(apps)} 个菜单入口吗？\\n\\n"
            f"{names}\\n\\n"
            "只删除菜单入口，不会删除原始软件文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        deleted = []
        errors = []

        for app in apps:
            desktop = app["path"]

            try:
                if desktop.parent.resolve() != MENU_DIR.resolve():
                    raise ValueError("入口不在应用菜单目录中")

                if not desktop.name.startswith("auto-") or desktop.suffix != ".desktop":
                    raise ValueError("不是受管理的菜单入口")

                data = read_desktop(desktop)
                if (
                    data.get("X-AutoManaged") != "true"
                    and data.get("X-AutoGenerated") != "true"
                ):
                    raise ValueError("该入口不属于 KMenu Manager")

                desktop.unlink()
                self.settings["categories"].pop(desktop.name, None)
                deleted.append(app["name"])

            except Exception as error:
                errors.append(f"{app['name']}：{error}")

        if deleted:
            try:
                save_settings(self.settings)
            except Exception as error:
                errors.append(f"保存分类设置失败：{error}")

            self.menu_cache.request_refresh()

            self.refresh()

        message = []
        if deleted:
            message.append("已删除入口：" + "、".join(deleted))
        if errors:
            message.append("发生以下问题：\\n" + "\\n".join(errors))

        QMessageBox.information(
            self, "删除结果", "\\n\\n".join(message) or "没有删除任何入口。"
        )

    def refresh(self):
        self.apps.clear()
        self.list_widget.clear()

        overrides = self.settings["categories"]

        for path in sorted(MENU_DIR.glob("auto-*.desktop")):
            data = read_desktop(path)

            if (
                data.get("X-AutoManaged") != "true"
                and data.get("X-AutoGenerated") != "true"
            ):
                continue

            name = data.get("Name", path.stem)
            source = data.get("X-AutoSource", "")
            generic = data.get("GenericName", "")
            comment = data.get("Comment", "")
            current = data.get("Categories", "Utility;")
            icon_value = data.get("Icon", "application-x-executable")

            manual = overrides.get(path.name)
            if manual:
                current = manual
                if data.get("Categories") != manual:
                    try:
                        write_categories(path, manual)
                    except OSError as error:
                        print(f"恢复分类失败：{error}")

            app = {
                "path": path,
                "name": name,
                "source": source,
                "exec": data.get("Exec", "未知"),
                "icon": icon_value,
                "generic": generic,
                "comment": comment,
                "categories": current,
            }
            self.apps.append(app)

            item = QListWidgetItem(QIcon(icon_value), name)
            item.setToolTip(source or str(path))
            self.list_widget.addItem(item)

        self.filter_apps()
        self.status_label.setText(
            f"已加载 {len(self.apps)} 个软件入口"
        )

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        else:
            self.show_app(-1)

    def filter_apps(self):
        query = self.search.text().strip().casefold()

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            item.setHidden(query not in item.text().casefold())

        visible = [
            row for row in range(self.list_widget.count())
            if not self.list_widget.item(row).isHidden()
        ]

        if visible and (
            self.list_widget.currentItem() is None
            or self.list_widget.currentItem().isHidden()
        ):
            self.list_widget.setCurrentRow(visible[0])

        self.status_label.setText(
            f"显示 {len(visible)} / {len(self.apps)} 个软件"
        )

    def show_app(self, index):
        valid = 0 <= index < len(self.apps)
        self.save_button.setEnabled(valid)
        self.category_combo.setEnabled(valid)

        if not valid:
            self.name_label.setText("请选择左侧软件")
            self.source_label.setText("—")
            self.exec_label.setText("—")
            self.current_label.setText("—")
            self.icon_preview.setPixmap(QPixmap())
            self.icon_preview.setText("暂无图标")
            self.update_icon_button.setEnabled(False)
            self.choose_icon_button.setEnabled(False)
            self.reset_icon_button.setEnabled(False)
            return

        app = self.apps[index]
        self.name_label.setText(app["name"])
        self.source_label.setText(app["source"] or "未知")
        self.exec_label.setText(app["exec"])
        self.current_label.setText(
            category_label(app["categories"])
        )

        icon_value = app.get("icon", "application-x-executable")
        icon = QIcon(str(icon_value))
        self.icon_preview.setPixmap(
            icon.pixmap(80, 80)
        )
        self.icon_preview.setText(
            "" if not icon.isNull() else "暂无图标"
        )

        self.update_icon_button.setEnabled(True)
        self.choose_icon_button.setEnabled(True)
        self.reset_icon_button.setEnabled(True)

        combo_index = self.category_combo.findData(
            app["categories"]
        )

        if combo_index < 0:
            self.category_combo.addItem(
                f"当前分类（{app['categories']}）",
                app["categories"]
            )
            combo_index = self.category_combo.count() - 1

        self.category_combo.setCurrentIndex(combo_index)

    def suggest_category(self):
        index = self.list_widget.currentRow()
        if not 0 <= index < len(self.apps):
            return

        app = self.apps[index]
        suggestion = category_for(
            app["name"], app["source"],
            app["generic"], app["comment"]
        )

        combo_index = self.category_combo.findData(suggestion)
        if combo_index >= 0:
            self.category_combo.setCurrentIndex(combo_index)

        self.status_label.setText(
            f"自动分类建议：{category_label(suggestion)}（尚未保存）"
        )

    def save_current(self):
        index = self.list_widget.currentRow()
        if not 0 <= index < len(self.apps):
            return

        app = self.apps[index]
        categories = self.category_combo.currentData()

        try:
            write_categories(app["path"], categories)

            self.settings["categories"][app["path"].name] = categories
            save_settings(self.settings)

            app["categories"] = categories
            self.current_label.setText(category_label(categories))

            self.menu_cache.request_refresh()

            self.status_label.setText(
                f"已保存：{app['name']} → {category_label(categories)}"
            )
            QMessageBox.information(
                self, "保存成功",
                f"{app['name']} 的分类已保存。\n"
                "手动分类优先于自动分类建议。"
            )
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))

    def write_icon(self, app, icon_value):
        path = app["path"]
        lines = path.read_text(encoding="utf-8").splitlines()
        output = []
        replaced = False

        for line in lines:
            if line.startswith("Icon="):
                output.append("Icon=" + str(icon_value))
                replaced = True
            else:
                output.append(line)

        if not replaced:
            output.append("Icon=" + str(icon_value))

        backup = path.with_suffix(path.suffix + ".icon-backup")
        if not backup.exists():
            import shutil
            shutil.copy2(path, backup)

        fd, temp = tempfile.mkstemp(
            prefix="desktop-icon-", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write("\n".join(output) + "\n")
            os.chmod(temp, 0o644)
            os.replace(temp, path)
        except Exception:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

        app["icon"] = str(icon_value)
        self.menu_cache.request_refresh()
        self.show_app(self.list_widget.currentRow())
        self.list_widget.currentItem().setIcon(QIcon(str(icon_value)))
        self.status_label.setText(f"已更新 {app['name']} 的图标")

    def update_scan_icon(self):
        index = self.list_widget.currentRow()
        if not 0 <= index < len(self.apps):
            return

        app = self.apps[index]
        source = app.get("source")
        if not source:
            QMessageBox.warning(self, "无法更新", "该入口没有记录软件路径。")
            return

        try:
            results, _, errors = scan(
                self.settings.get("scan_dirs", []), self.settings
            )
            target = Path(source).resolve()
            match = next(
                (
                    item for item in results
                    if Path(item.get("path", "")).resolve() == target
                ),
                None
            )
            icon = match.get("icon") if match else None

            if not icon or icon == "application-x-executable":
                QMessageBox.warning(
                    self, "没有可用图标",
                    "扫描器没有找到该软件的专属图标。"
                )
                return

            if not Path(str(icon)).is_file() and "/" in str(icon):
                QMessageBox.warning(
                    self, "图标不存在", f"找不到图标文件：\\n{icon}"
                )
                return

            answer = QMessageBox.question(
                self, "确认更新图标",
                f"将 {app['name']} 的菜单图标更新为扫描到的图标？",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.write_icon(app, icon)

        except Exception as error:
            QMessageBox.critical(self, "更新失败", str(error))

    def choose_local_icon(self):
        index = self.list_widget.currentRow()
        if not 0 <= index < len(self.apps):
            return

        filename, _ = QFileDialog.getOpenFileName(
            self, "选择软件图标", str(HOME),
            "图标文件 (*.png *.svg *.xpm *.ico);;所有文件 (*)"
        )
        if not filename:
            return

        answer = QMessageBox.question(
            self, "确认更换图标",
            f"将当前软件图标更换为：\n{filename} ？",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.write_icon(self.apps[index], filename)
        except Exception as error:
            QMessageBox.critical(self, "更换失败", str(error))

    def reset_icon(self):
        index = self.list_widget.currentRow()
        if not 0 <= index < len(self.apps):
            return

        answer = QMessageBox.question(
            self, "恢复默认图标",
            "确定将当前软件图标恢复为系统通用图标吗？",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.write_icon(
                self.apps[index], "application-x-executable"
            )
        except Exception as error:
            QMessageBox.critical(self, "恢复失败", str(error))

    def on_menu_cache_refresh_finished(self, success, error):
        if success:
            self.status_label.setText("KDE 菜单缓存已更新")
        else:
            self.status_label.setText("KDE 菜单缓存更新失败")
            QMessageBox.warning(
                self,
                "KDE 菜单缓存更新失败",
                error or "未知错误",
            )

    def open_scan_dialog(self):
        dialog = ScanDialog(
            self,
            self.settings,
            self.refresh,
            self.menu_cache.request_refresh,
        )
        dialog.exec()

    def manage_directories(self):
        dialog = DirectoryDialog(
            self.settings["scan_dirs"], self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings["scan_dirs"] = dialog.directories()
            try:
                save_settings(self.settings)
                self.status_label.setText(
                    f"已保存 {len(self.settings['scan_dirs'])} 个扫描目录"
                )
            except Exception as error:
                QMessageBox.critical(
                    self, "保存失败", str(error)
                )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KMenu Manager")

    resource_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    icon_path = resource_dir / "assets" / "kmenu-manager.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = Manager()
    window.setWindowIcon(app.windowIcon())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
