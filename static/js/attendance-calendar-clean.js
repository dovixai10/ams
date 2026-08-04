/**
 * CLEAN ATTENDANCE CALENDAR - NO LOGIC, NO FLICKER
 * 
 * CRITICAL RULES:
 * 1. ONLY fetch backend data
 * 2. ONLY apply colors from backend
 * 3. NEVER recalculate status
 * 4. NEVER override backend status
 * 5. NEVER use fallback logic
 * 6. Single render, no re-renders
 */

(function() {
    'use strict';
    
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCalendar);
    } else {
        initCalendar();
    }
    
    function initCalendar() {
        console.log('[CALENDAR] Initializing clean calendar system');
        
        // Get current month/year from URL or use today
        const urlParams = new URLSearchParams(window.location.search);
        const month = parseInt(urlParams.get('month')) || new Date().getMonth() + 1;
        const year = parseInt(urlParams.get('year')) || new Date().getFullYear();
        
        // Load calendar data from backend
        loadCalendarData(year, month);
        
        // Setup month picker
        setupMonthPicker();
    }
    
    function setupMonthPicker() {
        const monthOptions = document.querySelectorAll('.am-month-picker__option');
        
        monthOptions.forEach(option => {
            option.addEventListener('click', function(e) {
                e.preventDefault();
                
                const month = parseInt(this.dataset.month);
                const year = new Date().getFullYear();
                
                // Update URL
                const newUrl = `?year=${year}&month=${month}`;
                window.history.pushState({}, '', newUrl);
                
                // Reload calendar
                loadCalendarData(year, month);
            });
        });
    }
    
    function loadCalendarData(year, month) {
        console.log(`[CALENDAR] Fetching data for ${year}-${month}`);
        
        const url = `/api/attendance/calendar/unified/?year=${year}&month=${month}`;
        
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
            console.log('[CALENDAR] Backend data received:', data);
            
            if (data.success) {
                // Apply colors from backend - SINGLE RENDER
                applyBackendColors(data.days);
                
                // Update stats from backend
                updateStats(data.stats);
                
                console.log('[CALENDAR] ✓ Colors applied - NO further updates');
            } else {
                console.error('[CALENDAR] API error:', data.error);
            }
        })
        .catch(error => {
            console.error('[CALENDAR] Error:', error);
        });
    }
    
    function applyBackendColors(daysData) {
        // Apply colors from backend data to calendar cells
        // CRITICAL: Use ONLY backend status, NEVER recalculate
        const cells = document.querySelectorAll('.am-calendar__cell--interactive');
        
        cells.forEach(cell => {
            const dateStr = cell.dataset.date;
            if (!dateStr) return;
            
            const dayData = daysData[dateStr];
            if (!dayData) return;
            
            const status = dayData.status;
            const color = dayData.color;
            
            // Remove all old status classes
            removeAllStatusClasses(cell);
            
            // Add new status class based on backend status
            const statusClass = getStatusClass(status);
            if (statusClass) {
                cell.classList.add(statusClass);
            }
            
            // Apply background color from backend
            if (color) {
                cell.style.backgroundColor = color;
            }
            
            // Store status for modal
            cell.dataset.status = status;
            
            console.log(`[CALENDAR] ${dateStr}: ${status} (${color})`);
        });
    }
    
    function removeAllStatusClasses(cell) {
        // Remove all attendance status classes
        const statusClasses = [
            'am-calendar__cell--present',
            'am-calendar__cell--halfday',
            'am-calendar__cell--half-day',
            'am-calendar__cell--half',
            'am-calendar__cell--absent',
            'am-calendar__cell--holiday',
            'am-calendar__cell--paid-leave',
            'am-calendar__cell--paid_leave',
            'am-calendar__cell--sandwich-leave',
            'am-calendar__cell--sandwich_leave',
            'am-calendar__cell--future',
            'am-calendar__cell--checked-in',
            'bg-success',
            'bg-warning',
            'bg-danger',
            'bg-dark-grey',
            'bg-info'
        ];
        
        statusClasses.forEach(cls => {
            cell.classList.remove(cls);
        });
    }
    
    function getStatusClass(status) {
        // Map backend status to CSS class
        const statusMap = {
            'present': 'am-calendar__cell--present',
            'half_day': 'am-calendar__cell--halfday',
            'absent': 'am-calendar__cell--absent',
            'holiday': 'am-calendar__cell--holiday',
            'paid_leave': 'am-calendar__cell--paid-leave',
            'sandwich_leave': 'am-calendar__cell--sandwich-leave',
            'future': 'am-calendar__cell--future',
            'checked_in_only': 'am-calendar__cell--checked-in'
        };
        
        return statusMap[status] || null;
    }
    
    function updateStats(stats) {
        // Update stats boxes with backend values
        if (!stats) return;
        
        console.log('[CALENDAR] Updating stats:', stats);
        
        // Find stat boxes
        const statBoxes = document.querySelectorAll('.am-stat');
        
        if (statBoxes.length >= 5) {
            // Update each stat
            const statLabels = Array.from(statBoxes).map(box => 
                box.querySelector('.am-stat__label')?.textContent.toLowerCase() || ''
            );
            
            statBoxes.forEach((box, index) => {
                const label = statLabels[index];
                const valueEl = box.querySelector('.am-stat__value');
                
                if (!valueEl) return;
                
                if (label.includes('present') && !label.includes('half')) {
                    valueEl.textContent = stats.present || 0;
                } else if (label.includes('half')) {
                    valueEl.textContent = stats.half_day || 0;
                } else if (label.includes('absent')) {
                    valueEl.textContent = stats.absent || 0;
                } else if (label.includes('holiday')) {
                    valueEl.textContent = stats.holidays || 0;
                } else if (label.includes('paid')) {
                    valueEl.textContent = stats.paid_leave || 0;
                }
            });
            
            console.log('[CALENDAR] Stats updated');
        }
    }
    
    // Export for global access
    window.loadCalendarData = loadCalendarData;
    
})();
