from django.contrib import admin
from .models import (
    Shift,
    Employee,
    Attendance,
    AttendanceLog,
    Ticket,
    TicketComment,
    FaceUpdateRequest,
    LeaveRequest,
    Task,
    TaskUpdate,
    CompanyRule,
    LoanRequest,
    ReimbursementRequest,
    RuleAcknowledgement,
    RulesAcceptance,
    AssetAssignment,
    SalarySlip,
    EmployeeIDCard,
    EmployeeSalary,
    PaidLeaveAdjustment,
    EmployeeLeaveBalance,
    LeaveCreditLog,
    LeaveType
)


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'shift_type', 'start_time', 'end_time', 'is_active')
    list_filter = ('shift_type', 'is_active', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Shift Information', {
            'fields': ('name', 'shift_type', 'start_time', 'end_time', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'full_name', 'email', 'contact', 'created_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('name', 'full_name', 'email', 'contact')
    ordering = ('name', 'full_name')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'full_name', 'email', 'contact')
        }),
        ('Employment Details', {
            'fields': ('joining_date', 'shift')
        }),
        ('Financial Information', {
            'fields': ('aadhar_card_number', 'account_number', 'ifsc_code', 'pan_card', 'manual_extra_leaves')
        }),
        ('Profile', {
            'fields': ('profile_picture',)
        }),
        ('Account', {
            'fields': ('user',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )



@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "basic_salary",
        "gross_salary",
        "fixed_deductions",
        "net_salary_before_attendance",
        "payment_mode",
        "effective_from",
        "is_active",
    )

    list_filter = (
        "payment_mode",
        "is_active",
        "effective_from",
    )

    search_fields = (
        "employee__full_name",
        "employee__employee_id",
        "employee__email",
    )

    ordering = (
        "employee__full_name",
    )

    readonly_fields = (
        "gross_salary",
        "fixed_deductions",
        "net_salary_before_attendance",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Employee",
            {
                "fields": (
                    "employee",
                    "is_active",
                    "effective_from",
                )
            },
        ),
        (
            "Earnings",
            {
                "fields": (
                    "basic_salary",
                    "hra",
                    "da",
                    "conveyance_allowance",
                    "medical_allowance",
                    "special_allowance",
                    "bonus",
                )
            },
        ),
        (
            "Overtime",
            {
                "fields": (
                    "overtime_rate_per_hour",
                )
            },
        ),
        (
            "Deductions",
            {
                "fields": (
                    "pf",
                    "esi",
                    "professional_tax",
                    "tds",
                )
            },
        ),
        (
            "Payment",
            {
                "fields": (
                    "payment_mode",
                    "remarks",
                )
            },
        ),
        (
            "Salary Summary",
            {
                "fields": (
                    "gross_salary",
                    "fixed_deductions",
                    "net_salary_before_attendance",
                )
            },
        ),
        (
            "Audit Information",
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'check_in_time', 'get_date')
    list_filter = ('check_in_time',)
    search_fields = ('employee__name', 'employee__full_name', 'employee__email')
    ordering = ('-check_in_time',)
    total_work_hours = ('total_work_hours')
    final_status = ('final_status')

    fieldsets = ('Attendance Information', {
            'fields': ('employee', 'date', 'check_out_time', 'check_in_photo', 'check_out_photo', 'total_work_hours', 'final_status')
        }),

    def get_date(self, obj):
        return obj.date

    get_date.short_description = 'Date'
    get_date.admin_order_field = 'date'

@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('employee', 'action', 'success', 'timestamp', 'ip_address', 'confidence')
    list_filter = ('action', 'success', 'failure_reason', 'timestamp')
    search_fields = ('employee__name', 'employee__email', 'ip_address', 'notes')
    ordering = ('-timestamp',)
    readonly_fields = ('timestamp',)
    
    fieldsets = (
        ('Log Information', {
            'fields': ('employee', 'action', 'success', 'timestamp')
        }),
        ('Details', {
            'fields': ('failure_reason', 'confidence', 'attendance')
        }),
        ('Technical Information', {
            'fields': ('ip_address', 'user_agent', 'notes'),
            'classes': ('collapse',)
        }),
    )


@admin.register(FaceUpdateRequest)
class FaceUpdateRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'status',
        'requested_at',
        'reviewed_at',
        'reviewed_by',
        'completed_at',
    )
    list_filter = ('status', 'requested_at', 'reviewed_at')
    search_fields = ('employee__name', 'employee__email', 'reason', 'admin_comment')
    ordering = ('-requested_at',)
    readonly_fields = ('requested_at', 'reviewed_at', 'completed_at')

    fieldsets = (
        ('Request', {
            'fields': ('employee', 'status', 'reason')
        }),
        ('Review', {
            'fields': ('admin_comment', 'reviewed_by', 'reviewed_at', 'completed_at')
        }),
    )


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'start_date',
        'end_date',
        'status',
        'created_at',
        'reviewed_at',
        'reviewed_by',
    )
    list_filter = ('status', 'start_date', 'end_date', 'created_at')
    search_fields = ('employee__name', 'employee__full_name', 'employee__email', 'reason', 'admin_comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')

    fieldsets = (
        ('Leave Details', {
            'fields': ('employee', 'start_date', 'end_date', 'reason')
        }),
        ('Review', {
            'fields': ('status', 'admin_comment', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0
    readonly_fields = ('user', 'created_at')
    fields = ('user', 'comment', 'is_internal', 'created_at')


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'employee', 'subject', 'category', 'priority', 'status', 'created_at')
    list_filter = ('status', 'priority', 'category', 'created_at')
    search_fields = ('ticket_number', 'subject', 'employee__name', 'employee__email', 'description')
    ordering = ('-created_at',)
    readonly_fields = ('ticket_number', 'created_at', 'updated_at', 'resolved_at')
    inlines = [TicketCommentInline]
    
    fieldsets = (
        ('Ticket Information', {
            'fields': ('ticket_number', 'employee', 'subject', 'description', 'attachment')
        }),
        ('Classification', {
            'fields': ('category', 'priority', 'status')
        }),
        ('Resolution', {
            'fields': ('resolved_by', 'resolved_at', 'admin_notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'user', 'comment_preview', 'is_internal', 'created_at')
    list_filter = ('is_internal', 'created_at')
    search_fields = ('ticket__ticket_number', 'user__username', 'comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    def comment_preview(self, obj):
        return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment
    comment_preview.short_description = 'Comment'


class TaskUpdateInline(admin.TabularInline):
    model = TaskUpdate
    extra = 0
    readonly_fields = ('updated_by', 'previous_status', 'new_status', 'comment', 'created_at')
    fields = ('updated_by', 'previous_status', 'new_status', 'comment', 'created_at')
    can_delete = False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'assigned_to', 'status', 'priority', 'due_date', 'status_updated_at', 'created_at')
    list_filter = ('status', 'priority', 'due_date', 'created_at')
    search_fields = (
        'title',
        'description',
        'assigned_to__full_name',
        'assigned_to__email',
    )
    ordering = ('-created_at',)
    readonly_fields = ('status_updated_at', 'created_at', 'updated_at')
    inlines = [TaskUpdateInline]
    fieldsets = (
        ('Assignment', {
            'fields': ('title', 'description', 'assigned_to', 'assigned_by')
        }),
        ('Planning', {
            'fields': ('priority', 'status', 'due_date')
        }),
        ('Timestamps', {
            'fields': ('status_updated_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TaskUpdate)
class TaskUpdateAdmin(admin.ModelAdmin):
    list_display = ('task', 'updated_by', 'previous_status', 'new_status', 'created_at')
    list_filter = ('new_status', 'created_at')
    search_fields = (
        'task__title',
        'updated_by__username',
        'updated_by__email',
        'comment',
    )
    ordering = ('-created_at',)
    readonly_fields = ('previous_status', 'created_at')


@admin.register(CompanyRule)
class CompanyRuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'description')
    ordering = ('order', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Rule Information', {
            'fields': ('title', 'description', 'points')
        }),
        ('Display Settings', {
            'fields': ('order', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(LoanRequest)
class LoanRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'amount', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'created_at', 'reviewed_at')
    search_fields = ('employee__name', 'employee__email', 'reason', 'admin_comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Request Details', {
            'fields': ('employee', 'amount', 'reason', 'attachment')
        }),
        ('Review', {
            'fields': ('status', 'admin_comment', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ReimbursementRequest)
class ReimbursementRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'amount', 'category', 'status', 'expense_date', 'created_at')
    list_filter = ('status', 'category', 'expense_date', 'created_at')
    search_fields = ('employee__name', 'employee__email', 'reason', 'admin_comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Request Details', {
            'fields': ('employee', 'amount', 'category', 'reason', 'payment_slip', 'expense_date')
        }),
        ('Verification', {
            'fields': ('status', 'admin_comment', 'verified_by', 'verified_at')
        }),
        ('Payment', {
            'fields': ('paid_by', 'paid_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RuleAcknowledgement)
class RuleAcknowledgementAdmin(admin.ModelAdmin):
    list_display = ('employee', 'rule', 'acknowledged_at')
    search_fields = ('employee__full_name', 'employee__email', 'rule__title')
    list_filter = ('acknowledged_at',)
    ordering = ('-acknowledged_at',)


@admin.register(RulesAcceptance)
class RulesAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'version', 'accepted_at')
    search_fields = ('employee__full_name', 'employee__email')
    list_filter = ('version', 'accepted_at')
    ordering = ('-accepted_at',)


@admin.register(AssetAssignment)
class AssetAssignmentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'asset_name', 'asset_type', 'assigned_date')
    list_filter = ('asset_type', 'assigned_date')
    search_fields = ('employee__full_name', 'employee__email', 'asset_name', 'notes')
    ordering = ('-assigned_date',)


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = ('employee', 'month', 'basic_salary', 'deductions', 'net_salary', 'created_at')
    list_filter = ('month', 'created_at')
    search_fields = ('employee__full_name', 'employee__email')
    ordering = ('-month',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Salary Information', {
            'fields': ('employee', 'month')
        }),
        ('Salary Details', {
            'fields': ('basic_salary', 'deductions', 'net_salary')
        }),
        ('Document', {
            'fields': ('pdf_file',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EmployeeIDCard)
class EmployeeIDCardAdmin(admin.ModelAdmin):
    list_display = ('employee', 'employee_id_number', 'job_position', 'date_of_joining', 'created_at')
    list_filter = ('date_of_joining', 'created_at')
    search_fields = ('employee__full_name', 'employee__email', 'employee_id_number', 'job_position')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'qr_code')
    
    fieldsets = (
        ('Employee Information', {
            'fields': ('employee', 'employee_id_number', 'job_position', 'date_of_joining')
        }),
        ('Photo', {
            'fields': ('employee_photo',)
        }),
        ('QR Code', {
            'fields': ('qr_code',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
from django.contrib import admin

admin.site.register([PaidLeaveAdjustment, LeaveType, EmployeeLeaveBalance, LeaveCreditLog])