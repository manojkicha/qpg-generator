#!/usr/bin/env python3
"""
question_paper_generator.py
---------------------------
Turn a question-paper JSON into a professionally formatted, print-ready A4 PDF
(question paper only: answer keys, sample answers and marking schemes are ignored).

Usage
    pip install reportlab
    python question_paper_generator.py input.json                 # -> <title>.pdf
    python question_paper_generator.py input.json -o paper.pdf
    python question_paper_generator.py input.json --assets ./images --max-marks 50

Accepted JSON shapes
    {"question_paper": {...}, "answer_key": {...}}     (wrapped)
    {...paper fields directly...}                      (flat)

Supported question types
    multiple_choice, true_false, fill_in_the_blank, match_the_following,
    picture_based_mcq, one_word_answer, short_answer, long_answer,
    problem_solving, case_study  (anything else falls back to a question + ruled lines)

    case_study questions carry a `case_passage` (the scenario) and a list of
    `sub_questions` ({question_text, question_type, options, marks}) that are
    printed as (i), (ii), ... under the passage.

Images
    `image_url` / `logo_url` can be a local path, an http(s) URL, or a data: URI.
    If a picture question has no loadable image, a built-in illustration is used
    (air / balloon / jar) or a dashed "Picture" placeholder box.
"""
import argparse, base64, io, json, os, random, re, sys, urllib.request
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.graphics.shapes import Circle, Drawing, Ellipse, Line, Path, PolyLine, Rect, String
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

# --------------------------------------------------------------------------- theme
NAVY = colors.HexColor("#14284B"); TEAL = colors.HexColor("#0E7C86"); TEAL_L = colors.HexColor("#E3F2F3")
LIGHT = colors.HexColor("#EEF3F8"); AMBER = colors.HexColor("#E0A526"); AMBER_L = colors.HexColor("#FFF7E3")
GREY = colors.HexColor("#6B7785"); LINE = colors.HexColor("#D5DCE4"); INK = colors.HexColor("#1B2430")
FB = "Helvetica-Bold"
W = 178 * mm            # usable page width
CONT_W = 134 * mm       # question content width (between number badge and marks tag)
FW, FH = 52 * mm, 42 * mm   # figure box

S = {
    "q": ParagraphStyle("q", fontName="Helvetica", fontSize=11.5, leading=17, textColor=INK),
    "opt": ParagraphStyle("opt", fontName="Helvetica", fontSize=11, leading=15, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=10.5, leading=14, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName=FB, fontSize=9, leading=12, textColor=colors.white),
    "instr": ParagraphStyle("instr", fontName="Helvetica-Oblique", fontSize=9.5, leading=12, textColor=GREY, spaceBefore=4, spaceAfter=8),
    "sec": ParagraphStyle("sec", fontName=FB, fontSize=10, leading=13, textColor=colors.white),
    "sect": ParagraphStyle("sect", fontName=FB, fontSize=11.5, leading=14, textColor=NAVY),
    "secr": ParagraphStyle("secr", fontName=FB, fontSize=9, leading=12, textColor=TEAL, alignment=TA_RIGHT),
    "ih": ParagraphStyle("ih", fontName=FB, fontSize=9, leading=12, textColor=colors.HexColor("#8A6410"), spaceAfter=3),
    "ib": ParagraphStyle("ib", fontName="Helvetica", fontSize=10, leading=14, textColor=colors.HexColor("#3B3217"), leftIndent=10),
    "ml": ParagraphStyle("ml", fontName="Helvetica", fontSize=7, leading=9, textColor=GREY),
    "mv": ParagraphStyle("mv", fontName=FB, fontSize=12, leading=15, textColor=NAVY),
    "end": ParagraphStyle("end", fontName=FB, fontSize=9, leading=12, textColor=GREY, alignment=TA_CENTER),
    "case": ParagraphStyle("case", fontName="Helvetica", fontSize=10.5, leading=15, textColor=INK),
    "caseh": ParagraphStyle("caseh", fontName=FB, fontSize=8.5, leading=11, textColor=TEAL),
    "subm": ParagraphStyle("subm", fontName=FB, fontSize=8.5, leading=12, textColor=TEAL, alignment=TA_RIGHT),
}

DEFAULT_INSTR = {
    "multiple_choice": "Read each question and circle the correct answer.",
    "true_false": "Read each statement and circle True or False.",
    "fill_in_the_blank": "Fill in the blanks with the correct word.",
    "match_the_following": "Match the items in Column A with Column B. Write the correct letters.",
    "picture_based_mcq": "Look at each picture and circle the correct answer.",
    "one_word_answer": "Answer in one word.",
    "short_answer": "Write the answer in 2-3 sentences.",
    "long_answer": "Write the answer in detail.",
    "problem_solving": "Solve the problem showing all steps.",
    "case_study": "Read the case carefully and answer the questions that follow.",
}

# --------------------------------------------------------------------------- text helpers
def fmt(t):
    """XML-escape for Paragraph and turn x^2 into a real superscript."""
    t = str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\^(\w+)", r"<super>\1</super>", t)

def blanks(t):
    return re.sub(r"_{2,}", "_" * 14, t)

def tidy_math(t):
    """'a x^2 + b x + c' -> 'ax^2 + bx + c' (only on equations)."""
    return re.sub(r"\b([abc]) ([xX])", r"\1\2", t) if "=" in t else t

# generator leftovers that should never be printed on a paper
_STRIP = [r"\s*Remember, items are shuffled for variety\.", r"\s*Ensure (?:that )?the items are properly paired[^.]*\."]
def clean(t):
    for s in _STRIP:
        t = re.sub(s, "", t)
    return t.strip()

# --------------------------------------------------------------------------- image loading
def load_image(src, assets_dir=None):
    """Return an ImageReader for a path / URL / data-URI, or None."""
    if not src or not isinstance(src, str):
        return None
    try:
        if src.startswith("data:"):
            return ImageReader(io.BytesIO(base64.b64decode(src.split(",", 1)[1])))
        if re.match(r"https?://", src):
            with urllib.request.urlopen(src, timeout=8) as r:
                return ImageReader(io.BytesIO(r.read()))
        for base in filter(None, [None, assets_dir]):
            p = os.path.join(base, src) if base else src
            if os.path.isfile(p):
                return ImageReader(p)
    except Exception:
        pass
    return None

class FitImage(Flowable):
    def __init__(self, reader, w, h):
        super().__init__(); self.r = reader
        iw, ih = reader.getSize(); s = min(w / iw, h / ih)
        self.w, self.h = iw * s, ih * s
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self): self.canv.drawImage(self.r, 0, 0, self.w, self.h, mask="auto")

# --------------------------------------------------------------------------- built-in illustrations
GLASS = colors.HexColor("#DDEFF7"); GLASS_E = colors.HexColor("#5B8FA8")

def _cap(d, txt="Look at the picture"):
    d.add(String(FW / 2, 1 * mm, txt, textAnchor="middle", fontName="Helvetica-Oblique", fontSize=6.8, fillColor=GREY))

def _dust(d, x0, y0, x1, y1, n, seed, r=0.75 * mm):
    rnd = random.Random(seed)
    for _ in range(n):
        d.add(Circle(rnd.uniform(x0, x1), rnd.uniform(y0, y1), r * rnd.uniform(.7, 1.3),
                     fillColor=colors.HexColor("#8A7B6A"), strokeColor=None))

def _arrows(d, cx, cy):
    c = colors.HexColor("#9DB9C8")
    for dx, dy in [(-9, 5), (9, 7), (-5, -6), (8, -4)]:
        x, y = cx + dx * mm, cy + dy * mm
        d.add(Line(x - 2 * mm, y, x + 2 * mm, y, strokeColor=c, strokeWidth=.8))
        d.add(PolyLine([x + 1 * mm, y + .8 * mm, x + 2 * mm, y, x + 1 * mm, y - .8 * mm], strokeColor=c, strokeWidth=.8, fillColor=None))

def fig_container():
    d = Drawing(FW, FH); x0, y0, w, h = 11 * mm, 5 * mm, 30 * mm, 28 * mm
    d.add(Rect(x0, y0, w, h, rx=3 * mm, ry=3 * mm, fillColor=GLASS, strokeColor=GLASS_E, strokeWidth=1.4))
    d.add(Rect(x0 - 1.5 * mm, y0 + h - 1 * mm, w + 3 * mm, 3.5 * mm, rx=1 * mm, ry=1 * mm, fillColor=colors.HexColor("#B8C6D1"), strokeColor=GLASS_E, strokeWidth=1))
    _arrows(d, x0 + w / 2, y0 + h / 2); _dust(d, x0 + 3 * mm, y0 + 3 * mm, x0 + w - 3 * mm, y0 + h - 4 * mm, 16, 3)
    d.add(String(x0 + w / 2, y0 + h + 4.5 * mm, "container full of air", textAnchor="middle", fontName="Helvetica-Oblique", fontSize=7, fillColor=GREY))
    _cap(d); return d

def fig_balloon():
    d = Drawing(FW, FH); cx, cy = FW / 2, 26 * mm; rose = colors.HexColor("#C25B70")
    d.add(Ellipse(cx, cy, 11 * mm, 13 * mm, fillColor=colors.HexColor("#F7C6CF"), strokeColor=rose, strokeWidth=1.4))
    d.add(Ellipse(cx - 4.2 * mm, cy + 5 * mm, 1.8 * mm, 3 * mm, fillColor=colors.white, strokeColor=None))
    p = Path(fillColor=rose, strokeColor=rose)
    p.moveTo(cx, cy - 12.8 * mm); p.lineTo(cx - 1.6 * mm, cy - 15.6 * mm); p.lineTo(cx + 1.6 * mm, cy - 15.6 * mm); p.closePath(); d.add(p)
    d.add(PolyLine([cx, cy - 15.6 * mm, cx + 2 * mm, cy - 18 * mm, cx - 2 * mm, cy - 20 * mm], strokeColor=GREY, strokeWidth=.9, fillColor=None))
    _arrows(d, cx, cy); _dust(d, cx - 7.5 * mm, cy - 9 * mm, cx + 7.5 * mm, cy + 9 * mm, 13, 5)
    _cap(d); return d

def fig_jar():
    d = Drawing(FW, FH); x0, y0, w, h = 12 * mm, 4 * mm, 28 * mm, 27 * mm
    d.add(Rect(x0, y0, w, h, rx=3.5 * mm, ry=3.5 * mm, fillColor=GLASS, strokeColor=GLASS_E, strokeWidth=1.4))
    d.add(Rect(x0 + 2 * mm, y0 + h - 1 * mm, w - 4 * mm, 4 * mm, rx=1 * mm, ry=1 * mm, fillColor=colors.HexColor("#C9A66B"), strokeColor=colors.HexColor("#8A6A33"), strokeWidth=1))
    for sx, sy in [(8, 5), (15, 4), (22, 5.5), (11, 9.5), (19, 9), (25, 10), (8, 14), (15, 14.5), (22, 15), (12, 19), (19, 19.5)]:
        d.add(Ellipse(x0 + sx * mm, y0 + sy * mm, 1.7 * mm, 1.1 * mm, fillColor=colors.HexColor("#8B5E34"), strokeColor=colors.HexColor("#5C3A1B"), strokeWidth=.5))
    _arrows(d, x0 + w / 2, y0 + 22 * mm)
    d.add(String(x0 + w / 2, y0 + h + 6.5 * mm, "jar with seeds", textAnchor="middle", fontName="Helvetica-Oblique", fontSize=7, fillColor=GREY))
    _cap(d); return d

def fig_placeholder():
    d = Drawing(FW, FH)
    d.add(Rect(2 * mm, 4 * mm, FW - 4 * mm, FH - 8 * mm, rx=2 * mm, ry=2 * mm, fillColor=LIGHT, strokeColor=GREY, strokeWidth=.8, strokeDashArray=[3, 2]))
    d.add(String(FW / 2, FH / 2 - 1 * mm, "Picture", textAnchor="middle", fontName="Helvetica-Oblique", fontSize=10, fillColor=GREY))
    return d

def get_figure(q, assets_dir):
    """Real image if loadable; else a built-in illustration for picture questions; else None."""
    rdr = load_image(q.get("image_url"), assets_dir)
    if rdr: return FitImage(rdr, FW, FH)
    if q.get("question_type") != "picture_based_mcq": return None
    t = (q["question_text"] + " " + str(q.get("image_url") or "")).lower()
    if "balloon" in t: return fig_balloon()
    if "jar" in t or "seed" in t: return fig_jar()
    if "air" in t or "container" in t: return fig_container()
    return fig_placeholder()

# --------------------------------------------------------------------------- reusable flowables
def qnum(n):
    d = Drawing(9 * mm, 9 * mm)
    d.add(Circle(4.5 * mm, 4.5 * mm, 4.4 * mm, fillColor=NAVY, strokeColor=NAVY))
    d.add(String(4.5 * mm, 2.6 * mm, str(n), textAnchor="middle", fontName=FB, fontSize=9.5 if n < 100 else 8, fillColor=colors.white))
    return d

def pill(m):
    txt = f"{m:g} Mark" + ("" if m == 1 else "s")
    d = Drawing(21 * mm, 7 * mm); d.hAlign = "RIGHT"
    d.add(Rect(0, 0.5 * mm, 21 * mm, 6 * mm, rx=3 * mm, ry=3 * mm, fillColor=TEAL_L, strokeColor=TEAL, strokeWidth=.7))
    d.add(String(10.5 * mm, 2.4 * mm, txt, textAnchor="middle", fontName=FB, fontSize=8, fillColor=TEAL))
    return d

# --------------------------------------------------------------------------- option helpers
def opt_text(o):
    if isinstance(o, dict): return str(next(iter(o.values())))
    return re.sub(r"^\(?\w\)\s*", "", str(o)) if re.match(r"^\(\w\)", str(o)) else str(o)

def pair(o):
    ks = list(o.keys()); return str(o[ks[0]]), str(o[ks[1]])

def derange(n, seed):
    """Shuffle with no item left in its original place (so answers don't line up)."""
    if n < 2: return list(range(n))
    rnd = random.Random(seed)
    while True:
        p = list(range(n)); rnd.shuffle(p)
        if all(p[i] != i for i in range(n)): return p

def options_grid(opts, width=CONT_W):
    cells = [Paragraph(f"<font color='#0E7C86'><b>({'ABCDEFGH'[i]})</b></font>&nbsp;&nbsp;{fmt(tidy_math(opt_text(o)))}", S["opt"])
             for i, o in enumerate(opts)]
    if len(cells) % 2: cells.append("")
    t = Table([cells[i:i + 2] for i in range(0, len(cells), 2)], colWidths=[width / 2] * 2)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t

def match_block(opts, seed, width=CONT_W):
    pairs = [pair(o) for o in opts]; perm = derange(len(pairs), seed)
    rows = [[Paragraph("COLUMN A", S["cellh"]), Paragraph("COLUMN B", S["cellh"])]]
    for i, (l, _) in enumerate(pairs):
        rows.append([Paragraph(f"<b>{i + 1}.</b>&nbsp;&nbsp;{fmt(l)}", S["cell"]),
                     Paragraph(f"<font color='#0E7C86'><b>{'ABCDEFGH'[i]}.</b></font>&nbsp;&nbsp;{fmt(pairs[perm[i]][1])}", S["cell"])])
    t = Table(rows, colWidths=[38 * mm, width - 38 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                           ("BOX", (0, 0), (-1, -1), .7, LINE), ("INNERGRID", (0, 0), (-1, -1), .5, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return [t]

# --------------------------------------------------------------------------- question + section blocks
def answer_area(qt, opts, seed, width=CONT_W):
    """Options that follow a question stem. No writing space: answers go on a separate sheet."""
    if qt == "match_the_following" and opts:
        return [Spacer(1, 3 * mm)] + match_block(opts, seed, width)
    if qt == "true_false" and not opts:
        return [Spacer(1, 3 * mm), options_grid(["True", "False"], width)]
    if opts:
        return [Spacer(1, 3 * mm), options_grid(opts, width)]
    return []

def case_study_block(num, q):
    """Case scenario box followed by its sub-questions (i), (ii), ...

    Returned as a list of flowables (not one table row) so a long case can break across pages.
    """
    marks = q.get("marks", 1); indent_w = W - 12 * mm
    intro = clean(q.get("question_text") or "") or DEFAULT_INSTR["case_study"]
    head = Table([[qnum(num), Paragraph(fmt(intro), S["q"]), pill(marks)]], colWidths=[12 * mm, 138 * mm, 28 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (1, 0), (1, 0), 4 * mm),
                              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))

    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", str(q.get("case_passage") or "")) if p.strip()]
    rows = [[Paragraph("CASE STUDY", S["caseh"])]] + [[Paragraph(fmt(p), S["case"])] for p in paras]
    case = Table(rows, colWidths=[indent_w], hAlign="RIGHT")
    case.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL_L), ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                              ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                              ("TOPPADDING", (0, 0), (0, 0), 7), ("BOTTOMPADDING", (0, -1), (0, -1), 8)]))
    out = [head, case, Spacer(1, 2 * mm)]

    subs = [s for s in (q.get("sub_questions") or []) if isinstance(s, dict) and s.get("question_text")]
    body_w = indent_w - 10 * mm - 22 * mm
    for i, sq in enumerate(subs):
        sqt = sq.get("question_type", "short_answer")
        body = [Paragraph(blanks(fmt(tidy_math(clean(sq["question_text"])))), S["q"])]
        body += answer_area(sqt, sq.get("options") or [], num * 100 + i, body_w)
        sm = sq.get("marks")
        mtxt = f"[{sm:g} Mark{'' if sm == 1 else 's'}]" if isinstance(sm, (int, float)) else ""
        t = Table([[Paragraph(f"<b>({ROMAN[i] if i < len(ROMAN) else i + 1})</b>", S["q"]), body, Paragraph(mtxt, S["subm"])]],
                  colWidths=[10 * mm, body_w, 22 * mm], hAlign="RIGHT")
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (1, 0), (1, 0), 3 * mm),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        out.append(t)
    rule = Table([[""]], colWidths=[W], rowHeights=[3 * mm])
    rule.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]))
    # keep the case together with its first sub-question so it never sits alone at a page bottom
    return [KeepTogether(out[:4])] + out[4:] + [rule]

ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]

def question_block(num, q, assets_dir):
    """One question as a list of flowables."""
    qt = q.get("question_type", "")
    if qt == "case_study":
        return case_study_block(num, q)
    text = clean(q["question_text"])
    fig = get_figure(q, assets_dir)
    if qt == "picture_based_mcq":
        sents = re.findall(r"[^.?!]*\?", text)
        if sents: text = sents[-1].strip()          # the text is often "picture description. Actual question?"
        else: text = "Look at the picture. What does it show about air?" if "air" in text.lower() else "Look at the picture and choose the correct answer."
    body = Paragraph(blanks(fmt(tidy_math(text))), S["q"])

    content = []
    if fig is not None:
        fw = fig.wrap(0, 0)[0] if isinstance(fig, FitImage) else FW
        t = Table([[body, fig]], colWidths=[CONT_W - max(fw, FW), max(fw, FW)])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (0, 0), 6), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        content.append(t)
    else:
        content.append(body)

    content += answer_area(qt, q.get("options") or [], num)

    marks = q.get("marks", 1)
    t = Table([[qnum(num), content, pill(marks)]], colWidths=[12 * mm, 138 * mm, 28 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (1, 0), (1, 0), 4 * mm),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]))
    return [t]

MCQ_TYPES = {"multiple_choice", "picture_based_mcq"}

def merge_if_mcq_only(sections):
    """MCQ-only paper: fold the (chapter-wise) sections into one "Multiple Choice Questions" section.

    Question order is unchanged, so numbering still matches the answer key. Returns (sections, merged).
    """
    qs = [q for sec in sections for q in sec["questions"]]
    if not qs or any(q.get("question_type") not in MCQ_TYPES for q in qs):
        return sections, False
    instrs = {(sec.get("instructions") or "").strip() for sec in sections} - {""}
    instr = instrs.pop() if len(instrs) == 1 else DEFAULT_INSTR["multiple_choice"]
    return [{"section_title": "Multiple Choice Questions", "instructions": instr, "questions": qs}], True

TYPE_LABELS = {
    "multiple_choice": "Multiple Choice", "true_false": "True / False",
    "fill_in_the_blank": "Fill in the Blanks", "fill_in_the_blanks": "Fill in the Blanks",
    "match_the_following": "Match the Following",
    "picture_based_mcq": "Picture Based Questions", "picture_based": "Picture Based Questions",
    "one_word_answer": "One Word Answer", "very_short_answer": "Very Short Answer",
    "short_answer": "Short Answer", "long_answer": "Long Answer", "problem_solving": "Problem Solving",
    "case_study": "Case Study", "case_based": "Case Study",
}

def type_titled(sections):
    """Banner titles show the question type only (e.g. "Multiple Choice"), never chapter names."""
    out = []
    for sec in sections:
        qt = (sec["questions"][0].get("question_type") or "") if sec["questions"] else ""
        title = TYPE_LABELS.get(qt) or qt.replace("_", " ").title() or "Questions"
        out.append({**sec, "section_title": title})
    return out

def section_banner(idx, sec, label=True):
    qs = sec["questions"]; n = len(qs); m = qs[0].get("marks", 1)
    instr = sec.get("instructions") or ""
    mt = re.search(r"any\s+(\d+)\s+(?:out\s+of|of)\s+(\d+)", instr, re.I)
    if mt:
        k = int(mt.group(1)); right = f"Attempt any {k} of {n}  |  {k * m:g} Marks"
    else:
        right = f"{n} Question{'s' if n != 1 else ''}  |  {sum(q.get('marks', 1) for q in qs):g} Marks"
    if not instr: instr = DEFAULT_INSTR.get(qs[0].get("question_type"), "")
    if not label:                                     # single unlabelled banner (MCQ-only paper)
        t = Table([[Paragraph(fmt(sec.get("section_title", "")), S["sect"]), Paragraph(right, S["secr"])]],
                  colWidths=[118 * mm, 60 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBEFORE", (0, 0), (0, 0), 4, NAVY),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), 1.6, TEAL)]))
        return t, instr
    t = Table([[Paragraph(f"SECTION {chr(65 + idx)}", S["sec"]), Paragraph(fmt(sec.get("section_title", "")), S["sect"]),
                Paragraph(right, S["secr"])]], colWidths=[28 * mm, 90 * mm, 60 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), NAVY), ("BACKGROUND", (1, 0), (-1, 0), LIGHT),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), 1.6, TEAL)]))
    return t, instr

# --------------------------------------------------------------------------- header / front matter
def draw_logo(c, cx, cy, r, reader=None):
    c.saveState()
    if reader and reader.getSize()[0] > 1.6 * reader.getSize()[1]:   # wide wordmark: rounded white badge
        iw, ih = reader.getSize(); bw, bh = 2 * r + 2 * mm, r * 0.95
        c.setFillColor(colors.white); c.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 2 * mm, stroke=0, fill=1)
        s = min((bw - 3 * mm) / iw, (bh - 3 * mm) / ih)
        c.drawImage(reader, cx - iw * s / 2, cy - ih * s / 2, iw * s, ih * s, mask="auto")
        c.restoreState(); return
    c.setFillColor(colors.white); c.circle(cx, cy, r, stroke=0, fill=1)
    if reader:                                        # real logo, fitted inside the ring
        iw, ih = reader.getSize(); box = r * 1.45; s = min(box / iw, box / ih)
        c.drawImage(reader, cx - iw * s / 2, cy - ih * s / 2, iw * s, ih * s, mask="auto")
    else:                                             # built-in sprout mark
        c.setStrokeColor(NAVY); c.setLineWidth(1.6); c.line(cx, cy - r * .5, cx, cy + r * .05)
        for sgn in (-1, 1):
            p = c.beginPath(); p.moveTo(cx, cy + r * .05)
            p.curveTo(cx + sgn * r * .1, cy + r * .6, cx + sgn * r * .55, cy + r * .6, cx + sgn * r * .6, cy + r * .3)
            p.curveTo(cx + sgn * r * .5, cy + r * .02, cx + sgn * r * .2, cy - r * .02, cx, cy + r * .05)
            c.setFillColor(TEAL); c.setStrokeColor(NAVY); c.setLineWidth(1); c.drawPath(p, stroke=1, fill=1)
    c.setStrokeColor(AMBER); c.setLineWidth(1.6); c.circle(cx, cy, r - 1.2 * mm, stroke=1, fill=0)
    c.restoreState()

class HeaderBlock(Flowable):
    """Front-page header (question paper and answer key): logo, school name, exam title, title, exam level."""
    PW = 32 * mm                                      # exam-level badge width
    def __init__(self, school, exam_title, title, level, logo, one_line_title=False):
        super().__init__(); self.level, self.logo = level, logo
        maxw = W - 41 * mm - (self.PW + 10 * mm if level else 6 * mm)
        texts = [t for t in (school, exam_title, title) if t]
        texts = [t for i, t in enumerate(texts) if t.lower() not in (x.lower() for x in texts[:i])] or ["Question Paper"]
        # first line is the headline; the rest are sub-lines  (text, font, size, colour, leading)
        styles = [(FB, 16, colors.white, 6.8 * mm), (FB, 12, colors.HexColor("#DCE4F0"), 5.4 * mm),
                  ("Helvetica", 11, colors.HexColor("#B9C7DD"), 5 * mm)]
        self.lines = []
        for i, (t, (f, s, col, lead)) in enumerate(zip(texts, styles)):
            # school name always on one line; title too when one_line_title (answer key)
            if (i == 0 and t == school) or (one_line_title and t == title):
                min_s = max(s - 4, 9)                 # never smaller than 9pt; "…" beyond that
                while stringWidth(t, f, s) > maxw and s > min_s:
                    s -= 0.5; lead = s * 0.42 * mm
                while len(t) > 4 and stringWidth(t, f, s) > maxw: t = t[:-2].rstrip() + "…"
                self.lines.append((t, f, s, col, lead)); continue
            self.lines += [(ln, f, s, col, lead) for ln in simpleSplit(t, f, s, maxw)[:2]]
        self.h = max(38 * mm, sum(l[4] for l in self.lines) + 16 * mm)
    def wrap(self, aw, ah): return W, self.h
    def draw(self):
        c, h, lines = self.canv, self.h, self.lines
        c.setFillColor(NAVY); c.roundRect(0, 0, W, h, 4 * mm, stroke=0, fill=1)
        c.setFillColor(TEAL); c.roundRect(0, 0, W, 3 * mm, 1.5 * mm, stroke=0, fill=1)
        c.setFillColor(AMBER); c.rect(0, 3 * mm, 26 * mm, 0.8 * mm, stroke=0, fill=1)
        draw_logo(c, 22 * mm, h / 2 + 1.5 * mm, 12.5 * mm, self.logo)
        pw = self.PW
        block_h = sum(l[4] for l in lines)
        y = h / 2 + 1.5 * mm + block_h / 2 - lines[0][4] + 1.5 * mm   # vertically centred on the logo
        for txt, font, size, col, lead in lines:
            c.setFillColor(col); c.setFont(font, size); c.drawString(41 * mm, y, txt); y -= lead
        if self.level:
            txt = self.level.upper()
            while len(txt) > 4 and stringWidth(txt, FB, 8.5) > pw - 4 * mm: txt = txt[:-2].rstrip() + "…"
            px = W - pw - 6 * mm; py = h / 2 - 1.75 * mm
            c.setFillColor(AMBER); c.roundRect(px, py, pw, 6.5 * mm, 3.2 * mm, stroke=0, fill=1)
            c.setFillColor(NAVY); c.setFont(FB, 8.5); c.drawCentredString(px + pw / 2, py + 2.1 * mm, txt)

def header_fields(P):
    """(school name, exam title, title, exam level) for the front-page header of a paper / answer-key JSON."""
    school = str(P.get("school_name") or "").strip()
    exam_title = str(P.get("exam_title") or "").strip()
    level = str(P.get("exam_level") or P.get("grade_level") or "").strip()
    title = str(P.get("title") or "").strip()
    if level and title.lower().startswith(level.lower()):
        title = re.sub(r"^\W*", "", title[len(level):]) or title     # level is shown as a badge already
    return school, exam_title, title, level

def meta_strip(max_marks, nq, nsec=None):
    cells = [("MAXIMUM MARKS", str(max_marks)), ("QUESTIONS", str(nq))]
    if nsec is not None: cells.append(("SECTIONS", str(nsec)))
    t = Table([[[Paragraph(l, S["ml"]), Paragraph(v, S["mv"])] for l, v in cells]], colWidths=[W / len(cells)] * len(cells))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    return t

def candidate_row():
    lab = ParagraphStyle("lab", fontName=FB, fontSize=9.5, textColor=NAVY)
    t = Table([[Paragraph("Name:", lab), "", Paragraph("Roll No.:", lab), "", Paragraph("Date:", lab), ""]],
              colWidths=[14 * mm, 62 * mm, 18 * mm, 30 * mm, 12 * mm, 42 * mm], rowHeights=[10 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, 0), 0.6, GREY), ("LINEBELOW", (3, 0), (3, 0), 0.6, GREY),
                           ("LINEBELOW", (5, 0), (5, 0), 0.6, GREY), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t

def instructions_box(items_):
    items = [Paragraph("GENERAL INSTRUCTIONS", S["ih"])] + [Paragraph(fmt(s), S["ib"], bulletText=f"{i}.") for i, s in enumerate(items_, 1)]
    t = Table([[items]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBER_L), ("LINEBEFORE", (0, 0), (0, 0), 3, AMBER),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t

def make_canvas(title, grade, max_marks):
    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._saved = []
        def showPage(self):
            self._saved.append(dict(self.__dict__)); self._startPage()
        def save(self):
            n = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st); self._decorate(n); super().showPage()
            super().save()
        def _decorate(self, n):
            pw, ph = A4; pg = self._pageNumber; self.saveState()
            if pg > 1:
                self.setFont(FB, 8.5); self.setFillColor(NAVY); self.drawString(16 * mm, ph - 12 * mm, title)
                self.setFont("Helvetica", 8.5); self.setFillColor(GREY)
                self.drawRightString(pw - 16 * mm, ph - 12 * mm, f"{grade}  |  Max Marks: {max_marks}")
                self.setStrokeColor(TEAL); self.setLineWidth(1); self.line(16 * mm, ph - 14.5 * mm, pw - 16 * mm, ph - 14.5 * mm)
            self.setStrokeColor(LINE); self.setLineWidth(.6); self.line(16 * mm, 15 * mm, pw - 16 * mm, 15 * mm)
            self.setFont("Helvetica", 8); self.setFillColor(GREY)
            foot = title
            while len(foot) > 4 and stringWidth(foot, "Helvetica", 8) > 85 * mm: foot = foot[:-2].rstrip() + "…"
            self.drawString(16 * mm, 10.5 * mm, foot)
            self.drawRightString(pw - 16 * mm, 10.5 * mm, f"Page {pg} of {n}")
            self.restoreState()
    return NumberedCanvas

# --------------------------------------------------------------------------- main build
def load_paper(path):
    raw = json.load(open(path, encoding="utf-8"))
    return raw.get("question_paper", raw)       # answer_key / validation_summary are ignored

def ensure_sections(P):
    """Use the JSON sections; if absent, group the flat question list by question type."""
    if P.get("sections"): return P["sections"]
    secs, order = {}, []
    for q in P["questions"]:
        k = q.get("question_type", "questions")
        if k not in secs: secs[k] = {"section_title": k.replace("_", " ").title(), "instructions": "", "questions": []}; order.append(k)
        secs[k]["questions"].append(q)
    return [secs[k] for k in order]

def build(json_path, out_path=None, assets_dir=None, max_marks=None):
    P = load_paper(json_path)
    school, exam_title, title, level = header_fields(P)
    running = exam_title or title or "Question Paper"          # page header / footer text
    sections, mcq_only = merge_if_mcq_only(ensure_sections(P))
    if not mcq_only: sections = type_titled(sections)
    questions = P.get("questions") or [q for s in sections for q in s["questions"]]
    max_marks = max_marks if max_marks is not None else P.get("total_marks", sum(q.get("marks", 0) for q in questions))
    nq = P.get("total_questions") or len(questions)
    logo = load_image(P.get("logo_url"), assets_dir)
    out_path = out_path or re.sub(r"[^\w\-]+", "_", P.get("title", "question_paper")).strip("_") + ".pdf"

    doc = BaseDocTemplate(out_path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm,
                          bottomMargin=20 * mm, title=P.get("title", title), author="Question Paper Generator")
    fw, fh = A4[0] - 32 * mm, A4[1]
    frame = lambda top: Frame(16 * mm, 20 * mm, fw, fh - top - 20 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=[frame(12 * mm)]), PageTemplate(id="later", frames=[frame(22 * mm)])])

    story = [NextPageTemplate("later"), HeaderBlock(school, exam_title, title, level, logo), Spacer(1, 5 * mm),
             meta_strip(max_marks, nq, None if mcq_only else len(sections)), Spacer(1, 3 * mm), candidate_row(), Spacer(1, 4 * mm)]
    if P.get("general_instructions"):
        story += [instructions_box(P["general_instructions"]), Spacer(1, 6 * mm)]
    n = 0
    for si, sec in enumerate(sections):
        first = True
        for q in sec["questions"]:
            n += 1
            blocks = question_block(n, q, assets_dir)
            if first:
                banner, instr = section_banner(si, sec, label=not mcq_only)
                story.append(KeepTogether([banner, Paragraph(fmt(instr), S["instr"]), blocks[0]])); first = False
                story += blocks[1:]
            else:
                story += blocks
        story.append(Spacer(1, 5 * mm))
    story += [Spacer(1, 4 * mm), Paragraph("-  End of Question Paper  -", S["end"])]
    doc.build(story, canvasmaker=make_canvas(running, level, max_marks))
    return out_path, n

def main():
    ap = argparse.ArgumentParser(description="Generate a formatted question-paper PDF from JSON.")
    ap.add_argument("json", help="input JSON file")
    ap.add_argument("-o", "--output", help="output PDF path (default: derived from title)")
    ap.add_argument("--assets", help="folder to resolve relative image_url / logo_url paths")
    ap.add_argument("--max-marks", type=int, help="override maximum marks")
    a = ap.parse_args()
    out, n = build(a.json, a.output, a.assets, a.max_marks)
    print(f"Created {out} ({n} questions)")

if __name__ == "__main__":
    sys.exit(main())