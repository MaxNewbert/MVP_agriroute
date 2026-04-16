"""
AgriRoute - Completion Report Generator
Generates professional PDF application/operation reports for growers.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime
import io

GREEN_DARK  = colors.HexColor("#1B4332")
GREEN_MID   = colors.HexColor("#2D6A4F")
GREEN_LIGHT = colors.HexColor("#D8F3DC")
GREY_LIGHT  = colors.HexColor("#F4F4F4")
GREY_MID    = colors.HexColor("#CCCCCC")
TEXT_DARK   = colors.HexColor("#1A1A2E")
AMBER       = colors.HexColor("#E9A800")
RED_WARN    = colors.HexColor("#C1121F")
BLUE_LINK   = colors.HexColor("#1565C0")


def generate_completion_report(report_data: dict) -> bytes:
    """
    Generate a PDF completion report.

    report_data keys:
      contractor_name, contractor_address, cert_number,
      grower_name, grower_address,
      farm_name, field_name, field_ha, crop_type, variety, bbch_stage,
      operation_type, operation_date, start_time, finish_time,
      operator_name, equipment, gps_system,
      products: [{name, mapp_no, rate, unit, total_used}],
      application: {nozzle, pressure_bar, forward_speed_kph, water_vol_lha},
      weather: {wind_ms, wind_mph, wind_dir, temp_c, humidity_pct, rainfall_mm},
      weather_warnings: [str],
      buffer_zones: [{feature, distance_m, required_m, compliant}],
      justification: {type, detail, link, advisor_name, advisor_email, advice_date},
      notes: str,
    """
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=15*mm, rightMargin=15*mm,
                              topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story  = []

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_sty = sty("T",  fontSize=18, textColor=GREEN_DARK, leading=22,
                     spaceAfter=2, fontName="Helvetica-Bold")
    sub_sty   = sty("S",  fontSize=10, textColor=GREEN_MID, leading=13, spaceAfter=8)
    h2_sty    = sty("H2", fontSize=11, textColor=colors.white,
                     fontName="Helvetica-Bold", leading=14)
    body_sty  = sty("B",  fontSize=9,  leading=13, textColor=TEXT_DARK)
    warn_sty  = sty("W",  fontSize=9,  leading=13, textColor=RED_WARN,
                     fontName="Helvetica-Bold")
    ok_sty    = sty("OK", fontSize=9,  leading=13, textColor=GREEN_MID,
                     fontName="Helvetica-Bold")
    link_sty  = sty("L",  fontSize=9,  leading=13, textColor=BLUE_LINK)
    small_sty = sty("SM", fontSize=8,  leading=11, textColor=colors.grey)

    def section_header(text):
        t = Table([[Paragraph(text, h2_sty)]], colWidths=[180*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN_MID),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        return t

    def kv_table(rows, col_w=(65*mm, 115*mm)):
        data = [[Paragraph(f"<b>{k}</b>", body_sty), Paragraph(str(v or ""), body_sty)]
                for k, v in rows]
        t = Table(data, colWidths=list(col_w))
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [GREY_LIGHT, colors.white]),
            ("LINEBELOW",      (0, 0), (-1, -1), 0.3, GREY_MID),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ]))
        return t

    # ── Header ────────────────────────────────────────────────────────────────
    op_date = report_data.get("operation_date", datetime.now().strftime("%d/%m/%Y"))
    story.append(Paragraph("AgriRoute", title_sty))
    story.append(Paragraph(
        f"Field Operation Completion Report — "
        f"{report_data.get('operation_type', 'Operation')} | {op_date}", sub_sty))
    story.append(HRFlowable(width="100%", thickness=2, color=GREEN_DARK, spaceAfter=6))

    # Contractor / Grower
    c_rows = [
        ["<b>Contractor</b>",            "<b>Grower / Client</b>"],
        [report_data.get("contractor_name", ""),  report_data.get("grower_name", "")],
        [report_data.get("contractor_address", ""), report_data.get("grower_address", "")],
        [f"Cert No: {report_data.get('cert_number', '')}", ""],
    ]
    c_paras = [[Paragraph(str(c or ""), body_sty) for c in row] for row in c_rows]
    hdr_tbl = Table(c_paras, colWidths=[90*mm, 90*mm])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), GREEN_LIGHT),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.5, GREEN_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BOX",           (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story += [hdr_tbl, Spacer(1, 6*mm)]

    # ── Field & Operation Details ─────────────────────────────────────────────
    story.append(section_header("Field & Operation Details"))
    story.append(Spacer(1, 2*mm))
    story.append(kv_table([
        ("Farm",           report_data.get("farm_name", "")),
        ("Field",          report_data.get("field_name", "")),
        ("Area (ha)",      report_data.get("field_ha", "")),
        ("Crop",           report_data.get("crop_type", "")),
        ("Variety",        report_data.get("variety", "")),
        ("BBCH Stage",     report_data.get("bbch_stage", "")),
        ("Operation",      report_data.get("operation_type", "")),
        ("Date",           op_date),
        ("Start / Finish", f"{report_data.get('start_time', '')} – {report_data.get('finish_time', '')}"),
        ("Operator",       report_data.get("operator_name", "")),
        ("Equipment",      report_data.get("equipment", "")),
        ("GPS System",     report_data.get("gps_system", "")),
    ]))
    story.append(Spacer(1, 4*mm))

    # ── Justification for Operation ───────────────────────────────────────────
    just = report_data.get("justification", {})
    if just and just.get("type"):
        story.append(section_header("Justification for Operation"))
        story.append(Spacer(1, 2*mm))
        jtype = just.get("type", "")
        detail = just.get("detail", "")
        link   = just.get("link", "")
        adv_name  = just.get("advisor_name", "")
        adv_email = just.get("advisor_email", "")
        adv_date  = just.get("advice_date", "")

        rows = [("Basis for Application", jtype)]
        if detail:
            rows.append(("Detail", detail))
        if link:
            rows.append(("Reference / Link", link))
        if adv_name:
            rows.append(("Advisor", adv_name))
        if adv_email:
            rows.append(("Advisor Email", adv_email))
        if adv_date:
            rows.append(("Date of Advice", adv_date))
        story.append(kv_table(rows))
        story.append(Spacer(1, 4*mm))

    # ── Products Applied ──────────────────────────────────────────────────────
    products = report_data.get("products", [])
    if products:
        story.append(section_header("Products Applied"))
        story.append(Spacer(1, 2*mm))
        headers = ["Product", "MAPP No.", "Rate", "Unit", "Total Used"]
        rows = [headers] + [
            [p.get("name", ""), p.get("mapp_no", ""),
             str(p.get("rate", "")), p.get("unit", "L/ha"), str(p.get("total_used", ""))]
            for p in products
        ]
        paras = [[Paragraph(str(c), body_sty) for c in row] for row in rows]
        pt = Table(paras, colWidths=[60*mm, 28*mm, 25*mm, 25*mm, 30*mm])
        pt.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), GREEN_MID),
            ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
            ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [GREY_LIGHT, colors.white]),
            ("LINEBELOW",      (0, 0), (-1, -1), 0.3, GREY_MID),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
            ("BOX",            (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        story += [pt, Spacer(1, 4*mm)]

    # ── Application Settings ──────────────────────────────────────────────────
    app_set = report_data.get("application", {})
    if app_set:
        story.append(section_header("Application Settings"))
        story.append(Spacer(1, 2*mm))
        story.append(kv_table([
            ("Nozzle Type",   app_set.get("nozzle", "")),
            ("Pressure (bar)", app_set.get("pressure_bar", "")),
            ("Forward Speed",  f"{app_set.get('forward_speed_kph', '')} km/h"),
            ("Water Volume",   f"{app_set.get('water_vol_lha', '')} L/ha"),
        ]))
        story.append(Spacer(1, 4*mm))

    # ── Weather During Operation ──────────────────────────────────────────────
    wx = report_data.get("weather", {})
    if wx:
        story.append(section_header("Weather During Operation"))
        story.append(Spacer(1, 2*mm))
        story.append(kv_table([
            ("Wind Speed",     f"{wx.get('wind_ms', '')} m/s  ({wx.get('wind_mph', '')} mph)"),
            ("Wind Direction", wx.get("wind_dir", "")),
            ("Temperature",    f"{wx.get('temp_c', '')} °C"),
            ("Humidity",       f"{wx.get('humidity_pct', '')} %"),
            ("Rainfall",       f"{wx.get('rainfall_mm', '')} mm"),
        ]))
        for w in report_data.get("weather_warnings", []):
            story.append(Paragraph(w, warn_sty))
        story.append(Spacer(1, 4*mm))

    # ── Buffer Zone Compliance ────────────────────────────────────────────────
    buffers = report_data.get("buffer_zones", [])
    if buffers:
        story.append(section_header("Buffer Zone Compliance"))
        story.append(Spacer(1, 2*mm))
        headers = ["Feature", "Distance Maintained (m)", "Required (m)", "Status"]
        rows = [headers] + [
            [b.get("feature", ""), str(b.get("distance_m", "")),
             str(b.get("required_m", "")),
             "✓ Compliant" if b.get("compliant", True) else "✗ NON-COMPLIANT"]
            for b in buffers
        ]
        buf_paras = []
        for i, row in enumerate(rows):
            p_row = []
            for j, c in enumerate(row):
                if i > 0 and j == 3:
                    s = ok_sty if buffers[i-1].get("compliant", True) else warn_sty
                else:
                    s = body_sty
                p_row.append(Paragraph(str(c), s))
            buf_paras.append(p_row)
        bt = Table(buf_paras, colWidths=[65*mm, 45*mm, 35*mm, 35*mm])
        bt.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), GREEN_MID),
            ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
            ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [GREY_LIGHT, colors.white]),
            ("LINEBELOW",      (0, 0), (-1, -1), 0.3, GREY_MID),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
            ("BOX",            (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        story += [bt, Spacer(1, 4*mm)]

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = report_data.get("notes", "")
    if notes:
        story.append(section_header("Additional Notes"))
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(notes, body_sty))
        story.append(Spacer(1, 4*mm))

    # ── Signature Block ───────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=GREY_MID, spaceBefore=6))
    sig_data = [
        [Paragraph("<b>Operator Signature</b>", body_sty),
         Paragraph("<b>Date</b>", body_sty),
         Paragraph("<b>Grower Signature</b>", body_sty),
         Paragraph("<b>Date</b>", body_sty)],
        ["", "", "", ""],
        [Paragraph("_______________________", body_sty),
         Paragraph("____________", body_sty),
         Paragraph("_______________________", body_sty),
         Paragraph("____________", body_sty)],
    ]
    sig_tbl = Table(sig_data, colWidths=[55*mm, 35*mm, 55*mm, 35*mm])
    sig_tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_tbl)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        f"Generated by AgriRoute | {datetime.now().strftime('%d/%m/%Y %H:%M')} | Confidential",
        small_sty))

    doc.build(story)
    return buf.getvalue()
