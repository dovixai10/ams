"""
Management command to fix attendance dates after migration
"""
from django.core.management.base import BaseCommand
from employees.models import Attendance
from django.utils import timezone


class Command(BaseCommand):
    help = 'Fix attendance dates to ensure they are properly set'

    def handle(self, *args, **options):
        self.stdout.write('Fixing attendance dates...')
        
        # Get all attendance records
        attendance_records = Attendance.objects.all()
        
        fixed_count = 0
        for attendance in attendance_records:
            # If date is not set, set it from check_in_time
            if not attendance.date:
                attendance.date = attendance.check_in_time.date()
                attendance.save()
                fixed_count += 1
                self.stdout.write(f'  Fixed attendance ID {attendance.id}')
        
        self.stdout.write(self.style.SUCCESS(f'\n✓ Fixed {fixed_count} attendance records'))
        
        # Check for duplicates
        from django.db.models import Count
        duplicates = Attendance.objects.values('employee', 'date').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        if duplicates:
            self.stdout.write(self.style.WARNING(f'\n⚠ Found {len(duplicates)} duplicate attendance records'))
            for dup in duplicates:
                self.stdout.write(f'  Employee ID {dup["employee"]}, Date {dup["date"]}: {dup["count"]} records')
                
                # Keep only the first record, delete others
                records = Attendance.objects.filter(
                    employee_id=dup['employee'],
                    date=dup['date']
                ).order_by('check_in_time')
                
                # Keep the first one
                first_record = records.first()
                # Delete the rest
                deleted_count = records.exclude(id=first_record.id).delete()[0]
                
                self.stdout.write(f'    Kept record ID {first_record.id}, deleted {deleted_count} duplicates')
            
            self.stdout.write(self.style.SUCCESS(f'\n✓ Cleaned up duplicate records'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ No duplicate records found'))
        
        self.stdout.write(self.style.SUCCESS('\n✅ Attendance data is now clean!'))
