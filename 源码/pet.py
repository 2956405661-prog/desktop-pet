# -*- coding: utf-8 -*-
"""
桌面宠物（仿 Mini 的悬浮小宠物）

一只趴在桌面上的小家伙：置顶、无边框、背景透明、可拖拽。
任何软件都可以让它动起来、说话、提醒你——只要往 pet_state.json 里写一行 JSON，
或者调用 petctl.py（见 README.md）。

运行：
    python pet.py            正常启动
    python pet.py --selftest  只做自检（不弹窗），用于排查问题

依赖：Python 3.9+，标准库 + Pillow（只有气泡文字和缩放需要它，缺了也能跑）
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import re
import sys
import time
import webbrowser
import tkinter as tk

try:
    from update_check import VERSION, check_for_update
except Exception:                      # 单独跑 pet.py 时也不许因为少个模块起不来
    VERSION = "1.0.0"

    def check_for_update(*_a, **_k):
        return None

# 打包成 exe 之后 __file__ 指向临时解包目录，配置/素材/任务卡得跟着 exe 走
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_DIR, "pet_assets")
CONFIG_PATH = os.path.join(APP_DIR, "pet_config.json")
STATE_PATH = os.path.join(APP_DIR, "pet_state.json")
TASKS_DIR = os.path.join(APP_DIR, "pet_tasks")     # 每个会话一个任务文件

KEY_COLOR = "#010203"          # 透明色（画面里不会用到这个颜色）
HERO = 4                       # 气泡与缩放的超采样倍数

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    HAS_PIL = True
except Exception:              # pragma: no cover
    HAS_PIL = False

try:
    import winsound
except Exception:              # pragma: no cover
    winsound = None

DEFAULT_CONFIG = {
    "size": "中",                     # 小 / 中 / 大
    "scale": {"小": 0.7, "中": 1.0, "大": 1.45},
    "x": None,                        # 窗口位置，None = 右下角
    "y": None,
    "margin": 24,                     # 贴边吸附距离
    "hotkey": "ctrl+alt+p",           # 显示/隐藏快捷键
    "always_on_top": True,
    "sound": True,                    # 完成/提醒时播放系统提示音
    "idle_talk": True,                # 无聊时自言自语
    "idle_talk_min_sec": 180,
    "idle_talk_max_sec": 420,
    "demo_seconds": 6.0,              # 手动「演示」持续多久后回到真实状态
    "alert_seconds": 180.0,           # 「要你确认」最多瞪你多久，超时自动收回
    "state_poll_seconds": 0.08,       # 多快去瞄一眼状态文件（越小反应越快）
    "task_poll_seconds": 0.08,        # 多快去瞄一眼任务卡目录（一个会话一张卡）
    "card_seconds": 0.0,              # 结果卡片停留多久；0 = 一直留着（直到你点它或来了新状态）
    "task_ttl": 1800,                 # 任务卡活多久（秒）：太久没动静的会话卡片自动收掉
    "follow_claude": True,            # 跟着 Claude Code 一起进退：它关了，宠物过一会儿也退下
    "exit_grace_seconds": 30,         # Claude 关了之后再守多久才退场（秒）
    "claude_check_seconds": 5,        # 多久查一次 Claude 还在不在
    "update_check": True,             # 是否检查新版本（只读一个公开的小文件，不上传任何东西）
    "update_manifest": None,          # 版本清单地址；None＝用内置的两个（CDN + raw）
    "update_interval_hours": 24,      # 多久查一次
    "update_delay_seconds": 20,       # 启动后隔多久才去查（别跟启动抢资源）
    "fps_scale": 1.0,                 # 帧率倍率：<1 更快更顺（更费 CPU），>1 更慢更省
    "jump_command": "",               # 自定义「点卡片跳转」命令，留空＝自动找窗口
    "jump_clear": True,               # 跳转成功后是否把卡片收走
    "jump_open_folder": False,        # 找不到窗口时，是否退化成「用 VS Code / 终端打开那个目录」
    "select_tab": True,               # 跳到 VS Code 后，再按名字点名对应的标签页
    "tab_script": "",                 # 点名标签页的脚本位置（留空＝同目录的 select_vscode_tab.ps1）
    "bubble_seconds": 6.0,
    "font": "",                       # 留空自动挑选中文字体
    "spritesheet": None,              # 想用精灵图（一张图多帧）就填这里，见 README
}

MOODS = ("idle", "working", "done", "alert", "sleep")
MOOD_LABEL = {"idle": "待机", "working": "干活中", "done": "搞定", "alert": "要你确认", "sleep": "睡觉"}
# 右键菜单里的五个动作名（干净、只说状态本身）
# 右键菜单：按「宠物会做出什么动作」来命名，不是状态名
MENU_LABEL = {
    "working": "转齿轮",
    "done": "蹦蹦跳",
    "alert": "吓一跳",
    "sleep": "打呼噜",
    "idle": "发呆",
}

IDLE_TALK = [
    "要不要伸个懒腰？",
    "我一直在这儿看着呢。",
    "咕噜咕噜……",
    "忙完了记得喝水呀。",
    "有活儿就叫我。",
    "今天的桌子好亮。",
]
PET_TALK = [
    "嘿嘿，好痒。",
    "别闹～",
    "摸头加一。",
    "我在的，随时喊我。",
    "呼噜……继续忙你的。",
]
STATE_TALK = {
    "working": "我盯着呢，你忙你的。",
    "done": "搞定啦！",
    "alert": "这个需要你看一眼。",
    "sleep": "那我先眯一会儿……",
    "idle": "我在这儿。",
}


# ----------------------------------------------------------------- 配置

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except Exception as exc:
            print(f"[pet] 配置文件读取失败，已用默认值：{exc}")
    return cfg


def save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def pick_font_path(cfg: dict) -> str | None:
    if cfg.get("font"):
        return cfg["font"]
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\Deng.ttf",       # 等线
        r"C:\Windows\Fonts\simhei.ttf",     # 黑体
        r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ----------------------------------------------------------------- 素材

NATIVE_PX = 128        # 96 DPI、尺寸=中 时的显示像素（素材本身是 2 倍分辨率）


class Assets:
    """加载动画帧；支持普通帧目录，也支持「一张精灵图切多帧」。

    素材以 2 倍分辨率保存（256px），按需要缩放到显示尺寸 —— 在高 DPI 屏上才不会糊。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.src: dict[str, list] = {}        # 源图（PIL）
        self.delay: dict[str, int] = {}
        self.source_px = NATIVE_PX
        self._cache: dict[tuple, list] = {}   # (动作, 目标像素) -> PhotoImage
        self._src_cache: list[str] = []       # 源图按需加载，最多同时留 2 套，省内存
        self._files: dict[str, list] = {}
        self._load()

    # -- 读取
    def _load_manifest(self) -> dict:
        path = os.path.join(ASSET_DIR, "manifest.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    def _load(self) -> None:
        sheet = self.cfg.get("spritesheet") or None
        if sheet and HAS_PIL:
            self._load_spritesheet(sheet)
            return
        manifest = self._load_manifest()
        self.source_px = int(manifest.get("size", NATIVE_PX))
        for mood in MOODS:
            folder = os.path.join(ASSET_DIR, mood)
            files = sorted(f for f in os.listdir(folder) if f.endswith(".png")) \
                if os.path.isdir(folder) else []
            if not files:
                continue
            self._files[mood] = [os.path.join(folder, f) for f in files]
            self.delay[mood] = int(manifest.get("states", {}).get(mood, {}).get("delay_ms", 120))

    def _sources(self, mood: str) -> list:
        """按需加载某个动作的源图（384px 的图全套放内存太占地方）"""
        if mood in self.src:
            self._src_cache.append(mood)
            return self.src[mood]
        files = self._files.get(mood) or []
        if not files:
            return []
        if not HAS_PIL:
            self.src[mood] = files
        else:
            self.src[mood] = [Image.open(f).convert("RGBA") for f in files]
        self._src_cache.append(mood)
        while len(self._src_cache) > 2:        # 只留最近用到的两套
            old = self._src_cache.pop(0)
            if old != mood and self._src_cache.count(old) == 0:
                self.src.pop(old, None)
        return self.src[mood]

    def _load_spritesheet(self, sheet: dict) -> None:
        """精灵图：一张 PNG/WEBP，按 frame_w/frame_h 切片，rows 指定每个动作在第几行。"""
        img = Image.open(sheet["path"]).convert("RGBA")
        fw, fh = int(sheet["frame_w"]), int(sheet["frame_h"])
        rows = sheet.get("rows", {})
        counts = sheet.get("counts", {})
        self.source_px = fh
        for mood, row in rows.items():
            count = int(counts.get(mood, img.width // fw))
            self.src[mood] = [img.crop((i * fw, int(row) * fh, (i + 1) * fw, (int(row) + 1) * fh))
                              for i in range(count)]
            self.delay[mood] = int(sheet.get("delay_ms", {}).get(mood, 120))
        for mood in MOODS:                     # rows 里没写的动作，借用 idle
            if mood not in self.src and self.src.get("idle"):
                self.src[mood] = self.src["idle"]

    @staticmethod
    def _harden(img):
        """把半透明边缘压成硬边：透明色方案需要「要么完全不透明、要么完全透明」。"""
        r, g, b, a = img.split()
        a = a.point(lambda v: 255 if v >= 118 else 0)
        out = Image.new("RGBA", img.size, (0, 0, 0, 0))
        out.paste(img.convert("RGB"), (0, 0), a)
        return out

    # -- 取用（按目标像素缓存）
    def frames_for(self, mood: str, px: int) -> list:
        """取某个动作在指定显示像素下的帧。"""
        px = max(16, int(px))
        key = (mood, px)
        if key in self._cache:
            return self._cache[key]
        out = []
        for item in self._sources(mood):
            if isinstance(item, str):          # 没有 Pillow：直接用原图
                out.append(tk.PhotoImage(file=item))
                continue
            img = item if item.width == px else item.resize((px, px), Image.LANCZOS)
            out.append(to_photo(self._harden(img)))
        self._cache[key] = out
        return out


def make_stack_frames(count: int, title: str, icon: str, width: int,
                      font_path: str | None, scale: float = 1.0, steps: int = 10):
    """折叠态：像一叠卡片，显示「有几个任务 + 最新那条在忙什么」"""
    if not HAS_PIL:
        return []
    base = make_card_frames(title, f"共 {count} 个任务 · 点开查看", icon, width, font_path, scale, steps)
    if not base:
        return []
    pad = max(3, int(4 * scale))
    r = max(7, int(9 * scale))
    out = []
    for frame in base:
        w, h = frame.size
        canvas = Image.new("RGBA", (w + pad * 2 + r * 2 + 8, h + pad * 2 + 2), (0, 0, 0, 0))
        mask = frame.split()[3].point(lambda v: 255 if v > 0 else 0)
        for layer in (2, 1):                       # 后面垫两层，往右下错开，做出"一叠"的观感
            back = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            back.paste(CARD_BG2 + (255,), (0, 0), mask)
            bd = ImageDraw.Draw(back)
            bd.rounded_rectangle([0, 0, w - 1, h - 1], radius=max(4, int(15 * scale)),
                                 outline=(58, 66, 78), width=max(1, int(1.4 * scale)))
            canvas.alpha_composite(back, (pad * layer, pad * layer))
        canvas.alpha_composite(frame, (0, 0))
        d = ImageDraw.Draw(canvas)
        cx, cy = w + pad * 2 + r + 3, min(h * 0.5, canvas.height - r - 2)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(232, 74, 74))
        try:
            fnt = ImageFont.truetype(font_path, max(8, int(11 * scale))) if font_path \
                else ImageFont.load_default()
        except Exception:
            fnt = ImageFont.load_default()
        d.text((cx, cy), str(count), font=fnt, fill=(255, 255, 255), anchor="mm")
        out.append(canvas)
    return out


def make_task_list(entries: list, width: int, font_path: str | None, scale: float = 1.0,
                   more: int = 0, total: int | None = None):
    """展开态：一行一个任务。返回 (图, 行矩形)；行矩形用来判断点到了哪一条。

    more > 0 表示还有几个任务这一屏放不下，底部补一行「翻页」。
    """
    if not HAS_PIL:
        return None, []
    title_size = max(11, int(13 * scale))
    detail_size = max(9, int(10.5 * scale))
    icon_r = 8 * scale
    pad = 11 * scale
    radius = 15 * scale
    header_h = int(27 * scale)
    row_h = int(35 * scale)

    def font(size):
        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, int(size * HERO))
            except Exception:
                pass
        return ImageFont.load_default()

    f_title, f_detail = font(title_size), font(detail_size)

    def fit(text, fnt, limit):
        text = " ".join(str(text).split())
        if fnt.getlength(text) <= limit * HERO:
            return text
        while text and fnt.getlength(text + "…") > limit * HERO:
            text = text[:-1]
        return text + "…"

    w = int(width * HERO)
    rows_n = len(entries) + (1 if more else 0)
    h = int((header_h + row_h * rows_n + pad * 0.7) * HERO)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius * HERO, fill=255)

    color = Image.new("RGB", (w, h), CARD_BG)
    cd = ImageDraw.Draw(color)
    cd.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius * HERO, fill=CARD_BG,
                         outline=(58, 66, 78), width=max(1, int(1.6 * HERO)))
    cd.text((pad * HERO, header_h * HERO * 0.40), "▼ 收起", font=f_detail, fill=ROW_STATUS)
    cd.text((w - pad * HERO, header_h * HERO * 0.40), f"{total or len(entries)} 个任务",
            font=f_detail, fill=ROW_STATUS, anchor="ra")
    cd.line([(pad * 0.6 * HERO, header_h * HERO), (w - pad * 0.6 * HERO, header_h * HERO)],
            fill=(48, 56, 68), width=max(1, int(HERO * 0.8)))

    rows = [(0, header_h, None)]
    for idx, item in enumerate(entries):
        y0, y1 = header_h + row_h * idx, header_h + row_h * (idx + 1)
        rows.append((y0, y1, item.get("key")))
        if idx:
            cd.line([(pad * 0.6 * HERO, y0 * HERO), (w - pad * 0.6 * HERO, y0 * HERO)],
                    fill=(40, 47, 58), width=max(1, int(HERO * 0.7)))
        cy = (y0 + row_h / 2) * HERO
        _draw_icon(cd, pad * HERO + icon_r * HERO, cy, icon_r * HERO,
                   item.get("icon") or "info", 0.0)
        tx = pad * HERO + icon_r * 2.6 * HERO
        status = item.get("status_text") or ""
        limit = width - tx / HERO - pad - (58 if status else 4)
        cd.text((tx, y0 * HERO + row_h * HERO * 0.13),
                fit(item.get("title") or "", f_title, limit), font=f_title, fill=CARD_TITLE)
        cd.text((tx, y0 * HERO + row_h * HERO * 0.53),
                fit(item.get("detail") or "", f_detail, limit + 12), font=f_detail, fill=CARD_DETAIL)
        if status:
            cd.text((w - pad * HERO, cy), status, font=f_detail, fill=ROW_STATUS, anchor="rm")

    if more:
        idx = len(entries)
        y0, y1 = header_h + row_h * idx, header_h + row_h * (idx + 1)
        rows.append((y0, y1, "__more__"))
        cd.line([(pad * 0.6 * HERO, y0 * HERO), (w - pad * 0.6 * HERO, y0 * HERO)],
                fill=(40, 47, 58), width=max(1, int(HERO * 0.7)))
        cy = (y0 + row_h / 2) * HERO
        _draw_icon(cd, pad * HERO + icon_r * HERO, cy, icon_r * HERO, "info", 0.0)
        tx = pad * HERO + icon_r * 2.6 * HERO
        cd.text((tx, cy), f"还有 {more} 个任务 · 点这里翻页", font=f_detail,
                fill=ROW_STATUS, anchor="lm")

    color = color.resize((w // HERO, h // HERO), Image.LANCZOS)
    mask = mask.resize((w // HERO, h // HERO), Image.LANCZOS)
    mask = mask.point(lambda v: 255 if v >= 118 else 0)
    img = color.convert("RGBA")
    img.putalpha(mask)
    # 注意：a/b 本来就是在「最终像素」这一档算的（图是缩 HERO 倍回来的），
    # 再除一次 HERO 行坐标就会缩成四分之一 —— 点哪一条都对不上，看着就是「点了没反应」
    rows = [(int(a), int(b), k) for a, b, k in rows]
    return img, rows


# ----------------------------------------------------------------- 气泡

CARD_BG = (18, 22, 28)
CARD_BG2 = (30, 36, 44)
CARD_TITLE = (255, 255, 255)
CARD_DETAIL = (178, 188, 200)
ROW_STATUS = (146, 158, 172)
CARD_DETAIL = (178, 188, 200)
SPINNER = (138, 180, 248)
SPINNER_TRACK = (58, 68, 82)
CHECK_GREEN = (52, 199, 89)
ALERT_RED = (255, 107, 107)
INFO_BLUE = (122, 158, 248)


def _draw_icon(draw, cx, cy, r, icon, phase=0.0):
    """画卡片左边那个小图标：转圈 / 绿勾 / 红叹号 / 蓝 i"""
    box = [cx - r, cy - r, cx + r, cy + r]
    w = max(1, int(r * 0.30))
    if icon == "spinner":
        draw.ellipse(box, outline=SPINNER_TRACK, width=w)
        draw.arc(box, start=phase, end=phase + 270, fill=SPINNER, width=w)
    elif icon == "check":
        draw.ellipse(box, fill=CHECK_GREEN)
        cut = max(1, int(r * 0.34))
        draw.line([(cx - r * 0.46, cy + r * 0.04), (cx - r * 0.12, cy + r * 0.40),
                   (cx + r * 0.50, cy - r * 0.36)], fill=(255, 255, 255), width=cut, joint="curve")
    elif icon == "alert":
        draw.ellipse(box, fill=ALERT_RED)
        draw.rounded_rectangle([cx - r * 0.13, cy - r * 0.52, cx + r * 0.13, cy + r * 0.16],
                               radius=r * 0.13, fill=(255, 255, 255))
        draw.ellipse([cx - r * 0.17, cy + r * 0.30, cx + r * 0.17, cy + r * 0.64], fill=(255, 255, 255))
    else:  # info
        draw.ellipse(box, fill=INFO_BLUE)
        draw.ellipse([cx - r * 0.15, cy - r * 0.60, cx + r * 0.15, cy - r * 0.30], fill=(255, 255, 255))
        draw.rounded_rectangle([cx - r * 0.14, cy - r * 0.16, cx + r * 0.14, cy + r * 0.58],
                               radius=r * 0.14, fill=(255, 255, 255))


def make_card_frames(title: str, detail: str, icon: str, width: int,
                     font_path: str | None, scale: float = 1.0, steps: int = 10):
    """状态卡片：左边一个图标，右边「标题 + 一行明细」。

    icon="spinner" 时返回多帧（转圈动画），其余返回 1 帧。
    """
    if not HAS_PIL:
        return []
    title_size = max(11, int(13 * scale))
    detail_size = max(10, int(12 * scale))
    icon_r = 11 * scale
    pad = 11 * scale
    gap = 9 * scale
    radius = 15 * scale

    def font(size):
        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, int(size * HERO))
            except Exception:
                pass
        return ImageFont.load_default()

    f_title, f_detail = font(title_size), font(detail_size)
    max_w = max(150, width)
    text_w = max_w - pad * 2 - icon_r * 2 - gap

    def fit(text, fnt, limit):
        text = " ".join(str(text).split())
        if fnt.getlength(text) <= limit * HERO:
            return text
        while text and fnt.getlength(text + "…") > limit * HERO:
            text = text[:-1]
        return text + "…"

    title = fit(title or "…", f_title, text_w)

    # 英文按单词断，中文按字断（否则会出现 output / s 这种断法）
    tokens: list[str] = []
    buf = ""
    for ch in " ".join(str(detail).split()):
        if ch.isascii() and not ch.isspace():
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            if ch == " ":
                tokens.append(" ")
            else:
                tokens.append(ch)
    if buf:
        tokens.append(buf)

    lines: list[str] = []
    cur = ""
    truncated = False
    for tk in tokens:
        cand = cur + tk
        if f_detail.getlength(cand) > text_w * HERO and cur.strip():
            lines.append(cur.rstrip())
            cur = "" if tk == " " else tk
            if len(lines) == 2:
                truncated = True
                break
        else:
            cur = cand
    if cur.strip() and len(lines) < 2:
        lines.append(cur.rstrip())
    if truncated:
        while lines[1] and f_detail.getlength(lines[1] + "…") > text_w * HERO:
            lines[1] = lines[1][:-1]
        lines[1] += "…"
    lines = lines or [""]

    # 卡片宽度跟着内容走（短就窄，长就宽，最多 max_w）
    natural = max([f_title.getlength(title)] + [f_detail.getlength(l) for l in lines]) / HERO
    card_w = int(min(max_w, max(146, natural + pad * 2 + icon_r * 2 + gap)))

    title_h = int(title_size * HERO * 1.42)
    detail_h = int(detail_size * HERO * 1.38)
    content_h = title_h + detail_h * len(lines)
    height = int(max(content_h + pad * 2, icon_r * 2 + pad * 1.6))
    w = int(card_w * HERO)
    h = height

    # spinner 给多帧（转圈）；alert 给两帧（边框一明一暗，像在喘气，好引起注意）
    if icon == "spinner":
        phases = [i * (360.0 / steps) for i in range(steps)]
        borders = [(46, 54, 66)] * len(phases)
    elif icon == "alert":
        phases = [0.0, 0.0]
        borders = [(58, 66, 78), (176, 84, 84)]
    else:
        phases, borders = [0.0], [(46, 54, 66)]

    frames: list = []
    for phase, border in zip(phases, borders):
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius * HERO, fill=255)

        color = Image.new("RGB", (w, h), CARD_BG)
        cd = ImageDraw.Draw(color)
        cd.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius * HERO, fill=CARD_BG,
                             outline=border, width=max(1, int(1.6 * HERO)))
        _draw_icon(cd, pad * HERO + icon_r * HERO, h / 2, icon_r * HERO, icon, phase)

        tx = pad * HERO + icon_r * 2 * HERO + gap * HERO
        ty = (h - content_h) / 2
        cd.text((tx, ty), title, font=f_title, fill=CARD_TITLE)
        ty += title_h
        for line in lines:
            cd.text((tx, ty), line, font=f_detail, fill=CARD_DETAIL)
            ty += detail_h

        color = color.resize((w // HERO, h // HERO), Image.LANCZOS)
        mask = mask.resize((w // HERO, h // HERO), Image.LANCZOS)
        mask = mask.point(lambda v: 255 if v >= 118 else 0)
        img = color.convert("RGBA")
        img.putalpha(mask)
        frames.append(img)
    return frames

def make_bubble(text: str, font_path: str | None, width: int, font_size: int = 13):
    """把一句话画成圆角气泡（返回 RGBA 图，边缘是硬边）"""
    if not HAS_PIL:
        return None
    font = None
    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, font_size * HERO)
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    pad = 9 * HERO
    max_text_w = max(60, width - pad * 2) * HERO
    # 逐字换行（中英混排都够用）；标点不留行首
    no_line_start = "，。！？、；：）】》”’…,.!?;:)]}"
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if font.getlength(trial) > max_text_w and cur and ch not in no_line_start:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lines = lines[:4]

    line_h = int(font_size * HERO * 1.42)
    text_w = int(max(font.getlength(ln) for ln in lines)) if lines else 0
    text_h = line_h * len(lines)
    w = text_w + pad * 2
    h = text_h + pad * 2 + 7 * HERO          # 底部留出小尖角

    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w - 1, h - 7 * HERO], radius=10 * HERO, fill=255)
    tipx = int(w * 0.30)
    md.polygon([(tipx - 6 * HERO, h - 8 * HERO), (tipx + 5 * HERO, h - 8 * HERO), (tipx, h - 1)], fill=255)

    color = Image.new("RGB", (w, h), (255, 255, 255))
    cd = ImageDraw.Draw(color)
    cd.rounded_rectangle([0, 0, w - 1, h - 7 * HERO], radius=10 * HERO, fill=(255, 255, 255), outline=(26, 58, 62),
                         width=max(1, 2 * HERO))
    y = pad
    for line in lines:
        cd.text((pad, y), line, font=font, fill=(28, 42, 46))
        y += line_h

    color = color.resize((w // HERO, h // HERO), Image.LANCZOS)
    mask = mask.resize((w // HERO, h // HERO), Image.LANCZOS)
    mask = mask.point(lambda v: 255 if v >= 118 else 0)
    bubble = color.convert("RGBA")
    bubble.putalpha(mask)
    return bubble


# ----------------------------------------------------------------- 主程序

def to_photo(img):
    """把带透明通道的图合成到透明色上，交回 tkinter（透明像素正好变成透明色）"""
    bg = Image.new("RGB", img.size, KEY_COLOR)
    bg.paste(img.convert("RGB"), (0, 0), img.split()[3])
    return ImageTk.PhotoImage(bg)


def claude_running() -> bool:
    """现在有没有 Claude Code 在跑（它的本体进程叫 claude.exe）。

    用系统自带的进程快照查，不起子进程、不弹黑框，几毫秒就回来。
    """
    try:
        class PE32(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                        ("th32ProcessID", ctypes.c_ulong),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                        ("th32ParentProcessID", ctypes.c_ulong),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                        ("szExeFile", ctypes.c_char * 260)]
        k = ctypes.windll.kernel32
        snap = k.CreateToolhelp32Snapshot(2, 0)          # 2 = 进程快照
        if snap in (0, -1):
            return True                                  # 查不了就当它在跑，别误杀自己
        entry = PE32()
        entry.dwSize = ctypes.sizeof(PE32)
        try:
            if k.Process32First(snap, ctypes.byref(entry)):
                while True:
                    name = entry.szExeFile.decode("mbcs", "replace").lower()
                    if name in ("claude.exe", "claude") or name.startswith("claude"):
                        return True
                    if not k.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            k.CloseHandle(snap)
    except Exception:
        return True                                      # 出错时保持现状，宁可留着
    return False


def monitor_work_area(x: int, y: int) -> tuple[int, int, int, int]:
    """点 (x, y) 落在哪块屏幕上，就返回那块屏幕的可用区域（不含任务栏）。

    用来做「卡片不许超出屏幕边缘」的保护：多屏、任务栏、缩放都在这儿解决。
    """
    u = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    try:
        hmon = u.MonitorFromPoint(POINT(int(x), int(y)), 2)   # 2 = 最近的那块屏
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if u.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcWork
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    try:                                     # 兜底：系统「工作区」（主屏可用面积）
        r = RECT()
        if u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))


def focus_window(hint: str, prefer: str = "visual studio code") -> bool:
    """把标题里带 hint 的窗口提到最前面（优先匹配 prefer 关键字）。"""
    if not hint:
        return False
    u = ctypes.windll.user32
    hint_l, prefer_l = hint.lower(), prefer.lower()
    hits: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.lower()
        if hint_l in title:
            hits.append((0 if prefer_l in title else 1, hwnd))
        return True

    try:
        u.EnumWindows(cb, 0)
    except Exception:
        return False
    if not hits:
        return False
    hits.sort(key=lambda t: t[0])
    hwnd = hits[0][1]
    try:
        if u.IsIconic(hwnd):
            u.ShowWindowAsync(hwnd, 9)      # SW_RESTORE
        u.SetForegroundWindow(hwnd)
    except Exception:
        return False
    return True


def select_tab(title: str, hint: str = "", script: str | None = None) -> bool:
    """跳到窗口之后，再按名字点名那一个标签页（VS Code 的标签页能被 UI 自动化看见）。

    Windows 的「UI 自动化」要 .NET 才方便调，本机自带 PowerShell，所以交给一个小脚本做；
    这里只负责把它悄悄叫起来（不弹黑框、不挡宠物），成功与否都不影响主流程。
    """
    title = (title or "").strip()
    path = script or os.path.join(APP_DIR, "select_vscode_tab.ps1")
    if not title or not os.path.exists(path):
        return False
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path,
           "-Hint", hint or "", "-Title", title]
    try:
        flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW：不闪黑框
        subprocess.Popen(cmd, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def enable_dpi_awareness() -> float:
    """让 Windows 不要拉伸我们，返回屏幕缩放倍数（150% 缩放 -> 1.5）。

    不声明 DPI 感知的话，在 150% 缩放的屏幕上整个窗口会被系统放大 1.5 倍，
    文字和边框就会发虚 —— 这也是之前看着比 Mini 糊的原因。
    """
    u = ctypes.windll.user32
    ok = False
    # 1) 首选 PER_MONITOR_AWARE_V2（注意：句柄是 64 位的，参数类型必须声明）
    try:
        u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        ok = bool(u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
    except Exception:
        ok = False
    # 2) 退而求其次：进程级 per-monitor
    if not ok:
        try:
            ok = ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
        except Exception:
            ok = False
    # 3) 最后兜底：系统级 DPI 感知
    if not ok:
        try:
            ok = bool(u.SetProcessDPIAware())
        except Exception:
            ok = False

    dpi = 96.0
    try:
        u.GetDpiForSystem.restype = ctypes.c_uint
        dpi = float(u.GetDpiForSystem())
    except Exception:
        pass
    if dpi <= 96.0:
        try:
            hdc = u.GetDC(0)
            dpi = float(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))
            u.ReleaseDC(0, hdc)
        except Exception:
            pass
    try:
        if sys.stdout is not None:      # pythonw 下没有控制台，stdout 可能是 None
            print(f"[pet] DPI 感知={'已开启' if ok else '开启失败'}  屏幕缩放={dpi/96:.2f}x")
    except Exception:
        pass
    return max(1.0, dpi / 96.0)


class DesktopPet:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mood = "idle"
        self.frame_idx = 0
        self.frame_started = time.time()
        self.mood_started = time.time()
        self.bubble_until = 0.0
        self.bubble_text = ""
        self.bubble_photo = None
        self.card_info: dict = {}          # {"title","detail","icon"}
        self.card_jump: dict = {}          # 点这张卡片时跳去哪里（cwd / hint / session_id）
        self.card_frame_delay = 0.11
        self.card_photos: list = []        # 卡片帧（转圈时多帧）
        self.notice_kind = None            # card / stack / list
        self.notice_photos: list = []
        self.notice_rows: list = []
        self.notice_key = None
        self.notice_jump: dict = {}
        self.notice_box = (0, 0, 0, 0)
        self.notice_delay = 0.11
        self.notice_idx = 0
        self.notice_next = 0.0
        self.notice_item = None
        self.bubble_item = None
        self._held_photos: list = []       # 藏起来的卡片图，留个引用免得 Tk 提前回收
        self.win_rect = None               # 上次真正落到窗口上的位置/大小（一样就不动它）
        self._shrink = True                # 关掉它就只藏卡片、不缩窗口（换内容时少一次重画）
        self.tasks: dict = {}              # pet_tasks/ 里的任务
        self.task_sig = None
        self.expanded = False              # 任务清单是否摊开
        self.list_page = 0                 # 清单翻到第几屏（任务多时用）
        self.ambient_card: dict | None = None
        self.mood_hold_until = 0.0
        self.pending_task_mood = False
        self.next_task_poll = 0.0
        self.next_claude_check = 0.0
        self.next_update_check = time.time() + float(cfg.get("update_delay_seconds", 20) or 0)
        self.update_info: dict | None = None   # 查到的新版本（有的话菜单里会多一项）
        self.last_claude_seen = time.time()   # 最近一次「看到 Claude 在跑」
        self.last_activity = time.time()      # 最近一次「我这儿有动静」（任务/状态变了）
        self.card_idx = 0
        self.card_next = 0.0
        self.card_until = 0.0
        self.card_item = None
        self.state_mtime = 0.0
        self.state_sig = None             # 已处理过的状态文件内容指纹
        self.next_state_poll = 0.0
        self.next_topmost = 0.0
        self.last_hotkey = False
        self.dragging = False
        self.drag_moved = False
        self.drag_offset = (0, 0)
        self.next_idle_talk = time.time() + random.uniform(
            cfg["idle_talk_min_sec"], cfg["idle_talk_max_sec"])
        self.font_path = pick_font_path(cfg)
        self.hidden = False
        self.menu_open = False            # 菜单弹出期间不抢置顶，免得把菜单压住
        self.sticky_mood = False          # 外部明确指定过状态时，不要自动回待机
        self.external_mood = "idle"       # 状态通道（Claude Code 等）给的真实状态
        self.demo_until = 0.0             # 手动「演示」的结束时刻
        self.quitting = False             # 已经决定退场了（别再跑剩下的小动作）

        self.ui = enable_dpi_awareness()  # 必须先声明，再建窗口
        # 窗口要先建好，tkinter 的图片对象依赖它
        self.root = tk.Tk()
        self.root.title("DesktopPet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        try:
            self.root.attributes("-transparentcolor", KEY_COLOR)
        except tk.TclError:
            pass
        self.root.configure(bg=KEY_COLOR)

        self.assets = Assets(cfg)

        self.scale = float(cfg["scale"].get(cfg["size"], 1.0))
        self.rscale = self.scale * self.ui                 # 用户尺寸 × 屏幕缩放
        self.disp_px = int(round(NATIVE_PX * self.rscale))
        self.bubble_max_w = int(max(150, 240 * min(1.3, self.scale)) * self.ui)
        self.card_max_w = int(max(170, 268 * min(1.3, self.scale)) * self.ui)

        self.pet_px = self.disp_px
        self.pet_off = (0, 0)             # 宠物在窗口里的左上角
        self.panel_off = (0, 0)           # 卡片/气泡在窗口里的左上角
        self.panel_box = (0, 0, 0, 0)     # 同上，附带宽高（点清单时要用）
        self.win_w = self.pet_px
        self.win_h = self.pet_px

        self.canvas = tk.Canvas(self.root, width=self.pet_px, height=self.pet_px,
                                bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack()

        self.pet_img_id = self.canvas.create_image(0, 0, anchor="nw",
                                                  image=self._current_frame())
        # 宠物钉在屏幕上的位置：记「宠物左上角」，卡片再围着它摆
        self.pet_anchor = self._initial_anchor()
        self._place(0, 0)

        self.menu = self._build_menu()
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_right_click)

        try:
            self.read_state()      # 起手先同步一次外部状态（出错也不许把宠物弄死）
        except Exception as exc:
            self._log_error(exc)
        self.tick()

    # ------------------------------------------------------------- 位置

    def _screen(self):
        user32 = ctypes.windll.user32
        try:
            return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
                    user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
        except Exception:
            return (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())

    def _initial_anchor(self) -> tuple[int, int]:
        """宠物左上角该放哪：没存过就贴右下角（留 margin）"""
        px, py = self.cfg.get("x"), self.cfg.get("y")
        if px is not None and py is not None and self.cfg.get("anchor") == "pet":
            return int(px), int(py)
        if px is not None and py is not None:
            # 老配置存的是「窗口左上角」，换算成宠物左上角，别让它平白跳一下
            legacy_w = max(self.pet_px, self.bubble_max_w, self.card_max_w) + 8
            legacy_top = int(max(112, 158 * self.scale) * self.ui)
            return int(px) + (legacy_w - self.pet_px) // 2, int(py) + legacy_top
        l, t, r, b = monitor_work_area(0, 0)
        m = int(self.cfg["margin"])
        return r - m - self.pet_px, b - m - self.pet_px

    def _panel_room(self) -> tuple[str, float]:
        """卡片该摆头顶还是脚下，以及那一侧还剩多少地方（像素）"""
        above, below = self._panel_rooms()
        # 头顶够放（至少 90px）就优先头顶；实在没地方才翻到脚下去
        if above >= 90 or above >= below:
            return "above", max(40.0, float(above))
        return "below", max(40.0, float(below))

    def _panel_rooms(self) -> tuple[float, float]:
        """宠物头顶、脚下各还剩多少地方（都不含任务栏，多屏按宠物所在那块算）"""
        pet_x, pet_y = self.pet_anchor
        pad = self._gap()
        l, t, r, b = monitor_work_area(pet_x + self.pet_px // 2, pet_y + self.pet_px // 2)
        return (max(0.0, pet_y - t - pad),
                max(0.0, b - (pet_y + self.pet_px) - pad))

    def _pick_side(self, panel_h: float) -> str:
        """先按习惯选一侧；那一侧塞不下就翻到另一侧（只要另一边放得下）"""
        above, below = self._panel_rooms()
        side = "above" if (above >= 90 or above >= below) else "below"
        room = above if side == "above" else below
        if panel_h > room:
            other = "below" if side == "above" else "above"
            if panel_h <= (above if other == "above" else below):
                side = other
        return side

    def _gap(self) -> int:
        return max(4, int(6 * min(1.5, self.rscale)))

    def _clamp_pet(self, x: int, y: int) -> tuple[int, int]:
        """宠物必须整只都在屏幕可用区里（按它中心所在的那块屏算）"""
        l, t, r, b = monitor_work_area(x + self.pet_px // 2, y + self.pet_px // 2)
        return (min(max(int(x), l), max(l, r - self.pet_px)),
                min(max(int(y), t), max(t, b - self.pet_px)))

    def _place(self, panel_w: int = 0, panel_h: int = 0) -> None:
        """摆位（会真的动窗口）。只做一次几何变更，避免来回重画闪一下。"""
        self._apply_geo(self._layout(panel_w, panel_h))

    def _layout(self, panel_w: int = 0, panel_h: int = 0) -> dict:
        """纯计算：窗口该在哪、多大，宠物和卡片各自在窗口里放哪（不碰 Tk，不会重画）"""
        pad = self._gap()
        self.pet_anchor = self._clamp_pet(*self.pet_anchor)   # 整只宠物都得在屏幕里
        pet_x, pet_y = self.pet_anchor
        pet_r, pet_b = pet_x + self.pet_px, pet_y + self.pet_px
        win_x, win_y = pet_x, pet_y
        panel_off, panel_box = (0, 0), (0, 0, 0, 0)

        if panel_w > 0 and panel_h > 0:
            side = self._pick_side(panel_h)
            panel_y = pet_y - pad - panel_h if side == "above" else pet_b + pad
            panel_x = pet_x + self.pet_px // 2 - panel_w // 2
            l, t, r, b = monitor_work_area(pet_x + self.pet_px // 2, pet_y + self.pet_px // 2)
            panel_x = max(l + 4, min(panel_x, r - 4 - panel_w))   # 左右夹住，不越界
            panel_y = max(t + 4, min(panel_y, b - 4 - panel_h))   # 上下也兜一道底
            win_x = min(pet_x, panel_x)
            win_y = min(pet_y, panel_y)
            win_w = max(pet_r, panel_x + panel_w) - win_x
            win_h = max(pet_b, panel_y + panel_h) - win_y
            panel_off = (int(panel_x - win_x), int(panel_y - win_y))
            panel_box = (int(panel_x - win_x), int(panel_y - win_y), panel_w, panel_h)
        else:
            win_w, win_h = self.pet_px, self.pet_px

        return {"rect": (int(win_x), int(win_y), int(win_w), int(win_h)),
                "pet_off": (int(pet_x - win_x), int(pet_y - win_y)),
                "panel_off": panel_off, "panel_box": panel_box}

    def _apply_geo(self, geo: dict) -> None:
        """把算好的摆位一次性落到窗口上：位置/大小没变就一个 Tk 调用都不发（不闪）"""
        win_x, win_y, win_w, win_h = geo["rect"]
        self.pet_off, self.panel_off, self.panel_box = (geo["pet_off"], geo["panel_off"],
                                                        geo["panel_box"])
        if (win_w, win_h) != (self.win_w, self.win_h):
            self.win_w, self.win_h = win_w, win_h
            self.canvas.configure(width=win_w, height=win_h)
        if geo["rect"] != self.win_rect:
            self.win_rect = geo["rect"]
            self.root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        self.canvas.coords(self.pet_img_id, self.pet_off[0], self.pet_off[1])

    def _snap_and_save(self) -> None:
        """拖完手：贴着边就吸附，然后记住宠物自己的位置"""
        x, y = self.pet_anchor
        l, t, r, b = monitor_work_area(x + self.pet_px // 2, y + self.pet_px // 2)
        m = int(self.cfg["margin"])
        if abs(x - l) <= m:
            x = l
        if abs((x + self.pet_px) - r) <= m:
            x = r - self.pet_px
        if abs(y - t) <= m:
            y = t
        if abs((y + self.pet_px) - b) <= m:
            y = b - self.pet_px
        x, y = self._clamp_pet(x, y)
        self.pet_anchor = (x, y)
        self.cfg["x"], self.cfg["y"] = x, y
        self.cfg["anchor"] = "pet"
        save_config(self.cfg)
        if self.bubble_text:
            self._render_bubble()
        else:
            self._render_notice()

    # ------------------------------------------------------------- 交互

    def _build_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"桌面宠物 v{VERSION}", state="disabled")
        if self.update_info:
            menu.add_command(label=f"有新版本 v{self.update_info['version']} → 打开更新页",
                             command=self.open_update_page)
        menu.add_separator()
        menu.add_command(label="摸摸它", command=self.pet_it)
        menu.add_separator()
        for mood in ("working", "done", "alert", "sleep", "idle"):
            menu.add_command(label=MENU_LABEL[mood], command=lambda m=mood: self.demo_mood(m))
        size_menu = tk.Menu(menu, tearoff=0)
        for label in ("小", "中", "大"):
            size_menu.add_command(label=f"大小：{label}", command=lambda l=label: self.set_size(l))
        menu.add_cascade(label="尺寸", menu=size_menu)
        menu.add_separator()
        menu.add_command(label=f"藏起来（{self.cfg['hotkey'].upper()} 唤出）", command=self.hide)
        menu.add_command(label="打开宠物文件夹", command=self.open_folder)
        menu.add_separator()
        menu.add_command(label="退出", command=self.quit)
        return menu

    def open_folder(self) -> None:
        os.startfile(APP_DIR)  # noqa: S606  (Windows 专用)

    def open_update_page(self) -> None:
        """打开新版本的下载页（用系统默认浏览器）"""
        url = str((self.update_info or {}).get("url") or "")
        if url:
            webbrowser.open(url)

    def demo_mood(self, mood: str) -> None:
        """临时演一下，到点自己回到真实状态（菜单和「摸摸它」都走这里）"""
        self.set_mood(mood, STATE_TALK.get(mood, ""), seconds=self.cfg.get("demo_seconds", 6.0),
                      demo=True)

    def on_press(self, event) -> None:
        # 点在卡片上时交给卡片自己处理（跳转），不要开始拖宠物
        try:
            if "card" in self.canvas.gettags("current"):
                return
        except Exception:
            pass
        # 卡片刚被重画过时 "current" 是空的，所以再按坐标兜一道：
        # 只要落点在卡片/气泡里，这一下就不算「摸宠物」
        if self._in_panel(event):
            return
        self.dragging = True
        self.drag_moved = False
        self.drag_offset = (event.x, event.y)

    def _in_panel(self, event) -> bool:
        """这一下点的是不是卡片/气泡（而不是宠物）"""
        x, y, w, h = self.panel_box
        if not w or not h:
            return False
        try:
            return x <= event.x < x + w and y <= event.y < y + h
        except Exception:
            return False

    def on_drag(self, event) -> None:
        if not self.dragging:
            return
        if abs(event.x - self.drag_offset[0]) + abs(event.y - self.drag_offset[1]) > 3:
            self.drag_moved = True
        x = self.root.winfo_pointerx() - self.drag_offset[0]
        y = self.root.winfo_pointery() - self.drag_offset[1]
        # 宠物整只都得在屏幕里：拖到边上就贴住，不许露半只出去
        ax, ay = self._clamp_pet(x + self.pet_off[0], y + self.pet_off[1])
        x, y = ax - self.pet_off[0], ay - self.pet_off[1]
        self.root.geometry(f"+{x}+{y}")
        # 宠物跟着窗口一起动：记住它自己的位置（卡片是围着它摆的）
        self.pet_anchor = (x + self.pet_off[0], y + self.pet_off[1])

    def on_release(self, event) -> None:
        if self.dragging and self.drag_moved:
            self._snap_and_save()
        elif self.dragging:
            if not self._in_panel(event):
                self.pet_it()
        self.dragging = False

    def on_right_click(self, event) -> None:
        self.menu = self._build_menu()
        # 菜单弹出期间把宠物降到普通层级：
        # 否则「始终置顶」的宠物窗口会盖在菜单上面，把下面的选项挡掉
        self.menu_open = True
        self.root.attributes("-topmost", False)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        self.root.after(100, self._watch_menu_close)

    def _watch_menu_close(self) -> None:
        """菜单关掉之后，再把宠物放回最上层"""
        try:
            still_open = bool(self.menu.winfo_ismapped())
        except Exception:
            still_open = False
        if still_open:
            self.root.after(120, self._watch_menu_close)
            return
        self.menu_open = False
        if self.cfg.get("always_on_top"):
            self.root.attributes("-topmost", True)

    def pet_it(self) -> None:
        self.set_mood("done", random.choice(PET_TALK), seconds=2.2, sound=False, demo=True)

    # ------------------------------------------------------------- 状态

    def set_mood(self, mood: str, message: str = "", *, seconds: float | None = None,
                 sound: bool = True, demo: bool = False,
                 sticky: bool | None = None) -> None:
        """demo=True 表示「临时表演」，到点会自己回到 external_mood。"""
        if mood not in MOODS:
            mood = "idle"
        if not demo:
            # 真实状态：done 是一次性表演，实际持久状态按 idle 记；
            # 其余（working / alert / sleep / idle）就是要保持的样子
            self.external_mood = "idle" if mood == "done" else mood
            self.demo_until = 0.0
        else:
            self.demo_until = time.time() + float(seconds or self.cfg.get("demo_seconds", 6.0))
        self.mood = mood
        self.frame_idx = 0
        self.frame_started = time.time()
        self.mood_started = time.time()
        # 会「赖着不走」的情绪：干活中、要你确认、睡觉；
        # done 是一次性表演，气泡散场就回待机
        self.sticky_mood = (mood in ("working", "alert", "sleep")) if sticky is None else bool(sticky)
        if message:
            self.show_bubble(message, seconds)
        # 立刻换脸，别等下一帧（最多省 28ms，但换状态时的手感会明显不同）
        if hasattr(self, "canvas") and hasattr(self, "pet_img_id"):
            self.canvas.itemconfigure(self.pet_img_id, image=self._current_frame())
        if sound and self.cfg.get("sound"):
            self._beep(mood)

    def restore_real(self) -> None:
        """结束演示，回到状态通道给的（或最后记住的）真实状态"""
        self.set_mood(self.external_mood, "", sound=False)

    def _beep(self, mood: str) -> None:
        if winsound is None:
            return
        try:
            if mood == "done":
                winsound.MessageBeep(0x40)      # 系统「提示」音
            elif mood == "alert":
                winsound.MessageBeep(0x30)      # 系统「警告」音
        except Exception:
            pass

    def show_bubble(self, text: str, seconds: float | None = None) -> None:
        self._shrink = False               # 待会儿气泡自己会把窗口尺寸一次定好
        self._clear_notice()
        self._shrink = True
        self.bubble_text = text
        self.bubble_until = time.time() + float(seconds or self.cfg["bubble_seconds"])
        self._render_bubble()

    def _clear_bubble(self) -> None:
        self.bubble_until = 0.0
        self.bubble_text = ""
        if self.bubble_item is not None:
            self.canvas.itemconfigure(self.bubble_item, state="hidden")
        if not self.notice_photos:
            self._place(0, 0)

    # ---- 状态卡片（标题 + 明细 + 图标）------------------------------

    def show_card(self, title: str, detail: str = "", icon: str = "info",
                  seconds: float | None = None, jump: dict | None = None) -> None:
        """兼容接口：单张卡片。现在正式路径走任务列表（pet_tasks/）。"""
        key = (jump or {}).get("key") or "ambient"
        self.ambient_card = {"key": key, "title": str(title or ""), "detail": str(detail or ""),
                             "icon": icon, "state": "alert" if icon == "alert" else "working",
                             "cwd": str((jump or {}).get("cwd") or ""),
                             "hint": str((jump or {}).get("hint") or "")}
        self._render_notice()

    # ---- 任务列表：折叠 / 展开 --------------------------------------

    def _refresh_tasks(self) -> None:
        """扫一遍 pet_tasks/，把每个 Claude Code 会话的任务读进来"""
        now = time.time()
        ttl = float(self.cfg.get("task_ttl", 1800) or 0)
        tasks: dict = {}
        try:
            names = os.listdir(TASKS_DIR)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(TASKS_DIR, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            ts = float(data.get("ts") or 0)
            if ttl and now - ts > ttl:                 # 太久的任务自动清掉
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            tasks[name[:-5]] = data
        sig = tuple(sorted((k, float(v.get("ts") or 0), str(v.get("state")),
                            str(v.get("title") or "")) for k, v in tasks.items()))
        if sig != self.task_sig:
            prev, self.tasks = self.tasks, tasks
            self.task_sig = sig
            self._on_tasks_changed(prev, tasks)
        else:
            self.tasks = tasks

    def _task_entries(self) -> list:
        """要显示的任务（按 待处理 → 进行中 → 已完成 排序）"""
        order = {"alert": 0, "working": 1, "done": 2}
        entries = []
        for key, d in self.tasks.items():
            state = str(d.get("state") or "idle")
            if state in ("idle", "sleep", "closed"):
                continue
            entries.append({
                "key": key,
                "title": str(d.get("title") or "未命名任务"),
                "detail": str(d.get("detail") or ""),
                "icon": str(d.get("icon") or {"done": "check", "alert": "alert"}.get(state, "spinner")),
                "status_text": {"alert": "待处理", "working": "进行中", "done": "已完成"}.get(state, ""),
                "state": state,
                "cwd": str(d.get("cwd") or ""),
                "hint": str(d.get("hint") or ""),
                "session_id": str(d.get("session_id") or ""),
            })
        if not entries and self.ambient_card:
            e = dict(self.ambient_card)
            e.setdefault("status_text", "")
            entries.append(e)
        entries.sort(key=lambda e: (order.get(e["state"], 3), -float(self.tasks.get(e["key"], {}).get("ts") or 0)))
        return entries

    def _task_mood(self) -> str:
        states = [e["state"] for e in self._task_entries()]
        if "alert" in states:
            return "alert"
        if "working" in states:
            return "working"
        if "done" in states:
            return "done"
        return "idle"

    def _list_capacity(self) -> int:
        """展开清单最多能放几行（再多就把宠物窗口顶出去了）"""
        _, avail = self._panel_room()
        header = 27 * self.rscale
        row = max(1.0, 35 * self.rscale)
        return max(1, int((avail - header - 8 * self.rscale) // row))

    def _on_tasks_changed(self, prev: dict, now_tasks: dict) -> None:
        """任务变了：响了就提醒，然后按优先级更新表情"""
        self.list_page = 0
        self.last_activity = time.time()
        for key, d in now_tasks.items():
            old = prev.get(key) or {}
            state = str(d.get("state") or "")
            if float(d.get("ts") or 0) > float(old.get("ts") or 0) and state in ("alert", "done"):
                if state != old.get("state"):
                    self._beep(state)
        if self.demo_until > time.time():              # 正在手动演示，先不抢
            self._render_notice()
            return
        mood = self._task_mood()
        if mood == "done":
            self.set_mood("done", "", sound=False, sticky=True)
            self.mood_hold_until = time.time() + 4.0
            self.pending_task_mood = True
        else:
            self.set_mood(mood, "", sound=False, sticky=True)
        self._render_notice()

    def _render_notice(self) -> None:
        """按优先级决定显示什么：气泡 > （折叠堆 / 展开清单 / 单张卡片）"""
        now = time.time()
        if self.bubble_text and self.bubble_until > now:
            return                                     # 气泡优先，卡片先不画
        entries = self._task_entries()
        if not entries:
            self._clear_notice()
            return
        icon = entries[0]["icon"]
        if len(entries) == 1:
            one = entries[0]
            frames = make_card_frames(one["title"], one["detail"], icon, self.card_max_w,
                                      self.font_path, self.rscale)
            photos = [to_photo(f) for f in frames]
            self.notice_jump = one
            self._show_notice("card", photos, key=one["key"],
                              delay=0.11 if icon == "spinner" else 0.62)
            return
        if self.expanded:
            cap = self._list_capacity()
            page = min(self.list_page, max(0, (len(entries) - 1) // cap))
            self.list_page = page
            shown = entries[page * cap:(page + 1) * cap]
            more = max(0, len(entries) - (page + 1) * cap)
            img, rows = make_task_list(shown, self.card_max_w, self.font_path, self.rscale,
                                       more=more, total=len(entries))
            if img is None:
                return
            photos = [to_photo(img)]
            self.notice_jump = entries[0]
            self._show_notice("list", photos, rows=rows)
            return
        frames = make_stack_frames(len(entries), entries[0]["title"], icon,
                                   self.card_max_w, self.font_path, self.rscale)
        photos = [to_photo(f) for f in frames]
        self.notice_jump = entries[0]
        self._show_notice("stack", photos, key=entries[0]["key"],
                          delay=0.11 if icon == "spinner" else 0.62)

    def _show_notice(self, kind: str, photos: list, rows: list | None = None,
                     key: str | None = None, delay: float = 0.11) -> None:
        self.notice_kind = kind
        self.notice_photos = photos
        self.notice_rows = rows or []
        self.notice_key = key
        self.notice_idx = 0
        self.notice_delay = delay
        self.notice_next = time.time() + delay
        if self.bubble_item is not None:
            self.canvas.itemconfigure(self.bubble_item, state="hidden")
        self.bubble_text = ""
        self.bubble_until = 0.0
        w = photos[0].width()
        h = photos[0].height()
        self._held_photos = list(photos)       # 一直留个引用：Tk 的图不能被提前回收
        geo = self._layout(w, h)               # 先算好摆哪（头顶还是脚下、左右夹紧）
        # 关键：卡片画布**只换图、不删了重建**（删了重建中间会空一帧，看着就是闪）
        if self.notice_item is None:
            self.notice_item = self.canvas.create_image(
                geo["panel_off"][0], geo["panel_off"][1], anchor="nw",
                image=photos[0], tags=("notice", "card"))
            self.canvas.tag_bind("notice", "<Button-1>", self.on_notice_click)
        else:
            self.canvas.itemconfigure(self.notice_item, image=photos[0], state="normal")
            self.canvas.coords(self.notice_item, geo["panel_off"][0], geo["panel_off"][1])
        self._apply_geo(geo)                   # 位置/大小一次到位
        self.notice_box = self.panel_box

    def _clear_notice(self) -> None:
        if self.notice_item is not None:
            self.canvas.itemconfigure(self.notice_item, state="hidden")   # 先藏起来，别删
        if self.notice_photos:
            # 转圈/慢闪是多帧，当前显示的可能是其中任意一帧 —— 整组都留着，别让 Tk 提前回收
            self._held_photos = list(self.notice_photos)
        self.notice_photos = []
        self.notice_rows = []
        self.notice_kind = None
        if not self.bubble_text and self._shrink:
            self._place(0, 0)                  # 没东西显示了：窗口缩回成一只宠物

    # ---- 点通知：折叠→展开→跳转 ------------------------------------

    def on_notice_click(self, event=None) -> str:
        """点卡片：只管卡片的事，别让这一下继续传到「摸摸它」上去"""
        self._handle_notice_click(event)
        return "break"

    def _handle_notice_click(self, event=None) -> None:
        if self.notice_kind == "list" and event is not None:
            y = event.y - self.notice_box[1]
            for y0, y1, key in self.notice_rows:
                if y0 <= y < y1:
                    if key is None:                    # 点"收起"
                        self.expanded = False
                        self.list_page = 0
                    elif key == "__more__":            # 翻到下一屏
                        self.list_page += 1
                    else:
                        self._jump_to_task(key)
                        self.expanded = False
                    self._render_notice()
                    return
            return
        if self.notice_kind == "stack":
            self.expanded = True                        # 点一下摊开
            self.list_page = 0
            self._render_notice()
            return
        if self.notice_kind == "card" and self.notice_key:
            self._jump_to_task(self.notice_key)

    def _jump_to_task(self, key: str) -> None:
        entry = None
        for e in self._task_entries():
            if e["key"] == key:
                entry = e
                break
        self.jump_back(entry or {})

    def _log_jump(self, text: str) -> None:
        """专门记「点了卡片之后发生了什么」，方便出问题时对账（pet_jump.log）"""
        try:
            with open(os.path.join(APP_DIR, "pet_jump.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%m-%d %H:%M:%S')} {text}\n")
        except Exception:
            pass

    def jump_back(self, info: dict | None = None) -> bool:
        """跳到某个任务对应的窗口（点卡片／点清单里的某一行都会走这里）"""
        info = info if info is not None else (self.notice_jump or {})
        cwd = str(info.get("cwd") or "")
        hint = str(info.get("hint") or "") or (os.path.basename(cwd.rstrip("\\/")) if cwd else "")
        self._log_jump(f"点了卡片 key={info.get('key')!r} hint={hint!r} cwd={cwd!r}")

        custom = str(self.cfg.get("jump_command") or "")
        if custom:
            try:
                subprocess.Popen(custom.format(cwd=cwd, hint=hint), shell=True,
                                 cwd=cwd if os.path.isdir(cwd) else APP_DIR)
                self._after_jump(info)
                return True
            except Exception:
                pass

        ok = False
        if focus_window(hint):
            if self.cfg.get("select_tab", True):
                # 同一个 VS Code 窗口里开好几个会话时，再点名那一个标签页
                tab = str(info.get("tab") or "")
                title = str(info.get("title") or "")
                title = re.sub(r"（[^（）]{0,12}）$", "", title) or title
                select_tab(tab or title, hint=hint,
                           script=self.cfg.get("tab_script") or None)
            ok = True
        self._log_jump(f"  找到窗口={ok}")

        # 实在找不到窗口：想让它「打开那个目录」就得自己把 jump_open_folder 打开
        # （默认关掉 —— 免得点一下卡片就把你正在用的 VS Code 窗口抢过去换了文件夹）
        if not ok and self.cfg.get("jump_open_folder") and cwd and os.path.isdir(cwd):
            for cmd in (["code", "-r", cwd], ["code.cmd", "-r", cwd],
                        ["cmd", "/c", "start", "", "cmd", "/k", "cd", "/d", cwd]):
                try:
                    subprocess.Popen(cmd, cwd=cwd)
                    ok = True
                    break
                except FileNotFoundError:
                    continue
                except Exception:
                    continue
        # 不管跳没跳成，你点过的这张卡都收走（想留着就把 jump_clear 关掉）
        self._after_jump(info)
        return ok

    def _after_jump(self, info: dict) -> None:
        """跳过去之后，把这张卡收走（`jump_clear`，默认开）——
        卡片是「活的会话」的投影，人已经跳到跟前了就没必要再挂着；
        那个会话再有动静，钩子会重新写一张。"""
        self.expanded = False
        self.list_page = 0
        if not self.cfg.get("jump_clear", True):
            self._log_jump("  jump_clear=false，卡片留着不收")
            self._render_notice()
            return
        key = str(info.get("key") or "")
        removed = False
        if key and key != "ambient":
            try:
                os.remove(os.path.join(TASKS_DIR, key + ".json"))
                removed = True
            except OSError as exc:
                self._log_jump(f"  删卡失败：{exc}")
        if self.ambient_card and (not key or key == "ambient"):
            self.ambient_card = None
        self._log_jump(f"  收卡 key={key!r} jump_clear={self.cfg.get('jump_clear')} "
                       f"删除={removed} 文件还在={os.path.exists(os.path.join(TASKS_DIR, key + '.json'))}")
        self._refresh_tasks()
        self._render_notice()

    def _render_bubble(self) -> None:
        if not self.bubble_text:
            if self.bubble_item is not None:
                self.canvas.itemconfigure(self.bubble_item, state="hidden")
            if not self.notice_photos:
                self._place(0, 0)
            return
        image = make_bubble(self.bubble_text, self.font_path, self.bubble_max_w,
                            font_size=max(11, int(12 * min(1.6, self.rscale))))
        if image is None:
            geo = self._layout(max(160, self.bubble_max_w), 40)
            if self.bubble_item is not None:
                self.canvas.delete(self.bubble_item)
                self.bubble_item = None
            self.canvas.delete("bubbletext")
            self._apply_geo(geo)
            self.canvas.create_text(geo["panel_off"][0] + 6, geo["panel_off"][1] + 6,
                                    text=self.bubble_text, width=self.bubble_max_w - 12,
                                    fill="#1c2a2e", anchor="nw", tags="bubbletext",
                                    font=("Microsoft YaHei", 10))
            return
        bg = Image.new("RGB", image.size, KEY_COLOR)
        bg.paste(image.convert("RGB"), (0, 0), image.split()[3])
        self.bubble_photo = ImageTk.PhotoImage(bg)
        geo = self._layout(image.width, image.height)
        if self.bubble_item is None:
            self.bubble_item = self.canvas.create_image(
                geo["panel_off"][0], geo["panel_off"][1], anchor="nw",
                image=self.bubble_photo, tags="bubble")
        else:
            self.canvas.itemconfigure(self.bubble_item, image=self.bubble_photo, state="normal")
            self.canvas.coords(self.bubble_item, geo["panel_off"][0], geo["panel_off"][1])
        self._apply_geo(geo)

    def read_state(self) -> None:
        """读取外部写入的状态文件（任何软件都能写）。

        用「内容指纹」而不是文件时间来判断新旧：
        连着来两个事件（比如 Stop 后立刻 SessionEnd）时间戳可能相同，
        只看 mtime 会把后一个漏掉。
        """
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        sig = data.get("ts")
        if sig is None:
            try:
                sig = ("mtime", os.path.getmtime(STATE_PATH))
            except OSError:
                return
        if sig == self.state_sig:
            return
        self.state_sig = sig
        self.last_activity = time.time()
        mood = str(data.get("state", "idle"))
        message = str(data.get("message", "") or "")
        seconds = data.get("seconds")
        title = str(data.get("title") or "")
        detail = str(data.get("detail") or "")
        icon = str(data.get("icon") or "")

        if mood == "say":            # 只说话，不动表情
            if detail or message:
                self.show_bubble(detail or message, seconds)
            return

        # 老式卡片（写在 pet_state.json 里的）当作一张临时卡片
        if title or detail:
            cwd = str(data.get("cwd") or "")
            self.ambient_card = {
                "key": str(data.get("session_id") or "ambient"),
                "title": title or MOOD_LABEL.get(mood, ""),
                "detail": detail,
                "icon": icon or {"done": "check", "alert": "alert", "working": "spinner"}.get(mood, "info"),
                "state": mood if mood in ("alert", "working", "done") else "working",
                "cwd": cwd,
                "hint": str(data.get("hint") or "") or (os.path.basename(cwd.rstrip("\\/")) if cwd else ""),
                "session_id": str(data.get("session_id") or ""),
            }
            self._render_notice()
            return

        self.ambient_card = None
        if mood == "idle":
            # 别的会话还在忙的时候，不要被一句「待机」抢走表情：任务卡片说了算
            if self._task_entries():
                self._render_notice()
                if not self.pending_task_mood and self.mood != "alert":
                    self.set_mood(self._task_mood(), message, sound=False)
                return
            self._clear_notice()
        elif mood == "sleep":
            self._clear_notice()
        self.set_mood(mood, message, seconds=seconds, sound=True)

    # ------------------------------------------------------------- 渲染循环

    def _current_frame(self):
        frames = (self.assets.frames_for(self.mood, self.disp_px)
                  or self.assets.frames_for("idle", self.disp_px))
        if not frames:
            raise SystemExit("没有找到动画素材，请先运行 make_pet_assets.py")
        return frames[self.frame_idx % len(frames)]

    def tick(self) -> None:
        """定时器：任何异常都不许把循环打断，否则整只宠物会僵住"""
        try:
            self._tick_once()
        except Exception as exc:                    # 兜住一切，记一笔继续跑
            self._log_error(exc)
        finally:
            if not self.quitting:
                self.root.after(self._next_wait_ms(), self.tick)

    def _next_wait_ms(self) -> int:
        """睡到下一次真需要动作为止（按需唤醒，比固定 12ms 轮询省 CPU）"""
        now = time.time()
        waits = [0.08]                              # 状态轮询：至少每 80ms 醒一次
        delay = self.assets.delay.get(self.mood)
        if delay:
            delay = delay * float(self.cfg.get("fps_scale", 1.0) or 1.0) / 1000.0
            waits.append(max(0.005, self.frame_started + delay - now))
        if self.card_photos and len(self.card_photos) > 1:
            waits.append(max(0.01, self.card_next - now))
        if self.notice_photos and len(self.notice_photos) > 1:
            waits.append(max(0.01, self.notice_next - now))
        for deadline in (self.bubble_until, self.demo_until):
            if deadline:
                waits.append(max(0.02, deadline - now))
        return int(max(5, min(waits) * 1000))

    def _log_error(self, exc: Exception) -> None:
        try:
            path = os.path.join(APP_DIR, "pet_errors.log")
            if os.path.exists(path) and os.path.getsize(path) > 200 * 1024:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    tail = fh.readlines()[-200:]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(tail)
            import traceback
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {exc!r}\n")
                fh.write("".join(traceback.format_exc()) + "\n")
        except Exception:
            pass

    def _tick_once(self) -> None:
        if self.quitting:
            return
        frames = self.assets.frames_for(self.mood, self.disp_px)
        if frames:
            delay = max(0.008, self.assets.delay.get(self.mood, 120)
                        * float(self.cfg.get("fps_scale", 1.0) or 1.0) / 1000.0)
            now = time.time()
            if now >= self.frame_started + delay:
                # 按「应该走到第几帧」推进，而不是每次都只走一帧：
                # tkinter 的定时器精度约 10~15ms，不补偿的话 42ms 的间隔会变成 48ms
                steps = max(1, int((now - self.frame_started) / delay))
                self.frame_idx = (self.frame_idx + steps) % len(frames)
                self.frame_started += steps * delay
                self.canvas.itemconfigure(self.pet_img_id, image=self._current_frame())

        # 演示到点：回到真实状态（比如 Claude Code 正在「干活中」）
        if self.demo_until and time.time() > self.demo_until:
            self.demo_until = 0.0
            self.restore_real()

        # 通知（单卡片 / 折叠堆 / 展开清单）：转圈动画 + 慢闪
        if self.notice_photos and len(self.notice_photos) > 1 and time.time() >= self.notice_next:
            self.notice_idx = (self.notice_idx + 1) % len(self.notice_photos)
            self.notice_next = time.time() + self.notice_delay
            self.canvas.itemconfigure(self.notice_item, image=self.notice_photos[self.notice_idx])

        # 任务目录（多个 Claude Code 会话）
        if time.time() >= self.next_task_poll:
            self.next_task_poll = time.time() + float(self.cfg.get("task_poll_seconds", 0.08))
            self._refresh_tasks()
        # 任务带来的「完成」表情演完就收回，卡片继续留着
        if self.pending_task_mood and time.time() > self.mood_hold_until:
            self.pending_task_mood = False
            self.set_mood(self._task_mood(), sound=False)

        # 「要你确认」没人理，超时就自己收回去（免得红点永远瞪着你）
        if (not self.demo_until and self.mood == "alert"
                and time.time() - self.mood_started > float(self.cfg.get("alert_seconds", 180))):
            self.set_mood("idle", sound=False)

        # 气泡是否过期
        if self.bubble_until and time.time() > self.bubble_until:
            self.bubble_until = 0.0
            self.bubble_text = ""
            if self.bubble_item is not None:
                self.canvas.itemconfigure(self.bubble_item, state="hidden")
            # 一次性情绪（done）演完就回真实状态；演示中的由上面的计时负责
            if self.mood == "done" and not self.demo_until:
                self.restore_real()
            self._render_notice()          # 气泡收走，把任务卡片放回来

        # 外部状态
        if time.time() >= self.next_state_poll:
            self.next_state_poll = time.time() + float(self.cfg.get("state_poll_seconds", 0.08))
            self.read_state()

        # 自言自语
        if (self.cfg.get("idle_talk") and not self.bubble_until and self.mood == "idle"
                and time.time() > self.next_idle_talk):
            self.show_bubble(random.choice(IDLE_TALK), 4.0)
            self.next_idle_talk = time.time() + random.uniform(
                self.cfg["idle_talk_min_sec"], self.cfg["idle_talk_max_sec"])

        # 快捷键（轮询实现，不需要额外库）
        pressed = self._hotkey_pressed()
        if pressed and not self.last_hotkey:
            self.toggle_visible()
        self.last_hotkey = pressed

        # 定时重新置顶，免得被别的窗口压住
        if self.cfg.get("always_on_top") and not self.menu_open:
            if time.time() >= self.next_topmost:    # 每秒做一次就够，别每帧都戳窗口
                self.next_topmost = time.time() + 1.0
                try:
                    # 已经是置顶就别再戳它 —— 多余的一次调用会让整个窗口重画一下（闪）
                    if not self.root.attributes("-topmost"):
                        self.root.attributes("-topmost", True)
                except Exception:
                    pass

        # 跟着 Claude Code 进退：它关了、而且我这边也没活儿了，就自己退场
        # 看看有没有新版本（只在到点那一刻发一个 GET，其余时间一动不动）
        if (self.cfg.get("update_check", True) and not self.update_info
                and time.time() >= self.next_update_check):
            self.next_update_check = time.time() + float(
                self.cfg.get("update_interval_hours", 24) or 24) * 3600
            info = check_for_update(self.cfg.get("update_manifest") or None, VERSION)
            if info:
                self.update_info = info
                self.show_bubble(f"有新版本 {info['version']}：右键我 → 打开更新页", 10.0)
        if self.cfg.get("follow_claude") and time.time() >= self.next_claude_check:
            self.next_claude_check = time.time() + float(
                self.cfg.get("claude_check_seconds", 5) or 5)
            if claude_running():
                self.last_claude_seen = time.time()
            else:
                grace = float(self.cfg.get("exit_grace_seconds", 180) or 0)
                quiet_for = time.time() - max(self.last_claude_seen, self.last_activity)
                # Claude 都不在了，卡片上那个"进行中"其实已经过期了，不再拿它当挡箭牌；
                # 只靠宽限期兜底（免得它重启一下就误判）
                if quiet_for > grace:
                    self._log_jump(f"Claude 关了 {int(quiet_for)} 秒、也没有新动静，先退下了")
                    self.quit()

    VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}

    def _hotkey_vks(self) -> list[int]:
        keys = []
        for part in str(self.cfg.get("hotkey", "")).lower().split("+"):
            part = part.strip()
            if part in self.VK:
                keys.append(self.VK[part])
            elif len(part) == 1:
                keys.append(ord(part.upper()))
        return keys

    def _hotkey_pressed(self) -> bool:
        keys = self._hotkey_vks()
        if not keys:
            return False
        user32 = ctypes.windll.user32
        return all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in keys)

    # ------------------------------------------------------------- 尺寸/显隐

    def set_size(self, label: str) -> None:
        self.cfg["size"] = label
        self.scale = float(self.cfg["scale"].get(label, 1.0))
        save_config(self.cfg)
        self._relayout()

    def _relayout(self) -> None:
        self.rscale = self.scale * self.ui
        self.disp_px = int(round(NATIVE_PX * self.rscale))
        self.pet_px = self.disp_px
        self.bubble_max_w = int(max(150, 240 * min(1.3, self.scale)) * self.ui)
        self.card_max_w = int(max(170, 268 * min(1.3, self.scale)) * self.ui)
        self.canvas.itemconfigure(self.pet_img_id, image=self._current_frame())
        if self.bubble_text:
            self._render_bubble()
        else:
            self._render_notice()

    def hide(self) -> None:
        self.hidden = True
        self.root.withdraw()

    def show(self) -> None:
        self.hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def toggle_visible(self) -> None:
        self.show() if self.hidden else self.hide()

    def quit(self) -> None:
        self.quitting = True
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


# ----------------------------------------------------------------- 自检

def selftest() -> int:
    print("[selftest] 依赖检查")
    print(f"  Python    : {sys.version.split()[0]}")
    print(f"  tkinter   : {'ok' if tk else 'missing'}")
    print(f"  Pillow    : {'ok' if HAS_PIL else '未安装（气泡将退化为纯文字）'}")
    ok = True
    manifest = os.path.join(ASSET_DIR, "manifest.json")
    if not os.path.exists(manifest):
        print("  pet_assets 缺失：请先运行 python make_pet_assets.py")
        return 1
    for mood in MOODS:
        folder = os.path.join(ASSET_DIR, mood)
        count = len([f for f in os.listdir(folder) if f.endswith(".png")]) if os.path.isdir(folder) else 0
        print(f"  帧 {mood:8s}: {count}")
        ok = ok and count > 0
    cfg = load_config()
    print(f"  字体      : {pick_font_path(cfg) or '默认'}")
    if HAS_PIL:
        bubble = make_bubble("自检：气泡渲染正常，中英文混排 Mixed OK 123", pick_font_path(cfg), 220)
        print(f"  气泡尺寸  : {bubble.size if bubble else 'n/a'}")
    print("[selftest] 通过" if ok else "[selftest] 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="桌面宠物")
    ap.add_argument("--selftest", action="store_true", help="只自检，不弹窗")
    ap.add_argument("--state", choices=MOODS, help="直接以某个状态启动")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    cfg = load_config()
    pet = DesktopPet(cfg)
    if args.state:
        pet.set_mood(args.state, STATE_TALK.get(args.state, ""), sound=False)
    pet.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
