/**
 * Attendance Calendar Loader
 * Dynamically loads calendar data from API and updates the calendar view
 */

// Wait for DOM to be fully ready
function initCalendarLoader() {
    const calendarGrid = document.querySelector('.am-calendar__grid');
    if (!calendarGrid) {
        console.warn('Calendar grid not found, retrying...');
        setTimeout(initCalendarLoader, 500);
        return;
    }

    // Get employee ID and current month/year from page
    const employeeId = document.querySelector('[data-employee-id]')?.dataset.employeeId;
    const monthPicker = document.querySelector('.am-month-picker');
    
    console.log('Calendar Loader: Employee ID:', employeeId);
    if (!employeeId) {
        console.error('Employee ID not found in data attribute');
        return;
    }

    // Load calendar on page load
    loadCalendarData();

    // Handle month picker changes with AJAX
    if (monthPicker) {
        const monthOptions = monthPicker.querySelectorAll('.am-month-picker__option');
        monthOptions.forEach(option => {
            option.addEventListener('click', function(e) {
                e.preventDefault();
                const month = this.dataset.month;
                const urlParams = new URLSearchParams(window.location.search);
                const year = parseInt(urlParams.get('year')) || new Date().getFullYear();
                
                console.log('Month selected:', month, 'Year:', year);
                
                // Update URL without full page reload
                const newUrl = `?year=${year}&month=${month}`;
                window.history.pushState({}, '', newUrl);
                
                // Reload calendar data
                loadCalendarData(year, parseInt(month));
            });
        });
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCalendarLoader);
} else {
    // DOM is already loaded
    initCalendarLoader();
}

// Make loadCalendarData available globally for refresh calls
window.loadCalendarData = loadCalendarData;

/**
 * Load calendar data from API
 * CRITICAL: ONLY fetch backend status - NO recalculation
 */
function loadCalendarData(year, month) {
    // Get current month/year if not provided
    if (!year || !month) {
        const urlParams = new URLSearchParams(window.location.search);
        year = parseInt(urlParams.get('year')) || new Date().getFullYear();
        month = parseInt(urlParams.get('month')) || new Date().getMonth() + 1;
    }

    const employeeId = document.querySelector('[data-employee-id]')?.dataset.employeeId || 
                      document.querySelector('.am-screen')?.dataset.employeeId;
    
    if (!employeeId) {
        console.error('Employee ID not found. Cannot load calendar data.');
        return;
    }
    
    const url = `/api/attendance/${employeeId}/month/?year=${year}&month=${month}`;

    console.log('[CALENDAR] Fetching backend status from:', url);

    fetch(url, {
        headers: {
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        credentials: 'same-origin'
    })
        .then(response => {
            console.log('[CALENDAR] API Response status:', response.status);
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || `HTTP error! status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('[CALENDAR] Backend status received:', data);
            if (data.success !== false && data.days) {
                // CRITICAL: Apply ONLY backend status - single render, no recalculation
                updateCalendarUI(data);
                console.log('[CALENDAR] ✓ Backend status applied - NO further updates will be made');
            } else {
                console.error('[CALENDAR] Failed to load:', data.error || 'Unknown error');
            }
        })
        .catch(error => {
            console.error('[CALENDAR] Error:', error);
        });
}

/**
 * Apply unified day status to calendar cell
 * CRITICAL: Single source of truth for status mapping - EXACTLY as Django API provides
 * NO OVERRIDES - Use Django status directly
 * FIX: Remove fallback logic that forces "Absent" on missing status
 */
function applyDayStatus(cell, dayData) {
    if (!dayData) return;
    
    // Remove all old status classes
    const classesToRemove = [
        'am-calendar__cell--present',
        'am-calendar__cell--halfday',
        'am-calendar__cell--half',
        'am-calendar__cell--half-day',
        'am-calendar__cell--absent',
        'am-calendar__cell--holiday',
        'am-calendar__cell--paid-leave',
        'am-calendar__cell--paid_leave',
        'am-calendar__cell--sandwich-leave',
        'am-calendar__cell--sandwich_leave',
        'am-calendar__cell--future',
        'am-calendar__cell--checked-in'
    ];
    
    let classList = Array.from(cell.classList);
    classList = classList.filter(cls => !classesToRemove.includes(cls));
    
    // EXACT STATUS MAPPING FROM DJANGO API - NO MODIFICATIONS
    // STATUS → COLOR mapping (exactly as specified in requirements)
    let statusClass = null;
    let statusLabel = 'No data';
    let bgColor = null;
    
    // Use status from Django API - EXACT match
    let djangoStatus = dayData.status || dayData.status_color || '';
    djangoStatus = djangoStatus.toLowerCase().trim();
    
    // DIRECT MAPPING: Django status → CSS class (NO logic, NO overrides)
    switch (djangoStatus) {
        case 'present':
            statusClass = 'am-calendar__cell--present';
            statusLabel = 'Present';
            bgColor = '#34C759';
            break;
        case 'half_day':
        case 'halfday':
        case 'half':
            statusClass = 'am-calendar__cell--halfday';
            statusLabel = 'Half Day';
            bgColor = '#FFCC00';
            break;
        case 'absent':
            statusClass = 'am-calendar__cell--absent';
            statusLabel = 'Absent';
            bgColor = '#FF3B30';
            break;
        case 'holiday':
            statusClass = 'am-calendar__cell--holiday';
            statusLabel = 'Holiday';
            bgColor = '#9E9E9E';
            break;
        case 'paid_leave':
        case 'paid-leave':
            statusClass = 'am-calendar__cell--paid-leave';
            statusLabel = 'Paid Leave';
            bgColor = '#2196F3';
            break;
        case 'future':
            statusClass = 'am-calendar__cell--future';
            statusLabel = 'Future';
            break;
        default:
            // FIX: Do NOT force "Absent" or "Future" if no status from Django
            // If Django API didn't provide status, don't override with fallback logic
            // Just keep the cell as-is (pre-rendered by Django template)
            console.warn(`[Calendar] No status from API for date ${cell.dataset.date}, keeping pre-rendered status`);
            return;
    }
    
    // Apply the status class ONLY ONCE - never override
    if (statusClass && !classList.includes(statusClass)) {
        classList.push(statusClass);
        cell.className = classList.join(' ');
        
        // Apply background color from backend status
        if (bgColor) {
            cell.style.backgroundColor = bgColor;
        }
        
        cell.setAttribute('aria-label', `${cell.dataset.date} - ${statusLabel}`);
        cell.dataset.status = djangoStatus;
        cell.dataset.hasAttendance = dayData.has_attendance ? 'true' : 'false';
    }
}

/**
 * Update calendar UI with live data
 * CRITICAL: Apply colors ONLY ONCE - use Django API as single source of truth
 * NO RE-RENDERS - NO FLICKERING
 * FIX: Remove dataset.processed check that blocks valid updates
 */
function updateCalendarUI(data) {
    const calendarGrid = document.querySelector('.am-calendar__grid');
    if (!calendarGrid) {
        console.error('Calendar grid not found');
        return;
    }

    // Get all calendar cells
    const cells = calendarGrid.querySelectorAll('.am-calendar__cell--interactive');
    
    if (!data.days || Object.keys(data.days).length === 0) {
        console.warn('No days data received from API');
        return;
    }
    
    // CRITICAL: Apply status ONLY ONCE per day - prevent flickering
    // Track which cells we've updated to prevent duplicate processing
    const processedCells = new Set();
    
    cells.forEach(cell => {
        const dateStr = cell.dataset.date;
        if (!dateStr) {
            return;
        }
        
        // Skip if already processed in this batch
        if (processedCells.has(dateStr)) {
            return;
        }
        
        // Try to find matching day data - API returns dates as YYYY-MM-DD strings
        let dayData = data.days[dateStr];
        
        // If not found, try to match by parsing the date
        if (!dayData) {
            // Try to find by matching date format
            for (const key in data.days) {
                if (key === dateStr || key.startsWith(dateStr)) {
                    dayData = data.days[key];
                    break;
                }
            }
        }
        
        if (dayData) {
            // Use unified status mapping function - applies color EXACTLY as Django provides
            applyDayStatus(cell, dayData);
            processedCells.add(dateStr);
        }
    });
    
    console.log(`[Calendar] Applied Django API status colors to ${processedCells.size} dates - no further updates will be made`);
}

/**
 * Update stats row with live data - Only update if stats are missing or zero
 */
function updateStatsRow(data) {
    const stats = data.stats;
    const paidLeaveBalance = data.paid_leave_balance;

    // Map stats to display values
    const present = stats.present || 0;
    const halfDay = stats.half_day || 0;
    const absent = stats.absent || 0;
    const holidays = stats.holidays || 0;
    const paidLeave = stats.paid_leave || 0;
    const attendanceRate = calculateAttendanceRate(present, halfDay, absent);

    // Update stat boxes only if they show zero (indicating they need API data)
    const statBoxes = document.querySelectorAll('.am-stat');
    if (statBoxes.length >= 5) {
        // Check if present days is zero (needs API update)
        const presentValue = statBoxes[1].querySelector('.am-stat__value').textContent;
        if (presentValue === '0' || presentValue === '') {
            // Paid Leaves - update balance
            statBoxes[0].querySelector('.am-stat__value').textContent = paidLeaveBalance;
            
            // Present
            statBoxes[1].querySelector('.am-stat__value').textContent = present;
            
            // Half Day
            statBoxes[2].querySelector('.am-stat__value').textContent = halfDay;
            
            // Absent
            statBoxes[3].querySelector('.am-stat__value').textContent = absent;
            
            // Holidays (check if this stat box exists)
            if (statBoxes[4]) {
                const holidayLabel = statBoxes[4].querySelector('.am-stat__label').textContent.toLowerCase();
                if (holidayLabel.includes('holiday')) {
                    statBoxes[4].querySelector('.am-stat__value').textContent = holidays;
                } else if (holidayLabel.includes('attendance')) {
                    statBoxes[4].querySelector('.am-stat__value').textContent = attendanceRate + '%';
                }
            }
            
            // Paid Leave stat box (if it exists separately from balance)
            if (statBoxes.length > 5) {
                const paidLeaveLabel = statBoxes[5].querySelector('.am-stat__label').textContent.toLowerCase();
                if (paidLeaveLabel.includes('paid leave')) {
                    statBoxes[5].querySelector('.am-stat__value').textContent = paidLeave;
                }
            }
            
            console.log('Updated stats from API:', { present, halfDay, absent, holidays, paidLeave, paidLeaveBalance });
        } else {
            console.log('Stats already have values, not overriding from API');
        }
    }
}

/**
 * Calculate attendance rate percentage
 */
function calculateAttendanceRate(present, halfDay, absent) {
    const total = present + halfDay + absent;
    if (total === 0) return 0;
    
    const rate = ((present + (halfDay * 0.5)) / total) * 100;
    return Math.round(rate * 10) / 10;
}
