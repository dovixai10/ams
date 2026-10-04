# employees/management/commands/credit_leave_accruals.py
from django.core.management.base import BaseCommand
from django.db import transaction
from employees.models import Employee, LeaveType, EmployeeLeaveBalance
from employees.leave_accrual import ensure_accrual
from datetime import date


class Command(BaseCommand):
    help = "Runs due leave accruals for every active employee and leave type."

    def handle(self, *args, **options):
        employees = Employee.objects.filter(user__is_active=True)
        leave_types = LeaveType.objects.filter(is_active=True)
        credited_count = 0

        for employee in employees:
            for lt in leave_types:
                if not lt.is_applicable_for(employee):
                    continue

                with transaction.atomic():
                    balance_obj, _ = EmployeeLeaveBalance.objects.get_or_create(
                        employee=employee,
                        leave_type=lt,
                        defaults={'balance': 0, 'credit_year': date.today().year},
                    )
                    before = balance_obj.balance
                    ensure_accrual(employee, balance_obj)
                    balance_obj.refresh_from_db()
                    if balance_obj.balance != before:
                        credited_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Accrual check complete. {credited_count} balance(s) updated."
        ))