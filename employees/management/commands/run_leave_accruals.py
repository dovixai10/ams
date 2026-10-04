from datetime import date
from django.core.management.base import BaseCommand
from employees.leave_type_utils import run_all_accruals


class Command(BaseCommand):
    help = 'Credit leave accruals for all active leave types. Safe to run daily via cron — idempotent per period.'

    def handle(self, *args, **options):
        count = run_all_accruals(date.today())
        self.stdout.write(self.style.SUCCESS(f'Leave accrual run complete. {count} balances credited.'))