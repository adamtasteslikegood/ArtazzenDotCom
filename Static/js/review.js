// Format all timestamps in elements with [data-ts]
function formatTimestamps() {
  document.querySelectorAll('[data-ts]').forEach(el => {
    const ts = parseFloat(el.dataset.ts);
    if (!isNaN(ts)) {
      el.textContent = new Date(ts * 1000).toLocaleString();
    }
  });
}

// Busy overlay
function showBusy(msg = "Working…") {
  const el = document.getElementById('busy');
  if (el) {
    el.setAttribute('aria-hidden', 'false');
    const indicator = el.querySelector('.busy-indicator');
    if (indicator) indicator.textContent = msg;
  }
}

function hideBusy() {
  const el = document.getElementById('busy');
  if (el) el.setAttribute('aria-hidden', 'true');
}

// Theme handling
function updateThemeToggleButtons(theme) {
  document.querySelectorAll('[data-theme-toggle]').forEach(toggle => {
    toggle.textContent = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
    toggle.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
  });
}

function applyTheme(theme) {
  const body = document.body;
  body.classList.remove('theme-light', 'theme-dark');
  body.classList.add(theme === 'dark' ? 'theme-dark' : 'theme-light');

  updateThemeToggleButtons(theme);

  try {
    localStorage.setItem('adminTheme', theme);
  } catch (_) {}
}

function initTheme() {
  try {
    const saved = localStorage.getItem('adminTheme');
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const theme = (saved === 'light' || saved === 'dark') ? saved : (prefersDark ? 'dark' : 'light');
    applyTheme(theme);
  } catch (_) {}
}

function bindThemeToggle() {
  const toggles = document.querySelectorAll('[data-theme-toggle]');
  toggles.forEach(toggle => {
    toggle.addEventListener('click', () => {
      const isDark = document.body.classList.contains('theme-dark');
      applyTheme(isDark ? 'light' : 'dark');
    });
  });
}

// Feedback banner
function showFeedback(message, type = 'info') {
  const feedback = document.getElementById('feedback');
  if (!feedback) return;
  feedback.textContent = message;
  feedback.classList.remove('error', 'success');
  feedback.classList.add(type === 'error' ? 'error' : 'success');
  feedback.hidden = false;
  window.setTimeout(() => {
    feedback.hidden = true;
  }, 8000);
}

// Sort / filter controls shared across render helpers
let pendingSort;
let pendingFilter;
let gallerySort;
let galleryFilter;
// Dashboard data state (must be defined before initReview/renderDashboard use them)
let pendingData = [];
let reviewedData = [];
let reviewInitStarted = false;

async function initReview() {
  if (reviewInitStarted) return;
  reviewInitStarted = true;

  // Basic page setup
  try { formatTimestamps(); } catch (_) {}
  try { initTheme(); } catch (_) {}
  try { bindThemeToggle(); } catch (_) {}

  // Parse initial admin state embedded in the page (if provided)
  try {
    const stateEl = document.getElementById('admin-state');
    if (stateEl?.textContent) {
      const initial = JSON.parse(stateEl.textContent);
      if (initial && (initial.pending || initial.reviewed)) {
        renderDashboard(initial);
      }
    }
  } catch (err) {
    console.warn('Failed to parse initial admin state:', err);
  }

  // Ensure config is loaded and UI bindings are attached
  try {
    await loadAdminConfig();
  } catch (_) {}
  try {
    bindReviewUI();
  } catch (err) {
    console.error('Failed to bind review UI:', err);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initReview);
} else {
  initReview();
}

// Called once DOM and admin state is ready
function bindReviewUI() {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const selectFilesButton = document.getElementById('select-files');
  const feedback = document.getElementById('feedback');
  const pendingList = document.getElementById('pending-list');
  const pendingCount = document.getElementById('pending-count');
  const galleryList = document.getElementById('reviewed-list');
  const galleryCount = document.getElementById('gallery-count');
  const refreshButton = document.getElementById('refresh-pending');
  const pathForm = document.getElementById('path-form');
  const aiForm = document.getElementById('ai-config-form');
  const aiEnabled = document.getElementById('ai-enabled');
  const aiStartupEnabled = document.getElementById('ai-startup-enabled');
  const sidecarStartupEnabled = document.getElementById('sidecar-startup-enabled');
  const aiModel = document.getElementById('ai-model');
  const aiTemp = document.getElementById('ai-temp');
  const aiTokens = document.getElementById('ai-tokens');
  const sidecarMaxWorkers = document.getElementById('sidecar-max-workers');
  const resetAiButton = document.getElementById('reset-ai-config');
  const selectAllBtn = document.getElementById('select-all');
  const acceptSelectedBtn = document.getElementById('accept-selected');
  const regenBtn = document.getElementById('regen-selected');
  const deleteSelectedBtn = document.getElementById('delete-selected');
  const forceOverwrite = document.getElementById('force-overwrite');
  gallerySort = document.getElementById('gallery-sort');
  pendingSort = document.getElementById('pending-sort');
  galleryFilter = document.getElementById('gallery-filter');
  pendingFilter = document.getElementById('pending-filter');
  const selectAllGalleryBtn = document.getElementById('select-all-gallery');
  const deleteSelectedGalleryBtn = document.getElementById('delete-selected-gallery');

  // --- Dropzone / Upload Handling ---
  dropzone.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('is-dragover');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('is-dragover'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('is-dragover');
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });

  selectFilesButton.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', e => {
    if (e.target.files.length) uploadFiles(e.target.files);
    e.target.value = '';
  });

  // --- Form Handling ---
  pathForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const formData = new FormData(pathForm);
    showBusy("Importing from path...");
    try {
      const res = await fetch('/admin/import-path', { method: 'POST', body: formData });
      const data = await res.json();
      showFeedback(`Imported ${data.copied.length} items.`);
      renderDashboard(data);
      pathForm.reset();
    } catch {
      showFeedback('Import failed.', 'error');
    } finally {
      hideBusy();
    }
  });

  aiForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const payload = {
      ai: {
        enabled: aiEnabled.checked,
        startup_enrichment_enabled: aiStartupEnabled.checked,
        startup_sidecar_enabled: sidecarStartupEnabled.checked,
        max_workers_create_sidecars: parseInt(sidecarMaxWorkers.value || '2'),
        model: aiModel.value,
        temperature: parseFloat(aiTemp.value || '0.6'),
        max_output_tokens: parseInt(aiTokens.value || '600')
      }
    };
    showBusy("Saving AI config...");
    try {
      const res = await fetch('/admin/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      await res.json();
      showFeedback('AI settings saved.');
    } catch {
      showFeedback('Failed to save config.', 'error');
    } finally {
      hideBusy();
    }
  });

  resetAiButton?.addEventListener('click', async () => {
    showBusy("Resetting AI config...");
    try {
      const res = await fetch('/admin/config/reset', { method: 'POST' });
      const data = await res.json();
      const ai = data.ai || {};
      aiEnabled.checked = !!ai.enabled;
      aiStartupEnabled.checked = !!ai.startup_enrichment_enabled;
      sidecarStartupEnabled.checked = !!ai.startup_sidecar_enabled;
      sidecarMaxWorkers.value = ai.max_workers_create_sidecars ?? 2;
      aiModel.value = ai.model || aiModel.options[0].value;
      aiTemp.value = ai.temperature ?? 0.6;
      aiTokens.value = ai.max_output_tokens ?? 600;
      showFeedback('AI config reset.');
    } catch {
      showFeedback('Failed to reset config.', 'error');
    } finally {
      hideBusy();
    }
  });

  // --- Toolbar Buttons ---
  selectAllBtn?.addEventListener('click', () => {
    const boxes = pendingList.querySelectorAll('.item-select');
    const shouldCheck = [...boxes].some(b => !b.checked);
    boxes.forEach(b => (b.checked = shouldCheck));
  });

  acceptSelectedBtn?.addEventListener('click', () => {
    const names = collectSelectedFrom(pendingList);
    if (!names.length) return showFeedback('No images selected.', 'error');
    acceptImages(names);
  });

  selectAllGalleryBtn?.addEventListener('click', () => {
    const boxes = galleryList.querySelectorAll('.item-select');
    const shouldCheck = [...boxes].some(b => !b.checked);
    boxes.forEach(b => (b.checked = shouldCheck));
  });

  regenBtn?.addEventListener('click', () => {
    const names = collectSelectedFrom(pendingList);
    if (!names.length) return showFeedback('No images selected.', 'error');
    const fieldCheckboxes = document.querySelectorAll('.bulk-regen-field:checked');
    const fields = Array.from(fieldCheckboxes)
      .map(el => el.dataset.field)
      .filter(Boolean);
    triggerRegeneration(names, !!forceOverwrite?.checked, fields);
  });

  deleteSelectedBtn?.addEventListener('click', () => {
    const names = collectSelectedFrom(pendingList);
    if (!names.length) return showFeedback('No images selected.', 'error');
    if (!confirm(`Delete ${names.length} item(s)?`)) return;
    Promise.all(names.map(n => deleteImage(n)));
  });

  deleteSelectedGalleryBtn?.addEventListener('click', () => {
    const names = collectSelectedFrom(galleryList);
    if (!names.length) return showFeedback('No curated items selected.', 'error');
    if (!confirm(`Delete ${names.length} curated item(s)?`)) return;
    Promise.all(names.map(n => deleteImage(n)));
  });

  refreshButton?.addEventListener('click', async () => {
    try {
      const data = await fetchDashboard();
      renderDashboard(data);
      showFeedback('Gallery refreshed.');
    } catch {
      showFeedback('Refresh failed.', 'error');
    }
  });

  gallerySort?.addEventListener('change', updateGalleryView);
  pendingSort?.addEventListener('change', updatePendingView);
  galleryFilter?.addEventListener('input', updateGalleryView);
  pendingFilter?.addEventListener('input', updatePendingView);

  // Per-card OK button using event delegation so dynamic cards work too
  pendingList?.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const button = target.closest('[data-action="accept-single"]');
    if (!button) return;
    const card = button.closest('.image-card');
    if (!card) return;
    const name = card.dataset.imageName;
    if (!name) return;
    acceptImages([name]);
  });
}

// --- Reusable Helpers ---
function collectSelectedFrom(container) {
  return Array.from(container.querySelectorAll('.item-select:checked'))
    .map((cb) => cb.closest('.image-card'))
    .filter(Boolean)
    .map((card) => card.dataset.imageName)
    .filter(Boolean);
}

function formatTimestamp(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '';
}

function buildTagList(tags = []) {
  const list = document.createElement('ul');
  list.className = 'tag-list list-inline small mb-0';
  tags.forEach(tag => {
    const li = document.createElement('li');
    li.className = 'list-inline-item border rounded-pill px-2 py-1 bg-light text-dark';
    li.textContent = tag;
    list.appendChild(li);
  });
  return list;
}

function createCardActions(item, type) {
  const reviewUrl = `/admin/review/${encodeURIComponent(item.name)}`;
  const actions = document.createElement('div');
  actions.className = 'image-card__actions d-flex gap-2 flex-wrap';

  const link = document.createElement('a');
  link.href = reviewUrl;
  link.className = 'btn btn-outline-primary btn-sm';
  link.textContent = type === 'reviewed' ? 'Edit' : 'Review details';
  actions.appendChild(link);

  if (type === 'pending') {
    const okBtn = document.createElement('button');
    okBtn.type = 'button';
    okBtn.className = 'btn btn-success btn-sm';
    okBtn.textContent = 'OK';
    okBtn.setAttribute('data-action', 'accept-single');
    actions.insertBefore(okBtn, link);
  }

  return actions;
}

// --- Rendering ---
function renderDashboard(data) {
  pendingData = data.pending || [];
  reviewedData = data.reviewed || [];
  updatePendingView();
  updateGalleryView();
  refreshCounts();
}

function refreshCounts() {
  document.getElementById('pending-count').textContent = pendingData.length;
  document.getElementById('gallery-count').textContent = reviewedData.length;
}

function updatePendingView() {
  const sorted = sortData(pendingData, pendingSort?.value || '');
  const filtered = filterData(sorted, pendingFilter?.value || '');
  renderCardList(filtered, 'pending', document.getElementById('pending-list'));
}

function updateGalleryView() {
  const sorted = sortData(reviewedData, gallerySort?.value || '');
  const filtered = filterData(sorted, galleryFilter?.value || '');
  renderCardList(filtered, 'reviewed', document.getElementById('reviewed-list'));
}

function renderCardList(list, type, container) {
  container.innerHTML = '';
  if (!list.length) {
    const p = document.createElement('p');
    p.className = 'alert alert-info text-center';
    p.textContent = type === 'reviewed'
      ? 'No curated artwork yet.'
      : 'No new files waiting for review.';
    container.appendChild(p);
    return;
  }

  list.forEach(item => {
    const card = document.createElement('article');
    card.className = 'image-card card h-100 shadow-sm p-3 mb-3';
    card.dataset.imageName = item.name;

    // Selection checkbox (for bulk actions)
    const selectWrap = document.createElement('div');
    selectWrap.className = 'form-check mb-2';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input item-select';
    checkbox.setAttribute('aria-label', `Select ${item.name}`);
    selectWrap.appendChild(checkbox);
    card.appendChild(selectWrap);

    // Preview
    const preview = document.createElement('div');
    preview.className = 'image-card__preview ratio ratio-4x3 mb-3';
    const link = document.createElement('a');
    // Link thumbnail to the same review page used by the toolbar buttons
    link.href = `/admin/review/${encodeURIComponent(item.name)}`;
    const img = document.createElement('img');
    img.src = item.url;
    img.alt = item.title || item.name;
    img.className = 'img-fluid rounded border';
    img.loading = 'lazy';
    link.appendChild(img);
    preview.appendChild(link);
    card.appendChild(preview);

    // Meta
    const meta = document.createElement('div');
    meta.className = 'image-card__meta d-flex flex-column gap-2';

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center';
    const title = document.createElement('h5');
    title.className = 'fw-semibold mb-0';
    title.textContent = item.title || item.name;
    header.appendChild(title);

    const badge = document.createElement('span');
    badge.className = item.ai_generated
      ? 'badge bg-secondary'
      : 'badge bg-light text-dark border';
    badge.textContent = item.ai_generated ? 'AI generated' : 'Needs text';
    header.appendChild(badge);
    meta.appendChild(header);

    const filename = document.createElement('p');
    filename.className = 'filename small text-muted mb-0';
    filename.textContent = item.name;
    meta.appendChild(filename);

    if (item.caption) {
      const caption = document.createElement('p');
      caption.className = 'caption fst-italic text-muted mb-0';
      caption.textContent = item.caption;
      meta.appendChild(caption);
    }

    if (item.description) {
      const desc = document.createElement('p');
      desc.className = 'description mb-0';
      desc.textContent = item.description;
      meta.appendChild(desc);
    }

    if (item.tags && item.tags.length) {
      meta.appendChild(buildTagList(item.tags));
    }

    const footer = document.createElement('div');
    footer.className = 'image-card__footer d-flex justify-content-between align-items-center mt-auto flex-wrap gap-2';

    if (item.ai_details?.created || item.ai_details?.attempted_at) {
      const time = document.createElement('span');
      time.className = 'timestamp small text-muted';
      time.dataset.ts = item.ai_details.created || item.ai_details.attempted_at;
      footer.appendChild(time);
    }

    footer.appendChild(createCardActions(item, type));
    meta.appendChild(footer);
    card.appendChild(meta);

    container.appendChild(card);
  });

  // Format new timestamps
  formatTimestamps();
}

// --- Sorting / Filtering ---
function sortData(data, sortValue = '') {
  const [field = 'title', direction = 'asc'] = sortValue.split(':');
  const dir = direction === 'desc' ? -1 : 1;

  return [...data].sort((a, b) => {
    let aVal;
    let bVal;

    switch (field) {
      case 'detected_at': {
        const aTime = (a.ai_details?.created || a.ai_details?.attempted_at || a.detected_at || 0);
        const bTime = (b.ai_details?.created || b.ai_details?.attempted_at || b.detected_at || 0);
        aVal = Number(aTime) || 0;
        bVal = Number(bTime) || 0;
        break;
      }
      case 'tag': {
        const aTags = Array.isArray(a.tags) ? a.tags : [];
        const bTags = Array.isArray(b.tags) ? b.tags : [];
        aVal = (aTags[0] || '').toString().toLowerCase();
        bVal = (bTags[0] || '').toString().toLowerCase();
        break;
      }
      default:
        aVal = (a[field] || '').toString().toLowerCase();
        bVal = (b[field] || '').toString().toLowerCase();
    }

    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return (aVal - bVal) * dir;
    }

    if (aVal < bVal) return -1 * dir;
    if (aVal > bVal) return 1 * dir;
    return 0;
  });
}

function filterData(data, query = '') {
  if (!query.trim()) return data;
  const term = query.toLowerCase();
  return data.filter(item =>
    (item.title || '').toLowerCase().includes(term) ||
    (item.author || '').toLowerCase().includes(term) ||
    (item.tags || []).some(tag => tag.toLowerCase().includes(term))
  );
}

// --- API Actions ---
async function fetchDashboard() {
  const res = await fetch('/admin/api/gallery');
  if (!res.ok) throw new Error('Failed to load dashboard data');
  return res.json();
}

async function uploadFiles(files) {
  const dropzone = document.getElementById('dropzone');
  const selectFilesButton = document.getElementById('select-files');
  const fileInput = document.getElementById('file-input');
  const formData = new FormData();
  [...files].forEach(file => formData.append('files', file));
  showBusy("Uploading...");
  if (dropzone) dropzone.classList.add('is-disabled');
  if (selectFilesButton) selectFilesButton.disabled = true;
  if (fileInput) fileInput.disabled = true;
  try {
    const res = await fetch('/admin/upload', { method: 'POST', body: formData });
    const data = await res.json();
    showFeedback(data.message || 'Upload complete.');
    renderDashboard(data);
  } catch {
    showFeedback('Upload failed.', 'error');
  } finally {
    hideBusy();
    if (dropzone) dropzone.classList.remove('is-disabled');
    if (selectFilesButton) selectFilesButton.disabled = false;
    if (fileInput) fileInput.disabled = false;
  }
}

async function triggerRegeneration(images, force = false, fields) {
  showBusy("Regenerating metadata...");
  const pendingList = document.getElementById('pending-list');
  const busyCards = [];
  if (pendingList) {
    images.forEach((name) => {
      const selector = `[data-image-name="${CSS.escape ? CSS.escape(name) : name}"]`;
      const card = pendingList.querySelector(selector);
      if (card) {
        card.classList.add('is-busy');
        busyCards.push(card);
      }
    });
  }
  try {
    const payload = { images, force };
    if (Array.isArray(fields) && fields.length) {
      payload.fields = fields;
    }
    const res = await fetch('/admin/ai/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.errors?.length) {
      const details = data.errors.map(e => `${e.name}: ${e.error}`).join(', ');
      showFeedback(`Some errors occurred: ${details}`, 'error');
    } else {
      showFeedback('Metadata regenerated.');
    }
    renderDashboard(data);
  } catch {
    showFeedback('Failed to regenerate metadata.', 'error');
  } finally {
    hideBusy();
    busyCards.forEach(card => card.classList.remove('is-busy'));
  }
}

async function acceptImages(names) {
  showBusy("Accepting images...");
  try {
    const res = await fetch('/admin/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images: names })
    });
    const data = await res.json();
    if (data.errors?.length) {
      const details = data.errors.map(e => `${e.name}: ${e.error}`).join(', ');
      showFeedback(`Some images were not accepted: ${details}`, 'error');
    } else {
      showFeedback(`Accepted ${names.length} image(s).`);
    }
    renderDashboard(data);
  } catch {
    showFeedback('Failed to accept images.', 'error');
  } finally {
    hideBusy();
  }
}

async function deleteImage(name) {
  showBusy(`Deleting ${name}...`);
  try {
    const res = await fetch(`/admin/image/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const data = await res.json();
    showFeedback(data.message || 'Image deleted.');
    const newData = await fetchDashboard();
    renderDashboard(newData);
  } catch {
    showFeedback('Delete failed.', 'error');
  } finally {
    hideBusy();
  }
}

async function loadAdminConfig() {
  try {
    const res = await fetch('/admin/config');
    const data = await res.json();
    const ai = data.ai || {};
    document.getElementById('ai-enabled').checked = !!ai.enabled;
    document.getElementById('ai-startup-enabled').checked = !!ai.startup_enrichment_enabled;
    document.getElementById('sidecar-startup-enabled').checked = !!ai.startup_sidecar_enabled;
    document.getElementById('sidecar-max-workers').value = ai.max_workers_create_sidecars ?? 2;
    document.getElementById('ai-model').value = ai.model || '';
    document.getElementById('ai-temp').value = ai.temperature ?? 0.6;
    document.getElementById('ai-tokens').value = ai.max_output_tokens ?? 600;
  } catch (err) {
    console.error('Failed to load config:', err);
  }
}
