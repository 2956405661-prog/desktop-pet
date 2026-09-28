# -*- coding: utf-8 -*-
"""
让桌面宠物动起来 / 说话 / 提醒你的小遥控器。

任何软件、任何语言，只要能写一个 JSON 文件，就能驱动这只宠物。
本脚本只是把「写 JSON」这件事包成人话命令，方便调用。

常用写法：
    python petctl.py working "开始编译"
    python petctl.py done    "编译通过"
    python petctl.py alert   "有个报错要你看"
    python petctl.py say     "路上小心"
    python petctl.py demo                     演示一遍完整流程
    python petctl.py run -- python build.py   跑命令，自动「干活中 -> 完成/失败」
    python petctl.py watch --file app.log --pattern "ERROR" --state alert --message "日志里有错"
    python petctl.py status                   看当前状态

当作 Python 模块用：
    from petctl import notify
    notify("done", "跑完了")
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

PET_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PET_DIR, "pet_state.json")
TASKS_DIR = os.path.join(PET_DIR, "pet_tasks")
STATES = ("idle", "working", "done", "alert", "sleep")


def notify(state: str = "alert", message: str = "", seconds: float | None = None,
           pet_dir: str | None = None, title: str = "", detail: str = "", icon: str = "",
           cwd: str = "", hint: str = "", session_id: str = "") -> str:
    """把状态写给宠物。state 见 STATES；想只说话不改表情就传 "say"。"""
    path = os.path.join(pet_dir, "pet_state.json") if pet_dir else STATE_PATH
    payload = {
        "state": state,
        "message": message,
        "seconds": seconds,
        "title": title,
        "detail": detail,
        "icon": icon,
        "cwd": cwd,
        "hint": hint,
        "session_id": session_id,
        "ts": time.time(),
        "source": os.environ.get("PET_SOURCE", "petctl"),
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    _replace(tmp, path)            # 原子替换，宠物永远读到完整文件
    return path


def _replace(src: str, dst: str) -> None:
    """Windows 上「目标文件正好被宠物读着」时 os.replace 会偶发失败，重试几次就好。"""
    last = None
    for _ in range(6):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    raise last


def task_path(key: str, pet_dir: str | None = None) -> str:
    safe = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_.")[:60] or "task"
    return os.path.join(pet_dir or PET_DIR, "pet_tasks", f"{safe}.json")


def write_task(title: str, detail: str = "", icon: str = "info", state: str = "working",
               key: str = "petctl", cwd: str = "", hint: str = "",
               pet_dir: str | None = None) -> str:
    """写一张任务卡（会和 Claude Code 的任务一起叠在宠物身上）。"""
    payload = {
        "state": state,
        "title": title,
        "detail": detail,
        "icon": icon,
        "cwd": cwd,
        "hint": hint,
        "session_id": key,
        "ts": time.time(),
        "source": "petctl",
    }
    path = task_path(key, pet_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    _replace(tmp, path)
    return path


def remove_task(key: str, pet_dir: str | None = None) -> None:
    try:
        os.remove(task_path(key, pet_dir))
    except OSError:
        pass


def read_state(pet_dir: str | None = None) -> dict:
    path = os.path.join(pet_dir, "pet_state.json") if pet_dir else STATE_PATH
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_demo(args) -> int:
    steps = [
        ("working", "开工了，我盯着。", 0),
        ("done", "第一件事搞定！", 2.2),
        ("alert", "这条消息要你看一眼。", 2.2),
        ("idle", "", 3.0),
    ]
    for state, message, wait in steps:
        if wait:
            time.sleep(wait)
        notify(state, message, pet_dir=args.pet_dir)
        print(f"-> {state} {message}")
    return 0


def cmd_run(args) -> int:
    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("用法：python petctl.py run -- <要执行的命令>")
        return 2
    notify("working", args.message or f"正在跑：{' '.join(cmd)}", pet_dir=args.pet_dir)
    started = time.time()
    code = subprocess.call(cmd)
    cost = time.time() - started
    if code == 0:
        notify("done", f"{args.done_message or '跑完啦'}（{cost:.1f}s）", pet_dir=args.pet_dir)
    else:
        notify("alert", f"退出码 {code}（{cost:.1f}s）", pet_dir=args.pet_dir)
    return code


def cmd_watch(args) -> int:
    path = os.path.abspath(args.file)
    pattern = re.compile(args.pattern) if args.pattern else None
    print(f"盯着 {path}" + (f"，匹配 /{args.pattern}/" if args.pattern else "") + "  (Ctrl+C 停止)")
    pos = os.path.getsize(path) if args.from_end and os.path.exists(path) else 0
    while True:
        try:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size < pos:            # 日志被清空/轮转了
                    pos = 0
                if size > pos:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        for line in fh:
                            if pattern is None or pattern.search(line):
                                notify(args.state, args.message or line.strip()[:80],
                                       pet_dir=args.pet_dir)
                        pos = fh.tell()
        except KeyboardInterrupt:
            return 0
        except Exception as exc:          # 文件被占用之类，忽略继续
            print(f"[watch] {exc}")
        time.sleep(args.interval)


def cmd_status(args) -> int:
    data = read_state(args.pet_dir)
    print(json.dumps(data, ensure_ascii=False, indent=2) if data else "（还没有状态，宠物在待机）")
    folder = os.path.join(args.pet_dir or PET_DIR, "pet_tasks")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as fh:
                task = json.load(fh)
        except Exception:
            continue
        print(f"  · [{task.get('state', '?')}] {task.get('title', '')}"
              f"（{name}）｜{task.get('detail', '')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="桌面宠物遥控器")
    ap.add_argument("--pet-dir", default=None, help="宠物目录（默认与本脚本同目录）")
    sub = ap.add_subparsers(dest="cmd")

    for name in STATES:
        p = sub.add_parser(name, help=f"让宠物进入 {name} 状态")
        p.add_argument("message", nargs="?", default="")
        p.add_argument("--seconds", type=float, default=None, help="气泡显示时长")

    p_say = sub.add_parser("say", help="只说话，不换表情")
    p_say.add_argument("message")
    p_say.add_argument("--seconds", type=float, default=5.0)

    p_card = sub.add_parser("card", help="显示状态卡片：标题 + 明细 + 图标")
    p_card.add_argument("title")
    p_card.add_argument("detail", nargs="?", default="")
    p_card.add_argument("--icon", default="info", choices=["spinner", "check", "alert", "info"])
    p_card.add_argument("--state", default="working", choices=STATES)
    p_card.add_argument("--seconds", type=float, default=None)
    p_card.add_argument("--cwd", default="", help="点这张卡片时跳到哪个目录/窗口")
    p_card.add_argument("--key", default="petctl", help="任务标识；同一个 key 会覆盖上一张")
    p_card.add_argument("--clear", action="store_true", help="把这个 key 的卡片收走")

    sub.add_parser("demo", help="演示一遍")
    sub.add_parser("status", help="看当前状态")

    p_run = sub.add_parser("run", help="跑一条命令并自动汇报")
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    p_run.add_argument("--message", default="")
    p_run.add_argument("--done-message", dest="done_message", default="")

    p_watch = sub.add_parser("watch", help="盯着日志文件，命中就提醒")
    p_watch.add_argument("--file", required=True)
    p_watch.add_argument("--pattern", default="")
    p_watch.add_argument("--state", default="alert", choices=STATES)
    p_watch.add_argument("--message", default="")
    p_watch.add_argument("--interval", type=float, default=1.0)
    p_watch.add_argument("--from-end", action="store_true", help="只关心新内容")

    args = ap.parse_args()

    if args.cmd == "demo":
        return cmd_demo(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "watch":
        return cmd_watch(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "say":
        notify("say", args.message, args.seconds, args.pet_dir)
        return 0
    if args.cmd == "card":
        if args.clear:
            remove_task(args.key, args.pet_dir)
            return 0
        write_task(args.title, args.detail, args.icon, args.state, args.key, args.cwd,
                   hint=os.path.basename(args.cwd.rstrip("\\/")) if args.cwd else "",
                   pet_dir=args.pet_dir)
        return 0
    if args.cmd in STATES:
        notify(args.cmd, getattr(args, "message", ""), getattr(args, "seconds", None), args.pet_dir)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
