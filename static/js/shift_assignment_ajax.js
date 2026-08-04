/**
 * Shift Assignment AJAX Handler
 * Handles individual and bulk shift assignments
 */

document.addEventListener('DOMContentLoaded', function() {
  // Initialize event listeners
  initializeEventListeners();
  updateSummary();
});

/**
 * Initialize all event listeners
 */
function initializeEventListeners() {
  // Use event delegation for dynamically added elements
  document.addEventListener('change', function(event) {
    if (event.target.classList.contains('shift-dropdown')) {
      handleShiftChange(event);
    }
    if (event.target.classList.contains('employee-checkbox')) {
      handleCheckboxChange(event);
    }
    if (event.target.id === 'selectAllCheckbox' || event.target.id === 'headerSelectAll') {
      handleSelectAll(event);
    }
  });

  document.addEventListener('click', function(event) {
    if (event.target.classList.contains('remove-shift-btn') || 
        (event.target.closest('.remove-shift-btn'))) {
      handleRemoveShift(event);
    }
    if (event.target.id === 'bulkAssignBtn') {
      handleBulkAssign(event);
    }
  });

  // Bulk shift select
  const bulkShiftSelect = document.getElementById('bulkShiftSelect');
  if (bulkShiftSelect) {
    bulkShiftSelect.addEventListener('change', function() {
      const bulkAssignBtn = document.getElementById('bulkAssignBtn');
      bulkAssignBtn.disabled = !this.value;
    });
  }
}

/**
 * Handle individual shift dropdown change
 */
function handleShiftChange(event) {
  const dropdown = event.target;
  const employeeId = dropdown.dataset.employeeId;
  const shiftId = dropdown.value;

  if (!shiftId) {
    showError('Please select a shift');
    return;
  }

  updateEmployeeShift(employeeId, shiftId);
}

/**
 * Update employee shift via AJAX
 */
function updateEmployeeShift(employeeId, shiftId) {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    getCookie('csrftoken');

  fetch('/shift/update/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify({
      employee_id: employeeId,
      shift_id: shiftId,
    }),
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showSuccess(data.message);
      updateEmployeeRow(employeeId, data.shift_display, data.shift_name);
      updateSummary();
    } else {
      showError(data.message);
      // Reset dropdown
      const dropdown = document.querySelector(`[data-employee-id="${employeeId}"]`);
      if (dropdown) {
        dropdown.value = '';
      }
    }
  })
  .catch(error => {
    console.error('Error:', error);
    showError('Error updating shift. Please try again.');
  });
}

/**
 * Handle remove shift button click
 */
function handleRemoveShift(event) {
  event.preventDefault();
  const employeeId = event.currentTarget.dataset.employeeId;

  if (!confirm('Are you sure you want to remove this shift?')) {
    return;
  }

  removeEmployeeShift(employeeId);
}

/**
 * Remove shift from employee
 */
function removeEmployeeShift(employeeId) {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    getCookie('csrftoken');

  fetch('/shift/remove/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify({
      employee_id: employeeId,
    }),
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showSuccess(data.message);
      // Reload the row
      location.reload();
    } else {
      showError(data.message);
    }
  })
  .catch(error => {
    console.error('Error:', error);
    showError('Error removing shift. Please try again.');
  });
}

/**
 * Handle select all checkbox
 */
function handleSelectAll(event) {
  const isChecked = event.target.checked;
  document.querySelectorAll('.employee-checkbox').forEach(checkbox => {
    checkbox.checked = isChecked;
  });
  updateSummary();
}

/**
 * Handle individual checkbox change
 */
function handleCheckboxChange(event) {
  updateSummary();
  
  // Update select all checkbox state
  const allCheckboxes = document.querySelectorAll('.employee-checkbox');
  const checkedCheckboxes = document.querySelectorAll('.employee-checkbox:checked');
  const selectAllCheckbox = document.getElementById('selectAllCheckbox');
  const headerSelectAll = document.getElementById('headerSelectAll');
  
  const allChecked = allCheckboxes.length === checkedCheckboxes.length;
  if (selectAllCheckbox) selectAllCheckbox.checked = allChecked;
  if (headerSelectAll) headerSelectAll.checked = allChecked;
}

/**
 * Handle bulk assign
 */
function handleBulkAssign(event) {
  event.preventDefault();

  const selectedCheckboxes = document.querySelectorAll('.employee-checkbox:checked');
  const shiftId = document.getElementById('bulkShiftSelect').value;

  if (selectedCheckboxes.length === 0) {
    showError('Please select at least one employee');
    return;
  }

  if (!shiftId) {
    showError('Please select a shift');
    return;
  }

  const employeeIds = Array.from(selectedCheckboxes).map(cb => cb.value);

  // Show confirmation
  if (!confirm(`Assign this shift to ${employeeIds.length} employee(s)?`)) {
    return;
  }

  bulkAssignShift(employeeIds, shiftId);
}

/**
 * Bulk assign shift to multiple employees
 */
function bulkAssignShift(employeeIds, shiftId) {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                    getCookie('csrftoken');

  // Disable button during request
  const bulkAssignBtn = document.getElementById('bulkAssignBtn');
  const originalText = bulkAssignBtn.innerHTML;
  bulkAssignBtn.disabled = true;
  bulkAssignBtn.innerHTML = '<i class="bx bx-loader-alt bx-spin me-1"></i>Processing...';

  fetch('/shift/bulk-assign/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify({
      employee_ids: employeeIds,
      shift_id: shiftId,
    }),
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showSuccess(data.message);
      // Clear selections and reload
      setTimeout(() => {
        location.reload();
      }, 1500);
    } else {
      showError(data.message);
    }
  })
  .catch(error => {
    console.error('Error:', error);
    showError('Error assigning shifts. Please try again.');
  })
  .finally(() => {
    bulkAssignBtn.disabled = false;
    bulkAssignBtn.innerHTML = originalText;
  });
}

/**
 * Update employee row after shift change
 */
function updateEmployeeRow(employeeId, shiftDisplay, shiftName) {
  const row = document.querySelector(`[data-employee-id="${employeeId}"]`);
  if (!row) return;

  // Update shift info cell
  const shiftCell = row.querySelector('.shift-info');
  if (shiftCell) {
    shiftCell.innerHTML = `
      <div class="fw-semibold">${shiftName}</div>
      <small class="text-muted">${shiftDisplay}</small>
    `;
  }

  // Add remove button if not present
  const removeBtn = row.querySelector('.remove-shift-btn');
  if (!removeBtn) {
    const actionCell = row.querySelector('td:last-child');
    const dropdown = actionCell.querySelector('.shift-dropdown');
    const newRemoveBtn = document.createElement('button');
    newRemoveBtn.className = 'btn btn-sm btn-outline-danger remove-shift-btn';
    newRemoveBtn.dataset.employeeId = employeeId;
    newRemoveBtn.title = 'Remove shift';
    newRemoveBtn.innerHTML = '<i class="bx bx-trash"></i>';
    newRemoveBtn.addEventListener('click', handleRemoveShift);
    dropdown.parentElement.appendChild(newRemoveBtn);
  }
}

/**
 * Update summary statistics
 */
function updateSummary() {
  const allRows = document.querySelectorAll('.employee-row');
  const selectedCheckboxes = document.querySelectorAll('.employee-checkbox:checked');
  
  let assignedCount = 0;
  let notAssignedCount = 0;

  allRows.forEach(row => {
    const shiftInfo = row.querySelector('.shift-info');
    if (shiftInfo) {
      assignedCount++;
    } else {
      notAssignedCount++;
    }
  });

  document.getElementById('assignedCount').textContent = assignedCount;
  document.getElementById('notAssignedCount').textContent = notAssignedCount;
  document.getElementById('selectedCount').textContent = selectedCheckboxes.length;
}

/**
 * Show success toast
 */
function showSuccess(message) {
  const toast = document.getElementById('successToast');
  const messageEl = document.getElementById('successToastMessage');
  
  messageEl.textContent = message;
  
  const bsToast = new bootstrap.Toast(toast);
  bsToast.show();
}

/**
 * Show error toast
 */
function showError(message) {
  const toast = document.getElementById('errorToast');
  const messageEl = document.getElementById('errorToastMessage');
  
  messageEl.textContent = message;
  
  const bsToast = new bootstrap.Toast(toast);
  bsToast.show();
}

/**
 * Get CSRF token from cookies
 */
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}
