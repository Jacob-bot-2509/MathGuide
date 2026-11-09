"""Shared math parsing for document exports."""
from __future__ import annotations

import re

# Common TeX delimiters and standalone AMS display environments; nested environments
# remain inside their outer match and are passed to the math renderer intact.
MATH_RE = re.compile(
    r"(?<![\\$])(?P<adjacent>\$(?!\$)[^$\n]+[+\-]\$\$(?!\$)[^$\n]+(?<!\\)\$(?!\$))"
    r"|(?<!\\)(?P<dollar_display>\$\$[\s\S]+?(?<!\\)\$\$)"
    r"|(?<!\\)(?P<bracket>\\{1,2}\[(?P<bracket_body>[\s\S]+?)(?<!\\)\\{1,2}\])"
    r"|(?<!\\)(?P<paren>\\{1,2}\((?P<paren_body>[\s\S]+?)(?<!\\)\\{1,2}\))"
    r"|(?P<env>\\begin\{(?P<envname>equation|align|alignat|gather|multline|flalign|aligned|alignedat|gathered|split|array|cases|[pbBvV]?matrix|displaymath)(?P<envstar>\\?\*)?\}[\s\S]+?\\end\{(?P=envname)(?(envstar)\\?\*)\})"
    r"|(?<![\\$])(?P<dollar>\$(?!\$)[^$\n]+?(?<!\\)\$)"
)

# These commands occur in the OpenStax/LibreTexts source material; their definitions
# must be shared by PDF and Word so both formats mean the same thing.
MACROS = {
    r"\dee": r"\mathrm{d}#1", r"\pdiff": r"\frac{\partial #1}{\partial #2}",
    r"\Set": r"\left\{#1\mid #2\right\}", r"\set": r"\left\{#1\mid #2\right\}", r"\dblInt": r"\iint",
    r"\tripInt": r"\iiint", r"\vF": r"\mathbf{F}", r"\vr": r"\mathbf{r}",
    r"\vnabla": r"\boldsymbol{\nabla}", r"\hn": r"\hat{\mathbf{n}}",
    r"\hi": r"\hat{\mathbf{i}}", r"\hj": r"\hat{\mathbf{j}}", r"\hk": r"\hat{\mathbf{k}}",
    r"\ds": r"\displaystyle", r"\diff": r"\frac{\mathrm{d}#1}{\mathrm{d}#2}",
    r"\overparen": r"\overset{\frown}{#1}", r"\mbox": r"\text{#1}",
    r"\bbbr": r"\mathbb{R}", r"\vZero": r"\mathbf{0}", r"\half": r"\frac{1}{2}",
    r"\perpendicular": r"\perp", r"\Om": r"\Omega",
    # shortcut: render the cancellation arrow separately until native cancelto is available.
    r"\cancelto": r"\overset{\nearrow #1}{\cancel{#2}}",
    r"\Atop": r"\substack{#1\\#2}", r"\knowl": r"#2", r"\PageIndex": r"#1",
    r"\hN": r"\hat{\mathbf{N}}", r"\hT": r"\hat{\mathbf{T}}",
    **{rf"\c{letter}": rf"\mathcal{{{letter}}}" for letter in "CDLPRSV"},
    **{rf"\v{letter}": rf"\mathbf{{{letter}}}" for letter in "AEGHVabcnv"},
}
_ARGS = {r"\dee": 1, r"\pdiff": 2, r"\Set": 2, r"\set": 2, r"\diff": 2, r"\overparen": 1, r"\mbox": 1, r"\Atop": 2, r"\cancelto": 2, r"\knowl": 2, r"\PageIndex": 1}
_DEFINITIONS = "".join(
    rf"\newcommand{{{name}}}" + (f"[{_ARGS[name]}]" if name in _ARGS else "") + "{" + value + "}"
    for name, value in MACROS.items()
)


def isolate(text: str) -> tuple[str, dict[str, str]]:
    """Protect complete math from text cleanup and paragraph splitting."""
    prefix = "MGFORMULATOKEN"
    while prefix in text:
        prefix += "X"
    formulas: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        token = f"{prefix}{len(formulas)}END"
        formulas[token] = match.group()
        return token

    protected = MATH_RE.sub(replace, text)
    pending = re.search(r"(?<![\\$])(?:\$\$|\$(?!\$)|\\{1,2}[\[(])", protected)
    if pending:
        token = f"{prefix}{len(formulas)}END"
        formulas[token] = protected[pending.start():]
        protected = protected[:pending.start()] + token
    return protected, formulas


def restore(text: str, formulas: dict[str, str]) -> str:
    for token, original in reversed(list(formulas.items())):
        text = text.replace(token, original)
    return text


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
        body = ("{}".join(raw[1:-1].split("$$", 1)) if match.group("adjacent") else
                match.group("bracket_body") if match.group("bracket") else
                match.group("paren_body") if match.group("paren") else
                raw if raw.startswith(r"\begin{") else
                raw[2:-2] if raw.startswith("$$") else raw[1:-1])
        if re.match(r"\s*\\{1,2}begin\{(?:align|alignat|gather|equation|multline|flalign)(?:\\?\*)?\}", body):
            display = True
        yield True, display, body
        pos = match.end()
    if pos < len(text):
        yield False, False, text[pos:]


def prepare(tex: str) -> str:
    if tex.strip() in (r"\(", r"\)"):
        return tex.strip()[1:]
    # A Markdown-escaped environment signals that TeX syntax was escaped as prose.
    if re.search(r"\\(?:begin|end)\{[A-Za-z]+\\\*\}", tex):
        tex = re.sub(r"(\\(?:begin|end)\{[A-Za-z]+)\\\*(\})", r"\1*\2", tex)
        parts = re.split(r"(\\(?:text|mathrm|operatorname|mathtt|mbox)\s*\{(?:[^{}]|\{[^{}]*\})*\})", tex)
        for index in range(0, len(parts), 2):
            part = re.sub(r"\\_(?=[{0-9])", "_", parts[index])
            part = part.replace(r"\\,", r"\,")
            parts[index] = re.sub(r"\\\\\\(?=\s*&)", lambda _: r"\\", part)
        tex = "".join(parts)
    # Machine translations sometimes repeat a geometry symbol outside nested delimiters.
    duplicate = re.fullmatch(r"\s*(\\(?:triangle|angle))\s*\\{1,2}\(\s*(\1\b[\s\S]*?)\\{1,2}\)\s*", tex)
    if duplicate:
        tex = duplicate.group(2)
    # Some source formulas contain a second pair of delimiters inside the first.
    inner = MATH_RE.fullmatch(tex.strip())
    if inner and (inner.group("paren") or inner.group("bracket")):
        tex = inner.group("paren_body") or inner.group("bracket_body")
    parts = re.split(r"(\\(?:text|mathrm|operatorname|mathtt|mbox)\s*\{(?:[^{}]|\{[^{}]*\})*\})", tex)
    for index in range(0, len(parts), 2):
        part = parts[index]
        escaped_env = bool(re.search(r"(?<!\\)\\\\(?:begin|end)\{", part))
        part = re.sub(
            r"(?<!\\)\\\\(?=(?:begin|end|frac|dfrac|tfrac|sqrt|leqslant|geqslant|leq|geq|left|right|boxed|cdot|times|sin|cos|tan)\b)",
            lambda _: "\\", part,
        )
        if escaped_env:
            part = re.sub(r"(?<!\\)\\{4}(?!\\)", lambda _: r"\\", part)
        if r"\\{" in part and r"\\}" in part:
            part = part.replace(r"\\{", r"\{").replace(r"\\}", r"\}")
        part = re.sub(r"\\root\s*(\d+)\s*\\of\s*", lambda m: r"\sqrt[" + m.group(1) + "]", part)
        part = re.sub(r"\\renewcommand\s*\{\\arraystretch\}\s*\{([^{}]+)\}", lambda m: r"\def\arraystretch{" + m.group(1) + "}", part)
        part = re.sub(r"(?<![A-Za-z\\])_([A-Za-z])_(?![A-Za-z0-9])", r"\1", part)
        part = re.sub(r"\\\[([^\[\]]*?)\\\]", r"[\1]", part)
        parts[index] = part.replace(r"^{\*}", r"^{*}").replace("\\\u221a", r"\surd")
    for index in range(1, len(parts), 2):
        if re.match(r"\\(?:text|mbox)\s*\{", parts[index]):
            parts[index] = re.sub(r"(?<!\\)_", lambda _: r"\_", parts[index])
    tex = "".join(parts)
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


def expand_macros(tex: str) -> str:
    """Expand the known source macros for Markdown readers without project configuration."""
    def expand(source: str, depth: int = 0) -> str:
        if depth > 32:
            return source
        out = []
        pos = 0
        while pos < len(source):
            if source[pos] != "\\":
                out.append(source[pos])
                pos += 1
                continue
            command = re.match(r"\\[A-Za-z]+|\\.", source[pos:])
            if not command:
                out.append(source[pos])
                pos += 1
                continue
            name = command.group()
            end = pos + len(name)
            if name not in MACROS:
                out.append(name)
                pos = end
                continue
            args = []
            cursor = end
            for _ in range(_ARGS.get(name, 0)):
                while cursor < len(source) and source[cursor].isspace():
                    cursor += 1
                if cursor >= len(source):
                    break
                if source[cursor] == "{":
                    start = cursor + 1
                    level = 1
                    cursor += 1
                    while cursor < len(source) and level:
                        if source[cursor] == "\\" and cursor + 1 < len(source):
                            cursor += 2
                            continue
                        level += (source[cursor] == "{") - (source[cursor] == "}")
                        cursor += 1
                    if level:
                        break
                    args.append(source[start:cursor - 1])
                elif source[cursor] == "\\":
                    arg = re.match(r"\\[A-Za-z]+|\\.", source[cursor:])
                    if not arg:
                        break
                    args.append(arg.group())
                    cursor += len(arg.group())
                else:
                    args.append(source[cursor])
                    cursor += 1
            if len(args) != _ARGS.get(name, 0):
                out.append(name)
                pos = end
                continue
            value = MACROS[name]
            for number, arg in enumerate(args, 1):
                value = value.replace(f"#{number}", "{" + expand(arg, depth + 1) + "}")
            out.append("{" + expand(value, depth + 1) + "}")
            pos = cursor
        return "".join(out)

    return expand(tex)


def markdown(text: str) -> str:
    """Use common Markdown math delimiters and self-contained source macros."""
    result = []
    for is_math, display, value in segments(text):
        if not is_math:
            result.append(value)
            continue
        value = expand_macros(prepare(value))
        result.append("\n\n$$\n" + value + "\n$$\n\n" if display else "$" + re.sub(r"\s*\r?\n\s*", " ", value) + "$")
    return "".join(result)


def to_omml(tex: str):
    from latex2mathml.converter import convert
    import mathml2omml
    from lxml import etree
    from docx.oxml import parse_xml

    tex = prepare(tex).replace(r"\begin{aligned}", r"\begin{align*}").replace(r"\end{aligned}", r"\end{align*}")
    # The Word converter supports align but not alignat's spacing argument.
    tex = re.sub(r"\\begin\{(?:alignat\*?|alignedat)\}\s*\{\d+\}", lambda _: r"\begin{align*}", tex)
    tex = re.sub(r"\\end\{(?:alignat\*?|alignedat)\}", lambda _: r"\end{align*}", tex)
    tex = re.sub(r"(?<!\\)\\\r?\n", lambda _: r"\ ", tex)
    # Word math has no equation numbering or discretionary line breaks here.
    tex = re.sub(r"(?<!\\)\\(?:nonumber|notag|allowbreak)\b", "", tex)
    tex = re.sub(r"(?<!\\)\\arg\b", lambda _: r"\operatorname{arg}", tex)
    if re.search(r"\\begin\{array\}\s*\{[^{}]*[@*]", tex):
        raise ValueError("Unsupported array column specification")
    # Work around converter ambiguity for equations beginning with a bracket.
    tex = re.sub(r"(\\begin\{align\*?\})\s*(?=\[)", lambda m: m.group(1) + " {} ", tex)
    tex = re.sub(
        r"\\genfrac\s*\{\}\s*\{\}\s*\{0pt\}\s*\{\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
        lambda m: r"\substack{" + m.group(1) + r"\\" + m.group(2) + "}", tex,
    )
    tex = re.sub(r"\\mathop\s*\{\s*\\text\s*\{([A-Za-z]+)\}\s*\}", lambda m: r"\operatorname{" + m.group(1) + "}", tex)
    try:
        mathml = convert(_DEFINITIONS + tex)
        root = etree.fromstring(mathml.encode("utf-8"))
        unknown = root.xpath("//*[local-name()='mi' and starts-with(text(), '\\')]")
        literal_backslashes = len(re.findall(r"(?<!\\)\\backslash\b", tex))
        for node in unknown:
            if node.text == "\\" and literal_backslashes:
                literal_backslashes -= 1
                continue
            raise ValueError("Unsupported TeX command: " + (node.text or ""))
        # latex2mathml may emit matrix delimiters as extra children of a script.
        for node in root.xpath("//*[local-name()='msup' or local-name()='msub' or local-name()='msubsup']"):
            expected = 3 if etree.QName(node).localname == "msubsup" else 2
            if len(node) > expected:
                group = etree.Element("{http://www.w3.org/1998/Math/MathML}mrow")
                for child in list(node)[:len(node) - expected + 1]:
                    group.append(child)
                node.insert(0, group)
        mathml = etree.tostring(root, encoding="unicode")
        xml = mathml2omml.convert(mathml)
        # mathml2omml 0.0.2 closes groupChrPr incorrectly for overbrace/underbrace.
        xml = xml.replace('</m:groupChr><m:e>', '</m:groupChrPr><m:e>')
        result = parse_xml('<root xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">' + xml + '</root>')[0]
        enclosures = root.xpath("//*[local-name()='menclose']")
        boxes = result.xpath(".//*[local-name()='borderBox']")
        if len(enclosures) != len(boxes):
            raise ValueError("Unable to preserve math enclosure")
        for enclosure, box in zip(enclosures, boxes):
            notation = set(enclosure.get("notation", "longdiv").split())
            if notation == {"box"}:
                continue
            strikes = {"updiagonalstrike": "strikeBLTR", "downdiagonalstrike": "strikeTLBR",
                       "horizontalstrike": "strikeH", "verticalstrike": "strikeV"}
            if not notation or not notation <= strikes.keys():
                raise ValueError("Unsupported math enclosure")
            namespace = "http://schemas.openxmlformats.org/officeDocument/2006/math"
            properties = etree.Element(f"{{{namespace}}}borderBoxPr")
            for name in ("hideTop", "hideBot", "hideLeft", "hideRight"):
                etree.SubElement(properties, f"{{{namespace}}}{name}").set(f"{{{namespace}}}val", "1")
            for name in ("horizontalstrike", "verticalstrike", "updiagonalstrike", "downdiagonalstrike"):
                if name in notation:
                    etree.SubElement(properties, f"{{{namespace}}}{strikes[name]}").set(f"{{{namespace}}}val", "1")
            box.insert(0, properties)
        return result
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid or unsupported formula") from exc
