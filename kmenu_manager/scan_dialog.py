#!/usr/bin/env python3
import hashlib
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QMessageBox
)

from .scanner import scan


def escape_value(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def exec_value(path):
    value = str(path).replace("\\", "\\\\")
    value = value.replace('"', '\\"').replace("%", "%%")
    return '"' + value + '"'


def restore_kde_menu_entry(desktop_name):
    """Remove KDE Menu Editor exclusion and hidden records for one entry."""
    menu_file = (
        Path.home() / ".config/menus/applications-kmenuedit.menu"
    )

    if not menu_file.is_file():
        return False

    tree = ET.parse(menu_file)
    root = tree.getroot()
    changed = False

    for menu in root.iter("Menu"):
        menu_name = menu.findtext("Name", default="").strip()

        if menu_name == ".hidden":
            include = menu.find("Include")
            if include is not None:
                for item in list(include.findall("Filename")):
                    if (item.text or "").strip() == desktop_name:
                        include.remove(item)
                        changed = True

        exclude = menu.find("Exclude")
        if exclude is not None:
            for item in list(exclude.findall("Filename")):
                if (item.text or "").strip() == desktop_name:
                    exclude.remove(item)
                    changed = True

    if not changed:
        return False

    backup = menu_file.with_suffix(menu_file.suffix + ".kmenu-manager-backup")
    if not backup.exists():
        import shutil
        shutil.copy2(menu_file, backup)

    content = ET.tostring(root, encoding="unicode")
    doctype = (
        "<!DOCTYPE Menu PUBLIC "
        "'-//freedesktop//DTD Menu 1.0//EN' "
        "'http://www.freedesktop.org/standards/menu-spec/menu-1.0.dtd'>"
    )
    menu_file.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + doctype + "\n" + content + "\n",
        encoding="utf-8"
    )
    return True


class ScanDialog(QDialog):
    def __init__(
        self, parent, settings, refresh_callback,
        menu_refresh_callback
    ):
        super().__init__(parent)
        self.setWindowTitle("扫描软件 - 预览与添加")
        self.resize(760, 560)
        self.settings = settings
        self.refresh_callback = refresh_callback
        self.menu_refresh_callback = menu_refresh_callback
        self.results = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "扫描结果：已有入口不会重复添加；新软件可勾选后添加。"
        ))

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        self.summary = QLabel("正在扫描……")
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("添加选中的新软件")
        close_button = QPushButton("关闭")
        self.add_button.clicked.connect(self.add_selected)
        close_button.clicked.connect(self.reject)
        buttons.addWidget(self.add_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.perform_scan()

    def perform_scan(self):
        directories = self.settings.get("scan_dirs", [])
        self.results, archives, errors = scan(
            directories, self.settings
        )

        self.list.clear()
        new_count = 0

        for app in self.results:
            existing = app["existing"]
            status = "已有入口" if existing else "新发现"
            text = (
                f"{app['name']}  [{app['type']}]  — {status}\n"
                f"分类：{app['categories']}\n"
                f"路径：{app['path']}"
            )

            item = QListWidgetItem(text)
            icon = app.get("icon")
            if icon:
                item.setIcon(QIcon(str(icon)))
            item.setData(Qt.ItemDataRole.UserRole, app)

            if existing:
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setFlags(
                    item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked)
                new_count += 1

            self.list.addItem(item)

        self.summary.setText(
            f"发现 {len(self.results)} 个软件，其中已有入口 "
            f"{len(self.results) - new_count} 个，新发现 {new_count} 个；"
            f"压缩包 {archives} 个。"
        )

        if errors:
            self.summary.setText(
                self.summary.text() + f" 另有 {len(errors)} 条扫描警告。"
            )

        self.add_button.setEnabled(new_count > 0)

    def add_selected(self):
        selected = []

        for row in range(self.list.count()):
            item = self.list.item(row)
            app = item.data(Qt.ItemDataRole.UserRole)

            if (
                not app["existing"]
                and item.checkState() == Qt.CheckState.Checked
            ):
                selected.append(app)

        if not selected:
            QMessageBox.information(
                self, "提示", "没有勾选任何新软件。"
            )
            return

        menu_dir = Path.home() / ".local/share/applications"
        menu_dir.mkdir(parents=True, exist_ok=True)

        added = 0
        skipped = 0
        errors = []
        menu_changed = False

        for app in selected:
            source = Path(app["path"]).resolve()

            if not source.is_file() or not os.access(source, os.X_OK):
                errors.append(f"{app['name']}：文件不存在或不可执行")
                continue

            uid = hashlib.sha256(
                str(source).encode()
            ).hexdigest()[:16]

            desktop = menu_dir / f"auto-{uid}.desktop"

            # 重新添加时，先解除 KDE 菜单编辑器的隐藏和排除记录
            try:
                menu_changed = (
                    restore_kde_menu_entry(desktop.name) or menu_changed
                )
            except (OSError, ET.ParseError) as error:
                errors.append(
                    f"{app['name']}：恢复 KDE 菜单记录失败：{error}"
                )
                continue

            if desktop.exists():
                skipped += 1
                continue

            icon = app.get("icon") or "application-x-executable"
            categories = app.get("categories") or "Utility;"

            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Version=1.0\n"
                f"Name={escape_value(app['name'])}\n"
                f"Exec={exec_value(source)}\n"
                f"Icon={escape_value(icon)}\n"
                "Terminal=false\n"
                f"Categories={categories}\n"
                "StartupNotify=true\n"
                "X-AutoManaged=true\n"
                f"X-AutoSource={escape_value(source)}\n"
            )

            try:
                fd = os.open(
                    desktop,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644
                )
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write(content)
                added += 1
            except FileExistsError:
                skipped += 1
            except OSError as error:
                errors.append(f"{app['name']}：{error}")

        if added > 0 or menu_changed:
            self.menu_refresh_callback()

        self.refresh_callback()
        self.perform_scan()

        message = f"成功添加：{added} 个\n跳过已存在：{skipped} 个"
        if errors:
            message += "\n\n遇到的问题：\n" + "\n".join(errors)

        QMessageBox.information(self, "添加结果", message)
