"""Shared math parsing for document exports."""
from __future__ import annotations

import re

# Common TeX delimiters and standalone AMS display environments; nested environments
# remain inside their outer match and are passed to the math renderer intact.
MATH_RE = re.compile(
    r"(?<!\\)(?P<dollar_display>\$\$[\s\S]+?(?<!\\)\$\$)"
    r"|(?P<bracket>\\\[[\s\S]+?\\\])"
    r"|(?P<paren>\\\([\s\S]+?\\\))"
    r"|(?P<env>\\begin\{(?P<envname>equation\*?|align\*?|aligned|alignat\*?|alignedat|gather\*?|gathered|multline\*?|flalign\*?|split|array|cases|[pbBvV]?matrix|displaymath)\}[\s\S]+?\\end\{(?P=envname)\})"
    r"|(?<![\\$])(?P<dollar>\$(?!\$)[^$\n]+?(?<!\\)\$)"
)

# These commands occur in the OpenStax/LibreTexts source material; their definitions
# must be shared by PDF and Word so both formats mean the same thing.
MACROS = {
    r"\dee": r"\mathrm{d}#1", r"\pdiff": r"\frac{\partial #1}{\partial #2}",
    r"\Set": r"\left\{#1\mid #2\right\}", r"\dblInt": r"\iint",
    r"\tripInt": r"\iiint", r"\vF": r"\mathbf{F}", r"\vr": r"\mathbf{r}",
    r"\vnabla": r"\boldsymbol{\nabla}", r"\hn": r"\hat{\mathbf{n}}",
    r"\hi": r"\hat{\mathbf{i}}", r"\hj": r"\hat{\mathbf{j}}", r"\ds": r"\displaystyle",
}
_ARGS = {r"\dee": 1, r"\pdiff": 2, r"\Set": 2}
_DEFINITIONS = "".join(
    rf"\newcommand{{{name}}}" + (f"[{_ARGS[name]}]" if name in _ARGS else "") + "{" + value + "}"
    for name, value in MACROS.items()
)


def segments(text: str):
    text = re.sub(
        r"(?im)^(?P<label>[ \t]*(?:[0-9]+\.[ \t]*)?(?:\u7b54\u6848|answer)[ \t]*[:\uff1a][ \t]*)(?P<answer>[^\r\n]+)$",
        lambda match: match.group("label") + formula_answer(match.group("answer")),
        text,
    )
    text = re.sub(
        r"(?m)^[ \t]*(\\text\{[^{}\r\n]*\})[ \t]*$",
        lambda match: r"\(" + match.group(1) + r"\)",
        text,
    )
    pos = 0
    for match in MATH_RE.finditer(text):
        if match.start() > pos:
            yield False, False, text[pos:match.start()]
        raw = match.group()
        display = match.lastgroup in ("dollar_display", "bracket", "env", "envname")
        body = raw if raw.startswith(r"\begin{") else raw[2:-2] if raw.startswith(("$$", r"\[", r"\(")) else raw[1:-1]
        yield True, display, body
        pos = match.end()
    if pos < len(text):
        yield False, False, text[pos:]


def prepare(tex: str) -> str:
    # LibreTexts represents the alignment character as \amp in some exports.
    return re.sub(r"\\amp\b", "&", tex)


def formula_answer(value: str) -> str:
    """Mark a bare TeX-only answer as math; ordinary prose is left alone."""
    text = value.strip()
    if any(mark in text for mark in ("$", r"\(", r"\[", r"\begin{")):
        return value
    command = re.match(r"^\\[A-Za-z]+\b", text)
    plain_math = re.fullmatch(r"[A-Za-z0-9_+*/^=(){}.,\-\s]+", text) and re.search(r"[_^]", text)
    if command or plain_math:
        return r"\(" + text + r"\)"
    return value


def to_omml(tex: str):
    from latex2mathml.converter import convert
    import mathml2omml
    from lxml import etree
    from docx.oxml import parse_xml

    tex = prepare(tex).replace(r"\begin{aligned}", r"\begin{align*}").replace(r"\end{aligned}", r"\end{align*}")
    try:
        mathml = convert(_DEFINITIONS + tex)
        root = etree.fromstring(mathml.encode("utf-8"))
        unknown = root.xpath("//*[local-name()='mi' and starts-with(text(), '\\')]")
        if unknown:
            raise ValueError("Unsupported TeX command: " + (unknown[0].text or ""))
        xml = mathml2omml.convert(mathml)
        # mathml2omml 0.0.2 closes groupChrPr incorrectly for overbrace/underbrace.
        xml = xml.replace('</m:groupChr><m:e>', '</m:groupChrPr><m:e>')
        return parse_xml('<root xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">' + xml + '</root>')[0]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid or unsupported formula") from exc
