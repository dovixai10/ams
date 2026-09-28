"""Integrations section - WhatsApp: accounts (sender credentials), recipients
(people / groups), report schedules, and the message log. One generic set of
list/create/edit/toggle/delete views serves the first three via `kind`."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .integration_forms import (
    WhatsAppAccountForm, WhatsAppGroupCreateForm, WhatsAppRecipientForm, WhatsAppReportScheduleForm,
    WhatsAppWebSessionForm,
)
from .integrations import services, web_client
from .integrations.attendance_report import SUGGESTED_TEMPLATE_TEXT
from .integrations.whatsapp_client import WhatsAppError, get_invite_link
from .models import (
    WhatsAppAccount, WhatsAppMessageLog, WhatsAppRecipient, WhatsAppReportSchedule, WhatsAppWebSession,
)
from .permissions import feature_required, get_request_branch, get_request_office, tenant_queryset

manage_required = user_passes_test(feature_required('integrations.manage'))


def _scope_text(obj):
    return f'{obj.branch.name} only' if obj.branch_id else 'Whole office'


def _account_row(a):
    return {
        'title': a.label,
        'subtitle': a.display_phone_number or f'ID {a.phone_number_id}',
        'cells': [
            _scope_text(a),
            'Token saved' if a.has_token else 'No token',
            a.api_version,
        ],
    }


def _recipient_row(r):
    cells = []
    if r.numbers:
        cells.append('Numbers: ' + ', '.join(r.numbers))
    if r.group_name_list:
        cells.append('Groups (QR): ' + ', '.join(r.group_name_list))
    if r.group_id_list:
        cells.append('Group IDs (API): ' + ', '.join(r.group_id_list))
    cells.append(_scope_text(r))
    return {
        'title': r.label,
        'subtitle': r.summary.capitalize(),
        'cells': cells,
        'links': [('Invite link', r.invite_link)] if r.invite_link else [],
        'can_fetch_link': len(r.group_id_list) == 1 and not r.group_id_list[0].endswith('@g.us') and not r.invite_link,
    }


_SESSION_STATE_TEXT = {
    'connected': 'Connected',
    'qr': 'Waiting for QR scan',
    'connecting': 'Connecting...',
    'closed': 'Not linked - QR expired',
    'not_started': 'Not linked yet',
    'logged_out': 'Logged out from the phone',
    'helper_offline': 'Helper service offline',
}


def _session_row(sess):
    state = getattr(sess, 'live_state', 'not_started')
    phone = f' +{sess.phone_number}' if sess.phone_number and state == 'connected' else ''
    return {
        'title': sess.label,
        'subtitle': f'+{sess.phone_number}' if sess.phone_number else 'Not linked yet',
        'cells': [f'{_SESSION_STATE_TEXT.get(state, state)}{phone}', _scope_text(sess)],
        'state': state,
    }


def _schedule_row(s):
    recipient_names = ', '.join(r.label for r in s.recipients.all()) or 'No recipients'
    last = f'{s.last_run_date:%d %b}' if s.last_run_date else 'Never'
    return {
        'title': s.name,
        'subtitle': f'{s.send_time:%I:%M %p} · {s.days_display}',
        'cells': [
            f'Covers: {s.branch.name}' if s.branch_id else 'Covers: whole office',
            f'To: {recipient_names}',
            'Via linked phone (QR)' if s.channel == 'web' else 'Via Business API',
            'Plain text' if (s.channel == 'web' or s.message_mode != 'template') else 'Template',
            f'Last run: {last}',
        ],
    }


KINDS = {
    'accounts': {
        'model': WhatsAppAccount, 'form': WhatsAppAccountForm, 'row': _account_row,
        'label': 'API Account', 'label_plural': 'Business API Accounts', 'icon': 'bx-phone-call',
        'blurb': 'Method A - the official WhatsApp Business API. The Business number messages are sent from; give the whole office one, and let any branch have its own.',
        'order': ('label',),
    },
    'recipients': {
        'model': WhatsAppRecipient, 'form': WhatsAppRecipientForm, 'row': _recipient_row,
        'label': 'Recipient', 'label_plural': 'Recipients', 'icon': 'bx-user-voice',
        'blurb': 'Named lists of who gets a report - each entry can hold several numbers and several groups.',
        'order': ('label',),
    },
    'sessions': {
        'model': WhatsAppWebSession, 'form': WhatsAppWebSessionForm, 'row': _session_row,
        'label': 'Linked Phone', 'label_plural': 'Linked Phones', 'icon': 'bx-qr-scan',
        'blurb': 'Method B - link a phone by scanning a QR code (like WhatsApp Web) to send from that number, to any contact or to any group it is in, by name.',
        'order': ('label',),
    },
    'schedules': {
        'model': WhatsAppReportSchedule, 'form': WhatsAppReportScheduleForm, 'row': _schedule_row,
        'label': 'Report Schedule', 'label_plural': 'Report Schedules', 'icon': 'bx-time-five',
        'blurb': 'Attendance reports sent automatically at a set time on chosen days - or sent right now.',
        'order': ('send_time', 'name'),
    },
}


def _config(kind):
    config = KINDS.get(kind)
    if config is None:
        raise Http404(f'Unknown WhatsApp setting "{kind}".')
    return config


def _json_safe(value):
    if isinstance(value, (datetime.time, datetime.datetime, datetime.date)):
        return value.strftime('%H:%M') if isinstance(value, datetime.time) else value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return '' if value is None else value


def _edit_values(form):
    """Field values of a bound-to-instance form, in a shape the page's edit
    panel can drop straight into its inputs. The access token is never included."""
    values = {}
    for name in form.fields:
        if name == 'access_token':
            continue
        values[name] = _json_safe(form[name].value())
    return values


def _errors_text(form):
    parts = []
    for name, errors in form.errors.items():
        label = form.fields[name].label if name in form.fields else 'Form'
        parts.append(f"{label or name}: {' '.join(errors)}")
    return '; '.join(parts)


@login_required
@manage_required
def whatsapp_home(request):
    """Setup overview: the two sending methods side by side, and what to do next."""
    accounts = tenant_queryset(request, WhatsAppAccount.objects.filter(is_active=True))
    api_active = sum(1 for a in accounts if a.has_token)
    sessions = list(tenant_queryset(request, WhatsAppWebSession.objects.filter(is_active=True)))
    _attach_live_state(sessions)
    states = {s.live_state for s in sessions}
    connected = sum(1 for s in sessions if s.live_state == 'connected')

    if connected:
        qr_status = 'ready'
    elif 'helper_offline' in states:
        qr_status = 'offline'
    elif sessions:
        qr_status = 'needs_scan'
    else:
        qr_status = 'not_set_up'

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'kind': 'home',
        'api_status': 'ready' if api_active else 'not_set_up',
        'api_active': api_active,
        'qr_status': qr_status,
        'qr_connected': connected,
        'recipient_count': tenant_queryset(request, WhatsAppRecipient.objects.all()).count(),
        'schedule_count': tenant_queryset(request, WhatsAppReportSchedule.objects.all()).count(),
    })
    return render(request, 'employees/integrations/whatsapp_overview.html', context)


def _warn_if_channel_unconnected(request, schedule):
    """A schedule can be saved before its sending method is set up - but say so."""
    office = get_request_office(request)
    if schedule.channel == 'web':
        missing = WhatsAppWebSession.resolve(office, schedule.branch) is None
        where, page = 'linked phone', 'Linked Phone (QR)'
    else:
        missing = WhatsAppAccount.resolve(office, schedule.branch) is None
        where, page = 'Business API account', 'Business API'
    if missing:
        messages.warning(
            request,
            f'Saved - but no active {where} is set up for this schedule yet, so it can\'t send until you add one under "{page}".',
        )


@login_required
@manage_required
def whatsapp_manage(request, kind):
    """List + create page for accounts / recipients / schedules."""
    config = _config(kind)
    model, form_cls = config['model'], config['form']

    if request.method == 'POST':
        form = form_cls(request.POST, request=request)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.office = get_request_office(request)
            obj.created_by = request.user
            obj.save()
            form.save_m2m()
            messages.success(request, f'{config["label"]} created.')
            if kind == 'schedules':
                _warn_if_channel_unconnected(request, obj)
            if kind == 'sessions':
                return redirect('employees:whatsapp_web_link', pk=obj.pk)
            return redirect('employees:whatsapp_manage', kind=kind)
        messages.error(request, _errors_text(form) or 'Please correct the errors below.')
    else:
        form = form_cls(request=request)

    queryset = tenant_queryset(request, model.objects.all()).order_by(*config['order'])
    if kind == 'schedules':
        queryset = queryset.prefetch_related('recipients').select_related('branch')
    elif kind in ('accounts', 'recipients', 'sessions'):
        queryset = queryset.select_related('branch')

    objects = list(queryset)
    if kind == 'sessions':
        _attach_live_state(objects)

    rows, edit_data = [], {}
    for obj in objects:
        row = config['row'](obj)
        row['obj'] = obj
        rows.append(row)
        edit_data[str(obj.pk)] = {
            'url': _update_url(kind, obj.pk),
            'title': row['title'],
            'values': _edit_values(form_cls(instance=obj, request=request)),
        }

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'kind': kind,
        'config': config,
        'rows': rows,
        'edit_data': edit_data,
        'suggested_template_text': SUGGESTED_TEMPLATE_TEXT,
        'form_has_errors': bool(form.is_bound and form.errors),
        'group_form': WhatsAppGroupCreateForm(request=request) if kind == 'recipients' else None,
    })
    return render(request, 'employees/integrations/whatsapp_manage.html', context)


def _attach_live_state(sessions):
    """Ask the helper what each linked phone is doing right now (one quick call
    each). If the helper isn't running, say so instead of failing the page."""
    helper_up = True
    for sess in sessions:
        if not helper_up:
            sess.live_state = 'helper_offline'
            continue
        try:
            info = web_client.status(sess.pk)
        except WhatsAppError:
            helper_up = False
            sess.live_state = 'helper_offline'
            continue
        sess.live_state = info.get('status', 'not_started')
        _remember_phone(sess, info)


def _remember_phone(sess, info):
    if info.get('status') == 'connected' and info.get('phone') and info['phone'] != sess.phone_number:
        sess.phone_number = info['phone']
        sess.save(update_fields=['phone_number', 'updated_at'])


def _update_url(kind, pk):
    from django.urls import reverse
    return reverse('employees:whatsapp_update', kwargs={'kind': kind, 'pk': pk})


def _get_object(request, kind, pk):
    config = _config(kind)
    obj = get_object_or_404(tenant_queryset(request, config['model'].objects.all()), pk=pk)
    return config, obj


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_update(request, kind, pk):
    config, obj = _get_object(request, kind, pk)
    form = config['form'](request.POST, instance=obj, request=request)
    if form.is_valid():
        saved = form.save()
        messages.success(request, f'{config["label"]} updated.')
        if kind == 'schedules':
            _warn_if_channel_unconnected(request, saved)
    else:
        messages.error(request, f'Could not update - {_errors_text(form)}')
    return redirect('employees:whatsapp_manage', kind=kind)


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_toggle(request, kind, pk):
    config, obj = _get_object(request, kind, pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'{config["label"]} {"activated" if obj.is_active else "deactivated"}.')
    return redirect('employees:whatsapp_manage', kind=kind)


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_delete(request, kind, pk):
    config, obj = _get_object(request, kind, pk)
    extra = ''
    if kind == 'sessions':
        try:
            web_client.logout(obj.pk)
        except WhatsAppError:
            extra = ' The helper service was not running, so also remove this device under "Linked devices" on the phone.'
    obj.delete()
    messages.success(request, f'{config["label"]} deleted.{extra}')
    return redirect('employees:whatsapp_manage', kind=kind)


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_schedule_send_now(request, pk):
    """Send a schedule's report immediately, to its recipients, without waiting
    for (or affecting) its normal time."""
    schedule = get_object_or_404(tenant_queryset(request, WhatsAppReportSchedule.objects.all()), pk=pk)
    logs = services.run_schedule(schedule.pk, triggered_by='manual')
    skipped = [log for log in logs if log.status == 'skipped']
    failed = [log for log in logs if log.status == 'failed']
    if skipped:
        messages.warning(request, f'Nothing was sent: {skipped[0].error}')
    elif failed:
        messages.error(request, failed[0].error)
    else:
        messages.success(request, f'Report queued for {len(logs)} recipient(s). Check the Message Log for delivery status.')
    return redirect('employees:whatsapp_manage', kind='schedules')


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_recipient_test(request, pk):
    """Send Meta's built-in hello_world template to a recipient to check that
    the account credentials and this number/group actually work."""
    recipient = get_object_or_404(tenant_queryset(request, WhatsAppRecipient.objects.all()), pk=pk)
    channel = 'web' if request.POST.get('channel') == 'web' else 'api'
    logs = services.send_test_message(recipient, channel=channel)
    failed = [log for log in logs if log.status == 'failed']
    sent = [log for log in logs if log.status == 'sent']
    if failed:
        messages.error(request, f'Test failed for {len(failed)} of {len(logs)}: {failed[0].to_address} - {failed[0].error}')
    elif len(sent) == len(logs):
        messages.success(request, f'Test message sent to {len(sent)} place(s) in {recipient.label}.')
    else:
        messages.info(request, f'Test message queued for {len(logs)} place(s) in {recipient.label} - check the Message Log.')
    return redirect('employees:whatsapp_manage', kind='recipients')


@login_required
@manage_required
def whatsapp_logs(request):
    status = request.GET.get('status', '').strip()
    logs = tenant_queryset(request, WhatsAppMessageLog.objects.all()).select_related('schedule', 'recipient')
    if status in dict(WhatsAppMessageLog.Status.choices):
        logs = logs.filter(status=status)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'kind': 'logs',
        'logs': logs.order_by('-created_at')[:200],
        'status_filter': status,
        'status_choices': WhatsAppMessageLog.Status.choices,
    })
    return render(request, 'employees/integrations/whatsapp_logs.html', context)


# ---------------------------------------------------------------- Business API groups ----

@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_group_create(request):
    """Create a WhatsApp group through Meta's Groups API and save it as a group
    recipient, showing its ID and invite link."""
    back = redirect('employees:whatsapp_manage', kind='recipients')
    form = WhatsAppGroupCreateForm(request.POST, request=request)
    if not form.is_valid():
        messages.error(request, f'Could not create the group - {_errors_text(form)}')
        return back

    office, branch = get_request_office(request), form.resolved_branch()
    account = WhatsAppAccount.resolve(office, branch)
    if account is None:
        messages.error(request, 'Add a WhatsApp Business account first (Integrations - Accounts) - groups are created from that number.')
        return back

    subject = form.cleaned_data['subject'].strip()
    try:
        group_id, invite_link = services.create_api_group(
            account, subject, form.cleaned_data['description'].strip(), form.cleaned_data['join_approval_mode'],
        )
    except WhatsAppError as exc:
        messages.error(request, f'Could not create the group: {exc}')
        return back

    WhatsAppRecipient.objects.create(
        office=office, branch=branch, label=subject[:100],
        group_ids=group_id, invite_link=invite_link, created_by=request.user,
    )
    link_text = invite_link or 'not available yet - use "Get invite link" on the group\'s row'
    messages.success(request, f'Group "{subject}" created. Group ID: {group_id}. Invite link: {link_text}')
    return back


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_group_sync(request):
    """Bring the Business API account's existing groups in as recipients."""
    back = redirect('employees:whatsapp_manage', kind='recipients')
    office = get_request_office(request)
    account = WhatsAppAccount.resolve(office, get_request_branch(request))
    if account is None:
        messages.error(request, 'Add a WhatsApp Business account first (Integrations - Accounts).')
        return back
    try:
        added = services.sync_api_groups(account, office, account.branch, request.user)
    except WhatsAppError as exc:
        messages.error(request, f'Could not read the groups from Meta: {exc}')
        return back
    if added:
        messages.success(request, f'Imported {len(added)} group(s): {", ".join(r.label for r in added)}.')
    else:
        messages.info(request, 'No new groups - everything Meta has for this number is already in your recipients.')
    return back


@login_required
@manage_required
@require_http_methods(['POST'])
def whatsapp_group_invite_link(request, pk):
    """Fetch (or re-fetch) a Business API group's invite link and save it."""
    recipient = get_object_or_404(tenant_queryset(request, WhatsAppRecipient.objects.all()), pk=pk)
    back = redirect('employees:whatsapp_manage', kind='recipients')
    ids = recipient.group_id_list
    if len(ids) != 1 or ids[0].endswith('@g.us'):
        messages.error(request, 'An invite link can be fetched for an entry that has exactly one Business API group ID.')
        return back
    account = WhatsAppAccount.resolve(recipient.office, recipient.branch)
    if account is None:
        messages.error(request, 'No active WhatsApp Business account for this scope.')
        return back
    try:
        recipient.invite_link = get_invite_link(account, ids[0])
    except WhatsAppError as exc:
        messages.error(request, f'Could not get the invite link: {exc}')
        return back
    recipient.save(update_fields=['invite_link', 'updated_at'])
    messages.success(request, f'Invite link for "{recipient.label}": {recipient.invite_link}')
    return back


# ---------------------------------------------------------------- Linked phones (QR) ----

def _get_session(request, pk):
    return get_object_or_404(tenant_queryset(request, WhatsAppWebSession.objects.all()), pk=pk)


@login_required
@manage_required
def whatsapp_web_link(request, pk):
    """The page where a phone is linked: shows the QR code and its live status."""
    sess = _get_session(request, pk)
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'kind': 'sessions',
        'session': sess,
    })
    return render(request, 'employees/integrations/whatsapp_web_link.html', context)


@login_required
@manage_required
@require_http_methods(['GET', 'POST'])
def whatsapp_web_api(request, pk, action):
    """JSON used by the link page: status (with QR as SVG), start, logout, groups."""
    sess = _get_session(request, pk)
    try:
        if action == 'status' and request.method == 'GET':
            info = web_client.status(sess.pk)
            _remember_phone(sess, info)
            info['qr_svg'] = web_client.qr_svg(info['qr']) if info.get('qr') else ''
            info.pop('qr', None)
            return JsonResponse(info)
        if action == 'start' and request.method == 'POST':
            info = web_client.start(sess.pk)
            info.pop('qr', None)
            return JsonResponse(info)
        if action == 'logout' and request.method == 'POST':
            web_client.logout(sess.pk)
            sess.phone_number = ''
            sess.save(update_fields=['phone_number', 'updated_at'])
            return JsonResponse({'status': 'logged_out'})
        if action == 'groups' and request.method == 'GET':
            return JsonResponse({'groups': web_client.groups(sess.pk, refresh=request.GET.get('refresh') == '1')})
    except WhatsAppError as exc:
        offline = 'helper' in str(exc).lower() and exc.transient
        return JsonResponse({'status': 'helper_offline' if offline else 'error', 'error': str(exc)}, status=200 if offline else 400)
    raise Http404('Unknown action')
