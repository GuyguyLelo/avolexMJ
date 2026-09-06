"""Génération PDF de l'acte de procuration ministérielle."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from apps.procurations.models import Procuration

logger = logging.getLogger(__name__)

INK = (12, 28, 46)
BRASS = (196, 154, 60)
SLATE = (102, 116, 131)

_STUB_PDF = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >>endobj
trailer<< /Root 1 0 R >>
%%EOF
"""


def build_procuration_pdf(procuration: Procuration) -> bytes:
    """Rend l'acte de procuration en PDF."""
    backend = getattr(settings, "BILLING_PDF_BACKEND", "weasyprint")
    if backend == "stub":
        return _STUB_PDF

    procuration = (
        type(procuration)
        .unscoped.select_related("cabinet", "matter", "granted_by")
        .prefetch_related("matter__parties")
        .get(pk=procuration.pk)
    )

    if backend == "fpdf":
        return _build_with_fpdf(procuration)

    if backend in {"weasyprint", "auto"}:
        pdf = _try_weasyprint(procuration)
        if pdf is not None:
            return pdf
        if backend == "weasyprint":
            logger.warning("WeasyPrint indisponible — génération fpdf2.")

    return _build_with_fpdf(procuration)


def _try_weasyprint(procuration: Procuration) -> bytes | None:
    html = render_to_string(
        "procurations/pdf/procuration.html",
        _template_context(procuration),
    )
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]

        result = HTML(string=html, base_url=".").write_pdf()
    except Exception as exc:
        logger.warning("WeasyPrint indisponible (%s).", exc)
        return None
    if isinstance(result, bytes) and result.startswith(b"%PDF"):
        return result
    return None


def _template_context(procuration: Procuration) -> dict[str, object]:
    cabinet = procuration.cabinet
    matter = procuration.matter
    # Use parties instead of client
    parties = []
    if matter is not None:
        parties = list(matter.parties.all().order_by("role", "name"))
    client_name = procuration.client_name
    granted_by = ""
    if procuration.granted_by_id:
        granted_by = procuration.granted_by.get_full_name() or procuration.granted_by.email
    return {
        "procuration": procuration,
        "cabinet": cabinet,
        "matter": matter,
        "parties": parties,
        "client_name": client_name,
        "granted_by": granted_by,
        "country": getattr(settings, "SITE_COUNTRY", "République Démocratique du Congo"),
        "institution": getattr(
            settings, "SITE_INSTITUTION", "Ministère de la Justice et Garde des Sceaux"
        ),
        "authority": getattr(settings, "SITE_AUTHORITY", "Le Gouvernement"),
    }


def _format_date(value: object) -> str:
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")  # type: ignore[union-attr]
    return str(value)


def _font_candidates() -> list[tuple[Path, Path]]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    base = Path(settings.BASE_DIR) / "static" / "fonts"
    return [
        (base / "SourceSans3-Regular.ttf", base / "SourceSans3-Bold.ttf"),
        (windir / "arial.ttf", windir / "arialbd.ttf"),
        (windir / "calibri.ttf", windir / "calibrib.ttf"),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ),
    ]


def _join(*parts: str) -> str:
    return "  ·  ".join(p.strip() for p in parts if p and p.strip())


def _build_with_fpdf(procuration: Procuration) -> bytes:
    from fpdf import FPDF

    ctx = _template_context(procuration)
    cabinet = procuration.cabinet
    matter = procuration.matter

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.alias_nb_pages()

    font_name = "Helvetica"
    for regular, bold in _font_candidates():
        if regular.is_file():
            bold_path = bold if bold.is_file() else regular
            pdf.add_font("ProcSans", "", str(regular))
            pdf.add_font("ProcSans", "B", str(bold_path))
            font_name = "ProcSans"
            break

    pdf.add_page()

    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 42, "F")
    pdf.set_fill_color(*BRASS)
    pdf.rect(0, 42, 210, 1.6, "F")

    pdf.set_text_color(201, 212, 224)
    pdf.set_font(font_name, "", 9)
    pdf.set_xy(16, 10)
    pdf.cell(178, 5, str(ctx["country"]), align="C")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "B", 14)
    pdf.set_xy(16, 17)
    pdf.cell(178, 8, str(ctx["institution"]), align="C")

    pdf.set_text_color(*BRASS)
    pdf.set_font(font_name, "B", 11)
    pdf.set_xy(16, 28)
    pdf.cell(178, 6, "PROCURATION", align="C")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "B", 12)
    pdf.set_xy(16, 34)
    pdf.cell(178, 6, procuration.reference, align="C")

    y = 54
    if procuration.ministry_reference:
        pdf.set_text_color(*SLATE)
        pdf.set_font(font_name, "", 9)
        pdf.set_xy(16, y)
        pdf.cell(178, 5, f"Référence ministérielle : {procuration.ministry_reference}", align="C")
        y += 10

    pdf.set_text_color(*INK)
    pdf.set_font(font_name, "", 11)
    pdf.set_xy(16, y)
    pdf.multi_cell(
        178,
        6,
        "Le Ministre de la Justice et Garde des Sceaux donne par les présentes "
        "procuration au cabinet d'avocats ci-après désigné, pour accomplir les "
        "actes de procédure et de représentation dans le dossier indiqué.",
    )
    y = pdf.get_y() + 8

    def _section(title: str) -> None:
        nonlocal y
        pdf.set_text_color(*SLATE)
        pdf.set_font(font_name, "B", 8)
        pdf.set_xy(16, y)
        pdf.cell(178, 5, title.upper())
        y += 6

    def _body(text: str, *, bold: bool = False) -> None:
        nonlocal y
        pdf.set_text_color(*INK)
        pdf.set_font(font_name, "B" if bold else "", 11)
        pdf.set_xy(16, y)
        pdf.multi_cell(178, 6, text)
        y = pdf.get_y() + 4

    _section("Cabinet destinataire")
    _body(cabinet.name, bold=True)
    extras = _join(
        cabinet.legal_name if cabinet.legal_name != cabinet.name else "",
        cabinet.bar_association,
        cabinet.address_line1,
        f"{cabinet.postal_code} {cabinet.city}".strip(),
    )
    if extras:
        pdf.set_font(font_name, "", 9)
        pdf.set_text_color(58, 69, 84)
        pdf.set_xy(16, y)
        pdf.multi_cell(178, 5, extras)
        y = pdf.get_y() + 6

    _section("Objet de la procuration")
    _body(procuration.purpose or procuration.subject)

    _section("Dossier")
    if matter is not None:
        _body(f"{matter.reference} — {matter.title}", bold=True)
        details = [
            f"Juridiction : {matter.jurisdiction}" if matter.jurisdiction else "",
            f"Échelle : {matter.get_scale_display()}",
        ]
        # Add parties
        for party in ctx.get("parties", []):
            role_display = party.get_role_display()
            state_marker = " (État)" if party.is_state_entity else ""
            details.append(f"{role_display}{state_marker} : {party.name}")
            if party.notes:
                details.append(f"  Note : {party.notes}")
    else:
        _body(procuration.subject or procuration.purpose, bold=True)
        details = [
            f"Justiciable : {procuration.client_name}" if procuration.client_name else "",
            f"Juridiction : {procuration.jurisdiction}" if procuration.jurisdiction else "",
            f"Échelle : {procuration.get_scale_display()}",
            f"Partie adverse : {procuration.opposing_party}" if procuration.opposing_party else "",
        ]
    lines = [line for line in details if line]
    if lines:
        pdf.set_font(font_name, "", 10)
        pdf.set_text_color(58, 69, 84)
        pdf.set_xy(16, y)
        pdf.multi_cell(178, 5, "\n".join(lines))
        y = pdf.get_y() + 6

    _section("Validité")
    valid_from = _format_date(procuration.valid_from or procuration.granted_at)
    expires = (
        _format_date(procuration.expires_at) if procuration.expires_at else "sans terme"
    )
    _body(f"Du {valid_from} au {expires}.")

    if procuration.notes:
        _section("Observations")
        _body(procuration.notes)

    y += 6
    granted_at = _format_date(procuration.granted_at)
    pdf.set_text_color(*INK)
    pdf.set_font(font_name, "", 11)
    pdf.set_xy(16, y)
    pdf.cell(178, 6, f"Fait à Kinshasa, le {granted_at}.")
    y += 16

    pdf.set_text_color(*SLATE)
    pdf.set_font(font_name, "B", 8)
    pdf.set_xy(110, y)
    pdf.cell(78, 5, "Pour le Ministre de la Justice", align="C")
    y += 6
    pdf.set_text_color(*INK)
    pdf.set_font(font_name, "B", 11)
    pdf.set_xy(110, y)
    pdf.cell(78, 6, str(ctx["granted_by"]) or "—", align="C")

    pdf.set_y(-18)
    pdf.set_draw_color(*BRASS)
    pdf.set_line_width(0.4)
    pdf.line(16, pdf.get_y(), 194, pdf.get_y())
    pdf.set_y(-15)
    pdf.set_text_color(*SLATE)
    pdf.set_font(font_name, "", 7.5)
    pdf.cell(
        120,
        6,
        "Acte généré par AvoLex — Ministère de la Justice (RDC).",
        align="L",
    )
    pdf.cell(58, 6, f"Page {pdf.page_no()}/{{nb}}", align="R")

    raw = pdf.output()
    return bytes(raw) if not isinstance(raw, bytes) else raw
