from django.utils import timezone
from rest_framework import serializers

from .models import Employee


def _absolute_file_url(file_field, request):
    """Return an absolute URL for a FileField/ImageField, or None if unset."""
    if not file_field:
        return None
    url = file_field.url
    return request.build_absolute_uri(url) if request else url


class EmployeeProfileSerializer(serializers.ModelSerializer):
    """Everything an employee can see about themselves: personal details,
    employment info, leave balance and current salary breakdown."""

    employee_code = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    office = serializers.SerializerMethodField()
    shift = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    has_registered_face = serializers.SerializerMethodField()
    paid_leave_balance = serializers.SerializerMethodField()
    salary = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id',
            'employee_code',
            'name',
            'full_name',
            'email',
            'contact',
            'profile_picture',
            'office',
            'shift',
            'joining_date',
            'current_address',
            'permanent_address',
            'relative_name',
            'relative_contact',
            'relation_with_employee',
            'aadhar_card_number',
            'pan_card',
            'account_number',
            'ifsc_code',
            'upi_id',
            'documents',
            'face_registered',
            'has_registered_face',
            'available_cl',
            'available_sl',
            'paid_leave_balance',
            'salary',
            'created_at',
            'updated_at',
        ]

    def get_employee_code(self, obj):
        return f"KI{obj.id:05d}"

    def get_profile_picture(self, obj):
        return _absolute_file_url(obj.profile_picture, self.context.get('request'))

    def get_office(self, obj):
        if not obj.office_id:
            return None
        return {
            'id': obj.office.id,
            'name': obj.office.name,
            'slug': obj.office.slug,
        }

    def get_shift(self, obj):
        if not obj.shift_id:
            return None
        return {
            'id': obj.shift.id,
            'name': obj.shift.name,
            'shift_type': obj.shift.shift_type,
            'start_time': obj.shift.start_time,
            'end_time': obj.shift.end_time,
        }

    def get_documents(self, obj):
        request = self.context.get('request')
        return {
            'aadhar_document': _absolute_file_url(obj.aadhar_document, request),
            'pan_document': _absolute_file_url(obj.pan_document, request),
            'bank_passbook_document': _absolute_file_url(obj.bank_passbook_document, request),
            'educational_qualifications': _absolute_file_url(obj.educational_qualifications, request),
        }

    def get_has_registered_face(self, obj):
        return obj.has_registered_face

    def get_paid_leave_balance(self, obj):
        return obj.get_final_leave_balance()

    def get_salary(self, obj):
        # Imported lazily to avoid a heavy import at module load time -
        # views.py pulls in the whole employees app.
        from .views import calculate_salary_for_month

        today = timezone.now().date()
        salary_profile = (
            obj.salary_profiles
            .filter(effective_from__lte=today)
            .order_by('-effective_from')
            .first()
        )
        if not salary_profile:
            return None

        data = {
            'effective_from': salary_profile.effective_from,
            'payment_mode': salary_profile.payment_mode,
            'basic_salary': salary_profile.basic_salary,
            'hra': salary_profile.hra,
            'da': salary_profile.da,
            'conveyance_allowance': salary_profile.conveyance_allowance,
            'medical_allowance': salary_profile.medical_allowance,
            'special_allowance': salary_profile.special_allowance,
            'bonus': salary_profile.bonus,
            'overtime_rate_per_hour': salary_profile.overtime_rate_per_hour,
            'pf': salary_profile.pf,
            'esi': salary_profile.esi,
            'professional_tax': salary_profile.professional_tax,
            'tds': salary_profile.tds,
            'gross_salary': salary_profile.gross_salary,
            'fixed_deductions': salary_profile.fixed_deductions,
            'net_salary_before_attendance': salary_profile.net_salary_before_attendance,
        }

        calc = calculate_salary_for_month(obj, today.year, today.month)
        if calc:
            data['current_month'] = {
                'year': today.year,
                'month': today.month,
                'working_days': calc['working_days'],
                'present_days': calc['present_days'],
                'half_days': calc['half_days'],
                'lwp_days': calc['lwp_days'],
                'per_day_salary': calc['per_day_salary'],
                'lwp_deduction': calc['lwp_deduction'],
                'payable_salary': calc['payable_salary'],
            }
        return data
