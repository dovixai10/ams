"""
SHIFT-BASED ATTENDANCE VALIDATION TEST SUITE
=============================================

This test suite validates the shift-based attendance system for:
1. All shift durations (30 min, 45 min, 1 hr, 4 hr, 8 hr, 9 hr, etc.)
2. Exact decimal calculations (0.25 hr, 0.5 hr, etc.)
3. Half-Day = 50% of shift duration
4. Present = 100% of shift duration
5. Edge cases (overnight shifts, missing checkout, seconds-level differences)

Run with: python manage.py test employees.test_shift_attendance_validation

Author: EMS System
Date: 2024
"""

from django.test import TestCase
from django.utils import timezone
from datetime import datetime, timedelta, time
from decimal import Decimal
from employees.models import Shift, Employee, Attendance, User
from employees.shift_attendance_logic import (
    get_shift_total_hours,
    get_shift_half_day_threshold,
    calculate_duration_hours,
    determine_attendance_status,
)


class ShiftTotalHoursValidation(TestCase):
    """Test Shift.total_hours property for various durations"""
    
    def test_30_minute_shift(self):
        """30 minutes = 0.5 hours"""
        shift = Shift.objects.create(
            name="30-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 30),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('0.50'))
        print(f"✓ 30-min shift: {total_hours} hours")
    
    def test_45_minute_shift(self):
        """45 minutes = 0.75 hours"""
        shift = Shift.objects.create(
            name="45-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 45),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('0.75'))
        print(f"✓ 45-min shift: {total_hours} hours")
    
    def test_1_hour_shift(self):
        """1 hour = 1.00 hours"""
        shift = Shift.objects.create(
            name="1-Hour Shift",
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('1.00'))
        print(f"✓ 1-hour shift: {total_hours} hours")
    
    def test_4_hour_shift(self):
        """4 hours = 4.00 hours"""
        shift = Shift.objects.create(
            name="4-Hour Shift",
            start_time=time(9, 0),
            end_time=time(13, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('4.00'))
        print(f"✓ 4-hour shift: {total_hours} hours")
    
    def test_8_hour_shift(self):
        """8 hours = 8.00 hours"""
        shift = Shift.objects.create(
            name="8-Hour Shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('8.00'))
        print(f"✓ 8-hour shift: {total_hours} hours")
    
    def test_8_5_hour_shift(self):
        """8.5 hours = 8.50 hours"""
        shift = Shift.objects.create(
            name="8.5-Hour Shift",
            start_time=time(9, 0),
            end_time=time(17, 30),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('8.50'))
        print(f"✓ 8.5-hour shift: {total_hours} hours")
    
    def test_9_hour_shift(self):
        """9 hours = 9.00 hours"""
        shift = Shift.objects.create(
            name="9-Hour Shift",
            start_time=time(9, 0),
            end_time=time(18, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('9.00'))
        print(f"✓ 9-hour shift: {total_hours} hours")
    
    def test_overnight_shift_8_hours(self):
        """Overnight shift: 10 PM - 6 AM = 8 hours"""
        shift = Shift.objects.create(
            name="Night Shift",
            start_time=time(22, 0),
            end_time=time(6, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('8.00'))
        print(f"✓ Overnight shift (10 PM - 6 AM): {total_hours} hours")
    
    def test_overnight_shift_10_hours(self):
        """Overnight shift: 9 PM - 7 AM = 10 hours"""
        shift = Shift.objects.create(
            name="Long Night Shift",
            start_time=time(21, 0),
            end_time=time(7, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        self.assertEqual(total_hours, Decimal('10.00'))
        print(f"✓ Overnight shift (9 PM - 7 AM): {total_hours} hours")


class HalfDayThresholdValidation(TestCase):
    """Test Shift.half_day_threshold property (50% of total hours)"""
    
    def test_30_minute_shift_threshold(self):
        """30-min shift: half-day threshold = 15 minutes = 0.25 hours"""
        shift = Shift.objects.create(
            name="30-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 30),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('0.25'))
        print(f"✓ 30-min shift threshold: {threshold} hours (15 minutes)")
    
    def test_45_minute_shift_threshold(self):
        """45-min shift: half-day threshold = 22.5 minutes = 0.375 hours"""
        shift = Shift.objects.create(
            name="45-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 45),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('0.38'))  # Rounded to 0.01
        print(f"✓ 45-min shift threshold: {threshold} hours (~22.5 minutes)")
    
    def test_1_hour_shift_threshold(self):
        """1-hour shift: half-day threshold = 30 minutes = 0.5 hours"""
        shift = Shift.objects.create(
            name="1-Hour Shift",
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('0.50'))
        print(f"✓ 1-hour shift threshold: {threshold} hours (30 minutes)")
    
    def test_4_hour_shift_threshold(self):
        """4-hour shift: half-day threshold = 2 hours"""
        shift = Shift.objects.create(
            name="4-Hour Shift",
            start_time=time(9, 0),
            end_time=time(13, 0),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('2.00'))
        print(f"✓ 4-hour shift threshold: {threshold} hours")
    
    def test_8_hour_shift_threshold(self):
        """8-hour shift: half-day threshold = 4 hours"""
        shift = Shift.objects.create(
            name="8-Hour Shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('4.00'))
        print(f"✓ 8-hour shift threshold: {threshold} hours")
    
    def test_8_5_hour_shift_threshold(self):
        """8.5-hour shift: half-day threshold = 4.25 hours"""
        shift = Shift.objects.create(
            name="8.5-Hour Shift",
            start_time=time(9, 0),
            end_time=time(17, 30),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('4.25'))
        print(f"✓ 8.5-hour shift threshold: {threshold} hours")
    
    def test_9_hour_shift_threshold(self):
        """9-hour shift: half-day threshold = 4.5 hours"""
        shift = Shift.objects.create(
            name="9-Hour Shift",
            start_time=time(9, 0),
            end_time=time(18, 0),
            is_active=True
        )
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(threshold, Decimal('4.50'))
        print(f"✓ 9-hour shift threshold: {threshold} hours")


class DurationCalculationValidation(TestCase):
    """Test calculate_duration_hours() for exact decimal output"""
    
    def test_15_minute_duration(self):
        """15 minutes = 0.25 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(minutes=15)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('0.25'))
        print(f"✓ 15-min duration: {duration} hours")
    
    def test_30_minute_duration(self):
        """30 minutes = 0.5 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(minutes=30)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('0.50'))
        print(f"✓ 30-min duration: {duration} hours")
    
    def test_45_minute_duration(self):
        """45 minutes = 0.75 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(minutes=45)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('0.75'))
        print(f"✓ 45-min duration: {duration} hours")
    
    def test_1_hour_duration(self):
        """1 hour = 1.00 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(hours=1)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('1.00'))
        print(f"✓ 1-hour duration: {duration} hours")
    
    def test_8_hour_duration(self):
        """8 hours = 8.00 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(hours=8)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('8.00'))
        print(f"✓ 8-hour duration: {duration} hours")
    
    def test_8_5_hour_duration(self):
        """8.5 hours = 8.50 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(hours=8, minutes=30)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('8.50'))
        print(f"✓ 8.5-hour duration: {duration} hours")
    
    def test_9_hour_duration(self):
        """9 hours = 9.00 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(hours=9)
        duration = calculate_duration_hours(check_in, check_out)
        self.assertEqual(duration, Decimal('9.00'))
        print(f"✓ 9-hour duration: {duration} hours")
    
    def test_duration_with_seconds(self):
        """Duration with seconds: 1 hour 30 minutes 45 seconds = 1.51 hours"""
        check_in = timezone.now()
        check_out = check_in + timedelta(hours=1, minutes=30, seconds=45)
        duration = calculate_duration_hours(check_in, check_out)
        # 1.5125 hours rounded to 0.01 = 1.51
        self.assertEqual(duration, Decimal('1.51'))
        print(f"✓ 1h 30m 45s duration: {duration} hours")


class AttendanceStatusValidation(TestCase):
    """Test determine_attendance_status() for correct status and color"""
    
    # ===== 30-MINUTE SHIFT TESTS =====
    def test_30min_shift_absent(self):
        """30-min shift: < 15 min = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.20'),  # 12 minutes
            shift_total_hours=Decimal('0.50'),
            half_day_threshold=Decimal('0.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 30-min shift, 12-min work: {status} (Red)")
    
    def test_30min_shift_half_day(self):
        """30-min shift: 15-29 min = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.25'),  # 15 minutes
            shift_total_hours=Decimal('0.50'),
            half_day_threshold=Decimal('0.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 30-min shift, 15-min work: {status} (Yellow)")
    
    def test_30min_shift_present(self):
        """30-min shift: >= 30 min = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.50'),  # 30 minutes
            shift_total_hours=Decimal('0.50'),
            half_day_threshold=Decimal('0.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 30-min shift, 30-min work: {status} (Green)")
    
    # ===== 1-HOUR SHIFT TESTS =====
    def test_1hour_shift_absent(self):
        """1-hour shift: < 30 min = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.40'),  # 24 minutes
            shift_total_hours=Decimal('1.00'),
            half_day_threshold=Decimal('0.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 1-hour shift, 24-min work: {status} (Red)")
    
    def test_1hour_shift_half_day(self):
        """1-hour shift: 30-59 min = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.50'),  # 30 minutes
            shift_total_hours=Decimal('1.00'),
            half_day_threshold=Decimal('0.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 1-hour shift, 30-min work: {status} (Yellow)")
    
    def test_1hour_shift_present(self):
        """1-hour shift: >= 1 hour = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('1.00'),  # 1 hour
            shift_total_hours=Decimal('1.00'),
            half_day_threshold=Decimal('0.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 1-hour shift, 1-hour work: {status} (Green)")
    
    # ===== 4-HOUR SHIFT TESTS =====
    def test_4hour_shift_absent(self):
        """4-hour shift: < 2 hours = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('1.50'),  # 1.5 hours
            shift_total_hours=Decimal('4.00'),
            half_day_threshold=Decimal('2.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 4-hour shift, 1.5-hour work: {status} (Red)")
    
    def test_4hour_shift_half_day(self):
        """4-hour shift: 2-3.99 hours = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('2.50'),  # 2.5 hours
            shift_total_hours=Decimal('4.00'),
            half_day_threshold=Decimal('2.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 4-hour shift, 2.5-hour work: {status} (Yellow)")
    
    def test_4hour_shift_present(self):
        """4-hour shift: >= 4 hours = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('4.00'),  # 4 hours
            shift_total_hours=Decimal('4.00'),
            half_day_threshold=Decimal('2.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 4-hour shift, 4-hour work: {status} (Green)")
    
    # ===== 8-HOUR SHIFT TESTS =====
    def test_8hour_shift_absent(self):
        """8-hour shift: < 4 hours = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('3.50'),  # 3.5 hours
            shift_total_hours=Decimal('8.00'),
            half_day_threshold=Decimal('4.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 8-hour shift, 3.5-hour work: {status} (Red)")
    
    def test_8hour_shift_half_day(self):
        """8-hour shift: 4-7.99 hours = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('5.00'),  # 5 hours
            shift_total_hours=Decimal('8.00'),
            half_day_threshold=Decimal('4.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 8-hour shift, 5-hour work: {status} (Yellow)")
    
    def test_8hour_shift_present(self):
        """8-hour shift: >= 8 hours = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('8.50'),  # 8.5 hours
            shift_total_hours=Decimal('8.00'),
            half_day_threshold=Decimal('4.00'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 8-hour shift, 8.5-hour work: {status} (Green)")
    
    # ===== 8.5-HOUR SHIFT TESTS =====
    def test_8_5hour_shift_absent(self):
        """8.5-hour shift: < 4.25 hours = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('4.00'),  # 4 hours
            shift_total_hours=Decimal('8.50'),
            half_day_threshold=Decimal('4.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 8.5-hour shift, 4-hour work: {status} (Red)")
    
    def test_8_5hour_shift_half_day(self):
        """8.5-hour shift: 4.25-8.49 hours = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('5.00'),  # 5 hours
            shift_total_hours=Decimal('8.50'),
            half_day_threshold=Decimal('4.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 8.5-hour shift, 5-hour work: {status} (Yellow)")
    
    def test_8_5hour_shift_present(self):
        """8.5-hour shift: >= 8.5 hours = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('8.50'),  # 8.5 hours
            shift_total_hours=Decimal('8.50'),
            half_day_threshold=Decimal('4.25'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 8.5-hour shift, 8.5-hour work: {status} (Green)")
    
    # ===== 9-HOUR SHIFT TESTS =====
    def test_9hour_shift_absent(self):
        """9-hour shift: < 4.5 hours = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('4.00'),  # 4 hours
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ 9-hour shift, 4-hour work: {status} (Red)")
    
    def test_9hour_shift_half_day(self):
        """9-hour shift: 4.5-8.99 hours = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('5.00'),  # 5 hours
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ 9-hour shift, 5-hour work: {status} (Yellow)")
    
    def test_9hour_shift_present(self):
        """9-hour shift: >= 9 hours = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('9.50'),  # 9.5 hours
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ 9-hour shift, 9.5-hour work: {status} (Green)")
    
    # ===== EDGE CASE: NO CHECKOUT =====
    def test_no_checkout(self):
        """No checkout recorded = Checked-In Only (Blue)"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('0.00'),
            shift_total_hours=Decimal('8.00'),
            half_day_threshold=Decimal('4.00'),
            has_checkout=False
        )
        self.assertEqual(status, 'checked_in_only')
        self.assertEqual(color, '#007AFF')
        print(f"✓ No checkout: {status} (Blue)")


class EdgeCaseValidation(TestCase):
    """Test edge cases and boundary conditions"""
    
    def test_exact_half_day_threshold(self):
        """Exactly at half-day threshold = Half-Day"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('4.50'),  # Exactly 50%
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'half_day')
        self.assertEqual(color, '#FFCC00')
        print(f"✓ Exactly at half-day threshold: {status} (Yellow)")
    
    def test_just_below_half_day_threshold(self):
        """Just below half-day threshold = Absent"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('4.49'),  # Just below 50%
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'absent')
        self.assertEqual(color, '#FF3B30')
        print(f"✓ Just below half-day threshold: {status} (Red)")
    
    def test_exact_full_day_threshold(self):
        """Exactly at full-day threshold = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('9.00'),  # Exactly 100%
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ Exactly at full-day threshold: {status} (Green)")
    
    def test_just_above_full_day_threshold(self):
        """Just above full-day threshold = Present"""
        status, color = determine_attendance_status(
            duration_hours=Decimal('9.01'),  # Just above 100%
            shift_total_hours=Decimal('9.00'),
            half_day_threshold=Decimal('4.50'),
            has_checkout=True
        )
        self.assertEqual(status, 'present')
        self.assertEqual(color, '#34C759')
        print(f"✓ Just above full-day threshold: {status} (Green)")
    
    def test_seconds_level_precision(self):
        """Test seconds-level precision in duration calculation"""
        check_in = timezone.now()
        # 1 hour 30 minutes 45 seconds
        check_out = check_in + timedelta(hours=1, minutes=30, seconds=45)
        duration = calculate_duration_hours(check_in, check_out)
        # Should be 1.5125 hours, rounded to 1.51
        self.assertEqual(duration, Decimal('1.51'))
        print(f"✓ Seconds-level precision: {duration} hours")
    
    def test_very_small_shift_1_minute(self):
        """Very small shift: 1 minute = 0.02 hours"""
        shift = Shift.objects.create(
            name="1-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 1),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        threshold = get_shift_half_day_threshold(shift)
        # 1 minute = 0.0167 hours, rounded to 0.02
        self.assertEqual(total_hours, Decimal('0.02'))
        # Half-day = 0.01 hours
        self.assertEqual(threshold, Decimal('0.01'))
        print(f"✓ 1-minute shift: {total_hours} hours, threshold: {threshold} hours")
    
    def test_very_small_shift_15_minutes(self):
        """Very small shift: 15 minutes = 0.25 hours"""
        shift = Shift.objects.create(
            name="15-Min Shift",
            start_time=time(9, 0),
            end_time=time(9, 15),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(total_hours, Decimal('0.25'))
        self.assertEqual(threshold, Decimal('0.12'))  # Rounded to 0.01
        print(f"✓ 15-minute shift: {total_hours} hours, threshold: {threshold} hours")


class OvernightShiftValidation(TestCase):
    """Test overnight shift calculations"""
    
    def test_overnight_shift_10pm_to_6am(self):
        """Overnight: 10 PM - 6 AM = 8 hours"""
        shift = Shift.objects.create(
            name="Night Shift",
            start_time=time(22, 0),
            end_time=time(6, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(total_hours, Decimal('8.00'))
        self.assertEqual(threshold, Decimal('4.00'))
        print(f"✓ Overnight shift (10 PM - 6 AM): {total_hours} hours, threshold: {threshold} hours")
    
    def test_overnight_shift_9pm_to_7am(self):
        """Overnight: 9 PM - 7 AM = 10 hours"""
        shift = Shift.objects.create(
            name="Long Night Shift",
            start_time=time(21, 0),
            end_time=time(7, 0),
            is_active=True
        )
        total_hours = get_shift_total_hours(shift)
        threshold = get_shift_half_day_threshold(shift)
        self.assertEqual(total_hours, Decimal('10.00'))
        self.assertEqual(threshold, Decimal('5.00'))
        print(f"✓ Overnight shift (9 PM - 7 AM): {total_hours} hours, threshold: {threshold} hours")


# ============================================================================
# MANUAL TEST FUNCTION (for running outside Django test framework)
# ============================================================================

def manual_validation_test():
    """
    Run manual validation tests without Django test framework.
    
    Usage:
        python manage.py shell
        >>> from employees.test_shift_attendance_validation import manual_validation_test
        >>> manual_validation_test()
    """
    from decimal import Decimal
    from employees.shift_attendance_logic import (
        determine_attendance_status,
    )
    
    print("\n" + "="*80)
    print("SHIFT-BASED ATTENDANCE VALIDATION TEST")
    print("="*80 + "\n")
    
    test_cases = [
        # (duration, shift_hours, threshold, expected_status, description)
        (Decimal('0.20'), Decimal('0.50'), Decimal('0.25'), 'absent', '30-min shift, 12-min work'),
        (Decimal('0.25'), Decimal('0.50'), Decimal('0.25'), 'half_day', '30-min shift, 15-min work'),
        (Decimal('0.50'), Decimal('0.50'), Decimal('0.25'), 'present', '30-min shift, 30-min work'),
        
        (Decimal('0.40'), Decimal('1.00'), Decimal('0.50'), 'absent', '1-hour shift, 24-min work'),
        (Decimal('0.50'), Decimal('1.00'), Decimal('0.50'), 'half_day', '1-hour shift, 30-min work'),
        (Decimal('1.00'), Decimal('1.00'), Decimal('0.50'), 'present', '1-hour shift, 1-hour work'),
        
        (Decimal('1.50'), Decimal('4.00'), Decimal('2.00'), 'absent', '4-hour shift, 1.5-hour work'),
        (Decimal('2.50'), Decimal('4.00'), Decimal('2.00'), 'half_day', '4-hour shift, 2.5-hour work'),
        (Decimal('4.00'), Decimal('4.00'), Decimal('2.00'), 'present', '4-hour shift, 4-hour work'),
        
        (Decimal('3.50'), Decimal('8.00'), Decimal('4.00'), 'absent', '8-hour shift, 3.5-hour work'),
        (Decimal('5.00'), Decimal('8.00'), Decimal('4.00'), 'half_day', '8-hour shift, 5-hour work'),
        (Decimal('8.50'), Decimal('8.00'), Decimal('4.00'), 'present', '8-hour shift, 8.5-hour work'),
        
        (Decimal('4.00'), Decimal('8.50'), Decimal('4.25'), 'absent', '8.5-hour shift, 4-hour work'),
        (Decimal('5.00'), Decimal('8.50'), Decimal('4.25'), 'half_day', '8.5-hour shift, 5-hour work'),
        (Decimal('8.50'), Decimal('8.50'), Decimal('4.25'), 'present', '8.5-hour shift, 8.5-hour work'),
        
        (Decimal('4.00'), Decimal('9.00'), Decimal('4.50'), 'absent', '9-hour shift, 4-hour work'),
        (Decimal('5.00'), Decimal('9.00'), Decimal('4.50'), 'half_day', '9-hour shift, 5-hour work'),
        (Decimal('9.50'), Decimal('9.00'), Decimal('4.50'), 'present', '9-hour shift, 9.5-hour work'),
    ]
    
    passed = 0
    failed = 0
    
    for duration, shift_hours, threshold, expected_status, description in test_cases:
        status, color = determine_attendance_status(
            duration_hours=duration,
            shift_total_hours=shift_hours,
            half_day_threshold=threshold,
            has_checkout=True
        )
        
        if status == expected_status:
            print(f"✓ PASS: {description}")
            print(f"        Status: {status}, Color: {color}\n")
            passed += 1
        else:
            print(f"✗ FAIL: {description}")
            print(f"        Expected: {expected_status}, Got: {status}\n")
            failed += 1
    
    print("="*80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("="*80 + "\n")
    
    if failed == 0:
        print("✓ ALL TESTS PASSED - Shift-based attendance system is working correctly!")
    else:
        print(f"✗ {failed} TEST(S) FAILED - Please review the logic")
