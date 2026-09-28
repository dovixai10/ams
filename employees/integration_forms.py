"""Forms for the Integrations section (WhatsApp accounts, recipients, report
schedules). Every form has a `scope` choice - whole office, or only the branch
the admin is currently working in - so office-wide vs branch-specific setup is
an explicit decision rather than something silently stamped on save."""
import re

from django import forms
from django.utils import timezone

from types import SimpleNamespace

from .integrations.targets import normalise_numbers, split_list
from .models import WhatsAppAccount, WhatsAppRecipient, WhatsAppReportSchedule, WhatsAppWebSession
from .permissions import get_request_branch, get_request_office, tenant_queryset

SCOPE_OFFICE = 'office'
SCOPE_BRANCH = 'branch'


class ScopeFieldMixin:
    """Adds a `scope` field and resolves it to a branch (or None = office-wide)."""

    scope_label = 'Applies to'

    def _init_scope(self, request):
        self.request = request
        active_branch = get_request_branch(request) if request else None
        choices = [(SCOPE_OFFICE, 'Whole office (all branches)')]
        if active_branch is not None:
            choices.append((SCOPE_BRANCH, f'Only {active_branch.name}'))
        self.fields['scope'] = forms.ChoiceField(
            choices=choices, label=self.scope_label,
            widget=forms.Select(attrs={'class': 'form-control'}),
        )
        self.fields['scope'].initial = SCOPE_BRANCH if (self.instance.pk and self.instance.branch_id) else SCOPE_OFFICE
        self.order_fields(['label', 'name', 'scope'])

    def _resolved_branch(self):
        if self.cleaned_data.get('scope') != SCOPE_BRANCH:
            return None
        # Editing something already tied to a branch keeps that branch rather
        # than silently moving it to whichever branch the admin is viewing.
        if self.instance.pk and self.instance.branch_id:
            return self.instance.branch
        return get_request_branch(self.request)


class WhatsAppAccountForm(ScopeFieldMixin, forms.ModelForm):
    scope_label = 'Used by'

    access_token = forms.CharField(
        required=False, label='Access token',
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text='From Meta (System User permanent token). Stored encrypted and never shown again - leave blank when editing to keep the saved one.',
    )

    class Meta:
        model = WhatsAppAccount
        fields = ['label', 'phone_number_id', 'display_phone_number', 'api_version', 'is_active']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. HR alerts number'}),
            'phone_number_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 123456789012345'}),
            'display_phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional, e.g. +91 98765 43210'}),
            'api_version': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_scope(request)

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not (cleaned.get('access_token') or '').strip():
            self.add_error('access_token', 'An access token is required for a new account.')
        office = get_request_office(self.request) if self.request else None
        if office is not None and 'scope' in cleaned:
            clash = WhatsAppAccount.objects.filter(office=office, branch=self._resolved_branch())
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error('scope', 'There is already a WhatsApp account for this scope - edit that one instead.')
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.branch = self._resolved_branch()
        token = (self.cleaned_data.get('access_token') or '').strip()
        if token:
            obj.set_access_token(token)
        if commit:
            obj.save()
        return obj


class WhatsAppWebSessionForm(ScopeFieldMixin, forms.ModelForm):
    """A phone that will be linked by scanning a QR code. Saving only creates the
    entry - the QR code is shown by the "Link phone" button on its row."""
    scope_label = 'Used by'

    class Meta:
        model = WhatsAppWebSession
        fields = ['label', 'is_active']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "e.g. HR manager's phone"}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_scope(request)

    def clean(self):
        cleaned = super().clean()
        office = get_request_office(self.request) if self.request else None
        if office is not None and 'scope' in cleaned:
            clash = WhatsAppWebSession.objects.filter(office=office, branch=self._resolved_branch())
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error('scope', 'There is already a linked phone for this scope - use that one, or remove it first.')
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.branch = self._resolved_branch()
        if commit:
            obj.save()
        return obj


class WhatsAppRecipientForm(ScopeFieldMixin, forms.ModelForm):
    """One entry = one named list: any mix of numbers and groups."""
    scope_label = 'Available to'

    class Meta:
        model = WhatsAppRecipient
        fields = ['label', 'phone_numbers', 'group_names', 'group_ids', 'is_active']
        labels = {
            'phone_numbers': 'Phone numbers',
            'group_names': 'Group names (linked phone / QR)',
            'group_ids': 'Group IDs (Business API)',
        }
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "e.g. HR team"}),
            'phone_numbers': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': '919876543210, 919812345678'}),
            'group_names': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ops Team, Managers'}),
            'group_ids': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Only for the Business API'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'phone_numbers': 'With country code, separated by commas. Works with both sending methods.',
            'group_names': 'Exactly as the group is named on the linked phone, separated by commas.',
            'group_ids': "Only needed for the Business API - use 'Create WhatsApp group' to get one.",
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_scope(request)
        self.order_fields(['label', 'scope', 'phone_numbers', 'group_names', 'group_ids', 'is_active'])

    def clean_phone_numbers(self):
        numbers, invalid = normalise_numbers(self.cleaned_data.get('phone_numbers'))
        if invalid:
            raise forms.ValidationError(
                f"Not a valid number: {', '.join(invalid)}. Use the full number with country code, e.g. 919876543210."
            )
        return ', '.join(numbers)

    def clean_group_names(self):
        return ', '.join(split_list(self.cleaned_data.get('group_names')))

    def clean_group_ids(self):
        return ', '.join(split_list(self.cleaned_data.get('group_ids')))

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.branch = self._resolved_branch()
        # Only a single-group entry can carry the invite link of that group.
        if len(obj.group_id_list) != 1:
            obj.invite_link = ''
        if commit:
            obj.save()
        return obj


DAY_CHOICES = [(0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri'), (5, 'Sat'), (6, 'Sun')]


class WhatsAppReportScheduleForm(ScopeFieldMixin, forms.ModelForm):
    scope_label = 'Report covers'

    days = forms.MultipleChoiceField(
        choices=DAY_CHOICES, widget=forms.CheckboxSelectMultiple, label='Send on',
        initial=[0, 1, 2, 3, 4, 5],
    )

    class Meta:
        model = WhatsAppReportSchedule
        fields = [
            'name', 'channel', 'report_type', 'send_time', 'skip_holidays', 'message_mode',
            'template_name', 'template_language', 'recipients', 'is_active',
        ]
        labels = {'channel': 'Send through', 'recipients': 'Send to'}
        help_texts = {
            'channel': 'Business API needs an account under "Business API"; Linked phone needs a scanned phone under "Linked Phone (QR)". Set up either one, or both.',
        }
        widgets = {
            'channel': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Morning attendance 10:30'}),
            'report_type': forms.Select(attrs={'class': 'form-control'}),
            'send_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'skip_holidays': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'message_mode': forms.Select(attrs={'class': 'form-control'}),
            'template_name': forms.TextInput(attrs={'class': 'form-control'}),
            'template_language': forms.TextInput(attrs={'class': 'form-control'}),
            'recipients': forms.CheckboxSelectMultiple(),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_scope(request)
        self.fields['days'].initial = self.instance.weekdays if self.instance.pk else [0, 1, 2, 3, 4, 5]
        self.fields['recipients'].queryset = (
            tenant_queryset(request, WhatsAppRecipient.objects.filter(is_active=True)) if request
            else WhatsAppRecipient.objects.none()
        ).order_by('label')
        self.fields['recipients'].required = False
        self.fields['recipients'].label = 'Send to'
        self.fields['template_name'].required = False
        self.fields['template_language'].required = False
        self.fields['channel'].required = False  # an older open page may not send it; default is the Business API
        self.order_fields([
            'name', 'scope', 'channel', 'report_type', 'send_time', 'days', 'skip_holidays', 'recipients',
            'message_mode', 'template_name', 'template_language', 'is_active',
        ])

    def clean_channel(self):
        return self.cleaned_data.get('channel') or WhatsAppReportSchedule.Channel.API

    def clean_days(self):
        days = self.cleaned_data.get('days') or []
        if not days:
            raise forms.ValidationError('Pick at least one day.')
        return sorted({int(d) for d in days})

    def clean(self):
        cleaned = super().clean()
        uses_template = (
            cleaned.get('channel') == WhatsAppReportSchedule.Channel.API
            and cleaned.get('message_mode') == WhatsAppReportSchedule.MessageMode.TEMPLATE
        )
        if uses_template and not (cleaned.get('template_name') or '').strip():
            self.add_error('template_name', 'Enter the approved template name (or switch to plain text).')
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.branch = self._resolved_branch()
        obj.days_of_week = ','.join(str(d) for d in self.cleaned_data['days'])
        obj.template_name = (self.cleaned_data.get('template_name') or '').strip()
        obj.template_language = (self.cleaned_data.get('template_language') or 'en').strip()

        # Don't fire immediately for a time that has already passed today: a new
        # 10:30 schedule saved at 11:00 should first run tomorrow. Moving the
        # time to later today (or re-activating) re-arms it for today.
        now = timezone.localtime()
        is_new = obj.pk is None
        if is_new:
            if obj.send_time <= now.time():
                obj.last_run_date = now.date()
        elif 'send_time' in self.changed_data or 'is_active' in self.changed_data:
            obj.last_run_date = None if obj.send_time > now.time() else now.date()

        if commit:
            obj.save()
            self.save_m2m()
        return obj


class WhatsAppGroupCreateForm(ScopeFieldMixin, forms.Form):
    """Creates a new WhatsApp group through the Business API (Groups API)."""
    scope_label = 'Available to'

    subject = forms.CharField(
        max_length=128, label='Group name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Ops team reports'}),
    )
    description = forms.CharField(
        max_length=2048, required=False, label='Description',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )
    join_approval_mode = forms.ChoiceField(
        choices=[('auto_approve', 'Anyone with the link joins straight away'), ('approval_required', 'Admin approves each join request')],
        label='Joining', widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.instance = SimpleNamespace(pk=None, branch_id=None, branch=None)  # what ScopeFieldMixin expects
        super().__init__(*args, **kwargs)
        self._init_scope(request)
        self.order_fields(['subject', 'scope', 'description', 'join_approval_mode'])

    def resolved_branch(self):
        return self._resolved_branch()
