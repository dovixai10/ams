/**
 * Main
 */

'use strict';

let menu,
  animate;
document.addEventListener('DOMContentLoaded', function () {
  // class for ios specific styles
  if (navigator.userAgent.match(/iPhone|iPad|iPod/i)) {
    document.body.classList.add('ios');
  }
});

(function () {
  // Initialize menu
  //-----------------

  let layoutMenuEl = document.querySelectorAll('#layout-menu');
  layoutMenuEl.forEach(function (element) {
    menu = new Menu(element, {
      orientation: 'vertical',
      closeChildren: false
    });
    // Change parameter to true if you want scroll animation
    window.Helpers.scrollToActive((animate = false));
    window.Helpers.mainMenu = menu;
  });

  // The theme's own markup puts "layout-menu-toggle" on TWO different
  // elements: the real "<" chevron inside the sidebar, AND the full-screen
  // dark overlay/backdrop that sits behind the content on mobile (see
  // layout_vertical.html: `<div class="layout-overlay layout-menu-toggle">`).
  // Binding the click-to-toggle listener below to every ".layout-menu-toggle"
  // element (the theme's own intent - it's a "tap outside closes the menu"
  // backdrop) therefore also wires up ANY tap on the content area to close
  // the sidebar, because that's exactly what the overlay is for. That
  // mattered here specifically because there's no navbar on this app to
  // provide a separate, always-visible way to reopen the menu afterwards -
  // so closing it that way left the user with no way back in until they
  // reloaded the page.
  //
  // The fix is to stop the overlay/backdrop from ever being a toggle
  // element in the first place - strip the shared class off it (and its
  // desktop cousin, the content-backdrop) BEFORE the click-toggler below
  // ever queries for ".layout-menu-toggle", so only the real "<" chevron is
  // ever bound. This is deterministic (no relying on event-listener order
  // or propagation timing versus the vendor bundle) and doesn't touch the
  // vendor files themselves.
  document.querySelectorAll('.layout-overlay, .content-backdrop').forEach(el => {
    el.classList.remove('layout-menu-toggle');
  });

  // Initialize menu togglers and bind click on each - after the strip
  // above, this only ever matches the real "<" chevron.
  let menuToggler = document.querySelectorAll('.layout-menu-toggle');
  menuToggler.forEach(item => {
    item.addEventListener('click', event => {
      event.preventDefault();
      window.Helpers.toggleCollapsed();
    });
  });

  // Display menu toggle (layout-menu-toggle) on hover with delay
  let delay = function (elem, callback) {
    let timeout = null;
    elem.onmouseenter = function () {
      // Set timeout to be a timer which will invoke callback after 300ms (not for small screen)
      if (!Helpers.isSmallScreen()) {
        timeout = setTimeout(callback, 300);
      } else {
        timeout = setTimeout(callback, 0);
      }
    };

    elem.onmouseleave = function () {
      // Clear any timers set to timeout
      document.querySelector('.layout-menu-toggle').classList.remove('d-block');
      clearTimeout(timeout);
    };
  };
  if (document.getElementById('layout-menu')) {
    delay(document.getElementById('layout-menu'), function () {
      // not for small screen
      if (!Helpers.isSmallScreen()) {
        document.querySelector('.layout-menu-toggle').classList.add('d-block');
      }
    });
  }

  // Display in main menu when menu scrolls
  let menuInnerContainer = document.getElementsByClassName('menu-inner'),
    menuInnerShadow = document.getElementsByClassName('menu-inner-shadow')[0];
  if (menuInnerContainer.length > 0 && menuInnerShadow) {
    menuInnerContainer[0].addEventListener('ps-scroll-y', function () {
      if (this.querySelector('.ps__thumb-y').offsetTop) {
        menuInnerShadow.style.display = 'block';
      } else {
        menuInnerShadow.style.display = 'none';
      }
    });
  }

  // Init helpers & misc
  // --------------------

  // Init BS Tooltip
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Accordion active class
  const accordionActiveFunction = function (e) {
    if (e.type == 'show.bs.collapse' || e.type == 'show.bs.collapse') {
      e.target.closest('.accordion-item').classList.add('active');
    } else {
      e.target.closest('.accordion-item').classList.remove('active');
    }
  };

  const accordionTriggerList = [].slice.call(document.querySelectorAll('.accordion'));
  const accordionList = accordionTriggerList.map(function (accordionTriggerEl) {
    accordionTriggerEl.addEventListener('show.bs.collapse', accordionActiveFunction);
    accordionTriggerEl.addEventListener('hide.bs.collapse', accordionActiveFunction);
  });

  // Auto update layout based on screen size
  window.Helpers.setAutoUpdate(true);

  // Toggle Password Visibility
  window.Helpers.initPasswordToggle();

  // Speech To Text
  window.Helpers.initSpeechToText();

  // Manage menu expanded/collapsed with templateCustomizer & local storage
  //------------------------------------------------------------------

  // If current layout is horizontal OR current window screen is small (overlay menu) than return from here
  if (window.Helpers.isSmallScreen()) {
    return;
  }

  // If current layout is vertical and current window screen is > small

  // Auto update menu collapsed/expanded based on the themeConfig
      window.Helpers.setCollapsed(true, false);
})();
// Utils
function isMacOS() {
  return /Mac|iPod|iPhone|iPad/.test(navigator.userAgent);
}

// Leave verification uploads helper (shared across pages)
(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
    return null;
  }

  function notify(message, type) {
    if (typeof window.showToastMessage === 'function') {
      window.showToastMessage(message, type);
    } else if (window.toastr) {
      window.toastr[type === 'error' ? 'error' : 'success'](message);
    } else {
      alert(message);
    }
  }

  function renderDocs(leaveId, documents = []) {
    const container = document.querySelector(`[data-doc-list="${leaveId}"]`);
    if (!container) return;
    if (!documents.length) {
      container.innerHTML = '<small class="text-muted">No documents uploaded yet.</small>';
      return;
    }
    const pills = documents
      .map(
        doc =>
          `<a href="${doc.url}" target="_blank" rel="noopener" class="badge bg-label-secondary">
            <i class="bx bx-paperclip me-1"></i>${doc.name}
          </a>`
      )
      .join('');
    container.innerHTML = `
      <div class="small text-muted mb-1">Uploaded documents:</div>
      <div class="d-flex flex-wrap gap-2">${pills}</div>
    `;
  }

  function init(scope) {
    const forms = (scope || document).querySelectorAll('.js-leave-upload-form');
    if (!forms.length) return;

    forms.forEach(form => {
      const fileInput = form.querySelector('[data-file-input]');
      const preview = form.querySelector('[data-file-preview]');
      const uploadBtn = form.querySelector('[data-upload-btn]');

      if (fileInput && preview) {
        fileInput.addEventListener('change', e => {
          const file = e.target.files[0];
          if (!file) {
            preview.innerHTML = '';
            return;
          }
          const maxSize = 5 * 1024 * 1024;
          const allowedTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
          if (file.size > maxSize) {
            preview.innerHTML =
              '<div class="text-danger small"><i class="bx bx-error-circle"></i> File size exceeds 5MB limit</div>';
            fileInput.value = '';
            return;
          }
          if (!allowedTypes.includes(file.type)) {
            preview.innerHTML =
              '<div class="text-danger small"><i class="bx bx-error-circle"></i> Only PDF, JPG, and PNG files allowed</div>';
            fileInput.value = '';
            return;
          }
          preview.innerHTML = `<div class="text-success small"><i class="bx bx-check-circle"></i> ${file.name} (${(
            file.size / 1024
          ).toFixed(1)} KB)</div>`;
        });
      }

      form.addEventListener('submit', async e => {
        e.preventDefault();
        if (!fileInput || !fileInput.files.length) {
          notify('Please choose a document first.', 'error');
          return;
        }

        const uploadUrl = form.dataset.uploadUrl;
        const leaveId = form.dataset.leaveId;
        const formData = new FormData();
        formData.append('receipt', fileInput.files[0]);

        if (uploadBtn) {
          uploadBtn.disabled = true;
          uploadBtn.dataset.originalText = uploadBtn.dataset.originalText || uploadBtn.innerHTML;
          uploadBtn.innerHTML = '<i class="bx bx-loader-alt bx-spin me-1"></i>Uploading...';
        }

        try {
          const response = await fetch(uploadUrl, {
            method: 'POST',
            body: formData,
            headers: {
              'X-CSRFToken': getCookie('csrftoken') || ''
            }
          });
          const data = await response.json();

          if (data.success) {
            notify('Document uploaded successfully!', 'success');
            fileInput.value = '';
            if (preview) preview.innerHTML = '';
            renderDocs(leaveId, data.documents || []);
          } else {
            notify(data.error || 'Upload failed', 'error');
          }
        } catch (error) {
          console.error('Leave upload error:', error);
          notify('Error uploading document', 'error');
        } finally {
          if (uploadBtn) {
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = uploadBtn.dataset.originalText || 'Upload';
          }
        }
      });
    });
  }

  window.LeaveVerificationUploads = {
    init,
    renderDocs
  };

  document.addEventListener('DOMContentLoaded', function () {
    init(document);
  });
})();

// Generic document viewer
(function () {
  function openDocumentModal(url, title) {
    if (!url) return;
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.innerHTML = `
      <div class="modal-dialog modal-lg modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${title || 'Document Viewer'}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body p-0">
            <iframe src="${url}" style="width: 100%; height: 70vh; border: none;"></iframe>
          </div>
          <div class="modal-footer">
            <a class="btn btn-primary" href="${url}" target="_blank" rel="noopener">
              <i class="bx bx-download me-1"></i>Open in new tab
            </a>
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const modalInstance = new bootstrap.Modal(modal);
    modalInstance.show();
    modal.addEventListener('hidden.bs.modal', () => modal.remove());
  }

  window.viewComplianceDocument = openDocumentModal;

  document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-view-document]');
    if (!trigger) return;
    event.preventDefault();
    const url = trigger.getAttribute('data-doc-url');
    const title = trigger.getAttribute('data-doc-title');
    openDocumentModal(url, title);
  });
})();