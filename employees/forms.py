from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    Employee,
    LeaveRequest,
    LoanRequest,
    ReimbursementRequest,
    Task,
    TaskUpdate,
    Project,
    ProjectAttachment,
    Team,
    AssetAssignment,
    LeaveType,
    AttendanceRule,
    DocumentType,
    AttendanceRegularizationRequest,
    Designation,
    Department,
    EmploymentType,
    SubscriptionPlan,
    Job,
)

from django.utils import timezone
from .permissions import (
    office_admin_required, is_platform_admin, get_request_office,
    tenant_queryset, tenant_object_or_404,
)

from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify

from .models import Office, OfficeAdmin, OfficeRegistrationDocumentType, OfficeRegistrationDocument
from .models import Employee, Shift, Branch, Role


class OfficeRegistrationForm(forms.Form):
    # -------------------------
    # Office Admin Information
    # -------------------------
    full_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your full name'
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'you@company.com'
        })
    )

    contact_number = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your mobile number'
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control'
        })
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control'
        })
    )

    # -------------------------
    # Office Information
    # -------------------------
    office_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control'
        })
    )

    office_address = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3
        })
    )

    office_contact = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control'
        })
    )

    logo = forms.ImageField(required=False)

    website = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://example.com'
        })
    )

    industry = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'IT, Education, Healthcare...'
        })
    )

    employee_strength = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control'
        })
    )
    latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=7,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': 'any',
            'placeholder': 'e.g. 26.912434'
        })
    )

    longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=7,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': 'any',
            'placeholder': 'e.g. 75.787270'
        })
    )

    registration_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control'
        })
    )

    gst_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control'
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # One file field per active document type, configured by the
        # platform admin via Django admin - new types appear here with no
        # code change needed.
        self.doc_types = list(
            OfficeRegistrationDocumentType.objects.filter(is_active=True).order_by('display_order', 'name')
        )
        for doc_type in self.doc_types:
            self.fields[f'doc_type_{doc_type.id}'] = forms.FileField(
                required=doc_type.is_required,
                label=doc_type.name,
                help_text=doc_type.description,
                widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
            )

    def document_fields(self):
        """(doc_type, bound_field) pairs for the template to render in order."""
        return [(doc_type, self[f'doc_type_{doc_type.id}']) for doc_type in self.doc_types]

    # -------------------------
    # Validation
    # -------------------------
    def clean_email(self):
        email = self.cleaned_data['email']

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        if (
            cleaned_data.get("password")
            and cleaned_data.get("confirm_password")
            and cleaned_data["password"] != cleaned_data["confirm_password"]
        ):
            self.add_error(
                "confirm_password",
                "Passwords do not match."
            )

        return cleaned_data

    # -------------------------
    # Save
    # -------------------------
    def save(self):
        data = self.cleaned_data

        base_slug = slugify(data["office_name"])
        slug = base_slug
        counter = 1

        while Office.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        office = Office.objects.create(
            name=data["office_name"],
            slug=slug,
            address=data["office_address"],
            contact_number=data["office_contact"],
            logo=data.get("logo"),
            website=data.get("website"),
            industry=data.get("industry"),
            employee_strength=data.get("employee_strength"),
            registration_number=data.get("registration_number"),
            gst_number=data.get("gst_number"),
            latitude=data["latitude"],
            longitude=data["longitude"],
            status=Office.Status.PENDING,
        )

        for doc_type in self.doc_types:
            uploaded = self.files.get(f'doc_type_{doc_type.id}')
            if uploaded:
                OfficeRegistrationDocument.objects.create(office=office, document_type=doc_type, file=uploaded)

        user = User.objects.create_user(
            username=data["email"],
            email=data["email"],
            password=data["password"],
            first_name=data["full_name"],
            is_active=False,  # Activated after approval
        )

        OfficeAdmin.objects.create(
            user=user,
            office=office,
            is_owner=True,
            full_name=data["full_name"],
            contact_number=data["contact_number"],
        )

        return office

class OfficeRegistrationDocumentTypeForm(forms.ModelForm):
    """Platform admin: create/edit a document type companies must submit
    when registering a new office - the in-site equivalent of doing this
    from Django admin, same screen pattern as SubscriptionPlanForm/plans."""

    class Meta:
        model = OfficeRegistrationDocumentType
        fields = ['name', 'code', 'description', 'is_required', 'is_active', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. GST Certificate'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to auto-generate'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Shown to the registrant, e.g. accepted file types'}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if code:
            clash = OfficeRegistrationDocumentType.objects.filter(code=code)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError('A document type with this code already exists.')
        return code


class OfficeProfileForm(forms.ModelForm):
    
    class Meta:
        model = Office
        fields = [
            'name', 'address', 'contact_number', 'website', 'industry',
            'employee_strength', 'registration_number', 'gst_number',
            'logo', 'latitude', 'longitude', 'attendance_radius_meters',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'industry': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_strength': forms.NumberInput(attrs={'class': 'form-control'}),
            'registration_number': forms.TextInput(attrs={'class': 'form-control'}),
            'gst_number': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'attendance_radius_meters': forms.NumberInput(attrs={'class': 'form-control', 'min': '10', 'placeholder': '250 (default)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['attendance_radius_meters'].required = False
        self.fields['attendance_radius_meters'].label = 'Attendance check-in radius (meters)'
        self.fields['attendance_radius_meters'].help_text = (
            "How far (in meters) an employee can be from the office and still check in/out - "
            "applies to the employee portal and the Attendance Kiosk URL. "
            "Leave blank to use the default (250m). A branch can override this with its own radius "
            "in Branches settings."
        )

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

    def __init__(self, *args, **kwargs):
        """ Receive the request and show only shifts/branches belonging to the current office/company. """
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs) # Never show all shifts by default.
        self.fields['shift'].queryset = Shift.objects.none()
        if self.request: self.fields['shift'].queryset = ( tenant_queryset( self.request, Shift.objects.filter(is_active=True) ) .order_by('name') )

        # Branch: restrict to the admin's own office, default to whichever
        # branch is currently active in their session.
        self.fields['branch'].queryset = Branch.objects.none()
        self.fields['branch'].required = True
        if self.request:
            office = get_request_office(self.request)
            if office is not None:
                self.fields['branch'].queryset = Branch.objects.filter(
                    office=office, is_active=True
                ).order_by('-is_head_office', 'name')
                if not self.is_bound:
                    from .permissions import get_request_branch
                    active_branch = get_request_branch(self.request)
                    if active_branch is not None:
                        self.fields['branch'].initial = active_branch.id

        # Roles: delegated permissions (e.g. "HR"), scoped to the SAME
        # branch this employee is being created into (branch-specific,
        # same as CompanyRule/Holiday - a role only applies within the
        # branch it was created for). Optional - most employees hold none.
        self.fields['roles'].queryset = Role.objects.none()
        self.fields['roles'].required = False
        if self.request:
            from .permissions import get_request_branch
            office = get_request_office(self.request)
            branch = get_request_branch(self.request)
            if office is not None and branch is not None:
                self.fields['roles'].queryset = Role.objects.filter(
                    office=office, branch=branch, is_active=True
                ).order_by('name')

        # Department/Designation/Employment Type: office-configurable lists
        # (HR creates these themselves under Company Settings), same
        # tenant-scoping as Shift above - never show another office's list.
        for field_name, model in (('department', Department), ('designation', Designation), ('employee_type', EmploymentType)):
            self.fields[field_name].queryset = model.objects.none()
            self.fields[field_name].required = False
            if self.request:
                self.fields[field_name].queryset = tenant_queryset(
                    self.request, model.objects.filter(is_active=True)
                ).order_by('display_order', 'name')

    class Meta:
        model = Employee
        fields = [
            'full_name', 'email', 'contact',
            'aadhar_card_number', 'account_number', 'ifsc_code', 'pan_card',
            'current_address', 'permanent_address',
            'relative_name', 'relative_contact', 'relation_with_employee',
            'aadhar_document', 'pan_document', 'bank_passbook_document',
            'joining_date', 'department', 'designation', 'employee_type',
            'shift', 'branch', 'roles',
        ]
        widgets = {
            'roles': forms.CheckboxSelectMultiple(),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-control'}),
            'designation': forms.Select(attrs={'class': 'form-control'}),
            'employee_type': forms.Select(attrs={'class': 'form-control'}),
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
            'employee_type': 'Employment Type',
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
            'aadhar_document': 'Upload Aadhar (PDF or image)',
            'pan_document': 'Upload PAN (PDF or image)',
            'bank_passbook_document': 'Upload bank passbook or cancelled cheque (PDF or image)',
            'joining_date': 'Employee\'s joining date (used for paid leave calculation)',
            'department': 'Which department this employee belongs to',
            'designation': 'Job title, printed on the ID card',
            'employee_type': 'Full-time, part-time, intern, contract, etc.',
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
        fields = ['aadhar_document', 'pan_document', 'bank_passbook_document']
        widgets = {
            'aadhar_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'pan_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'bank_passbook_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class EmployeeUpdateForm(forms.ModelForm):
    """Form for updating existing employees"""

    def __init__(self, *args, **kwargs):
        """ Receive the request and show only shifts/branches belonging to the current office/company. """
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs) # Never expose every company's shifts.
        self.fields['shift'].queryset = Shift.objects.none()
        if self.request: self.fields['shift'].queryset = ( tenant_queryset( self.request, Shift.objects.filter(is_active=True) ) .order_by('name') )

        # Branch: any branch in the admin's own office (including inactive
        # ones, so an employee already parked there doesn't lose their
        # current value) - lets the admin transfer this employee.
        self.fields['branch'].queryset = Branch.objects.none()
        self.fields['branch'].required = True
        if self.request:
            office = get_request_office(self.request)
            if office is not None:
                self.fields['branch'].queryset = Branch.objects.filter(
                    office=office
                ).order_by('-is_head_office', 'name')

        # Roles: delegated permissions, scoped to THIS employee's own
        # branch (branch-specific, same as CompanyRule/Holiday). If you
        # transfer them to a different branch, reopen Edit afterwards to
        # pick that branch's roles - their old branch's roles stop
        # granting anything the moment the transfer saves regardless
        # (see employee_has_permission), this queryset just keeps the
        # checkbox list itself relevant.
        self.fields['roles'].queryset = Role.objects.none()
        self.fields['roles'].required = False
        if self.request and self.instance and self.instance.pk and self.instance.branch_id:
            self.fields['roles'].queryset = Role.objects.filter(
                office=self.instance.office_id, branch=self.instance.branch_id
            ).order_by('name')

        # Department/Designation/Employment Type: office-configurable lists,
        # same tenant-scoping as Shift above.
        for field_name, model in (('department', Department), ('designation', Designation), ('employee_type', EmploymentType)):
            self.fields[field_name].queryset = model.objects.none()
            self.fields[field_name].required = False
            if self.request:
                self.fields[field_name].queryset = tenant_queryset(
                    self.request, model.objects.filter(is_active=True)
                ).order_by('display_order', 'name')

    class Meta:
        model = Employee
        fields = [
            'full_name', 'email', 'contact',
            'aadhar_card_number', 'account_number', 'ifsc_code', 'pan_card',
            'current_address', 'permanent_address',
            'relative_name', 'relative_contact', 'relation_with_employee',
            'aadhar_document', 'pan_document', 'bank_passbook_document',
            'joining_date', 'department', 'designation', 'employee_type',
            'shift', 'branch', 'roles',
        ]
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'roles': forms.CheckboxSelectMultiple(),
            'department': forms.Select(attrs={'class': 'form-control'}),
            'designation': forms.Select(attrs={'class': 'form-control'}),
            'employee_type': forms.Select(attrs={'class': 'form-control'}),
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
            'employee_type': 'Employment Type',
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
            'aadhar_document': 'Upload Aadhar (PDF or image)',
            'pan_document': 'Upload PAN (PDF or image)',
            'bank_passbook_document': 'Upload bank passbook or cancelled cheque (PDF or image)',
            'joining_date': 'Employee\'s joining date (used for paid leave calculation)',
            'department': 'Which department this employee belongs to',
            'designation': 'Job title, printed on the ID card',
            'employee_type': 'Full-time, part-time, intern, contract, etc.',
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


class DocumentTypeForm(forms.ModelForm):
    class Meta:
        model = DocumentType
        fields = ['name', 'code', 'description', 'is_required', 'is_active', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 10th Marksheet, Offer Letter'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated if left blank'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False


class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = ['name', 'code', 'is_active', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Software Engineer, HR Manager'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated if left blank'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'is_active', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Engineering, Sales, HR, Finance'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated if left blank'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False


class EmploymentTypeForm(forms.ModelForm):
    class Meta:
        model = EmploymentType
        fields = ['name', 'code', 'is_active', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Full-time, Part-time, Intern, Contract'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated if left blank'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False


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
            # branch=NULL means "office-wide"; a branch-tagged leave type
            # only applies to employees in that same branch (same rule the
            # mobile API and admin_leave_types use everywhere else).
            applicable = [
                lt for lt in LeaveType.objects.filter(office=employee.office, is_active=True).order_by('display_order', 'name')
                if (lt.branch_id is None or lt.branch_id == employee.branch_id) and lt.is_applicable_for(employee)
            ]
            applicable_ids = [lt.id for lt in applicable]
            self.fields['leave_type_ref'].queryset = LeaveType.objects.filter(office=employee.office, id__in=applicable_ids)

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

        # The two halves of one day don't collide: a First Half request and a
        # Second Half request for the same single date can both exist.
        if leave_type in (LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF) and start_date == end_date:
            other_half = (
                LeaveRequest.LeaveType.SECOND_HALF
                if leave_type == LeaveRequest.LeaveType.FIRST_HALF
                else LeaveRequest.LeaveType.FIRST_HALF
            )
            overlapping = overlapping.exclude(
                leave_type=other_half, start_date=start_date, end_date=start_date,
            )

        if overlapping.exists():
            raise ValidationError('You already have a pending or approved leave request that overlaps with these dates.')

        return cleaned_data


class AttendanceRegularizationRequestForm(forms.ModelForm):
    """Form for employees to ask that a missed check-in/check-out be marked
    for them - the reason is optional, matching how the feature was asked
    for, but at least one of the two times is required (enforced in clean())."""

    class Meta:
        model = AttendanceRegularizationRequest
        fields = ['date', 'requested_check_in', 'requested_check_out', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control', 'required': True}),
            'requested_check_in': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'requested_check_out': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional - why you missed marking attendance'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get('date')
        check_in = cleaned_data.get('requested_check_in')
        check_out = cleaned_data.get('requested_check_out')

        if not check_in and not check_out:
            raise ValidationError('Provide at least a check-in or check-out time.')
        if date and date > timezone.now().date():
            raise ValidationError('You cannot request attendance for a future date.')
        if check_in and check_out and check_out <= check_in:
            raise ValidationError('Check-out time must be after check-in time.')

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
    def __init__(self, *args, **kwargs): 
        """ Restrict the employee dropdown to the current company/office. """ 
        # Remove request before calling the parent ModelForm. 
        request = kwargs.pop('request', None) 
        super().__init__(*args, **kwargs) # Security default: # If the request is not supplied, do not show any employees. 
        self.fields['employee'].queryset = Employee.objects.none()
        # if request is not None: # Show only employees belonging to the logged-in # admin's current company/office.
        #     self.fields['employee'].queryset = ( tenant_queryset( request, Employee.objects.select_related('user') ).order_by('full_name') ) 
          
        if request is not None:
            employee_queryset = tenant_queryset(
                request,
                Employee.objects.select_related("user"),
            )

            self.fields["employee"].queryset = (
                employee_queryset
                .order_by("full_name")
            )

            # Optional: show name and email in the dropdown
            self.fields["employee"].label_from_instance = (
                lambda employee: (
                    f"{employee.full_name or employee.name}"
                    f" ({employee.email})"
                )
            )
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
            'project',
            'team',
            'title',
            'description',
            'assigned_to',
            'type',
            'priority',
            'severity',
            'status',
            'due_date',
            'estimated_hours',
        ]
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'team': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Task title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Task details and acceptance criteria'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'severity': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'estimated_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.25', 'min': '0', 'placeholder': 'e.g. 4'}),
        }

    def __init__(self, *args, assigned_by=None, request=None, employee=None, project=None, team=None, **kwargs):
        self.assigned_by = assigned_by
        self.request = request
        self.employee = employee

        super().__init__(*args, **kwargs)

        # Task.assigned_to is nullable at the model level (a team-board work
        # item can be created unassigned) but every *other* task-creation
        # path in the app - this form's normal admin/self-create flows -
        # should still require picking someone, exactly like before.
        self.fields['assigned_to'].required = True

        self.fields['project'].required = False
        self.fields['project'].empty_label = 'No project'
        if employee is not None:
            # Self-assignment: only show projects this employee is actually
            # on the team of (or manages) - not every project in the branch.
            projects = Project.objects.filter(
                Q(assigned_employees=employee) | Q(manager=employee)
            ).distinct()
        else:
            projects = Project.objects.all()
            if self.request:
                projects = tenant_queryset(self.request, projects)
        self.fields['project'].queryset = projects.order_by('name')

        if project is not None:
            # Opened from a project's detail page: lock the field to it.
            self.fields['project'].initial = project.pk
            self.fields['project'].widget = forms.HiddenInput()

        self.fields['team'].required = False
        self.fields['team'].empty_label = 'No team'
        if employee is not None:
            # Self-assignment: only show teams this employee is actually on.
            teams = Team.objects.filter(members=employee).distinct()
        else:
            teams = Team.objects.all()
            if self.request:
                teams = tenant_queryset(self.request, teams)
        self.fields['team'].queryset = teams.order_by('name')

        if team is not None:
            # Opened from a team's board: lock the field to it.
            self.fields['team'].initial = team.pk
            self.fields['team'].widget = forms.HiddenInput()

        if employee is not None:
            # Employee self-assignment: lock the field to themselves.
            self.fields['assigned_to'].queryset = Employee.objects.filter(pk=employee.pk)
            self.fields['assigned_to'].initial = employee.pk
            self.fields['assigned_to'].widget = forms.HiddenInput()
        else:
            employees = Employee.objects.select_related("user")
            if self.request:
                employees = tenant_queryset(self.request, employees)

            self.fields["assigned_to"].queryset = employees.order_by(
                "full_name",
                "email",
            )
            self.fields['assigned_to'].label_from_instance = (
                lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
            )

        if 'status' in self.fields:
            self.fields['status'].choices = Task.Status.choices
        if 'priority' in self.fields:
            self.fields['priority'].choices = Task.Priority.choices
        if 'type' in self.fields:
            self.fields['type'].choices = Task.Type.choices
        if 'severity' in self.fields:
            self.fields['severity'].choices = Task.Severity.choices
            self.fields['severity'].required = False

    def save(self, commit=True):
        task = super().save(commit=False)
        if self.assigned_by and not task.assigned_by:
            task.assigned_by = self.assigned_by

        if not task.office and task.assigned_to:
            task.office = task.assigned_to.office
        if not task.branch and task.assigned_to:
            task.branch = task.assigned_to.branch
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


class ProjectForm(forms.ModelForm):
    """Form for admins/permission-holders to create or edit a project."""

    class Meta:
        model = Project
        fields = [
            'name',
            'description',
            'client_department',
            'start_date',
            'end_date',
            'status',
            'manager',
            'assigned_employees',
            'priority',
            'tags',
            'estimated_budget',
            'actual_spend',
            'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Project name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description / objective'}),
            'client_department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Acme Corp or Marketing (optional)'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'assigned_employees': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Development, Marketing, Internal'}),
            'estimated_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'actual_spend': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Any additional notes'}),
        }

    def __init__(self, *args, request=None, created_by=None, **kwargs):
        self.request = request
        self.created_by = created_by
        super().__init__(*args, **kwargs)

        employees = Employee.objects.select_related('user')
        if self.request:
            employees = tenant_queryset(self.request, employees)
        employees = employees.order_by('full_name', 'email')

        self.fields['manager'].queryset = employees
        self.fields['manager'].required = False
        self.fields['manager'].empty_label = 'No manager assigned'
        self.fields['manager'].label_from_instance = (
            lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
        )

        self.fields['assigned_employees'].queryset = employees
        self.fields['assigned_employees'].required = False
        self.fields['assigned_employees'].label_from_instance = (
            lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
        )

        self.fields['status'].choices = Project.Status.choices
        self.fields['priority'].choices = Project.Priority.choices
        self.fields['start_date'].required = False
        self.fields['end_date'].required = False

    def save(self, commit=True):
        project = super().save(commit=False)
        if self.created_by and not project.created_by_id:
            project.created_by = self.created_by
        if not project.office_id and self.request:
            from .permissions import get_request_office, get_request_branch
            project.office = get_request_office(self.request)
            if not project.branch_id:
                project.branch = get_request_branch(self.request)
        if commit:
            project.save()
            self.save_m2m()
        return project


class JobForm(forms.ModelForm):
    """Form for recruitment.manage holders to create or edit a job posting."""

    class Meta:
        model = Job
        fields = [
            'title', 'description', 'department', 'designation', 'employment_type',
            'branch', 'location', 'salary_min', 'salary_max', 'openings', 'status',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Backend Developer'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Role summary, responsibilities, requirements'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'designation': forms.Select(attrs={'class': 'form-select'}),
            'employment_type': forms.Select(attrs={'class': 'form-select'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "e.g. Remote, or a city"}),
            'salary_min': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Annual, e.g. 600000'}),
            'salary_max': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Annual, e.g. 900000'}),
            'openings': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request=None, created_by=None, **kwargs):
        self.request = request
        self.created_by = created_by
        super().__init__(*args, **kwargs)

        if self.request:
            self.fields['department'].queryset = tenant_queryset(self.request, Department.objects.filter(is_active=True))
            self.fields['designation'].queryset = tenant_queryset(self.request, Designation.objects.filter(is_active=True))
            self.fields['employment_type'].queryset = tenant_queryset(self.request, EmploymentType.objects.filter(is_active=True))
            # Branch has no 'branch' field of its own (it IS the branch) - tenant_queryset()
            # is for models that reference a branch, so scope this one directly instead.
            office = get_request_office(self.request)
            self.fields['branch'].queryset = (
                Branch.objects.filter(office=office, is_active=True) if office else Branch.objects.none()
            )

        for key in ('department', 'designation', 'employment_type', 'branch'):
            self.fields[key].required = False
        self.fields['branch'].empty_label = 'Office-wide (every branch)'
        self.fields['status'].choices = Job.Status.choices

    def save(self, commit=True):
        job = super().save(commit=False)
        if self.created_by and not job.created_by_id:
            job.created_by = self.created_by
        if not job.office_id and self.request:
            from .permissions import get_request_office
            job.office = get_request_office(self.request)
        if commit:
            job.save()
        return job


class TeamForm(forms.ModelForm):
    """Form for admins/permission-holders to create or edit a team."""

    class Meta:
        model = Team
        fields = ['name', 'description', 'manager', 'members']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Backend Squad'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'What this team works on (optional)'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'members': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
        }

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

        employees = Employee.objects.select_related('user')
        if self.request:
            employees = tenant_queryset(self.request, employees)
        employees = employees.order_by('full_name', 'email')

        self.fields['manager'].queryset = employees
        self.fields['manager'].required = False
        self.fields['manager'].empty_label = 'No manager'
        self.fields['manager'].label_from_instance = (
            lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
        )

        self.fields['members'].queryset = employees
        self.fields['members'].required = False
        self.fields['members'].label_from_instance = (
            lambda obj: f"{obj.full_name or obj.name} ({obj.email})"
        )

    def save(self, commit=True):
        team = super().save(commit=False)
        if self.request:
            if not team.office_id:
                team.office = get_request_office(self.request)
            if not team.branch_id:
                team.branch = getattr(self.request, 'branch', None)
        if commit:
            team.save()
            self.save_m2m()
        return team


class ProjectAttachmentForm(forms.ModelForm):
    """Single-file upload form for a project's Attachments tab."""

    class Meta:
        model = ProjectAttachment
        fields = ['file', 'name']
        widgets = {
            'file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Display name (optional)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = False


class AttendanceRuleForm(forms.ModelForm):
    class Meta:
        model = AttendanceRule
        fields = ['threshold_mode', 'full_day_percentage', 'half_day_percentage',
                  'full_day_hours', 'half_day_hours', 'is_active']
        widgets = {
            'threshold_mode': forms.Select(attrs={'class': 'form-select'}),
            'full_day_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'half_day_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'full_day_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'half_day_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned = super().clean()
        instance = self.instance
        for field, value in cleaned.items():
            setattr(instance, field, value)
        instance.clean()  # reuse model-level validation
        return cleaned


class SubscriptionPlanForm(forms.ModelForm):
    """Platform admin: create/edit a subscription plan. Which features it
    includes is a separate checklist (SubscriptionPlanFeature rows), handled
    by the view - not part of this form, since it's dynamic (one checkbox
    per permissions.FEATURE_PERMISSIONS entry, not a fixed model field)."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            'name', 'slug', 'description', 'price', 'is_free', 'duration_value', 'duration_unit',
            'max_branches', 'max_employees', 'is_active', 'is_default', 'is_featured', 'order',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Growth'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to auto-generate'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'is_free': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'duration_value': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'duration_unit': forms.Select(attrs={'class': 'form-select'}),
            'max_branches': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'max_employees': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Unlimited'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, created_by=None, **kwargs):
        self.created_by = created_by
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['max_employees'].required = False
        self.fields['max_branches'].required = False

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip()
        if slug:
            clash = SubscriptionPlan.objects.filter(slug=slug)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError('That slug is already used by another plan.')
        return slug

    def save(self, commit=True):
        plan = super().save(commit=False)
        if self.created_by and not plan.created_by_id:
            plan.created_by = self.created_by
        if commit:
            plan.save()
        return plan
