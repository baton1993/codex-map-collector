/* Codex Map Collector */
'use strict';

const S = {
  agents: [], selectedAgent: null, selectedModel: '',
  currentFile: null,
  tableData: null,   // {columns, rows}
  filtered: [],      // [{_idx, ...fields}]
  selected: new Set(), // selected row indices
  visibleColumns: null,
  activeRow: null,   // row obj for detail pane
  activeFilters: new Set(),
  styles: [], haTemplates: [], customTemplates: [],
  styleMode: 'auto', selectedStyle: 'auto', selectedHaTemplate: '',
  landingJobId: null, parserJobId: null,
  enrichJobId: null, enrichResultPath: null,
  webEnrichJobId: null, webEnrichResults: [],
  legalJobId: null, legalResults: [],
  screenJobId: null,
  batchJobId: null,
  batchPool: [],
  sendQueue: [],
  mapKeys: {},
};

// ══════════════════════════════════════════
// INIT & SETUP
// ══════════════════════════════════════════

async function stopJob(jid) {
  if (!jid) return;
  if (!confirm('Отменить текущую задачу?')) return;
  try {
    const res = await api(`/api/job/${jid}/cancel`, 'POST');
    if (res.ok) {
      alert('Задача остановлена.');
    }
  } catch (e) {
    console.error('Stop error:', e);
  }
}

async function shutdownApp() {
  if (!confirm('Вы уверены, что хотите завершить работу приложения?\\n\\nСервер будет выключен, эта страница перестанет работать.')) return;
  try {
    await api('/api/shutdown', 'POST');
  } catch (e) {}
  document.body.innerHTML = '<div style="display:flex;height:100vh;align-items:center;justify-content:center;flex-direction:column;color:#64748b"><div style="font-size:3rem;margin-bottom:1rem">⏻</div><h2>Сервер выключен.</h2><p>Можете закрыть эту вкладку.</p></div>';
}

document.addEventListener('DOMContentLoaded', async () => {
  await Promise.all([loadAgents(), loadSettings(), loadStyles(), loadMemo(), loadHaTemplates()]);
  onProviderChange();
});

// ══════════════════════════════════════════
// TABS
// ══════════════════════════════════════════
function switchTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn[data-tab]').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelector(`[data-tab="${name}"]`).classList.add('active');
  // При переходе на лендинги — обновить список компаний из актуальной таблицы
  if (name === 'landing') updateLandingCompanySelect();
  if (name === 'legal') updateLegalUrls();
  if (name === 'send') refreshSendStats();
}

// Sub-tab для лендингов
function switchLandingTab(name) {
  const displayMode = {
    table: 'flex',
    research: 'flex',
    md: 'flex',
    html: 'flex',
    send: 'flex',
    templates: 'flex',
  };
  ['table','research','md','html','send','templates'].forEach(t => {
    const el = document.getElementById(`lsub-${t}`);
    if (el) el.style.display = t === name ? displayMode[t] : 'none';
    document.getElementById(`lst-${t}`)?.classList.toggle('active', t === name);
  });
  if (name === 'templates') filterTemplates();
  if (name === 'table') renderLandingTable();
  if (name === 'send') renderLandingSendLinks();
}

function switchSubTab(parent, sub) {
  const subs = document.querySelectorAll(`#tab-${parent} [id^="sub-"]`);
  subs.forEach(el => { el.style.display = 'none'; el.style.flexDirection = ''; });
  const target = document.getElementById(`sub-${sub}`);
  if (target) { target.style.display = 'flex'; target.style.flexDirection = sub === 'table' ? 'column' : 'row'; }
  document.querySelectorAll(`#tab-${parent} .tab-btn`).forEach(b => b.classList.remove('active'));
  const stBtn = document.getElementById(`st-${sub}`);
  if (stBtn) stBtn.classList.add('active');
}

// ══════════════════════════════════════════
// AGENTS
// ══════════════════════════════════════════
async function loadAgents() {
  const data = await api('/api/agents').catch(() => ({agents: []}));
  S.agents = data.agents || [];
  const avail = S.agents.find(a => a.available);
  if (avail && !S.selectedAgent) selectAgent(avail.id, false);
  renderAgentChip();
}

async function loadSettings() {
  const s = await api('/api/settings').catch(() => ({}));
  if (s.selected_agent) selectAgent(s.selected_agent, false);
  if (s.selected_model) S.selectedModel = s.selected_model;
  S.mapKeys = s.map_api_keys || {};
  onProviderChange();
}

function selectAgent(id, save = true) {
  S.selectedAgent = S.agents.find(a => a.id === id) || {id, label: id, bin: id, available: false};
  renderAgentChip();
  updateLandingModels();
  if (save) api('/api/settings', {method: 'PATCH', json: {selected_agent: id}}).catch(() => {});
}

function renderAgentChip() {
  const a = S.selectedAgent;
  document.getElementById('agent-dot').className = 'dot' + (a?.available ? ' ok' : '');
  document.getElementById('agent-label').textContent = a ? a.label : 'Нет агента';
}

function openAgentModal() {
  const list = document.getElementById('agent-list');
  list.innerHTML = S.agents.map(a => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;
         background:var(--s2);border-radius:8px;border:1px solid ${S.selectedAgent?.id===a.id?'var(--accent)':'var(--border)'}">
      <div>
        <div style="font-size:.85rem;font-weight:600">${a.label}</div>
        <div style="font-size:.7rem;color:var(--muted)">${a.available ? '✅ ' + a.bin : '❌ Не найден'}</div>
      </div>
      ${a.available ? `<button class="btn btn-accent" style="padding:5px 12px;font-size:.75rem"
        onclick="selectAgent('${a.id}');closeModal('agent-modal')">Выбрать</button>` : ''}
    </div>`).join('');
  showModal('agent-modal');
}

// ══════════════════════════════════════════
// PARSER
// ══════════════════════════════════════════
async function startParser() {
  const city = v('p-city'), query = v('p-query');
  if (!city || !query) { alert('Укажите город и запрос'); return; }
  const provider = v('p-provider') || '2gis';
  const apiKey = v('p-api-key');
  if (document.getElementById('p-save-key')?.checked && apiKey) {
    S.mapKeys[provider] = apiKey;
    api('/api/settings', {method: 'PATCH', json: {map_api_keys: {[provider]: apiKey}}}).catch(() => {});
  }
  show('p-running'); hide('p-idle');
  document.getElementById('p-result').style.display = 'none';
  clearLog('p-log');
  setText('p-status', `Парсинг: ${provider} / ${city} / ${query}...`);

  const data = await api('/api/parse', {method:'POST', json:{
    provider,
    city, query,
    limit: int('p-limit', 200),
    sleep_min: parseFloat(v('p-sleep')||'3'),
    sleep_max: parseFloat(v('p-sleep')||'3') * 1.5,
    save_raw: document.getElementById('p-raw').checked,
    fetch_reviews: provider === '2gis' && document.getElementById('p-fetch-reviews').checked,
    api_key: apiKey,
    locale: 'ru_RU',
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.parserJobId = data.job_id;
  watchJob(S.parserJobId, 'p-log', job => {
    if (job.status === 'done') {
      const r = job.result || {};
      S._parserCsvPath = r.csv_path;
      setText('p-result-text', `✅ Найдено ${r.count || 0} компаний`);
      show('p-result', 'p-idle'); hide('p-running');
      document.getElementById('p-result').style.display = 'block';
      hide('p-running');
      // Разблокируем кнопку загрузки из парсера
      const btn = document.getElementById('btn-load-parser');
      if (btn) btn.disabled = false;
    } else {
      show('p-idle'); hide('p-running');
      setText('p-status', '❌ Ошибка парсера');
    }
  });
}

function onProviderChange() {
  const provider = v('p-provider') || '2gis';
  const keyWrap = document.getElementById('p-api-key-wrap');
  const reviewsWrap = document.getElementById('p-fetch-reviews-wrap');
  const keyInput = document.getElementById('p-api-key');
  const needsKey = ['yandex', 'google'].includes(provider);
  if (keyWrap) keyWrap.style.display = needsKey || provider === '2gis' ? 'block' : 'none';
  if (reviewsWrap) reviewsWrap.style.display = provider === '2gis' ? 'flex' : 'none';
  if (keyInput && S.mapKeys?.[provider]) keyInput.value = S.mapKeys[provider];
  const hints = {
    '2gis': 'Нужен официальный 2GIS API key. Введите его здесь или задайте DGIS_API_KEY локально.',
    'yandex': 'Нужен ключ Yandex Maps Search API для поиска организаций.',
    'google': 'Нужен ключ Google Places API для Text Search.',
    'osm': 'Ключ не нужен. Nominatim подходит для лёгкого мирового поиска, но часто отдаёт меньше бизнес-контактов.',
  };
  const idle = document.getElementById('p-idle');
  if (idle && !document.getElementById('p-running')?.offsetParent) {
    idle.innerHTML = `Заполните параметры и нажмите «Запустить парсер».<br><br>${hints[provider]}<br><br>Результат сохраняется в едином CSV для таблицы, обогащения, лендингов и выгрузки.`;
  }
}

function useParserResult() {
  if (!S._parserCsvPath) return;
  document.getElementById('e-path').value = S._parserCsvPath;
  switchTab('enrich');
  switchSubTab('enrich', 'enrich');
}

function loadFromParser() {
  if (!S._parserCsvPath) { alert('Сначала запустите парсер'); return; }
  api('/api/table?path=' + encodeURIComponent(S._parserCsvPath))
    .then(data => loadTableData(data, S._parserCsvPath.split('/').pop()))
    .catch(e => alert(e.message));
}

function loadFromEnricher() {
  if (!S.enrichResultPath) { alert('Сначала запустите обогащение'); return; }
  loadEnrichResult();
}

// ══════════════════════════════════════════
// TABLE UPLOAD & RENDER
// ══════════════════════════════════════════
async function uploadTableFile(input) {
  const file = input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  const data = await api('/api/upload', {method:'POST', body:fd}).catch(e => { alert(e.message); return null; });
  if (!data) return;
  S.currentFile = data.path;
  loadTableData(data.data, data.name);
}

function handleTableDrop(ev) {
  ev.preventDefault();
  document.querySelector('.upload-zone')?.classList.remove('drag');
  const file = ev.dataTransfer.files[0];
  if (!file) return;
  const input = document.getElementById('tbl-upload');
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  uploadTableFile(input);
}

function loadTableData(data, name) {
  S.tableData = data;
  S.visibleColumns = new Set(data.columns);
  S.filtered = data.rows.map((r, i) => toObj(r, data.columns, i));
  applyFilters();
  updateLandingCompanySelect();
  switchSubTab('enrich', 'table');
  // Показываем имя файла в тулбаре всех вкладок
  const badge = document.createElement('div');
  badge.style.cssText = 'position:fixed;bottom:10px;right:10px;background:var(--ok);color:#fff;padding:6px 14px;border-radius:20px;font-size:.75rem;z-index:999;animation:fadeIn .3s';
  badge.textContent = `✅ Таблица загружена: ${name} (${data.rows.length} строк)`;
  document.body.appendChild(badge);
  setTimeout(() => badge.remove(), 3000);
}

function toObj(row, cols, idx) {
  const o = {_idx: idx};
  cols.forEach((c, i) => o[c] = row[i] || '');
  return o;
}

function applyFilters() {
  if (!S.tableData) return;
  const q = v('t-search').toLowerCase();
  const seg = v('t-seg');
  const noSite = S.activeFilters.has('no_site');
  const hasEmail = S.activeFilters.has('has_email');

  S.filtered = S.tableData.rows
    .map((r, i) => toObj(r, S.tableData.columns, i))
    .filter(row => {
      const name = (row['Название'] || '').toLowerCase();
      if (q && !name.includes(q)) return false;
      if (seg) { const rs = row['Сегмент'] || ''; if (!rs.startsWith(seg)) return false; }
      if (noSite && row['Сайт'] && row['Сайт'] !== 'None') return false;
      if (hasEmail && !row['Почта электронная']) return false;
      return true;
    });

  setText('t-count', S.filtered.length + ' строк');
  renderTable();
}

function renderTable() {
  const wrap = document.getElementById('tbl-wrap');
  if (!S.tableData || !S.filtered.length) {
    wrap.innerHTML = '<div style="padding:20px;color:var(--muted);font-size:.85rem">Нет данных / загрузите файл</div>';
    return;
  }
  const cols = getVisibleColumns();
  let h = `<table><thead><tr>
    <th style="width:30px"><input type="checkbox" id="chk-all" onchange="toggleAll(this.checked)"></th>
    ${cols.map(c => `<th onclick="sortByCol(${S.tableData.columns.indexOf(c)})">${esc(c)}</th>`).join('')}
  </tr></thead><tbody>`;

  S.filtered.forEach((row, fi) => {
    const chk = S.selected.has(row._idx);
    const sel = S.activeRow && S.activeRow._idx === row._idx;
    h += `<tr class="${sel ? 'sel-row' : ''}" onclick="selectRow(${fi})">
      <td onclick="event.stopPropagation()"><input type="checkbox" ${chk?'checked':''} onchange="toggleRow(${row._idx},this.checked)"></td>
      ${cols.map(c => `<td title="${esc(row[c]||'')}" onclick="event.stopPropagation();editCell(this,${fi},${S.tableData.columns.indexOf(c)})">${esc(String(row[c]||'').slice(0,80))}</td>`).join('')}
    </tr>`;
  });
  h += '</tbody></table>';
  wrap.innerHTML = h;
}

function editCell(td, fi, ci) {
  const row = S.filtered[fi];
  const col = S.tableData.columns[ci];
  const cur = row[col] || '';
  td.className = 'editing';
  td.innerHTML = `<input value="${esc(cur)}" onblur="commitEdit(this,${fi},${ci})" onkeydown="if(event.key==='Enter')this.blur();if(event.key==='Escape'){this.value='${esc(cur)}';this.blur()}">`;
  td.querySelector('input').focus();
}

function commitEdit(input, fi, ci) {
  const row = S.filtered[fi];
  const col = S.tableData.columns[ci];
  const newVal = input.value;
  // Update in main data
  S.tableData.rows[row._idx][ci] = newVal;
  row[col] = newVal;
  renderTable();
}

async function saveTableEdits() {
  if (!S.tableData || !S.currentFile) { alert('Нет загруженной таблицы'); return; }
  await api('/api/table/save', {method:'POST', json:{
    path: S.currentFile,
    columns: S.tableData.columns,
    rows: S.tableData.rows,
  }});
  alert('✅ Сохранено');
}

function selectRow(fi) {
  S.activeRow = S.filtered[fi];
  renderTable();
  renderDetail();
  show('detail-pane');
  document.getElementById('detail-pane').style.display = 'flex';
}

function renderDetail() {
  const r = S.activeRow;
  if (!r) return;
  document.getElementById('dp-name').textContent = r['Название'] || '—';
  const seg = r['Сегмент'] || '';
  const cls = seg.startsWith('A')?'seg-a':seg.startsWith('B')?'seg-b':'seg-c';
  document.getElementById('dp-seg').innerHTML = seg ?
    `<span class="seg-badge ${cls}">${seg.split(' ')[0]}</span>` : '';

  const fields = [['Сайт','🌐'],['Номер','📞'],['Почта электронная','✉️'],
    ['Адрес','📍'],['Рейтинг','⭐'],['Отзывы','💬'],['Статус сайта','🔄'],
    ['Свежесть балл','📊'],['Ссылка 2ГИС','🗺️']];
  document.getElementById('dp-fields').innerHTML = '<h3>Данные</h3>' +
    fields.map(([k,icon]) => {
      const v2 = r[k];
      if (!v2 || v2==='None'||v2==='nan') return '';
      return `<div class="dp-row"><span class="k">${icon} ${k}</span><span class="v">${esc(String(v2).slice(0,100))}</span></div>`;
    }).join('');
}

function toggleRow(idx, checked) {
  if (checked) S.selected.add(idx); else S.selected.delete(idx);
  renderLandingTable();
}
function toggleAll(checked) {
  S.filtered.forEach(r => { if(checked) S.selected.add(r._idx); else S.selected.delete(r._idx); });
  renderTable();
  renderLandingTable();
}
function selectAllRows() { toggleAll(true); renderTable(); }

function getVisibleColumns() {
  if (!S.tableData) return [];
  if (!S.visibleColumns) S.visibleColumns = new Set(S.tableData.columns);
  const visible = S.tableData.columns.filter(c => S.visibleColumns.has(c));
  return visible.length ? visible : S.tableData.columns;
}

function openColumnsModal() {
  if (!S.tableData) { alert('Сначала загрузите таблицу'); return; }
  const list = document.getElementById('cols-list');
  list.innerHTML = S.tableData.columns.map((c, i) => `
    <label style="display:flex;gap:8px;align-items:center;padding:7px 8px;background:var(--s2);border-radius:8px;margin-bottom:6px;font-size:.8rem">
      <input type="checkbox" ${S.visibleColumns?.has(c) ? 'checked' : ''} onchange="toggleTableColumnByIndex(${i},this.checked)">
      <span>${esc(c)}</span>
    </label>`).join('');
  showModal('columns-modal');
}

function toggleTableColumnByIndex(index, checked) {
  const col = S.tableData?.columns?.[index];
  if (col) toggleTableColumn(col, checked);
}

function toggleTableColumn(col, checked) {
  if (!S.visibleColumns) S.visibleColumns = new Set(S.tableData?.columns || []);
  if (checked) S.visibleColumns.add(col); else S.visibleColumns.delete(col);
  renderTable();
  renderLandingTable();
}

function addRow() {
  if (!S.tableData) { alert('Сначала загрузите таблицу'); return; }
  const newRow = S.tableData.columns.map(() => '');
  S.tableData.rows.unshift(newRow);
  // Обновляем индексы в S.selected, так как все строки сдвинулись
  const newSelected = new Set();
  S.selected.forEach(idx => newSelected.add(idx + 1));
  S.selected = newSelected;
  applyFilters();
}

function deleteSelectedRows() {
  if (!S.tableData || !S.selected.size) { alert('Выберите строки для удаления'); return; }
  if (!confirm(`Удалить ${S.selected.size} строк?`)) return;
  const toDelete = new Set(S.selected);
  S.tableData.rows = S.tableData.rows.filter((_, i) => !toDelete.has(i));
  S.selected.clear();
  applyFilters();
  updateLandingCompanySelect();
}

function addBlankColumn() {
  if (!S.tableData) return;
  const name = prompt('Название нового столбца');
  if (!name || S.tableData.columns.includes(name)) return;
  S.tableData.columns.push(name);
  S.tableData.rows.forEach(r => r.push(''));
  if (!S.visibleColumns) S.visibleColumns = new Set();
  S.visibleColumns.add(name);
  applyFilters();
  openColumnsModal();
}

function toggleChip(el, filter) {
  el.classList.toggle('on');
  if (S.activeFilters.has(filter)) S.activeFilters.delete(filter); else S.activeFilters.add(filter);
  applyFilters();
}

function sortByCol(ci) {
  S.tableData.rows.sort((a, b) => String(a[ci]||'').localeCompare(String(b[ci]||''), 'ru'));
  applyFilters();
}

// ══════════════════════════════════════════
// ENRICHER
// ══════════════════════════════════════════
function setEnrichFile(input) {
  const file = input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  api('/api/upload', {method:'POST', body:fd}).then(d => {
    document.getElementById('e-path').value = d.path;
    S.currentFile = d.path;
  }).catch(e => alert(e.message));
}

function useParserForEnrich() {
  if (S._parserCsvPath) document.getElementById('e-path').value = S._parserCsvPath;
  else alert('Сначала запустите парсер');
}

async function startEnrich() {
  const path = v('e-path') || S.currentFile;
  if (!path) { alert('Укажите файл'); return; }
  show('e-running'); hide('e-idle');
  document.getElementById('e-result').style.display = 'none';
  clearLog('e-log');
  setText('e-status', 'Обогащение запущено...');

  const data = await api('/api/enrich', {method:'POST', json:{
    input_path: path,
    workers: int('e-workers', 3),
    timeout: int('e-timeout', 25000),
    expand_socials: document.getElementById('e-expand-soc').checked,
    collect_reviews: document.getElementById('e-collect-reviews')?.checked ?? true,
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.enrichJobId = data.job_id;
  watchJob(S.enrichJobId, 'e-log', job => {
    hide('e-running'); show('e-idle');
    if (job.status === 'done') {
      S.enrichResultPath = job.result?.xlsx_path;
      setText('e-status', '✅ Готово');
      document.getElementById('e-result').style.display = 'block';
      // Авто-загрузка таблицы
      loadEnrichResult();
      // Разблокируем кнопку загрузки
      const btn = document.getElementById('btn-load-enricher');
      if (btn) btn.disabled = false;
    } else {
      setText('e-status', '❌ Ошибка (смотри лог)');
    }
  });
}

async function loadEnrichResult() {
  if (!S.enrichResultPath) return;
  const data = await api('/api/table?path=' + encodeURIComponent(S.enrichResultPath));
  S.currentFile = S.enrichResultPath;
  loadTableData(data, S.enrichResultPath.split('/').pop());
}

function downloadEnrichResult() {
  if (S.enrichResultPath) window.open('/api/download?path=' + encodeURIComponent(S.enrichResultPath));
}

// ══════════════════════════════════════════
// WEB ENRICHER
// ══════════════════════════════════════════
async function startWebEnrich() {
  if (!S.tableData) { alert('Сначала загрузите таблицу'); return; }
  const src = v('wr-source');
  let companies = S.filtered;
  if (src === 'no_site') companies = S.filtered.filter(r => !r['Сайт'] || r['Сайт']==='None');
  if (src === 'selected') companies = S.filtered.filter(r => S.selected.has(r._idx));

  if (!companies.length) { alert('Нет компаний для поиска'); return; }

  show('wr-running'); hide('wr-idle');
  clearLog('wr-log');
  setText('wr-status', `Поиск для ${companies.length} компаний...`);

  const plain = companies.map(r => { const o = {...r}; delete o._idx; return o; });
  const data = await api('/api/enrich/web', {method:'POST', json:{
    companies: plain,
    concurrency: int('wr-conc', 3),
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.webEnrichJobId = data.job_id;
  watchJob(S.webEnrichJobId, 'wr-log', job => {
    hide('wr-running'); show('wr-idle');
    if (job.status === 'done') {
      S.webEnrichResults = job.result?.results || [];
      setText('wr-status', `✅ Обогащено: ${S.webEnrichResults.length}`);
      document.getElementById('wr-result').style.display = 'block';
      renderWebEnrichResults();
    } else {
      setText('wr-status', '❌ Ошибка');
    }
  });
}

function renderWebEnrichResults() {
  const list = document.getElementById('wr-results-list');
  list.innerHTML = S.webEnrichResults.map(r => {
    const reviews = r.web_reviews || [];
    const sources = r.research_sources || [];
    const reviewsHtml = reviews.length
      ? reviews.slice(0, 5).map(rv => {
          const stars = '⭐'.repeat(Math.min(5, rv.rating || 5));
          return `<div style="background:var(--s3);border-radius:6px;padding:8px 10px;margin-bottom:5px">
            <div style="font-size:.7rem;color:var(--a2);margin-bottom:3px">${esc(rv.author||'Клиент')} ${rv.date ? '· ' + esc(rv.date) : ''} ${stars} ${rv.source ? '· ' + esc(rv.source) : ''}</div>
            <div style="font-size:.78rem;line-height:1.5">${esc(rv.text||'')}</div>
          </div>`;
        }).join('')
      : '<div style="font-size:.72rem;color:var(--muted);padding:4px 0">Отзывы не найдены</div>';

    const srcHtml = sources.length
      ? `<div style="font-size:.68rem;color:var(--muted);margin-top:6px">📎 Источники: ${sources.map(s => esc(s.source||s.url)).join(', ')}</div>`
      : '';

    return `<div style="background:var(--s2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:12px">
      <div style="font-size:.85rem;font-weight:700;margin-bottom:6px">${esc(r['Название']||'—')}</div>
      ${r.web_description ? `<div style="font-size:.78rem;color:var(--muted);margin-bottom:8px;line-height:1.5">${esc(r.web_description.slice(0,300))}</div>` : ''}
      <div style="font-size:.72rem;color:var(--a2);font-weight:600;margin-bottom:6px">💬 Отзывы (${reviews.length}):</div>
      ${reviewsHtml}
      ${srcHtml}
    </div>`;
  }).join('');
}

function mergeWebEnrich() {
  if (!S.tableData || !S.webEnrichResults.length) return;
  mergeWebResultsToTable(S.webEnrichResults);
  updateLandingCompanySelect();
  alert('✅ Веб-данные добавлены в таблицу');
}

// ══════════════════════════════════════════
// LEGAL
// ══════════════════════════════════════════
async function loadMemo() {
  const d = await api('/api/legal/memo').catch(() => ({}));
  const el = document.getElementById('memo-text');
  if (el) el.textContent = (d.full_text || '').slice(0, 1500) + '...';
}

function onLegalSrcChange() {
  const src = v('leg-src');
  document.getElementById('leg-manual').style.display = src === 'manual' ? 'block' : 'none';
}

function getLegalUrls() {
  const src = v('leg-src');
  if (src === 'manual') return v('leg-urls').split('\n').map(u => u.trim()).filter(u => u.startsWith('http'));
  if (!S.tableData) return [];
  // Только компании с живым сайтом (Статус сайта = живой, сегмент A или B)
  let rows = src === 'selected'
    ? S.filtered.filter(r => S.selected.has(r._idx))
    : S.filtered;
  return rows
    .filter(r => {
      const site = r['Сайт'] || '';
      const seg = r['Сегмент'] || '';
      const status = r['Статус сайта'] || '';
      return site.startsWith('http') && (seg.startsWith('A') || seg.startsWith('B') || status === 'живой');
    })
    .map(r => r['Сайт'])
    .filter(Boolean);
}

async function startLegal() {
  const urls = getLegalUrls();
  if (!urls.length) { alert('Нет подтверждённых сайтов для проверки'); return; }
  show('leg-running'); hide('leg-idle');
  document.getElementById('leg-results').style.display = 'none';
  clearLog('leg-log');

  const data = await api('/api/legal/check', {method:'POST', json:{
    urls,
    agent_bin: 'codex',
    use_ai: document.getElementById('leg-ai').checked,
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.legalJobId = data.job_id;
  watchJob(S.legalJobId, 'leg-log', job => {
    if (job.status === 'done') {
      S.legalResults = job.result?.results || [];
      renderLegalResults();
      document.getElementById('leg-results').style.display = 'block';
    }
  });
}

function renderLegalResults() {
  document.getElementById('leg-list').innerHTML = S.legalResults.map(r => {
    const risk = r.risk_score || 0;
    const rc = risk >= 60 ? 'var(--err)' : risk >= 30 ? 'var(--warn)' : 'var(--ok)';
    const viols = (r.violations || []).map(v => `
      <div class="viol ${v.severity}">
        <div class="vt">${esc(v.title)}</div>
        <div class="vl">${esc(v.law)}</div>
        <div class="vf">Штраф: ${esc(v.fine)}</div>
      </div>`).join('');
    return `
      <div style="background:var(--s2);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:12px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
          <div>
            <a href="${r.url}" target="_blank" rel="noopener" style="font-size:.85rem;font-weight:700;color:var(--text);text-decoration:none;border-bottom:1px solid var(--border)" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text)'">${esc(r.url)}</a>
            <div style="font-size:.72rem;color:var(--muted);margin-top:3px">
              ${r.accessible ? `✅ ${r.http_code}` : '❌ Недоступен'}
              ${r.https ? ' · 🔒 HTTPS' : ' · ⚠️ HTTP'}
              ${(r.cross_border||[]).length ? ` · 🌐 Трекеры: ${r.cross_border.slice(0,3).join(', ')}` : ''}
            </div>
          </div>
          <div style="text-align:center">
            <div style="font-size:1.4rem;font-weight:800;color:${rc}">${risk}</div>
            <div style="font-size:.6rem;color:var(--muted)">риск</div>
          </div>
        </div>
        ${(r.violations||[]).length ? viols : '<div style="font-size:.8rem;color:var(--ok)">✅ Явных нарушений не обнаружено</div>'}
      </div>`;
  }).join('');
}

function downloadLegalReport() {
  if (!S.legalJobId) return;
  api(`/api/job/${S.legalJobId}`).then(job => {
    const p = job.result?.json_path;
    if (p) window.open('/api/download?path=' + encodeURIComponent(p));
  });
}

// ══════════════════════════════════════════
// LANDING
// ══════════════════════════════════════════
async function loadStyles() {
  const data = await api('/api/landing/styles').catch(() => ({styles:[],custom_templates:[],ha_templates:[]}));
  S.styles = data.styles || [];
  S.customTemplates = data.custom_templates || [];
  S.haTemplates = data.ha_templates || [];
  renderStylesGrid();
  populateHaSelect();
  populateCustomSelect();
  updateLandingModels();
  populateLandingTemplateSelect();
}

function renderStylesGrid() {
  const grid = document.getElementById('styles-grid');
  if (!grid) return;
  grid.innerHTML = S.styles.map(s => `
    <div class="style-card ${S.selectedStyle===s.id?'sel':''}" onclick="selectStyle('${s.id}')">
      <div class="sc-c" style="background:${s.preview_color}"></div>
      <div class="sc-i"><div class="sc-n">${esc(s.name)}</div><div class="sc-d">${esc(s.description)}</div></div>
    </div>`).join('');
}

function selectStyle(id) {
  S.selectedStyle = id;
  renderStylesGrid();
}

function populateHaSelect() {
  const sel = document.getElementById('l-ha-tmpl');
  if (!sel) return;
  sel.innerHTML = '<option value="">— выберите —</option>' +
    S.haTemplates.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
}

function populateCustomSelect() {
  const sel = document.getElementById('l-custom-tmpl');
  if (!sel) return;
  sel.innerHTML = '<option value="">— не использовать —</option>' +
    S.customTemplates.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
}

function setStyleMode(mode) {
  S.styleMode = mode;
  ['auto','manual','ha'].forEach(m => {
    document.getElementById(`ch-${m}-style`).classList.toggle('on', m === mode);
  });
  document.getElementById('style-manual').style.display = mode === 'manual' ? 'block' : 'none';
  document.getElementById('style-ha').style.display = mode === 'ha' ? 'block' : 'none';
  document.getElementById('style-auto-hint').style.display = mode === 'auto' ? 'block' : 'none';
}

function updateLandingModels() {
  const models = {
    template: [''],
    codex: ['', 'gpt-5-5-ultra', 'gpt-5-0-pro', 'gpt-4-o-next'],
  };
  const agent = v('l-agent');
  const sel = document.getElementById('l-model');
  if (!sel) return;
  sel.innerHTML = (models[agent] || ['']).map(m =>
    `<option value="${m}">${m || 'Default'}</option>`
  ).join('');
}

function populateLandingTemplateSelect() {
  const sel = document.getElementById('l-template-select');
  if (!sel) return;
  const current = selHaId || S.selectedHaTemplate || '';
  sel.innerHTML = '<option value="">— выбрать шаблон —</option>' +
    S.haTemplates.map(t => `<option value="${t.id}" ${current===t.id?'selected':''}>${esc(t.emoji || '')} ${esc(t.name)}</option>`).join('');
}

function updateLandingCompanySelect() {
  const sel = document.getElementById('l-company');
  if (!sel || !S.tableData) return;
  const currentVal = sel.value;
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  sel.innerHTML = '<option value="">— выберите из таблицы —</option>' +
    rows.map(r => `<option value="${r._idx}">${esc(r['Название'] || 'Строка ' + r._idx)}</option>`).join('');
  // Восстанавливаем предыдущий выбор если он ещё есть
  if (currentVal && rows.some(r => String(r._idx) === currentVal)) {
    sel.value = currentVal;
  }
  const batchBtn = document.getElementById('l-batch-btn');
  if (batchBtn) batchBtn.disabled = rows.length === 0;
  renderLandingTable();
}

function selectLandingCompany(idx) {
  if (idx === '' || !S.tableData) return;
  const row = S.tableData.rows[parseInt(idx)];
  S.activeRow = toObj(row, S.tableData.columns, parseInt(idx));
  document.getElementById('l-gen-btn').disabled = false;
}

function _setLandingActive(rows, label) {
  if (!rows.length) return;
  S.activeRow = rows[0];
  document.getElementById('l-company').value = String(rows[0]._idx);
  document.getElementById('l-gen-btn').disabled = false;
  const info = document.getElementById('l-active-company');
  if (info) info.textContent = `✅ ${label}: ${rows.length} шт. Первая: ${rows[0]['Название'] || '?'}`;
}

function useSelectedForLanding() {
  if (!S.tableData || !S.selected.size) { alert('Сначала отметьте строки галочками в таблице'); return; }
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i)).filter(r => S.selected.has(r._idx));
  _setLandingActive(rows, 'Выбранные');
}

function useNoSiteForLanding() {
  if (!S.tableData) { alert('Загрузите таблицу'); return; }
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i))
    .filter(r => { const s = r['Сайт'] || ''; return !s.startsWith('http') || r['Сегмент']?.startsWith('C') || !s; });
  if (!rows.length) { alert('Все компании уже имеют сайт'); return; }
  _setLandingActive(rows, 'Без сайта');
}

function useAllForLanding() {
  if (!S.tableData) { alert('Загрузите таблицу'); return; }
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  _setLandingActive(rows, 'Все');
}

function goLanding() {
  if (!S.activeRow) return;
  switchTab('landing');
  document.getElementById('l-company').value = S.activeRow._idx;
  selectLandingCompany(S.activeRow._idx);
}

async function startLanding() {
  const mdDossier = v('l-md') || '';
  if (!S.activeRow && !mdDossier.trim()) { alert('Выберите компанию или вставьте MD'); return; }
  const company = buildLandingCompanyFromMd(mdDossier, S.activeRow);
  document.getElementById('l-log-wrap').style.display = 'block';
  clearLog('l-log');
  document.getElementById('l-gen-btn').disabled = true;
  document.getElementById('l-dl-btn').disabled = true;
  document.getElementById('l-open-btn').disabled = true;
  document.getElementById('l-pub-btn').disabled = true;
  hide('l-preview-wrap');
  show('l-placeholder');
  const logEl = document.getElementById('l-log');
  const log = msg => appendLog(logEl, msg);

  // Определяем стиль и шаблон
  // - 'ha' режим: используем выбранный из галереи шаблон (S.selectedHaTemplate)
  // - 'manual' режим: используем наш встроенный CSS-стиль (S.selectedStyle)
  // - 'auto': подбираем по рубрике
  let style = 'auto';
  let customTmpl = S.selectedHaTemplate || '';
  const tmplType = v('l-tmpl-type') || 'standard';

  const agentBin = v('l-agent') || 'codex';
  const agentModel = v('l-model') || '';

  log(`🚀 Запрос: шаблон=${customTmpl||'auto'}, тип=${tmplType}, агент=${agentBin}`);

  const data = await api('/api/landing/generate', {method:'POST', json:{
    company, style,
    agent_bin: agentBin,
    agent_model: agentModel,
    custom_template_id: customTmpl,
    md_dossier: mdDossier,
    tmpl_type: tmplType,
  }}).catch(e => { alert(e.message); return null; });
  if (!data) { document.getElementById('l-gen-btn').disabled = false; return; }

  S.landingJobId = data.job_id;
  watchJob(S.landingJobId, 'l-log', job => {
    document.getElementById('l-gen-btn').disabled = false;
    if (job.status === 'done') {
      const r = job.result || {};
      setText('l-preview-label', `${r.company_name} · ${r.style_name} · ${Math.round((r.html_size||0)/1024)}KB`);
      hide('l-placeholder');
      document.getElementById('l-preview-wrap').style.display = 'flex';
      setLandingPreviewSrc(`/api/landing/preview/${S.landingJobId}?t=${Date.now()}`);
      document.getElementById('l-dl-btn').disabled = false;
      document.getElementById('l-open-btn').disabled = false;
      document.getElementById('l-pub-btn').disabled = false;
      // Показываем рефайн-бар
      document.getElementById('l-refine-bar').style.display = 'block';
      document.getElementById('l-refine-btn').disabled = false;
      document.getElementById('l-save-btn').disabled = false;
      attachLandingToTable(S.activeRow?._idx ?? company._idx, `/api/landing/preview/${S.landingJobId}`, r.html_path || '');
      renderLandingSendLinks();
    }
  });
}

function buildLandingCompanyFromMd(md, row) {
  const base = row ? rowToPlain(row) : {};
  if (!md || !md.trim()) return base;

  const h1 = md.match(/^#\s+(.+)$/m)?.[1]?.trim();
  const boldName = md.match(/\*\*([^*\n]{3,120})\*\*/)?.[1]?.trim();
  const firstText = md.split('\n').map(s => s.replace(/^#+\s*/, '').trim()).find(Boolean);
  const name = base['Название'] || h1 || boldName || firstText || 'Лендинг из MD';

  const phone = base['Телефон'] || md.match(/(?:телефон|тел\.?|phone)[:\s*]*([+()\d\s-]{6,})/i)?.[1]?.trim() || '';
  const email = base['Почта электронная'] || md.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || '';
  const site = base['Сайт'] || md.match(/https?:\/\/[^\s)]+/i)?.[0] || '';
  const address = base['Адрес'] || md.match(/(?:адрес)[:\s*]*([^\n]+)/i)?.[1]?.trim() || '';

  return {
    ...base,
    _idx: row?._idx,
    'Название': name,
    'Телефон': phone,
    'Почта электронная': email,
    'Сайт': site,
    'Адрес': address,
    'Описание': base['Описание'] || md.slice(0, 1200),
  };
}

function attachLandingToTable(rowIdx, url, filePath = '') {
  if (!S.tableData || rowIdx === undefined || rowIdx === null) return;
  const cols = ['Лендинг HTML', 'Лендинг файл'];
  cols.forEach(col => {
    if (!S.tableData.columns.includes(col)) S.tableData.columns.push(col);
    if (S.visibleColumns) S.visibleColumns.add(col);
  });
  const urlCi = S.tableData.columns.indexOf('Лендинг HTML');
  const pathCi = S.tableData.columns.indexOf('Лендинг файл');
  const row = S.tableData.rows[rowIdx];
  if (!row) return;
  while (row.length <= Math.max(urlCi, pathCi)) row.push('');
  row[urlCi] = url;
  row[pathCi] = filePath;
  applyFilters();
}

function attachBatchLandingsToTable(results) {
  if (!S.tableData || !results?.length) return;
  const nameCi = S.tableData.columns.indexOf('Название');
  results.forEach(r => {
    if (r.error || !r.company) return;
    const idx = S.tableData.rows.findIndex(row => String(row[nameCi] || '') === String(r.company));
    if (idx >= 0) {
      const url = r.html_path ? `/api/download?path=${encodeURIComponent(r.html_path)}` : '';
      attachLandingToTable(idx, url, r.html_path || '');
    }
  });
}

function landingRowsForSelection() {
  if (!S.tableData) return [];
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  const chosen = rows.filter(r => S.selected.has(r._idx));
  return chosen.length ? chosen : rows.filter(r => {
    const site = r['Сайт'] || '';
    return !site.startsWith('http') || r['Сегмент']?.startsWith('C') || !site;
  });
}

function landingCandidateRows() {
  if (!S.tableData) return [];
  const mode = v('l-filter') || 'landing';
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  if (mode === 'all') return rows;
  if (mode === 'selected') return rows.filter(r => S.selected.has(r._idx));
  return rows.filter(r => {
    const site = r['Сайт'] || '';
    return !site.startsWith('http') || r['Сегмент']?.startsWith('C') || !site || S.selected.has(r._idx);
  });
}

function renderLandingTable() {
  const wrap = document.getElementById('l-table-wrap');
  if (!wrap) return;
  if (!S.tableData) {
    wrap.innerHTML = '<div style="padding:16px;color:var(--muted);font-size:.85rem">Загрузите таблицу во вкладке «Обогащение».</div>';
    setText('l-table-count', '0');
    return;
  }
  const q = (v('l-search') || '').toLowerCase();
  const rows = landingCandidateRows().filter(r => {
    if (!q) return true;
    return Object.values(r).some(val => String(val || '').toLowerCase().includes(q));
  });
  const cols = getVisibleColumns();
  setText('l-table-count', `${rows.length} строк · выбрано ${S.selected.size}`);
  wrap.innerHTML = `<table><thead><tr>
    <th style="width:30px"><input type="checkbox" onchange="toggleLandingAll(this.checked)"></th>
    ${cols.map(c => `<th>${esc(c)}</th>`).join('')}
  </tr></thead><tbody>` + rows.map(r => `
    <tr onclick="selectLandingCompany(${r._idx});document.getElementById('l-company').value='${r._idx}'">
      <td onclick="event.stopPropagation()"><input type="checkbox" ${S.selected.has(r._idx)?'checked':''} onchange="toggleRow(${r._idx},this.checked)"></td>
      ${cols.map(c => `<td title="${esc(r[c]||'')}" onclick="event.stopPropagation();editLandingCell(this,${r._idx},${S.tableData.columns.indexOf(c)})">${esc(String(r[c]||'').slice(0,80))}</td>`).join('')}
    </tr>`).join('') + '</tbody></table>';
}

function editLandingCell(td, rowIdx, ci) {
  const row = S.tableData.rows[rowIdx];
  const col = S.tableData.columns[ci];
  const cur = row[ci] || '';
  td.className = 'editing';
  td.innerHTML = `<input value="${esc(cur)}" onblur="commitLandingEdit(this,${rowIdx},${ci})" onkeydown="if(event.key==='Enter')this.blur();if(event.key==='Escape'){this.value='${esc(cur)}';this.blur()}">`;
  td.querySelector('input').focus();
}

function commitLandingEdit(input, rowIdx, ci) {
  S.tableData.rows[rowIdx][ci] = input.value;
  renderLandingTable();
}

function toggleLandingAll(checked) {
  const q = (v('l-search') || '').toLowerCase();
  landingCandidateRows().filter(r => {
    if (!q) return true;
    return Object.values(r).some(val => String(val || '').toLowerCase().includes(q));
  }).forEach(r => { if (checked) S.selected.add(r._idx); else S.selected.delete(r._idx); });
  renderLandingTable();
  renderTable();
}

async function buildLandingMdFromCompany(row) {
  if (!row) return;
  await buildMarketingMdForRows([row]);
}

async function buildLandingMdFromSelection() {
  const rows = landingRowsForSelection();
  if (!rows.length) { alert('Нет строк для MD'); return; }
  S.activeRow = rows[0];
  await buildMarketingMdForRows(rows);
}

async function buildMarketingMdForRows(rows) {
  if (!rows.length) return;
  const logWrap = document.getElementById('l-md-log-wrap');
  const logBox = document.getElementById('l-md-log');
  if (logWrap) logWrap.style.display = 'block';
  if (logBox) logBox.innerHTML = '';
  setText('l-md-count', `Готовлю MD: ${rows.length} компаний...`);

  const mdAgent = v('l-md-agent') || (v('l-agent') && v('l-agent') !== 'template' ? v('l-agent') : 'codex');
  const customPrompt = v('l-md-custom-prompt') || '';
  const data = await api('/api/landing/md', {method:'POST', json:{
    companies: rows.map(rowToPlain),
    agent_bin: mdAgent,
    agent_model: v('l-model') || '',
    custom_template_id: S.selectedHaTemplate || '',
    custom_prompt: customPrompt,
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  watchJob(data.job_id, 'l-md-log', job => {
    if (job.status === 'done') {
      const md = job.result?.md || '';
      document.getElementById('l-md').value = md;
      setText('l-md-count', `${job.result?.count || rows.length} компаний в MD · ${Math.round(md.length / 1024)}KB`);
      S.activeRow = rows[0];
      document.getElementById('l-company').value = String(rows[0]._idx);
      document.getElementById('l-gen-btn').disabled = false;
    } else if (job.status === 'error') {
      setText('l-md-count', 'Ошибка формирования MD');
    }
  });
}

async function transformSelectedToMd() {
  await buildLandingMdFromSelection();
  switchLandingTab('md');
}

async function startLandingFromMd() {
  const mdDossier = v('l-md') || '';
  if (!S.activeRow && S.selected.size) {
    const rows = landingRowsBySource('selected');
    if (rows.length) S.activeRow = rows[0];
  } else if (!S.activeRow && !mdDossier.trim()) {
    const rows = landingRowsForSelection();
    if (rows.length) S.activeRow = rows[0];
  }
  await startLanding();
}

function landingRowsBySource(source) {
  if (!S.tableData) return [];
  const rows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  if (source === 'selected') return rows.filter(r => S.selected.has(r._idx));
  if (source === 'all') return rows;
  return rows.filter(r => {
    const site = r['Сайт'] || '';
    return !site.startsWith('http') || r['Сегмент']?.startsWith('C') || !site;
  });
}

async function startLandingResearch() {
  if (!S.tableData) { alert('Загрузите таблицу'); return; }
  const source = v('lr-source') || 'selected';
  const rows = landingRowsBySource(source);
  if (!rows.length) { alert('Нет строк для сбора данных'); return; }

  clearLog('lr-log');
  setText('lr-status', `Сбор данных: ${rows.length} компаний...`);
  const plain = rows.map(rowToPlain);
  const data = await api('/api/enrich/web', {method:'POST', json:{
    companies: plain,
    concurrency: int('lr-conc', 3),
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.webEnrichJobId = data.job_id;
  watchJob(S.webEnrichJobId, 'lr-log', job => {
    if (job.status === 'done') {
      const results = job.result?.results || [];
      S.webEnrichResults = results;
      mergeWebResultsToTable(results);
      setText('lr-status', `Готово: ${results.length} компаний. Данные добавлены в таблицу.`);
      renderLandingResearchResults(results);
    } else if (job.status === 'error') {
      setText('lr-status', 'Ошибка сбора данных');
    }
  });
}

function renderLandingResearchResults(results) {
  const list = document.getElementById('lr-results-list');
  if (!list) return;
  list.innerHTML = results.map((r, idx) => {
    const reviews = r.web_reviews || [];
    const sources = r.research_sources || [];
    const name = r['Название'] || '—';
    const revCount = reviews.length;
    const srcCount = sources.length;
    const descLen = (r.web_description || '').length;
    const socialLen = (r.research_social_text || '').length;
    const summary = [
      descLen ? `📝 ${descLen} симв описание` : '',
      revCount ? `⭐ ${revCount} отзывов` : '',
      srcCount ? `🔗 ${srcCount} источников` : '',
      socialLen ? `💬 ${socialLen} симв соцсети` : '',
    ].filter(Boolean).join(' · ') || 'Данных не собрано';

    const revHtml = reviews.map(rv =>
      `<div style="font-size:.72rem;border-left:2px solid var(--accent);padding:4px 0 4px 8px;margin-bottom:5px">
        <div style="color:var(--a2);font-weight:600">${esc(rv.author||'Клиент')}${rv.date ? ' · '+esc(rv.date) : ''}${rv.rating ? ' · ★'+rv.rating : ''}</div>
        <div style="color:var(--text);margin-top:2px">${esc(rv.text||'')}</div>
      </div>`
    ).join('');

    const srcHtml = sources.map(s =>
      `<div style="font-size:.7rem;margin-bottom:4px;padding:5px 8px;background:var(--s3);border-radius:6px">
        <div style="font-weight:600;color:var(--a2)">${esc(s.source||s.url||'?')}</div>
        ${s.title ? `<div style="color:var(--muted)">${esc(s.title.slice(0,100))}</div>` : ''}
        ${s.text ? `<div style="color:var(--text);margin-top:3px;line-height:1.5">${esc(s.text.slice(0,500))}</div>` : ''}
      </div>`
    ).join('');

    const socialHtml = r.research_social_text
      ? `<pre style="font-size:.7rem;white-space:pre-wrap;color:var(--text);background:var(--s3);border-radius:6px;padding:8px;line-height:1.5;max-height:300px;overflow-y:auto">${esc(r.research_social_text)}</pre>`
      : '';

    return `
    <div style="background:var(--s2);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden">
      <div onclick="toggleResearchDetail(${idx})" style="padding:10px 12px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none">
        <div>
          <div style="font-size:.82rem;font-weight:700">${esc(name)}</div>
          <div style="font-size:.68rem;color:var(--muted);margin-top:2px">${summary}</div>
        </div>
        <span id="lr-arrow-${idx}" style="font-size:.8rem;color:var(--muted);transition:transform .2s">▶</span>
      </div>
      <div id="lr-detail-${idx}" style="display:none;padding:0 12px 12px">
        ${r.web_description ? `<div style="font-size:.8rem;margin-bottom:10px">
          <div style="font-size:.68rem;color:var(--muted);font-weight:600;margin-bottom:4px">ОПИСАНИЕ</div>
          <div style="line-height:1.6">${esc(r.web_description)}</div>
        </div>` : ''}
        ${revHtml ? `<div style="margin-bottom:10px">
          <div style="font-size:.68rem;color:var(--muted);font-weight:600;margin-bottom:6px">ОТЗЫВЫ (${revCount})</div>
          ${revHtml}
        </div>` : ''}
        ${socialHtml ? `<div style="margin-bottom:10px">
          <div style="font-size:.68rem;color:var(--muted);font-weight:600;margin-bottom:4px">СОЦСЕТИ</div>
          ${socialHtml}
        </div>` : ''}
        ${srcHtml ? `<div>
          <div style="font-size:.68rem;color:var(--muted);font-weight:600;margin-bottom:6px">ИСТОЧНИКИ (${srcCount})</div>
          ${srcHtml}
        </div>` : ''}
      </div>
    </div>`;
  }).join('');
}

function toggleResearchDetail(idx) {
  const detail = document.getElementById(`lr-detail-${idx}`);
  const arrow = document.getElementById(`lr-arrow-${idx}`);
  if (!detail) return;
  const open = detail.style.display === 'none';
  detail.style.display = open ? 'block' : 'none';
  if (arrow) arrow.style.transform = open ? 'rotate(90deg)' : '';
}

function mergeWebResultsToTable(results) {
  if (!S.tableData || !results?.length) return;
  const newCols = [
    'web_description', 'web_reviews', 'Отзывы текст', 'web_extra',
    'research_sources', 'research_images', 'research_social_text', 'research_md'
  ];
  newCols.forEach(col => {
    if (!S.tableData.columns.includes(col)) S.tableData.columns.push(col);
    if (S.visibleColumns) S.visibleColumns.add(col);
  });
  results.forEach(wr => {
    const name = wr['Название'] || '';
    S.tableData.rows.forEach(row => {
      const rowName = row[S.tableData.columns.indexOf('Название')] || '';
      if (rowName === name) {
        newCols.forEach(col => {
          const ci = S.tableData.columns.indexOf(col);
          let val = String(wr[col] || '');
          if (col === 'web_reviews') val = JSON.stringify(wr[col] || []);
          if (col === 'research_sources' || col === 'research_images') val = JSON.stringify(wr[col] || [], null, 0);
          if (col === 'Отзывы текст') {
            val = (wr.web_reviews || []).map(rv => {
              if (typeof rv === 'string') return rv;
              return `${rv.author || 'Клиент'}: ${rv.text || ''}`;
            }).filter(Boolean).join('\n');
          }
          while (row.length <= ci) row.push('');
          row[ci] = val;
        });
      }
    });
  });
  applyFilters();
  renderLandingTable();
}

function changePreviewDevice() {
  const w = v('l-device');
  const iframe = document.getElementById('l-iframe');
  iframe.style.width = w;
  setTimeout(resizeLandingIframe, 80);
}

function setLandingPreviewSrc(url) {
  const iframe = document.getElementById('l-iframe');
  iframe.onload = () => setTimeout(resizeLandingIframe, 80);
  iframe.src = url;
}

function resizeLandingIframe() {
  const iframe = document.getElementById('l-iframe');
  const wrap = document.getElementById('l-preview-wrap');
  if (!iframe || !wrap) return;
  try {
    const doc = iframe.contentDocument || iframe.contentWindow?.document;
    const body = doc?.body;
    const root = doc?.documentElement;
    const contentH = Math.max(
      body?.scrollHeight || 0,
      body?.offsetHeight || 0,
      root?.scrollHeight || 0,
      root?.offsetHeight || 0,
    );
    iframe.style.height = Math.max(wrap.clientHeight || 0, contentH || 0) + 'px';
  } catch {
    iframe.style.height = '100%';
  }
}

function downloadLanding() {
  if (S.landingJobId) window.open(`/api/landing/download/${S.landingJobId}`);
}
function openLandingTab() {
  if (S.landingJobId) window.open(`/api/landing/preview/${S.landingJobId}`);
}

function renderLandingSendLinks() {
  const list = document.getElementById('l-send-list');
  if (!list) return;
  if (!S.tableData) {
    list.innerHTML = '<div style="color:var(--muted);font-size:.85rem">Нет таблицы.</div>';
    return;
  }
  const urlCi = S.tableData.columns.indexOf('Лендинг HTML');
  const pathCi = S.tableData.columns.indexOf('Лендинг файл');
  const nameCi = S.tableData.columns.indexOf('Название');
  if (urlCi < 0) {
    list.innerHTML = '<div style="color:var(--muted);font-size:.85rem">HTML ещё не создан. Перейдите на шаг HTML и сгенерируйте страницы.</div>';
    return;
  }
  const rows = S.tableData.rows
    .map((row, idx) => ({idx, name: row[nameCi] || `Строка ${idx + 1}`, url: row[urlCi] || '', path: pathCi >= 0 ? row[pathCi] || '' : ''}))
    .filter(r => r.url);
  if (!rows.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:.85rem">В таблице пока нет HTML-ссылок.</div>';
    return;
  }
  list.innerHTML = rows.map(r => `
    <div style="display:flex;gap:10px;align-items:center;background:var(--s2);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:10px">
      <div style="flex:1;min-width:0">
        <div style="font-size:.85rem;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.name)}</div>
        <div style="font-size:.72rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.path || r.url)}</div>
      </div>
      <button class="btn btn-ghost" style="padding:5px 10px" onclick="window.open('${esc(r.url)}','_blank')">Открыть</button>
      <button class="btn btn-accent" style="padding:5px 10px" onclick="switchTab('send');buildSendQueue()">В отправку</button>
    </div>
  `).join('');
}

// Batch landing
function openBatchLandingModal() {
  if (!S.tableData) { alert('Загрузите таблицу'); return; }
  const allRows = S.tableData.rows.map((r, i) => toObj(r, S.tableData.columns, i));
  const selectedRows = allRows.filter(r => S.selected.has(r._idx));
  const noSite = (selectedRows.length ? selectedRows : allRows).filter(r => {
    const site = r['Сайт'] || '';
    return selectedRows.length || !site.startsWith('http') || r['Сегмент']?.startsWith('C') || !site;
  });
  document.getElementById('bl-count').textContent = noSite.length;
  document.getElementById('bl-result').style.display = 'none';
  document.getElementById('bl-log-wrap').style.display = 'none';
  clearLog('bl-log');
  updateBatchPoolBadge();
  showModal('batch-landing-modal');
  S._batchNoSite = noSite;
}

async function startBatchLanding() {
  const companies = (S._batchNoSite || []).map(rowToPlain);
  if (!companies.length) { alert('Нет компаний'); return; }
  document.getElementById('bl-log-wrap').style.display = 'block';
  clearLog('bl-log');

  const batchCustomTmpl = S.selectedHaTemplate || v('l-custom-tmpl') || '';
  const data = await api('/api/landing/batch', {method:'POST', json:{
    companies,
    style: S.styleMode === 'manual' ? (S.selectedStyle || 'auto') : 'auto',
    agent_bin: v('l-agent') || 'codex',
    agent_model: v('l-model') || '',
    custom_template_id: batchCustomTmpl,
    template_pool: S.batchPool.length ? S.batchPool : [],
    concurrency: int('bl-conc', 2),
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.batchJobId = data.job_id;
  watchJob(S.batchJobId, 'bl-log', job => {
    if (job.status === 'done') {
      const results = job.result?.results || [];
      document.getElementById('bl-result').style.display = 'block';
      document.getElementById('bl-result-list').innerHTML = results.map(r =>
        `<div style="margin-bottom:4px">${r.error ? '❌' : '✅'} ${esc(r.company||'?')}${r.error?' — ошибка':''}</div>`
      ).join('');
      attachBatchLandingsToTable(results);
      renderLandingSendLinks();
    }
  });
}

// Custom templates
function openAddTemplate() {
  document.getElementById('tmpl-name').value = '';
  document.getElementById('tmpl-body').value = '';
  showModal('add-template-modal');
}

async function saveTemplate() {
  const name = v('tmpl-name').trim();
  const body = v('tmpl-body').trim();
  if (!name || !body) { alert('Заполните название и тело шаблона'); return; }
  await api('/api/templates', {method:'POST', json:{name, body}});
  closeModal('add-template-modal');
  await loadStyles();
  alert('✅ Шаблон сохранён');
}

async function showTemplateHint() {
  const d = await api('/api/templates/hint');
  document.getElementById('hint-text').textContent = d.hint || '';
  showModal('hint-modal');
}

// ══════════════════════════════════════════
// SCREENSHOTS
// ══════════════════════════════════════════
function onScSrcChange() {
  document.getElementById('sc-manual').style.display = v('sc-src') === 'manual' ? 'block' : 'none';
}

function switchScreenTab(tab) {
  ['screenshots', 'analysis'].forEach(t => {
    document.getElementById(`sc-panel-${t}`).style.display = t === tab ? 'block' : 'none';
    document.getElementById(`sctab-${t}`).classList.toggle('active', t === tab);
  });
}

async function analyzeScreenSite(url, pageText, freshness, companyJson) {
  const company = companyJson ? JSON.parse(decodeURIComponent(companyJson)) : {};
  const resultsEl = document.getElementById('sc-analysis-results');
  const idleEl   = document.getElementById('sc-analysis-idle');
  if (idleEl) idleEl.style.display = 'none';

  const cardId = `sc-acard-${Date.now()}`;
  resultsEl.insertAdjacentHTML('afterbegin', `
    <div id="${cardId}" style="background:var(--s2);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:12px">
      <div style="font-size:.82rem;font-weight:700;margin-bottom:8px">${esc(url)}</div>
      <div class="spinner" style="width:16px;height:16px;margin-bottom:6px"></div>
      <div class="logbox" id="${cardId}-log" style="max-height:120px;margin-bottom:8px"></div>
      <div id="${cardId}-result"></div>
    </div>`);

  switchScreenTab('analysis');

  const data = await api('/api/screenshots/analyze_site', {method:'POST', json:{
    url,
    company,
    page_text: pageText || '',
    freshness: freshness || 0,
    agent_bin: 'codex',
    openai_api_key: v('sc-oai-analysis') || '',
    screenshots_job_id: S.screenJobId || '',
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  watchJob(data.job_id, `${cardId}-log`, job => {
    if (job.status === 'done') {
      const r = job.result || {};
      const card = document.getElementById(`${cardId}-result`);
      const mdHtml = (r.analysis || '').replace(/\n/g, '<br>').replace(/##\s(.+)/g, '<b style="color:var(--a2)">$1</b>');
      card.innerHTML = `
        <div style="font-size:.78rem;line-height:1.7;margin-bottom:12px">${mdHtml}</div>
        ${r.dalle_prompt ? `<div style="background:var(--s3);border-radius:8px;padding:10px;margin-bottom:10px">
          <div style="font-size:.65rem;color:var(--muted);font-weight:600;margin-bottom:4px">DALL-E ПРОМТ:</div>
          <div style="font-size:.72rem;color:var(--text)">${esc(r.dalle_prompt)}</div>
        </div>` : ''}
        ${r.concept_image ? `<img src="/api/screenshots/${S.screenJobId}/${r.concept_image}" style="width:100%;border-radius:8px;border:1px solid var(--border);margin-top:8px">` : ''}`;
      // Убираем спиннер
      const spinner = document.querySelector(`#${cardId} .spinner`);
      if (spinner) spinner.remove();
    }
  });
}

function toggleConceptOpts() {
  document.getElementById('sc-concept-opts').style.display =
    document.getElementById('sc-concept').checked ? 'block' : 'none';
}

function getScreenUrls() {
  const src = v('sc-src');
  if (src === 'manual') return v('sc-urls').split('\n').map(u => u.trim()).filter(u => u.startsWith('http'));
  if (!S.tableData) return [];
  let rows = src === 'selected' ? S.filtered.filter(r => S.selected.has(r._idx)) : S.filtered;
  if (src === 'old') rows = rows.filter(r => parseInt(r['Свежесть балл']||'100') < 50);
  if (src === 'all') rows = rows.filter(r => (r['Сайт']||'').startsWith('http'));
  return rows.map(r => r['Сайт']).filter(u => u && u.startsWith('http'));
}

async function startScreenshots() {
  const urls = getScreenUrls();
  if (!urls.length) { alert('Нет URL для скриншотов'); return; }
  show('sc-log-wrap'); clearLog('sc-log');
  document.getElementById('sc-results').innerHTML = '';
  hide('sc-idle');

  const data = await api('/api/screenshots/capture', {method:'POST', json:{
    urls,
    generate_concept: document.getElementById('sc-concept').checked,
    openai_api_key: v('sc-oai') || '',
    concept_prompt: v('sc-prompt') || '',
    agent_bin: 'codex',
  }}).catch(e => { alert(e.message); return null; });
  if (!data) return;

  S.screenJobId = data.job_id;
  watchJob(S.screenJobId, 'sc-log', job => {
    if (job.status === 'done') renderScreenResults(job.result || []);
  });
}

function renderScreenResults(results) {
  S._screenResults = results;
  document.getElementById('sc-results').innerHTML = results.map((r, idx) => {
    const screens = (r.screenshots || []).map(s => `
      <div class="sc-thumb" onclick="window.open('/api/screenshots/${S.screenJobId}/${s.file}','_blank')">
        <img src="/api/screenshots/${S.screenJobId}/${s.file}" loading="lazy" onerror="this.style.display='none'">
        <div class="sc-lbl">${s.type}</div>
      </div>`).join('');
    const concept = r.concept ? `
      <div style="margin-top:10px">
        <div style="font-size:.75rem;color:var(--a2);font-weight:700;margin-bottom:6px">✨ Концепт</div>
        <img src="/api/screenshots/${S.screenJobId}/${r.concept.file}"
          style="width:100%;border-radius:8px;border:1px solid var(--border)" loading="lazy">
      </div>` : '';
    const companyJson = encodeURIComponent(JSON.stringify(_findCompanyByUrl(r.url)));
    return `
      <div style="background:var(--s2);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <div>
            <a href="${r.url}" target="_blank" rel="noopener" style="font-size:.82rem;font-weight:700;color:var(--text);text-decoration:none;border-bottom:1px solid var(--border)">${esc(r.url)}</a>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
            <div style="font-size:.72rem;padding:2px 8px;border-radius:20px;border:1px solid;
                 color:${r.is_outdated?'var(--warn)':'var(--ok)'};border-color:${r.is_outdated?'rgba(245,158,11,.3)':'rgba(34,197,94,.3)'};
                 background:${r.is_outdated?'rgba(245,158,11,.08)':'rgba(34,197,94,.08)'}">
              ${r.is_outdated?'⚠️ Устарел':'✅ Актуален'} · ${r.freshness||0}/100
            </div>
            <button class="btn btn-ghost" style="padding:3px 10px;font-size:.72rem"
              onclick="analyzeScreenSite('${r.url}','${encodeURIComponent(r.page_text||'')}',${r.freshness||0},'${companyJson}')">
              🔍 Анализировать
            </button>
          </div>
        </div>
        <div class="sc-grid">${screens}</div>${concept}
      </div>`;
  }).join('');
}

function _findCompanyByUrl(url) {
  if (!S.tableData) return {};
  const ci = S.tableData.columns.indexOf('Сайт');
  if (ci < 0) return {};
  const row = S.tableData.rows.find(r => (r[ci] || '').includes(url.replace(/https?:\/\//, '').split('/')[0]));
  if (!row) return {};
  return toObj(row, S.tableData.columns, S.tableData.rows.indexOf(row));
}

// ══════════════════════════════════════════
// SEND
// ══════════════════════════════════════════
function buildSendQueue() {
  if (!S.tableData) { alert('Загрузите таблицу'); return; }
  const companies = S.filtered;

  S.sendQueue = companies.map(r => {
    // Реальные контакты из строки таблицы
    const email = r['Почта электронная'] || '';
    const telegram = r['Соц_Telegram'] || (r['Соцсети'] || '').match(/https?:\/\/t\.me\/[^\s;,)]+/)?.[0] || '';
    const whatsapp = r['Соц_WhatsApp'] || (r['Соцсети'] || '').match(/https?:\/\/wa\.me\/\d+/)?.[0] || '';
    const address = r['Адрес'] || '';

    // Авто-выбор лучшего канала (приоритет: email → telegram → whatsapp → визит)
    let bestChannel = 'visit';
    if (email) bestChannel = 'email';
    else if (telegram) bestChannel = 'telegram';
    else if (whatsapp) bestChannel = 'whatsapp';

    return {
      name: r['Название'] || '—',
      channel: bestChannel,
      channelValue: {email, telegram, whatsapp, visit: address}[bestChannel] || '',
      status: 'wait',
      address,
      row: r,
    };
  });

  renderSendQueue();
  document.getElementById('send-idle').style.display = 'none';
  document.getElementById('send-queue').style.display = 'block';
  document.getElementById('send-all-wrap').style.display = 'block';
  document.getElementById('send-stats').style.display = 'flex';
  refreshSendStats();
}

function renderSendQueue() {
  const chIcons = {email:'✉️', telegram:'✈️', whatsapp:'📱', visit:'🚶'};
  const chLabels = {email:'Email', telegram:'Telegram', whatsapp:'WhatsApp', visit:'Визит'};
  const statusLabel = {sent:'✅ Отправлено', visit:'🚶 Визит', wait:'⏳ Ожидает'};

  document.getElementById('send-list').innerHTML = S.sendQueue.map((item, i) => {
    // Для каждой компании показываем ТОЛЬКО её реальный контакт по выбранному каналу
    const contactMap = {
      email: item.row?.['Почта электронная'] || '',
      telegram: item.row?.['Соц_Telegram'] || item.row?.['Соцсети']?.match(/t\.me\/[^\s;,]+/)?.[0] || '',
      whatsapp: item.row?.['Соц_WhatsApp'] || item.row?.['Соцсети']?.match(/wa\.me\/\d+/)?.[0] || '',
      visit: item.row?.['Адрес'] || '',
    };
    const contact = contactMap[item.channel] || '—';
    return `
    <div class="send-row" id="sr-${i}">
      <div style="flex:1;min-width:0">
        <div style="font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(item.name)}</div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:2px">${chIcons[item.channel]} ${esc(contact.slice(0,60))}</div>
      </div>
      <select class="sel" style="padding:3px 7px;font-size:.7rem;flex-shrink:0" onchange="changeChannel(${i},this.value)">
        ${['email','telegram','whatsapp','visit'].map(c =>
          `<option value="${c}" ${item.channel===c?'selected':''}>${chIcons[c]} ${chLabels[c]}</option>`
        ).join('')}
      </select>
      <button class="btn btn-ghost" style="padding:3px 8px;font-size:.7rem;flex-shrink:0" onclick="previewMsg(${i})" title="Просмотр письма">✉️</button>
      <div class="send-status ss-${item.status}" id="ss-${i}">${statusLabel[item.status]||'⏳'}</div>
      <button class="btn btn-ok" style="padding:3px 8px;font-size:.7rem;flex-shrink:0" onclick="markSent(${i})">✓</button>
      <button class="btn btn-ghost" style="padding:3px 8px;font-size:.7rem;flex-shrink:0" onclick="markVisit(${i})">🚶</button>
    </div>`;
  }).join('');
  refreshSendStats();
}

function changeChannel(i, ch) {
  S.sendQueue[i].channel = ch;
  renderSendQueue();
}

function markSent(i) {
  S.sendQueue[i].status = 'sent';
  const el = document.getElementById(`ss-${i}`);
  if (el) { el.className = 'send-status ss-sent'; el.textContent = '✅ Отправлено'; }
}

function markVisit(i) {
  S.sendQueue[i].status = 'visit';
  const el = document.getElementById(`ss-${i}`);
  if (el) { el.className = 'send-status ss-visit'; el.textContent = '🚶 Визит'; }
}

function markAllVisit() {
  S.sendQueue.forEach((_, i) => markVisit(i));
}

function exportSendList() {
  const lines = ['Название,Канал,Адрес/Контакт,Статус'];
  S.sendQueue.forEach(item => {
    lines.push([item.name, item.channel, item.channelValue, item.status].map(s => `"${(s||'').replace(/"/g,'""')}"`).join(','));
  });
  const blob = new Blob(['﻿' + lines.join('\n')], {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'send_list.csv';
  a.click();
}

// ══════════════════════════════════════════
// BATCH MODAL (from table)
// ══════════════════════════════════════════
function openBatchModal() {
  document.getElementById('batch-count').textContent = S.selected.size || S.filtered.length;
  showModal('batch-modal');
}
function batchGoLanding() { closeModal('batch-modal'); switchTab('landing'); openBatchLandingModal(); }
function batchGoLegal() { closeModal('batch-modal'); switchTab('legal'); document.getElementById('leg-src').value = 'selected'; onLegalSrcChange(); }
function batchGoScreens() { closeModal('batch-modal'); switchTab('screens'); document.getElementById('sc-src').value = 'selected'; onScSrcChange(); }
function batchGoSend() { closeModal('batch-modal'); switchTab('send'); buildSendQueue(); }

function goLegal() { if (S.activeRow && (S.activeRow['Сайт']||'').startsWith('http')) { switchTab('legal'); document.getElementById('leg-src').value = 'manual'; onLegalSrcChange(); document.getElementById('leg-urls').value = S.activeRow['Сайт']; } else { alert('У этой компании нет подтверждённого сайта — аудит не проводится'); } }
function goScreenshot() { switchTab('screens'); document.getElementById('sc-src').value = 'manual'; onScSrcChange(); if (S.activeRow) document.getElementById('sc-urls').value = S.activeRow['Сайт']||''; }
function goSend() { switchTab('send'); if (S.activeRow) { const item = {name:S.activeRow['Название'],channel:'email',channelValue:S.activeRow['Почта электронная']||'',status:'wait',address:S.activeRow['Адрес']||'',row:S.activeRow}; S.sendQueue = [item]; renderSendQueue(); document.getElementById('send-idle').style.display='none'; document.getElementById('send-queue').style.display='block'; setText('send-count','1 компания'); } }

// ══════════════════════════════════════════
// CHAT
// ══════════════════════════════════════════
function chatKey(ev, tab) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); sendChat(tab); }
}

async function sendChat(tab) {
  const ta = document.getElementById(`chat-${tab}`);
  const msg = ta.value.trim();
  if (!msg) return;
  ta.value = '';
  ta.style.height = '';

  const ctx = {tab};
  if (S.activeRow) ctx.company = S.activeRow['Название'];
  if (S.currentFile) ctx.file = S.currentFile.split('/').pop();

  const d = await api(`/api/chat/${tab}`, {method:'POST', json:{tab, message:msg, context:ctx}}).catch(() => null);
  if (!d) return;

  const out = document.getElementById(`chat-out-${tab}`);
  out.style.display = 'block';
  out.textContent = d.response || '';
}

function autoResize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(100, ta.scrollHeight) + 'px';
}

// ══════════════════════════════════════════
// JOB WATCHER
// ══════════════════════════════════════════
function watchJob(jobId, logElId, onDone) {
  const logEl = document.getElementById(logElId);
  if (!logEl) return;
  const ws = new WebSocket(`ws://${location.host}/ws/job/${jobId}`);
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'log') appendLog(logEl, msg.msg);
    else if (msg.type === 'status') { ws.close(); onDone(msg); }
  };
  ws.onerror = () => pollJob(jobId, logElId, onDone, 0);
}

async function pollJob(jobId, logElId, onDone, sent) {
  const logEl = document.getElementById(logElId);
  try {
    const job = await api(`/api/job/${jobId}`);
    const newLogs = (job.log || []).slice(sent);
    if (logEl) newLogs.forEach(m => appendLog(logEl, m));
    if (job.status === 'pending' || job.status === 'running') {
      setTimeout(() => pollJob(jobId, logElId, onDone, (job.log||[]).length), 600);
    } else { onDone(job); }
  } catch { setTimeout(() => pollJob(jobId, logElId, onDone, sent), 1000); }
}

function appendLog(el, msg) {
  if (!el) return;
  const d = document.createElement('div');
  d.className = 'll' + (msg.includes('❌') || msg.includes('ERROR') ? ' e' : msg.includes('✅') ? ' s' : '');
  d.textContent = msg;
  el.appendChild(d);
  el.scrollTop = el.scrollHeight;
}

// ══════════════════════════════════════════
// MODALS
// ══════════════════════════════════════════
function showModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }

// ══════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════
async function api(url, opts = {}) {
  const options = {method: opts.method || 'GET', ...opts};
  if (opts.json) {
    options.headers = {'Content-Type': 'application/json', ...(opts.headers || {})};
    options.body = JSON.stringify(opts.json);
    delete options.json;
  }
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const v = id => (document.getElementById(id) || {}).value || '';
const int = (id, def) => parseInt(v(id)) || def;
const show = (...ids) => ids.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = 'block'; });
const hide = (...ids) => ids.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = 'none'; });
const setText = (id, t) => { const el = document.getElementById(id); if(el) el.textContent = t; };
const clearLog = id => { const el = document.getElementById(id); if(el) el.innerHTML = ''; };

function rowToPlain(row) {
  const o = {...row};
  delete o._idx;
  return o;
}

// ══════════════════════════════════════════
// HA TEMPLATES GALLERY
// ══════════════════════════════════════════
let selHaId = '';
let filterCat = '';
let hoverTimer = null;
let hoverCache = {};

async function loadHaTemplates() {
  const d = await api('/api/ha/templates').catch(() => ({templates:[]}));
  S.haTemplates = d.templates || [];
  buildCatFilters();
  filterTemplates();
  populateLandingTemplateSelect();
}

function buildCatFilters() {
  const cats = [...new Set(S.haTemplates.map(t => t.category).filter(Boolean))];
  const el = document.getElementById('cat-filters');
  if (!el) return;
  el.innerHTML = cats.map(c =>
    `<div class="cat-chip" id="catc-${c}" onclick="setCatFilter('${c}')">${c}</div>`
  ).join('');
}

function setCatFilter(cat) {
  filterCat = filterCat === cat ? '' : cat;
  document.querySelectorAll('.cat-chip').forEach(el => {
    const c = el.id.replace('catc-','');
    el.classList.toggle('on', c === filterCat);
  });
  filterTemplates();
}

function filterTemplates() {
  const q = (document.getElementById('tmpl-search')?.value || '').toLowerCase();
  const gallery = document.getElementById('ha-gallery');
  if (!gallery) return;
  const filtered = S.haTemplates.filter(t => {
    if (filterCat && t.category !== filterCat) return false;
    if (q && !t.name.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) return false;
    return true;
  });
  gallery.innerHTML = filtered.map(t => {
    const inPool = S.batchPool.includes(t.id);
    return `
    <div class="ha-tmpl-row ${selHaId===t.id?'sel':''}" id="htrow-${t.id}"
      onmouseenter="startHover(event,'${t.id}')" onmouseleave="endHover()"
      onclick="pickHaTemplate('${t.id}')">
      <span class="emoji">${t.emoji}</span>
      <div class="info">
        <div class="t-name">${esc(t.name)}</div>
        <div class="t-cat">${esc(t.category)}${t.aspect_hint?' · '+t.aspect_hint:''}</div>
      </div>
      <div style="display:flex;gap:4px;flex-shrink:0">
        <button class="btn ${inPool?'btn-accent':'btn-ghost'} pool-btn" id="pool-btn-${t.id}"
          style="padding:3px 7px;font-size:.68rem"
          onclick="event.stopPropagation();toggleBatchPool('${t.id}')"
          title="Добавить в пул пакетной генерации">${inPool?'✓ В пуле':'+ В пул'}</button>
        <button class="btn btn-accent use-btn" onclick="event.stopPropagation();pickHaTemplate('${t.id}');switchLandingTab('html')">Выбрать</button>
      </div>
    </div>`;
  }).join('');
}

function toggleBatchPool(id) {
  const idx = S.batchPool.indexOf(id);
  if (idx >= 0) {
    S.batchPool.splice(idx, 1);
  } else {
    S.batchPool.push(id);
  }
  const btn = document.getElementById(`pool-btn-${id}`);
  if (btn) {
    const inPool = S.batchPool.includes(id);
    btn.textContent = inPool ? '✓ В пуле' : '+ В пул';
    btn.className = `btn ${inPool ? 'btn-accent' : 'btn-ghost'} pool-btn`;
    btn.style.cssText = 'padding:3px 7px;font-size:.68rem';
  }
  updateBatchPoolBadge();
}

function updateBatchPoolBadge() {
  const badge = document.getElementById('batch-pool-badge');
  if (badge) {
    badge.textContent = S.batchPool.length
      ? `🎨 В пуле: ${S.batchPool.length} шаблонов`
      : '🎨 Пул пуст — используется выбранный шаблон';
    badge.style.color = S.batchPool.length ? 'var(--ok)' : 'var(--muted)';
  }
}

function clearBatchPool() {
  S.batchPool = [];
  filterTemplates();
  updateBatchPoolBadge();
}

function pickHaTemplate(id) {
  selHaId = id;
  const tmpl = S.haTemplates.find(t => t.id === id);
  document.querySelectorAll('.ha-tmpl-row').forEach(r => {
    r.classList.toggle('sel', r.id === `htrow-${id}`);
  });
  const nameEl = document.getElementById('l-selected-tmpl-name');
  if (nameEl) {
    nameEl.textContent = tmpl ? `${tmpl.emoji} ${tmpl.name}` : 'не выбран';
  }
  S.selectedHaTemplate = id;
  populateLandingTemplateSelect();
}

function startHover(ev, id) {
  clearTimeout(hoverTimer);
  hoverTimer = setTimeout(() => showHoverPreview(ev, id), 250);
}

function endHover() {
  clearTimeout(hoverTimer);
  const preview = document.getElementById('tmpl-hover-preview');
  if (preview) preview.style.display = 'none';
}

async function showHoverPreview(ev, id) {
  const preview = document.getElementById('tmpl-hover-preview');
  const iframe = document.getElementById('tmpl-hover-iframe');
  const label = document.getElementById('tmpl-hover-label');
  if (!preview || !iframe) return;

  const tmpl = S.haTemplates.find(t => t.id === id);
  if (label && tmpl) label.innerHTML = `<span>${tmpl.emoji}</span> <span>${tmpl.name}</span>`;

  // Позиционируем превью
  const rect = ev.currentTarget?.getBoundingClientRect() || {right: ev.clientX, top: ev.clientY};
  let left = rect.right + 12;
  if (left + 420 > window.innerWidth) left = rect.left - 432;
  let top = Math.min(rect.top, window.innerHeight - 320);
  preview.style.left = left + 'px';
  preview.style.top = top + 'px';
  preview.style.display = 'block';

  // Загружаем HTML
  if (!hoverCache[id]) {
    iframe.src = `/api/ha/templates/${id}/preview`;
    hoverCache[id] = true;
  } else {
    iframe.src = `/api/ha/templates/${id}/preview?t=${Date.now()}`;
  }
}

// ══════════════════════════════════════════
// LANDING REFINEMENT (редактирование с AI)
// ══════════════════════════════════════════
function refineKey(ev) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); refineLanding(); }
}

async function refineLanding() {
  if (!S.landingJobId) { alert('Сначала сгенерируйте лендинг'); return; }
  const instr = document.getElementById('l-refine-input')?.value?.trim();
  if (!instr) return;
  document.getElementById('l-refine-logbox').innerHTML = '';
  document.getElementById('l-refine-log').style.display = 'block';
  document.getElementById('l-refine-btn').disabled = true;
  document.getElementById('l-refine-input').value = '';

  const data = await api('/api/landing/refine', {method:'POST', json:{
    job_id: S.landingJobId,
    instruction: instr,
    agent_bin: v('l-agent') || 'codex',
    agent_model: v('l-model') || '',
  }}).catch(e => { alert(e.message); return null; });
  if (!data) { document.getElementById('l-refine-btn').disabled = false; return; }

  watchJob(data.job_id, 'l-refine-logbox', job => {
    document.getElementById('l-refine-btn').disabled = false;
    if (job.status === 'done' && job.result?.updated) {
      // Перезагружаем iframe
      setLandingPreviewSrc(`/api/landing/preview/${S.landingJobId}?t=${Date.now()}`);
    }
  });
}

async function saveLandingResult() {
  if (!S.landingJobId || !S.activeRow) return;
  attachLandingToTable(S.activeRow._idx, `/api/landing/preview/${S.landingJobId}`, '');
  alert('✅ Лендинг привязан к компании в таблице');
}

function showPublishGuide() {
  showModal('publish-modal');
}

// ══════════════════════════════════════════
// SEND TAB — ПЕРСОНАЛИЗАЦИЯ
// ══════════════════════════════════════════
function updateLegalUrls() {
  // Обновляем список URL для аудита при переключении на вкладку
  // (ничего не делаем — функция getLegalUrls() читает актуальный S.tableData)
}

function refreshSendStats() {
  const el = document.getElementById('send-stats');
  if (!el || !S.sendQueue.length) return;
  el.style.display = 'flex';
  setText('ss-total', S.sendQueue.length);
  setText('ss-sent', S.sendQueue.filter(i => i.status==='sent').length);
  setText('ss-visit', S.sendQueue.filter(i => i.status==='visit').length);
  setText('ss-wait', S.sendQueue.filter(i => i.status==='wait').length);
}

function applyGlobalChannel() {
  const ch = v('send-channel-global');
  if (!ch) return;
  S.sendQueue.forEach((item, i) => {
    item.channel = ch;
    // Обновляем channelValue
    const chMap = {
      email: item.row?.['Почта электронная'] || '',
      telegram: item.row?.['Соц_Telegram'] || '',
      whatsapp: item.row?.['Соц_WhatsApp'] || '',
      visit: item.row?.['Адрес'] || '',
    };
    item.channelValue = chMap[ch] || '';
  });
  renderSendQueue();
  document.getElementById('send-channel-global').value = '';
}

// Генерация персонального текста письма
function buildPersonalMsg(item) {
  const tmpl = document.getElementById('send-msg-tmpl')?.value ||
    'Здравствуйте!\n\nМы подготовили материалы для {name}.\n\nС уважением';
  return tmpl.replace(/{name}/g, item.name).replace(/{address}/g, item.address || '');
}

function openSendAllModal() {
  const preview = document.getElementById('send-all-preview');
  if (!preview) return;
  const waiting = S.sendQueue.filter(i => i.status === 'wait');
  preview.innerHTML = waiting.slice(0, 5).map(item => `
    <div style="background:var(--s2);border-radius:8px;padding:10px 12px;margin-bottom:8px">
      <div style="font-size:.8rem;font-weight:600;margin-bottom:5px">${esc(item.name)}</div>
      <div style="font-size:.72rem;color:var(--muted);margin-bottom:5px">Канал: ${item.channel} · ${esc((item.channelValue||'').slice(0,50))}</div>
      <pre style="font-size:.7rem;color:var(--muted);white-space:pre-wrap;margin:0">${esc(buildPersonalMsg(item).slice(0,150))}...</pre>
    </div>`).join('') +
    (waiting.length > 5 ? `<div style="font-size:.75rem;color:var(--muted);text-align:center;padding:8px">...и ещё ${waiting.length-5}</div>` : '');
  showModal('send-all-modal');
}

function confirmSendAll() {
  closeModal('send-all-modal');
  S.sendQueue.filter(i => i.status==='wait').forEach((_, i) => {
    const qi = S.sendQueue.indexOf(_);
    markSent(qi);
  });
  renderSendQueue();
  refreshSendStats();
  alert(`✅ Отмечено как отправлено: ${S.sendQueue.filter(i => i.status==='sent').length}`);
}

function previewMsg(i) {
  const item = S.sendQueue[i];
  document.getElementById('msg-modal-title').textContent = `Письмо: ${item.name}`;
  document.getElementById('msg-modal-body').textContent = buildPersonalMsg(item);
  S._copyMsg = buildPersonalMsg(item);
  showModal('msg-preview-modal');
}

function copyMsgToClipboard() {
  navigator.clipboard.writeText(S._copyMsg || '').then(() => alert('Скопировано!')).catch(() => {});
}
