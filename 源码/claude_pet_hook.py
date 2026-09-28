# -*- coding: utf-8 -*-
"""
Claude Code → 桌面宠物 的钩子脚本。

Claude Code 在特定时刻会执行挂上的命令，并把一份 JSON 从 stdin 递给它。
这个脚本读那份 JSON，然后决定让宠物做表情还是说话。

设计原则（很重要）：
1. 永远 exit 0，永远不往 stdout 打印任何东西 —— 绝不干扰 Claude Code 的判断；
2. 只做「看一眼 + 写个状态文件」，耗时几毫秒，不会拖慢它；
3. 任何异常都吞掉，钩子绝不能成为 Claude Code 的故障点；
4. 认不出的新事件会记进日志，方便以后补配置。

手动测试（不需要 Claude Code）：
    echo {"hook_event_name":"Stop"} | python claude_pet_hook.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

# 打包成 exe 之后 __file__ 指向临时解包目录，状态文件得跟着 exe 走
if getattr(sys, "frozen", False):
    PET_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    PET_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PET_DIR, "pet_state.json")
TASKS_DIR = os.path.join(PET_DIR, "pet_tasks")     # 一个会话一个文件，宠物会把它们叠起来
CFG_PATH = os.path.join(PET_DIR, "pet_hook_config.json")
LOG_PATH = os.path.join(PET_DIR, "pet_hook.log")
LOG_MAX_BYTES = 200 * 1024

DEFAULT_CFG = {
    "permission_prompt": True,
    "idle_prompt": True,
    "stop": True,
    "prompt_submit": True,
    "session_start": True,
    "session_end": True,
    "subagent_stop": False,
    "tool_error": True,
    "dangerous_command": True,
    "clear_alert_on_tool": True,
    "permission_request": False,  # 2.1.153 的 PermissionRequest：先只记日志，确认不吵再开
    "permission_denied": False,   # 你拒绝了某次操作
    "tool_failure": True,         # PostToolUseFailure：工具失败（比从 PostToolUse 猜更准）
    "stop_failure": True,         # 一轮结束时出错
    "subagent_start": False,      # 子代理开跑
    "task_created": False,        # 建了任务
    "task_completed": False,      # 任务完成
    "compact": False,
    "task_tool": False,
    "quiet_seconds": 20,
    "auto_start": True,           # Claude 开工时顺手把宠物叫起来（已经在跑就不重复开）
    "log": True,
    "include_project": True,
}

DANGER_PATTERNS = (
    "rm -rf", "rmdir /s", "del /f", "del /q", "format ", "mkfs",
    "dd if=", "reg delete", "git reset --hard", "git clean -fd",
    "git push --force", "shutdown", "diskpart",
)

PERMISSION_TEXT = {
    "permission_prompt": "Claude 在等你批准一件事。",
    "idle_prompt": "Claude 在等你回话。",
    "elicitation_dialog": "Claude 想问你一个问题。",
}

# 已知事件（用来判断是不是「没见过的新事件」）
KNOWN_EVENTS = {
    "PreToolUse", "PostToolUse", "Notification", "UserPromptSubmit", "Stop",
    "SubagentStop", "SessionStart", "SessionEnd", "PreCompact",
    "PostToolUseFailure", "StopFailure", "SubagentStart", "PermissionRequest",
    "PermissionDenied", "TaskCreated", "TaskCompleted",
}

# 记录原始字段时，只看这几个（别把命令全文、文件内容抄进日志）
INTERESTING_KEYS = (
    "hook_event_name", "hook_event", "event", "notification_type", "tool_name",
    "cwd", "session_id", "source", "reason", "trigger", "matcher", "stop_hook_active",
)


def read_payload() -> tuple[dict, str]:
    """读 stdin 里的 JSON。

    Windows 上坑不少：
      1. pythonw 默认按系统编码（GBK）读，中文会读坏 —— 所以直接读字节、按 UTF-8 解；
      2. 有些 payload 里带原始换行/控制字符，严格 JSON 解析会报
         「Expecting ',' delimiter」—— 所以退一步用 strict=False；
      3. 实在解析不了，就用正则从文本里把关键字段捞出来，至少别丢通知。
    """
    raw = ""
    try:
        if hasattr(sys.stdin, "buffer"):
            raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        else:
            raw = sys.stdin.read()
    except Exception:
        raw = ""

    for kwargs in ({"strict": True}, {"strict": False}):
        try:
            return (json.loads(raw, **kwargs) if raw.strip() else {}), raw
        except Exception:
            pass

    # 兜底：用正则捞出关键字段
    salvaged: dict = {}
    for key in ("hook_event_name", "notification_type", "tool_name", "cwd", "source", "reason"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw)
        if m:
            salvaged[key] = m.group(1)
    return salvaged, raw


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    try:
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
    except Exception:
        pass
    return cfg


def load_memory() -> dict:
    try:
        with open(os.path.join(PET_DIR, "pet_hook_memory.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_memory(mem: dict) -> None:
    try:
        path = os.path.join(PET_DIR, "pet_hook_memory.json")
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(mem, fh)
        os.replace(path + ".tmp", path)
    except Exception:
        pass


def pet_running() -> bool:
    """宠物在不在跑？看它那个窗口就够了（比查进程快，也不怕同名进程）"""
    try:
        import ctypes
        return bool(ctypes.windll.user32.FindWindowW(None, "DesktopPet"))
    except Exception:
        return False


def pet_dir_of_hook() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def start_pet(cfg: dict) -> None:
    """把宠物悄悄叫起来：不弹黑框、不占着 Claude 的管道、失败也当没这回事"""
    if not cfg.get("auto_start", True) or os.environ.get("PET_NO_AUTOSTART"):
        return
    if pet_running():
        return
    pet_dir = pet_dir_of_hook()
    script = os.path.join(pet_dir, "pet.py")
    if not os.path.exists(script):
        return
    exe = sys.executable or "pythonw.exe"
    quiet = os.path.join(os.path.dirname(exe), "pythonw.exe")   # 无窗口解释器
    exe = quiet if os.path.exists(quiet) else exe
    try:
        flags = 0x00000008 | 0x08000000          # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen([exe, script], cwd=pet_dir, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        log("宠物没在跑，顺手把它叫起来了", cfg)
    except Exception as exc:
        log(f"叫宠物失败（不影响你干活）：{exc}", cfg)


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


def log(line: str, cfg: dict) -> None:
    if not cfg.get("log"):
        return
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-500:]
            with open(LOG_PATH, "w", encoding="utf-8") as fh:
                fh.writelines(tail)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def project_name(data: dict) -> str:
    for key in ("cwd", "project_dir", "workspace"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return os.path.basename(value.rstrip("\\/")) or value
    return os.path.basename(os.getcwd().rstrip("\\/")) or ""


def summarize(data: dict) -> str:
    """把一份原始 payload 压成一行摘要（值截断，不记录敏感大字段）"""
    parts = []
    for key in INTERESTING_KEYS:
        if key in data and not isinstance(data[key], (dict, list)):
            parts.append(f"{key}={str(data[key])[:70]}")
    if isinstance(data.get("prompt"), str):
        parts.append(f"prompt_len={len(data['prompt'])}")      # 只记长度，不抄你输入的内容
    keys = ",".join(sorted(data.keys()))[:260]
    return " ".join(parts) + f" || keys=[{keys}]"


def notify(cfg: dict, state: str = "idle", message: str = "", seconds: float | None = None,
           title: str = "", detail: str = "", icon: str = "",
           cwd: str = "", hint: str = "", session_id: str = "") -> None:
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
        "source": "claude-code",
    }
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        _replace(tmp, STATE_PATH)
    except Exception as exc:
        log(f"write state failed: {exc}", cfg)


def task_path(session_id: str, hint: str) -> str:
    key = session_id or hint or "claude"
    safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_.")[:60] or "claude"
    return os.path.join(TASKS_DIR, f"{safe}.json")


def write_task(cfg: dict, session_id: str, hint: str, state: str, title: str,
               detail: str, icon: str, cwd: str, tab: str = "") -> None:
    """把某个会话的状态写成一个任务文件；宠物会把多个会话叠起来显示"""
    try:
        os.makedirs(TASKS_DIR, exist_ok=True)
        tmp = task_path(session_id, hint) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"state": state, "title": title, "detail": detail, "icon": icon,
                       "cwd": cwd, "hint": hint, "session_id": session_id, "tab": tab,
                       "ts": time.time(), "source": "claude-code"}, fh, ensure_ascii=False, indent=2)
        _replace(tmp, task_path(session_id, hint))
    except Exception as exc:
        log(f"write task failed: {exc}", cfg)


def close_task(cfg: dict, session_id: str, hint: str) -> None:
    """会话结束：把这个任务从宠物身上撤掉"""
    try:
        path = task_path(session_id, hint)
        if os.path.exists(path):
            os.remove(path)
    except Exception as exc:
        log(f"close task failed: {exc}", cfg)


def looks_dangerous(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, dict):
        cmd = str(tool_input.get("command") or tool_input.get("cmd") or "")
    else:
        cmd = str(tool_input)
    low = cmd.lower()
    for pat in DANGER_PATTERNS:
        if pat in low:
            return cmd.strip()[:60]
    return ""


def tool_failed(data: dict) -> bool:
    resp = data.get("tool_response")
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError") or resp.get("error"):
            return True
        code = resp.get("exit_code", resp.get("exitCode"))
        if isinstance(code, int) and code != 0:
            return True
        text = str(resp.get("stderr") or "")[:400].lower()
        if "error" in text or "traceback" in text:
            return True
    return False


def decide(data: dict, cfg: dict, mem: dict):
    """把 Claude Code 的事件翻译成宠物要做的事。

    返回 None（安静）或一个字典：
        state  : idle / working / done / alert / sleep / say
        title  : 卡片标题（在忙什么）
        detail : 卡片明细（正在思考／执行了什么／结果如何）
        icon   : spinner / check / alert / info
    """
    event = str(data.get("hook_event_name") or data.get("hook_event") or data.get("event") or "")
    where = project_name(data) if cfg.get("include_project") else ""
    tool = str(data.get("tool_name") or data.get("toolName") or "")
    sid = str(data.get("session_id") or "")
    task = str((mem.get("titles") or {}).get(sid) or "")

    def title_of(text: str) -> str:
        text = " ".join(str(text).split())
        if len(text) > 18:
            text = text[:18] + "…"
        return f"{text}（{where}）" if where and len(text) <= 14 else text

    if event == "Notification":
        notif_type = str(data.get("notification_type") or data.get("notificationType") or "")
        if notif_type in PERMISSION_TEXT and cfg.get(notif_type):
            return {"state": "alert", "title": title_of(task or "Claude Code"),
                    "detail": PERMISSION_TEXT[notif_type], "icon": "alert"}
        return None

    if event == "Stop":
        if not cfg.get("stop"):
            return None
        summary = str(data.get("last_assistant_message") or "").strip()
        summary = " ".join(summary.split())
        if len(summary) > 90:
            summary = summary[:90] + "…"
        return {"state": "done", "title": title_of(task or "这一轮"), "detail": summary or "这一轮跑完了",
                "icon": "check"}

    if event == "UserPromptSubmit":
        if not cfg.get("prompt_submit"):
            return None
        prompt = " ".join(str(data.get("prompt") or "").split())
        if sid and prompt and not (mem.get("firsts") or {}).get(sid):
            mem.setdefault("firsts", {})[sid] = prompt[:60]   # 第一句话，多半就是那个标签页的名字
        return {"state": "working", "title": title_of(prompt or "新任务"),
                "detail": "正在思考…", "icon": "spinner"}

    if event == "PreToolUse":
        danger = looks_dangerous(data)
        if danger and cfg.get("dangerous_command"):
            return {"state": "alert", "title": title_of(task or "危险命令"),
                    "detail": f"拦下了：{danger}", "icon": "alert"}
        if tool == "Task" and cfg.get("task_tool"):
            return {"state": "working", "title": title_of(task), "detail": "派出子任务", "icon": "spinner"}
        if tool == "Bash" and cfg.get("clear_alert_on_tool"):
            cmd = ""
            ti = data.get("tool_input")
            if isinstance(ti, dict):
                cmd = str(ti.get("command") or "")
            cmd = " ".join(cmd.split())[:40]
            return {"state": "working", "title": title_of(task or "执行命令"),
                    "detail": f"执行：{cmd}" if cmd else "正在执行…", "icon": "spinner"}
        return None

    if event == "PostToolUse":
        if cfg.get("tool_error") and tool_failed(data):
            return {"state": "alert", "title": title_of(task), "detail": f"{tool or '工具'} 出错了", "icon": "alert"}
        return None

    if event == "PermissionRequest":
        if cfg.get("permission_request"):
            return {"state": "alert", "title": title_of(task), "detail": f"想动 {tool or '某个工具'}，等你点头",
                    "icon": "alert"}
        return None

    if event == "PermissionDenied":
        if not cfg.get("permission_denied"):
            return None
        return {"state": "say", "message": f"你拒绝了 {tool or '这次操作'}", "seconds": 5.0}

    if event == "PostToolUseFailure":
        if not cfg.get("tool_failure"):
            return None
        why = ""
        resp = data.get("tool_response")
        if isinstance(resp, dict):
            why = " ".join(str(resp.get("error") or resp.get("stderr") or "").split())[:40]
        return {"state": "alert", "title": title_of(task),
                "detail": f"{tool or '工具'} 失败：{why}" if why else f"{tool or '工具'} 失败了",
                "icon": "alert"}

    if event == "StopFailure":
        if not cfg.get("stop_failure"):
            return None
        return {"state": "alert", "title": title_of(task), "detail": "这一轮出错了", "icon": "alert"}

    if event == "SubagentStart":
        if not cfg.get("subagent_start"):
            return None
        return {"state": "working", "title": title_of(task), "detail": "子代理开跑", "icon": "spinner"}

    if event == "TaskCreated":
        if not cfg.get("task_created"):
            return None
        return {"state": "working", "title": title_of(str(data.get("task_subject") or "新任务")),
                "detail": "已建立任务", "icon": "spinner"}

    if event == "TaskCompleted":
        if not cfg.get("task_completed"):
            return None
        return {"state": "done", "title": title_of(str(data.get("task_subject") or "任务")),
                "detail": "任务完成", "icon": "check"}

    if event == "SubagentStop":
        if not cfg.get("subagent_stop"):
            return None
        return {"state": "say", "message": "子任务完成", "seconds": 3.0}

    if event == "SessionStart":
        if not cfg.get("session_start"):
            return None
        return {"state": "say", "message": f"Claude 开工了（{where}）" if where else "Claude 开工了",
                "seconds": 4.0}

    if event == "SessionEnd":
        if not cfg.get("session_end"):
            return None
        return {"state": "idle"}

    if event == "PreCompact":
        if not cfg.get("compact"):
            return None
        return {"state": "working", "title": title_of(task), "detail": "正在整理记忆…", "icon": "spinner"}

    return None


def main() -> int:
    cfg = load_cfg()
    data, raw = read_payload()
    if not data:
        log(f"stdin unreadable, raw={raw[:300]!r}", cfg)
        return 0
    if raw and "hook_event_name" not in data:
        log(f"payload 只捞到部分字段，raw 前 300 字：{raw[:300]!r}", cfg)

    try:
        event = str(data.get("hook_event_name") or data.get("hook_event") or data.get("event") or "?")
        if event in ("SessionStart", "UserPromptSubmit"):
            start_pet(cfg)          # Claude 开工了，宠物也该上场（已在跑就不动它）
        mem = load_memory()
        decision = decide(data, cfg, mem)
        now = time.time()
        last = float(mem.get(event, 0) or 0)
        quiet = float(cfg.get("quiet_seconds") or 0)

        # 每类事件（含它的子类型）第一次见到时，把原始字段记下来，方便以后校准
        variant = (str(data.get("notification_type") or data.get("notificationType") or "")
                   or str(data.get("tool_name") or data.get("toolName") or ""))
        seen_key = f"seen:{event}:{variant}"
        if not mem.get(seen_key):
            mem[seen_key] = 1
            log(f"RAW {event} :: {summarize(data)}", cfg)
        if event not in KNOWN_EVENTS:
            log(f"UNKNOWN {event} :: {summarize(data)}", cfg)

        if decision is None:
            save_memory(mem)
            log(f"{event} -> (安静)", cfg)
        elif quiet and decision.get("state") == "alert" and now - last < quiet:
            save_memory(mem)
            log(f"{event} -> 抑制（{int(quiet)}s 内已提示过）", cfg)
        else:
            sid = str(data.get("session_id") or "")
            cwd = str(data.get("cwd") or "")
            hint = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
            state = str(decision.get("state") or "")
            title = str(decision.get("title") or "")
            detail = str(decision.get("detail") or "")

            if event == "SessionEnd":
                close_task(cfg, sid, hint)             # 会话结束：把它那一条从宠物身上撤掉

            if title or (detail and state != "say"):
                # 一次会话 = 一张任务卡。多个会话同时开着，宠物会把它们叠成一叠。
                write_task(cfg, sid, hint, state, title, detail,
                           str(decision.get("icon") or ""), cwd,
                           tab=str((mem.get("firsts") or {}).get(sid) or ""))
                if title:
                    mem.setdefault("titles", {})[sid] = title    # 记住这个会话在忙什么
                mem[event] = now
                save_memory(mem)
                log(f"{event} -> {state} [任务] | {title} :: {detail}", cfg)
            else:
                notify(cfg, cwd=cwd, hint=hint, session_id=sid, **decision)
                mem[event] = now
                save_memory(mem)
                log(f"{event} -> {state} | "
                    f"{title} :: {detail or decision.get('message', '')}", cfg)
    except Exception as exc:
        log(f"handle failed: {exc}", cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
