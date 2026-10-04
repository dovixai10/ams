from datetime import date
from django.core.management.base import BaseCommand
from employees.leave_type_utils import run_year_end_carry_forward


class Command(BaseCommand):
    help = 'Run year-end carry-forward processing for all leave balances. Run once on Jan 1 via cron.'

    def handle(self, *args, **options):
        count = run_year_end_carry_forward(date.today().year)
        self.stdout.write(self.style.SUCCESS(f'Carry-forward run complete. {count} balances processed.'))