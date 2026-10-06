"""Génération PDF de l'acte de procuration ministérielle (modèle officiel MJ)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

if TYPE_CHECKING:
    from apps.procurations.models import Procuration

logger = logging.getLogger(__name__)

INK = (17, 17, 17)
SLATE = (51, 51, 51)

_STUB_PDF = b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >>endobj
trailer<< /Root 1 0 R >>
%%EOF
"""


def build_procuration_pdf(procuration: Procuration) -> bytes:
    """Rend l'acte de procuration en PDF selon le modèle ministériel."""
    backend = getattr(settings, "BILLING_PDF_BACKEND", "weasyprint")
    if backend == "stub":
        return _STUB_PDF

    procuration = (
        type(procuration)
        .unscoped.select_related(
            "cabinet",
            "matter",
            "matter__responsible_lawyer",
            "granted_by",
        )
        .prefetch_related("matter__parties", "matter__assigned_lawyers__lawyer")
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


def _format_date_long(value: object) -> str:
    """Date française : 08 septembre 2026."""
    if value is None:
        return "…………………"
    if not hasattr(value, "strftime"):
        return str(value)
    months = (
        "",
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    day = int(value.strftime("%d"))  # type: ignore[union-attr]
    month = months[int(value.strftime("%m"))]  # type: ignore[union-attr]
    year = value.strftime("%Y")  # type: ignore[union-attr]
    return f"{day:02d} {month} {year}"


def _cabinet_address(cabinet: Any) -> str:
    if cabinet is None:
        return ""
    parts = [
        cabinet.address_line1 or "",
        cabinet.address_line2 or "",
        " ".join(p for p in [cabinet.postal_code or "", cabinet.city or ""] if p).strip(),
    ]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _lawyer_label(user: Any) -> str:
    if user is None:
        return ""
    name = (user.get_full_name() or user.email or "").strip()
    if not name:
        return ""
    if name.lower().startswith("maître") or name.lower().startswith("maitre"):
        return name
    return f"Maître {name}"


def _resolve_lawyer(procuration: Procuration) -> tuple[str, str, str]:
    """Retourne (nom avocat, barreau, adresse cabinet)."""
    cabinet = procuration.cabinet
    bar = (cabinet.bar_association if cabinet else "") or ""
    address = _cabinet_address(cabinet)
    matter = procuration.matter
    lawyer = None
    if matter is not None:
        lawyer = matter.responsible_lawyer
        if lawyer is None:
            lead = (
                matter.assigned_lawyers.filter(is_lead=True)
                .select_related("lawyer")
                .first()
            )
            if lead is None:
                lead = matter.assigned_lawyers.select_related("lawyer").first()
            if lead is not None:
                lawyer = lead.lawyer
    return _lawyer_label(lawyer), bar, address


def _party_names(parties: list[Any], *, state: bool) -> str:
    names = [p.name.strip() for p in parties if bool(p.is_state_entity) is state and p.name.strip()]
    return ", ".join(names)


def _en_cause_contre(procuration: Procuration, parties: list[Any]) -> tuple[str, str]:
    state = _party_names(parties, state=True)
    others = _party_names(parties, state=False)
    en_cause = state or "La République Démocratique du Congo"
    if state and others:
        # Conservé si l'État est déjà nommé ; sinon « et consorts » reste possible.
        pass
    if state and "République" not in en_cause and "REPUBLIQUE" not in en_cause.upper():
        en_cause = f"{en_cause}"
    contre = others or (procuration.opposing_party or "—")
    return en_cause, contre


def _document_number(procuration: Procuration) -> str:
    if procuration.ministry_reference:
        return procuration.ministry_reference
    year = timezone.localdate().year
    return f"/CAB/ME/MIN/J&GS/{year}/{procuration.reference}"


def _purpose_text(procuration: Procuration) -> str:
    matter = procuration.matter
    jurisdiction = (
        (matter.jurisdiction if matter is not None else "")
        or procuration.jurisdiction
        or "la juridiction compétente"
    )
    case_ref = matter.reference if matter is not None else procuration.reference
    custom = (procuration.purpose or "").strip()
    if custom and custom.lower() not in {"représentation", "representation", "procuration"}:
        base = custom
        if "devant" not in custom.lower():
            base = f"{custom} devant {jurisdiction}"
        if case_ref and case_ref not in base:
            base = f"{base} dans l'affaire enrôlée sous {case_ref}"
        return base.rstrip(".") + "."
    return (
        "Représenter la République Démocratique du Congo et accomplir tous les actes "
        f"et formalités afférents à la défense de ses intérêts devant {jurisdiction} "
        f"dans l'affaire enrôlée sous {case_ref}."
    )


def _template_context(procuration: Procuration) -> dict[str, object]:
    cabinet = procuration.cabinet
    matter = procuration.matter
    parties: list[Any] = []
    if matter is not None:
        parties = list(matter.parties.all().order_by("role", "name"))
    lawyer_name, lawyer_bar, lawyer_address = _resolve_lawyer(procuration)
    en_cause, contre = _en_cause_contre(procuration, parties)
    granted_by = ""
    if procuration.granted_by_id:
        granted_by = procuration.granted_by.get_full_name() or procuration.granted_by.email
    printed = timezone.localtime()
    return {
        "procuration": procuration,
        "cabinet": cabinet,
        "matter": matter,
        "parties": parties,
        "document_number": _document_number(procuration),
        "minister_name": getattr(
            settings,
            "PROCURATION_MINISTER_NAME",
            "Monsieur Guillaume NGEFA ATONDOKO ANDALI",
        ),
        "minister_title": getattr(
            settings,
            "PROCURATION_MINISTER_TITLE",
            "Ministre d'État, Ministre de la Justice et Garde des Sceaux",
        ),
        "ministry_address": getattr(
            settings,
            "PROCURATION_MINISTRY_ADDRESS",
            "Kinshasa, Palais de Justice, Place de l'Indépendance, dans la Commune de la Gombe",
        ),
        "ordinance_appointment": getattr(
            settings,
            "PROCURATION_ORDINANCE_APPOINTMENT",
            "Ordonnance n°25/247 du 07 août 2025 portant nomination des Vice-Premiers "
            "Ministres, Ministres d'État, Ministres, Ministres Délégués et Vice-Ministres",
        ),
        "ordinance_attributions": getattr(
            settings,
            "PROCURATION_ORDINANCE_ATTRIBUTIONS",
            "Ordonnance n° 25/293 du 15 décembre 2025 fixant les attributions des "
            "Ministères, article 1er litera B point 12",
        ),
        "lawyer_name": lawyer_name,
        "lawyer_bar": lawyer_bar,
        "lawyer_address": lawyer_address or _cabinet_address(cabinet),
        "cabinet_address": _cabinet_address(cabinet),
        "purpose_text": _purpose_text(procuration),
        "en_cause": en_cause,
        "contre": contre,
        "granted_date": _format_date_long(procuration.granted_at or timezone.localdate()),
        "signatory_capacity": (
            "Pour le Ministre d'État, Ministre de la Justice et Garde des Sceaux"
        ),
        "signatory_name": granted_by,
        "signatory_title": "",
        "granted_by": granted_by,
        "printed_at": printed.strftime("%d/%m/%Y imp %H:%M:%S"),
        "country": getattr(settings, "SITE_COUNTRY", "République Démocratique du Congo"),
        "institution": getattr(
            settings, "SITE_INSTITUTION", "Ministère de la Justice et Garde des Sceaux"
        ),
    }


def _font_candidates() -> list[tuple[Path, Path]]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    base = Path(settings.BASE_DIR) / "static" / "fonts"
    return [
        (base / "SourceSans3-Regular.ttf", base / "SourceSans3-Bold.ttf"),
        (windir / "times.ttf", windir / "timesbd.ttf"),
        (windir / "arial.ttf", windir / "arialbd.ttf"),
        (windir / "calibri.ttf", windir / "calibrib.ttf"),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
        ),
    ]


def _build_with_fpdf(procuration: Procuration) -> bytes:
    from fpdf import FPDF

    ctx = _template_context(procuration)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(20, 22, 20)

    font_name = "Times"
    for regular, bold in _font_candidates():
        if regular.is_file():
            bold_path = bold if bold.is_file() else regular
            pdf.add_font("ProcSerif", "", str(regular))
            pdf.add_font("ProcSerif", "B", str(bold_path))
            font_name = "ProcSerif"
            break

    pdf.add_page()
    usable = 210 - 40

    def _center(text: str, *, size: float = 12, bold: bool = False) -> None:
        pdf.set_text_color(*INK)
        pdf.set_font(font_name, "B" if bold else "", size)
        pdf.multi_cell(usable, 6, text, align="C")

    def _para(text: str, *, bold_prefix: str = "") -> None:
        pdf.set_text_color(*INK)
        pdf.set_font(font_name, "", 11)
        if bold_prefix:
            # fpdf n'enchaîne pas facilement gras+normal : préfixe en gras puis suite.
            pdf.set_font(font_name, "B", 11)
            pdf.write(6, bold_prefix)
            pdf.set_font(font_name, "", 11)
            pdf.multi_cell(usable, 6, text)
        else:
            pdf.multi_cell(usable, 6, text)
        pdf.ln(3)

    _center("// PROCURATION //", size=13, bold=True)
    pdf.ln(1)
    _center(f"N° {ctx['document_number']}", size=11, bold=False)
    pdf.ln(2)
    y = pdf.get_y()
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.6)
    pdf.line(20, y, 190, y)
    pdf.line(20, y + 0.8, 190, y + 0.8)
    pdf.ln(8)

    preamble = (
        f"La REPUBLIQUE DEMOCRATIQUE DU CONGO, représentée par "
        f"le {ctx['minister_title']}, {ctx['minister_name']}, "
        f"nommé par {ctx['ordinance_appointment']}, "
        f"ayant son Cabinet sis à {ctx['ministry_address']}, "
        f"agissant en vertu de {ctx['ordinance_attributions']},"
    )
    _para(preamble)

    if ctx["lawyer_name"]:
        mandate = (
            f"donne par les présentes mandat à {ctx['lawyer_name']}"
            + (f", {ctx['lawyer_bar']}" if ctx["lawyer_bar"] else "")
            + (
                f", dont le Cabinet est établi {ctx['lawyer_address']},"
                if ctx["lawyer_address"]
                else ","
            )
            + " agissant conjointement ou séparément avec pouvoir de substitution."
        )
    elif ctx["cabinet"]:
        cab = ctx["cabinet"]
        mandate = (
            f"donne par les présentes mandat au cabinet {cab.name}"  # type: ignore[union-attr]
            + (f", {cab.bar_association}" if cab.bar_association else "")  # type: ignore[union-attr]
            + (
                f", dont le Cabinet est établi {ctx['cabinet_address']},"
                if ctx["cabinet_address"]
                else ","
            )
            + " agissant conjointement ou séparément avec pouvoir de substitution."
        )
    else:
        mandate = (
            "donne par les présentes mandat à l'avocat désigné, "
            "agissant conjointement ou séparément avec pouvoir de substitution."
        )
    _para(mandate)

    pdf.set_font(font_name, "B", 11)
    pdf.write(6, "Aux fins de : ")
    pdf.set_font(font_name, "", 11)
    pdf.multi_cell(usable, 6, str(ctx["purpose_text"]))
    pdf.ln(4)

    pdf.set_font(font_name, "B", 11)
    pdf.write(6, "En cause : ")
    pdf.set_font(font_name, "", 11)
    pdf.multi_cell(usable, 6, str(ctx["en_cause"]))
    pdf.ln(2)

    pdf.set_font(font_name, "B", 11)
    pdf.write(6, "Contre : ")
    pdf.set_font(font_name, "", 11)
    pdf.multi_cell(usable, 6, str(ctx["contre"]))
    pdf.ln(6)

    _para(f"Fait à Kinshasa, le {ctx['granted_date']}")

    pdf.ln(8)
    pdf.set_x(110)
    pdf.set_font(font_name, "", 10)
    pdf.multi_cell(70, 5, str(ctx["signatory_capacity"]), align="C")
    if ctx["signatory_name"]:
        pdf.ln(14)
        pdf.set_x(110)
        pdf.set_font(font_name, "B", 11)
        pdf.multi_cell(70, 6, str(ctx["signatory_name"]), align="C")
    if ctx["signatory_title"]:
        pdf.set_x(110)
        pdf.set_font(font_name, "", 10)
        pdf.multi_cell(70, 5, str(ctx["signatory_title"]), align="C")

    pdf.set_y(-28)
    pdf.set_text_color(*SLATE)
    pdf.set_font(font_name, "", 8)
    if ctx["granted_by"]:
        pdf.cell(usable, 4, str(ctx["granted_by"]), ln=1)
    pdf.cell(usable, 4, f"Le {ctx['printed_at']}", ln=1)
    pdf.cell(usable, 4, "Visa Dircaba", ln=1)

    raw = pdf.output()
    return bytes(raw) if not isinstance(raw, bytes) else raw
