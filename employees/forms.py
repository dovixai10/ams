from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Employee,
    LeaveRequest,
    LoanRequest,
    ReimbursementRequest,
    Task,
    TaskUpdate,
    AssetAssignment,
    LeaveType,
)
from django.utils import timezone


class EmployeeForm(forms.ModelForm):
    """Form for creating new employees"""

    # Additional fields for user creation
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        }),
        min_length=8,
        help_text="Password for the employee's login account (minimum 8 characters)"
    )
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        }),
        help_text="Confirm the password"
    )

    class Meta:
        model = Employee
        fields = [
            'full_name', 'email', 'contact',
            'aadhar_card_number', 'account_number', 'ifsc_code', 'pan_card',
            'current_address', 'permanent_address',
            'relative_name', 'relative_contact', 'relation_with_employee',
            'educational_qualifications',
            'aadhar_document', 'pan_document', 'bank_passbook_document',
            'joining_date', 'shift'
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address'
            }),
            'contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter contact number'
            }),
            'aadhar_card_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter 12-digit Aadhar number'
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter bank account number'
            }),
            'ifsc_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter IFSC code'
            }),
            'pan_card': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter PAN card number'
            }),
            'educational_qualifications': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'aadhar_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'pan_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'bank_passbook_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'joining_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'placeholder': 'Select joining date'
            }),
            'shift': forms.Select(attrs={
                'class': 'form-control',
            }),
        }
        labels = {
            'joining_date': 'Date of Joining',
        }
        help_texts = {
            'full_name': 'Employee\'s complete name',
            'email': 'Email address (will be used as username)',
            'contact': 'Contact phone number',
            'aadhar_card_number': '12-digit Aadhar card number',
            'account_number': 'Bank account number (9-18 digits)',
            'ifsc_code': '11-character IFSC code',
            'pan_card': '10-character PAN card number (e.g., ABCDE1234F)',
            'current_address': 'Current residential address',
            'permanent_address': 'Permanent residential address',
            'relative_name': 'Name of a relative for emergency contact',
            'relative_contact': 'Contact number of the relative',
            'relation_with_employee': 'Relationship with the employee',
            'educational_qualifications': 'Upload educational certificates (PDF or image)',
            'aadhar_document': 'Upload Aadhar (PDF or image)',
            'pan_document': 'Upload PAN (PDF or image)',
            'bank_passbook_document': 'Upload bank passbook or cancelled cheque (PDF or image)',
            'joining_date': 'Employee\'s joining date (used for paid leave calculation)',
            'shift': 'Select the shift allocated to this employee',
        }

    def clean_email(self):
        """Validate email uniqueness"""
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with this email already exists.')
        return email

    def clean_password(self):
        """Validate password strength"""
        password = self.cleaned_data.get('password')

        if password:
            if len(password) < 8:
                raise forms.ValidationError('Password must be at least 8 characters long.')

            # Check for at least one number and one letter
            if not any(char.isdigit() for char in password):
                raise forms.ValidationError('Password must contain at least one number.')

            if not any(char.isalpha() for char in password):
                raise forms.ValidationError('Password must contain at least one letter.')

        return password

    def clean_confirm_password(self):
        """Validate password confirmation"""
        password = self.cleaned_data.get('password')
        confirm_password = self.cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError('Passwords do not match.')

        return confirm_password

    def clean_aadhar_card_number(self):
        """Validate Aadhar number format"""
        aadhar = self.cleaned_data.get('aadhar_card_number')
        if len(aadhar) != 12 or not aadhar.isdigit():
            raise forms.ValidationError('Aadhar number must be exactly 12 digits.')
        return aadhar

    def clean_pan_card(self):
        """Validate PAN card format"""
        pan = self.cleaned_data.get('pan_card').upper()
        if len(pan) != 10:
            raise forms.ValidationError('PAN card number must be exactly 10 characters.')

        # PAN format: 5 letters, 4 numbers, 1 letter
        if not (pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()):
            raise forms.ValidationError('Invalid PAN card format. Should be ABCDE1234F.')

        return pan

    def clean_ifsc_code(self):
        """Validate IFSC code format"""
        ifsc = self.cleaned_data.get('ifsc_code').upper()
        if len(ifsc) != 11:
            raise forms.ValidationError('IFSC code must be exactly 11 characters.')

        # IFSC format: 4 letters, 0, 6 alphanumeric
        if not (ifsc[:4].isalpha() and ifsc[4] == '0' and ifsc[5:].isalnum()):
            raise forms.ValidationError('Invalid IFSC code format.')

        return ifsc

    def save(self, commit=True):
        """Persist the employee while keeping the legacy name field synchronised."""
        employee = super().save(commit=False)
        if employee.full_name:
            employee.name = employee.full_name

        if commit:
            employee.save()
            self.save_m2m()

        return employee


class EmployeeDocumentForm(forms.ModelForm):
    """Form for employees to manage their uploaded documents."""

    class Meta:
        model = Employee
        fields = ['educational_qualifications', 'aadhar_document', 'pan_document', 'bank_passbook_document']
        widgets = {
            'educational_qualifications': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'aadhar_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'pan_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'bank_passbook_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class EmployeeUpdateForm(forms.ModelForm):
    """Form for updating existing employees"""

    class Meta:
        model = Employee
        fields = [
            'full_name', 'email', 'contact',
            'aadhar_card_number', 'account_number', 'ifsc_code', 'pan_card',
            'current_address', 'permanent_address',
            'relative_name', 'relative_contact', 'relation_with_employee',
            'educational_qualifications',
            'aadhar_document', 'pan_document', 'bank_passbook_document',
            'joining_date', 'shift'
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address'
            }),
            'contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter contact number'
            }),
            'aadhar_card_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter 12-digit Aadhar number'
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter bank account number'
            }),
            'ifsc_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter IFSC code'
            }),
            'pan_card': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter PAN card number'
            }),
            'educational_qualifications': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'aadhar_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'pan_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'bank_passbook_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'joining_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'placeholder': 'Select joining date'
            }),
            'shift': forms.Select(attrs={
                'class': 'form-control',
            }),
        }
        labels = {
            'joining_date': 'Date of Joining',
        }
        help_texts = {
            'full_name': 'Employee\'s complete name',
            'email': 'Email address (will be used as username)',
            'contact': 'Contact phone number',
            'aadhar_card_number': '12-digit Aadhar card number',
            'account_number': 'Bank account number (9-18 digits)',
            'ifsc_code': '11-character IFSC code',
            'pan_card': '10-character PAN card number (e.g., ABCDE1234F)',
            'current_address': 'Current residential address',
            'permanent_address': 'Permanent residential address',
            'relative_name': 'Name of a relative for emergency contact',
            'relative_contact': 'Contact number of the relative',
            'relation_with_employee': 'Relationship with the employee',
            'educational_qualifications': 'Mention highest education, degrees, and institutes',
            'aadhar_document': 'Upload Aadhar (PDF or image)',
            'pan_document': 'Upload PAN (PDF or image)',
            'bank_passbook_document': 'Upload bank passbook or cancelled cheque (PDF or image)',
            'joining_date': 'Employee\'s joining date (used for paid leave calculation)',
            'shift': 'Select the shift allocated to this employee',
        }

    def clean_email(self):
        """Validate email uniqueness (excluding current user)"""
        email = self.cleaned_data.get('email')
        employee = self.instance

        # Check if email is different from current
        if employee.user.email != email:
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError('A user with this email already exists.')

        return email

    def clean_aadhar_card_number(self):
        """Validate Aadhar number format"""
        aadhar = self.cleaned_data.get('aadhar_card_number')
        if len(aadhar) != 12 or not aadhar.isdigit():
            raise forms.ValidationError('Aadhar number must be exactly 12 digits.')
        return aadhar

    def clean_pan_card(self):
        """Validate PAN card format"""
        pan = self.cleaned_data.get('pan_card').upper()
        if len(pan) != 10:
            raise forms.ValidationError('PAN card number must be exactly 10 characters.')

        # PAN format: 5 letters, 4 numbers, 1 letter
        if not (pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()):
            raise forms.ValidationError('Invalid PAN card format. Should be ABCDE1234F.')

        return pan

    def clean_ifsc_code(self):
        """Validate IFSC code format"""
        ifsc = self.cleaned_data.get('ifsc_code').upper()
        if len(ifsc) != 11:
            raise forms.ValidationError('IFSC code must be exactly 11 characters.')

        # IFSC format: 4 letters, 0, 6 alphanumeric
        if not (ifsc[:4].isalpha() and ifsc[4] == '0' and ifsc[5:].isalnum()):
            raise forms.ValidationError('Invalid IFSC code format.')

        return ifsc


class EmployeePasswordResetForm(PasswordResetForm):
    """Customize password reset form used on employee login flow."""

    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                'autocomplete': 'email',
                'placeholder': 'you@example.com',
                'class': 'am-input',
            }
        ),
        label='Email address',
    )

class SuperAdminProfileForm(forms.ModelForm):
    """Form for superadmin profile management"""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter first name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address'
            }),
        }
        help_texts = {
            'first_name': 'Your first name',
            'last_name': 'Your last name',
            'email': 'Your email address (used for login)',
        }

    def clean_email(self):
        """Validate email uniqueness (excluding current user)"""
        email = self.cleaned_data.get('email')
        user = self.instance

        # Check if email is different from current
        if user.email != email:
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError('A user with this email already exists.')

        return email

class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = [
            'name', 'code', 'description', 'category',
            'accrual_frequency', 'accrual_amount',
            'annual_limit', 'max_balance_cap',
            'allow_carry_forward', 'carry_forward_cap',
            'min_service_days_required', 'applicable_gender',
            'requires_document', 'max_consecutive_days',
            'is_active', 'display_order',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Earned Leave'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. EL'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'accrual_frequency': forms.Select(attrs={'class': 'form-select'}),
            'accrual_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
            'annual_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
            'max_balance_cap': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
            'allow_carry_forward': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'carry_forward_cap': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
            'min_service_days_required': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'applicable_gender': forms.Select(attrs={'class': 'form-select'}),
            'requires_document': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_consecutive_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

# class LeaveRequestForm(forms.ModelForm):
#     """Form for employees to request leave with validation for date ranges."""

#     leave_type = forms.ChoiceField(
#         choices=LeaveRequest.LeaveType.choices,
#         widget=forms.RadioSelect(attrs={'class': 'leave-type-radio'}),
#         initial=LeaveRequest.LeaveType.FULL_DAY,
#         required=True,
#         label='Leave Type'
#     )
    
#     # RULE A: Employee must select only one option → "Paid Leave (PL)" OR "Leave Without Pay (LWP)"
#     leave_category = forms.ChoiceField(
#         choices=LeaveRequest.LeaveCategory.choices,
#         widget=forms.RadioSelect(attrs={'class': 'leave-category-radio'}),
#         required=True,
#         label='Leave Category',
#         help_text='Select either Paid Leave or Leave Without Pay (required)'
#     )

#     class Meta:
#         model = LeaveRequest
#         fields = ['start_date', 'end_date', 'leave_type', 'leave_category', 'reason']
#         widgets = {
#             'start_date': forms.DateInput(attrs={
#                 'type': 'date', 
#                 'class': 'form-control',
#                 'required': True,
#                 'pattern': r'\d{4}-\d{2}-\d{2}'
#             }),
#             'end_date': forms.DateInput(attrs={
#                 'type': 'date', 
#                 'class': 'form-control',
#                 'required': True,
#                 'pattern': r'\d{4}-\d{2}-\d{2}'
#             }),
#             'reason': forms.Textarea(attrs={
#                 'class': 'form-control', 
#                 'rows': 4, 
#                 'placeholder': 'Explain the reason for your leave request',
#                 'required': True
#             }),
#         }

#     def __init__(self, *args, employee=None, **kwargs):
#         self.employee = employee
#         super().__init__(*args, **kwargs)

#     def clean(self):
#         from datetime import timedelta
        
#         cleaned_data = super().clean()
#         start_date = cleaned_data.get('start_date')
#         end_date = cleaned_data.get('end_date')
#         leave_category = cleaned_data.get('leave_category')
#         leave_type = cleaned_data.get('leave_type')

#         # Basic date validation
#         if start_date and end_date and start_date > end_date:
#             raise ValidationError('End date must be on or after the start date.')

#         if start_date and start_date < timezone.now().date():
#             raise ValidationError('Leave start date cannot be in the past.')

#         # RULE A: Ensure leave_category is selected
#         if not leave_category:
#             raise ValidationError('You must select either Paid Leave or Leave Without Pay.')

#         if not self.employee or not start_date or not end_date:
#             return cleaned_data

#         # Calculate total days requested
#         total_days = (end_date - start_date).days + 1
        
#         # CRITICAL FIX: Half-day restrictions for multi-day leaves
#         # If leave spans more than one day, only full-day is allowed
#         if total_days > 1 and leave_type in [LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF]:
#             raise ValidationError(
#                 'Half-day options are only available for single-day leaves. '
#                 f'Your leave request spans {total_days} days, so only Full Day is allowed.'
#             )
        
#         # Calculate paid leave days based on leave_type
#         if leave_type == LeaveRequest.LeaveType.FULL_DAY:
#             paid_leave_days = total_days
#         elif leave_type in [LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF]:
#             # For half days, each day counts as 0.5
#             paid_leave_days = total_days * 0.5
#         else:
#             paid_leave_days = total_days

#         # RULE C: Check paid leave balance if requesting Paid Leave
#         if leave_category == LeaveRequest.LeaveCategory.PAID:
#             # remaining_balance = self.employee.calculate_paid_leave_balance()
#             remaining_balance = self.employee.get_final_leave_balance()
#             print(remaining_balance, '@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
            
#             # Count only pending/approved PAID leaves when checking balance
#             existing_paid_leaves = LeaveRequest.objects.filter(
#                 employee=self.employee,
#                 leave_category=LeaveRequest.LeaveCategory.PAID,
#                 status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
#             )
#             if self.instance.pk:
#                 existing_paid_leaves = existing_paid_leaves.exclude(pk=self.instance.pk)
            
#             # Calculate pending paid leave days
#             pending_paid_days = 0
#             # for existing_leave in existing_paid_leaves:
#             #     existing_days = (existing_leave.end_date - existing_leave.start_date).days + 1
#             #     if existing_leave.leave_type == LeaveRequest.LeaveType.FULL_DAY:
#             #         pending_paid_days += existing_days
#             #     elif existing_leave.leave_type in [LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF]:
#             #         pending_paid_days += existing_days * 0.5
            
#             available_balance = float(remaining_balance) - pending_paid_days
#             print(available_balance, '##########################################')
            
#             if paid_leave_days > available_balance:
#                 raise ValidationError(
#                     f'Insufficient paid leave balance. You have {available_balance:.1f} paid leave(s) available, '
#                     f'but requested {paid_leave_days:.1f} day(s).'
#                 )
            
#             # RULE B: Employee cannot request more than 3 consecutive Paid Leaves at once
#             if paid_leave_days > 3:
#                 raise ValidationError(
#                     'You cannot request more than 3 consecutive Paid Leaves at once. '
#                     f'Your request is for {paid_leave_days:.1f} day(s).'
#                 )

#         # RULE D: LWP has no limit - no validation needed

#         # Check for overlapping requests
#         overlapping = LeaveRequest.objects.filter(
#             employee=self.employee,
#             end_date__gte=start_date,
#             start_date__lte=end_date,
#             status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
#         )
#         if self.instance.pk:
#             overlapping = overlapping.exclude(pk=self.instance.pk)

#         if overlapping.exists():
#             raise ValidationError('You already have a pending or approved leave request that overlaps with these dates.')

#         return cleaned_data

from decimal import Decimal
from .models import LeaveType, EmployeeLeaveBalance   # add to existing imports


class LeaveRequestForm(forms.ModelForm):
    """Form for employees to request leave, tied to a configurable LeaveType."""

    leave_type = forms.ChoiceField(
        choices=LeaveRequest.LeaveType.choices,
        widget=forms.RadioSelect(attrs={'class': 'leave-type-radio'}),
        initial=LeaveRequest.LeaveType.FULL_DAY,
        required=True,
        label='Duration'
    )

    leave_category = forms.ChoiceField(
        choices=LeaveRequest.LeaveCategory.choices,
        widget=forms.RadioSelect(attrs={'class': 'leave-category-radio'}),
        initial=LeaveRequest.LeaveCategory.PAID,
        required=True,
        label='Leave Category',
        help_text='Select either Paid Leave or Leave Without Pay (required)'
    )

    leave_type_ref = forms.ModelChoiceField(
        queryset=LeaveType.objects.none(),
        required=False,   # only required when leave_category == PAID (enforced in clean())
        label='Leave Type',
        empty_label='-- Select Leave Type --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = LeaveRequest
        fields = ['start_date', 'end_date', 'leave_type_ref', 'leave_category', 'leave_type', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={
                'type': 'date', 'class': 'form-control', 'required': True,
                'pattern': r'\d{4}-\d{2}-\d{2}'
            }),
            'end_date': forms.DateInput(attrs={
                'type': 'date', 'class': 'form-control', 'required': True,
                'pattern': r'\d{4}-\d{2}-\d{2}'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Explain the reason for your leave request',
                'required': True
            }),
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)

        if employee:
            applicable = [
                lt for lt in LeaveType.objects.filter(is_active=True).order_by('display_order', 'name')
                if lt.is_applicable_for(employee)
            ]
            applicable_ids = [lt.id for lt in applicable]
            self.fields['leave_type_ref'].queryset = LeaveType.objects.filter(id__in=applicable_ids)

            balances = {
                b.leave_type_id: b.balance
                for b in EmployeeLeaveBalance.objects.filter(employee=employee, leave_type_id__in=applicable_ids)
            }
            self.fields['leave_type_ref'].label_from_instance = lambda lt: (
                f"{lt.name} ({lt.code}) — {balances.get(lt.id, Decimal('0.0'))} day(s) available"
                if lt.category == LeaveType.Category.PAID
                else f"{lt.name} ({lt.code}) — Unpaid"
            )

    def clean(self):
        from datetime import timedelta

        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        leave_category = cleaned_data.get('leave_category')
        leave_type = cleaned_data.get('leave_type')
        leave_type_ref = cleaned_data.get('leave_type_ref')

        if start_date and end_date and start_date > end_date:
            raise ValidationError('End date must be on or after the start date.')

        if start_date and start_date < timezone.now().date():
            raise ValidationError('Leave start date cannot be in the past.')

        if not leave_category:
            raise ValidationError('You must select either Paid Leave or Leave Without Pay.')

        # A leave type reference is required for Paid Leave so we know which balance to draw from
        if leave_category == LeaveRequest.LeaveCategory.PAID and not leave_type_ref:
            self.add_error('leave_type_ref', 'Please select which leave type this Paid Leave should draw from.')
            return cleaned_data

        if not self.employee or not start_date or not end_date:
            return cleaned_data

        total_days = (end_date - start_date).days + 1

        if total_days > 1 and leave_type in [LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF]:
            raise ValidationError(
                'Half-day options are only available for single-day leaves. '
                f'Your leave request spans {total_days} days, so only Full Day is allowed.'
            )

        if leave_type == LeaveRequest.LeaveType.FULL_DAY:
            requested_days = Decimal(total_days)
        else:
            requested_days = Decimal(total_days) * Decimal('0.5')

        # RULE C: Check balance for the SPECIFIC leave type selected
        if leave_category == LeaveRequest.LeaveCategory.PAID and leave_type_ref:
            balance_obj = EmployeeLeaveBalance.objects.filter(
                employee=self.employee, leave_type=leave_type_ref
            ).first()
            available_balance = balance_obj.balance if balance_obj else Decimal('0.0')

            # Subtract days already tied up in other pending/approved requests for this same type
            existing_qs = LeaveRequest.objects.filter(
                employee=self.employee,
                leave_type_ref=leave_type_ref,
                leave_category=LeaveRequest.LeaveCategory.PAID,
                status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            )
            if self.instance.pk:
                existing_qs = existing_qs.exclude(pk=self.instance.pk)

            pending_days = Decimal('0.0')
            for existing in existing_qs:
                existing_total = (existing.end_date - existing.start_date).days + 1
                if existing.leave_type == LeaveRequest.LeaveType.FULL_DAY:
                    pending_days += Decimal(existing_total)
                else:
                    pending_days += Decimal(existing_total) * Decimal('0.5')

            remaining_after_pending = available_balance - pending_days

            if requested_days > remaining_after_pending:
                raise ValidationError(
                    f'Insufficient {leave_type_ref.name} balance. You have '
                    f'{remaining_after_pending:.1f} day(s) available, but requested {requested_days:.1f} day(s).'
                )

            if requested_days > 3:
                raise ValidationError(
                    'You cannot request more than 3 consecutive Paid Leaves at once. '
                    f'Your request is for {requested_days:.1f} day(s).'
                )

        # Overlap check
        overlapping = LeaveRequest.objects.filter(
            employee=self.employee,
            end_date__gte=start_date,
            start_date__lte=end_date,
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
        )
        if self.instance.pk:
            overlapping = overlapping.exclude(pk=self.instance.pk)

        if overlapping.exists():
            raise ValidationError('You already have a pending or approved leave request that overlaps with these dates.')

        return cleaned_data

    
class LoanRequestForm(forms.ModelForm):
    """Form for employee loan/advance submissions."""

    class Meta:
        model = LoanRequest
        fields = ['amount', 'reason', 'attachment']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter amount (₹)',
                'min': '0',
                'step': '0.01'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Explain why you need this amount'
            }),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*,application/pdf'
            })
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        return amount


class ReimbursementRequestForm(forms.ModelForm):
    """Form for employee reimbursement submissions."""

    expense_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    upi_id = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'example@bank'
        }),
        label='UPI ID'
    )

    class Meta:
        model = ReimbursementRequest
        fields = ['amount', 'category', 'expense_date', 'reason', 'payment_slip', 'upi_id']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter amount (₹)',
                'min': '0',
                'step': '0.01'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Describe this expense'
            }),
            'payment_slip': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*,application/pdf'
            })
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise ValidationError('Amount must be greater than zero.')
        return amount


class LeaveVerificationUploadForm(forms.Form):
    """Form for employees to upload verification documents for pending leaves."""

    leave = forms.ModelChoiceField(
        queryset=LeaveRequest.objects.none(),
        label='Select leave request',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    receipt = forms.FileField(
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,.jpg,.jpeg,.png'
        }),
        label='Upload document'
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional notes or description'
        })
    )

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        if employee:
            from datetime import timedelta
            from django.utils import timezone
            
            # Only show APPROVED leaves that require documentation
            # Exclude: pending, rejected, already verified leaves
            queryset = LeaveRequest.objects.filter(
                employee=employee,
                status=LeaveRequest.Status.APPROVED,  # Only approved leaves
                verification_status__in=[
                    LeaveRequest.VerificationStatus.PENDING,
                    LeaveRequest.VerificationStatus.SUBMITTED,
                    LeaveRequest.VerificationStatus.UNDER_REVIEW,
                ]
            ).exclude(
                # Exclude leaves that are already verified
                verification_status=LeaveRequest.VerificationStatus.VERIFIED
            ).order_by('-created_at')
            
            self.fields['leave'].queryset = queryset

    def clean_leave(self):
        leave = self.cleaned_data['leave']
        if leave.employee != self.employee:
            raise ValidationError('Invalid leave selection.')
        if not leave.is_verification_window_open:
            raise ValidationError('Verification window has expired for this leave.')
        return leave

    def clean_receipt(self):
        receipt = self.cleaned_data['receipt']
        max_size = 5 * 1024 * 1024
        allowed_types = {'application/pdf', 'image/jpeg', 'image/jpg', 'image/png'}
        if receipt.size > max_size:
            raise ValidationError('File size exceeds 5MB limit.')
        if receipt.content_type not in allowed_types:
            raise ValidationError('Only PDF, JPG, and PNG files are allowed.')
        return receipt


class AssetAssignmentForm(forms.ModelForm):
    """Admin form for assigning assets to employees."""

    assigned_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    class Meta:
        model = AssetAssignment
        fields = ['employee', 'asset_type', 'asset_name', 'assigned_date', 'notes']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'asset_type': forms.Select(attrs={'class': 'form-select'}),
            'asset_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., MacBook Pro 16"'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Serial number, condition, etc.'}),
        }

    def clean_asset_name(self):
        asset_name = self.cleaned_data['asset_name'].strip()
        if not asset_name:
            raise ValidationError('Asset name cannot be empty.')
        return asset_name


class TaskForm(forms.ModelForm):
    """Form for admins to create or edit employee tasks."""

    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'assigned_to',
            'priority',
            'status',
            'due_date',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Task title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Task details and acceptance criteria'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, assigned_by=None, **kwargs):
        self.assigned_by = assigned_by
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = (
            Employee.objects.select_related('user').order_by('full_name', 'email')
        )
        self.fields['assigned_to'].label_from_instance = (
            lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
        )
        if 'status' in self.fields:
            self.fields['status'].choices = Task.Status.choices
        if 'priority' in self.fields:
            self.fields['priority'].choices = Task.Priority.choices

    def save(self, commit=True):
        task = super().save(commit=False)
        if self.assigned_by and not task.assigned_by:
            task.assigned_by = self.assigned_by
        if commit:
            task.save()
            self.save_m2m()
        return task


class TaskUpdateForm(forms.ModelForm):
    """Form for employees or admins to log task status updates."""

    class Meta:
        model = TaskUpdate
        fields = ['new_status', 'comment']
        widgets = {
            'new_status': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Share context for the status change'}),
        }

    def __init__(self, *args, user=None, task=None, **kwargs):
        self.user = user
        self.task = task
        super().__init__(*args, **kwargs)
        if task:
            self.fields['new_status'].choices = Task.Status.choices
            self.fields['new_status'].initial = task.status

    def save(self, commit=True):
        update = super().save(commit=False)
        if self.user:
            update.updated_by = self.user
        if self.task:
            update.task = self.task
            update.previous_status = self.task.status

        if commit:
            update.save()
            # Update task with latest status
            if self.task and update.new_status != self.task.status:
                self.task.status = update.new_status
                self.task.save(update_fields=['status', 'status_updated_at', 'updated_at'])
        return update
