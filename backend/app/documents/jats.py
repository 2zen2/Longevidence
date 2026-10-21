"""JATS XML (PubMed Central / Europe PMC open-access full text) -> sections, paragraphs, tables, captions.

Why JATS before PDF: for open-access papers the publisher XML already has the structure a PDF parser has to guess
(headings, paragraphs, table cells, caption text), and no layout errors such as hyphenation or column interleaving.
The cost is that JATS has no PDF page numbers; passages carry page_number=NULL and the document keeps the printed page range.
"""
from lxml import etree

from .model import ParsedDocument, ParsedPassage, assemble, canonical_section, clean

PARSER = "jats-2"
SKIP_TAGS = {"ref-list", "supplementary-material", "ack-skip"}
BACK_FUNDING_NOTES = ("coi", "conflict", "competing", "funding", "disclos", "financial")


BLOCKS = ("p", "title", "break", "label", "caption", "list-item", "sec", "td", "th", "tr", "table-wrap-foot")


def _spaced(el: etree._Element) -> etree._Element:
    """Copy of el where block-level boundaries become spaces ('diagram.' + <p> must not fuse), institution ids are removed."""
    el = etree.fromstring(etree.tostring(el, with_tail=False))
    for x in list(el.iter("institution-id")):
        _drop(x)
    for x in el.iter(*BLOCKS):
        x.tail = " " + (x.tail or "")
    for x in el.iter("break"):
        x.tail = " " + (x.tail or "")
    return el


def _text(el: etree._Element) -> str:
    """Element text with bibliography callouts (the superscript '12' after a sentence) removed and whitespace collapsed."""
    el = _spaced(el)
    for x in list(el.iter("xref")):
        if x.get("ref-type") == "bibr":
            _drop(x)
    for x in list(el.iter("table-wrap", "fig")):     # floats nested in a paragraph are emitted as their own passages
        if x is not el:
            _drop(x)
    return clean("".join(el.itertext()))


def _drop(el: etree._Element) -> None:
    """Remove an element but keep the text that follows it."""
    parent, tail = el.getparent(), el.tail
    if parent is None:
        return
    prev = el.getprevious()
    if tail:
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(el)


def _title(sec: etree._Element) -> str:
    t = sec.find("title")
    return clean("".join(t.itertext())) if t is not None else ""


def _table(tw: etree._Element) -> tuple[str, dict] | None:
    label = clean(tw.findtext("label") or "")
    cap_el = tw.find("caption")
    caption = clean("".join(_spaced(cap_el).itertext())) if cap_el is not None else ""
    head, rows = [], []
    table = tw.find(".//table")
    if table is None:
        return None
    for tr in table.iter("tr"):
        cells = [clean("".join(_spaced(c).itertext())) for c in tr if c.tag in ("td", "th")]
        if not any(cells):
            continue
        in_head = tr.getparent().tag == "thead"
        (head if in_head else rows).append(cells)
    foot = tw.find(".//table-wrap-foot")
    foot_text = clean("".join(_spaced(foot).itertext())) if foot is not None else ""
    lines = [f"{label}. {caption}" if (label and caption) else (label or caption or "Table")]
    for r in head + rows:
        lines.append(" | ".join(r))
    if foot_text:
        lines.append(foot_text)
    return "\n".join(lines), {"label": label, "caption": caption, "header": head, "rows": rows, "footnote": foot_text}


def _walk_sec(sec, path: list[str], inherited: str, out: list[ParsedPassage]) -> None:
    title = _title(sec)
    section = canonical_section(title, sec.get("sec-type"), inherited)
    here = path + ([title] if title else [])
    shown = " > ".join(here) or None
    for ch in sec:
        if ch.tag == "sec":
            _walk_sec(ch, here, section, out)
        elif ch.tag == "p":
            _emit_p(ch, section, shown, out)
        elif ch.tag in ("table-wrap", "fig"):
            _emit_float(ch, section, shown, out)
        elif ch.tag in ("list", "boxed-text", "statement"):
            _emit_p(ch, section, shown, out)


def _emit_p(p, section, shown, out) -> None:
    for fl in p.iter("table-wrap", "fig"):           # floats nested inside a paragraph
        _emit_float(fl, section, shown, out)
    t = _text(p)
    if len(t) >= 20:
        out.append(ParsedPassage(text=t, section=section, kind="paragraph", section_title=shown))


def _emit_float(el, section, shown, out) -> None:
    label = clean(el.findtext("label") or "")
    if el.tag == "table-wrap":
        tb = _table(el)
        if tb:
            out.append(ParsedPassage(text=tb[0], section=section, kind="table", section_title=shown, label=label or None, table_json=tb[1]))
    else:
        cap = el.find("caption")
        t = clean("".join(_spaced(cap).itertext())) if cap is not None else ""
        if t:
            out.append(ParsedPassage(text=f"{label}. {t}" if label else t, section=section, kind="figure_caption",
                                     section_title=shown, label=label or None))


def parse_jats(xml: bytes) -> ParsedDocument:
    root = etree.fromstring(xml)
    passages: list[ParsedPassage] = []

    # funding statements live in front matter
    for fg in root.iterfind(".//article-meta/funding-group"):
        t = _text(fg)
        if t:
            passages.append(ParsedPassage(text=t, section="funding_coi", kind="note", section_title="Funding"))
    body = root.find("body")
    if body is not None:
        for ch in body:
            if ch.tag == "sec":
                _walk_sec(ch, [], "other", passages)
            elif ch.tag == "p":
                _emit_p(ch, "other", None, passages)
            elif ch.tag in ("table-wrap", "fig"):
                _emit_float(ch, "other", None, passages)
    back = root.find("back")
    if back is not None:
        for ch in back:
            if ch.tag in SKIP_TAGS:
                continue
            if ch.tag in ("ack", "fn-group", "notes", "sec", "app-group"):
                _emit_back(ch, passages)
    if passages and passages[0].section_title == "Funding" and any(p.section_title == "Funding" for p in passages[1:]):
        passages = passages[1:]          # the back-matter funding statement exists; the front-matter award list is repetitive id soup
    lic = None
    lr = next(iter(root.iter("{http://www.niso.org/schemas/ali/1.0/}license_ref")), None)
    if lr is not None and lr.text:
        lic = lr.text.strip()
    elif root.find(".//license") is not None:
        lic = clean("".join(root.find(".//license").itertext()))[:200]
    fp, lp = root.findtext(".//article-meta/fpage"), root.findtext(".//article-meta/lpage")
    pages = f"{fp}-{lp}" if fp and lp else (fp or root.findtext(".//article-meta/elocation-id"))
    return assemble("pmc_jats", PARSER, passages, license=lic, printed_pages=pages,
                    meta={"title": clean("".join(root.find(".//article-meta/title-group/article-title").itertext()))
                          if root.find(".//article-meta/title-group/article-title") is not None else None})


def _emit_back(el, out) -> None:
    title = _title(el) if el.tag in ("sec", "ack", "notes", "app") else ""
    ntype = (el.get("notes-type") or el.get("fn-type") or "").lower()
    blob = f"{title} {ntype}".lower()
    funding = el.tag == "ack" or any(k in blob for k in BACK_FUNDING_NOTES) or canonical_section(title) == "funding_coi"
    section = "funding_coi" if funding else "other"
    shown = title or {"ack": "Acknowledgements", "fn-group": "Footnotes", "notes": "Notes"}.get(el.tag, "Back matter")
    for fl in el.iter("table-wrap", "fig"):                    # appendix / extended-data floats
        _emit_float(fl, "other", shown, out)
    for p in el.iter("p"):
        if any(a.tag in ("table-wrap", "fig", "caption", "table-wrap-foot") for a in p.iterancestors()):
            continue
        t = _text(p)
        if len(t) >= 20:
            out.append(ParsedPassage(text=t, section=section, kind="note", section_title=shown))
