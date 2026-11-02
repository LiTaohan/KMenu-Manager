#!/usr/bin/env python3
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HOME = Path.home()
CONFIG = HOME / ".config/app-menu-manager/settings.json"
MENU = HOME / ".local/share/applications"
CACHE = HOME / ".cache/app-menu-manager"
EXTRACT_CACHE = CACHE / "appimage"
ICON_CACHE = HOME / ".local/share/icons"

ARCHIVES = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz",
    ".txz", ".tar.bz2", ".tbz2", ".7z", ".rar"
)

HELPERS = {
    "chrome-sandbox", "crashpad_handler",
    "chrome_crashpad_handler"
}


def read_desktop(path):
    data = {}
    section = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section == "Desktop Entry" and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                data[key] = value
    except (OSError, UnicodeError):
        pass
    return data


def load_settings():
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def existing_entries():
    entries = {}

    # KDE Menu Editor stores deleted entries in the special .hidden menu.
    hidden_entries = set()
    menu_config = HOME / ".config/menus/applications-kmenuedit.menu"

    try:
        if menu_config.is_file():
            root = ET.parse(menu_config).getroot()
            for menu in root.findall(".//Menu"):
                if menu.findtext("Name") == ".hidden":
                    include = menu.find("Include")
                    if include is not None:
                        hidden_entries.update(
                            item.text.strip()
                            for item in include.findall("Filename")
                            if item.text and item.text.strip()
                        )
    except (OSError, ET.ParseError):
        pass

    for path in MENU.glob("auto-*.desktop"):
        if path.name in hidden_entries:
            continue
        data = read_desktop(path)
        if data.get("X-AutoManaged") != "true":
            continue
        source = data.get("X-AutoSource")
        if source:
            entries[str(Path(source).expanduser().resolve())] = {
                "name": data.get("Name"),
                "icon": data.get("Icon"),
                "categories": data.get("Categories"),
                "desktop": path.name,
            }
    return entries


def clean_name(filename):
    name = re.sub(r"\.appimage$", "", filename, flags=re.I)
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\s+\d+(?:\.\d+)+(?:\s+.*)?$", "", name)
    name = re.sub(
        r"\s+(linux|amd64|x86 64|x86 64 01)$",
        "", name, flags=re.I
    )
    return name.strip() or "未知软件"


def classify(name):
    n = name.casefold()
    rules = [
        ("Network;InstantMessaging;", (
            "qq", "telegram", "wechat", "微信", "discord", "即时通讯"
        )),
        ("Network;", (
            "flclash", "clash", "vpn", "proxy",
            "firefox", "chrome", "browser", "浏览器"
        )),
        ("AudioVideo;Audio;Player;", (
            "voicefox", "spotify", "音乐", "music"
        )),
        ("AudioVideo;Video;", (
            "红果", "短剧", "video", "vlc", "mpv"
        )),
        ("Development;", ("vscode", "pycharm", "开发", "developer")),
        ("Graphics;", ("gimp", "krita", "blender", "inkscape", "绘图")),
        ("Game;", ("steam", "lutris", "游戏")),
        ("Office;", ("libreoffice", "office", "办公")),
    ]
    for category, keywords in rules:
        if any(word in n for word in keywords):
            return category
    return "Utility;"


def is_elf(path):
    try:
        with path.open("rb") as file:
            return file.read(4) == b"\x7fELF"
    except OSError:
        return False


def app_fingerprint(path):
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def find_app_icon(root, desktop_data):
    icon_name = desktop_data.get("Icon", "").strip()
    candidates = []

    if icon_name:
        icon_path = Path(icon_name)
        if icon_path.is_absolute() and icon_path.is_file():
            candidates.append(icon_path)

        base = Path(icon_name).name
        if Path(base).suffix:
            names = [base]
        else:
            names = [base + ext for ext in (".png", ".svg", ".xpm")]

        for name in names:
            candidates.extend(root.rglob(name))

    candidates.extend([
        root / ".DirIcon",
        root / "AppRun",
    ])

    valid = []
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.suffix.lower() in (
                ".png", ".svg", ".xpm", ".ico"
            ):
                valid.append(candidate)
        except OSError:
            pass

    if not valid:
        return None

    # 优先使用文件名与 Desktop Entry 的 Icon 字段匹配的图标
    if icon_name:
        base = Path(icon_name).stem.casefold()
        matched = [
            p for p in valid
            if p.stem.casefold() == base
        ]
        if matched:
            valid = matched

    # 优先选择 hicolor 中较大尺寸的图标
    def score(path):
        text = str(path).lower()
        size = 0
        match = re.search(r"/(\d+)x\1/", text)
        if match:
            size = int(match.group(1))
        return (size, len(path.parts))

    valid.sort(key=score, reverse=True)
    return valid[0]


def extract_appimage(path):
    """解包可信 AppImage，并缓存其元数据和图标。"""
    EXTRACT_CACHE.mkdir(parents=True, exist_ok=True)
    ICON_CACHE.mkdir(parents=True, exist_ok=True)

    fingerprint = app_fingerprint(path)
    final_dir = EXTRACT_CACHE / fingerprint
    metadata_file = final_dir / "app-menu-metadata.json"

    if metadata_file.is_file():
        try:
            return json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    temp_dir = Path(tempfile.mkdtemp(prefix="extract-", dir=EXTRACT_CACHE))

    try:
        result = subprocess.run(
            [str(path), "--appimage-extract"],
            cwd=temp_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )

        root = temp_dir / "squashfs-root"
        if result.returncode != 0 or not root.is_dir():
            raise RuntimeError("AppImage 解包失败")

        desktop_files = list(root.rglob("*.desktop"))
        desktop_data = {}

        for desktop_file in desktop_files:
            data = read_desktop(desktop_file)
            if data.get("Type") == "Application" and data.get("Name"):
                desktop_data = data
                break

        if not desktop_data:
            raise RuntimeError("没有找到有效的 Desktop Entry")

        icon_source = find_app_icon(root, desktop_data)
        icon_target = None

        if icon_source:
            icon_ext = icon_source.suffix.lower()
            icon_target = ICON_CACHE / f"app-{fingerprint}{icon_ext}"
            shutil.copy2(icon_source, icon_target)

        metadata = {
            "name": desktop_data.get("Name"),
            "generic_name": desktop_data.get("GenericName"),
            "comment": desktop_data.get("Comment"),
            "categories": desktop_data.get("Categories"),
            "icon": str(icon_target) if icon_target else None,
        }

        if final_dir.exists():
            shutil.rmtree(final_dir)

        temp_dir.rename(final_dir)

        metadata_file = final_dir / "app-menu-metadata.json"
        metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return metadata

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def scan(directories, settings):
    entries = existing_entries()
    overrides = settings.get("categories", {})
    results = []
    seen = set()
    archives = 0
    errors = []

    for directory in directories:
        base = Path(directory).expanduser()

        if not base.is_dir():
            errors.append(f"目录不存在：{base}")
            continue

        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in files:
                path = Path(root) / filename

                try:
                    if path.is_symlink() or not path.is_file():
                        continue

                    resolved = str(path.resolve())

                    if resolved in seen:
                        continue

                    lower = filename.lower()

                    if lower.endswith(ARCHIVES):
                        archives += 1
                        continue

                    if lower.endswith(".appimage"):
                        app_type = "AppImage"
                    elif (
                        filename not in HELPERS
                        and os.access(path, os.X_OK)
                        and is_elf(path)
                    ):
                        app_type = "ELF"
                    else:
                        continue

                    seen.add(resolved)
                    old = entries.get(resolved, {})
                    metadata = {}

                    if app_type == "AppImage":
                        try:
                            metadata = extract_appimage(path)
                        except Exception as error:
                            errors.append(
                                f"{filename}：元数据提取失败：{error}"
                            )

                    # 已有菜单入口优先保留原名称、图标和分类
                    name = (
                        old.get("name")
                        or metadata.get("name")
                        or clean_name(filename)
                    )

                    category = (
                        overrides.get(old.get("desktop"))
                        or old.get("categories")
                        or metadata.get("categories")
                        or classify(name)
                    )

                    if category and not category.endswith(";"):
                        category += ";"

                    icon = old.get("icon") or metadata.get("icon")

                    # VoiceFox 专属图标回退：不覆盖用户自定义图标
                    if (
                        name.casefold() == "voicefox"
                        and icon in (None, "", "application-x-executable")
                    ):
                        voicefox_icon = ICON_CACHE / "voicefox.png"
                        if voicefox_icon.is_file():
                            icon = str(voicefox_icon)

                    results.append({
                        "name": name,
                        "path": resolved,
                        "type": app_type,
                        "icon": icon,
                        "categories": category,
                        "existing": bool(old),
                        "comment": metadata.get("comment"),
                        "generic_name": metadata.get("generic_name"),
                    })

                except OSError as error:
                    errors.append(f"{path}：{error}")

    results.sort(key=lambda item: item["name"].casefold())
    return results, archives, errors


def main():
    settings = load_settings()
    directories = settings.get(
        "scan_dirs", [str(HOME / "Applications")]
    )

    results, archives, errors = scan(directories, settings)

    print("第三方软件扫描预览")
    print("=" * 55)

    for directory in directories:
        print(f"扫描目录：{directory}")

    print(f"\n发现软件：{len(results)} 个")
    print(f"发现压缩包：{archives} 个\n")

    for index, item in enumerate(results, 1):
        print(f"{index}. {item['name']}")
        print(f"   类型：{item['type']}")
        print(f"   分类：{item['categories']}")
        print(f"   已有菜单入口：{'是' if item['existing'] else '否'}")
        print(f"   图标：{item['icon'] or '默认图标'}")
        print(f"   路径：{item['path']}\n")

    if errors:
        print("扫描警告：")
        for error in errors:
            print("  -", error)

    print("=" * 55)
    print("预览模式：没有修改或删除任何菜单入口。")


if __name__ == "__main__":
    main()
