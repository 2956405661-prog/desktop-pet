# -*- coding: utf-8 -*-
"""安装程序：把自己带着的那份程序解到用户的程序目录，然后叫出接入向导。

打成一个 exe 用：把"桌面宠物"整个文件夹压成 payload.zip，用 --add-data 塞进来。
用户双击这个 exe 就是安装；不需要 Python、不需要联网。
"""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile

KEEP = ("pet_config.json", "pet_state.json", "pet_tasks")   # 覆盖安装时不许动的东西
APP_NAME = "桌面宠物"


def install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def extract(payload: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(payload) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            top = name.replace("\\", "/").split("/")[0]
            if top in KEEP and os.path.exists(os.path.join(dest, top)):
                continue                        # 升级：用户的数据原样保留
            z.extract(name, dest)


def write_uninstall_entry(dest: str) -> None:
    """在"应用和功能"里留一个卸载入口（只写 HKCU，不需要管理员）"""
    try:
        import winreg
    except Exception:
        return
    exe = os.path.join(dest, f"{APP_NAME}.exe")
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopPet")
        for name, value in (("DisplayName", "桌面宠物（Claude Code 助手）"),
                            ("DisplayVersion", version()),
                            ("InstallLocation", dest),
                            ("DisplayIcon", exe),
                            ("UninstallString", f'"{exe}" --uninstall'),
                            ("NoModify", 1), ("NoRepair", 1)):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ if isinstance(value, str) else winreg.REG_DWORD,
                              value)
        winreg.CloseKey(key)
    except Exception:
        pass


def version() -> str:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from update_check import VERSION
        return VERSION
    except Exception:
        return "1.0.1"


def main() -> int:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    payload = os.path.join(base, "payload.zip")
    dest = install_dir()
    if not os.path.exists(payload):
        return 2
    extract(payload, dest)
    write_uninstall_entry(dest)
    exe = os.path.join(dest, f"{APP_NAME}.exe")
    if os.path.exists(exe) and not os.environ.get("PET_INSTALL_NO_LAUNCH"):
        subprocess.Popen([exe, "--setup"], cwd=dest, close_fds=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
