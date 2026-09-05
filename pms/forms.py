from django import forms
from django.contrib.auth.models import User

from employees.models import Employee

from .models import (
    EmployeeSkill,
    EmployeeWorkStatus,
    ResourceAllocation,
    Role,
    Skill,
    UserGroup,
)
from .permission_catalog import PROFICIENCY_CHOICES


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ['name', 'description']


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ['name', 'category', 'description']


class EmployeeSkillForm(forms.ModelForm):
    class Meta:
        model = EmployeeSkill
        fields = ['employee', 'skill', 'proficiency', 'years_experience', 'last_used', 'certification', 'cert_expires']
        widgets = {
            'last_used': forms.DateInput(attrs={'type': 'date'}),
            'cert_expires': forms.DateInput(attrs={'type': 'date'}),
        }


class UserGroupForm(forms.ModelForm):
    member_ids = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
    )

    class Meta:
        model = UserGroup
        fields = ['name', 'group_type', 'description']

    def __init__(self, *args, user_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user_qs is not None:
            self.fields['member_ids'].queryset = user_qs
        if self.instance.pk:
            self.fields['member_ids'].initial = self.instance.members.values_list('user_id', flat=True)


class WorkStatusForm(forms.ModelForm):
    class Meta:
        model = EmployeeWorkStatus
        fields = ['status', 'reason', 'effective_date']
        widgets = {'effective_date': forms.DateInput(attrs={'type': 'date'})}


class AllocationForm(forms.ModelForm):
    class Meta:
        model = ResourceAllocation
        fields = ['employee', 'label', 'allocation_percent', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, employee_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if employee_qs is not None:
            self.fields['employee'].queryset = employee_qs


class UserRoleAssignForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}))
    role = forms.ModelChoiceField(queryset=Role.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, user_qs=None, role_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user_qs is not None:
            self.fields['user'].queryset = user_qs
        if role_qs is not None:
            self.fields['role'].queryset = role_qs
