from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import RegexValidator, FileExtensionValidator
from django.utils import timezone
from datetime import date, timedelta
import json
from decimal import Decimal

class Office(models.Model):
    """A tenant / company using this HRMS. Every Employee, Attendance,
    LeaveRequest, etc. ultimately belongs to exactly one Office."""

    class Status(models.TextChoices):
        PENDING = ('pending', 'Pending Approval')
        APPROVED = ('approved', 'Approved')
        REJECTED = ('rejected', 'Rejected')
        SUSPENDED = ('suspended', 'Suspended')

    name = models.CharField(max_length=200, help_text="Company/office name")
    slug = models.SlugField(max_length=100, unique=True, help_text="Used for subdomain/URL identification")
    address = models.CharField(max_length=200, help_text="Company/office address")
    contact_number = models.CharField(
        max_length=15, blank=True,
        validators=[RegexValidator(r'^\+?1?\d{9,15}$', 'Enter a valid phone number.')]
    )
    logo = models.ImageField(upload_to='office_logos/', blank=True,null=True)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=100, blank=True, help_text="IT, Education, Manufacturing, Healthcare, etc.")

    employee_strength = models.PositiveIntegerField(null=True, blank=True, help_text="Approximate number of employees")

    # Optional Business Verification
    registration_number = models.CharField(max_length=100, blank=True, help_text="Company Registration Number")

    gst_number = models.CharField(max_length=20, blank=True)

    registration_document = models.FileField(upload_to="office_documents/", blank=True, null=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_offices'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def approve(self, admin_user):
        self.status = self.Status.APPROVED
        self.approved_by = admin_user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        # Activate the owning admin's login now that the office is approved
        owner = self.admins.filter(is_owner=True).first()
        if owner and not owner.user.is_active:
            owner.user.is_active = True
            owner.user.save(update_fields=['is_active'])

    def reject(self, admin_user, reason=''):
        self.status = self.Status.REJECTED
        self.approved_by = admin_user
        self.approved_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'])

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

class OfficeAdmin(models.Model):
    """Marks a Django User as the HR/admin for a specific Office.
    This user manages everything within their office once approved."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='office_admin_profile'
    )
    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name='admins')
    is_owner = models.BooleanField(default=True, help_text="The person who originally registered this office")
    full_name = models.CharField(max_length=200, blank=True)
    contact_number = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Office Admin'
        verbose_name_plural = 'Office Admins'

    def __str__(self):
        return f"{self.full_name or self.user.username} — {self.office.name}"

class Shift(models.Model):
    """Shift model for managing employee work shifts"""

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='shifts',
        null=True,
        blank=True,
        db_index=True,
        help_text='Office/company that owns this shift'
    )

    class ShiftType(models.TextChoices):
        FULL_DAY = ('full_day', 'Full Day')
        HALF_DAY = ('half_day', 'Half Day')
    
    name = models.CharField(
        max_length=100,
        help_text="Shift name (e.g., Morning, Night, General)"
    )
    shift_type = models.CharField(
        max_length=20,
        choices=ShiftType.choices,
        default=ShiftType.FULL_DAY,
        help_text="Type of shift: Full Day or Half Day"
    )
    start_time = models.TimeField(
        help_text="Shift start time (HH:MM)"
    )
    end_time = models.TimeField(
        help_text="Shift end time (HH:MM)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this shift is active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Shift'
        verbose_name_plural = 'Shifts'

        constraints = [
        models.UniqueConstraint(
            fields=['office', 'name'],
            name='unique_shift_name_per_office'
            )
        ]

        indexes = [
            models.Index(fields=['office', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_shift_type_display()}) - {self.start_time} to {self.end_time}"
    
    @property
    def duration_minutes(self):
        """Calculate shift duration in minutes"""
        from datetime import datetime
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        if end < start:  # Handle overnight shifts
            end = end.replace(day=end.day + 1)
        return int((end - start).total_seconds() / 60)
    
    @property
    def total_hours(self):
        """Calculate shift duration in decimal hours (e.g., 8.5)"""
        from decimal import Decimal
        from datetime import datetime
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        if end < start:  # Handle overnight shifts
            end = end.replace(day=end.day + 1)
        duration_seconds = (end - start).total_seconds()
        hours = Decimal(str(duration_seconds / 3600))
        return hours.quantize(Decimal('0.01'))
    
    @property
    def half_day_threshold(self):
        """Calculate half-day threshold (50% of total shift hours)"""
        return self.total_hours * Decimal('0.5')


class Employee(models.Model):
    """Employee model representing an employee in the system"""

    office = models.ForeignKey(
        'Office', on_delete=models.CASCADE, related_name='employees',
        null=True, blank=True,  # nullable at first for migration safety, tighten later
        help_text="The office/company this employee belongs to"
    )
    # Basic Information
    name = models.CharField(max_length=100, help_text="Employee's first name")
    full_name = models.CharField(max_length=200, help_text="Employee's full name")

    # Contact Information
    contact = models.CharField(
        max_length=15,
        validators=[RegexValidator(r'^\+?1?\d{9,15}$', 'Enter a valid phone number.')],
        help_text="Employee's contact number"
    )
    email = models.EmailField(unique=True, help_text="Employee's email address")

    # Financial Information
    aadhar_card_number = models.CharField(
        max_length=12,
        validators=[RegexValidator(r'^\d{12}$', 'Aadhar number must be exactly 12 digits.')],
        help_text="Employee's Aadhar card number"
    )
    account_number = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^\d{9,18}$', 'Account number must be 9-18 digits.')],
        help_text="Employee's bank account number"
    )
    ifsc_code = models.CharField(
        max_length=11,
        validators=[RegexValidator(r'^[A-Z]{4}0[A-Z0-9]{6}$', 'Enter a valid IFSC code.')],
        help_text="Bank IFSC code"
    )
    pan_card = models.CharField(
        max_length=10,
        validators=[RegexValidator(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', 'Enter a valid PAN card number.')],
        help_text="Employee's PAN card number"
    )

    educational_qualifications = models.FileField(
        upload_to='employee_docs/education/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="Uploaded copy of the employee's educational certificates"
    )

    # Document Uploads
    aadhar_document = models.FileField(
        upload_to='employee_docs/aadhar/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text='Uploaded copy of the employee\'s Aadhar card'
    )
    pan_document = models.FileField(
        upload_to='employee_docs/pan/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text='Uploaded copy of the employee\'s PAN card'
    )
    bank_passbook_document = models.FileField(
        upload_to='employee_docs/bank_passbook/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text='Uploaded copy of the employee\'s bank passbook or cancelled cheque'
    )

    # Address Information
    current_address = models.TextField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Current residential address"
    )
    permanent_address = models.TextField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Permanent residential address"
    )
    
    # Relative Information
    relative_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Name of the relative"
    )
    relative_contact = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[RegexValidator(r'^\+?1?\d{9,15}$', 'Enter a valid phone number.')],
        help_text="Contact number of the relative"
    )
    relation_with_employee = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Relationship with the employee (e.g., Father, Mother, Spouse)"
    )

    upi_id = models.CharField(
        max_length=120,
        blank=True,
        help_text="Preferred UPI ID for reimbursements"
    )
    
    # Profile Picture
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        blank=True,
        null=True,
        help_text="Employee's profile picture"
    )
    
    # Face Recognition Data
    face_encoding = models.TextField(
        blank=True,
        null=True,
        help_text="JSON-encoded face encoding data for recognition"
    )
    face_registered = models.BooleanField(
        default=False,
        help_text="Whether face recognition data has been registered"
    )
    face_registered_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When face was registered for recognition"
    )

    # User Account (linked to Django's User model)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='employee_profile',
        help_text="Associated Django user account"
    )

    # Employment Details
    joining_date = models.DateField(
        blank=True,
        null=True,
        help_text="Employee's joining date (used for paid leave calculation and 90-day logic)"
    )
    shift = models.ForeignKey(
        'Shift',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='employees',
        help_text="Shift allocated to this employee"
    )

    # Leave Balance (Auto-credit system)
    available_cl = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        help_text="Available Casual Leave balance (+1 per 30 days)"
    )
    available_sl = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0,
        help_text="Available Sick Leave balance (+0.5 per 30 days)"
    )
    last_leave_credit_date = models.DateField(
        blank=True,
        null=True,
        help_text="Last date when leave credits were auto-credited"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True,null =True,blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True,blank=True)

    manual_extra_leaves = models.DecimalField(
    max_digits=7,
    decimal_places=2,
    default=0,
    help_text="Admin-added additional paid leaves"
)

    class Meta:
        ordering = ['name', 'full_name']
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'

    def __str__(self):
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        # Always mirror the legacy short name from the full name
        if self.full_name:
            self.full_name = self.full_name.strip()
            self.name = self.full_name
        elif self.name:
            # Fallback for legacy records missing full_name
            self.full_name = self.name.strip()

        # Auto-generate username if not set (only for new users)
        if self.user and not self.user.username:
            self.user.username = self.email
        super().save(*args, **kwargs)
    
    def get_face_encoding(self):
        """Get face encoding as numpy array"""
        if not self.face_encoding:
            print(f"[DEBUG] Employee {self.id}: face_encoding is empty/None")
            return None
        try:
            import numpy as np
            encoding_data = json.loads(self.face_encoding)
            encoding_array = np.array(encoding_data)
            
            # Check if it's a placeholder (all zeros)
            is_placeholder = np.allclose(encoding_array, 0.0)
            print(f"[DEBUG] Employee {self.id}: Loaded encoding, shape={encoding_array.shape}, is_placeholder={is_placeholder}")
            
            if is_placeholder:
                print(f"[WARNING] Employee {self.id}: Stored encoding is all zeros (placeholder)!")
                return None
            
            return encoding_array
        except (json.JSONDecodeError, ValueError, ImportError) as e:
            print(f"[ERROR] Employee {self.id}: Error loading face encoding: {str(e)}")
            return None
    
    def set_face_encoding(self, encoding_array):
        """Set face encoding from numpy array"""
        if encoding_array is not None:
            self.face_encoding = json.dumps(encoding_array.tolist())
            self.face_registered = True
            from django.utils import timezone
            if not self.face_registered_at:
                self.face_registered_at = timezone.now()
        else:
            self.face_encoding = None
            self.face_registered = False
            self.face_registered_at = None

    @property
    def has_registered_face(self):
        """Return True only when face data and profile picture are present."""
        return bool(
            self.face_registered and
            self.face_encoding and
            self.profile_picture
        )

    @property
    def can_access_face_registration(self) -> bool:
        """Return True when the employee can view the face registration entry."""

        if not self.has_registered_face:
            return True

        return self.face_update_requests.filter(status=FaceUpdateRequest.Status.APPROVED).exists()

    @property
    def latest_face_update_request(self):
        """Convenience accessor for the most recent face update request."""

        return self.face_update_requests.order_by('-requested_at').first()


#--------------------------------------------------------------------------------------
    def calculate_paid_leave_balance(self):
        """
        Calculate the paid leave balance for the employee.
        
        Policy:
        - For every 30 calendar days from joining date, credit 1.5 paid leaves
          (1.0 Casual Leave + 0.5 Sick Leave)
        - This continues as long as the employee is active
        - After 90 days from joining, deduct approved leaves from the balance
        
        Returns: float (remaining paid leave balance)
        """
        from django.utils import timezone
        from datetime import timedelta
        from decimal import Decimal
        
        # Use joining_date if available, otherwise fall back to created_at
        if self.joining_date:
            joining_date = self.joining_date
        elif self.created_at:
            joining_date = self.created_at.date()
        else:
            return Decimal('0.0')
        
        # Calculate days since joining
        today = timezone.now().date()
        days_since_joining = (today - joining_date).days
        
        if days_since_joining < 0:
            return Decimal('0.0')
        
        # Calculate total credited leaves (1.5 leaves per 30 days)
        total_credited = Decimal(str((days_since_joining // 30) * 0))
        
        # Calculate total approved leaves taken (only after 90 days from joining)
        cutoff_date = joining_date + timedelta(days=90)
        total_days_taken = Decimal('0.0')
        
        if today >= cutoff_date:
            # Only count PAID leaves that were approved after the 90-day cutoff
            # RULE F: LWP does not deduct from paid leave balance
            from .models import LeaveRequest
            approved_paid_leaves = LeaveRequest.objects.filter(
                employee=self,
                leave_category=LeaveRequest.LeaveCategory.PAID,
                status=LeaveRequest.Status.APPROVED,
                start_date__gte=cutoff_date  # Only count leaves after 90 days
            )
            
            for leave in approved_paid_leaves:
                # Calculate actual calendar days in the leave period
                calendar_days = (leave.end_date - leave.start_date).days + 1
                
                # Calculate paid leave days based on leave_type
                if leave.leave_type == LeaveRequest.LeaveType.FULL_DAY:
                    leave_days = calendar_days
                elif leave.leave_type in [LeaveRequest.LeaveType.FIRST_HALF, LeaveRequest.LeaveType.SECOND_HALF]:
                    # Half days count as 0.5 per calendar day
                    leave_days = calendar_days * Decimal('0.5')
                else:
                    leave_days = calendar_days
                
                total_days_taken += Decimal(str(leave_days))
        
        # Calculate balance
        balance = total_credited - total_days_taken
        print(balance, 'QQQQQQQQQQQQQQQQQQ')
        return max(balance, Decimal('0.0'))  # Return 0 if negative

#--------------------------------------------------------------------------------------


    def get_final_leave_balance(self):
        auto_balance = self.calculate_paid_leave_balance()  # existing logic
        manual = self.manual_extra_leaves                   # admin added + or -

        final_balance = auto_balance + manual

        # Negative balance ko 0 rakho
        return max(final_balance, Decimal('0.0'))


# ===========================
# CONFIGURABLE LEAVE TYPES
# ===========================

class LeaveType(models.Model):
    """
    Admin-configurable leave type (e.g. Earned Leave, Casual Leave,
    Maternity Leave). Controls how much leave is credited and how often.

    Example: to get "1 paid leave per month", admin creates a LeaveType
    with accrual_frequency=MONTHLY and accrual_amount=1.
    """

    class Category(models.TextChoices):
        PAID = ('paid', 'Paid Leave')
        UNPAID = ('unpaid', 'Unpaid Leave')

    class AccrualFrequency(models.TextChoices):
        MONTHLY = ('monthly', 'Monthly')
        YEARLY = ('yearly', 'Yearly')
        ONE_TIME = ('one_time', 'One Time (fixed allocation)')
        NONE = ('none', 'No Auto Accrual (manual only)')

    class ApplicableGender(models.TextChoices):
        ALL = ('all', 'All')
        MALE = ('male', 'Male')
        FEMALE = ('female', 'Female')

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='leave_types',
        null=True,
        blank=True,
        db_index=True
    )

    name = models.CharField(
        max_length=100,
        
        help_text="Full name of the leave type (e.g. 'Earned Leave')"
    )
    code = models.CharField(
        max_length=20,
        help_text="Short code (e.g. EL, CL, SL, ML, PL, COMP)"
    )
    description = models.TextField(
        blank=True,
        help_text="Explanation of when/how this leave can be used"
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.PAID,
        help_text="Whether this leave type is paid or unpaid"
    )

    # ----- Accrual configuration -----
    accrual_frequency = models.CharField(
        max_length=20,
        choices=AccrualFrequency.choices,
        default=AccrualFrequency.MONTHLY,
        help_text="How often leave is auto-credited"
    )
    accrual_amount = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Days credited per accrual cycle (e.g. 1 per month, 15 per year)"
    )
    annual_limit = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Max total days this leave type can credit in a calendar year (blank = no limit)"
    )
    max_balance_cap = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Max balance an employee can hold at once (blank = no cap)"
    )

    # ----- Carry forward -----
    allow_carry_forward = models.BooleanField(
        default=True,
        help_text="Whether unused balance carries into the next year"
    )
    carry_forward_cap = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Max days that can be carried forward (blank = no cap, only relevant if carry forward allowed)"
    )

    # ----- Eligibility -----
    min_service_days_required = models.IntegerField(
        default=0,
        help_text="Employee must have completed this many days since joining before this leave applies (e.g. 90 for Comp-off eligibility, 180 for Maternity)"
    )
    applicable_gender = models.CharField(
        max_length=10,
        choices=ApplicableGender.choices,
        default=ApplicableGender.ALL,
        help_text="Restrict this leave type to a gender (e.g. Maternity → Female, Paternity → Male)"
    )
    requires_document = models.BooleanField(
        default=False,
        help_text="Whether supporting documents are mandatory for this leave type"
    )
    max_consecutive_days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Max consecutive days allowed per request (blank = no limit, useful for Bereavement/Marriage leave)"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Inactive leave types are hidden from employees but history is preserved"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which leave types appear in dropdowns/lists"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_leave_types'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'Leave Type'
        verbose_name_plural = 'Leave Types'

        constraints = [
            models.UniqueConstraint(
                fields=['office', 'name'],
                name='unique_leave_type_name_per_office'
            ),
            models.UniqueConstraint(
                fields=['office', 'code'],
                name='unique_leave_type_code_per_office'
            ),
        ]

        indexes = [
            models.Index(fields=['office', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def accrual_display(self):
        if self.accrual_frequency == self.AccrualFrequency.NONE:
            return "Manual only"
        return f"{self.accrual_amount} day(s) / {self.get_accrual_frequency_display().lower()}"

    def is_applicable_for(self, employee) -> bool:
        """Check gender + service-length eligibility for a given employee."""
        if self.applicable_gender != self.ApplicableGender.ALL:
            emp_gender = getattr(employee, 'gender', None)
            if emp_gender and emp_gender.lower() != self.applicable_gender:
                return False

        if self.min_service_days_required and employee.joining_date:
            days_served = (date.today() - employee.joining_date).days
            if days_served < self.min_service_days_required:
                return False

        return True


# models.py — add this near the top, above EmployeeLeaveBalance,
# right after your imports (date, Decimal, etc.)

def fiscal_year_for(d: date) -> int:
    """Fiscal year label: April 1 -> March 31. E.g. Feb 2027 -> FY 2026, Apr 2027 -> FY 2027."""
    return d.year if d.month >= 4 else d.year - 1

class EmployeeLeaveBalance(models.Model):
    """Per-employee, per-leave-type running balance."""

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='employee_leave_balance',
        null=True,
        blank=True,
        db_index=True
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_balances'
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='employee_balances'
    )
    balance = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text="Current available balance for this leave type"
    )
    total_credited_this_year = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text="Total credited so far in `credit_year` (used to enforce annual_limit)"
    )
    credit_year = models.IntegerField(
        help_text="Calendar year this total_credited_this_year applies to; reset when year changes"
    )
    last_credited_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of the most recent auto-accrual credit"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'leave_type')
        ordering = ['employee', 'leave_type']
        verbose_name = 'Employee Leave Balance'
        verbose_name_plural = 'Employee Leave Balances'

    def __str__(self):
        return f"{self.employee.full_name} — {self.leave_type.code}: {self.balance}"

    def credit(self, amount, credit_type='auto_accrual', note='', credited_by=None, commit=True):
        """
        Add `amount` to the balance, respecting max_balance_cap and annual_limit,
        and write an audit log entry. Returns the LeaveCreditLog created (or None
        if nothing was credited because caps were already reached).
        """
        from decimal import Decimal
        amount = Decimal(str(amount))

        today = date.today()
        current_fy = fiscal_year_for(today)   # <-- module-level function, no import needed
        if self.credit_year != current_fy:
            self.total_credited_this_year = Decimal('0.0')
            self.credit_year = current_fy

        # Respect annual_limit
        if self.leave_type.annual_limit is not None:
            remaining_annual = self.leave_type.annual_limit - self.total_credited_this_year
            if remaining_annual <= 0:
                return None
            amount = min(amount, remaining_annual)

        new_balance = self.balance + amount

        # Respect max_balance_cap
        if self.leave_type.max_balance_cap is not None:
            new_balance = min(new_balance, self.leave_type.max_balance_cap)
            amount = new_balance - self.balance

        if amount <= 0:
            return None

        self.balance = new_balance
        self.total_credited_this_year += amount
        self.last_credited_date = today

        if commit:
            self.save(update_fields=[
                'balance', 'total_credited_this_year', 'credit_year',
                'last_credited_date', 'updated_at'
            ])

        return LeaveCreditLog.objects.create(
            employee=self.employee,
            leave_type=self.leave_type,
            amount=amount,
            balance_after=self.balance,
            credit_type=credit_type,
            note=note,
            credited_by=credited_by,
        )


    def deduct(self, amount, note='', commit=True):
        """Deduct `amount` (e.g. when a leave request is approved) and log it."""
        from decimal import Decimal
        amount = Decimal(str(amount))
        self.balance = max(self.balance - amount, Decimal('0.0'))
        if commit:
            self.save(update_fields=['balance', 'updated_at'])
        return LeaveCreditLog.objects.create(
            employee=self.employee,
            leave_type=self.leave_type,
            amount=-amount,
            balance_after=self.balance,
            credit_type='deduction',
            note=note,
        )

    

class LeaveCreditLog(models.Model):
    """Audit trail of every credit/debit against an employee's leave balance."""

    class CreditType(models.TextChoices):
        AUTO_ACCRUAL = ('auto_accrual', 'Auto Accrual')
        INITIAL_ALLOCATION = ('initial_allocation', 'Initial Allocation')
        MANUAL_ADJUSTMENT = ('manual_adjustment', 'Manual Adjustment')
        CARRY_FORWARD = ('carry_forward', 'Carry Forward')
        DEDUCTION = ('deduction', 'Deduction (Leave Taken)')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='leave_credit_log',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_credit_logs'
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='credit_logs'
    )
    amount = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Positive for credits, negative for deductions"
    )
    balance_after = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Balance after this transaction was applied"
    )
    credit_type = models.CharField(
        max_length=30,
        choices=CreditType.choices,
        default=CreditType.AUTO_ACCRUAL
    )
    note = models.TextField(blank=True)
    credited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leave_credits_made',
        help_text="Admin who made this adjustment (blank for system auto-accrual)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Leave Credit Log'
        verbose_name_plural = 'Leave Credit Logs'
        indexes = [
            models.Index(fields=['employee', 'leave_type', '-created_at']),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.employee.full_name} · {self.leave_type.code} · {sign}{self.amount} ({self.get_credit_type_display()})"




    
def _format_duration_from_seconds(total_seconds: int) -> str:
    """Return a human-readable duration string (e.g., '1h 20m')."""

    if total_seconds is None:
        return '0m'

    try:
        total = max(int(total_seconds), 0)
    except (TypeError, ValueError):
        total = 0

    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return ' '.join(parts)


class Attendance(models.Model):
    """Attendance model for tracking employee check-ins"""

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='attendance_record',
        null=True,
        blank=True,
        db_index=True
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        help_text="Employee who checked in"
    )
    check_in_time = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when employee checked in"
    )
    date = models.DateField(
        help_text="Date of the check-in"
    )
    check_in_photo = models.ImageField(
        upload_to='checkin_photos/',
        blank=True,
        null=True,
        help_text="Photo taken during check-in for verification"
    )
    check_out_time = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when employee checked out"
    )
    check_out_photo = models.ImageField(
        upload_to='checkout_photos/',
        blank=True,
        null=True,
        help_text="Photo taken during check-out for verification"
    )
    check_in_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        help_text="Latitude of check-in location"
    )
    check_in_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        help_text="Longitude of check-in location"
    )
    check_out_latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        help_text="Latitude of check-out location"
    )
    check_out_longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        help_text="Longitude of check-out location"
    )
    half_day = models.BooleanField(
        default=False,
        help_text="Whether the attendance is marked as half-day due to short worked hours"
    )
    
    # Late Coming Fields
    is_late = models.BooleanField(
        default=False,
        help_text="Whether employee came late (within 30-45 min window)"
    )
    late_minutes = models.IntegerField(
        default=0,
        help_text="Minutes late from shift start time"
    )
    late_count = models.IntegerField(
        default=0,
        help_text="Monthly late count (resets on 1st of month)"
    )
    
    # Work Duration Fields
    total_work_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Total work hours (checkout - checkin - breaks)"
    )
    final_status = models.CharField(
        max_length=20,
        choices=[
            ('present', 'Present'),
            ('absent', 'Absent'),
            ('half_day', 'Half Day'),
            ('late_penalty', 'Late Penalty Half Day'),
            ('sandwich_leave', 'Sandwich Leave'),
            ('checked_in', 'Checked In Only'),
        ],
        default='present',
        help_text="Final attendance status after all rules applied"
    )
    forced_half_day_due_to_late = models.BooleanField(
        default=False,
        help_text="Whether half day was forced due to 4th late coming"
    )
    
    # Leave & Sandwich Leave Fields
    sandwich_flag = models.BooleanField(
        default=False,
        help_text="Whether this day is marked as sandwich leave"
    )
    absent_days_auto = models.BooleanField(
        default=False,
        help_text="Whether absence was auto-marked due to no leave request"
    )

    class Meta:
        ordering = ['-check_in_time']
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendance Records'
        # Ensure only one check-in per employee per day
        unique_together = ['employee', 'date']

    @classmethod
    def has_checked_in_today(cls, employee):
        """Check if the employee has checked in today."""
        from django.utils import timezone
        today = timezone.now().date()
        return cls.objects.filter(employee=employee, date=today).exists()

    @property
    def duration(self):
        """Calculate duration between check-in and check-out in HH:MM:SS format"""
        if not self.check_out_time or not self.check_in_time:
            return None
        
        delta = self.check_out_time - self.check_in_time
        total_seconds = int(delta.total_seconds())
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    @property
    def duration_display(self):
        """Human-readable duration display"""
        if not self.check_out_time:
            return "-"
        return self.duration or "-"
    
    @property
    def duration_hours(self):
        """Calculate duration in decimal hours"""
        if not self.check_out_time:
            return 0
        
        delta = self.check_out_time - self.check_in_time
        hours = delta.total_seconds() / 3600
        return round(hours, 2)

    @property
    def active_break(self):
        """Return the current active break for this attendance (if any)."""
        return self.breaks.filter(end_time__isnull=True).order_by('-start_time').first()

    @property
    def total_break_seconds(self):
        """Sum of all completed break durations in seconds."""
        total = 0
        for break_record in self.breaks.all():
            total += break_record.duration_seconds
        return total

    @property
    def total_break_display(self):
        """Human readable representation of total break time."""
        seconds = self.total_break_seconds
        if not seconds:
            return '0m'
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes or not parts:
            parts.append(f"{minutes}m")
        return ' '.join(parts)

    def calculate_attendance_status(self):
        """
        Calculate attendance status based on working duration.
        
        Rules (EXACT):
        - Duration >= 8.5 hours → PRESENT (Green)
        - Duration >= 4.5 hours and < 8.5 hours → HALF DAY (Yellow)
        - Duration < 4.5 hours OR missing punch → ABSENT (Red)
        
        Returns: tuple (status, color_code)
        - status: 'present', 'half_day', 'absent'
        - color_code: CSS color code
        """
        from datetime import datetime, timedelta
        
        # Check for missing punch-in or punch-out
        if not self.check_in_time or not self.check_out_time:
            return ('absent', '#FF3B30')  # Red
        
        # Make check-in and check-out times timezone-aware
        check_in = self.check_in_time
        check_out = self.check_out_time
        
        if timezone.is_naive(check_in):
            check_in = timezone.make_aware(check_in)
        if timezone.is_naive(check_out):
            check_out = timezone.make_aware(check_out)
        
        # Calculate working duration in hours
        duration_seconds = (check_out - check_in).total_seconds()
        duration_hours = duration_seconds / 3600
        
        # Apply rules based on working duration (EXACT THRESHOLDS)
        if duration_hours >= 8.5:
            return ('present', '#34C759')  # Green
        elif duration_hours >= 4.5:
            return ('half_day', '#FFCC00')  # Yellow
        else:  # duration_hours < 4.5
            return ('absent', '#FF3B30')  # Red
    
    def calculate_shift_based_status(self):
        """
        Calculate attendance status based on SHIFT-BASED logic.
        
        This uses the employee's assigned shift to determine:
        - Present: worked hours >= shift total hours
        - Half-Day: worked hours >= (shift hours * 0.5) AND < shift total hours
        - Absent: worked hours < (shift hours * 0.5)
        - Checked-In Only: no checkout recorded
        
        Returns: tuple (status, color_code)
        - status: 'present', 'half_day', 'absent', 'checked_in_only'
        - color_code: CSS color code
        """
        from employees.shift_attendance_logic import (
            calculate_attendance_status_for_record,
        )
        
        try:
            status, color = calculate_attendance_status_for_record(self)
            return (status, color)
        except Exception as e:
            # Fallback to old logic if shift-based fails
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in shift-based calculation: {str(e)}")
            return self.calculate_attendance_status()

    def end_active_breaks(self, *, end_time=None, origin='attendance update', ip_address=None, user_agent=None):
        """Close any active breaks tied to this attendance record and return the results."""

        if end_time is None:
            end_time = timezone.now()

        active_breaks = list(self.breaks.filter(end_time__isnull=True).order_by('start_time'))
        results = []

        for break_record in active_breaks:
            break_record.end_time = end_time
            break_record.save(update_fields=['end_time'])

            exceeded_now = break_record.check_and_mark_exceeded(commit=True)
            duration_display = break_record.duration_display

            AttendanceLog.objects.create(
                employee=self.employee,
                attendance=self,
                action='break_end_success',
                success=True,
                ip_address=ip_address or None,
                user_agent=user_agent or None,
                notes=f"Break automatically ended during {origin}. Duration: {duration_display}"
            )

            if exceeded_now:
                expected_display = break_record.expected_duration_display or 'no limit set'
                exceeded_display = break_record.exceeded_by_display or 'unknown'
                AttendanceLog.objects.create(
                    employee=self.employee,
                    attendance=self,
                    action='break_duration_exceeded',
                    success=False,
                    failure_reason='break_exceeded_limit',
                    ip_address=ip_address or None,
                    user_agent=user_agent or None,
                    notes=(
                        f"Break exceeded expected duration ({expected_display}) "
                        f"during {origin}. Exceeded by {exceeded_display}."
                    )
                )

            results.append((break_record, exceeded_now))

        return results

    def save(self, *args, **kwargs):
        """Ensure active breaks end automatically when a check-out is recorded."""

        check_out_time = self.check_out_time
        auto_end_needed = False

        if check_out_time is not None:
            if self.pk:
                original_check_out = (
                    self.__class__.objects
                    .filter(pk=self.pk)
                    .values_list('check_out_time', flat=True)
                    .first()
                )
                auto_end_needed = original_check_out is None
            else:
                auto_end_needed = True

        auto_ctx = getattr(self, '_auto_end_context', {}) or {}
        skip_auto = getattr(self, '_skip_auto_end_breaks', False)

        # CRITICAL FIX: Ensure final_status is always set before saving
        # This prevents frontend from recalculating and overwriting the status
        if not self.final_status and self.check_out_time:
            # If checkout exists but no final_status, compute it now
            status, _ = self.calculate_shift_based_status()
            self.final_status = status

        result = super().save(*args, **kwargs)

        end_results = []
        if auto_end_needed and not skip_auto:
            end_results = self.end_active_breaks(
                end_time=check_out_time,
                origin=auto_ctx.get('origin', 'attendance update'),
                ip_address=auto_ctx.get('ip_address'),
                user_agent=auto_ctx.get('user_agent'),
            )

        self._auto_end_results = end_results

        if hasattr(self, '_auto_end_context'):
            delattr(self, '_auto_end_context')
        if hasattr(self, '_skip_auto_end_breaks'):
            delattr(self, '_skip_auto_end_breaks')

        return result


class AttendanceDayComment(models.Model):
    """Daily comment shared between employee and admin for a given date."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='attendance_day_comment',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='attendance_day_comments',
        help_text="Employee the comment belongs to"
    )
    date = models.DateField(help_text="Date the comment refers to")
    comment = models.TextField(help_text="Comment text shared for the day")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='attendance_day_comments',
        null=True,
        blank=True,
        help_text="User who authored the comment"
    )
    is_admin_comment = models.BooleanField(
        default=False,
        help_text="Flag to indicate comment authored by an admin"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['date', 'employee']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'date', 'is_admin_comment'],
                name='unique_daily_comment_per_role'
            )
        ]

    def __str__(self) -> str:
        author = 'Admin' if self.is_admin_comment else 'Employee'
        date_str = self.date.strftime('%Y-%m-%d')
        return f"{author} comment for {self.employee.name} on {date_str}"


class AttendanceBreak(models.Model):
    """Track employee breaks during an attendance session."""

    class BreakReason(models.TextChoices):
        TEA = ('tea', 'Tea Break (15 min)')
        LUNCH = ('lunch', 'Lunch Break (40 min)')
        OTHER = ('other', 'Other')

    DEFAULT_DURATIONS = {
        BreakReason.TEA.value: 15,
        BreakReason.LUNCH.value: 40,
    }
    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='attendance_break',
            null=True,
            blank=True,
            db_index=True
        )

    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name='breaks',
        help_text="Related attendance record"
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='attendance_breaks',
        help_text="Employee taking the break"
    )
    start_time = models.DateTimeField(
        auto_now_add=True,
        help_text="When the break started"
    )
    end_time = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the break ended"
    )
    reason_type = models.CharField(
        max_length=20,
        choices=BreakReason.choices,
        default=BreakReason.TEA,
        help_text="Categorised break reason"
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional break reason provided by employee"
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes recorded by system or admin"
    )
    expected_duration_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Expected break duration in minutes for compliance"
    )
    exceeded_limit = models.BooleanField(
        default=False,
        help_text="Flag indicating the break exceeded its expected duration"
    )
    exceeded_notified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when stakeholders were notified about the exceedance"
    )

    class Meta:
        ordering = ['-start_time']
        verbose_name = 'Attendance Break'
        verbose_name_plural = 'Attendance Breaks'
        indexes = [
            models.Index(fields=['-start_time']),
            models.Index(fields=['employee', '-start_time']),
        ]

    def __str__(self):
        status = 'active' if self.end_time is None else 'completed'
        return f"{self.employee.name} break on {self.start_time.strftime('%Y-%m-%d %H:%M')} ({status})"

    @property
    def is_active(self):
        return self.end_time is None

    @property
    def duration(self):
        """Duration as timedelta (uses current time when break is active)."""
        end = self.end_time or timezone.now()
        return end - self.start_time

    @property
    def duration_seconds(self):
        return int(self.duration.total_seconds()) if self.duration else 0

    @property
    def duration_display(self):
        seconds = max(self.duration_seconds, 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def expected_duration_display(self):
        if not self.expected_duration_minutes:
            return ''
        return _format_duration_from_seconds(self.expected_duration_minutes * 60)

    @property
    def allowed_seconds(self) -> int:
        return int(self.expected_duration_minutes * 60)

    @property
    def is_over_allowed_duration(self) -> bool:
        if self.expected_duration_minutes <= 0:
            return False
        return self.duration_seconds > self.allowed_seconds

    @property
    def exceeded_by_display(self) -> str:
        if not self.is_over_allowed_duration:
            return ''
        excess = self.duration_seconds - self.allowed_seconds
        return _format_duration_from_seconds(excess)

    def check_and_mark_exceeded(self, commit: bool = True) -> bool:
        """Mark break as exceeded when duration passes the expected threshold.

        Returns True only when the exceeded flag changed in this call.
        """

        if not self.is_over_allowed_duration:
            return False

        if self.exceeded_limit:
            return False

        self.exceeded_limit = True
        self.exceeded_notified_at = timezone.now()
        if commit:
            self.save(update_fields=['exceeded_limit', 'exceeded_notified_at'])
        return True

    def complete(self) -> bool:
        """Mark break as completed and return True if it exceeded limits."""
        if not self.end_time:
            self.end_time = timezone.now()
            self.save(update_fields=['end_time'])

        # Ensure exceedance flag is set when relevant and report whether it changed now
        return self.check_and_mark_exceeded(commit=True)


class LeaveRequest(models.Model):
    """Track employee leave applications and their approval workflow."""

    class Status(models.TextChoices):
        PENDING = ('pending', 'Pending')
        APPROVED = ('approved', 'Approved')
        REJECTED = ('rejected', 'Rejected')

    class VerificationStatus(models.TextChoices):
        NOT_REQUIRED = ('not_required', 'Not Required')
        PENDING = ('pending', 'Pending Documents')
        SUBMITTED = ('submitted', 'Submitted')
        UNDER_REVIEW = ('under_review', 'Under Review')
        VERIFIED = ('verified', 'Verified')
        EXPIRED = ('expired', 'Expired')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='leave_request',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_requests',
        help_text="Employee requesting the leave"
    )
    class LeaveType(models.TextChoices):
        FIRST_HALF = ('first_half', 'First Half')
        SECOND_HALF = ('second_half', 'Second Half')
        FULL_DAY = ('full_day', 'Full Day')
    
    class LeaveCategory(models.TextChoices):
        PAID = ('paid', 'Paid Leave')
        LWP = ('lwp', 'Leave Without Pay')
        WITHOUT_PAID = ('without_paid', 'Without Paid Leave')
    
    reason = models.TextField(help_text="Reason provided by the employee for taking leave")
    leave_category = models.CharField(
        max_length=30,
        choices=LeaveCategory.choices,
        default=LeaveCategory.PAID,
        help_text="Category of leave: Paid Leave or Leave Without Pay"
    )
    leave_type = models.CharField(
        max_length=20,
        choices=LeaveType.choices,
        default=LeaveType.FULL_DAY,
        help_text="Type of leave: First Half, Second Half, or Full Day"
    )
    receipt = models.FileField(
        upload_to='leave_receipts/',
        blank=True,
        null=True,
        help_text="Receipt or supporting document (e.g., medical certificate)"
    )

    leave_type_ref = models.ForeignKey(
        'LeaveType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leave_requests',
        help_text="Configurable leave type this request draws from (Earned Leave, Comp-off, etc.)"
    )
    start_date = models.DateField(help_text="Leave start date (inclusive)")
    end_date = models.DateField(help_text="Leave end date (inclusive)")
    approved_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date when leave was approved (used for compliance deadline calculation)"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current approval status"
    )
    admin_comment = models.TextField(
        blank=True,
        help_text="Optional comment provided by the admin while approving/rejecting"
    )
    reviewed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the request was last reviewed"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='leave_reviews',
        help_text="Admin who processed the request"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        help_text="Document verification workflow status"
    )
    verification_deadline = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Deadline for submitting verification documents (auto-set to 3 days after request)"
    )
    verification_completed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When verification requirements were satisfied"
    )
    verification_locked_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When uploads were locked (deadline expired)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Leave request'
        verbose_name_plural = 'Leave requests'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lte=models.F('end_date')),
                name='leave_request_valid_dates',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} · {self.start_date} → {self.end_date} ({self.get_status_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError('End date must be on or after the start date.')
        if not self.verification_deadline:
            self.verification_deadline = (self.created_at or timezone.now()) + timedelta(days=3)

    @property
    def total_days(self) -> int:
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1
    
    def is_paid_leave(self) -> bool:
        """Check if this leave type deducts from paid leave balance"""
        return self.leave_category == self.LeaveCategory.PAID
    
    def is_without_pay(self) -> bool:
        """Check if this leave is without pay (marks as absent)"""
        return self.leave_category in [self.LeaveCategory.WITHOUT_PAID, self.LeaveCategory.LWP]
    
    @property
    def display_status(self) -> str:
        """Return display status based on approval and document verification"""
        if self.status == self.Status.REJECTED:
            return 'Rejected'
        elif self.status == self.Status.APPROVED and self.verification_status == self.VerificationStatus.VERIFIED:
            return 'Approved'
        elif self.status == self.Status.APPROVED and self.verification_status != self.VerificationStatus.VERIFIED:
            return 'Pending Documents'
        else:
            return 'Pending'

    @property
    def is_verification_window_open(self) -> bool:
        if self.verification_status in {
            self.VerificationStatus.VERIFIED,
            self.VerificationStatus.NOT_REQUIRED,
            self.VerificationStatus.EXPIRED,
        }:
            return False
        if not self.verification_deadline:
            return True
        return timezone.now() <= self.verification_deadline

    @property
    def verification_time_remaining(self):
        if not self.verification_deadline:
            return None
        delta = self.verification_deadline - timezone.now()
        return max(delta, timedelta(0))

    def ensure_verification_deadline(self):
        if not self.verification_deadline:
            base = self.created_at or timezone.now()
            self.verification_deadline = base + timedelta(days=3)

    def mark_verification_submitted(self):
        if self.verification_status in [self.VerificationStatus.VERIFIED]:
            return
        self.verification_status = self.VerificationStatus.SUBMITTED
        self.ensure_verification_deadline()
        self.save(update_fields=['verification_status', 'verification_deadline', 'updated_at'])

    def mark_verification_under_review(self):
        self.verification_status = self.VerificationStatus.UNDER_REVIEW
        self.save(update_fields=['verification_status', 'updated_at'])

    def mark_verification_verified(self, commit=True):
        self.verification_status = self.VerificationStatus.VERIFIED
        self.verification_completed_at = timezone.now()
        update_fields = ['verification_status', 'verification_completed_at', 'updated_at']
        if commit:
            self.save(update_fields=update_fields)

    def expire_verification_window(self):
        if self.verification_status == self.VerificationStatus.VERIFIED:
            return
        self.verification_status = self.VerificationStatus.EXPIRED
        self.verification_locked_at = timezone.now()
        self.save(update_fields=['verification_status', 'verification_locked_at', 'updated_at'])

    def save(self, *args, **kwargs):
        if not self.pk and not self.verification_deadline:
            self.verification_deadline = timezone.now() + timedelta(days=3)
        super().save(*args, **kwargs)

    def mark_pending(self):
        self.status = self.Status.PENDING
        self.reviewed_at = None
        self.reviewed_by = None
        self.admin_comment = ''
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'admin_comment', 'updated_at'])

    def mark_approved(self, admin_user, comment: str = ''):
        """
        Mark leave request as approved.
        
        RULE E: When admin APPROVES a Paid Leave:
        - The employee.remaining_paid_leaves balance will automatically reflect this 
          approved leave through calculate_paid_leave_balance() method
        - No manual deduction needed as balance is calculated dynamically
        
        RULE F: When admin approves LWP:
        - Do NOT deduct anything from paid leaves (balance calculation filters by PAID category)
        """
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        self.approved_date = timezone.now().date()
        if comment is not None:
            self.admin_comment = comment
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'admin_comment', 'approved_date', 'updated_at'])
        
        # Note: Paid leave balance is calculated dynamically via calculate_paid_leave_balance()
        # which automatically counts only APPROVED PAID leaves, so no manual deduction needed

    def mark_rejected(self, admin_user, comment: str = ''):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        if comment is not None:
            self.admin_comment = comment
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'admin_comment', 'updated_at'])


class FaceUpdateRequest(models.Model):
    """Track employee requests to refresh their face recognition data."""

    class Status(models.TextChoices):
        PENDING = ('pending', 'Pending')
        APPROVED = ('approved', 'Approved')
        REJECTED = ('rejected', 'Rejected')
        COMPLETED = ('completed', 'Completed')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='face_update_request',
            null=True,
            blank=True,
            db_index=True
        )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='face_update_requests',
        help_text="Employee requesting face data refresh"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Workflow status for this request"
    )
    reason = models.TextField(
        blank=True,
        help_text="Optional reason provided by the employee"
    )
    admin_comment = models.TextField(
        blank=True,
        help_text="Optional response recorded by the admin"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the request was approved or rejected"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='face_update_reviews',
        help_text="Admin who processed the request"
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the employee finished re-registering their face"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'Face update request'
        verbose_name_plural = 'Face update requests'
        constraints = [
            models.UniqueConstraint(
                fields=['employee'],
                condition=models.Q(status__in=['pending', 'approved']),
                name='unique_active_face_update_request'
            )
        ]

    def __str__(self):
        return f"Face update request for {self.employee.full_name} ({self.get_status_display()})"

    def mark_pending(self):
        self.status = self.Status.PENDING
        self.reviewed_at = None
        self.reviewed_by = None
        self.completed_at = None
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'completed_at', 'updated_at'])

    def mark_approved(self, admin_user, comment=''):
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        if comment:
            self.admin_comment = comment
        self.completed_at = None
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'admin_comment', 'completed_at', 'updated_at'])

    def mark_rejected(self, admin_user, comment=''):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        if comment:
            self.admin_comment = comment
        self.completed_at = None
        self.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'admin_comment', 'completed_at', 'updated_at'])

    def mark_completed(self):
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])


class AttendanceLog(models.Model):
    """Log all attendance activities including successful and failed attempts"""
    
    ACTION_CHOICES = [
        ('check_in_success', 'Check-In Success'),
        ('check_in_failed', 'Check-In Failed'),
        ('check_out_success', 'Check-Out Success'),
        ('check_out_failed', 'Check-Out Failed'),
        ('break_start_success', 'Break Start Success'),
        ('break_start_failed', 'Break Start Failed'),
        ('break_end_success', 'Break End Success'),
        ('break_end_failed', 'Break End Failed'),
    ]
    
    FAILURE_REASONS = [
        ('no_face_detected', 'No Face Detected'),
        ('multiple_faces', 'Multiple Faces Detected'),
        ('face_not_matched', 'Face Not Matched'),
        ('already_checked_in', 'Already Checked In'),
        ('not_checked_in', 'Not Checked In Yet'),
        ('already_checked_out', 'Already Checked Out'),
        ('no_face_registered', 'Face Not Registered'),
        ('photo_required', 'Photo Required'),
        ('other', 'Other Error'),
        ('break_active_exists', 'Break Already Active'),
        ('break_not_active', 'No Active Break'),
        ('break_not_allowed', 'Break Not Allowed'),
    ]

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='attendance_log',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='attendance_logs',
        help_text="Employee who attempted the action"
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        help_text="Type of action attempted"
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When the action was attempted"
    )
    success = models.BooleanField(
        default=True,
        help_text="Whether the action was successful"
    )
    failure_reason = models.CharField(
        max_length=30,
        choices=FAILURE_REASONS,
        blank=True,
        null=True,
        help_text="Reason for failure if unsuccessful"
    )
    confidence = models.FloatField(
        blank=True,
        null=True,
        help_text="Face recognition confidence percentage"
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="IP address of the request"
    )
    user_agent = models.TextField(
        blank=True,
        null=True,
        help_text="Browser user agent"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes or error messages"
    )
    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='logs',
        help_text="Related attendance record if successful"
    )
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Attendance Log'
        verbose_name_plural = 'Attendance Logs'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['employee', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]
    
    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} {self.employee.name} - {self.get_action_display()} at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    
    @property
    def status_badge(self):
        """Return Bootstrap badge class based on status"""
        if self.success:
            return 'success'
        else:
            return 'danger'
    
    @property
    def action_icon(self):
        """Return icon based on action type"""
        icons = {
            'check_in_success': 'bx-log-in',
            'check_in_failed': 'bx-log-in',
            'check_out_success': 'bx-log-out',
            'check_out_failed': 'bx-log-out',
        }
        return icons.get(self.action, 'bx-time')


# ======================
# TASK MANAGEMENT MODELS
# ======================


class Task(models.Model):
    """Task assignments for employees with shared status updates."""

    class Priority(models.TextChoices):
        LOW = ('low', 'Low')
        MEDIUM = ('medium', 'Medium')
        HIGH = ('high', 'High')
        CRITICAL = ('critical', 'Critical')

    class Status(models.TextChoices):
        PENDING = ('pending', 'Pending')
        IN_PROGRESS = ('in_progress', 'In Progress')
        COMPLETED = ('completed', 'Completed')
        BLOCKED = ('blocked', 'Blocked')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='task',
            null=True,
            blank=True,
            db_index=True
        )
    
    title = models.CharField(
        max_length=150,
        help_text="Short summary of the task",
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed task description and acceptance notes",
    )
    assigned_to = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='tasks',
        help_text="Employee responsible for the task",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks',
        help_text="Admin who assigned the task",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current task status",
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        help_text="Priority to help employees order work",
    )
    due_date = models.DateField(
        blank=True,
        null=True,
        help_text="Optional due date for the task",
    )
    status_updated_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the task status was last updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Task'
        verbose_name_plural = 'Tasks'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['assigned_to', '-created_at']),
            models.Index(fields=['status', '-status_updated_at']),
            models.Index(fields=['priority', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} → {self.assigned_to.full_name}"

    def save(self, *args, **kwargs):
        status_changed = False

        if self.pk:
            original = (
                self.__class__.objects
                .filter(pk=self.pk)
                .values('status')
                .first()
            )
            if original:
                status_changed = original['status'] != self.status
        else:
            status_changed = True

        if status_changed or not self.status_updated_at:
            self.status_updated_at = timezone.now()

        return super().save(*args, **kwargs)

    @property
    def priority_badge(self) -> str:
        mapping = {
            self.Priority.LOW: 'info',
            self.Priority.MEDIUM: 'primary',
            self.Priority.HIGH: 'warning',
            self.Priority.CRITICAL: 'danger',
        }
        return mapping.get(self.priority, 'secondary')

    @property
    def status_badge(self) -> str:
        mapping = {
            self.Status.PENDING: 'secondary',
            self.Status.IN_PROGRESS: 'info',
            self.Status.COMPLETED: 'success',
            self.Status.BLOCKED: 'danger',
        }
        return mapping.get(self.status, 'secondary')

    @property
    def is_overdue(self) -> bool:
        if not self.due_date or self.status == self.Status.COMPLETED:
            return False
        return date.today() > self.due_date

    @property
    def latest_update(self):
        return self.updates.order_by('-created_at').first()


class TaskUpdate(models.Model):
    """Audit trail of task status updates and comments."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='task_update',
            null=True,
            blank=True,
            db_index=True
        )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='updates',
        help_text="Task referenced by this update",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='task_updates',
        help_text="User who performed the update",
    )
    previous_status = models.CharField(
        max_length=20,
        choices=Task.Status.choices,
        blank=True,
        null=True,
        help_text="Status before the change",
    )
    new_status = models.CharField(
        max_length=20,
        choices=Task.Status.choices,
        help_text="Status after the change",
    )
    comment = models.TextField(
        blank=True,
        help_text="Optional comment to describe the update",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Task Update'
        verbose_name_plural = 'Task Updates'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['task', '-created_at']),
        ]

    def __str__(self):
        return f"{self.task.title} → {self.get_new_status_display()} by {self.updated_by}"


class Ticket(models.Model):
    """Support ticket system for employees to raise issues"""

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('reopened', 'Reopened'),
    ]

    CATEGORY_CHOICES = [
        ('attendance', 'Attendance Issue'),
        ('leave', 'Leave Request'),
        ('payroll', 'Payroll Issue'),
        ('technical', 'Technical Support'),
        ('hr', 'HR Related'),
        ('facility', 'Facility/Infrastructure'),
        ('other', 'Other'),
    ]
    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='ticket',
            null=True,
            blank=True,
            db_index=True
        )

    ticket_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        help_text="Auto-generated ticket number"
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='tickets',
        help_text="Employee who raised the ticket"
    )
    subject = models.CharField(
        max_length=200,
        help_text="Brief subject of the issue"
    )
    description = models.TextField(
        help_text="Detailed description of the issue"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='other',
        help_text="Category of the ticket",
        null=True,
        blank=True
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium',
        help_text="Priority level",
        null=True,
        blank=True
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='open',
        help_text="Current status"
    )
    attachment = models.FileField(
        upload_to='ticket_attachments/',
        blank=True,
        null=True,
        help_text="Optional file attachment"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the ticket was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update time"
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the ticket was resolved"
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='resolved_tickets',
        help_text="Admin who resolved the ticket"
    )
    admin_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Internal notes by admin"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Support Ticket'
        verbose_name_plural = 'Support Tickets'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.ticket_number} - {self.subject} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        if not self.ticket_number:
            # Generate ticket number: TKT-YYYYMMDD-XXXX
            from django.utils import timezone
            today = timezone.now()
            date_str = today.strftime('%Y%m%d')
            
            # Get count of tickets created today
            today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
            count = Ticket.objects.filter(created_at__gte=today_start).count() + 1
            
            self.ticket_number = f"TKT-{date_str}-{count:04d}"
        
        # Auto-set resolved_at when status changes to resolved
        if self.status == 'resolved' and not self.resolved_at:
            from django.utils import timezone
            self.resolved_at = timezone.now()
        
        super().save(*args, **kwargs)
    
    @property
    def status_color(self):
        """Return color class based on status"""
        colors = {
            'open': 'primary',
            'in_progress': 'warning',
            'resolved': 'success',
            'closed': 'secondary',
            'reopened': 'danger',
        }
        return colors.get(self.status, 'secondary')
    
    @property
    def priority_color(self):
        """Return color class based on priority"""
        colors = {
            'low': 'info',
            'medium': 'primary',
            'high': 'warning',
            'urgent': 'danger',
        }
        return colors.get(self.priority, 'secondary')
    
    @property
    def category_icon(self):
        """Return icon based on category"""
        icons = {
            'attendance': 'bx-time-five',
            'leave': 'bx-calendar-x',
            'payroll': 'bx-money',
            'technical': 'bx-wrench',
            'hr': 'bx-user-voice',
            'facility': 'bx-building',
            'other': 'bx-help-circle',
        }
        return icons.get(self.category, 'bx-help-circle')
    
    @property
    def is_overdue(self):
        """Check if ticket is overdue (open for more than 3 days)"""
        if self.status in ['resolved', 'closed']:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return (timezone.now() - self.created_at) > timedelta(days=3)


class TicketComment(models.Model):
    """Comments/replies on tickets"""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='ticket_comment',
            null=True,
            blank=True,
            db_index=True
        )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='comments',
        help_text="Related ticket"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        help_text="User who posted the comment"
    )
    comment = models.TextField(
        help_text="Comment text"
    )
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal note (visible only to admins)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the comment was posted"
    )
    
    class Meta:
        ordering = ['created_at']
        verbose_name = 'Ticket Comment'
        verbose_name_plural = 'Ticket Comments'
    
    def __str__(self):
        return f"Comment on {self.ticket.ticket_number} by {self.user.username}"
    
    @property
    def is_admin(self):
        """Check if comment is from admin"""
        return self.user.is_superuser


class PasswordResetRequest(models.Model):
    """Model to track employee password reset requests"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='password_request',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='password_reset_requests',
        help_text="Employee requesting password reset"
    )
    email = models.EmailField(help_text="Email address used for request")
    reason = models.TextField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Reason for password reset request"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Status of the request"
    )
    new_password = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="New password set by admin (temporary)"
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_password_requests',
        help_text="Admin who processed the request"
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the request was processed"
    )
    admin_notes = models.TextField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Admin notes about the request"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Password Reset Request'
        verbose_name_plural = 'Password Reset Requests'
    
    def __str__(self):
        return f"Password reset request for {self.employee.name} - {self.status}"
    
    @property
    def is_pending(self):
        return self.status == 'pending'
    
    @property
    def is_approved(self):
        return self.status == 'approved'
    
    @property
    def is_rejected(self):
        return self.status == 'rejected'


# ===========================
# DOCUMENT UPLOAD SYSTEM
# ===========================

class EmployeeDocument(models.Model):
    """Track employee document uploads and verification status."""
    
    class DocumentType(models.TextChoices):
        MARKSHEET_10TH = ('marksheet_10th', '10th Marksheet')
        MARKSHEET_12TH = ('marksheet_12th', '12th Marksheet')
        AADHAR_FRONT = ('aadhar_front', 'Aadhar Front')
        AADHAR_BACK = ('aadhar_back', 'Aadhar Back')
        PAN = ('pan', 'PAN Card')
        BANK_PROOF = ('bank_proof', 'Bank Proof')
        EDUCATION_PROOF = ('education_proof', 'Education Proof')
        ADDRESS_PROOF = ('address_proof', 'Address Proof')
        OTHER = ('other', 'Other Document')
    
    class VerificationStatus(models.TextChoices):
        PENDING = ('pending', 'Pending')
        SUBMITTED = ('submitted', 'Submitted')
        VERIFIED = ('verified', 'Verified')
        REJECTED = ('rejected', 'Rejected')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='document',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='documents',
        help_text="Employee who uploaded the document"
    )
    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
        help_text="Type of document"
    )
    file = models.FileField(
        upload_to='employee_docs/%Y/%m/%d/',
        help_text="Uploaded document file"
    )
    status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        help_text="Document verification status"
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the document was uploaded"
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the document was verified"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_documents',
        help_text="Admin who verified the document"
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection (if rejected)"
    )
    needs_resubmission = models.BooleanField(
        default=False,
        help_text="Whether the employee has been asked to re-upload this document"
    )
    resubmit_requested_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the admin requested resubmission"
    )
    resubmit_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional note for why resubmission was requested"
    )
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Employee Document'
        verbose_name_plural = 'Employee Documents'
        indexes = [
            models.Index(fields=['employee', '-uploaded_at']),
            models.Index(fields=['status', '-uploaded_at']),
        ]
    
    def __str__(self):
        return f"{self.employee.name} - {self.get_document_type_display()}"
    
    @property
    def file_extension(self):
        """Get file extension"""
        if self.file:
            return self.file.name.split('.')[-1].lower()
        return None
    
    @property
    def file_size_mb(self):
        """Get file size in MB"""
        if self.file:
            return round(self.file.size / (1024 * 1024), 2)
        return 0


class LeaveVerificationDocument(models.Model):
    """Files uploaded by employees to verify leave requests."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='verification_document',
            null=True,
            blank=True,
            db_index=True
        )
    
    leave = models.ForeignKey(
        LeaveRequest,
        on_delete=models.CASCADE,
        related_name='verification_documents'
    )
    uploaded_by = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_verification_uploads'
    )
    file = models.FileField(
        upload_to='leave_verification_docs/%Y/%m/%d/',
        help_text="Supporting file for the leave request"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    replaced_at = models.DateTimeField(blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Leave Verification Document'
        verbose_name_plural = 'Leave Verification Documents'

    def __str__(self):
        return f"Leave #{self.leave_id} document ({self.file.name.split('/')[-1]})"

    def deactivate(self, note=''):
        if not self.is_active:
            return
        self.is_active = False
        self.replaced_at = timezone.now()
        if note:
            self.notes = note
        self.save(update_fields=['is_active', 'replaced_at', 'notes', 'updated_at'])


# ===========================
# HOLIDAY MANAGEMENT
# ===========================
class Holiday(models.Model):
    HOLIDAY_TYPES = (
        ("public", "Public Holiday"),
        ("company", "Company Holiday"),
        ("optional", "Optional Holiday"),
    )
    office = models.ForeignKey('Office', on_delete=models.CASCADE, related_name='holidays', null=True, blank=True)

    name = models.CharField(max_length=255)
    date = models.DateField()
    description = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=20, choices=HOLIDAY_TYPES, default="public")

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    class Meta:
        ordering = ['date']
        verbose_name = 'Holiday'
        verbose_name_plural = 'Holidays'
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['date', 'name']),
        ]
    
    def __str__(self):
        return f"{self.name} - {self.date}"
    
    @classmethod
    def is_holiday(cls, date_obj: date) -> bool:
        """Check if a date is a holiday"""
        return cls.objects.filter(date=date_obj).exists()
    
    @classmethod
    def get_holiday(cls, date_obj: date):
        """Get holiday object for a date"""
        return cls.objects.filter(date=date_obj).first()


# ===========================
# RULES & REGULATIONS
# ===========================

class CompanyRule(models.Model):
    """Company rules and regulations"""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='company_rule',
            null=True,
            blank=True,
            db_index=True
        )
    
    title = models.CharField(max_length=200, help_text="Rule title")
    description = models.TextField(help_text="Rule description")
    points = models.JSONField(
        default=list,
        blank=True,
        help_text="List of bullet points for this rule"
    )
    order = models.IntegerField(
        default=0,
        help_text="Display order (lower numbers appear first)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_rules'
    )
    
    class Meta:
        ordering = ['order', 'created_at']
        verbose_name = 'Company Rule'
        verbose_name_plural = 'Company Rules'
    
    def __str__(self):
        return self.title


class RuleAcknowledgement(models.Model):
    """Track per-rule acknowledgements for each employee."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='rule_acknowledgement',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='rule_acknowledgements'
    )
    rule = models.ForeignKey(
        CompanyRule,
        on_delete=models.CASCADE,
        related_name='acknowledgements'
    )
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'rule')
        ordering = ['employee', 'rule']

    def __str__(self):
        return f"{self.employee} acknowledged {self.rule}"


class RulesAcceptance(models.Model):
    """Track when an employee has accepted the overall rules set."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='rule_acceptance',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name='rules_acceptance'
    )
    accepted_at = models.DateTimeField(auto_now_add=True)
    version = models.CharField(
        max_length=50,
        default='v1',
        help_text="Version identifier for the rules"
    )

    def __str__(self):
        return f"{self.employee} accepted rules ({self.version})"


# ===========================
# ASSET MANAGEMENT
# ===========================

class AssetAssignment(models.Model):
    """Assets issued to employees."""

    class AssetType(models.TextChoices):
        LAPTOP = ('laptop', 'Laptop')
        LOCKER_KEY = ('locker_key', 'Locker Key')
        HEADPHONE = ('headphone', 'Headphone')
        CUSTOM = ('custom', 'Custom / Other')
    
    class AssetStatus(models.TextChoices):
        NOT_RECEIVED = ('not_received', 'Not Received')
        RECEIVED = ('received', 'Received')
        RETURNED = ('returned', 'Returned')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='asset_assignment',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='asset_assignments'
    )
    asset_type = models.CharField(
        max_length=20,
        choices=AssetType.choices,
        default=AssetType.CUSTOM
    )
    asset_name = models.CharField(
        max_length=120,
        help_text="Specific name or identifier of the asset"
    )
    assigned_date = models.DateField(
        help_text="Date when the asset was assigned"
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional notes such as serial numbers"
    )
    # Employee Status (what employee selected)
    employee_status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.NOT_RECEIVED,
        help_text="Employee's selected status for the asset"
    )
    status_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When employee last updated the status"
    )
    
    # HR Verification Fields
    hr_verified = models.BooleanField(
        default=False,
        help_text="Whether HR has verified the employee's status"
    )
    return_requested = models.BooleanField(
        default=False,
        help_text="Whether HR has requested return of the asset"
    )
    hr_comment = models.TextField(
        blank=True,
        help_text="HR's comment on the asset status"
    )
    hr_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When HR verified the status"
    )
    hr_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_assets',
        help_text="Admin who verified the asset"
    )
    
    # Keep status field for backward compatibility
    @property
    def status(self):
        """For backward compatibility, status returns employee_status"""
        return self.employee_status
    
    @status.setter
    def status(self, value):
        """For backward compatibility, setting status updates employee_status"""
        self.employee_status = value
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-assigned_date', '-created_at']

    def __str__(self):
        return f"{self.asset_name} → {self.employee.full_name}"
    
    def get_asset_icon(self):
        """Return the appropriate Font Awesome icon for the asset type"""
        icon_map = {
            'laptop': 'fas fa-laptop',
            'locker_key': 'fas fa-key',
            'headphone': 'fas fa-headphones',
            'custom': 'fas fa-box',
        }
        return icon_map.get(self.asset_type, 'fas fa-box')


# ===========================
# LOANS & ADVANCE MONEY REQUEST
# ===========================

class LoanRequest(models.Model):
    """Employee loan and advance money requests"""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DISAPPROVED = 'disapproved', 'Disapproved'

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='loan_request',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='loan_requests'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Loan/advance amount"
    )
    reason = models.TextField(help_text="Reason for loan request")
    attachment = models.FileField(
        upload_to='loan_attachments/',
        blank=True,
        null=True,
        help_text="Optional supporting document"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    admin_comment = models.TextField(blank=True, help_text="Admin comment/notes")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_loans'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Loan Request'
        verbose_name_plural = 'Loan Requests'
    
    def __str__(self):
        return f"{self.employee.full_name} - ₹{self.amount} - {self.get_status_display()}"
    
    @property
    def request_number(self):
        """Get per-employee request number (not global ID)"""
        # Count how many requests this employee has made up to and including this one
        count = LoanRequest.objects.filter(
            employee=self.employee,
            created_at__lte=self.created_at
        ).count()
        return count


# ===========================
# REIMBURSEMENT
# ===========================

class ReimbursementRequest(models.Model):
    """Employee reimbursement requests"""
    
    class Category(models.TextChoices):
        TRAVEL = 'travel', 'Travel'
        CAB = 'cab', 'Cab'
        FOOD = 'food', 'Food'
        OFFICE_SUPPLIES = 'office_supplies', 'Office Supplies'
        OTHER = 'other', 'Other'
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        VERIFIED = 'verified', 'Verified'
        PAID = 'paid', 'Paid'
        REJECTED = 'rejected', 'Rejected'

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='reimbursement_request',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='reimbursement_requests'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Reimbursement amount"
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER
    )
    reason = models.TextField(help_text="Reason for reimbursement")
    payment_slip = models.ImageField(
        upload_to='reimbursement_slips/',
        help_text="Payment slip photo (required)"
    )
    expense_date = models.DateField(help_text="Date of expense")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    admin_comment = models.TextField(blank=True, help_text="Admin comment/notes")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_reimbursements'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paid_reimbursements'
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    upi_id = models.CharField(
        max_length=120,
        blank=True,
        help_text="UPI ID provided for this reimbursement"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Reimbursement Request'
        verbose_name_plural = 'Reimbursement Requests'
    
    def __str__(self):
        return f"{self.employee.full_name} - ₹{self.amount} - {self.get_status_display()}"


class EmployeeSalary(models.Model):
    """
    Stores salary structure HISTORY for an employee. An employee can have
    multiple rows over time, each with its own effective_from date. The
    row that applies to a given month is the most recent one whose
    effective_from is on/before that month (see calculate_salary_for_month
    in views.py).
    """

    class PaymentMode(models.TextChoices):
        BANK = "bank", "Bank Transfer"
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        CHEQUE = "cheque", "Cheque"

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='salary_profile',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_profiles"  # CHANGED from OneToOneField(related_name="salary_profile")
    )

    # ==========================
    # Earnings
    # ==========================

    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hra = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="House Rent Allowance")
    da = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Dearness Allowance")
    conveyance_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    medical_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    special_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ==========================
    # Overtime
    # ==========================

    overtime_rate_per_hour = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        help_text="Amount paid per overtime hour"
    )

    # ==========================
    # Fixed Monthly Deductions
    # ==========================

    pf = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Provident Fund")
    esi = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Employee State Insurance")
    professional_tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tds = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Tax Deducted at Source")

    # ==========================
    # Payment
    # ==========================

    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices, default=PaymentMode.BANK)
    effective_from = models.DateField(help_text="Salary effective from")
    is_active = models.BooleanField(default=True, help_text="Marks the current/latest profile in the admin UI")
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name", "-effective_from"]
        unique_together = ["employee", "effective_from"]  # NEW: prevents duplicate rows for the same date
        verbose_name = "Employee Salary"
        verbose_name_plural = "Employee Salaries"

    def __str__(self):
        return f"{self.employee.full_name} Salary (from {self.effective_from})"

    @property
    def gross_salary(self):
        return (
            self.basic_salary + self.hra + self.da +
            self.conveyance_allowance + self.medical_allowance +
            self.special_allowance + self.bonus
        )

    @property
    def fixed_deductions(self):
        return self.pf + self.esi + self.professional_tax + self.tds

    @property
    def net_salary_before_attendance(self):
        return self.gross_salary - self.fixed_deductions


# ===========================
# SALARY SLIP MANAGEMENT
# ===========================

class SalarySlip(models.Model):
    """Employee salary slip records"""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='salary_slip',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='salary_slips',
        help_text="Employee associated with this salary slip"
    )
    month = models.DateField(
        help_text="Month for which salary slip is generated (first day of month)"
    )
    basic_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Basic salary amount"
    )
    deductions = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total deductions"
    )
    net_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Net salary after deductions"
    )
    pdf_file = models.FileField(
        upload_to='salary_slips/',
        blank=True,
        null=True,
        help_text="PDF file of the salary slip"
    )

    salary_profile = models.ForeignKey(
        EmployeeSalary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-month']
        unique_together = ['employee', 'month']
        verbose_name = 'Salary Slip'
        verbose_name_plural = 'Salary Slips'
    
    def __str__(self):
        return f"{self.employee.full_name} - {self.month.strftime('%B %Y')}"


# ===========================
# EMPLOYEE ID CARD MANAGEMENT
# ===========================

class EmployeeIDCard(models.Model):
    """Employee digital ID card"""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='employee_id_card',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name='id_card',
        help_text="Employee associated with this ID card"
    )
    employee_id_number = models.CharField(
        max_length=50,
        help_text="Unique employee ID number"
    )
    job_position = models.CharField(
        max_length=100,
        help_text="Job position/role"
    )
    date_of_joining = models.DateField(
        help_text="Employee's date of joining"
    )
    employee_photo = models.ImageField(
        upload_to='id_card_photos/',
        help_text="Employee photo for ID card"
    )
    qr_code = models.TextField(
        blank=True,
        help_text="QR code data (auto-generated)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Employee ID Card'
        verbose_name_plural = 'Employee ID Cards'
    
    def __str__(self):
        return f"ID Card - {self.employee.full_name}"


# ===========================
# EMPLOYEE PERFORMANCE POINTS
# ===========================

class EmployeePoints(models.Model):
    """Track employee performance points"""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='performance_point',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='performance_points',
        help_text="Employee associated with these points"
    )
    points = models.IntegerField(
        default=0,
        help_text="Current points balance"
    )
    month = models.IntegerField(
        help_text="Month (1-12)"
    )
    year = models.IntegerField(
        help_text="Year (YYYY)"
    )
    points_earned = models.IntegerField(
        default=0,
        help_text="Points earned this month"
    )
    points_deducted = models.IntegerField(
        default=0,
        help_text="Points deducted this month"
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Creation timestamp"
    )
    
    class Meta:
        unique_together = ('employee', 'month', 'year')
        ordering = ['-year', '-month']
        verbose_name = 'Employee Points'
        verbose_name_plural = 'Employee Points'
        indexes = [
            models.Index(fields=['employee', 'year', 'month']),
        ]
    
    def __str__(self):
        return f"{self.employee.full_name} - {self.month}/{self.year}: {self.points} pts"


# ===========================
# EMPLOYEE TASKS & NOTIFICATIONS
# ===========================

class EmployeeTask(models.Model):
    """Tasks assigned to employees"""
    
    class TaskStatus(models.TextChoices):
        PENDING = ('pending', 'Pending')
        IN_PROGRESS = ('in_progress', 'In Progress')
        COMPLETED = ('completed', 'Completed')
        OVERDUE = ('overdue', 'Overdue')
    
    class TaskPriority(models.TextChoices):
        LOW = ('low', 'Low')
        MEDIUM = ('medium', 'Medium')
        HIGH = ('high', 'High')
        URGENT = ('urgent', 'Urgent')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='assigned_task',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='assigned_tasks',
        help_text="Employee assigned to this task"
    )
    title = models.CharField(
        max_length=255,
        help_text="Task title"
    )
    description = models.TextField(
        blank=True,
        help_text="Task description"
    )
    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        help_text="Current task status"
    )
    priority = models.CharField(
        max_length=20,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
        help_text="Task priority level"
    )
    due_date = models.DateField(
        help_text="Task due date"
    )
    assigned_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_tasks_by',
        help_text="Admin who assigned this task"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Task creation timestamp"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp"
    )
    
    class Meta:
        ordering = ['-priority', 'due_date']
        verbose_name = 'Employee Task'
        verbose_name_plural = 'Employee Tasks'
        indexes = [
            models.Index(fields=['employee', 'status']),
            models.Index(fields=['due_date']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.employee.full_name}"
class LeaveAdjustment(models.Model):
    """Stores admin a leave increase/decrease history."""

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='leave_adjustment',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_adjustments"
    )
    old_balance = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    change_amount = models.DecimalField(max_digits=5, decimal_places=2)
    new_balance = models.DecimalField(max_digits=5, decimal_places=2)
    
    reason = models.CharField(
        max_length=100,
        choices=[
            ("manual_correction", "Manual Correction"),
            ("hr_adjustment", "HR Adjustment"),
            ("compensation", "Compensation"),
            ("penalty", "Penalty"),
        ]
    )

    comment = models.TextField(blank=True, null=True)

    adjusted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="leave_adjustments_made"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.change_amount} ({self.created_at.date()})"


class EmployeeNotification(models.Model):
    """Notifications for employees"""
    
    class NotificationType(models.TextChoices):
        # Task & Work
        TASK_ASSIGNED = ('task_assigned', 'Task Assigned')
        TASK_UPDATED = ('task_updated', 'Task Updated')
        
        # Leave & Attendance
        LEAVE_APPROVED = ('leave_approved', 'Leave Approved')
        LEAVE_REJECTED = ('leave_rejected', 'Leave Rejected')
        LEAVE_PENDING = ('leave_pending', 'Leave Pending Review')
        
        # Face Recognition
        FACE_APPROVED = ('face_approved', 'Face Update Approved')
        FACE_REJECTED = ('face_rejected', 'Face Update Rejected')
        
        # Support & Services
        TICKET_CREATED = ('ticket_created', 'Support Ticket Created')
        TICKET_RESOLVED = ('ticket_resolved', 'Support Ticket Resolved')
        
        # Financial
        LOAN_APPROVED = ('loan_approved', 'Loan Request Approved')
        LOAN_REJECTED = ('loan_rejected', 'Loan Request Rejected')
        REIMBURSEMENT_APPROVED = ('reimbursement_approved', 'Reimbursement Approved')
        REIMBURSEMENT_REJECTED = ('reimbursement_rejected', 'Reimbursement Rejected')
        
        # HR & Documents
        DOCUMENT_REQUIRED = ('document_required', 'Document Required')
        DOCUMENT_VERIFIED = ('document_verified', 'Document Verified')
        ID_CARD_GENERATED = ('id_card_generated', 'ID Card Generated')
        
        # Assets
        ASSET_ASSIGNED = ('asset_assigned', 'Asset Assigned')
        ASSET_RETURN_REQUESTED = ('asset_return_requested', 'Asset Return Requested')
        
        # General
        RULE_UPDATE = ('rule_update', 'Policy Update')
        ALERT = ('alert', 'Alert')

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='notification',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text="Employee receiving notification"
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        help_text="Type of notification"
    )
    title = models.CharField(
        max_length=255,
        help_text="Notification title"
    )
    message = models.TextField(
        help_text="Notification message"
    )
    action_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL to action page"
    )
    is_read = models.BooleanField(
        default=False,
        help_text="Whether notification has been read"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Creation timestamp"
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When notification was read"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Employee Notification'
        verbose_name_plural = 'Employee Notifications'
        indexes = [
            models.Index(fields=['employee', 'is_read']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.employee.full_name}"
class PaidLeaveAdjustment(models.Model):

    office = models.ForeignKey(
            Office,
            on_delete=models.CASCADE,
            related_name='paid_leave_adjustment',
            null=True,
            blank=True,
            db_index=True
        )
    
    employee = models.ForeignKey(
        'Employee',
        on_delete=models.CASCADE,
        related_name='paid_leave_adjustments'
    )
    adjustment_type = models.CharField(
        max_length=10,
        choices=[('INCREASE', 'Increase'), ('DECREASE', 'Decrease')]
    )
    amount = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.TextField(blank=True)
    previous_balance = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    new_balance = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    adjusted_at = models.DateTimeField(auto_now_add=True)
    adjusted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
