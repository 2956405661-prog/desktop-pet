"""
生成桌面宠物的动画帧。

特点：
- 纯本地绘制（Pillow），不需要联网、不需要图片素材
- 输出带透明通道的 PNG 序列，任何支持透明图的框架都能用（tkinter / Electron / 网页）
- 顺便导出预览图 pet_assets/preview_states.png，方便看效果

用法：
    python make_pet_assets.py            # 生成到 ./pet_assets
    python make_pet_assets.py --out 某个目录
"""

from __future__ import annotations

import argparse
import json
import math
import os

from PIL import Image, ImageDraw

# ---------------------------------------------------------------- 基本参数

LOGICAL = 128       # 画的时候用的逻辑坐标系
SS = 6              # 超采样倍数，保证边缘干净
W = LOGICAL * SS    # 实际渲染画布
OUT = 384           # 输出尺寸：3 倍分辨率，覆盖到「大 + 200% 缩放」也不会被放大

# 整体右移：尾巴+描边最远能伸到逻辑坐标 -7.7，不移动就会被画布切掉
X_SHIFT = 7.0       # 逻辑像素（1 逻辑 = 3 实际像素）

OUTLINE = (26, 58, 62)
BODY = (128, 224, 206)
BODY_DARK = (96, 196, 180)
BELLY = (235, 253, 248)
CHEEK = (255, 152, 166)
EYE = (24, 38, 42)
WHITE = (255, 255, 255)
FLAME = (255, 172, 62)
FLAME_HI = (255, 228, 148)
SHADOW = (58, 108, 106)
SPARK = (255, 238, 158)
SPARK_CORE = (255, 255, 255)
BADGE = (86, 178, 255)
ALERT = (255, 106, 106)


def sx(v: float) -> float:
    """逻辑坐标 -> 画布坐标"""
    return (v + X_SHIFT) * SS


def box(x0, y0, x1, y1):
    return [sx(x0), sx(y0), sx(x1), sx(y1)]


# ---------------------------------------------------------------- 形状收集
#
# 为了同时得到「颜色」和「透明蒙版」，先把所有形状记下来，
# 再分别画到颜色画布和蒙版画布上。

class Shapes:
    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def ellipse(self, b, color):
        self.ops.append(("ellipse", b, color))

    def circle(self, cx, cy, r, color):
        self.ops.append(("ellipse", box(cx - r, cy - r, cx + r, cy + r), color))

    def polygon(self, pts, color):
        self.ops.append(("polygon", [(sx(x), sx(y)) for x, y in pts], color))

    def line(self, pts, width, color, cap=True):
        self.ops.append(("line", [(sx(x), sx(y)) for x, y in pts], max(1, int(round(sx(width)))), color, cap))

    def rounded(self, b, radius, color):
        self.ops.append(("rounded", b, sx(radius), color))

    # -- 渲染
    def render(self) -> Image.Image:
        color = Image.new("RGB", (W, W), OUTLINE)     # 底色=描边色，边缘像素自然过渡成描边
        mask = Image.new("L", (W, W), 0)
        cd = ImageDraw.Draw(color)
        md = ImageDraw.Draw(mask)
        for op in self.ops:
            kind = op[0]
            if kind == "ellipse":
                _, b, c = op
                cd.ellipse(b, fill=c)
                md.ellipse(b, fill=255)
            elif kind == "polygon":
                _, pts, c = op
                cd.polygon(pts, fill=c)
                md.polygon(pts, fill=255)
            elif kind == "rounded":
                _, b, r, c = op
                cd.rounded_rectangle(b, radius=r, fill=c)
                md.rounded_rectangle(b, radius=r, fill=255)
            elif kind == "line":
                _, pts, width, c, cap = op
                cd.line(pts, fill=c, width=width, joint="curve")
                md.line(pts, fill=255, width=width, joint="curve")
                if cap and len(pts) >= 2:
                    for (px, py) in (pts[0], pts[-1]):
                        cd.ellipse([px - width / 2, py - width / 2, px + width / 2, py + width / 2], fill=c)
                        md.ellipse([px - width / 2, py - width / 2, px + width / 2, py + width / 2], fill=255)
        color = color.resize((OUT, OUT), Image.LANCZOS)
        mask = mask.resize((OUT, OUT), Image.LANCZOS)
        out = color.convert("RGBA")
        # 蒙版二值化：大于一半算实体，其余完全透明（tkinter 透明色方案需要硬边）
        mask = mask.point(lambda v: 255 if v >= 118 else 0)
        out.putalpha(mask)
        return out


def bezier(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def star(s: Shapes, cx, cy, r, color, core=None):
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.34
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    s.polygon(pts, color)
    if core:
        s.circle(cx, cy, r * 0.22, core)


def zzz(s: Shapes, x, y, size, color):
    """画一个字母 Z"""
    w = max(1.4, size * 0.2)
    s.line([(x, y), (x + size, y)], w, color)
    s.line([(x + size, y), (x, y + size)], w, color)
    s.line([(x, y + size), (x + size, y + size)], w, color)


def gear(s: Shapes, cx, cy, r, color, teeth=6, phase=0.0):
    for i in range(teeth):
        ang = phase + 2 * math.pi * i / teeth
        x0, y0 = cx + math.cos(ang) * r * 0.72, cy + math.sin(ang) * r * 0.72
        x1, y1 = cx + math.cos(ang) * r * 1.32, cy + math.sin(ang) * r * 1.32
        s.line([(x0, y0), (x1, y1)], r * 0.44, color)
    s.circle(cx, cy, r, color)
    s.circle(cx, cy, r * 0.4, OUTLINE)


def draw_pet(*, breathe=0.0, hop=0.0, lean=0.0, eye="open", mouth="smile",
             tail_phase=0.0, arm=0.0, extras=(), squash=0.0) -> Image.Image:
    """画一帧。

    breathe: 0~1 呼吸幅度；hop: 离地高度；lean: 左右倾斜像素
    eye: open / blink / happy / closed；mouth: smile / open / flat
    tail_phase: 尾巴摆动相位；arm: 手臂抬起程度；extras: 特效列表
    """
    s = Shapes()

    cx = 64 + lean
    body_w = 37 * (1.0 + breathe * 0.045 - squash * 0.05)
    body_h = 34 * (1.0 - breathe * 0.06 + squash * 0.08)
    cy = 78 - hop + breathe * 1.2
    ground = 112.5

    # 影子
    shadow_w = 26 * (1.0 - min(0.35, hop / 42.0)) * (1.0 + squash * 0.1)
    s.ellipse(box(cx - shadow_w, ground - 3.2, cx + shadow_w, ground + 3.2), SHADOW)

    # 尾巴（身体后面，根部埋进身体里，看起来是连着的）
    t0 = (cx - body_w * 0.30, cy + body_h * 0.30)
    t2 = (cx - body_w - 17 - math.sin(tail_phase) * 3.2, cy - 14 + math.cos(tail_phase) * 5.0)
    t1 = (cx - body_w - 15, cy + body_h * 0.62)
    pts = [bezier(t0, t1, t2, i / 12) for i in range(13)]
    s.line(pts, 12.0, OUTLINE)
    s.line(pts, 8.4, BODY)
    s.line(pts[:6], 6.2, BODY_DARK)
    # 尾尖火苗
    tipx, tipy = t2
    flame = [(tipx, tipy - 11.5), (tipx + 6.2, tipy - 4.0), (tipx + 2.4, tipy + 6.0),
             (tipx - 2.6, tipy + 6.0), (tipx - 6.2, tipy - 4.0)]
    s.polygon([(x, y + 2.6) for x, y in flame], OUTLINE)
    s.polygon(flame, FLAME)
    s.circle(tipx - 1.0, tipy - 2.2, 2.4, FLAME_HI)

    # 耳朵
    for side in (-1, 1):
        ex = cx + side * body_w * 0.58
        ey = cy - body_h * 0.78
        ear = [(ex - 9.5, ey + 7.0), (ex + side * 2.0, ey - 11.5), (ex + 9.5, ey + 5.0)]
        s.polygon([(x + side * 0.0, y + 2.0) for x, y in ear], OUTLINE)
        s.polygon(ear, BODY)

    # 身体
    s.ellipse(box(cx - body_w - 2.6, cy - body_h - 2.6, cx + body_w + 2.6, cy + body_h + 2.6), OUTLINE)
    s.ellipse(box(cx - body_w, cy - body_h, cx + body_w, cy + body_h), BODY)
    s.ellipse(box(cx - body_w * 0.88, cy - body_h * 0.86, cx - body_w * 0.06, cy - body_h * 0.30), BODY_DARK)
    s.ellipse(box(cx + body_w * 0.18, cy - body_h * 0.80, cx + body_w * 0.74, cy - body_h * 0.26), BODY_DARK)
    s.ellipse(box(cx - body_w * 0.52, cy - body_h * 0.16, cx + body_w * 0.52, cy + body_h * 0.72), BELLY)

    # 脚
    for side in (-1, 1):
        fx = cx + side * body_w * 0.44
        s.ellipse(box(fx - 8.4, ground - 12.5 - hop * 0.0, fx + 8.4, ground - 0.4), OUTLINE)
        s.ellipse(box(fx - 6.6, ground - 10.8, fx + 6.6, ground - 1.8), BODY)

    # 手臂
    for side in (-1, 1):
        ax = cx + side * (body_w + 3.2)
        ay = cy + 2.0 - arm * 7.0
        s.circle(ax, ay, 6.4, OUTLINE)
        s.circle(ax, ay, 4.6, BODY)

    # 眼睛
    eye_dx = body_w * 0.42
    eye_y = cy - body_h * 0.22
    for side in (-1, 1):
        ex = cx + side * eye_dx
        if eye == "open":
            s.ellipse(box(ex - 5.6, eye_y - 7.6, ex + 5.6, eye_y + 7.6), EYE)
            s.circle(ex + side * 1.6, eye_y - 2.6, 2.5, WHITE)
            s.circle(ex - side * 1.4, eye_y + 2.8, 1.2, WHITE)
        elif eye == "blink":
            s.line([(ex - 5.6, eye_y), (ex + 5.6, eye_y)], 3.0, EYE)
        elif eye == "happy":
            s.line([(ex - 5.4, eye_y + 2.4), (ex, eye_y - 3.4), (ex + 5.4, eye_y + 2.4)], 3.0, EYE)
        else:  # closed / 睡觉
            s.line([(ex - 5.4, eye_y - 1.6), (ex, eye_y + 3.2), (ex + 5.4, eye_y - 1.6)], 3.0, EYE)

    # 腮红
    for side in (-1, 1):
        s.circle(cx + side * (body_w * 0.74), cy + 3.0, 4.0, CHEEK)

    # 嘴
    if mouth == "smile":
        s.line([(cx - 4.2, cy + 8.6), (cx, cy + 11.4), (cx + 4.2, cy + 8.6)], 2.4, EYE)
    elif mouth == "open":
        s.ellipse(box(cx - 4.6, cy + 7.2, cx + 4.6, cy + 14.2), EYE)
        s.ellipse(box(cx - 2.0, cy + 11.6, cx + 2.0, cy + 14.0), (255, 138, 150))
    else:
        s.line([(cx - 3.6, cy + 9.6), (cx + 3.6, cy + 9.6)], 2.4, EYE)

    # 特效
    for extra in extras:
        kind = extra[0]
        if kind == "spark":
            _, ex, ey, r, ph = extra
            star(s, ex, ey, r * (0.85 + 0.25 * math.sin(ph)), SPARK, SPARK_CORE)
        elif kind == "z":
            _, ex, ey, size = extra
            zzz(s, ex, ey, size, BODY_DARK)
        elif kind == "gear":
            _, ex, ey, r, ph = extra
            gear(s, ex, ey, r, BADGE, phase=ph)
        elif kind == "alert":
            _, ex, ey = extra
            s.rounded(box(ex - 3.4, ey - 12.0, ex + 3.4, ey + 3.0), 3.0, ALERT)
            s.circle(ex, ey + 8.0, 3.2, ALERT)
        elif kind == "dot":
            _, ex, ey, r, c = extra
            s.circle(ex, ey, r, c)

    return s.render()


# ---------------------------------------------------------------- 各状态帧

def frames_idle() -> list[Image.Image]:
    out = []
    n = 24                                    # 帧数：越多越顺，配合较短的帧间隔
    for i in range(n):
        t = i / n * 2 * math.pi
        breathe = (math.sin(t) + 1) / 2
        blink = i in (15, 16)
        eye = "blink" if blink else "open"
        # 尾巴相位必须在一轮里走「整数圈」，否则首尾接不上（会看到跳帧）
        out.append(draw_pet(breathe=breathe, eye=eye, tail_phase=t,
                            arm=0.06 * math.sin(t), mouth="smile"))
    return out


def frames_working() -> list[Image.Image]:
    out = []
    n = 24
    for i in range(n):
        t = i / n * 2 * math.pi
        breathe = (math.sin(t) + 1) / 2
        lean = math.sin(t) * 1.8
        out.append(draw_pet(breathe=breathe, lean=lean, eye="open", mouth="flat",
                            arm=0.55 + 0.35 * math.sin(t * 3),      # 手在快速捣鼓
                            tail_phase=t * 2,                        # 2 圈，首尾闭合
                            extras=[("gear", 96.0 + lean * 0.4, 40.0, 10.0, t * 3.0),
                                    ("spark", 28.0, 44.0 + math.sin(t * 2) * 3, 5.0, t * 2.0)]))
    return out


def frames_done() -> list[Image.Image]:
    out = []
    n = 30
    for i in range(n):
        t = i / n * 2 * math.pi
        hop = max(0.0, math.sin(t)) * 11.0
        breathe = (math.sin(t * 2) + 1) / 2
        out.append(draw_pet(breathe=breathe, hop=hop, squash=max(0.0, 0.5 - abs(math.sin(t)) * 0.5),
                            eye="happy", mouth="open", arm=0.85, tail_phase=t * 2,
                            extras=[("spark", 26.0, 30.0 + math.sin(t) * 4, 9.0, t * 3),
                                    ("spark", 104.0, 24.0 + math.cos(t) * 4, 7.5, t * 3 + 1.2),
                                    ("spark", 88.0, 60.0, 6.0, t * 3 + 2.4),
                                    ("spark", 16.0, 62.0, 5.0, t * 3 + 0.6)]))
    return out


def frames_alert() -> list[Image.Image]:
    out = []
    n = 30
    for i in range(n):
        t = i / n * 2 * math.pi
        hop = abs(math.sin(t)) * 6.0
        out.append(draw_pet(hop=hop, breathe=(math.sin(t * 2) + 1) / 2,
                            lean=math.sin(t * 2) * 1.6, eye="open", mouth="open",
                            arm=0.9, tail_phase=t * 3.0,
                            extras=[("alert", 100.0, 34.0)]))
    return out


def frames_sleep() -> list[Image.Image]:
    out = []
    n = 20
    for i in range(n):
        t = i / n * 2 * math.pi
        breathe = (math.sin(t) + 1) / 2
        zs = []
        for k in range(3):
            ph = (i / n + k / 3.0) % 1.0
            # 用「字号先涨后缩」当作淡入淡出：z 飘到头时缩成 0，就不会在循环处"闪现"到起点
            env = min(1.0, ph / 0.18) * min(1.0, (1.0 - ph) / 0.22)
            if env <= 0.06:
                continue
            zs.append(("z", 85.0 + ph * 11.0, 46.0 - ph * 26.0, (7.0 + ph * 5.0) * env))
        out.append(draw_pet(breathe=breathe * 1.25, eye="closed", mouth="smile",
                            squash=breathe * 0.35, arm=-0.2, tail_phase=t,
                            extras=zs))
    return out


STATES = {
    # 帧间隔（毫秒）：越小越顺。原来 85~170ms（8~12 帧/秒）看着一顿一顿的
    "idle": (frames_idle, 42),
    "working": (frames_working, 40),
    "done": (frames_done, 34),
    "alert": (frames_alert, 32),
    "sleep": (frames_sleep, 72),
}


def write_assets(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"size": OUT, "logical": LOGICAL, "states": {}}
    for name, (fn, delay) in STATES.items():
        frames = fn()
        d = os.path.join(out_dir, name)
        os.makedirs(d, exist_ok=True)
        for idx, frame in enumerate(frames):
            frame.save(os.path.join(d, f"frame_{idx:02d}.png"))
        manifest["states"][name] = {"count": len(frames), "delay_ms": delay}
        print(f"{name:8s} {len(frames):2d} 帧 -> {d}")
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # 预览图：每个状态横向铺一排
    cell = OUT // 2
    preview = Image.new("RGBA", (cell * 6, cell * len(STATES)), (245, 246, 248, 255))
    for row, name in enumerate(STATES):
        frames = STATES[name][0]()
        picks = [frames[int(i * len(frames) / 6)] for i in range(6)]
        for col, frame in enumerate(picks):
            preview.alpha_composite(frame.resize((cell, cell), Image.LANCZOS), (col * cell, row * cell))
    preview_path = os.path.join(out_dir, "preview_states.png")
    preview.save(preview_path)
    print(f"预览图 -> {preview_path}")

    # 每个动作再导一份循环动图，方便肉眼检查首尾是否接得上
    for name, (fn, delay) in STATES.items():
        frames = fn()
        cell = OUT // 2
        small = [f.resize((cell, cell), Image.LANCZOS) for f in frames]
        gif_path = os.path.join(out_dir, f"预览-{name}.gif")
        small[0].save(gif_path, save_all=True, append_images=small[1:],
                      duration=delay, loop=0, disposal=2, transparency=0)
        print(f"动图   -> {gif_path}")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="生成桌面宠物动画帧")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_assets"))
    args = ap.parse_args()
    write_assets(args.out)


if __name__ == "__main__":
    main()
