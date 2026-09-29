# -*- coding: utf-8 -*-
"""版本号 + "有没有新版本"的检查（宠物启动后自己用）。

设计原则：
  1. 最多发两个 GET（主用 CDN、备用 raw），拿一个小 JSON；**不上传任何用户数据**（连机器码都不带）；
  2. 断网、超时、格式不对 —— 一律当"没有更新"，绝不打扰用户；
  3. 用户可以一键关掉（pet_config.json 里 update_check=false）；
  4. 清单就是一个静态文件，放哪都行（GitHub raw / Gitee / 自己的服务器 / 对象存储）。

清单长这样（update.json）：
    {
      "version": "1.1.0",
      "notes": "修了尾巴接缝；点卡片支持跳到标签页",
      "url": "https://example.com/桌面宠物-1.1.0-安装程序.exe"
    }
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

VERSION = "1.0.1"
DEFAULT_MANIFEST = (
    "https://cdn.jsdelivr.net/gh/2956405661-prog/desktop-pet@main/update.json",
    "https://raw.githubusercontent.com/2956405661-prog/desktop-pet/main/update.json",
)


def parse_version(text: str) -> tuple:
    """把 "1.2.3" / "v1.2.3-beta" 变成能比大小的数字元组"""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def newer_than(candidate: str, current: str = VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def check_for_update(manifest_url=DEFAULT_MANIFEST, current: str = VERSION,
                     timeout: float = 3.0) -> dict | None:
    """有新版本就返回清单，否则返回 None。永远不抛异常。

    manifest_url 可以是单个地址，也可以是一串地址（主用 jsDelivr CDN、备用 GitHub raw）。
    **按顺序问，谁先报出新版本就用谁。**

    关键：某份清单说自己不比当前新时，不能就此收工 —— CDN 有缓存，刚发版那半天它可能
    还端着旧清单，得继续问下一个地址（raw 是实时的）。这里以前就是栽在这个"提前收工"上。
    超时给得短（默认 3 秒 × 最多两个地址），因为这段是在界面线程里跑的，不能让人看出来卡。
    """
    urls = [manifest_url] if isinstance(manifest_url, str) else list(manifest_url or [])
    for url in urls:
        if not url:
            continue
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"DesktopPet/{current}",
                              "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            continue                       # 这个地址不通就试下一个，全都安静处理
        if not isinstance(data, dict):
            continue
        if not newer_than(data.get("version"), current):
            continue                       # 这份没比现在新（可能是 CDN 缓存的旧货）→ 继续问下一个
        return {"version": str(data.get("version")),
                "notes": str(data.get("notes") or "有新版本啦"),
                "url": str(data.get("url") or ""),
                "from": url}
    return None


def due(last_checked: float, interval_hours: float = 24.0) -> bool:
    """距离上次检查够久了吗（默认一天一次，别没事就联网）"""
    return (time.time() - float(last_checked or 0)) >= interval_hours * 3600
