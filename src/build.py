#!/usr/bin/env python3
"""生成 GitHub 主页用的 SVG：文字转字形路径（GitHub 上不会字体回退），CSS 动画，预览帧内嵌为 base64。

  python3 src/build.py      # 输出到 assets/
"""
import base64
import io
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "src" / "raw"
OUT = ROOT / "assets"
FONTS = ROOT / "fonts"

PAPER, INK, SEAL, MUTED, RULE = "#F3EEE4", "#17150F", "#D93A26", "#8A8478", "#D9D2C3"
REDUCED = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"


class Face:
    def __init__(self, key: str, file: str):
        self.key = key
        self.font = TTFont(FONTS / file)
        self.cmap = self.font.getBestCmap()
        self.gs = self.font.getGlyphSet()
        self.hmtx = self.font["hmtx"]
        self.upm = self.font["head"].unitsPerEm

    def glyph(self, ch: str) -> str:
        return self.cmap.get(ord(ch)) or self.cmap[ord("?")]

    def width(self, text: str, size: float, track: float = 0) -> float:
        units = sum(self.hmtx[self.glyph(c)][0] for c in text)
        return units * size / self.upm + track * size * max(len(text) - 1, 0)


FACES = {
    "serif": Face("sf", "NotoSerifSC-Black.otf"),
    "serifm": Face("sm", "NotoSerifSC-Medium.otf"),
    "sans": Face("sb", "NotoSansSC-Bold.otf"),
    "sansr": Face("sr", "NotoSansSC-Regular.otf"),
    "mono": Face("mo", "JetBrainsMono-Medium.ttf"),
}


class Doc:
    """一个 SVG 文件：收集字形定义、样式和图层。"""

    def __init__(self, w: int, h: int, title: str):
        self.w, self.h, self.title = w, h, title
        self.defs: dict[str, str] = {}
        self.extra_defs: list[str] = []
        self.css: list[str] = []
        self.body: list[str] = []

    def text(self, s: str, x: float, y: float, size: float, face: str = "serif", fill: str = INK,
             track: float = 0, anchor: str = "start", cls: str = "", opacity: float = 1) -> float:
        f = FACES[face]
        w = f.width(s, size, track)
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        k = size / f.upm
        uses, cur = [], 0.0
        for ch in s:
            g = f.glyph(ch)
            gid = f"{f.key}{f.font.getGlyphID(g)}"
            if ch != " " and gid not in self.defs:
                pen = SVGPathPen(f.gs)
                f.gs[g].draw(pen)
                d = pen.getCommands()
                if d:
                    self.defs[gid] = f'<path id="{gid}" d="{d}"/>'
            if gid in self.defs:
                uses.append(f'<use href="#{gid}" x="{cur:.0f}"/>')
            cur += f.hmtx[g][0] + track * f.upm
        c = f' class="{cls}"' if cls else ""
        o = f' opacity="{opacity}"' if opacity != 1 else ""
        self.body.append(f'<g{c}{o} fill="{fill}" transform="translate({x:.1f} {y:.1f}) scale({k:.5f} {-k:.5f})">{"".join(uses)}</g>')
        return w

    def add(self, s: str):
        self.body.append(s)

    def render(self) -> str:
        css = "".join(self.css) + REDUCED
        defs = "".join(self.defs.values()) + "".join(self.extra_defs)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" role="img" aria-labelledby="t"><title id="t">{self.title}</title>'
                f'<style>{css}</style><defs>{defs}</defs>{"".join(self.body)}</svg>')


def jpeg(path: Path, w: int, h: int, q: int = 72, top: float = 0.5, box: tuple | None = None) -> str:
    """裁成 w×h（cover），top 控制纵向取景位置（0 顶部，0.5 居中）；box 是先按比例裁掉的边（左上右下）。"""
    im = Image.open(path).convert("RGB")
    if box:
        im = im.crop((round(box[0] * im.width), round(box[1] * im.height), round(box[2] * im.width), round(box[3] * im.height)))
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x = (im.width - w) // 2
    y = round((im.height - h) * top)
    im = im.crop((x, y, x + w, y + h))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def cycle_css(name: str, n: int, period: float, fade: float) -> str:
    """n 张叠放的帧轮流显示；fade=0 为硬切（翻页式），否则交叉淡入。返回 css，帧用 .{name}{i}。"""
    seg = 100 / n
    if fade <= 0:
        kf = f"@keyframes {name}{{0%,{seg - 0.01:.3f}%{{opacity:1}}{seg:.3f}%,100%{{opacity:0}}}}"
        timing = "steps(1)"
    else:
        f = fade / period * 100
        kf = (f"@keyframes {name}{{0%{{opacity:0}}{f:.3f}%,{seg:.3f}%{{opacity:1}}"
              f"{seg + f:.3f}%,100%{{opacity:0}}}}")
        timing = "linear"
    rules = "".join(f".{name}{i}{{opacity:0;animation:{name} {period}s {timing} infinite;"
                    f"animation-delay:{-(period - i * period / n) % period:.3f}s}}" for i in range(n))
    return kf + rules


def rounded_clip(doc: Doc, cid: str, x: float, y: float, w: float, h: float, r: float):
    doc.extra_defs.append(f'<clipPath id="{cid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/></clipPath>')


def chips(doc: Doc, items: list[str], x: float, y: float, color: str, solid_last: bool = False):
    for i, s in enumerate(items):
        w = FACES["mono"].width(s, 13.5, 0.08) + 28
        solid = solid_last and i == len(items) - 1
        doc.add(f'<rect x="{x:.1f}" y="{y - 22}" width="{w:.1f}" height="32" rx="16" '
                f'fill="{color if solid else "none"}" stroke="{color}" stroke-width="1.4"/>')
        doc.text(s, x + 14, y - 1, 13.5, "mono", "#fff" if solid else color, track=0.08)
        x += w + 10


# ---------------------------------------------------------------------------
# 页头
# ---------------------------------------------------------------------------
SKILLS = ["DESIGNER", "DIRECTOR", "SHORT-DRAMA", "EDITOR", "STUDIO", "OPUS3D", "GEN-UI", "GEN-VIDEO",
          "GEN-IMAGE", "GEN-COVER", "INFOGRAPHIC", "PPT", "VIDEO-SCRIPT", "WRITE-ARTICLE", "WRITE-XHS", "DE-AI"]


def header() -> str:
    d = Doc(1300, 270, "小马 MJH · 不懂审美的程序员，不是好产品经理。I build AI creative skills with taste.")
    rounded_clip(d, "hc", 0, 0, 1300, 270, 22)
    d.css.append("@keyframes ul{0%,10%{transform:scaleX(0)}28%,86%{transform:scaleX(1)}100%{transform:scaleX(0)}}"
                 ".ul{transform-box:fill-box;transform-origin:left center;animation:ul 7s cubic-bezier(.65,0,.35,1) infinite}"
                 "@keyframes mq{from{transform:translateX(0)}to{transform:translateX(-50%)}}"
                 ".mq{animation:mq 38s linear infinite}"
                 "@keyframes stamp{0%,78%{transform:scale(1);opacity:1}82%{transform:scale(1.12);opacity:.55}"
                 "88%{transform:scale(.97);opacity:1}92%,100%{transform:scale(1)}}"
                 ".stamp{transform-box:fill-box;transform-origin:center;animation:stamp 7s cubic-bezier(.3,0,.2,1) infinite}"
                 "@keyframes cur{0%,49.9%{opacity:1}50%,100%{opacity:0}}.cur{animation:cur 1.1s steps(1) infinite}")
    d.add('<g clip-path="url(#hc)">')
    d.add(f'<rect width="1300" height="270" fill="{PAPER}"/>')
    d.extra_defs.append(f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
                        f'<circle cx="2" cy="2" r="1.1" fill="{RULE}"/></pattern>')
    d.add('<rect width="1300" height="214" fill="url(#dots)" opacity=".9"/>')
    # 印章
    d.add('<g class="stamp">')
    d.add(f'<rect x="68" y="50" width="104" height="104" rx="14" fill="{SEAL}"/>')
    d.add(f'<rect x="76" y="58" width="88" height="88" rx="9" fill="none" stroke="{PAPER}" stroke-width="2" opacity=".85"/>')
    d.text("小", 120, 98, 40, "serif", PAPER, anchor="middle")
    d.text("马", 120, 138, 40, "serif", PAPER, anchor="middle")
    d.add('</g>')
    d.text("MJH", 196, 122, 66, "serif", INK, track=0.02)
    d.text("@crawfordxx", 200, 154, 17, "mono", MUTED, track=0.06)
    # 分隔竖线
    d.add(f'<path d="M520 52V164" stroke="{RULE}" stroke-width="1.5"/>')
    # 口号
    x0 = 562
    w1 = d.text("不懂", x0, 104, 38, "serif", INK)
    w2 = FACES["serif"].width("审美", 38)
    d.add(f'<rect class="ul" x="{x0 + w1:.1f}" y="110" width="{w2:.1f}" height="6" rx="3" fill="{SEAL}"/>')
    d.text("不懂审美的程序员，不是好产品经理。", x0, 104, 38, "serif", INK)
    d.add(f'<rect class="cur" x="{x0 + FACES["serif"].width("不懂审美的程序员，不是好产品经理。", 38) + 8:.1f}" '
          f'y="72" width="5" height="38" fill="{SEAL}"/>')
    d.text("Taste is a feature. I build AI creative skills that ship it.", x0, 146, 21, "serifm", "#5A554B")
    d.text("AI CREATIVE SKILLS  ·  AGENTS  ·  MOTION  ·  DESIGN", x0, 180, 14, "mono", MUTED, track=0.14)
    # 底部滚动带：16 个技能名
    d.add(f'<rect y="214" width="1300" height="56" fill="{INK}"/>')
    band = "  ✦  ".join(f"XIAOMA-{s}" for s in SKILLS) + "  ✦  "
    # ✦ 不在等宽字体里，换成中点
    band = band.replace("✦", "•")
    bw = FACES["mono"].width(band, 14, 0.12)
    d.add('<g class="mq">')
    d.text(band, 24, 248, 14, "mono", PAPER, track=0.12)
    d.text(band, 24 + bw + 14 * 0.12, 248, 14, "mono", PAPER, track=0.12)
    d.add('</g>')
    d.add('</g>')
    return d.render()


# ---------------------------------------------------------------------------
# 分隔线与页脚
# ---------------------------------------------------------------------------
def divider(n: str) -> str:
    d = Doc(1300, 52, "")
    d.css.append("@keyframes sw{0%{transform:translateX(0)}70%,100%{transform:translateX(1700px)}}"
                 ".sw{animation:sw 5s cubic-bezier(.45,0,.25,1) infinite}")
    d.extra_defs.append(f'<linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{SEAL}" stop-opacity="0"/>'
                        f'<stop offset=".6" stop-color="{SEAL}"/><stop offset="1" stop-color="{SEAL}" stop-opacity="0"/></linearGradient>'
                        '<clipPath id="ln"><rect x="0" y="24" width="606" height="5"/><rect x="694" y="24" width="606" height="5"/></clipPath>')
    d.add('<path d="M0 26.5H606M694 26.5H1300" stroke="rgba(140,136,128,.5)" stroke-width="1.4"/>')
    d.add('<g clip-path="url(#ln)"><rect class="sw" x="-360" y="25" width="360" height="3" rx="1.5" fill="url(#g)"/></g>')
    d.add(f'<rect x="628" y="8" width="44" height="37" rx="7" fill="{SEAL}"/>')
    d.text(n, 650, 32.5, 15, "mono", PAPER, anchor="middle", track=0.04)
    return d.render()


def footer() -> str:
    d = Doc(1300, 190, "觉得有用，就点一颗 star 吧。If something here helps, a star keeps me shipping.")
    rounded_clip(d, "fc", 0, 0, 1300, 190, 22)
    d.css.append("@keyframes tw{0%,100%{opacity:.15}50%{opacity:.9}}.tw{animation:tw 3.2s ease-in-out infinite}")
    d.add(f'<g clip-path="url(#fc)"><rect width="1300" height="190" fill="{INK}"/>')
    import random
    rnd = random.Random(7)
    for i in range(46):
        x, y, r = rnd.uniform(20, 1280), rnd.uniform(12, 178), rnd.choice([0.9, 1.2, 1.6])
        d.add(f'<circle class="tw" style="animation-delay:-{rnd.uniform(0, 3.2):.2f}s" cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{PAPER}"/>')
    d.add(f'<rect x="64" y="56" width="78" height="78" rx="12" fill="{SEAL}"/>')
    d.text("★", 103, 112, 40, "sans", PAPER, anchor="middle")
    d.text("觉得有用，就点一颗 star 吧。", 174, 96, 32, "serif", PAPER)
    d.text("If something here helps, a star keeps me shipping. Thanks for stopping by.", 176, 132, 17, "serifm", "#B9B2A4")
    d.add(f'<rect x="1030" y="74" width="206" height="44" rx="22" fill="{PAPER}"/>')
    d.text("XMCOURSE.COM  ↗", 1133, 101.5, 14, "mono", INK, anchor="middle", track=0.1)
    d.add('</g>')
    return d.render()


# ---------------------------------------------------------------------------
# 项目卡
# ---------------------------------------------------------------------------
def card_shell(d: Doc, no: str, kind: str, name: str, zh: list[str], en: str, items: list[str],
               bg: str, fg: str, sub: str, accent: str, icon: str):
    rounded_clip(d, "cc", 0, 0, 1300, 380, 22)
    d.add('<g clip-path="url(#cc)">')
    d.add(f'<rect width="560" height="380" fill="{bg}"/>')
    d.text(f"№ {no}  ·  {kind}", 44, 58, 14.5, "mono", accent, track=0.16)
    d.add(f'<rect x="44" y="84" width="58" height="58" rx="13" fill="{accent}"/>')
    d.add(icon)
    d.text(name, 120, 126, 34 if len(name) < 16 else 29, "sans", fg)
    y = 190
    for line in zh:
        d.text(line, 44, y, 27, "serif", fg)
        y += 40
    assert FACES["sansr"].width(en, 17) <= 480, en
    d.text(en, 44, y + 4, 17, "sansr", sub)
    chips(d, items, 44, 340, accent, solid_last=True)


def card_master() -> str:
    d = Doc(1300, 380, "xiaoma-design-master：十六个创作工种，一条命令装进你的 Agent。")
    frames = [("dm-designer-1.jpg", "xiaoma-designer", "海报 · KV", .5), ("dm-director-1.jpg", "xiaoma-director", "分镜表 · 导演审核", .5),
              ("dm-gen-ui-1.jpg", "xiaoma-gen-ui", "落地页 · 三轮自检", .3), ("dm-opus3d.jpg", "xiaoma-opus3d", "纯代码 3D 场景", .5),
              ("dm-studio-1.jpg", "xiaoma-studio", "代码动效视频", .5), ("dm-ppt-1.jpg", "xiaoma-ppt", "套企业模板出 pptx", .5),
              ("dm-cover-a.jpg", "xiaoma-gen-cover", "文章封面", .5), ("dm-video-script.jpg", "xiaoma-video-script", "口播提词卡", 0.0)]
    n, period = len(frames), 24
    d.css.append(cycle_css("f", n, period, 0.5))
    d.css.append("@keyframes kb{from{transform:scale(1)}to{transform:scale(1.06)}}"
                 ".kb{transform-box:fill-box;transform-origin:center;animation:kb 3s ease-out infinite alternate}"
                 "@keyframes bar{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
                 f".bar{{transform-box:fill-box;transform-origin:left;animation:bar {period / n}s linear infinite}}")
    icon = ''.join(f'<rect x="{56 + (i % 2) * 18}" y="{96 + (i // 2) * 18}" width="14" height="14" rx="3" fill="{PAPER}" '
                   f'opacity="{1 if i != 3 else .45}"/>' for i in range(4))
    card_shell(d, "01", "CREATIVE SUITE", "xiaoma-design-master", ["十六个创作工种，", "一条命令装进你的 Agent。"],
               "Sixteen creative crafts. One command, one agent.",
               ["16 SKILLS", "WRITE", "IMAGE", "VIDEO", "3D", "WEB"], INK, PAPER, "#B9B2A4", SEAL, icon)
    d.add(f'<rect x="560" width="740" height="380" fill="{PAPER}"/>')
    d.add(f'<rect x="560" width="740" height="380" fill="url(#dots2)"/>')
    d.extra_defs.append(f'<pattern id="dots2" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="{RULE}"/></pattern>')
    fx, fy, fw, fh = 598, 34, 664, 270
    rounded_clip(d, "pc", fx, fy, fw, fh, 14)
    d.add(f'<rect x="{fx - 6}" y="{fy - 6}" width="{fw + 12}" height="{fh + 12}" rx="18" fill="#fff" stroke="{RULE}"/>')
    d.add('<g clip-path="url(#pc)">')
    for i, (f, *_rest, top) in enumerate(frames):
        d.add(f'<g class="f{i}"><image class="kb" href="{jpeg(RAW / f, fw, fh, 74, top)}" x="{fx}" y="{fy}" width="{fw}" height="{fh}" '
              f'preserveAspectRatio="xMidYMid slice"/></g>')
    d.add('</g>')
    for i, (_f, skill, desc, _t) in enumerate(frames):
        d.add(f'<g class="f{i}">')
        d.text(skill, 598, 340, 19, "sans", INK)
        d.text(desc, 598 + FACES["sans"].width(skill, 19) + 14, 340, 15, "sansr", MUTED)
        d.text(f"{i + 1:02d} / {n:02d}", 1262, 340, 13, "mono", MUTED, anchor="end", track=0.1)
        d.add('</g>')
    d.add(f'<rect x="598" y="356" width="664" height="3" rx="1.5" fill="{RULE}"/>')
    d.add(f'<rect class="bar" x="598" y="356" width="664" height="3" rx="1.5" fill="{SEAL}"/>')
    d.add('</g>')
    return d.render()


def card_durex() -> str:
    d = Doc(1300, 380, "xiaoma-durex-copywriter：话只说一半，另一半让读者自己笑出来。")
    accent, bg = "#B3245A", "#F6ECE8"
    d.css.append("@keyframes la{0%,42%{transform:translateY(0) scale(1.04);opacity:1}50%,92%{transform:translateY(6px) scale(.94);opacity:.42}100%{transform:scale(1.04);opacity:1}}"
                 ".pa{transform-box:fill-box;transform-origin:center;animation:la 9s cubic-bezier(.6,0,.2,1) infinite}"
                 ".pb{transform-box:fill-box;transform-origin:center;animation:la 9s cubic-bezier(.6,0,.2,1) infinite;animation-delay:-4.5s}"
                 "@keyframes lt{0%,44%{opacity:1}50%,94%{opacity:0}100%{opacity:1}}"
                 ".ta{animation:lt 9s steps(1) infinite}.tb{animation:lt 9s steps(1) infinite;animation-delay:-4.5s}")
    icon = (f'<text x="0" y="0"/><path d="M58 113h30M58 124h18" stroke="{bg}" stroke-width="5" stroke-linecap="round"/>'
            f'<circle cx="86" cy="124" r="3.4" fill="{bg}"/>')
    card_shell(d, "02", "COPYWRITING", "xiaoma-durex-copywriter", ["话只说一半，", "另一半让读者自己笑出来。"],
               "Say half. Let the reader laugh out the other half.",
               ["DOUBLE MEANING", "8 FORMULAS", "260 POSTERS"], bg, "#2A1620", "#7D5E68", accent, icon)
    d.add('<rect x="560" width="740" height="380" fill="#1B1418"/>')
    pw, ph = 222, 296
    for cls, f, x in (("pa", "lays_onechip_3x4.jpg", 690), ("pb", "lays_daynight_3x4.jpg", 952)):
        rounded_clip(d, f"c{cls}", x, 42, pw, ph, 10)
        d.add(f'<g class="{cls}"><g clip-path="url(#c{cls})"><image href="{jpeg(RAW / f, pw * 2, ph * 2, 70)}" x="{x}" y="42" '
              f'width="{pw}" height="{ph}"/></g></g>')
    for cls, a, b in (("ta", "「就吃一片。」", "表层是克制，里层是根本停不下来"),
                      ("tb", "「白天数卡路里，晚上数薯片。」", "表层是自律，里层是破功")):
        d.add(f'<g class="{cls}">')
        w = d.text(a, 690, 366, 16, "sans", "#F3E6EA")
        d.text(b, 690 + w + 12, 366, 14.5, "sansr", "#B79AA5")
        d.add('</g>')
    d.add('</g>')
    return d.render()


def card_studio() -> str:
    d = Doc(1300, 380, "xiaoma-studio：每一帧，都是时间的函数。")
    accent, bg = "#FF5A36", "#101114"
    films = [("swiss-reel", [2, 4, 5, 8], "瑞士风 reel"), ("museum-compound", [1, 2, 4, 7], "博物馆纪录片《复利的形状》"),
             ("editorial-weeks", [1, 3, 6, 7], "编辑部数据《人生只有 4000 周》"), ("blueprint-switch", [1, 4, 6, 8], "工程爆炸图 · 机械键盘轴"),
             ("paper-cloud", [1, 3, 6, 8], "纸艺绘本《小云》")]
    per, n_f = 0.55, 4
    period = per * n_f * len(films)
    d.css.append(cycle_css("s", len(films) * n_f, period, 0))
    d.css.append(cycle_css("t", len(films), period, 0))
    d.css.append(f"@keyframes ph{{from{{transform:translateX(0)}}to{{transform:translateX(500px)}}}}"
                 f".ph{{animation:ph {period / len(films)}s linear infinite}}"
                 "@keyframes rec{0%,100%{opacity:1}50%{opacity:.25}}.rec{animation:rec 1.2s ease-in-out infinite}")
    icon = f'<path d="M64 100l26 13-26 13z" fill="{bg}"/>'
    card_shell(d, "03", "MOTION", "xiaoma-studio", ["每一帧，", "都是时间的函数。"],
               "Every frame is a pure function of time. Code in, film out.",
               ["30 VIRAL FILMS", "15 STYLES", "HTML → MP4"], bg, "#F2EFEA", "#8E8A84", accent, icon)
    d.add('<rect x="560" width="740" height="380" fill="#08090B"/>')
    fx, fy, fw = 670, 20, 500
    fh = round(fw * 9 / 16)
    rounded_clip(d, "sc", fx, fy, fw, fh, 10)
    d.add('<g clip-path="url(#sc)">')
    k = 0
    for name, idx, _title in films:
        for j in idx:
            d.add(f'<image class="s{k}" href="{jpeg(RAW / f"st-{name}-{j}.jpg", fw, fh, 70)}" x="{fx}" y="{fy}" width="{fw}" height="{fh}"/>')
            k += 1
    d.add('</g>')
    d.add(f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="10" fill="none" stroke="#2A2C31"/>')
    d.add(f'<circle class="rec" cx="{fx + 22}" cy="{fy + 22}" r="5" fill="{accent}"/>')
    ty = fy + fh + 14
    d.add(f'<rect x="{fx}" y="{ty}" width="{fw}" height="3" rx="1.5" fill="#26282D"/>')
    d.add(f'<g class="ph"><rect x="{fx - 1}" y="{ty - 7}" width="2.5" height="17" rx="1.2" fill="{accent}"/></g>')
    for i, (_n, _idx, title) in enumerate(films):
        d.add(f'<g class="t{i}">')
        d.text(title, fx, ty + 30, 16, "sansr", "#C9C5BE")
        d.text(f"0{i + 1} / 0{len(films)}", fx + fw, ty + 30, 13.5, "mono", "#77736D", anchor="end", track=0.1)
        d.add('</g>')
    d.add('</g>')
    return d.render()


def card_mingzhi() -> str:
    d = Doc(1300, 380, "明知AI剪辑 mingzhi：说一遍就好，口误、背景、封面交给它。")
    accent, bg = "#1F8A5B", "#EDF3EE"
    frames = [("mzq-4.png", .5), ("mzq-6.png", .5), ("mzq-8.png", .5), ("mzq-10.png", .5),
              ("mz-shot-live.png", .5), ("mz-shot-compare.png", .5)]
    period = 18
    d.css.append(cycle_css("m", len(frames), period, 0.45))
    icon = (f'<path d="M58 124c6-14 12-14 18 0s12 14 18 0" fill="none" stroke="{bg}" stroke-width="5" stroke-linecap="round"/>'
            f'<path d="M73 98v8" stroke="{bg}" stroke-width="5" stroke-linecap="round"/>')
    card_shell(d, "04", "TALKING-HEAD EDIT", "mingzhi", ["说一遍就好，", "口误、背景、封面交给它。"],
               "Talk once. It trims the stumbles and dresses the cut.",
               ["LOCAL ASR", "OPEN SOURCE", "≈ ¥2 / VIDEO"], bg, "#13261C", "#5E7366", accent, icon)
    d.add('<rect x="560" width="740" height="380" fill="#0E1210"/>')
    fh = 316
    fw = round(fh * 1.42)
    fx, fy = 560 + (740 - fw) // 2, 22
    rounded_clip(d, "mc", fx, fy, fw, fh, 12)
    d.add('<g clip-path="url(#mc)">')
    for i, (f, top) in enumerate(frames):
        box = (0.125, 0.075, 0.875, 0.93) if f.startswith("mzq") else None
        d.add(f'<image class="m{i}" href="{jpeg(RAW / f, fw, fh, 72, top, box)}" x="{fx}" y="{fy}" width="{fw}" height="{fh}"/>')
    d.add('</g>')
    d.text("原片 0:15 → 成片 0:12  ·  剪掉 4 处口误、换了背景  ·  用时 6 分钟，花费 ¥1.98", fx, fy + fh + 28, 15, "sansr", "#AFC3B6")
    d.add('</g>')
    return d.render()


def main():
    OUT.mkdir(exist_ok=True)
    files = {"header.svg": header(), "footer.svg": footer(), "card-master.svg": card_master(),
             "card-durex.svg": card_durex(), "card-studio.svg": card_studio(), "card-mingzhi.svg": card_mingzhi()}
    for i in range(1, 5):
        files[f"divider-{i}.svg"] = divider(f"0{i}")
    files["divider-end.svg"] = divider("✓".replace("✓", "··"))
    for name, svg in files.items():
        (OUT / name).write_text(svg, encoding="utf-8")
        print(f"{name:20s} {len(svg.encode()) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
