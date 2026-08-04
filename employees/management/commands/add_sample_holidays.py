from django.core.management.base import BaseCommand
from datetime import date
from employees.models import Holiday


class Command(BaseCommand):
    help = 'Add real holidays for the current year'

    def handle(self, *args, **options):
        today = date.today()
        year = today.year
        
        # Clear all existing holidays
        Holiday.objects.all().delete()
        self.stdout.write(f"Cleared all existing holidays")

        # Real holidays for 2024/2025 (common Indian holidays)
        holidays_data = [
            # Fixed holidays
            (date(year, 1, 1), "New Year's Day"),
            (date(year, 1, 26), "Republic Day"),
            (date(year, 5, 1), "Labour Day"),
            (date(year, 8, 15), "Independence Day"),
            (date(year, 10, 2), "Gandhi Jayanti"),
            (date(year, 12, 25), "Christmas"),
            
            # Diwali (varies, using approximate dates)
            (date(year, 11, 1), "Diwali"),
            (date(year, 11, 2), "Diwali (Bhai Dooj)"),
            
            # Other festivals (approximate dates)
            (date(year, 3, 25), "Holi"),
            (date(year, 8, 19), "Raksha Bandhan"),
            (date(year, 9, 7), "Janmashtami"),
            (date(year, 10, 12), "Dussehra"),
            (date(year, 3, 8), "Maha Shivaratri"),
            
            # Islamic holidays (approximate dates for 2024)
            (date(year, 4, 10), "Eid al-Fitr"),
            (date(year, 6, 17), "Eid al-Adha"),
            (date(year, 7, 7), "Muharram"),
        ]

        # Add holidays
        added_count = 0
        for holiday_date, holiday_name in holidays_data:
            # Only add if the date is valid (not in the past for current year)
            if holiday_date >= today or holiday_date.year > today.year:
                holiday, created = Holiday.objects.get_or_create(
                    date=holiday_date,
                    defaults={
                        'name': holiday_name,
                        'description': f"Company holiday for {holiday_name}"
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Added holiday: {holiday_name} on {holiday_date.strftime('%d %B %Y')}"))
                    added_count += 1
                else:
                    self.stdout.write(f"Holiday already exists: {holiday_name} on {holiday_date}")
            else:
                # Still add past holidays for testing calendar display
                holiday, created = Holiday.objects.get_or_create(
                    date=holiday_date,
                    defaults={
                        'name': holiday_name,
                        'description': f"Company holiday for {holiday_name}"
                    }
                )
                if created:
                    self.stdout.write(f"Added past holiday for testing: {holiday_name} on {holiday_date.strftime('%d %B %Y')}")
                    added_count += 1

        total = Holiday.objects.count()
        self.stdout.write(self.style.SUCCESS(f"\nTotal holidays in database: {total}"))
        
        # Show current month holidays
        current_month = today.month
        current_month_holidays = Holiday.objects.filter(
            date__year=year,
            date__month=current_month
        )
        self.stdout.write(f"\nHolidays for current month ({today.strftime('%B %Y')}): {current_month_holidays.count()}")
        for holiday in current_month_holidays:
            self.stdout.write(f"  - {holiday.date.strftime('%d %B')}: {holiday.name}")
