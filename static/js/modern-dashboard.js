/* ===========================
   MODERN DASHBOARD JAVASCRIPT
   =========================== */

let dashboardData = null;
let updateInterval = null;

// Initialize dashboard on page load
document.addEventListener('DOMContentLoaded', function() {
  loadDashboardData();
  updateTime();
  setInterval(updateTime, 1000);
  setInterval(loadDashboardData, 30000); // Refresh every 30 seconds
});

// Load dashboard data from API
function loadDashboardData() {
  fetch('/employees/api/dashboard/')
    .then(response => {
      if (!response.ok) throw new Error('Failed to load dashboard');
      return response.json();
    })
    .then(data => {
      if (data.success) {
        dashboardData = data;
        updateDashboardUI(data);
      }
    })
    .catch(error => {
      console.error('Dashboard error:', error);
    });
}

// Update dashboard UI with data
function updateDashboardUI(data) {
  // Update greeting
  document.getElementById('greetingText').textContent = data.greeting;
  document.getElementById('employeeName').textContent = data.employee.name;
  updateGreetingIcon(data.time_period);

  // Apply weather-based theme
  if (data.theme) {
    applyWeatherTheme(data.theme);
  }

  // Update weather display
  if (data.weather) {
    updateWeatherDisplay(data.weather);
  }

  // Update shift info
  document.getElementById('shiftStart').textContent = data.shift_window.shift_start;
  document.getElementById('shiftEnd').textContent = data.shift_window.shift_end;
  updateShiftStatus(data.shift_window);

  // Update check-in/out buttons
  updateCheckInOutButtons(data.shift_window);

  // Update attendance summary if checked in
  if (data.attendance.checked_in) {
    updateAttendanceSummary(data.attendance);
  }

  // Update points
  document.getElementById('pointsValue').textContent = data.points.current;

  // Update tasks
  updateTasksList(data.tasks.today);

  // Update alerts
  updateAlertsList(data.profile);

  // Update top performers
  updateTopPerformers(data.top_performers);
}

// Update greeting icon based on time period
function updateGreetingIcon(timePeriod) {
  const icons = {
    'morning': '🌅',
    'afternoon': '☀️',
    'evening': '🌇',
    'night': '🌙'
  };
  document.getElementById('greetingIcon').textContent = icons[timePeriod] || '🌅';
  
  // Update card theme
  const card = document.getElementById('greetingCard');
  card.className = 'greeting-card fade-in theme-' + timePeriod;
}

// Update shift status message
function updateShiftStatus(shiftWindow) {
  const statusEl = document.getElementById('shiftStatus');
  const textEl = document.getElementById('shiftStatusText');
  
  textEl.textContent = shiftWindow.message;
  
  statusEl.className = 'shift-status';
  if (shiftWindow.can_check_in || shiftWindow.can_check_out) {
    statusEl.classList.add('success');
  } else if (shiftWindow.message.includes('off duty')) {
    statusEl.classList.add('danger');
  } else {
    statusEl.classList.add('warning');
  }
}

// Update check-in/out buttons
function updateCheckInOutButtons(shiftWindow) {
  const checkinBtn = document.getElementById('checkinBtn');
  const checkoutBtn = document.getElementById('checkoutBtn');
  
  checkinBtn.disabled = !shiftWindow.can_check_in;
  checkoutBtn.disabled = !shiftWindow.can_check_out;
  
  if (!shiftWindow.can_check_in && !shiftWindow.can_check_out) {
    // Show message instead of buttons
    const shiftButtons = document.getElementById('shiftButtons');
    shiftButtons.innerHTML = `
      <button class="btn btn-full" style="background: #e5e7eb; color: #6b7280; cursor: not-allowed;">
        <i class="bx bx-time"></i> You're off duty
      </button>
    `;
  }
}

// Update attendance summary
function updateAttendanceSummary(attendance) {
  const summary = document.getElementById('attendanceSummary');
  document.getElementById('attendanceCheckIn').textContent = attendance.check_in_time || '--:-- --';
  document.getElementById('attendanceCheckOut').textContent = attendance.check_out_time || '--:-- --';
  
  if (attendance.checked_in && attendance.checked_out) {
    summary.style.display = 'block';
    document.getElementById('attendanceStatus').textContent = 'All set for today';
  } else if (attendance.checked_in) {
    summary.style.display = 'block';
    document.getElementById('attendanceStatus').textContent = 'Checked in - awaiting check-out';
  }
}

// Update tasks list
function updateTasksList(tasks) {
  const tasksList = document.getElementById('tasksList');
  
  if (!tasks || tasks.length === 0) {
    tasksList.innerHTML = `
      <div class="empty-state">
        <i class="bx bx-inbox"></i>
        <p>No tasks for today</p>
      </div>
    `;
    return;
  }
  
  let html = '';
  tasks.forEach(task => {
    const priorityClass = task.priority || 'medium';
    html += `
      <div class="task-item">
        <div class="task-info">
          <div class="task-title">${task.title}</div>
          <span class="task-priority ${priorityClass}">${task.priority || 'Medium'}</span>
        </div>
      </div>
    `;
  });
  
  tasksList.innerHTML = html;
}

// Update alerts list
function updateAlertsList(profile) {
  const alertsList = document.getElementById('alertsList');
  let alerts = [];
  
  // Check profile completion
  if (!profile.complete) {
    alerts.push({
      type: 'danger',
      icon: 'bx-alert-circle',
      title: 'Complete Your Profile',
      message: 'Please update your profile to access all features.',
      button: 'Complete Profile',
      url: '/employees/profile/'
    });
  }
  
  if (alerts.length === 0) {
    alertsList.innerHTML = `
      <div class="empty-state">
        <i class="bx bx-check-circle"></i>
        <p>All set! No alerts.</p>
      </div>
    `;
    return;
  }
  
  let html = '';
  alerts.forEach(alert => {
    html += `
      <div class="alert-item ${alert.type}">
        <i class="bx ${alert.icon}"></i>
        <div class="alert-content">
          <div class="alert-title">${alert.title}</div>
          <div class="alert-message">${alert.message}</div>
          <a href="${alert.url}" class="alert-button">${alert.button}</a>
        </div>
      </div>
    `;
  });
  
  alertsList.innerHTML = html;
}

// Update top performers
function updateTopPerformers(performers) {
  const performersList = document.getElementById('performersList');
  
  if (!performers || performers.length === 0) {
    performersList.innerHTML = `
      <div class="empty-state">
        <i class="bx bx-star"></i>
        <p>No performers data available</p>
      </div>
    `;
    return;
  }
  
  let html = '';
  performers.forEach(perf => {
    const rankClass = `rank-${perf.rank}`;
    html += `
      <div class="performer-item">
        <div class="performer-rank ${rankClass}">
          ${perf.rank === 1 ? '🥇' : perf.rank === 2 ? '🥈' : '🥉'}
        </div>
        <div class="performer-info">
          <div class="performer-name">${perf.name}</div>
          <div class="performer-points">
            <strong>${perf.points}</strong> points
          </div>
        </div>
      </div>
    `;
  });
  
  performersList.innerHTML = html;
}

// Update current time
function updateTime() {
  const now = new Date();
  const timeString = now.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true
  });
  
  const dateString = now.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric'
  });
  
  document.getElementById('currentTime').textContent = `${dateString} • ${timeString}`;
}

// Handle check-in
function handleCheckIn() {
  if (!dashboardData || !dashboardData.shift_window.can_check_in) {
    alert('Check-in window is not open');
    return;
  }
  
  // Redirect to check-in page
  window.location.href = '/employees/check-in/';
}

// Handle check-out
function handleCheckOut() {
  if (!dashboardData || !dashboardData.shift_window.can_check_out) {
    alert('Check-out window is not open');
    return;
  }
  
  // Redirect to check-out page
  window.location.href = '/employees/check-out/';
}

// Apply weather-based theme
function applyWeatherTheme(theme) {
  const card = document.getElementById('greetingCard');
  if (card) {
    card.style.background = theme.gradient;
    card.style.color = theme.text_color;
  }
}

// Update weather display
function updateWeatherDisplay(weather) {
  const weatherBox = document.getElementById('greetingWeather');
  if (!weatherBox) return;
  
  if (!weather.success) {
    weatherBox.innerHTML = `
      <div class="weather-item">
        <span class="weather-label">Weather unavailable</span>
      </div>
    `;
    return;
  }
  
  const html = `
    <div class="weather-item">
      <span class="weather-label">Temperature</span>
      <span class="weather-value">${weather.icon} ${weather.temperature}°C</span>
    </div>
    <div class="weather-item">
      <span class="weather-label">Condition</span>
      <span class="weather-value">${weather.condition}</span>
    </div>
    <div class="weather-item">
      <span class="weather-label">Humidity</span>
      <span class="weather-value">${weather.humidity}%</span>
    </div>
    <div class="weather-item">
      <span class="weather-label">Wind</span>
      <span class="weather-value">${weather.wind_speed} m/s</span>
    </div>
    <div class="weather-item" style="border-top: 1px solid rgba(255,255,255,0.2); padding-top: 0.75rem; margin-top: 0.75rem;">
      <span class="weather-label" style="color: #fbbf24; font-weight: 700;">💡 Tip</span>
      <span class="weather-value" style="font-size: 0.9rem;">${weather.recommendation}</span>
    </div>
  `;
  
  weatherBox.innerHTML = html;
}
