// Check-In/Check-Out Dashboard JavaScript
// Handles time-window logic, live updates, and API calls

class CheckInDashboard {
    constructor() {
        this.employee = null;
        this.shift = null;
        this.todayAttendance = null;
        this.updateInterval = null;
        this.timeWindowCheckInterval = null;
        this.init();
    }

    async init() {
        try {
            // Load initial data
            await this.loadDashboardData();
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Start live updates
            this.startLiveUpdates();
            
            // Check time window every 30 seconds
            this.startTimeWindowCheck();
            
            console.log('Dashboard initialized successfully');
        } catch (error) {
            console.error('Dashboard initialization error:', error);
        }
    }

    async loadDashboardData() {
        try {
            const response = await fetch('/api/checkin-dashboard/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) throw new Error('Failed to load dashboard data');

            const data = await response.json();
            
            this.employee = data.employee;
            this.shift = data.shift;
            this.shiftWindow = data.shift_window || null;
            this.todayAttendance = data.today_attendance;
            
            // Update UI with data
            this.updateGreetingHeader();
            this.updateShiftInfo();
            this.updateQuickStats(data);
            this.updateNotifications(data.notifications);
            this.checkTimeWindow();
            
        } catch (error) {
            console.error('Error loading dashboard data:', error);
        }
    }

    updateGreetingHeader() {
        const now = new Date();
        const hour = now.getHours();
        
        // Set greeting and theme based on local device time
        let greeting, theme;
        
        if (hour >= 4 && hour < 11) {
            greeting = 'Good Morning';
            theme = 'sunrise';
        } else if (hour >= 11 && hour < 16) {
            greeting = 'Good Afternoon';
            theme = 'day';
        } else if (hour >= 16 && hour < 20) {
            greeting = 'Good Evening';
            theme = 'sunset';
        } else {
            greeting = 'Good Night';
            theme = 'night';
        }
        
        // Update greeting title
        document.getElementById('greetingTitle').textContent = greeting;
        
        // Update theme
        const header = document.getElementById('greetingHeader');
        header.classList.remove('sunrise', 'day', 'sunset', 'night');
        header.classList.add(theme);
        
        // Update employee name
        document.getElementById('employeeName').textContent = this.employee?.full_name || 'Loading...';
        
        // Update time
        this.updateCurrentTime();
        
        // Update weather
        this.updateWeather();
        
        // Update points
        this.updatePointsBadge();
    }

    updateCurrentTime() {
        const now = new Date();
        const options = {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        };
        
        const timeString = now.toLocaleDateString('en-US', options);
        document.getElementById('currentTime').textContent = timeString;
    }

    async updateWeather() {
        try {
            // Fetch weather for Jaipur
            const response = await fetch(
                'https://api.open-meteo.com/v1/forecast?latitude=26.9124&longitude=75.7873&current=temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m&timezone=Asia/Kolkata'
            );
            
            if (!response.ok) throw new Error('Weather API error');
            
            const data = await response.json();
            const current = data.current;
            
            // Update weather icon based on weather code
            this.updateWeatherIcon(current.weather_code, current.temperature_2m);
            
        } catch (error) {
            console.error('Weather update error:', error);
        }
    }

    updateWeatherIcon(weatherCode, temperature) {
        const iconContainer = document.getElementById('weatherIcon');
        let icon = '';
        
        // Weather code interpretation (WMO codes)
        if (weatherCode === 0 || weatherCode === 1) {
            // Clear sky or mainly clear
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <circle cx="30" cy="30" r="25" fill="#FFD700"/>
                    <circle cx="30" cy="30" r="20" fill="none" stroke="#FFA500" stroke-width="2"/>
                </svg>
            `;
        } else if (weatherCode === 2 || weatherCode === 3) {
            // Partly cloudy or overcast
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <circle cx="25" cy="20" r="15" fill="#FFD700"/>
                    <path d="M35 35 Q40 32 45 35 Q48 35 48 38 Q48 42 45 42 H20 Q16 42 16 38 Q16 35 20 35 Q22 32 28 35" fill="#D3D3D3"/>
                </svg>
            `;
        } else if (weatherCode >= 45 && weatherCode <= 48) {
            // Foggy
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <line x1="15" y1="20" x2="45" y2="20" stroke="#999" stroke-width="2"/>
                    <line x1="15" y1="30" x2="45" y2="30" stroke="#999" stroke-width="2"/>
                    <line x1="15" y1="40" x2="45" y2="40" stroke="#999" stroke-width="2"/>
                </svg>
            `;
        } else if (weatherCode >= 51 && weatherCode <= 67) {
            // Drizzle or rain
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <path d="M35 15 Q40 12 45 15 Q48 15 48 18 Q48 22 45 22 H20 Q16 22 16 18 Q16 15 20 15 Q22 12 28 15" fill="#D3D3D3"/>
                    <line x1="25" y1="28" x2="20" y2="38" stroke="#4A90E2" stroke-width="2"/>
                    <line x1="35" y1="28" x2="30" y2="38" stroke="#4A90E2" stroke-width="2"/>
                    <line x1="45" y1="28" x2="40" y2="38" stroke="#4A90E2" stroke-width="2"/>
                </svg>
            `;
        } else if (weatherCode >= 71 && weatherCode <= 77) {
            // Snow
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <path d="M35 15 Q40 12 45 15 Q48 15 48 18 Q48 22 45 22 H20 Q16 22 16 18 Q16 15 20 15 Q22 12 28 15" fill="#D3D3D3"/>
                    <text x="25" y="40" font-size="16" fill="#E0E0E0">❄ ❄ ❄</text>
                </svg>
            `;
        } else {
            // Default sun
            icon = `
                <svg width="60" height="60" viewBox="0 0 60 60" fill="none">
                    <circle cx="30" cy="30" r="15" fill="#FFD700"/>
                    <line x1="30" y1="8" x2="30" y2="2" stroke="#FFA500" stroke-width="2"/>
                    <line x1="30" y1="58" x2="30" y2="52" stroke="#FFA500" stroke-width="2"/>
                    <line x1="52" y1="30" x2="58" y2="30" stroke="#FFA500" stroke-width="2"/>
                    <line x1="8" y1="30" x2="2" y2="30" stroke="#FFA500" stroke-width="2"/>
                </svg>
            `;
        }
        
        iconContainer.innerHTML = icon;
    }

    updatePointsBadge() {
        const pointsValue = this.employee?.month_points || 0;
        document.getElementById('pointsValue').textContent = pointsValue;
    }

    updateShiftInfo() {
        if (!this.shift) {
            document.getElementById('shiftStart').textContent = 'No shift assigned';
            document.getElementById('shiftEnd').textContent = 'No shift assigned';
            return;
        }
        
        const startTime = this.formatTime(this.shift.start_time);
        const endTime = this.formatTime(this.shift.end_time);
        
        // Update shift name
        const shiftNameEl = document.getElementById('shiftName');
        if (shiftNameEl) {
            shiftNameEl.textContent = this.shift.name || 'Your Shift';
        }
        
        document.getElementById('shiftStart').textContent = startTime;
        document.getElementById('shiftEnd').textContent = endTime;
    }

    formatTime(timeString) {
        if (!timeString) return '--:-- --';
        
        const [hours, minutes] = timeString.split(':');
        const hour = parseInt(hours);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const displayHour = hour % 12 || 12;
        
        return `${String(displayHour).padStart(2, '0')}:${minutes} ${ampm}`;
    }

    checkTimeWindow() {
        const checkInBtn = document.getElementById('checkInBtn');
        const checkOutBtn = document.getElementById('checkOutBtn');
        const offDutyMsg = document.getElementById('offDutyMessage');
        const statusCard = document.getElementById('attendanceStatusCard');

        // Hide all by default
        checkInBtn.style.display = 'none';
        checkOutBtn.style.display = 'none';
        offDutyMsg.style.display = 'none';
        statusCard.style.display = 'none';

        // If no shift, user is off duty
        if (!this.shift || !this.shiftWindow) {
            this.showOffDutyMessage();
            return;
        }

        const canCheckIn = !!this.shiftWindow.can_check_in;
        const canCheckOut = !!this.shiftWindow.can_check_out;

        const checkInBtn = document.getElementById('checkInBtn');
        const checkOutBtn = document.getElementById('checkOutBtn');
        const offDutyMsg = document.getElementById('offDutyMessage');
        const statusCard = document.getElementById('attendanceStatusCard');

        // Check if already checked out today
        if (this.todayAttendance && this.todayAttendance.check_out_time) {
            // Show attendance status card
            this.updateAttendanceStatusCard();
            statusCard.style.display = 'block';
            return;
        }
        
        // Check if already checked in today
        if (this.todayAttendance && this.todayAttendance.check_in_time) {
            // Within shift: allow check-out only when window is open
            if (canCheckOut) {
                checkOutBtn.style.display = 'flex';
            } else {
                offDutyMsg.style.display = 'flex';
            }
        } else {
            // Not yet checked in: allow check-in only when window is open
            if (canCheckIn) {
                checkInBtn.style.display = 'flex';
            } else {
                offDutyMsg.style.display = 'flex';
            }
        }
    }

    updateAttendanceStatusCard() {
        if (!this.todayAttendance) return;
        
        const checkInTime = this.formatTime(this.todayAttendance.check_in_time.split('T')[1]);
        const checkOutTime = this.formatTime(this.todayAttendance.check_out_time.split('T')[1]);
        
        document.getElementById('statusCheckIn').textContent = checkInTime;
        document.getElementById('statusCheckOut').textContent = checkOutTime;
        
        // Determine status
        let status = 'Full Day';
        let statusBadge = document.getElementById('statusBadge');
        
        if (this.todayAttendance.half_day) {
            status = 'Half Day';
            statusBadge.className = 'status-badge half-day';
        } else if (this.todayAttendance.is_late) {
            status = 'Late';
            statusBadge.className = 'status-badge late';
        } else {
            status = 'Full Day';
            statusBadge.className = 'status-badge';
        }
        
        statusBadge.textContent = status;
    }

    showOffDutyMessage() {
        const checkInBtn = document.getElementById('checkInBtn');
        const checkOutBtn = document.getElementById('checkOutBtn');
        const offDutyMsg = document.getElementById('offDutyMessage');
        
        checkInBtn.style.display = 'none';
        checkOutBtn.style.display = 'none';
        offDutyMsg.style.display = 'flex';
    }

    updateQuickStats(data) {
        document.getElementById('tasksCount').textContent = data.pending_tasks || 0;
        document.getElementById('alertsCount').textContent = data.alerts || 0;
        document.getElementById('topPerformers').textContent = data.top_performers || 0;
    }

    updateNotifications(notifications) {
        if (!notifications || notifications.length === 0) {
            document.getElementById('notificationBadge').style.display = 'none';
            return;
        }
        
        const unreadCount = notifications.filter(n => !n.is_read).length;
        if (unreadCount > 0) {
            document.getElementById('notificationBadge').textContent = unreadCount;
            document.getElementById('notificationBadge').style.display = 'flex';
        }
        
        this.renderNotifications(notifications);
    }

    renderNotifications(notifications) {
        const list = document.getElementById('notificationsList');
        list.innerHTML = '';
        
        notifications.forEach(notification => {
            const item = document.createElement('div');
            item.className = `notification-item ${!notification.is_read ? 'unread' : ''}`;
            
            const iconColor = this.getNotificationIconColor(notification.notification_type);
            const icon = this.getNotificationIcon(notification.notification_type);
            
            const createdAt = new Date(notification.created_at);
            const timeAgo = this.getTimeAgo(createdAt);
            
            item.innerHTML = `
                <div class="notification-icon" style="background: ${iconColor};">
                    ${icon}
                </div>
                <div class="notification-content">
                    <div class="notification-title">${notification.title}</div>
                    <div class="notification-message">${notification.message}</div>
                    <div class="notification-time">${timeAgo}</div>
                </div>
            `;
            
            item.addEventListener('click', () => this.handleNotificationClick(notification));
            list.appendChild(item);
        });
    }

    getNotificationIconColor(type) {
        const colors = {
            'task': '#667eea',
            'document': '#f093fb',
            'leave': '#4facfe',
            'loan': '#fa709a',
            'rule': '#ffa500',
            'alert': '#f5576c'
        };
        return colors[type] || '#667eea';
    }

    getNotificationIcon(type) {
        const icons = {
            'task': '✓',
            'document': '📄',
            'leave': '📅',
            'loan': '💰',
            'rule': '📋',
            'alert': '⚠'
        };
        return icons[type] || '🔔';
    }

    getTimeAgo(date) {
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        
        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    handleNotificationClick(notification) {
        if (notification.action_url) {
            window.location.href = notification.action_url;
        }
        
        // Mark as read
        this.markNotificationAsRead(notification.id);
    }

    async markNotificationAsRead(notificationId) {
        try {
            await fetch(`/api/notifications/${notificationId}/mark-read/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                }
            });
        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    setupEventListeners() {
        // Check-In button
        document.getElementById('checkInBtn').addEventListener('click', () => this.handleCheckIn());
        
        // Check-Out button
        document.getElementById('checkOutBtn').addEventListener('click', () => this.handleCheckOut());
        
        // Notifications bell
        document.getElementById('notificationsBell').addEventListener('click', () => this.toggleNotifications());
        
        // Close notifications
        document.getElementById('closeNotifications').addEventListener('click', () => this.closeNotifications());
        
        // Close notifications when clicking outside
        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('notificationsDropdown');
            const bell = document.getElementById('notificationsBell');
            
            if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
                this.closeNotifications();
            }
        });
    }

    toggleNotifications() {
        const dropdown = document.getElementById('notificationsDropdown');
        dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
    }

    closeNotifications() {
        document.getElementById('notificationsDropdown').style.display = 'none';
    }

    async handleCheckIn() {
        try {
            // Get geolocation
            const position = await this.getGeolocation();
            
            // Capture photo from camera
            const photoBlob = await this.capturePhotoBlob();
            
            // Create FormData for multipart submission
            const formData = new FormData();
            formData.append('latitude', position.coords.latitude);
            formData.append('longitude', position.coords.longitude);
            // Include CSRF token for Django
            const csrfToken = this.getCsrfToken();
            if (csrfToken) {
                formData.append('csrfmiddlewaretoken', csrfToken);
            }
            if (photoBlob) {
                formData.append('check_in_photo', photoBlob, 'checkin.jpg');
            }
            
            // Submit via AJAX
            const response = await fetch('/employees/check-in/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    ...(csrfToken ? {'X-CSRFToken': csrfToken} : {})
                }
            });
            
            const data = await response.json();
            
            if (data.success) {
                alert('✓ Check-in successful! ' + data.message);
                // Update UI state instead of reloading
                await this.loadUIState();
                await this.loadDashboardData();
            } else {
                alert('Check-in failed: ' + data.message);
            }
            
        } catch (error) {
            console.error('Check-in error:', error);
            alert('Check-in failed: ' + error.message);
        }
    }

    async handleCheckOut() {
        try {
            // Get geolocation
            const position = await this.getGeolocation();
            
            // Capture photo from camera
            const photoBlob = await this.capturePhotoBlob();
            
            // Create FormData for multipart submission
            const formData = new FormData();
            formData.append('latitude', position.coords.latitude);
            formData.append('longitude', position.coords.longitude);
            // Include CSRF token for Django
            const csrfToken = this.getCsrfToken();
            if (csrfToken) {
                formData.append('csrfmiddlewaretoken', csrfToken);
            }
            if (photoBlob) {
                formData.append('check_out_photo', photoBlob, 'checkout.jpg');
            }
            
            // Submit via AJAX
            const response = await fetch('/employees/check-out/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    ...(csrfToken ? {'X-CSRFToken': csrfToken} : {})
                }
            });
            
            const data = await response.json();
            
            if (data.success) {
                alert('✓ Check-out successful! ' + data.message);
                // Update UI state instead of reloading
                await this.loadUIState();
                await this.loadDashboardData();
            } else {
                alert('Check-out failed: ' + data.message);
            }
            
        } catch (error) {
            console.error('Check-out error:', error);
            alert('Check-out failed: ' + error.message);
        }
    }

    getGeolocation() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error('Geolocation not supported'));
            }
            
            navigator.geolocation.getCurrentPosition(resolve, reject);
        });
    }

    async capturePhotoBlob() {
        try {
            // Request camera access
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'user' } 
            });
            
            // Create video element
            const video = document.createElement('video');
            video.srcObject = stream;
            video.play();
            
            // Wait for video to load
            await new Promise(resolve => {
                video.onloadedmetadata = resolve;
            });
            
            // Create canvas and capture frame
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0);
            
            // Stop stream
            stream.getTracks().forEach(track => track.stop());
            
            // Convert canvas to blob
            return new Promise(resolve => {
                canvas.toBlob(blob => {
                    resolve(blob);
                }, 'image/jpeg', 0.9);
            });
            
        } catch (error) {
            console.warn('Camera access denied, continuing without photo:', error);
            return null;
        }
    }

    async capturePhoto() {
        // Placeholder - in production, integrate with camera
        return 'photo_placeholder';
    }

    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    startLiveUpdates() {
        // Update time every second
        this.updateInterval = setInterval(() => {
            this.updateCurrentTime();
        }, 1000);
    }

    startTimeWindowCheck() {
        // Check time window every 30 seconds
        this.timeWindowCheckInterval = setInterval(() => {
            this.checkTimeWindow();
        }, 30000);
    }

    async loadAttendanceCalendar() {
        try {
            const employeeId = this.employee?.id;
            if (!employeeId) return;

            const today = new Date();
            const year = today.getFullYear();
            const month = today.getMonth() + 1;

            const response = await fetch(`/api/attendance/${employeeId}/month/?year=${year}&month=${month}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) throw new Error('Failed to load calendar');

            const data = await response.json();
            this.renderCalendar(data.days);
        } catch (error) {
            console.error('Error loading calendar:', error);
        }
    }

    renderCalendar(days) {
        const calendarContainer = document.getElementById('attendanceCalendar');
        if (!calendarContainer) return;

        calendarContainer.innerHTML = '';

        // Add day headers
        const dayHeaders = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        dayHeaders.forEach(day => {
            const header = document.createElement('div');
            header.className = 'calendar-day-header';
            header.textContent = day;
            header.style.fontWeight = '600';
            header.style.fontSize = '0.75rem';
            header.style.textAlign = 'center';
            header.style.color = '#666';
            calendarContainer.appendChild(header);
        });

        // Add day cells
        const today = new Date();
        for (let i = 1; i <= 31; i++) {
            const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
            const dayData = days[dateStr];

            const dayCell = document.createElement('div');
            dayCell.className = 'calendar-day';

            if (!dayData) {
                dayCell.classList.add('empty');
            } else {
                dayCell.textContent = i;
                dayCell.classList.add(dayData.status_color || 'empty');
                dayCell.title = dayData.status_label || '';

                // Make attendance dates clickable – redirect to full calendar with selected date
                dayCell.dataset.date = dateStr;
                dayCell.style.cursor = 'pointer';
                dayCell.addEventListener('click', () => {
                    const baseUrl = window.ATTENDANCE_CALENDAR_URL || '/employees/attendance/calendar/';
                    const separator = baseUrl.includes('?') ? '&' : '?';
                    window.location.href = `${baseUrl}${separator}date=${encodeURIComponent(dateStr)}`;
                });
            }

            calendarContainer.appendChild(dayCell);
        }
    }

    destroy() {
        if (this.updateInterval) clearInterval(this.updateInterval);
        if (this.timeWindowCheckInterval) clearInterval(this.timeWindowCheckInterval);
    }

    async loadUIState() {
        try {
            const response = await fetch('/api/dashboard-ui-state/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) throw new Error('Failed to load UI state');

            const uiState = await response.json();
            console.log('UI State loaded:', uiState);
            
            this.renderUIState(uiState);
            
        } catch (error) {
            console.error('Error loading UI state:', error);
            this.showLast7DaysActivity([]);
        }
    }

    renderUIState(uiState) {
        this.hideAllStateCards();
        
        switch (uiState.state) {
            case 'waiting_checkout':
                this.showWaitingCheckoutState(uiState);
                break;
            case 'post_checkout':
                this.showPostCheckoutState(uiState);
                break;
        }
        
        this.showLast7DaysActivity(uiState.last_7_days || []);
    }

    hideAllStateCards() {
        ['checkInSuccessCard', 'postCheckoutAttendanceCard', 'last7DaysActivity'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
    }

    showWaitingCheckoutState(uiState) {
        const card = document.getElementById('checkInSuccessCard');
        if (card) {
            card.style.display = 'block';
            const timeEl = document.getElementById('successCheckInTime');
            if (timeEl && uiState.check_in_time) {
                timeEl.textContent = uiState.check_in_time;
            }
        }
    }

    showPostCheckoutState(uiState) {
        const card = document.getElementById('postCheckoutAttendanceCard');
        if (card) {
            card.style.display = 'block';
            document.getElementById('summaryCheckIn').textContent = uiState.check_in_time || '--:--';
            document.getElementById('summaryCheckOut').textContent = uiState.check_out_time || '--:--';
            document.getElementById('summaryStatus').textContent = uiState.attendance_status || '--';
            document.getElementById('summaryTotalHours').textContent = this.calculateTotalHours(uiState.check_in_time, uiState.check_out_time);
        }
    }

    showLast7DaysActivity(last7Days) {
        const card = document.getElementById('last7DaysActivity');
        const grid = document.getElementById('daysGrid');
        
        if (!card || !grid) return;
        
        card.style.display = 'block';
        grid.innerHTML = '';
        
        last7Days.forEach(day => {
            const dayCard = document.createElement('div');
            dayCard.className = `day-card ${day.status}`;
            dayCard.innerHTML = `
                <i class='bx ${day.icon} day-icon'></i>
                <div class="day-name">${day.day_name}</div>
                <div class="day-date">${new Date(day.date).toLocaleDateString('en-US', {month: 'short', day: 'numeric'})}</div>
                <div class="day-status">${day.status.replace('_', ' ')}</div>
                <div class="day-times">In: ${day.check_in_time || '--:--'}<br>Out: ${day.check_out_time || '--:--'}</div>
            `;
            grid.appendChild(dayCard);
        });
    }

    calculateTotalHours(checkInTime, checkOutTime) {
        try {
            if (!checkInTime || !checkOutTime) return '--';
            const checkIn = new Date(`2000-01-01 ${checkInTime}`);
            const checkOut = new Date(`2000-01-01 ${checkOutTime}`);
            let diffMs = checkOut - checkIn;
            if (diffMs < 0) diffMs += 24 * 60 * 60 * 1000;
            const hours = Math.floor(diffMs / (1000 * 60 * 60));
            const minutes = Math.round((diffMs % (1000 * 60 * 60)) / (1000 * 60));
            return `${hours}h ${minutes}m`;
        } catch (error) {
            return '--';
        }
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new CheckInDashboard();
    // Load calendar after dashboard initializes
    setTimeout(() => {
        if (window.dashboard) {
            window.dashboard.loadAttendanceCalendar();
        }
    }, 500);
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.dashboard) {
        window.dashboard.destroy();
    }
});
