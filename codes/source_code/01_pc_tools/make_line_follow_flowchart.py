from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(r"D:\parking_board_agent\docs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "line_follow_flowchart.png"

SCALE = 2  # supersampling for antialiasing
W, H = 1800, 2200


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


img = Image.new("RGB", (W * SCALE, H * SCALE), "#F7F9FC")
d = ImageDraw.Draw(img)

font_title = font(52, True)
font_node = font(30, True)
font_small = font(24, False)
font_label = font(24, True)
font_caption = font(24, False)


def sc(v):
    return int(round(v * SCALE))


def pts(points):
    return [(sc(x), sc(y)) for x, y in points]


C_START = "#DDF6E5"
C_PROC = "#E8F1FF"
C_CORE = "#FFF2CC"
C_DEC = "#FFE4E6"
C_ACTION = "#EDE9FE"
C_FAIL = "#FFEFD6"
C_STROKE = "#334155"
C_ARROW = "#475569"
C_TEXT = "#0F172A"
C_MUTED = "#475569"


def center_text(x, y, text, fnt, fill=C_TEXT):
    bb = d.textbbox((0, 0), text, font=fnt)
    d.text((sc(x) - (bb[2] - bb[0]) // 2, sc(y) - (bb[3] - bb[1]) // 2), text, font=fnt, fill=fill)


center_text(W / 2, 70, "line_follow 倒车决策流程图", font_title)
center_text(W / 2, 130, "基于闭环预演的纯倒车可达性判断与前进调整", font_caption, C_MUTED)


def wrap_text(text, fnt, max_w):
    lines = []
    for para in str(text).split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            test = cur + ch
            if d.textlength(test, font=fnt) <= max_w * SCALE or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines


def draw_text_center(cx, cy, text, box_w, fnt=font_node, fill=C_TEXT, line_gap=7):
    lines = wrap_text(text, fnt, box_w - 36)
    sizes = [d.textbbox((0, 0), line, font=fnt) for line in lines]
    heights = [bb[3] - bb[1] for bb in sizes]
    widths = [bb[2] - bb[0] for bb in sizes]
    total = sum(heights) + sc(line_gap) * (len(lines) - 1)
    y = sc(cy) - total // 2
    for line, wdt, hgt in zip(lines, widths, heights):
        d.text((sc(cx) - wdt // 2, y), line, font=fnt, fill=fill)
        y += hgt + sc(line_gap)


def rounded_rect(cx, cy, w, h, fill, outline=C_STROKE, radius=28, width=3, text="", fnt=font_node):
    x1, y1, x2, y2 = sc(cx - w / 2), sc(cy - h / 2), sc(cx + w / 2), sc(cy + h / 2)
    d.rounded_rectangle((x1 + sc(6), y1 + sc(8), x2 + sc(6), y2 + sc(8)), radius=sc(radius), fill="#D5DCE8")
    d.rounded_rectangle((x1, y1, x2, y2), radius=sc(radius), fill=fill, outline=outline, width=sc(width))
    if text:
        draw_text_center(cx, cy, text, w, fnt)


def diamond(cx, cy, w, h, fill, outline=C_STROKE, width=3, text="", fnt=font_node):
    poly = pts([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)])
    shadow = pts([(cx + 6, cy - h / 2 + 8), (cx + w / 2 + 6, cy + 8), (cx + 6, cy + h / 2 + 8), (cx - w / 2 + 6, cy + 8)])
    d.polygon(shadow, fill="#D5DCE8")
    d.polygon(poly, fill=fill)
    d.line(poly + [poly[0]], fill=outline, width=sc(width), joint="curve")
    if text:
        draw_text_center(cx, cy, text, w * 0.72, fnt)


nodes = {
    "A": ("round", 720, 230, 520, 100, "输入当前车辆位姿和车位目标线", C_START),
    "B": ("round", 720, 380, 560, 120, "计算相对状态\n纵向距离 y｜横向偏差 l｜航向误差 ψ", C_PROC),
    "C": ("round", 720, 560, 600, 140, "line_follow 控制律\n生成期望倒车曲率 κ", C_CORE),
    "D": ("round", 720, 740, 520, 110, "曲率限幅\n满足底盘最大转向约束", C_PROC),
    "E": ("round", 720, 900, 520, 110, "实测曲率-STE 标定表\nκ → STE 控制量", C_PROC),
    "F": ("round", 720, 1080, 620, 135, "闭环 rollout 预演\n评估纯倒车是否进入目标区域", C_CORE),
    "G": ("diamond", 720, 1260, 420, 150, "纯倒车\n可达？", C_DEC),
    "H": ("round", 720, 1440, 460, 105, "执行一步倒车\nREV + STE", C_ACTION),
    "I": ("diamond", 720, 1610, 390, 140, "达到泊车\n判据？", C_DEC),
    "J": ("round", 720, 1800, 430, 100, "泊车完成", C_START),
    "K": ("round", 1320, 1260, 500, 115, "搜索前进调整段\n改变车辆位置与航向", C_ACTION),
    "L": ("round", 1320, 1435, 540, 125, "预演调整后倒车轨迹\n评估是否满足目标", C_CORE),
    "M": ("diamond", 1320, 1625, 420, 150, "存在可行\n调整段？", C_DEC),
    "N": ("round", 1320, 1810, 530, 110, "执行最优前进调整段\n更新位姿后重新规划", C_ACTION),
    "O": ("round", 1320, 1990, 520, 110, "安全停止/重新感知\n或切换备用策略", C_FAIL),
}


def anchor(n, side):
    _, cx, cy, w, h, _, _ = nodes[n]
    return {
        "top": (cx, cy - h / 2),
        "bottom": (cx, cy + h / 2),
        "left": (cx - w / 2, cy),
        "right": (cx + w / 2, cy),
    }[side]


def arrow_line(points, label=None, label_pos=0.5, color=C_ARROW, width=4):
    ps = pts(points)
    for i in range(len(ps) - 1):
        d.line([ps[i], ps[i + 1]], fill=color, width=sc(width), joint="curve")

    (x1, y1), (x2, y2) = points[-2], points[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    ah, aw = 18, 11
    p1 = (x2 - ah * math.cos(ang) + aw * math.sin(ang), y2 - ah * math.sin(ang) - aw * math.cos(ang))
    p2 = (x2 - ah * math.cos(ang) - aw * math.sin(ang), y2 - ah * math.sin(ang) + aw * math.cos(ang))
    d.polygon(pts([(x2, y2), p1, p2]), fill=color)

    if label:
        segs, total = [], 0
        for a, b in zip(points[:-1], points[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            segs.append((a, b, length))
            total += length
        dist, acc = total * label_pos, 0
        lx, ly = points[0]
        for a, b, length in segs:
            if acc + length >= dist:
                t = (dist - acc) / length if length else 0
                lx = a[0] + (b[0] - a[0]) * t
                ly = a[1] + (b[1] - a[1]) * t
                break
            acc += length
        bb = d.textbbox((0, 0), label, font=font_label)
        pad = 8
        rect = (
            sc(lx) - (bb[2] - bb[0]) // 2 - sc(pad),
            sc(ly) - (bb[3] - bb[1]) // 2 - sc(pad),
            sc(lx) + (bb[2] - bb[0]) // 2 + sc(pad),
            sc(ly) + (bb[3] - bb[1]) // 2 + sc(pad),
        )
        d.rounded_rectangle(rect, radius=sc(12), fill="#FFFFFF", outline="#CBD5E1", width=sc(2))
        d.text((sc(lx) - (bb[2] - bb[0]) // 2, sc(ly) - (bb[3] - bb[1]) // 2 - sc(1)), label, font=font_label, fill=C_TEXT)


# Arrows under nodes
for a, b in zip(["A", "B", "C", "D", "E", "F"], ["B", "C", "D", "E", "F", "G"]):
    arrow_line([anchor(a, "bottom"), anchor(b, "top")])

arrow_line([anchor("G", "bottom"), anchor("H", "top")], label="可达", label_pos=0.45)
arrow_line([anchor("H", "bottom"), anchor("I", "top")])
arrow_line([anchor("I", "bottom"), anchor("J", "top")], label="满足", label_pos=0.45)
arrow_line([anchor("I", "left"), (380, 1610), (380, 380), anchor("B", "left")], label="未满足，继续观测", label_pos=0.18)

arrow_line([anchor("G", "right"), anchor("K", "left")], label="不可达", label_pos=0.50)
arrow_line([anchor("K", "bottom"), anchor("L", "top")])
arrow_line([anchor("L", "bottom"), anchor("M", "top")])
arrow_line([anchor("M", "bottom"), anchor("N", "top")], label="存在", label_pos=0.50)
arrow_line([anchor("N", "left"), (1060, 1810), (1020, 2025), (250, 2025), (250, 380), anchor("B", "left")], label="更新后重规划", label_pos=0.70)

arrow_line([anchor("M", "bottom"), anchor("O", "top")], label="不存在", label_pos=0.5)
arrow_line([anchor("O", "left"), (1030, 1990), (1030, 2085), (200, 2085), (200, 380), anchor("B", "left")], label="安全处理后重新观测", label_pos=0.67)


for key in nodes:
    typ, cx, cy, w, h, txt, fill = nodes[key]
    if typ == "diamond":
        diamond(cx, cy, w, h, fill, text=txt)
    else:
        rounded_rect(cx, cy, w, h, fill, text=txt)

rounded_rect(
    1450,
    330,
    560,
    230,
    "#FFFFFF",
    outline="#94A3B8",
    radius=22,
    width=2,
    text="核心依据\n由 rollout 评估物理可达性\n决定是否插入前进调整段",
    fnt=font_small,
)

center_text(W / 2, 2145, "注：rollout 表示执行前闭环仿真；shuffle/前进调整段表示短距离前进换向动作；STE 为舵机控制量。", font_caption, C_MUTED)

img = img.resize((W, H), Image.Resampling.LANCZOS)
img.save(OUT_PATH)
print(OUT_PATH)
