"""Single source of truth for the employee ID card design.

Used by all three surfaces that touch an ID card - the admin "ID'S Studio"
live preview, its PDF download, and the employee portal's own card page -
so all three always render the exact same front/back design from the exact
same dynamic office/branch data, instead of three different hand-built
designs drifting apart.

Front QR encodes the employee's own details. Back QR encodes the company's
website. Both are real, scannable QR codes generated with the `qrcode`
library - never a placeholder graphic.
"""
import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M

# Brand gradient - same blue/indigo family as the rest of the app's
# primary token (#696cff), just leaning bluer to match the reference design.
BRAND_BLUE = '#2563eb'
BRAND_INDIGO = '#4f46e5'


def get_company_details(office, branch=None):
    """Resolve the dynamic company name/address/phone/website/logo for an
    ID card. Prefers the branch's own details (per the office/branch
    convention used everywhere else in the app); falls back to the
    office's when the branch doesn't have its own address/phone set."""
    if office is None:
        return {'name': 'Company', 'address': '', 'phone': '', 'website': '', 'logo_url': None}

    address = ''
    phone = ''
    if branch is not None:
        parts = [branch.address, branch.city, branch.state, branch.pincode]
        address = ', '.join(p for p in parts if p)
        phone = branch.contact_number or ''
    if not address:
        address = office.address or ''
    if not phone:
        phone = office.contact_number or ''

    return {
        'name': office.name or 'Company',
        'address': address,
        'phone': phone,
        'website': office.website or '',
        'logo_url': office.logo.url if office.logo else None,
        'logo_path': office.logo.path if office.logo else None,
    }


def get_employee_card_fields(employee, employee_code=None, designation=None, joining_date=None):
    """Resolve the dynamic per-employee fields. Explicit overrides (as
    typed into the admin generator, or stored on a saved EmployeeIDCard)
    win; everything else is derived live from the Employee record."""
    resolved_joining = joining_date or employee.joining_date or (
        employee.created_at.date() if employee.created_at else None
    )
    return {
        'name': employee.full_name or employee.name,
        'code': employee_code or f"KI{employee.id:05d}",
        'designation': designation or (employee.designation.name if employee.designation else None) or 'Employee',
        'joining_date': resolved_joining,
        'contact': employee.contact or '',
        'photo_path': employee.profile_picture.path if employee.profile_picture else None,
        'photo_url': employee.profile_picture.url if employee.profile_picture else None,
    }


def build_front_qr_payload(fields):
    """Front QR content: the employee's own details."""
    lines = [
        f"Name: {fields['name']}",
        f"Employee Code: {fields['code']}",
        f"Designation: {fields['designation']}",
    ]
    if fields['joining_date']:
        lines.append(f"D.O.J.: {fields['joining_date'].strftime('%d %b %Y')}")
    if fields['contact']:
        lines.append(f"Contact: {fields['contact']}")
    return '\n'.join(lines)


def build_back_qr_payload(company):
    """Back QR content: the company's website (falls back to its name if
    no website is on file, so the QR is never empty)."""
    return company['website'] or company['name']


def make_qr_image(data):
    """Real, scannable QR code as a PIL Image - never a placeholder."""
    qr = qrcode.QRCode(version=1, box_size=10, border=2, error_correction=ERROR_CORRECT_M)
    qr.add_data(data or ' ')
    qr.make(fit=True)
    return qr.make_image(fill_color='#111827', back_color='white').convert('RGB')


def make_qr_png_bytes(data):
    img = make_qr_image(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def make_qr_data_uri(data):
    return 'data:image/png;base64,' + base64.b64encode(make_qr_png_bytes(data)).decode()


def build_id_card_context(employee, office=None, branch=None, employee_code=None,
                           designation=None, joining_date=None):
    """Everything a template or the PDF builder needs to render one
    employee's card - the single call site every surface should use."""
    office = office or employee.office
    branch = branch or employee.branch
    company = get_company_details(office, branch)
    fields = get_employee_card_fields(employee, employee_code, designation, joining_date)

    front_qr = build_front_qr_payload(fields)
    back_qr = build_back_qr_payload(company)

    return {
        'employee': fields,
        'company': company,
        'front_qr_data_uri': make_qr_data_uri(front_qr),
        'back_qr_data_uri': make_qr_data_uri(back_qr),
        'front_qr_payload': front_qr,
        'back_qr_payload': back_qr,
    }


def build_id_card_pdf(employee, office=None, branch=None, employee_code=None,
                       designation=None, joining_date=None):
    """Draws the two-page (front/back) PORTRAIT badge PDF (54mm x 85.6mm -
    a CR80 card held vertically, matching the reference design) and returns
    an in-memory BytesIO buffer. Both pages carry real, scannable QR codes."""
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    ctx = build_id_card_context(employee, office, branch, employee_code, designation, joining_date)
    fields = ctx['employee']
    company = ctx['company']

    CARD_W, CARD_H = 54 * mm, 85.6 * mm
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_W, CARD_H))

    blue = HexColor(BRAND_BLUE)
    indigo = HexColor(BRAND_INDIGO)
    ink = HexColor('#111827')
    muted = HexColor('#6b7280')

    # ---------------- FRONT ----------------
    # Laid out with a single top-down cursor (distance from the top edge)
    # so the fixed budget below is easy to verify against CARD_H at a glance.
    c.setFillColor(white)
    c.rect(0, 0, CARD_W, CARD_H, fill=1, stroke=0)
    _draw_blob(c, -8 * mm, CARD_H - 6 * mm, 20 * mm, blue, alpha=0.16)
    _draw_blob(c, CARD_W + 6 * mm, 8 * mm, 18 * mm, indigo, alpha=0.14)

    cursor = 8 * mm  # distance from top edge
    c.setFillColor(ink)
    c.setFont('Helvetica-Bold', 12)
    _draw_wrapped_title(c, company['name'], 4 * mm, CARD_H - cursor, 12, max_chars=18, line_gap=4.2 * mm)

    cursor += 5 * mm
    photo_r = 10 * mm
    photo_cx = CARD_W / 2
    photo_cy = CARD_H - cursor - photo_r
    c.saveState()
    p = c.beginPath()
    p.circle(photo_cx, photo_cy, photo_r)
    c.clipPath(p, stroke=0, fill=0)
    try:
        if fields['photo_path']:
            img = ImageReader(fields['photo_path'])
            c.drawImage(img, photo_cx - photo_r, photo_cy - photo_r,
                        width=photo_r * 2, height=photo_r * 2,
                        preserveAspectRatio=True, mask='auto')
        else:
            raise ValueError('no photo')
    except Exception:
        c.setFillColor(HexColor('#e0e7ff'))
        c.rect(photo_cx - photo_r, photo_cy - photo_r, photo_r * 2, photo_r * 2, fill=1, stroke=0)
        c.setFillColor(blue)
        c.setFont('Helvetica-Bold', 14)
        c.drawCentredString(photo_cx, photo_cy - 4, (fields['name'] or '?')[0].upper())
    c.restoreState()
    c.setStrokeColor(blue)
    c.setLineWidth(1.1)
    c.circle(photo_cx, photo_cy, photo_r, fill=0, stroke=1)
    cursor += photo_r * 2

    cursor += 5 * mm
    c.setFillColor(ink)
    c.setFont('Helvetica-Bold', 11)
    c.drawCentredString(CARD_W / 2, CARD_H - cursor, fields['name'])

    cursor += 4 * mm
    c.setFillColor(muted)
    c.setFont('Helvetica', 7.5)
    c.drawCentredString(CARD_W / 2, CARD_H - cursor, 'Employee')

    cursor += 5.5 * mm
    detail_rows = [
        ('Employee Code', fields['code']),
        ('Designation', fields['designation']),
        ('D.O.J.', fields['joining_date'].strftime('%d %b %Y') if fields['joining_date'] else '-'),
        ('Contact No.', fields['contact'] or '-'),
    ]
    label_font_size = 6.5
    label_x = 4 * mm
    # Measure the widest label so the value column starts just past it -
    # a fixed guess here is what let "Employee Code" collide with its own
    # value before. Card is only 54mm wide, so this has to be exact.
    max_label_w = max(stringWidth(label, 'Helvetica', label_font_size) for label, _ in detail_rows)
    value_x = label_x + max_label_w + 2.5 * mm
    value_max_w = CARD_W - value_x - 3 * mm

    for label, value in detail_rows:
        c.setFillColor(muted)
        c.setFont('Helvetica', label_font_size)
        c.drawString(label_x, CARD_H - cursor, label)
        c.setFillColor(blue)
        c.setFont('Helvetica-Bold', label_font_size)
        c.drawString(value_x, CARD_H - cursor, _fit_text_to_width(str(value), 'Helvetica-Bold', label_font_size, value_max_w))
        cursor += 4.6 * mm

    cursor += 2 * mm
    qr_size = 13 * mm
    qr_x = CARD_W / 2 - qr_size / 2
    front_qr_img = ImageReader(io.BytesIO(make_qr_png_bytes(ctx['front_qr_payload'])))
    c.drawImage(front_qr_img, qr_x, CARD_H - cursor - qr_size, width=qr_size, height=qr_size)
    cursor += qr_size

    cursor += 3.5 * mm
    c.setFillColor(ink)
    c.setFont('Helvetica-Bold', 6.5)
    c.drawCentredString(CARD_W / 2, CARD_H - cursor, 'Scan for Details')

    c.showPage()

    # ---------------- BACK ----------------
    # Colored band across the top ~38% (with a skyline motif), white for
    # the rest - same wave-transition language as the front's blob accents.
    # Everything below the band is laid out against a hard bottom margin so
    # a long address can never run off the card - see _fit_lines below.
    c.setPageSize((CARD_W, CARD_H))
    band_h = CARD_H * 0.38
    c.setFillColor(white)
    c.rect(0, 0, CARD_W, CARD_H, fill=1, stroke=0)
    _draw_gradient_bg(c, CARD_W, band_h, indigo, blue, y_offset=CARD_H - band_h)
    _draw_skyline(c, CARD_W, band_h, y_offset=CARD_H - band_h)
    _draw_wave_edge(c, CARD_W, CARD_H - band_h, blue)

    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 12)
    _draw_wrapped_title(c, company['name'], 4 * mm, CARD_H - 8 * mm, 12, color=white, max_chars=18, line_gap=4.2 * mm)

    qr_size = 16 * mm
    qr_x = CARD_W / 2 - qr_size / 2
    qr_y = CARD_H - band_h - qr_size - 5 * mm
    c.setFillColor(white)
    c.roundRect(qr_x - 1.5 * mm, qr_y - 1.5 * mm, qr_size + 3 * mm, qr_size + 3 * mm, 1.5, fill=1, stroke=0)
    c.setStrokeColor(HexColor('#e5e7eb'))
    c.setLineWidth(0.5)
    c.roundRect(qr_x - 1.5 * mm, qr_y - 1.5 * mm, qr_size + 3 * mm, qr_size + 3 * mm, 1.5, fill=0, stroke=1)
    back_qr_img = ImageReader(io.BytesIO(make_qr_png_bytes(ctx['back_qr_payload'])))
    c.drawImage(back_qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

    c.setFillColor(ink)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawCentredString(CARD_W / 2, qr_y - 4.5 * mm, 'Scan for Website')

    # Reserve fixed-height slots for phone/website at a hard bottom margin,
    # then give the address whatever room is left above them - truncating
    # (never overflowing) if it's longer than that room allows.
    # Address, phone and website are drawn as one flowing block (address
    # line(s), then phone, then website, each immediately below the last)
    # instead of anchoring the address to the top and phone/website to a
    # fixed spot near the bottom - which left a large gap between them
    # whenever the address was short (e.g. just "Jaipur").
    bottom_margin = 3 * mm
    line_h = 3.0 * mm
    block_top = qr_y - 4.5 * mm - 5 * mm
    available_h = block_top - bottom_margin
    max_total_lines = max(0, int(available_h / line_h))

    address_lines = []
    if company['address'] and max_total_lines:
        lines_for_address = max(0, max_total_lines - (1 if company['phone'] else 0) - (1 if company['website'] else 0))
        address_lines = _fit_lines(company['address'], width=27, max_lines=lines_for_address)

    footer_max_w = CARD_W - 8 * mm
    cursor_y = block_top
    c.setFillColor(ink)

    if address_lines:
        text_obj = c.beginText(4 * mm, cursor_y)
        text_obj.setFont('Helvetica', 6.8)
        text_obj.setLeading(line_h)
        text_obj.setFillColor(ink)
        for line in address_lines:
            text_obj.textLine(line)
        c.drawText(text_obj)
        cursor_y -= line_h * len(address_lines)

    c.setFont('Helvetica', 6.8)
    c.setFillColor(ink)
    if company['phone']:
        c.drawString(4 * mm, cursor_y, _fit_text_to_width(company['phone'], 'Helvetica', 6.8, footer_max_w))
        cursor_y -= line_h
    if company['website']:
        c.drawString(4 * mm, cursor_y, _fit_text_to_width(company['website'], 'Helvetica', 6.8, footer_max_w))

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def _draw_wrapped_title(c, text, x, top_y, font_size, color=None, max_chars=16, line_gap=None):
    """Draws a company name that may need to wrap to a second line (long
    names), top-anchored at (x, top_y)."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm

    if color is not None:
        c.setFillColor(color)
    lines = _wrap_text(text, max_chars)[:2]
    gap = line_gap or (font_size + 1)
    for i, line in enumerate(lines):
        c.drawString(x, top_y - i * gap, line)


def _wrap_text(text, width):
    import textwrap
    return textwrap.wrap(text, width=width) or ['']


def _fit_text_to_width(text, font_name, font_size, max_width):
    """Truncates text (with an ellipsis) so it never exceeds max_width when
    drawn in the given font - measured exactly via stringWidth rather than
    guessing a character count, since the card is only 54mm wide."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = '…'
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ellipsis
        if stringWidth(candidate, font_name, font_size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ellipsis if lo else ellipsis


def _fit_lines(text, width, max_lines):
    """Wraps text and hard-caps it to max_lines, marking the last shown
    line with an ellipsis when it had to cut something - so a long
    company address can never run past its reserved space on the card."""
    lines = _wrap_text(text, width)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    last = kept[-1]
    if len(last) > width - 1:
        last = last[:width - 1].rstrip()
    kept[-1] = last + '…'
    return kept


def _draw_gradient_bg(c, width, height, color_top, color_bottom, steps=40, y_offset=0):
    """Simulates a vertical gradient by stacking thin colored bands
    (reportlab canvas has no native linear gradient fill), drawn as a
    `height`-tall band starting at `y_offset` from the page bottom."""
    from reportlab.lib.colors import Color

    for i in range(steps):
        frac = i / float(steps - 1)
        r = color_top.red + (color_bottom.red - color_top.red) * frac
        g = color_top.green + (color_bottom.green - color_top.green) * frac
        b = color_top.blue + (color_bottom.blue - color_top.blue) * frac
        c.setFillColor(Color(r, g, b))
        band_h = height / steps
        c.rect(0, y_offset + height - (i + 1) * band_h, width, band_h + 0.5, fill=1, stroke=0)


def _draw_blob(c, cx, cy, r, color, alpha=0.15):
    """A soft translucent circle, used for the front's decorative swoosh
    accents (echoing the reference design's blue blob shapes)."""
    from reportlab.lib.colors import Color

    c.saveState()
    c.setFillColor(Color(color.red, color.green, color.blue, alpha=alpha))
    c.circle(cx, cy, r, fill=1, stroke=0)
    c.restoreState()


def _draw_skyline(c, width, height, y_offset=0):
    """A simple abstract skyline silhouette across a `height`-tall band
    starting at `y_offset`, echoing the reference design's building photo
    without needing a raster asset - stays fully vector/theme-colored."""
    from reportlab.lib.colors import Color

    c.saveState()
    c.setFillColor(Color(1, 1, 1, alpha=0.14))
    bands = [0.55, 0.75, 0.6, 0.9, 0.65, 0.8, 0.5, 0.7]
    band_w = width / len(bands)
    for i, h_frac in enumerate(bands):
        band_h = height * h_frac
        c.rect(i * band_w, y_offset + height - band_h, band_w * 0.9, band_h, fill=1, stroke=0)
    c.restoreState()


def _draw_wave_edge(c, width, white_zone_height, color):
    """A soft curved accent at the top of the white lower zone, so the
    gradient-to-white transition on the back face echoes the front's
    blob/wave motif instead of a hard straight line."""
    from reportlab.lib.colors import Color

    c.saveState()
    c.setFillColor(Color(color.red, color.green, color.blue, alpha=0.10))
    c.circle(width * 0.5, white_zone_height, width * 0.9, fill=1, stroke=0)
    c.restoreState()
