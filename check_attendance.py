"""
Quick script to check attendance records
Run with: python manage.py shell < check_attendance.py
"""
from employees.models import Attendance, Employee
from django.utils import timezone

today = timezone.now().date()

print(f"\n=== Attendance Check ===")
print(f"Today's date: {today}")
print(f"Total attendance records: {Attendance.objects.count()}")
print(f"Today's attendance records: {Attendance.objects.filter(date=today).count()}")

if Attendance.objects.filter(date=today).exists():
    print("\nToday's records:")
    for a in Attendance.objects.filter(date=today):
        print(f"  - ID: {a.id}, Employee: {a.employee.name}, Date: {a.date}, Time: {a.check_in_time}")

print("\nAll employees:")
for emp in Employee.objects.all():
    today_att = Attendance.objects.filter(employee=emp, date=today).count()
    print(f"  - {emp.name}: {today_att} check-in(s) today")
