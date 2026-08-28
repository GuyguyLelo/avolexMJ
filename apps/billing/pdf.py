"""Génération PDF des factures (WeasyPrint si possible, sinon fpdf2)."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.template.loader import render_to_string

from apps.core.money import format_money

if TYPE_CHECKING:
    from apps.billing.models import Invoice, InvoiceLine
    from apps.clients.models import Client
    from apps.tenants.models import Cabinet

logger = logging.getLogger(__name__)

INK = (12, 28, 46)
BRASS = (196, 154, 60)
SLATE = (102, 116, 131)
RULE = (226, 230, 236)

# PDF minimal valide (tests uniquement, BILLING_PDF_BACKEND=stub).
_STUB_PDF = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >>endobj
trailer<< /Root 1 0 R >>
%%EOF
"""


def build_invoice_pdf(invoice: Invoice) -> bytes:
    """
    Rend la facture en PDF.

    WeasyPrint est utilisé lorsqu'il est disponible (Linux/CI). Sous Windows,
    sans GTK/Pango, on bascule sur fpdf2 pour un PDF réellement lisible.
    """
    backend = getattr(settings, "BILLING_PDF_BACKEND", "weasyprint")
    if backend == "stub":
        return _STUB_PDF

    invoice = (
        type(invoice)
        .objects.select_related("cabinet", "client", "matter")
        .prefetch_related("lines")
        .get(pk=invoice.pk)
    )

    if backend == "fpdf":
        return _build_with_fpdf(invoice)

    if backend in {"weasyprint", "auto"}:
        pdf = _try_weasyprint(invoice)
        if pdf is not None:
            return pdf
        if backend == "weasyprint":
            logger.warning("WeasyPrint indisponible — génération fpdf2.")

    return _build_with_fpdf(invoice)


def _try_weasyprint(invoice: Invoice) -> bytes | None:
    """Tente WeasyPrint ; None si les libs système manquent."""
    html = render_to_string(
        "billing/pdf/invoice.html",
        {
            "invoice": invoice,
            "cabinet": invoice.cabinet,
            "client": invoice.client,
            "lines": invoice.lines.all(),
        },
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


def _format_qty(quantity: Decimal) -> str:
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return f"{quantity:.2f}"


def _format_date(value: object) -> str:
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")  # type: ignore[union-attr]
    return str(value)


def _join_address(*parts: str) -> str:
    return "  ·  ".join(p.strip() for p in parts if p and p.strip())


def _font_candidates() -> list[tuple[Path, Path]]:
    """Paires (regular, bold) de polices TrueType Unicode."""
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


def _clip(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _build_with_fpdf(invoice: Invoice) -> bytes:
    """Génère un PDF A4 via fpdf2 (sans dépendance native)."""
    from fpdf import FPDF

    cabinet: Cabinet = invoice.cabinet
    client: Client = invoice.client
    lines: list[InvoiceLine] = list(invoice.lines.all())
    is_draft = invoice.status == "draft" or not invoice.number
    title = invoice.number or "PROFORMA"

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.alias_nb_pages()

    font_name = "Helvetica"
    for regular, bold in _font_candidates():
        if regular.is_file():
            bold_path = bold if bold.is_file() else regular
            pdf.add_font("InvoiceSans", "", str(regular))
            pdf.add_font("InvoiceSans", "B", str(bold_path))
            font_name = "InvoiceSans"
            break

    pdf.add_page()

    # Bandeau
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 38, "F")
    pdf.set_fill_color(*BRASS)
    pdf.rect(0, 38, 210, 1.6, "F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "B", 18)
    pdf.set_xy(16, 10)
    pdf.cell(120, 8, cabinet.name, align="L")

    pdf.set_font(font_name, "", 9)
    pdf.set_xy(16, 19)
    legal = cabinet.legal_name or ""
    if legal and legal != cabinet.name:
        pdf.cell(120, 5, legal, align="L")
        pdf.set_xy(16, 24)
    pdf.set_text_color(201, 212, 224)
    pdf.cell(
        120,
        5,
        _join_address(cabinet.address_line1, f"{cabinet.postal_code} {cabinet.city}".strip()),
        align="L",
    )

    pdf.set_text_color(*BRASS)
    pdf.set_font(font_name, "B", 11)
    pdf.set_xy(130, 10)
    pdf.cell(64, 6, "FACTURE" if not is_draft else "FACTURE — PROFORMA", align="R")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "B", 16)
    pdf.set_xy(130, 17)
    pdf.cell(64, 8, title, align="R")
    pdf.set_font(font_name, "", 9)
    pdf.set_text_color(201, 212, 224)
    pdf.set_xy(130, 26)
    issued = _format_date(invoice.issued_at)
    due = _format_date(invoice.due_at)
    pdf.cell(64, 5, f"Émise le {issued}", align="R")
    pdf.set_xy(130, 31)
    pdf.cell(64, 5, f"Échéance {due}", align="R")

    y = 50
    pdf.set_text_color(*SLATE)
    pdf.set_font(font_name, "B", 8)
    pdf.set_xy(16, y)
    pdf.cell(90, 5, "FACTURÉ À")
    pdf.set_xy(110, y)
    pdf.cell(84, 5, "DOSSIER" if invoice.matter_id else "")

    y += 6
    pdf.set_text_color(*INK)
    pdf.set_font(font_name, "B", 12)
    pdf.set_xy(16, y)
    pdf.cell(90, 6, client.display_name)
    if invoice.matter_id:
        pdf.set_xy(110, y)
        pdf.cell(84, 6, invoice.matter.reference)

    y += 7
    pdf.set_font(font_name, "", 9)
    pdf.set_text_color(58, 69, 84)
    pdf.set_xy(16, y)
    client_city = f"{client.postal_code} {client.city}".strip()
    pdf.multi_cell(
        90,
        4.5,
        "\n".join(
            p
            for p in (
                client.address_line1,
                client.address_line2,
                client_city,
                client.email,
            )
            if p
        ),
    )
    client_block_bottom = pdf.get_y()
    if invoice.matter_id:
        pdf.set_xy(110, y)
        pdf.multi_cell(84, 4.5, invoice.matter.title)

    y = max(client_block_bottom, pdf.get_y()) + 6

    extras = []
    if cabinet.siret:
        extras.append(f"SIRET {cabinet.siret}")
    if cabinet.vat_number:
        extras.append(f"Impôt {cabinet.vat_number}")
    if cabinet.bar_association:
        extras.append(cabinet.bar_association)
    if extras:
        pdf.set_font(font_name, "", 8)
        pdf.set_text_color(*SLATE)
        pdf.set_xy(16, y)
        pdf.cell(178, 4, "  ·  ".join(extras))
        y += 8

    # Tableau
    col_w = (88, 22, 34, 34)
    headers = ("Description", "Qté", "P.U. HT", "Montant HT")
    pdf.set_fill_color(*INK)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "B", 8)
    pdf.set_xy(16, y)
    for i, header in enumerate(headers):
        align = "L" if i == 0 else "R"
        pdf.cell(col_w[i], 8, header, fill=True, align=align)
    y += 8

    pdf.set_font(font_name, "", 9)
    fill = False
    for line in lines:
        row_h = 8
        if y + row_h > 250:
            pdf.add_page()
            y = 20
            pdf.set_fill_color(*INK)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font(font_name, "B", 8)
            pdf.set_xy(16, y)
            for i, header in enumerate(headers):
                align = "L" if i == 0 else "R"
                pdf.cell(col_w[i], 8, header, fill=True, align=align)
            y += 8
            pdf.set_font(font_name, "", 9)

        if fill:
            pdf.set_fill_color(247, 248, 250)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(*INK)
        pdf.set_xy(16, y)
        pdf.set_font(font_name, "", 9)
        pdf.cell(col_w[0], row_h, _clip(line.description, 52), fill=True, align="L")
        pdf.cell(col_w[1], row_h, _format_qty(line.quantity), fill=True, align="R")
        pdf.cell(col_w[2], row_h, format_money(line.unit_price), fill=True, align="R")
        pdf.set_font(font_name, "B", 9)
        pdf.cell(col_w[3], row_h, format_money(line.amount), fill=True, align="R")
        y += row_h
        fill = not fill

    if not lines:
        pdf.set_xy(16, y)
        pdf.set_text_color(*SLATE)
        pdf.cell(sum(col_w), 10, "Aucune ligne.", align="C")
        y += 12

    y += 6
    totals_x = 110
    label_w, value_w = 46, 38

    def _total_row(label: str, value: str, *, emphasize: bool = False) -> None:
        nonlocal y
        pdf.set_xy(totals_x, y)
        if emphasize:
            pdf.set_fill_color(*INK)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font(font_name, "B", 11)
            pdf.cell(label_w, 9, label, fill=True)
            pdf.set_text_color(*BRASS)
            pdf.cell(value_w, 9, value, fill=True, align="R")
        else:
            pdf.set_fill_color(247, 248, 250)
            pdf.set_text_color(*SLATE)
            pdf.set_font(font_name, "", 9)
            pdf.cell(label_w, 7, label, fill=True)
            pdf.set_text_color(*INK)
            pdf.set_font(font_name, "B", 9)
            pdf.cell(value_w, 7, value, fill=True, align="R")
        y += 7 if not emphasize else 9

    _total_row("Total HT", format_money(invoice.subtotal))
    _total_row(f"TVA ({invoice.tax_rate} %)", format_money(invoice.tax_amount))
    y += 1
    _total_row("Total TTC", format_money(invoice.total), emphasize=True)

    if invoice.notes:
        y += 10
        pdf.set_xy(16, y)
        pdf.set_text_color(*SLATE)
        pdf.set_font(font_name, "B", 8)
        pdf.cell(178, 5, "NOTES")
        y += 6
        pdf.set_xy(16, y)
        pdf.set_text_color(*INK)
        pdf.set_font(font_name, "", 9)
        pdf.multi_cell(178, 4.5, invoice.notes)

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
        "Document généré par AvoLex — Ministère de la Justice (RDC).",
        align="L",
    )
    pdf.cell(58, 6, f"Page {pdf.page_no()}/{{nb}}", align="R")

    raw = pdf.output()
    return bytes(raw) if not isinstance(raw, bytes) else raw
