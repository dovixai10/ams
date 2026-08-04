/**
 * Attendance Calendar Manager
 * Handles month picker, calendar reload, and stats calculations
 */

(function() {
  'use strict';

  // ============================================
  // MONTH PICKER FUNCTIONALITY
  // ============================================

  class MonthPicker {
    constructor() {
      this.trigger = document.querySelector('.am-month-picker__trigger');
      this.panel = document.querySelector('.am-month-picker__panel');
      this.backdrop = document.querySelector('.am-month-picker__backdrop');
      this.searchInput = document.querySelector('.am-month-picker__search-input');
      this.listItems = document.querySelectorAll('.am-month-picker__item');
      
      if (!this.trigger || !this.panel) {
        console.warn('Month picker elements not found');
        return;
      }
      
      this.init();
    }

    init() {
      // Trigger click to toggle
      this.trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggle();
      });

      // Search functionality
      if (this.searchInput) {
        this.searchInput.addEventListener('input', (e) => {
          this.filterMonths(e.target.value);
        });
      }

      // Month selection
      this.listItems.forEach(item => {
        const link = item.querySelector('.am-month-picker__option');
        if (link) {
          link.addEventListener('click', (e) => {
            e.preventDefault();
            const month = link.getAttribute('data-month');
            this.selectMonth(month);
          });
        }
      });

      // Close on backdrop click
      if (this.backdrop) {
        this.backdrop.addEventListener('click', () => {
          this.close();
        });
      }

      // Close on outside click
      document.addEventListener('click', (e) => {
        if (!e.target.closest('.am-month-picker')) {
          this.close();
        }
      });

      // Close on Escape key
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          this.close();
        }
      });
    }

    toggle() {
      if (this.isOpen()) {
        this.close();
      } else {
        this.open();
      }
    }

    open() {
      this.panel.classList.add('am-month-picker__panel--open');
      this.backdrop.classList.add('am-month-picker__backdrop--active');
      this.trigger.setAttribute('aria-expanded', 'true');
      
      // Focus search input
      if (this.searchInput) {
        setTimeout(() => this.searchInput.focus(), 100);
      }
    }

    close() {
      this.panel.classList.remove('am-month-picker__panel--open');
      this.backdrop.classList.remove('am-month-picker__backdrop--active');
      this.trigger.setAttribute('aria-expanded', 'false');
      
      // Clear search
      if (this.searchInput) {
        this.searchInput.value = '';
        this.filterMonths('');
      }
    }

    isOpen() {
      return this.panel.classList.contains('am-month-picker__panel--open');
    }

    filterMonths(query) {
      const lowerQuery = query.toLowerCase();
      
      this.listItems.forEach(item => {
        const link = item.querySelector('.am-month-picker__option');
        const label = link.getAttribute('data-label');
        
        if (label.includes(lowerQuery)) {
          item.classList.remove('am-month-picker__item--hidden');
        } else {
          item.classList.add('am-month-picker__item--hidden');
        }
      });
    }

    selectMonth(month) {
      // Get current year from URL or use current year
      const urlParams = new URLSearchParams(window.location.search);
      const year = urlParams.get('year') || new Date().getFullYear();
      
      // Close the picker
      this.close();
      
      // Navigate to selected month (page reload will recalculate stats)
      window.location.href = `?year=${year}&month=${month}`;
    }
  }

  // ============================================
  // CALENDAR STATS
  // ============================================

  // NOTE: Stats are now fully rendered by Django on the server.
  // This file no longer recalculates or mutates any calendar
  // classes or stats numbers. The backend is the single
  // source of truth for counts and colors.

  // ============================================
  // CALENDAR RELOAD TRIGGERS
  // ============================================

  class CalendarReloadManager {
    constructor() {
      this.setupReloadTriggers();
    }

    setupReloadTriggers() {
      // Listen for custom events from other parts of the app
      document.addEventListener('leave:approved', () => {
        this.reloadCalendar('Leave approved');
      });

      document.addEventListener('leave:rejected', () => {
        this.reloadCalendar('Leave rejected');
      });

      document.addEventListener('leave:applied', () => {
        this.reloadCalendar('Leave applied');
      });

      document.addEventListener('attendance:checkin', () => {
        this.reloadCalendar('Check-in recorded');
      });

      document.addEventListener('attendance:checkout', () => {
        this.reloadCalendar('Check-out recorded');
      });
    }

    reloadCalendar(reason) {
      console.log(`Reloading calendar: ${reason}`);
      
      // Get current month/year from URL
      const urlParams = new URLSearchParams(window.location.search);
      const year = urlParams.get('year') || new Date().getFullYear();
      const month = urlParams.get('month') || new Date().getMonth() + 1;
      
      // Reload page with same month/year
      window.location.href = `?year=${year}&month=${month}`;
    }

    // Public method to trigger reload from other scripts
    static reload(reason = 'Manual reload') {
      const manager = new CalendarReloadManager();
      manager.reloadCalendar(reason);
    }
  }

  // ============================================
  // ATTENDANCE MODAL INTEGRATION
  // ============================================

  class AttendanceModalManager {
    constructor() {
      this.modal = document.getElementById('attendanceModal');
      this.calendarCells = document.querySelectorAll('.am-calendar__cell--interactive');
      
      if (!this.modal || this.calendarCells.length === 0) {
        console.warn('Attendance modal or calendar cells not found');
        return;
      }
      
      this.init();
    }

    init() {
      this.calendarCells.forEach(cell => {
        cell.addEventListener('click', (e) => {
          e.preventDefault();
          this.openModal(cell);
        });
      });
    }

    openModal(cell) {
      const date = cell.getAttribute('data-date');
      const status = cell.getAttribute('data-status');
      
      if (!date) {
        console.warn('No date found on cell');
        return;
      }

      // Get employee ID from screen element
      const screen = document.querySelector('.am-screen');
      const employeeId = screen ? screen.getAttribute('data-employee-id') : null;
      
      if (!employeeId) {
        console.warn('No employee ID found');
        return;
      }

      // Fetch attendance details
      this.fetchAttendanceDetails(employeeId, date);
    }

    fetchAttendanceDetails(employeeId, date) {
      const url = `/api/attendance/${employeeId}/${date}/`;
      
      fetch(url, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
      })
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        this.populateModal(data);
        const bsModal = new bootstrap.Modal(this.modal);
        bsModal.show();
      })
      .catch(error => {
        console.error('Error fetching attendance details:', error);
        alert('Error loading attendance details. Please try again.');
      });
    }

    populateModal(data) {
      // Update date
      const dateElement = document.getElementById('modal-date');
      if (dateElement && data.weekday) {
        dateElement.textContent = data.weekday;
      }

      // Update check-in
      const checkinElement = document.getElementById('modal-checkin');
      const checkinTimestamp = document.getElementById('modal-checkin-timestamp');
      if (data.check_in_time_display) {
        if (checkinElement) checkinElement.textContent = data.check_in_time_display;
        if (checkinTimestamp) checkinTimestamp.textContent = data.check_in_time_display;
      } else {
        if (checkinElement) checkinElement.textContent = 'Not recorded';
        if (checkinTimestamp) checkinTimestamp.textContent = 'Not recorded';
      }

      // Update check-out
      const checkoutElement = document.getElementById('modal-checkout');
      const checkoutTimestamp = document.getElementById('modal-checkout-timestamp');
      if (data.check_out_time_display) {
        if (checkoutElement) checkoutElement.textContent = data.check_out_time_display;
        if (checkoutTimestamp) checkoutTimestamp.textContent = data.check_out_time_display;
      } else {
        if (checkoutElement) checkoutElement.textContent = 'Not recorded';
        if (checkoutTimestamp) checkoutTimestamp.textContent = 'Not recorded';
      }

      // Update duration
      const durationElement = document.getElementById('modal-duration');
      if (durationElement) {
        durationElement.textContent = data.total_duration_display || '—';
      }

      // Update status
      const statusElement = document.getElementById('modal-status');
      if (statusElement && data.status_label) {
        statusElement.innerHTML = `<span class="badge bg-primary">${data.status_label}</span>`;
      }
    }
  }

  // ============================================
  // INITIALIZATION
  // ============================================

  function init() {
    // Wait for DOM to be fully loaded
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initializeComponents);
    } else {
      initializeComponents();
    }
  }

  function initializeComponents() {
    console.log('Initializing attendance calendar components...');
    
    // Initialize month picker (pure UI, navigation only)
    new MonthPicker();

    // Setup attendance modal (opens details, does not recolor calendar)
    new AttendanceModalManager();
    
    console.log('Attendance calendar components initialized');
  }

  // Start initialization
  init();

  // Export for external use
  window.CalendarReloadManager = CalendarReloadManager;

})();
