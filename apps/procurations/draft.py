"""Brouillon HTML de l'acte de procuration (éditeur puis publication PDF)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from apps.procurations.models import Procuration

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "sub",
        "sup",
        "span",
        "div",
        "font",
        "h1",
        "h2",
        "h3",
        "hr",
        "ul",
        "ol",
        "li",
    }
)
_ALLOWED_ATTRS = frozenset({"class", "style", "face", "size", "color"})
_COLOR = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)|"
    r"rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)|"
    r"[a-zA-Z]{3,20})$"
)
_LENGTH = re.compile(r"^[\d.]+\s*(pt|px|em|rem|%)?$", re.IGNORECASE)
_FONT_FAMILY = re.compile(r'^[a-zA-Z0-9\s,\-\'"\.]+$')
_ALIGN = re.compile(r"^(left|right|center|justify)$", re.IGNORECASE)
_WEIGHT = re.compile(r"^(normal|bold|[1-9]00)$", re.IGNORECASE)
_STYLE = re.compile(r"^(normal|italic|oblique)$", re.IGNORECASE)
_DECORATION = re.compile(
    r"^(none|underline|line-through|underline line-through)$",
    re.IGNORECASE,
)


def _sanitize_style(value: str) -> str:
    """Conserve uniquement des déclarations CSS de mise en forme sûres."""
    kept: list[str] = []
    for part in value.split(";"):
        if ":" not in part:
            continue
        prop, raw = part.split(":", 1)
        prop = prop.strip().lower()
        raw = raw.strip()
        if not prop or not raw or re.search(r"[{}<>]|expression|url\s*\(", raw, re.I):
            continue
        if prop in {"color", "background-color"} and _COLOR.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "font-size" and _LENGTH.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "font-family" and _FONT_FAMILY.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "font-weight" and _WEIGHT.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "font-style" and _STYLE.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "text-decoration" and _DECORATION.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop == "text-align" and _ALIGN.match(raw):
            kept.append(f"{prop}: {raw}")
        elif prop in {
            "margin",
            "margin-top",
            "margin-bottom",
            "margin-left",
            "margin-right",
            "text-indent",
            "letter-spacing",
            "line-height",
            "padding",
            "padding-top",
            "padding-bottom",
        } and not re.search(r"[{}<>]|url\s*\(", raw, re.I):
            kept.append(f"{prop}: {raw}")
    return "; ".join(kept)


class _HtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        if tag == "br":
            self._out.append("<br>")
            return
        if tag == "hr":
            self._out.append('<hr class="rule">')
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name = name.lower()
            if name not in _ALLOWED_ATTRS or value is None:
                continue
            if name == "style":
                cleaned = _sanitize_style(value)
                if cleaned:
                    safe_attrs.append(f'style="{_escape_attr(cleaned)}"')
            elif name == "class":
                classes = " ".join(
                    c for c in value.split() if re.fullmatch(r"[a-zA-Z0-9_-]+", c)
                )
                if classes:
                    safe_attrs.append(f'class="{classes}"')
            elif name == "face" and _FONT_FAMILY.match(value):
                safe_attrs.append(f'face="{_escape_attr(value)}"')
            elif name == "size" and re.fullmatch(r"[1-7]", value.strip()):
                safe_attrs.append(f'size="{value.strip()}"')
            elif name == "color" and _COLOR.match(value.strip()):
                safe_attrs.append(f'color="{_escape_attr(value.strip())}"')
        attr_s = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        self._out.append(f"<{tag}{attr_s}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _ALLOWED_TAGS and tag not in {"br", "hr"}:
            self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._out.append(_escape_text(data))

    def result(self) -> str:
        return "".join(self._out)


def _escape_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def sanitize_draft_html(html: str) -> str:
    """Ne conserve que des balises / styles sûrs pour l'éditeur et le PDF."""
    parser = _HtmlSanitizer()
    parser.feed(html or "")
    parser.close()
    return parser.result().strip()


def render_default_draft_html(procuration: Procuration) -> str:
    """Génère le HTML initial à partir des données métier (modèle officiel)."""
    from apps.procurations.pdf import _load_procuration, _template_context

    loaded = _load_procuration(procuration)
    return render_to_string(
        "procurations/pdf/procuration_body.html",
        _template_context(loaded),
    ).strip()


def ensure_draft_html(procuration: Procuration) -> str:
    """Retourne le brouillon existant ou initialise depuis le modèle."""
    current = (procuration.draft_html or "").strip()
    if current:
        return current
    return render_default_draft_html(procuration)
