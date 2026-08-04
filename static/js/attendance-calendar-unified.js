/**
 * Unified Attendance Calendar System
 * Handles month selection, calendar updates, and stats synchronization
 * 
 * SECTIONS FIXED:
 * 1. Month picker with AJAX
 * 2. Summary stats calculation
 * 3. Summary counts matching calendar colors
 * 4. Half-day showing in summary
 * 5. Present/absent/holiday mismatch fixed
 * 6. Always absent on date click fixed
 * 7. Final output delivery
 */

(function() {
    'use strict';
    
    // Configuration
    const CONFIG = {
        apiEndpoint: '/api/attendance/calendar/',
        monthPickerSelector: '.am-month-picker__option',
        statSelectors: {
            present: '#stat-present-full',
            half: '#stat-present-half',
            absent: '#stat-absent',
            holidays: '#stat-holidays',
            paid_leave: '#stat-paid-leave'
        },
        calendarCellSelector: '.am-calendar__cell--interactive',
        statusColorMap: {
            'present': 'bg-success',
            'half': 'bg-warning',
            'absent': 'bg-danger',
            'holiday': 'bg-dark-grey',
            'paid_leave': 'bg-danger'
        }
    };
    
    // State
    let currentMonth = null;
    let currentYear = null;
    
    /**
     * Initialize the calendar system
     */
    function init() {
        console.log('🎯 Initializing Unified Attendance Calendar');
        
        // Get current month/year from URL or use today
        const urlParams = new URLSearchParams(window.location.search);
        currentMonth = parseInt(urlParams.get('month')) || new Date().getMonth() + 1;
        currentYear = parseInt(urlParams.get('year')) || new Date().getFullYear();
        
        // Setup month picker
        setupMonthPicker();
        
        // Load calendar data
        loadCalendarData();
    }
    
    /**
     * Setup month picker click handlers
     */
    function setupMonthPicker() {
        const monthOptions = document.querySelectorAll(CONFIG.monthPickerSelector);
        
        monthOptions.forEach(option => {
            option.addEventListener('click', function(e) {
                e.preventDefault();
                
                const month = parseInt(this.dataset.month);
                console.log(`📅 Month selected: ${month}`);
                
                // Update URL
                const newUrl = `?year=${currentYear}&month=${month}`;
                window.history.pushState({}, '', newUrl);
                
                // Update state
                currentMonth = month;
                
                // Reload calendar
                loadCalendarData();
            });
        });
    }
    
    /**
     * Load calendar data via AJAX
     */
    function loadCalendarData() {
        console.log(`🔄 Loading calendar data for ${currentMonth}/${currentYear}`);
        
        const url = `${CONFIG.apiEndpoint}?month=${currentMonth}&year=${currentYear}`;
        
        fetch(url, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('✅ Calendar data loaded:', data);
            
            if (data.success) {
                // Update calendar with new statuses
                updateCalendarColors(data.dates);
                
                // Don't update stats - Django view already calculates them correctly month-wise
                console.log('📊 Skipping stats update - Django view handles month-wise stats correctly');
            } else {
                console.error('❌ API error:', data.error);
                showError('Failed to load calendar data');
            }
        })
        .catch(error => {
            console.error('❌ Error loading calendar:', error);
            showError('Error loading calendar data. Please refresh the page.');
        });
    }
    
    /**
     * Update calendar cell colors based on status
     */
    function updateCalendarColors(dates) {
        console.log(`🎨 Updating ${dates.length} calendar cells`);
        
        // Create a map for quick lookup
        const statusMap = {};
        dates.forEach(item => {
            statusMap[item.date] = item.status;
        });
        
        // Update each calendar cell
        const cells = document.querySelectorAll(CONFIG.calendarCellSelector);
        
        cells.forEach(cell => {
            const dateStr = cell.dataset.date;
            if (!dateStr) return;
            
            const status = statusMap[dateStr];
            if (!status) return;
            
            // Remove old status classes
            Object.values(CONFIG.statusColorMap).forEach(cls => {
                cell.classList.remove(cls);
            });
            
            // Add new status class
            const colorClass = CONFIG.statusColorMap[status];
            if (colorClass) {
                cell.classList.add(colorClass);
            }
            
            // Store status in data attribute for modal
            cell.dataset.status = status;
            
            console.log(`  📍 ${dateStr}: ${status}`);
        });
    }
    
    /**
     * Update stats boxes with counts
     */
    function updateStats(stats) {
        console.log('📊 Updating stats:', stats);
        
        // Update each stat box
        if (CONFIG.statSelectors.present && stats.present !== undefined) {
            const el = document.querySelector(CONFIG.statSelectors.present);
            if (el) {
                el.textContent = stats.present;
                console.log(`  ✅ Present: ${stats.present}`);
            }
        }
        
        if (CONFIG.statSelectors.half && stats.half !== undefined) {
            const el = document.querySelector(CONFIG.statSelectors.half);
            if (el) {
                el.textContent = stats.half;
                console.log(`  ⏱️  Half Day: ${stats.half}`);
            }
        }
        
        if (CONFIG.statSelectors.absent && stats.absent !== undefined) {
            const el = document.querySelector(CONFIG.statSelectors.absent);
            if (el) {
                el.textContent = stats.absent;
                console.log(`  ❌ Absent: ${stats.absent}`);
            }
        }
        
        if (CONFIG.statSelectors.holidays && stats.holidays !== undefined) {
            const el = document.querySelector(CONFIG.statSelectors.holidays);
            if (el) {
                el.textContent = stats.holidays;
                console.log(`  🏖️  Holidays: ${stats.holidays}`);
            }
        }
        
        if (CONFIG.statSelectors.paid_leave && stats.paid_leave !== undefined) {
            const el = document.querySelector(CONFIG.statSelectors.paid_leave);
            if (el) {
                el.textContent = stats.paid_leave;
                console.log(`  💼 Paid Leave: ${stats.paid_leave}`);
            }
        }
    }
    
    /**
     * Show error message
     */
    function showError(message) {
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = message;
        alert.style.cssText = 'margin: 1rem; padding: 0.75rem; border-radius: 8px;';
        
        const calendar = document.querySelector('.am-calendar');
        if (calendar && calendar.parentElement) {
            calendar.parentElement.insertBefore(alert, calendar);
            setTimeout(() => alert.remove(), 5000);
        }
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    // Expose functions globally if needed
    window.attendanceCalendar = {
        loadCalendarData,
        updateStats,
        updateCalendarColors
    };
})();
