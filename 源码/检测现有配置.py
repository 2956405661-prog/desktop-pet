# -*- coding: utf-8 -*-
"""看看这台机器上"要不要填 API"——能读到就沿用，读不到才让人手填。

只读本机、只读自己用户的配置，不联网、不上传、不打印密钥本身。
安装向导会直接调用这里的 detect()。
"""
from __future__ import annotations

import json
import os
import re

SECRET_RE = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.I)

# Claude Code 认的这几个键（顺序＝推荐顺序）
FIELDS = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "CLAUDE_CODE_EFFORT_LEVEL",
)


def mask(value: str) -> str:
    value = str(value)
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:5]}{'*' * 6}{value[-3:]}（共 {len(value)} 位）"


def claude_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude")


def from_settings() -> dict:
    """① 用户的 ~/.claude/settings.json 里 env 段（最准，因为 Claude Code 就用它）"""
    path = os.path.join(claude_dir(), "settings.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        env = data.get("env") or {}
        return {k: str(v) for k, v in env.items() if k in FIELDS}
    except Exception:
        return {}


def from_environment() -> dict:
    """② 系统环境变量（有些人是 setx 进去的）"""
    return {k: os.environ[k] for k in FIELDS if os.environ.get(k)}


def from_credentials() -> dict:
    """③ 用官方账号登录时，钥匙可能在这个文件里"""
    found = {}
    for name in (".credentials.json", "credentials.json"):
        path = os.path.join(claude_dir(), name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        text = json.dumps(data)
        for key in ("accessToken", "access_token", "apiKey", "api_key"):
            m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
            if m:
                found["ANTHROPIC_AUTH_TOKEN"] = m.group(1)
                found["_source_extra"] = f"来自 {name} 的登录凭据"
                break
    return found


def login_state() -> dict:
    """官方订阅（Pro/Max）登录态：只看「有没有登录过」，不去搬它的令牌。

    订阅用户的钥匙由 Claude Code 自己保管并自动刷新，**不需要、也不应该**
    写进 settings.json 的 env —— 写进去反而会顶掉官方登录机制。
    所以这一档的结论是"什么都不用填，直接跳过 API 页"。
    """
    info = {"logged_in": False, "email": "", "plan": "", "where": ""}
    home = os.path.expanduser("~")

    cred = os.path.join(claude_dir(), ".credentials.json")
    if os.path.exists(cred):
        info.update(logged_in=True, where=".claude/.credentials.json")
        try:
            with open(cred, "r", encoding="utf-8") as fh:
                text = fh.read()
            for key in ("subscriptionType", "subscription_type", "plan"):
                m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
                if m:
                    info["plan"] = m.group(1)
                    break
        except Exception:
            pass

    cfg_file = os.path.join(home, ".claude.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            account = data.get("oauthAccount") or {}
            if account:
                info["logged_in"] = True
                info["email"] = str(account.get("emailAddress") or "")
                info["plan"] = info["plan"] or str(account.get("organizationType") or "")
                info["where"] = (info["where"] + " + " if info["where"] else "") + ".claude.json 的 oauthAccount"
        except Exception:
            pass

    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        info["logged_in"] = True
        info["where"] = (info["where"] + " + " if info["where"] else "") + "环境变量 CLAUDE_CODE_OAUTH_TOKEN"
    return info


def detect() -> dict:
    """返回 {"config": {...}, "source": "...", "mode": "...", "need_input": bool}

    mode 四种：subscription（订阅已登录，跳过）/ third_party / official_api / none（手填）
    """
    # 注意：故意不去读 .credentials.json 里的令牌 —— 订阅的令牌属于 Claude Code 自己，
    # 抄进 settings.json 的 env 会顶掉官方登录、而且换台机器多半也用不了。
    for getter, source in ((from_settings, "settings.json 的 env 段"),
                           (from_environment, "系统环境变量")):
        found = getter()
        if found:
            extra = found.pop("_source_extra", "")
            mode = "第三方端点" if found.get("ANTHROPIC_BASE_URL") else "官方接口"
            return {"config": found, "source": f"{source}（{mode}）",
                    "mode": "third_party" if found.get("ANTHROPIC_BASE_URL") else "official_api",
                    "need_input": False, "extra": extra}
    login = login_state()
    if login["logged_in"]:
        return {"config": {}, "source": f"官方订阅已登录（{login['where']}）",
                "mode": "subscription", "need_input": False,
                "extra": f"账号：{login['email'] or '（没读到邮箱，但不影响）'}"
                         + (f"，套餐：{login['plan']}" if login["plan"] else "")}
    return {"config": {}, "source": "什么都没找到", "mode": "none",
            "need_input": True, "extra": ""}


def summary(result: dict) -> str:
    lines = [f"来源：{result['source']}"]
    if result.get("extra"):
        lines.append(f"       {result['extra']}")
    if result["mode"] == "subscription":
        lines.append("结论：订阅用户不需要填任何 API —— 钥匙由 Claude Code 自己保管并自动刷新；")
        lines.append("      安装时只写钩子，API 这一页直接跳过（绝不能把令牌抄出来）")
        return "\n".join(lines)
    cfg = result["config"]
    if not cfg:
        lines.append("结论：这台机器上没有现成的 API 配置 → 安装时应让用户手填")
        return "\n".join(lines)
    lines.append(f"读到 {len(cfg)} 项：")
    for key in FIELDS:
        if key in cfg:
            value = mask(cfg[key]) if SECRET_RE.search(key) else str(cfg[key])[:70]
            lines.append(f"  {key:36s} = {value}")
    lines.append("结论：可以「沿用现有配置」，用户不用手填，只要点下一步")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary(detect()))
