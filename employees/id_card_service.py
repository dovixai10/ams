"""Single data source for employee ID cards — preview, portal, and export."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Optional

from django.template.loader import render_to_string


def _abs_media_url(request, url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith(('http://', 'https://', 'data:')):
        return url
    if request:
        return request.build_absolute_uri(url)
    return url


@dataclass
class IDCardContext:
    employee_name: str
    employee_code: str
    designation: str
    date_of_joining: str
    contact: str
    company_name: str
    company_name_accent: str
    company_address: str
    company_phone: str
    company_website: str
    logo_url: Optional[str]
    photo_url: Optional[str]
    maps_url: str
    website_url: str
    verify_payload: str
    qr_verify_data_uri: str
    qr_maps_data_uri: str
    qr_website_data_uri: str
    blood_group: str
    emergency_contact: str
    emergency_relation: str
    residential_address: str
    validity_label: str
    flip_enabled: bool = True

    @property
    def visible_rows_front(self):
        rows = [
            ('Employee Code', self.employee_code, 'bx-id-card'),
            ('Designation', self.designation, 'bx-briefcase'),
            ('D.O.J.', self.date_of_joining, 'bx-calendar'),
            ('Contact No.', self.contact, 'bx-phone'),
        ]
        return [(label, val, icon) for label, val, icon in rows if val]

    @property
    def visible_rows_back(self):
        rows = [
            ('Address', self.company_address, 'bx-map'),
            ('Phone', self.company_phone, 'bx-phone-call'),
            ('Website', self.company_website, 'bx-globe'),
            ('Blood group', self.blood_group, 'bx-droplet'),
            ('Emergency', self.emergency_contact, 'bx-first-aid'),
            ('Relation', self.emergency_relation, 'bx-user'),
            ('Residence', self.residential_address, 'bx-home'),
            ('Valid until', self.validity_label, 'bx-time'),
        ]
        return [(label, val, icon) for label, val, icon in rows if val]


def _qr_data_uri(payload: str) -> str:
    if not payload:
        return ''
    try:
        import qrcode
    except ImportError:
        return ''
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#0f172a', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def build_id_card_context(employee, id_card=None, request=None) -> IDCardContext:
    from employees.models import EmployeeIDCard

    office = employee.office
    if id_card is None:
        id_card = EmployeeIDCard.objects.filter(employee=employee).first()

    employee_code = ''
    designation = ''
    doj = None
    photo_url = None

    if id_card:
        employee_code = id_card.employee_id_number or ''
        designation = id_card.job_position or ''
        doj = id_card.date_of_joining
        if id_card.employee_photo:
            photo_url = id_card.employee_photo.url
    if not employee_code:
        employee_code = f'EMP{employee.pk:05d}'
    if not designation:
        designation = getattr(employee, 'designation', '') or ''
    if not doj:
        doj = employee.joining_date or (employee.created_at.date() if employee.created_at else None)
    if not photo_url and getattr(employee, 'profile_picture', None):
        try:
            photo_url = employee.profile_picture.url
        except Exception:
            photo_url = None

    company_name = office.name if office else ''
    parts = company_name.split(None, 1)
    company_primary = parts[0] if parts else company_name
    company_accent = parts[1] if len(parts) > 1 else ''

    company_address = office.address if office else ''
    company_phone = office.contact_number if office else ''
    company_website = office.website if office else ''

    logo_url = None
    if office and office.logo:
        try:
            logo_url = office.logo.url
        except Exception:
            logo_url = None

    maps_url = ''
    if office and office.latitude is not None and office.longitude is not None:
        maps_url = f'https://www.google.com/maps?q={office.latitude},{office.longitude}'

    website_url = company_website or ''
    verify_payload = '|'.join([
        f'NAME:{employee.full_name}',
        f'ROLE:{designation}',
        f'ID:{employee_code}',
        f'DOJ:{doj.isoformat() if doj else ""}',
        f'COMPANY:{company_name}',
    ])

    blood_group = getattr(employee, 'blood_group', '') or ''
    emergency_contact = getattr(employee, 'emergency_contact_name', '') or ''
    emergency_relation = getattr(employee, 'emergency_contact_relation', '') or ''
    residential_address = employee.current_address or employee.permanent_address or ''
    validity_label = ''

    return IDCardContext(
        employee_name=employee.full_name or employee.name,
        employee_code=employee_code,
        designation=designation,
        date_of_joining=doj.strftime('%d %b %Y') if doj else '',
        contact=employee.contact or '',
        company_name=company_primary,
        company_name_accent=company_accent,
        company_address=company_address,
        company_phone=company_phone,
        company_website=company_website,
        logo_url=_abs_media_url(request, logo_url),
        photo_url=_abs_media_url(request, photo_url),
        maps_url=maps_url,
        website_url=website_url,
        verify_payload=verify_payload,
        qr_verify_data_uri=_qr_data_uri(verify_payload),
        qr_maps_data_uri=_qr_data_uri(maps_url),
        qr_website_data_uri=_qr_data_uri(website_url),
        blood_group=blood_group,
        emergency_contact=emergency_contact,
        emergency_relation=emergency_relation,
        residential_address=residential_address,
        validity_label=validity_label,
    )


def render_id_card_preview_html(card: IDCardContext, request=None, flipped: bool = False) -> str:
    return render_to_string(
        'employees/id_card/_unified_card.html',
        {'card': card, 'flipped': flipped},
        request=request,
    )


def render_id_card_pdf(card: IDCardContext, request=None) -> io.BytesIO:
    """Render print-ready CR80 portrait PDF from the same HTML export template."""
    html = render_to_string(
        'employees/id_card/_id_card_export.html',
        {'card': card},
        request=request,
    )
    buffer = io.BytesIO()
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError('xhtml2pdf is required for ID card PDF export.') from exc

    base_url = request.build_absolute_uri('/') if request else None
    result = pisa.CreatePDF(html, dest=buffer, encoding='utf-8', link_callback=None)
    if result.err:
        raise RuntimeError('Failed to generate ID card PDF.')
    buffer.seek(0)
    return buffer


def ensure_id_card_record(employee, employee_code=None, job_position=None, joining_date=None):
    """Create or update EmployeeIDCard from employee data."""
    from employees.models import EmployeeIDCard

    code = employee_code or f'EMP{employee.pk:05d}'
    doj = joining_date or employee.joining_date or (
        employee.created_at.date() if employee.created_at else None
    )
    designation = job_position or getattr(employee, 'designation', '') or 'Employee'
    photo = getattr(employee, 'profile_picture', None)

    defaults = {
        'employee_id_number': code,
        'job_position': designation,
        'date_of_joining': doj,
    }
    if photo:
        defaults['employee_photo'] = photo

    return EmployeeIDCard.objects.update_or_create(employee=employee, defaults=defaults)[0]

