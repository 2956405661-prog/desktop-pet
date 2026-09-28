# -*- coding: utf-8 -*-
"""接入向导：把桌面宠物接到 Claude Code 上（也可以反过来摘掉）。

两种用法（都由 桌面宠物.exe 调起）：
    桌面宠物.exe --setup        接入：看配置 → 让用户确认 → 写钩子 → 建快捷方式
    桌面宠物.exe --uninstall    卸掉：删掉我们写的钩子（可选恢复接入前的备份）

原则：
  1. 每一步都让用户**看见并确认**，绝不静默改人家的配置；
  2. 动 settings.json 之前一定先备份；
  3. 只补不覆盖：env 里已有的键默认不动，除非用户明确选了"我另外填"。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

APP_DIR = (os.path.dirname(os.path.abspath(sys.executable))
           if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)))

EVENTS = (("PreToolUse", "Bash"), ("PostToolUse", "Bash"), ("PostToolUseFailure", "Bash"),
          ("Notification", None), ("PermissionRequest", None), ("UserPromptSubmit", None),
          ("Stop", None), ("StopFailure", None), ("SessionStart", None), ("SessionEnd", None))

ENV_FIELDS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
              "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
              "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
              "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME")


# ----------------------------------------------------------------- 路径与读写

def claude_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude")


def settings_path() -> str:
    return os.path.join(claude_dir(), "settings.json")


def pet_exe() -> str:
    return os.path.join(APP_DIR, "桌面宠物.exe" if os.name == "nt" else "桌面宠物")


def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
        return json.loads(text) if text else {}
    except Exception:
        return {}


def save_json(path: str, data: dict, backup: bool = True) -> str | None:
    made = None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path):
        made = f"{path}.bak-{time.strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(path, made)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return made


def hook_command() -> str:
    return f'"{pet_exe().replace(os.sep, "/")}" --hook'


def is_our_hook(item) -> bool:
    try:
        for h in item.get("hooks", []):
            cmd = str(h.get("command") or "")
            if "--hook" in cmd and ("桌面宠物" in cmd or "DesktopPet" in cmd):
                return True
    except Exception:
        pass
    return False


def made_entry(matcher: str | None) -> dict:
    item = {"hooks": [{"type": "command", "command": hook_command(), "timeout": 10}]}
    return {"matcher": matcher, **item} if matcher else item


# ----------------------------------------------------------------- 检测

def detect() -> dict:
    """看一眼用户现在是怎么用 Claude 的（细节见 检测现有配置.py）"""
    path = settings_path()
    env = (load_json(path).get("env") or {}) if os.path.exists(path) else {}
    env = {k: str(v) for k, v in env.items() if k in ENV_FIELDS}
    if env:
        return {"mode": "existing", "env": env, "where": "settings.json 的 env 段"}
    env2 = {k: os.environ[k] for k in ENV_FIELDS if os.environ.get(k)}
    if env2:
        return {"mode": "existing", "env": env2, "where": "系统环境变量"}
    home = os.path.expanduser("~")
    if os.path.exists(os.path.join(claude_dir(), ".credentials.json")) \
            or load_json(os.path.join(home, ".claude.json")).get("oauthAccount") \
            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return {"mode": "subscription", "env": {}, "where": "官方订阅登录"}
    return {"mode": "none", "env": {}, "where": "什么都没找到"}


def mask(key: str, value: str) -> str:
    if not any(w in key.upper() for w in ("TOKEN", "KEY", "SECRET")):
        return value
    value = str(value)
    return f"{value[:5]}{'*' * 6}{value[-3:]}（共 {len(value)} 位）" if len(value) > 8 \
        else "*" * len(value)


# ----------------------------------------------------------------- 干活

def install_hooks(log) -> None:
    path = settings_path()
    data = load_json(path)
    hooks = data.setdefault("hooks", {})
    added = []
    for event, matcher in EVENTS:
        bucket = hooks.setdefault(event, [])
        bucket[:] = [item for item in bucket if not is_our_hook(item)]   # 清掉旧的我们
        bucket.append(made_entry(matcher))
        added.append(event)
    backup = save_json(path, data)
    log(f"钩子已写入：{len(added)} 个事件")
    log(f"  配置文件：{path}")
    if backup:
        log(f"  备份：{os.path.basename(backup)}")


def install_env(env: dict, log) -> None:
    if not env:
        return
    path = settings_path()
    data = load_json(path)
    data.setdefault("env", {}).update(env)
    backup = save_json(path, data)
    log(f"接口配置已写入：{', '.join(env.keys())}")
    if backup:
        log(f"  备份：{os.path.basename(backup)}")


def write_pet_config(follow: bool, update: bool, log) -> None:
    path = os.path.join(APP_DIR, "pet_config.json")
    cfg = load_json(path)
    cfg["follow_claude"] = bool(follow)
    cfg["update_check"] = bool(update)
    save_json(path, cfg, backup=False)
    log(f"宠物设置已更新：跟随 Claude={follow}，检查新版本={update}")


def uninstall_hooks(log, restore: bool = False) -> None:
    path = settings_path()
    if not os.path.exists(path):
        log("没有找到 Claude 的配置文件，跳过")
        return
    data = load_json(path)
    hooks = data.get("hooks") or {}
    removed = 0
    for event, bucket in list(hooks.items()):
        if not isinstance(bucket, list):
            continue
        keep = [item for item in bucket if not is_our_hook(item)]
        removed += len(bucket) - len(keep)
        if keep:
            hooks[event] = keep
        else:
            hooks.pop(event, None)
    save_json(path, data)
    log(f"已摘掉 {removed} 条钩子")
    if restore:
        cands = sorted((f for f in os.listdir(claude_dir()) if f.startswith("settings.json.bak-")),
                       reverse=True)
        if cands:
            src = os.path.join(claude_dir(), cands[0])
            shutil.copy2(src, path + f".before-restore-{time.strftime('%H%M%S')}")
            shutil.copy2(src, path)
            log(f"已恢复接入前的配置：{cands[0]}")
        else:
            log("没有找到备份文件，没恢复")


def make_shortcut(log) -> None:
    """在桌面放一个快捷方式（用系统自带的 WScript.Shell，不需要额外库）"""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        log("没找到桌面文件夹，跳过快捷方式")
        return
    lnk = os.path.join(desktop, "桌面宠物.lnk")
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          "$s.TargetPath='{exe}';$s.WorkingDirectory='{dir}';$s.Save()").format(
              lnk=lnk, exe=pet_exe(), dir=APP_DIR)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False,
                       creationflags=0x08000000)
        log("桌面快捷方式已创建")
    except Exception as exc:
        log(f"快捷方式没建上（不影响使用）：{exc}")


def start_pet(log) -> None:
    try:
        subprocess.Popen([pet_exe()], cwd=APP_DIR, creationflags=0x00000008 | 0x08000000,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        log("宠物已启动")
    except Exception as exc:
        log(f"启动失败：{exc}")


# ----------------------------------------------------------------- 界面

def run_gui(uninstall: bool = False) -> int:
    import tkinter as tk
    from tkinter import ttk

    info = detect()
    root = tk.Tk()
    root.title("桌面宠物 · 卸载" if uninstall else "桌面宠物 · 接入 Claude Code")
    root.geometry("560x560")
    root.resizable(False, False)

    pad = {"padx": 14, "pady": 4}
    tk.Label(root, text="桌面宠物 · 盯着 Claude Code 干活的小家伙",
             font=("Microsoft YaHei", 13, "bold")).pack(anchor="w", **pad)

    text = {
        "existing": f"检测到你已有的接口配置（来自 {info['where']}）：\n"
                    + "\n".join(f"    {k} = {mask(k, v)}" for k, v in info["env"].items()),
        "subscription": "检测到你已经用官方订阅登录过 Claude。\n"
                        "订阅登录不需要、也不建议再填 API —— 我只写钩子，不碰你的登录信息。",
        "none": "没有找到现成的 Claude 配置。\n"
                "如果你用的是官方订阅登录，这一页什么都不用填；\n"
                "如果用的是第三方接口，请在下面填接口地址和密钥。",
    }[info["mode"]]
    tk.Label(root, text=text, justify="left", anchor="w", wraplength=520,
             fg="#1a4b8c" if info["mode"] != "none" else "#8a4b00").pack(anchor="w", **pad)

    use_existing = tk.BooleanVar(value=info["mode"] == "existing")
    fill_manual = tk.BooleanVar(value=info["mode"] == "none")
    if not uninstall:
        box = tk.LabelFrame(root, text="接口配置（不确定就选第一项）")
        box.pack(fill="x", **pad)
        ttk.Radiobutton(box, text="沿用现有配置（推荐）", value=True, variable=use_existing,
                        command=lambda: (fill_manual.set(False),)).pack(anchor="w")
        ttk.Radiobutton(box, text="我另外填一份", value=True, variable=fill_manual,
                        command=lambda: (use_existing.set(False),)).pack(anchor="w")
        entries = {}
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"):
            row = tk.Frame(box)
            row.pack(fill="x", padx=6, pady=2)
            tk.Label(row, text=key, width=34, anchor="w").pack(side="left")
            var = tk.StringVar(value="" if key.endswith("TOKEN") else info["env"].get(key, ""))
            tk.Entry(row, textvariable=var, width=26).pack(side="left")
            entries[key] = var

    follow = tk.BooleanVar(value=True)
    update = tk.BooleanVar(value=True)
    shortcut = tk.BooleanVar(value=False)
    launch = tk.BooleanVar(value=not uninstall)
    if not uninstall:
        opt = tk.LabelFrame(root, text="别的选择")
        opt.pack(fill="x", **pad)
        ttk.Checkbutton(opt, text="跟着 Claude 一起进退（Claude 关了它就退下）",
                        variable=follow).pack(anchor="w")
        ttk.Checkbutton(opt, text="检查新版本（只读一个公开的小文件）",
                        variable=update).pack(anchor="w")
        ttk.Checkbutton(opt, text="在桌面建一个快捷方式", variable=shortcut).pack(anchor="w")
        ttk.Checkbutton(opt, text="装完立刻启动宠物", variable=launch).pack(anchor="w")
    else:
        restore = tk.BooleanVar(value=False)
        ttk.Checkbutton(root, text="顺便把 Claude 配置恢复成接入前的备份（默认不动）",
                        variable=restore).pack(anchor="w", **pad)

    log_box = tk.Text(root, height=9, wrap="word", state="disabled", bg="#f6f7f9")
    log_box.pack(fill="both", expand=True, **pad)

    def log(line: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", line + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update()

    def do_uninstall() -> None:
        log("开始卸载…")
        uninstall_hooks(log, restore=restore.get())
        log("")
        log("好了。程序文件夹可以自己删掉；桌面快捷方式也可以删掉。")

    def do_install() -> None:
        log("开始接入…")
        if not os.path.isdir(claude_dir()):
            log("⚠ 没找到 ~/.claude —— 你好像还没装 Claude Code。")
            log("  先去装 Claude Code（终端版或 VS Code 扩展都行），再回来点一次。")
            return
        install_hooks(log)
        if fill_manual.get():
            env = {k: v.get().strip() for k, v in entries.items() if v.get().strip()}
            install_env(env, log)
        else:
            log("接口配置：沿用你现有的，一个字都没动")
        write_pet_config(follow.get(), update.get(), log)
        if shortcut.get():
            make_shortcut(log)
        log("")
        log("接入完成！请新开一个 Claude Code 会话（它启动时才读配置）。")
        log("然后随便干点活，宠物就会动起来。")
        if launch.get():
            start_pet(log)

    btns = tk.Frame(root)
    btns.pack(fill="x", **pad)
    action = do_uninstall if uninstall else do_install
    tk.Button(btns, text="开始卸载" if uninstall else "开始接入", width=14,
              command=action).pack(side="left")
    tk.Button(btns, text="关掉", width=10, command=root.destroy).pack(side="right")
    root.mainloop()
    return 0


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--silent" in argv:                 # 给自动化/高级用户：不开界面，直接用现有配置接上
        def log(line: str) -> None:
            print(line, flush=True)
        if "--uninstall" in argv:
            uninstall_hooks(log, restore="--restore" in argv)
        else:
            if not os.path.isdir(claude_dir()):
                log("没找到 ~/.claude —— 请先安装 Claude Code")
                return 2
            install_hooks(log)
            log("接口配置：沿用现有的")
            write_pet_config(True, True, log)
            log("接入完成（静默模式）")
        return 0
    return run_gui(uninstall="--uninstall" in argv)


if __name__ == "__main__":
    raise SystemExit(main())
