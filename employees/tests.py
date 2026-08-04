import os
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import EmployeeForm
from .models import Employee


class EmployeeFormTests(TestCase):
    def test_employee_form_sets_legacy_name_and_accepts_educational_qualifications(self):
        form_data = {
            'full_name': 'Jane Doe',
            'email': 'jane@example.com',
            'contact': '+919999999999',
            'aadhar_card_number': '123456789012',
            'account_number': '123456789',
            'ifsc_code': 'ABCD0123456',
            'pan_card': 'ABCDE1234F',
            'current_address': '123 Current St',
            'permanent_address': '456 Permanent St',
            'relative_name': 'John Doe',
            'relative_contact': '+918888888888',
            'relation_with_employee': 'Brother',
            'educational_qualifications': 'B.Tech, XYZ University',
            'password': 'StrongPass123',
            'confirm_password': 'StrongPass123',
        }

        sample_file = SimpleUploadedFile('degree.pdf', b'%PDF-1.4 education', content_type='application/pdf')

        form = EmployeeForm(data=form_data, files={'educational_qualifications': sample_file})
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save(commit=False)
        self.assertEqual(employee.full_name, 'Jane Doe')
        self.assertEqual(employee.name, 'Jane Doe')
        self.assertTrue(employee.educational_qualifications)
        self.assertIn('degree.pdf', employee.educational_qualifications.name)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EmployeeDocumentUploadViewTests(TestCase):
    def setUp(self):
        self.media_root = settings.MEDIA_ROOT
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))

        self.user = User.objects.create_user(
            username='employee@example.com',
            email='employee@example.com',
            password='testpass123'
        )
        self.employee = Employee.objects.create(
            user=self.user,
            name='Employee One',
            full_name='Employee One',
            contact='+917000000000',
            email='employee@example.com',
            aadhar_card_number='987654321098',
            account_number='987654321',
            ifsc_code='WXYZ0123456',
            pan_card='WXYZE1234F'
        )

    def test_employee_can_upload_documents(self):
        self.client.login(username='employee@example.com', password='testpass123')

        sample_file = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 sample content', content_type='application/pdf')
        degree_file = SimpleUploadedFile('degree.pdf', b'%PDF-1.4 degree', content_type='application/pdf')

        response = self.client.post(
            reverse('employees:employee_documents'),
            data={
                'educational_qualifications': degree_file,
                'aadhar_document': sample_file,
                'pan_document': sample_file,
                'bank_passbook_document': sample_file,
            },
            follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.educational_qualifications.name)
        self.assertTrue(self.employee.aadhar_document.name)
        self.assertTrue(self.employee.pan_document.name)
        self.assertTrue(self.employee.bank_passbook_document.name)

        # Ensure files actually exist on disk
        for doc_field in [
            self.employee.educational_qualifications,
            self.employee.aadhar_document,
            self.employee.pan_document,
            self.employee.bank_passbook_document,
        ]:
            self.assertTrue(os.path.exists(doc_field.path))
