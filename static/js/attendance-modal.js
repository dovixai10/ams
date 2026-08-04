/**
 * Attendance Modal Handler
 * Handles dynamic loading of attendance details and comments via AJAX
 */

// Track active fetch requests to prevent memory leaks
let activeFetchRequests = new Map();

document.addEventListener('DOMContentLoaded', function() {
    const attendanceModal = document.getElementById('attendanceModal');
    const photoModal = document.getElementById('attendancePhotoModal');
    const screenRoot = document.querySelector('.am-screen');
    const screenEmployeeId = screenRoot ? screenRoot.dataset.employeeId : null;
    
    if (!attendanceModal) return;

    // Attach close button handler
    const closeBtn = document.getElementById('attendanceModalCloseBtn');
    if (closeBtn) {
        closeBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            closeAttendanceModal();
        });
    }

    // Handle calendar date click to load attendance details
    document.querySelectorAll('.am-calendar__cell--interactive').forEach(cell => {
        cell.addEventListener('click', function(e) {
            e.preventDefault();
            const employeeId = this.dataset.employeeId || screenEmployeeId;
            const date = this.dataset.date;
            if (!employeeId || !date) {
                console.warn('Missing employeeId or date on calendar cell', { employeeId, date });
                return;
            }
            loadAttendanceDetails(employeeId, date);
        });
    });

    // Handle photo modal
    document.querySelectorAll('[data-photo-type]').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const photoType = this.dataset.photoType;
            const photoId = photoType === 'checkin' ? 'modal-checkin-photo' : 'modal-checkout-photo';
            const photoImg = document.getElementById(photoId);
            
            if (photoImg && photoImg.src && !photoImg.classList.contains('d-none')) {
                showPhotoModal(photoImg.src, photoType);
            }
        });
    });

    // Handle comment form submission
    const commentForm = document.getElementById('modal-comment-form');
    if (commentForm) {
        commentForm.addEventListener('submit', function(e) {
            e.preventDefault();
            saveComment();
        });
    }

    // Handle comment refresh
    const refreshBtn = document.getElementById('modal-comment-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            const employeeId = attendanceModal.dataset.employeeId;
            const date = attendanceModal.dataset.date;
            if (employeeId && date) {
                loadComments(employeeId, date);
            }
        });
    }

    // Handle comment cancel
    const cancelBtn = document.getElementById('modal-comment-cancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            document.getElementById('modal-comment-input').value = '';
        });
    }
    
    // Handle modal lifecycle – minimal cleanup to avoid freezing UI
    attendanceModal.addEventListener('hide.bs.modal', function() {
        // Cancel any pending fetch requests immediately
        activeFetchRequests.forEach((controller) => {
            try {
                controller.abort();
            } catch (err) {
                // Silently ignore abort errors
            }
        });
        activeFetchRequests.clear();
        
        // Clear any pending timers
        if (window.attendanceModalTimers) {
            window.attendanceModalTimers.forEach(timer => clearTimeout(timer));
            window.attendanceModalTimers = [];
        }
    });
    
    attendanceModal.addEventListener('hidden.bs.modal', function() {
        // Reset modal fields and internal state
        resetModalFields();
        attendanceModal.dataset.employeeId = '';
        attendanceModal.dataset.date = '';

        // Ensure no focused element remains inside the (now hidden) modal
        if (document.activeElement && attendanceModal.contains(document.activeElement)) {
            document.activeElement.blur();
        }
        
        // Ensure body is not locked
        document.body.style.overflow = '';
        document.body.style.pointerEvents = '';
        
        // Remove any lingering backdrops
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            if (backdrop) backdrop.remove();
        });

        console.log('[DEBUG] Attendance modal closed and resources cleaned up');
    });
});

/**
 * Public helper to close the attendance modal safely
 * FIXES: Page freeze issue by ensuring complete cleanup
 */
window.closeAttendanceModal = function() {
    const modalEl = document.getElementById('attendanceModal');
    if (!modalEl) {
        return;
    }

    // Cancel all pending fetch requests to prevent memory leaks
    activeFetchRequests.forEach((controller) => {
        try {
            controller.abort();
        } catch (err) {
            // Ignore errors
        }
    });
    activeFetchRequests.clear();

    // Clear any timers/intervals
    if (window.attendanceModalTimers) {
        window.attendanceModalTimers.forEach(timer => clearTimeout(timer));
        window.attendanceModalTimers = [];
    }

    // If using Bootstrap 5, prefer its API
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) {
            modalInstance.hide();
        } else {
            // Create instance and hide immediately
            const newInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
            newInstance.hide();
        }
    }

    // Force hide the modal
    modalEl.classList.remove('show');
    modalEl.style.display = 'none';
    modalEl.setAttribute('aria-hidden', 'true');
    modalEl.removeAttribute('aria-modal');

    // Remove Bootstrap backdrop
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => backdrop.remove());

    // Remove any custom backdrops
    const customBackdrop = document.querySelector('.attendance-modal-backdrop');
    if (customBackdrop) {
        customBackdrop.remove();
    }

    // Re-enable body scroll and interactions
    document.body.style.overflow = '';
    document.body.style.pointerEvents = '';
    document.body.classList.remove('modal-open');
    document.body.style.paddingRight = '';

    // Clear focus to avoid any accidental focus traps
    if (document.activeElement && modalEl.contains(document.activeElement)) {
        document.activeElement.blur();
    }

    // Reset modal fields
    resetModalFields();

    // Clear modal data attributes
    modalEl.dataset.employeeId = '';
    modalEl.dataset.date = '';

    console.debug('[DEBUG] Attendance modal closed and all resources cleaned up');
};

/**
 * Load attendance details from API
 */
function loadAttendanceDetails(employeeId, date) {
    const modal = document.getElementById('attendanceModal');
    const url = `/api/attendance/${employeeId}/${date}/`;
    const bootstrapModal = typeof bootstrap !== 'undefined'
        ? bootstrap.Modal.getOrCreateInstance(modal)
        : null;

    // Cancel any previous requests
    const requestKey = `${employeeId}-${date}`;
    if (activeFetchRequests.has(requestKey)) {
        activeFetchRequests.get(requestKey).abort();
    }

    // Create new AbortController for this request
    const controller = new AbortController();
    activeFetchRequests.set(requestKey, controller);

    // Show loading state
    showLoadingState(true);

    fetch(url, { signal: controller.signal })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // Only process if request wasn't aborted
            if (!controller.signal.aborted) {
                populateModal(data);
                modal.dataset.employeeId = employeeId;
                modal.dataset.date = date;
                showLoadingState(false);
                if (bootstrapModal) {
                    bootstrapModal.show();
                } else if (window.jQuery) {
                    window.jQuery('#attendanceModal').modal('show');
                }
                // Remove from active requests
                activeFetchRequests.delete(requestKey);
            }
        })
        .catch(error => {
            // Only show error if request wasn't aborted
            if (error.name !== 'AbortError') {
                console.error('Error:', error);
            }
            showLoadingState(false);
            activeFetchRequests.delete(requestKey);
        });
}

/**
 * Populate modal with attendance data
 */
function populateModal(data) {
    const hasCheckin = !!(data.check_in_time_display || data.checkin_time || data.check_in_time);
    const hasCheckout = !!(data.check_out_time_display || data.checkout_time || data.check_out_time);
    const hasAnyRecord = hasCheckin || hasCheckout;

    const hasRecordContainer = document.getElementById('attendance-modal-has-record');
    const emptyStateContainer = document.getElementById('attendance-modal-empty-state');

    // Set date heading for both states
    const dateHeading = document.getElementById('modal-date');
    if (dateHeading) {
        dateHeading.textContent = data.weekday || data.date || '';
    }

    if (!hasAnyRecord) {
        // Show empty state
        if (hasRecordContainer) {
            hasRecordContainer.classList.add('d-none');
        }
        if (emptyStateContainer) {
            emptyStateContainer.classList.remove('d-none');
        }
        // Still update comments section to show any admin notes if present
        displayComments(data.comments || []);
        return;
    } else {
        if (hasRecordContainer) {
            hasRecordContainer.classList.remove('d-none');
        }
        if (emptyStateContainer) {
            emptyStateContainer.classList.add('d-none');
        }
    }

    // Check-in
    const checkinPhoto = document.getElementById('modal-checkin-photo');
    const checkinPlaceholder = document.getElementById('modal-checkin-photo-placeholder');
    
    if (data.check_in_photo_url || data.checkin_photo) {
        checkinPhoto.src = data.check_in_photo_url || data.checkin_photo;
        checkinPhoto.classList.remove('d-none');
        checkinPlaceholder.classList.add('d-none');
    } else {
        checkinPhoto.classList.add('d-none');
        checkinPlaceholder.classList.remove('d-none');
    }
    
    document.getElementById('modal-checkin').textContent =
        data.check_in_time_display || data.checkin_time || 'Not recorded';
    document.getElementById('modal-checkin-timestamp').textContent =
        data.check_in_time_display || data.checkin_timestamp || 'Not recorded';

    // Check-out
    const checkoutPhoto = document.getElementById('modal-checkout-photo');
    const checkoutPlaceholder = document.getElementById('modal-checkout-photo-placeholder');
    
    if (data.check_out_photo_url || data.checkout_photo) {
        checkoutPhoto.src = data.check_out_photo_url || data.checkout_photo;
        checkoutPhoto.classList.remove('d-none');
        checkoutPlaceholder.classList.add('d-none');
    } else {
        checkoutPhoto.classList.add('d-none');
        checkoutPlaceholder.classList.remove('d-none');
    }
    
    document.getElementById('modal-checkout').textContent =
        data.check_out_time_display || data.checkout_time || 'Not recorded';
    document.getElementById('modal-checkout-timestamp').textContent =
        data.check_out_time_display || data.checkout_timestamp || 'Not recorded';

    // Duration
    document.getElementById('modal-duration').textContent = data.total_duration_display || '—';

    // Status
    const statusBadge = createStatusBadge(data.status, data.status_label, data.status_color_class);
    document.getElementById('modal-status').innerHTML = statusBadge;
    document.getElementById('modal-status-note').textContent = getStatusNote(data.status);

    // Load comments
    displayComments(data.comments || []);
}

/**
 * Create status badge HTML
 */
function createStatusBadge(status, label, color) {
    const colorMap = {
        'present': 'success',
        'half_day': 'warning',
        'absent': 'danger',
        'holiday': 'secondary',
        'late_penalty': 'warning',
        'sandwich_leave': 'info',
        'checked_in': 'info',
        'future': 'light',
        // Legacy color names
        'dark-green': 'success',
        'yellow': 'warning',
        'red': 'danger',
        'dark-grey': 'secondary',
        'purple': 'info',
        'blue': 'info'
    };
    
    const badgeClass = colorMap[color] || 'secondary';
    return `<span class="badge bg-${badgeClass}">${label}</span>`;
}

/**
 * Get status note text
 */
function getStatusNote(status) {
    const notes = {
        'present_full': 'You were present for the full day.',
        'present_half': 'You were present for half the day.',
        'absent': 'You were absent on this day.',
        'holiday': 'This was a company holiday.',
        'paid_leave': 'This day was marked as paid leave.',
        'sandwich_leave': 'This was a sandwich leave day.'
    };
    return notes[status] || '';
}

/**
 * Load comments from API
 */
function loadComments(employeeId, date) {
    const url = `/api/attendance/${employeeId}/${date}/`;
    const requestKey = `comments-${employeeId}-${date}`;

    // Cancel any previous comment requests
    if (activeFetchRequests.has(requestKey)) {
        activeFetchRequests.get(requestKey).abort();
    }

    // Create new AbortController for this request
    const controller = new AbortController();
    activeFetchRequests.set(requestKey, controller);

    fetch(url, { signal: controller.signal })
        .then(response => response.json())
        .then(data => {
            // Only process if request wasn't aborted
            if (!controller.signal.aborted && data.comments) {
                displayComments(data.comments);
            }
            activeFetchRequests.delete(requestKey);
        })
        .catch(error => {
            if (error.name !== 'AbortError') {
                console.error('Error loading comments:', error);
            }
            activeFetchRequests.delete(requestKey);
        });
}

/**
 * Display comments in thread
 */
function displayComments(comments) {
    const thread = document.getElementById('modal-comment-thread');
    thread.innerHTML = '';

    if (!comments || comments.length === 0) {
        thread.innerHTML = '<p class="text-muted text-center py-3">No comments yet. Be the first to comment!</p>';
        return;
    }

    comments.forEach(comment => {
        const commentEl = document.createElement('div');
        commentEl.className = 'am-comment-item';
        const authorName = comment.created_by || comment.author || 'Unknown';
        commentEl.innerHTML = `
            <div class="am-comment-item__header">
                <strong class="am-comment-item__author">${escapeHtml(authorName)}</strong>
                ${comment.is_admin_comment ? '<span class="badge bg-info ms-2">Admin</span>' : ''}
                <small class="text-muted ms-auto">${formatDate(comment.created_at)}</small>
            </div>
            <div class="am-comment-item__body">
                <p class="mb-0">${escapeHtml(comment.comment)}</p>
            </div>
        `;
        thread.appendChild(commentEl);
    });
}

/**
 * Save comment
 */
function saveComment() {
    const modal = document.getElementById('attendanceModal');
    const employeeId = modal.dataset.employeeId;
    const date = modal.dataset.date;
    const comment = document.getElementById('modal-comment-input').value.trim();

    if (!comment) {
        alert('Please enter a comment');
        return;
    }

    const url = `/api/attendance/${employeeId}/${date}/comments/`;

    // Get CSRF token
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                      document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1];

    const submitBtn = document.getElementById('modal-comment-submit');
    const spinner = submitBtn.querySelector('.spinner-border');
    
    submitBtn.disabled = true;
    spinner.classList.remove('d-none');

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ comment: comment })
    })
        .then(response => response.json())
        .then(data => {
            document.getElementById('modal-comment-input').value = '';
            loadComments(employeeId, date);
            showSuccess('Comment saved successfully');
        })
        .catch(error => {
            console.error('Error:', error);
            showError('Failed to save comment. Please try again.');
        })
        .finally(() => {
            submitBtn.disabled = false;
            spinner.classList.add('d-none');
        });
}

/**
 * Show photo in modal
 */
function showPhotoModal(photoUrl, photoType) {
    const photoImg = document.getElementById('attendance-photo-full');
    const caption = document.getElementById('attendance-photo-caption');
    
    photoImg.src = photoUrl;
    
    const timeElement = photoType === 'checkin' 
        ? document.getElementById('modal-checkin-timestamp')
        : document.getElementById('modal-checkout-timestamp');
    
    const time = timeElement.textContent;
    const date = document.getElementById('modal-date').textContent;
    const photoLabel = photoType === 'checkin' ? 'Check-in' : 'Check-out';
    
    caption.textContent = `${photoLabel} photo · ${time}, ${date}`;
    
    const modal = new bootstrap.Modal(document.getElementById('attendancePhotoModal'));
    modal.show();
}

/**
 * Reset modal fields
 */
function resetModalFields() {
    document.getElementById('modal-checkin').textContent = 'Not recorded';
    document.getElementById('modal-checkin-timestamp').textContent = 'Not recorded';
    document.getElementById('modal-checkout').textContent = 'Not recorded';
    document.getElementById('modal-checkout-timestamp').textContent = 'Not recorded';
    document.getElementById('modal-duration').textContent = '—';
    
    document.getElementById('modal-checkin-photo').classList.add('d-none');
    document.getElementById('modal-checkin-photo-placeholder').classList.remove('d-none');
    document.getElementById('modal-checkout-photo').classList.add('d-none');
    document.getElementById('modal-checkout-photo-placeholder').classList.remove('d-none');
}

/**
 * Show loading state
 * FIX: Use visual feedback without blocking UI interactions
 */
function showLoadingState(show) {
    const body = document.querySelector('.attendance-modal-body');
    if (!body) return;
    
    if (show) {
        // Only reduce opacity, don't block pointer events
        body.style.opacity = '0.6';
        // Add a loading spinner class if needed
        body.classList.add('is-loading');
    } else {
        body.style.opacity = '1';
        body.classList.remove('is-loading');
    }
}

/**
 * Show error message
 */
function showError(message) {
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger alert-dismissible fade show';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    const modal = document.getElementById('attendanceModal');
    const body = modal.querySelector('.modal-body');
    body.insertBefore(alert, body.firstChild);
    
    setTimeout(() => alert.remove(), 5000);
}

/**
 * Show success message
 */
function showSuccess(message) {
    const alert = document.createElement('div');
    alert.className = 'alert alert-success alert-dismissible fade show';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    const modal = document.getElementById('attendanceModal');
    const body = modal.querySelector('.modal-body');
    body.insertBefore(alert, body.firstChild);
    
    setTimeout(() => alert.remove(), 3000);
}

/**
 * Format date string
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString();
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}
