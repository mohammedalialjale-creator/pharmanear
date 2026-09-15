/* ==========================================================================
   PharmaNear — frontend logic
   Talks to the Flask backend at /api/... (see app.py). No page reloads —
   everything below is fetch() + DOM updates.
   ========================================================================== */

let currentLang = 'ar';
let currentFilter = 'all';
let currentAppView = 'customer';
let editingMedicineId = null;
let pharmacistStage = 'gate';
let myPharmacyId = null;
let myPharmacy = null;
let userCoords = null; // { lat, lng } once captured
let searchDebounceTimer = null;
let lastResults = []; // the most recently rendered pharmacy list, indexed for onclick handlers

const statusLabel = {
  in_stock:     { en: 'In stock',     ar: 'متوفر' },
  low_stock:    { en: 'Low stock',    ar: 'كمية محدودة' },
  out_of_stock: { en: 'Out of stock', ar: 'غير متوفر' },
};

/* ============ HELPERS ============ */
function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[s]));
}
function medName(m, lang) { return m.name ? m.name[lang] : ''; }
function medForm(m, lang) { return m.form ? m.form[lang] : ''; }
function directionsUrl(ph) { return `https://www.google.com/maps/dir/?api=1&destination=${ph.latitude},${ph.longitude}`; }
function telUrl(phone) { return `tel:${phone}`; }
function whatsappUrl(phone, text) {
  // wa.me wants digits only (country code + number, no "+", spaces, or dashes).
  const digits = String(phone).replace(/[^\d]/g, '');
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}
async function apiSend(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status}`);
  return res.json();
}

/* ============ GEOLOCATION (HTML5 API) ============ */
function captureLocation() {
  const btn = document.getElementById('detect-btn');
  const status = document.getElementById('locate-status');

  if (!navigator.geolocation) {
    status.className = 'locate-status error';
    status.textContent = currentLang === 'ar' ? 'الموقع غير مدعوم في هذا المتصفح' : 'Geolocation not supported';
    return;
  }

  btn.classList.add('loading');
  status.className = 'locate-status';
  status.textContent = currentLang === 'ar' ? 'جارٍ تحديد موقعك بدقة GPS...' : 'Detecting your location with GPS accuracy...';

  navigator.geolocation.getCurrentPosition(
    pos => {
      userCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      btn.classList.remove('loading');
      status.className = 'locate-status success';
      status.textContent = currentLang === 'ar' ? 'تم تحديد موقعك ✓' : 'Location set ✓';
      // Skip the typing-debounce here — an explicit "detect my location" click
      // should refresh the results immediately, not after a delay.
      clearTimeout(searchDebounceTimer);
      fetchAndRender();
    },
    () => {
      btn.classList.remove('loading');
      status.className = 'locate-status error';
      status.textContent = currentLang === 'ar'
        ? 'تعذّر الوصول للموقع — تحقق من أذونات GPS في المتصفح'
        : "Couldn't access your location — check your browser's GPS permissions";
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}

/* ============ NAV HELPERS ============ */
function goToApp(view) {
  switchApp(view);
  document.getElementById('app').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function switchApp(view) {
  currentAppView = view;
  document.getElementById('panel-customer').hidden = view !== 'customer';
  document.getElementById('panel-pharmacist').hidden = view !== 'pharmacist';
  document.getElementById('tab-customer').classList.toggle('active', view === 'customer');
  document.getElementById('tab-pharmacist').classList.toggle('active', view === 'pharmacist');
  document.getElementById('tab-customer').setAttribute('aria-selected', view === 'customer');
  document.getElementById('tab-pharmacist').setAttribute('aria-selected', view === 'pharmacist');
  if (view === 'pharmacist') showPharmacistStage(pharmacistStage);
}

/* ============ PHARMACIST VERIFICATION FLOW ============ */
function showPharmacistStage(stage) {
  pharmacistStage = stage;
  document.getElementById('pharmacist-gate').hidden = stage !== 'gate';
  document.getElementById('pharmacist-pending').hidden = stage !== 'pending';
  document.getElementById('pharmacist-dashboard').hidden = stage !== 'dashboard';
  if (stage === 'dashboard') renderPharmacistDashboard();
}

function handleDocSelect(input) {
  const file = input.files && input.files[0];
  const arLabel = document.getElementById('upload-label');
  const enLabel = document.getElementById('upload-label-en');
  if (file) { arLabel.textContent = file.name; enLabel.textContent = file.name; }
  else {
    arLabel.textContent = 'اضغط لرفع صورة الترخيص';
    enLabel.textContent = 'Click to upload your license';
  }
}

async function submitVerification(e) {
  e.preventDefault();
  const name = document.getElementById('v-name').value.trim();
  const license = document.getElementById('v-license').value.trim();
  const city = document.getElementById('v-city').value.trim();
  const phone = document.getElementById('v-phone').value.trim();
  if (!name || !license || !city || !phone) return;

  const ref = 'PN-' + Math.floor(10000 + Math.random() * 89999);
  document.getElementById('pending-ref').textContent = (currentLang === 'ar' ? 'رقم الطلب: ' : 'Application ID: ') + ref;

  const lang = currentLang;
  document.getElementById('pending-summary').innerHTML = `
    <div class="row"><span>${lang === 'ar' ? 'اسم الصيدلية' : 'Pharmacy name'}</span><b>${escapeHtml(name)}</b></div>
    <div class="row"><span>${lang === 'ar' ? 'رقم الترخيص' : 'License number'}</span><b>${escapeHtml(license)}</b></div>
    <div class="row"><span>${lang === 'ar' ? 'المدينة' : 'City'}</span><b>${escapeHtml(city)}</b></div>
    <div class="row"><span>${lang === 'ar' ? 'رقم الهاتف' : 'Phone'}</span><b>${escapeHtml(phone)}</b></div>
  `;

  // Register a real (but initially closed) pharmacy row in the database.
  try {
    const pharmacy = await apiSend('/api/pharmacies', 'POST', {
      name_en: name, name_ar: name,
      address_en: city, address_ar: city,
      latitude: userCoords ? userCoords.lat : 15.6, // fall back to a Khartoum-area default
      longitude: userCoords ? userCoords.lng : 32.53,
      phone, status: 'closed', hours: '',
    });
    myPharmacyId = pharmacy.id;
    myPharmacy = pharmacy;
  } catch (err) {
    // Quietly keep this as a local-only demo record if the API call didn't go through.
    myPharmacyId = null;
    myPharmacy = {
      id: null, name: { en: name, ar: name }, address: { en: city, ar: city },
      is_open: false, status: 'closed', phone, hours: '', medicines: [],
    };
  }

  showPharmacistStage('pending');
}

function previewDashboard() { showPharmacistStage('dashboard'); }
function editApplication() { showPharmacistStage('gate'); }

/* ============ LANGUAGE / RTL ============ */
function setLang(lang) {
  currentLang = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.getElementById('btn-en').classList.toggle('active', lang === 'en');
  document.getElementById('btn-ar').classList.toggle('active', lang === 'ar');

  const input = document.getElementById('search-input');
  input.placeholder = lang === 'ar' ? input.getAttribute('data-ar-placeholder') : input.getAttribute('data-en-placeholder');

  renderPharmacies();
  if (myPharmacy) renderPharmacistDashboard();
}

/* ============ CUSTOMER: SEARCH + FILTERS + RENDER ============ */
function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('#filter-row .chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  renderPharmacies();
}

function renderPharmacies() {
  clearTimeout(searchDebounceTimer);

  if (!userCoords) {
    // The backend now looks up real pharmacies from OpenStreetMap around the
    // user's GPS position, so a location is required before we can search.
    document.getElementById('card-list').innerHTML =
      `<div class="loading-text">${currentLang === 'ar' ? 'بانتظار تحديد موقعك لعرض الصيدليات القريبة...' : 'Waiting for your location to show nearby pharmacies...'}</div>`;
    return;
  }

  document.getElementById('card-list').innerHTML =
    `<div class="loading-text">${currentLang === 'ar' ? 'جارٍ التحميل...' : 'Loading...'}</div>`;
  searchDebounceTimer = setTimeout(fetchAndRender, 250);
}

async function fetchAndRender() {
  if (!userCoords) { renderPharmacies(); return; }

  const query = document.getElementById('search-input').value.trim();
  const params = new URLSearchParams();
  params.set('lat', userCoords.lat);
  params.set('lng', userCoords.lng);
  if (query) params.set('q', query);
  if (currentFilter === 'open') params.set('open_only', 'true');
  if (currentFilter === 'instock') params.set('in_stock_only', 'true');

  try {
    const data = await apiGet(`/api/pharmacies/nearest?${params.toString()}`);
    let results = data.results;
    if (currentFilter === 'nearest') {
      results = results.slice().sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity));
    }
    renderResults(results);
  } catch (err) {
    document.getElementById('card-list').innerHTML =
      `<div class="loading-text">${currentLang === 'ar' ? 'تعذّر الاتصال بالخادم.' : 'Could not reach the server.'}</div>`;
  }
}

function renderResults(results) {
  lastResults = results;

  const list = document.getElementById('card-list');
  const emptyState = document.getElementById('empty-state');
  const countEl = document.getElementById('result-count');

  countEl.textContent = currentLang === 'ar' ? `${results.length} نتيجة` : `${results.length} result${results.length === 1 ? '' : 's'}`;

  if (results.length === 0) { list.innerHTML = ''; emptyState.classList.add('show'); return; }
  emptyState.classList.remove('show');

  const lang = currentLang;
  list.innerHTML = results.map((ph, index) => {
    const medRows = ph.medicines.map(m => `
      <div class="med-row">
        <div>
          <div class="med-name">${escapeHtml(medName(m, lang))}</div>
          <div class="med-form">${escapeHtml(medForm(m, lang))}</div>
          ${m.price ? `<div class="med-price">SDG ${Number(m.price).toLocaleString()}</div>` : ''}
        </div>
        <span class="stock-tag ${m.availability === 'in_stock' ? 'in' : m.availability === 'low_stock' ? 'low' : 'out'}">${statusLabel[m.availability][lang]}</span>
      </div>
    `).join('');

    const openBadge = ph.is_open
      ? `<span class="open-text">${lang === 'ar' ? 'مفتوحة' : 'Open now'}</span>`
      : `<span class="closed-text">${lang === 'ar' ? 'مغلقة' : 'Closed'}</span>`;

    // Show meters under 1km for a more precise "just around the corner" feel,
    // kilometers beyond that.
    let distanceText = '—';
    if (typeof ph.distance_km === 'number') {
      distanceText = ph.distance_km < 1
        ? `${Math.round(ph.distance_km * 1000)} m`
        : `${ph.distance_km.toFixed(1)} km`;
    }

    const directionsBtn = `
      <a class="action-btn map" href="${directionsUrl(ph)}" target="_blank" rel="noopener">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 21s-7-6.1-7-11.5A7 7 0 0119 9.5C19 14.9 12 21 12 21z" stroke="currentColor" stroke-width="2"/>
          <circle cx="12" cy="9.5" r="2.3" stroke="currentColor" stroke-width="2"/>
        </svg>
        ${lang === 'ar' ? 'الاتجاهات 🗺️' : 'Directions 🗺️'}
      </a>`;

    // Smart contact handling: only render Call/WhatsApp when a real phone
    // number came back from Overpass (`phone` or `contact:phone` tag) — never
    // a dead `tel:` or `wa.me` link with no number behind it. Otherwise fall
    // back to a "Share Location" action so the pharmacy is still reachable.
    const hasPhone = !!(ph.phone && String(ph.phone).trim());
    let contactButtons;
    let columnClass;

    if (hasPhone) {
      const waText = lang === 'ar'
        ? `مرحباً، أريد الاستفسار عن توفر دواء في ${ph.name.ar || ph.name.en}.`
        : `Hello, I'd like to ask about medicine availability at ${ph.name.en}.`;
      contactButtons = `
        <a class="action-btn call" href="${telUrl(ph.phone)}">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z" fill="currentColor"/>
          </svg>
          ${lang === 'ar' ? 'اتصال 📞' : 'Call 📞'}
        </a>
        <a class="action-btn whatsapp" href="${whatsappUrl(ph.phone, waText)}" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" fill="currentColor"/>
          </svg>
          ${lang === 'ar' ? 'طلب واتساب 💬' : 'WhatsApp Order 💬'}
        </a>`;
      columnClass = 'cols-3';
    } else {
      contactButtons = `
        <button type="button" class="action-btn share" onclick="shareLocation(${index})">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="18" cy="5" r="2.4" stroke="currentColor" stroke-width="1.8"/>
            <circle cx="6" cy="12" r="2.4" stroke="currentColor" stroke-width="1.8"/>
            <circle cx="18" cy="19" r="2.4" stroke="currentColor" stroke-width="1.8"/>
            <path d="M8.2 10.8l7.6-4.2M8.2 13.2l7.6 4.2" stroke="currentColor" stroke-width="1.8"/>
          </svg>
          ${lang === 'ar' ? 'مشاركة الموقع 📤' : 'Share Location 📤'}
        </button>`;
      columnClass = 'cols-2';
    }

    return `
      <article class="pcard">
        <div class="pcard-top">
          <div>
            <div class="pcard-name-row">
              <span class="status-dot ${ph.is_open ? 'open' : 'closed'}"></span>
              <span class="pcard-name">${escapeHtml(ph.name[lang])}</span>
            </div>
            <div class="pcard-meta">
              <span>${escapeHtml(ph.address[lang] || (lang === 'ar' ? 'بدون عنوان مسجل' : 'No address on record'))}</span>
              <span class="dot-sep"></span>
              ${openBadge}
            </div>
          </div>
          <div class="distance-badge">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 21s-7-6.1-7-11.5A7 7 0 0119 9.5C19 14.9 12 21 12 21z" stroke="currentColor" stroke-width="2"/>
              <circle cx="12" cy="9.5" r="2.3" stroke="currentColor" stroke-width="2"/>
            </svg>
            ${distanceText}
          </div>
        </div>
        <div class="med-list">${medRows}</div>
        <div class="pcard-actions ${columnClass}">
          ${directionsBtn}
          ${contactButtons}
        </div>
      </article>
    `;
  }).join('');
}

// Fallback contact path when no phone number exists on the OSM record.
// Prefers the native share sheet (great on mobile); falls back to opening a
// generic WhatsApp share screen with no pre-filled recipient.
async function shareLocation(index) {
  const ph = lastResults[index];
  if (!ph) return;

  const lang = currentLang;
  const name = ph.name[lang] || ph.name.en;
  const link = directionsUrl(ph);
  const shareText = lang === 'ar'
    ? `📍 ${name}\nموقع الصيدلية على الخريطة:\n${link}`
    : `📍 ${name}\nPharmacy location on the map:\n${link}`;

  if (navigator.share) {
    try {
      await navigator.share({ title: name, text: shareText, url: link });
      return;
    } catch (err) {
      // User dismissed the native share sheet — fall through to the WhatsApp fallback below.
    }
  }
  window.open(`https://wa.me/?text=${encodeURIComponent(shareText)}`, '_blank', 'noopener');
}

/* ============ PHARMACIST: INFO CARD ============ */
async function toggleOpenStatus() {
  const checked = document.getElementById('pharm-open-toggle').checked;
  myPharmacy.is_open = checked;
  myPharmacy.status = checked ? 'open' : 'closed';
  updateOpenCaption();
  renderPharmacies();
  if (myPharmacyId) {
    try { await apiSend(`/api/pharmacies/${myPharmacyId}`, 'PUT', { status: myPharmacy.status }); }
    catch (err) { /* keep the local toggle even if the write didn't persist */ }
  }
}

function updateOpenCaption() {
  const ar = document.getElementById('open-status-caption');
  const en = document.getElementById('open-status-caption-en');
  if (myPharmacy.is_open) {
    ar.textContent = 'مفتوحة الآن'; en.textContent = 'Open now';
    ar.classList.add('is-open'); en.classList.add('is-open');
  } else {
    ar.textContent = 'مغلقة'; en.textContent = 'Closed';
    ar.classList.remove('is-open'); en.classList.remove('is-open');
  }
}

async function savePharmacyInfo(e) {
  const name = document.getElementById('pharm-name').value.trim();
  const address = document.getElementById('pharm-address').value.trim();
  const phone = document.getElementById('pharm-phone').value.trim();
  const hours = document.getElementById('pharm-hours').value.trim();
  if (name) { myPharmacy.name.en = name; myPharmacy.name.ar = name; }
  if (address) { myPharmacy.address.en = address; myPharmacy.address.ar = address; }
  if (phone) myPharmacy.phone = phone;
  if (hours) myPharmacy.hours = hours;
  renderPharmacies();

  const btn = e.currentTarget;
  const original = btn.innerHTML;

  if (myPharmacyId) {
    try {
      await apiSend(`/api/pharmacies/${myPharmacyId}`, 'PUT', {
        name_en: name, name_ar: name, address_en: address, address_ar: address, phone, hours,
      });
    } catch (err) { /* keep the local update even if it didn't persist */ }
  }
  btn.innerHTML = currentLang === 'ar' ? 'تم الحفظ ✓' : 'Saved ✓';
  setTimeout(() => { btn.innerHTML = original; }, 1400);
}

/* ============ PHARMACIST: MEDICINE FORM ============ */
async function handleMedSubmit(e) {
  e.preventDefault();
  const name = document.getElementById('f-name').value.trim();
  const form = document.getElementById('f-form').value.trim();
  const price = Number(document.getElementById('f-price').value);
  const status = document.getElementById('f-status').value; // 'in' | 'low' | 'out'
  const availability = status === 'in' ? 'in_stock' : status === 'low' ? 'low_stock' : 'out_of_stock';
  if (!name || !form || !price) return;

  if (editingMedicineId !== null) {
    const existing = myPharmacy.medicines.find(m => m.id === editingMedicineId);
    if (existing) {
      existing.name = { en: name, ar: name };
      existing.form = { en: form, ar: form };
      existing.price = price;
      existing.availability = availability;
    }
    if (editingMedicineId && myPharmacyId) {
      try {
        await apiSend(`/api/medicines/${editingMedicineId}`, 'PUT', {
          name_en: name, name_ar: name, form_en: form, form_ar: form, price, availability,
        });
      } catch (err) { /* keep local edit even if it didn't persist */ }
    }
  } else {
    const medObj = { id: null, name: { en: name, ar: name }, form: { en: form, ar: form }, price, availability };
    if (myPharmacyId) {
      try {
        const created = await apiSend(`/api/pharmacies/${myPharmacyId}/medicines`, 'POST', {
          name_en: name, name_ar: name, form_en: form, form_ar: form, price, availability,
        });
        medObj.id = created.id;
      } catch (err) { /* keep it as a local-only entry */ }
    }
    myPharmacy.medicines.push(medObj);
  }

  resetMedForm();
  renderPharmacistDashboard();
  renderPharmacies();
}

function resetMedForm() {
  editingMedicineId = null;
  document.getElementById('med-form').reset();
  document.getElementById('form-submit-btn').innerHTML =
    '<span data-ar-only>إضافة الدواء</span><span data-en-only>Add medicine</span>';
  document.getElementById('form-cancel-btn').hidden = true;
  document.getElementById('form-heading').textContent = 'Add medicine';
  document.getElementById('form-heading-ar').textContent = 'إضافة دواء';
}

function cancelEdit() { resetMedForm(); }

function availabilityToStatus(av) { return av === 'in_stock' ? 'in' : av === 'low_stock' ? 'low' : 'out'; }

function startEdit(medicineId) {
  const m = myPharmacy.medicines.find(x => x.id === medicineId);
  if (!m) return;
  editingMedicineId = medicineId;
  document.getElementById('f-name').value = medName(m, 'en');
  document.getElementById('f-form').value = medForm(m, 'en');
  document.getElementById('f-price').value = m.price || '';
  document.getElementById('f-status').value = availabilityToStatus(m.availability);
  document.getElementById('form-submit-btn').innerHTML =
    '<span data-ar-only>تحديث الدواء</span><span data-en-only>Update medicine</span>';
  document.getElementById('form-cancel-btn').hidden = false;
  document.getElementById('form-heading').textContent = 'Edit medicine';
  document.getElementById('form-heading-ar').textContent = 'تعديل الدواء';
  document.getElementById('med-form').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function quickUpdateStock(medicineId, statusValue) {
  const availability = statusValue === 'in' ? 'in_stock' : statusValue === 'low' ? 'low_stock' : 'out_of_stock';
  const m = myPharmacy.medicines.find(x => x.id === medicineId);
  if (m) m.availability = availability;
  renderPharmacistDashboard();
  renderPharmacies();
  if (medicineId) {
    try { await apiSend(`/api/medicines/${medicineId}`, 'PUT', { availability }); }
    catch (err) { /* keep the local status even if it didn't persist */ }
  }
}

async function deleteMed(medicineId) {
  const msg = currentLang === 'ar' ? 'هل تريد حذف هذا الدواء من القائمة؟' : 'Remove this medicine from your listing?';
  if (!confirm(msg)) return;
  myPharmacy.medicines = myPharmacy.medicines.filter(m => m.id !== medicineId);
  if (editingMedicineId === medicineId) resetMedForm();
  renderPharmacistDashboard();
  renderPharmacies();
  if (medicineId) {
    try {
      await fetch(`/api/medicines/${medicineId}`, { method: 'DELETE' });
    } catch (err) { /* keep it removed locally even if the write didn't persist */ }
  }
}

/* ============ PHARMACIST: RENDER ============ */
function renderPharmacistDashboard() {
  if (!myPharmacy) return;
  document.getElementById('pharm-name').value = myPharmacy.name.en;
  document.getElementById('pharm-address').value = myPharmacy.address.en;
  document.getElementById('pharm-phone').value = myPharmacy.phone || '';
  document.getElementById('pharm-hours').value = myPharmacy.hours || '';
  document.getElementById('pharm-open-toggle').checked = !!myPharmacy.is_open;
  updateOpenCaption();

  const lang = currentLang;
  const list = document.getElementById('inv-list');
  const countEl = document.getElementById('inv-count');

  countEl.textContent = lang === 'ar'
    ? `${myPharmacy.medicines.length} دواء`
    : `${myPharmacy.medicines.length} medicine${myPharmacy.medicines.length === 1 ? '' : 's'}`;

  if (myPharmacy.medicines.length === 0) {
    list.innerHTML = `<div class="inv-empty">${lang === 'ar' ? 'لم تتم إضافة أدوية بعد.' : 'No medicines listed yet.'}</div>`;
    return;
  }

  list.innerHTML = myPharmacy.medicines.map(m => `
    <div class="inv-card">
      <div class="inv-card-top">
        <div>
          <div class="inv-name">${escapeHtml(medName(m, lang))}</div>
          <div class="inv-meta">${escapeHtml(medForm(m, lang))} · <span class="inv-price">SDG ${Number(m.price || 0).toLocaleString()}</span></div>
        </div>
        <span class="stock-tag ${m.availability === 'in_stock' ? 'in' : m.availability === 'low_stock' ? 'low' : 'out'}">${statusLabel[m.availability][lang]}</span>
      </div>
      <div class="inv-actions">
        <button type="button" class="inv-btn" onclick="startEdit(${m.id})">${lang === 'ar' ? 'تعديل' : 'Edit'}</button>
        <select class="quick-select" onchange="quickUpdateStock(${m.id}, this.value)" aria-label="Update stock">
          <option value="in" ${m.availability === 'in_stock' ? 'selected' : ''}>${lang === 'ar' ? 'متوفر' : 'In stock'}</option>
          <option value="low" ${m.availability === 'low_stock' ? 'selected' : ''}>${lang === 'ar' ? 'كمية محدودة' : 'Low stock'}</option>
          <option value="out" ${m.availability === 'out_of_stock' ? 'selected' : ''}>${lang === 'ar' ? 'غير متوفر' : 'Out of stock'}</option>
        </select>
        <button type="button" class="inv-btn danger" onclick="deleteMed(${m.id})">${lang === 'ar' ? 'حذف' : 'Delete'}</button>
      </div>
    </div>
  `).join('');
}

/* ============ INIT ============ */
document.addEventListener('DOMContentLoaded', () => {
  renderPharmacies();   // shows the "waiting for your location" placeholder immediately
  captureLocation();    // then request GPS permission automatically — no manual entry needed
});
