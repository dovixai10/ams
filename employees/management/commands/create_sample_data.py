from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from employees.models import Employee, Attendance


class Command(BaseCommand):
    help = 'Create sample data for Employee Management System'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing data before creating new sample data',
        )

    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write('Deleting existing data...')
            Employee.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Attendance.objects.all().delete()

        # Create superadmin user
        if not User.objects.filter(is_superuser=True).exists():
            self.stdout.write('Creating superadmin user...')
            superadmin = User.objects.create_superuser(
                username='admin',
                email='admin@company.com',
                password='admin123',
                first_name='System',
                last_name='Administrator'
            )
            self.stdout.write(
                self.style.SUCCESS(f'Superadmin created: {superadmin.username} / admin123')
            )

        # Sample employee data
        sample_employees = [
            {
                'name': 'John',
                'full_name': 'John Smith',
                'email': 'john.smith@company.com',
                'contact': '+1234567890',
                'aadhar_card_number': '123456789012',
                'account_number': '1234567890123456',
                'ifsc_code': 'HDFC0001234',
                'pan_card': 'ABCDE1234F',
                'password': 'employee123'
            },
            {
                'name': 'Jane',
                'full_name': 'Jane Doe',
                'email': 'jane.doe@company.com',
                'contact': '+1234567891',
                'aadhar_card_number': '123456789013',
                'account_number': '1234567890123457',
                'ifsc_code': 'ICIC0001234',
                'pan_card': 'FGHIJ5678K',
                'password': 'employee123'
            },
            {
                'name': 'Mike',
                'full_name': 'Mike Johnson',
                'email': 'mike.johnson@company.com',
                'contact': '+1234567892',
                'aadhar_card_number': '123456789014',
                'account_number': '1234567890123458',
                'ifsc_code': 'SBI0001234',
                'pan_card': 'LMNOP9012Q',
                'password': 'employee123'
            },
            {
                'name': 'Sarah',
                'full_name': 'Sarah Wilson',
                'email': 'sarah.wilson@company.com',
                'contact': '+1234567893',
                'aadhar_card_number': '123456789015',
                'account_number': '1234567890123459',
                'ifsc_code': 'PNB0001234',
                'pan_card': 'RSTUV3456W',
                'password': 'employee123'
            }
        ]

        created_count = 0
        for emp_data in sample_employees:
            if not User.objects.filter(email=emp_data['email']).exists():
                # Create user account
                user = User.objects.create_user(
                    username=emp_data['email'],
                    email=emp_data['email'],
                    first_name=emp_data['name'],
                    password=emp_data['password']
                )

                # Create employee record
                employee = Employee.objects.create(
                    name=emp_data['name'],
                    full_name=emp_data['full_name'],
                    email=emp_data['email'],
                    contact=emp_data['contact'],
                    aadhar_card_number=emp_data['aadhar_card_number'],
                    account_number=emp_data['account_number'],
                    ifsc_code=emp_data['ifsc_code'],
                    pan_card=emp_data['pan_card'],
                    user=user
                )

                created_count += 1
                self.stdout.write(f'Created employee: {employee.full_name}')

        # Create some sample attendance records
        if Employee.objects.exists():
            employees = Employee.objects.all()[:2]  # First 2 employees
            from django.utils import timezone
            from datetime import timedelta
            from django.db import IntegrityError

            attendance_count = 0
            for employee in employees:
                # Create attendance for today (ensure no duplicates)
                today = timezone.now().date()
                try:
                    if not Attendance.objects.filter(employee=employee, date=today).exists():
                        Attendance.objects.create(employee=employee)
                        attendance_count += 1
                except IntegrityError:
                    pass  # Already exists, skip

                # Create attendance for yesterday (ensure no duplicates)
                yesterday = timezone.now().date() - timedelta(days=1)
                try:
                    if not Attendance.objects.filter(employee=employee, date=yesterday).exists():
                        Attendance.objects.create(employee=employee)
                        attendance_count += 1
                except IntegrityError:
                    pass  # Already exists, skip

            if attendance_count > 0:
                self.stdout.write(f'Created {attendance_count} sample attendance records')

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} employees and sample data!')
        )
        self.stdout.write(
            self.style.SUCCESS('Login credentials:')
        )
        self.stdout.write('Superadmin: admin@company.com / admin123')
        self.stdout.write('Employees: [email] / employee123')
