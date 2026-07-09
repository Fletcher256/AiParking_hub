from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


OUT = Path(r"D:\parking_board_agent\docs\project_design_flowchart_preview.png")
OUT.parent.mkdir(parents=True, exist_ok=True)

S = 2
W, H = 2100, 1360


def font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size * S)
    return ImageFont.load_default()


img = Image.new("RGB", (W * S, H * S), "#F7F9FC")
d = ImageDraw.Draw(img)

F_TITLE = font(48, True)
F_SUB = font(24)
F_H = font(25, True)
F_B = font(19)
F_SMALL = font(19)
F_TAG = font(19, True)

C_TEXT = "#0F172A"
C_MUTED = "#475569"
C_STROKE = "#334155"
C_ARROW = "#475569"
C_BLUE = "#E8F1FF"
C_GREEN = "#DDF6E5"
C_YELLOW = "#FFF2CC"
C_PURPLE = "#EDE9FE"
C_PINK = "#FFE4E6"
C_ORANGE = "#FFEFD6"
C_WHITE = "#FFFFFF"
C_ACCENT = "#2563A9"


def sc(v):
    return int(round(v * S))


def pts(points):
    return [(sc(x), sc(y)) for x, y in points]


def text_size(text, f):
    bb = d.textbbox((0, 0), text, font=f)
    return bb[2] - bb[0], bb[3] - bb[1]


def center_text(cx, cy, text, f, fill=C_TEXT):
    tw, th = text_size(text, f)
    d.text((sc(cx) - tw // 2, sc(cy) - th // 2), text, font=f, fill=fill)


def wrap_text(text, f, max_w):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            test = cur + ch
            if d.textlength(test, font=f) <= max_w * S or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines


def draw_center_multiline(cx, cy, text, width, f, fill=C_TEXT, gap=5):
    lines = wrap_text(text, f, width - 30)
    sizes = [text_size(line, f) for line in lines]
    total = sum(h for _, h in sizes) + sc(gap) * (len(lines) - 1)
    y = sc(cy) - total // 2
    for line, (tw, th) in zip(lines, sizes):
        d.text((sc(cx) - tw // 2, y), line, font=f, fill=fill)
        y += th + sc(gap)


def rounded(cx, cy, w, h, fill, title=None, body=None, radius=24, outline=C_STROKE, lw=3):
    x1, y1, x2, y2 = sc(cx - w / 2), sc(cy - h / 2), sc(cx + w / 2), sc(cy + h / 2)
    d.rounded_rectangle((x1 + sc(6), y1 + sc(8), x2 + sc(6), y2 + sc(8)), radius=sc(radius), fill="#D5DCE8")
    d.rounded_rectangle((x1, y1, x2, y2), radius=sc(radius), fill=fill, outline=outline, width=sc(lw))
    if title and body:
        draw_center_multiline(cx, cy - 28, title, w, F_H)
        draw_center_multiline(cx, cy + 32, body, w, F_B, fill=C_MUTED, gap=4)
    elif title:
        draw_center_multiline(cx, cy, title, w, F_H)


def arrow(points, label=None, label_pos=0.5, color=C_ARROW, lw=4):
    ps = pts(points)
    for a, b in zip(ps[:-1], ps[1:]):
        d.line([a, b], fill=color, width=sc(lw), joint="curve")
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
        target, acc = total * label_pos, 0
        lx, ly = points[0]
        for a, b, length in segs:
            if acc + length >= target:
                t = (target - acc) / length if length else 0
                lx = a[0] + (b[0] - a[0]) * t
                ly = a[1] + (b[1] - a[1]) * t
                break
            acc += length
        tw, th = text_size(label, F_TAG)
        pad = 7
        d.rounded_rectangle(
            (sc(lx) - tw // 2 - sc(pad), sc(ly) - th // 2 - sc(pad), sc(lx) + tw // 2 + sc(pad), sc(ly) + th // 2 + sc(pad)),
            radius=sc(10),
            fill=C_WHITE,
            outline="#CBD5E1",
            width=sc(2),
        )
        d.text((sc(lx) - tw // 2, sc(ly) - th // 2), label, font=F_TAG, fill=C_TEXT)


def bracket_label(x, y1, y2, text, color=C_ACCENT):
    d.line([(sc(x), sc(y1)), (sc(x), sc(y2))], fill=color, width=sc(5))
    d.line([(sc(x), sc(y1)), (sc(x + 18), sc(y1))], fill=color, width=sc(5))
    d.line([(sc(x), sc(y2)), (sc(x + 18), sc(y2))], fill=color, width=sc(5))
    draw_center_multiline(x - 55, (y1 + y2) / 2, text, 100, F_TAG, fill=color)


# Title
center_text(W / 2, 58, "视觉闭环自主泊车系统设计流程图", F_TITLE)
center_text(W / 2, 110, "从需求约束、软硬件设计到验证复盘的总体设计路线", F_SUB, C_MUTED)


# Row 1: design process
xs = [260, 530, 800, 1070, 1340, 1610, 1880]
y = 260
top_nodes = [
    ("1 需求与约束", "低速泊车场景\n窄空间｜弱转向｜安全可停", C_GREEN),
    ("2 硬件平台", "SS928 边缘主控\n摄像头 + STM32 底盘", C_BLUE),
    ("3 感知标定", "YOLO 车位 polygon\nHomography 位姿估计", C_BLUE),
    ("4 底盘标定", "实测曲率-STE 表\n死区｜滑行量｜符号约定", C_YELLOW),
    ("5 决策规划", "line_follow 控制律\nrollout 可达性预演", C_YELLOW),
    ("6 安全执行", "短动作闭环\n授权｜状态门｜STOP", C_PURPLE),
    ("7 验证复盘", "单元/集成/蒙特卡洛\n实车日志 + 视频", C_ORANGE),
]
for x, (title, body, color) in zip(xs, top_nodes):
    rounded(x, y, 235, 150, color, title, body)
for a, b in zip(xs[:-1], xs[1:]):
    arrow([(a + 118, y), (b - 118, y)])


# Row 2: runtime chain
center_text(W / 2, 445, "板端实时闭环执行链路", F_H, C_ACCENT)
rt_y = 590
rt_xs = [275, 585, 895, 1205, 1515, 1825]
runtime_nodes = [
    ("摄像头采集", "OS08A20\n获取车位画面", C_BLUE),
    ("车位识别", "YOLO 检测/分割\n输出 polygon", C_BLUE),
    ("相对位姿", "y_dist / lateral\nheading", C_GREEN),
    ("运动决策", "line_follow\nrollout / shuffle", C_YELLOW),
    ("底盘执行", "ARC / MOVE / STOP\nSTM32 控制", C_PURPLE),
    ("反馈更新", "里程 / yaw / DONE\n重新观测", C_GREEN),
]
for x, (title, body, color) in zip(rt_xs, runtime_nodes):
    rounded(x, rt_y, 250, 125, color, title, body)
for a, b in zip(rt_xs[:-1], rt_xs[1:]):
    arrow([(a + 125, rt_y), (b - 125, rt_y)])
arrow([(1825, rt_y + 68), (1825, 745), (895, 745), (895, rt_y + 68)], label="停-看-走闭环", label_pos=0.46)


# Row 3: decision detail
center_text(W / 2, 850, "核心决策逻辑", F_H, C_ACCENT)
sub_y = 990
sub_xs = [385, 715, 1045, 1375, 1705]
sub_nodes = [
    ("生成期望曲率", "临界阻尼直线跟踪律", C_YELLOW),
    ("曲率限幅与反查", "满足底盘转向约束\nκ → STE", C_BLUE),
    ("闭环预演", "rollout 判断\n纯倒车是否可达", C_YELLOW),
    ("可达路径", "执行一步倒车\n动作后重新观测", C_GREEN),
    ("不可达路径", "搜索前进调整段\n再进入下一轮规划", C_PINK),
]
for x, (title, body, color) in zip(sub_xs, sub_nodes):
    rounded(x, sub_y, 260, 120, color, title, body)
arrow([(sub_xs[0] + 130, sub_y), (sub_xs[1] - 130, sub_y)])
arrow([(sub_xs[1] + 130, sub_y), (sub_xs[2] - 130, sub_y)])
arrow([(sub_xs[2] + 130, sub_y), (sub_xs[3] - 130, sub_y)], label="可达", label_pos=0.5)
arrow([(sub_xs[2], sub_y + 60), (sub_xs[2], 1125), (sub_xs[4], 1125), (sub_xs[4], sub_y + 60)], label="不可达", label_pos=0.55)
arrow([(sub_xs[3], sub_y - 60), (sub_xs[3], 835), (1825, 835), (1825, rt_y + 68)], label="反馈", label_pos=0.72)
arrow([(sub_xs[4], sub_y - 60), (sub_xs[4], 835), (1825, 835)], color=C_ARROW)


# Side labels
bracket_label(110, 188, 335, "设计阶段")
bracket_label(110, 520, 745, "运行闭环")
bracket_label(110, 925, 1125, "决策核心")

footer = "说明：本图用于展示项目总体设计路线，强调“感知—位姿—规划—执行—反馈—复盘”的闭环设计。"
center_text(W / 2, 1295, footer, F_SMALL, C_MUTED)

img = img.resize((W, H), Image.Resampling.LANCZOS)
img.save(OUT)
print(OUT)
