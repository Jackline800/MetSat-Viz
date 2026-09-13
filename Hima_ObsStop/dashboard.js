// Source-specific time semantics are shared by the timeline and table views.
let currentSat = 'H9', currentYearFilter = 'ALL', currentMode = 'JMA';
let currentCategory = 'all', currentView = 'timeline', searchQuery = '';
const CATEGORIES = {
    pause: {label: '觀測休止', color: '#4666c7', unit: '次', note: '例行控制、校正與維護'},
    quality: {label: '品質與配發異常', color: '#b56816', unit: '則紀錄', note: '缺漏、雜訊、延遲及其他異常'},
    change: {label: '處理方式變更', color: '#188078', unit: '次', note: '校正資訊、標頭與處理更新'},
    notice: {label: '營運與預期影響公告', color: '#7956a8', unit: '則', note: '任務交接與尚未確認的預期影響'}
};
const EVENT_TYPES = ['東西軌道控制', '南北軌道控制', '輻射計太陽校正', '衛星例行維護', '衛星檢修作業', '其他'];
let activeFilters = [...EVENT_TYPES], visibleMonths = new Map();
const el = id => document.getElementById(id);
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
}
function safeLink(url, label) {
    try {
        const u = new URL(url);
        if (!['https:', 'http:'].includes(u.protocol)) return escapeHtml(label);
        return `<a href="${escapeHtml(u.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ↗</a>`;
    } catch { return escapeHtml(label); }
}
function allData() { return typeof ALL_SAT_DATA === 'undefined' ? [] : ALL_SAT_DATA; }
function categoryOf(r) { return r.record_type === 'notice' || r.status === 'anticipated' ? 'notice' : r.category || 'pause'; }
function numberOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
}
function getEventCount(r) { return ['notice', 'change'].includes(categoryOf(r)) ? 0 : numberOrNull(r.event_count) ?? 0; }
function getObservationCount(r) { return numberOrNull(r.observation_count); }
function getBaseData() {
    return allData().filter(r => r.satellite === currentSat && (currentYearFilter === 'ALL' || r.ad_year === Number(currentYearFilter)));
}
function pauseReason(r) { return EVENT_TYPES.includes(r.event_tw) ? r.event_tw : '其他'; }
function getFilteredData() {
    const query = searchQuery.trim().toLocaleLowerCase();
    return getBaseData().filter(r =>
        (currentCategory === 'all' || categoryOf(r) === currentCategory) &&
        (categoryOf(r) !== 'pause' || activeFilters.includes(pauseReason(r))) &&
        (!query || [r.title_tw, r.event_tw, r.event_jp, r.memo_tw, r.date_raw, r.time_raw, r.start_utc, r.end_utc,
            ...(r.services || []), ...(r.bands || []).map(b => `第${b}頻道`)].join(' ').toLocaleLowerCase().includes(query)));
}
function summarizeRecords(rows) {
    const totals = {pause: 0, quality: 0, change: 0, notice: 0};
    for (const r of rows) {
        const c = categoryOf(r);
        totals[c] += c === 'change' ? numberOrNull(r.change_count) ?? 1 : c === 'notice' ? 1 : getEventCount(r);
    }
    return totals;
}
function shiftedISO(iso, r, mode) {
    if (!iso) return '';
    const date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return '';
    if (mode === 'TW' && r.time_role === 'observation' && !['hour', 'approximate'].includes(r.time_precision)) date.setUTCMinutes(date.getUTCMinutes() - 10);
    return date.toISOString();
}
function formatInstant(iso, r, mode, code = '') {
    const value = shiftedISO(iso, r, mode);
    if (!value) return '時間未明';
    const precision = r.time_precision;
    const text = value.slice(0, 10) + ' ' + value.slice(11, precision === 'second' ? 19 : precision === 'hour' ? 13 : 16) + (precision === 'hour' ? ' 時' : '');
    return `${precision === 'approximate' ? '約 ' : ''}<time datetime="${escapeHtml(value)}">${text} UTC</time>${code ? ` <span class="small">(${escapeHtml(code)})</span>` : ''}`;
}
function formatInterval(period, r, mode) {
    const startCode = period.start_p_code || r.start_p_code || r.p_code || '';
    const start = formatInstant(period.start_utc, r, mode, startCode);
    return period.end_utc && period.end_utc !== period.start_utc
        ? `${start}<br><span aria-label="至">～ </span>${formatInstant(period.end_utc, r, mode, period.end_p_code || r.end_p_code || '')}` : start;
}
function getDisplayDates(r, mode) {
    if (r.time_type === 'recurring_range' && r.occurrence_dates_iso?.length) {
        return r.occurrence_dates_iso.map(d => shiftedISO(`${d}T${r.start_utc.slice(11)}`, r, mode).slice(0, 10));
    }
    if ((r.affected_dates_iso || []).length && r.time_type === 'point') {
        const clock = (r.start_utc || '').slice(11);
        return r.affected_dates_iso.map(d => shiftedISO(`${d}T${clock}`, r, mode).slice(0, 10));
    }
    const start = shiftedISO(r.start_utc, r, mode), end = shiftedISO(r.end_utc, r, mode);
    return [...new Set([start.slice(0, 10), end.slice(0, 10)].filter(Boolean))];
}
function renderRecordTime(r, mode = currentMode) {
    if (!r.start_utc) return escapeHtml(r.time_raw || '來源未列明');
    if (r.time_type === 'recurring_range') {
        const dates = getDisplayDates(r, mode);
        return `${escapeHtml(dates.join('、'))}<br><span class="small">所列日期反覆休止；首日範例：</span><br>${formatInterval(r, r, mode)}`;
    }
    if (r.time_type === 'open_range') return `${formatInterval(r, r, mode)}<br><span class="small">來源未列結束時間</span>`;
    if (r.time_type === 'point' && (r.affected_dates_iso || []).length > 1) {
        const dates = getDisplayDates(r, mode), clock = shiftedISO(r.start_utc, r, mode).slice(11, 16);
        return `${dates[0]} ～ ${dates.at(-1)}<br>所列日期 ${clock} UTC ${r.p_code ? `(${escapeHtml(r.p_code)})` : ''}<br><span class="small">依日期反覆休止，非連續中斷</span>`;
    }
    const periods = r.intervals?.length ? r.intervals : [r];
    return periods.map(p => formatInterval(p, r, mode)).join('<br><span class="small">另一次時次：</span><br>');
}
function timeRole(r) {
    return {effective: '生效時間', announcement: r.status === 'anticipated' ? '預期影響時間' : '公告所列時間',
        distribution: '日誌所列事件／配發時間', event: '日誌所列事件時間', observation: '觀測休止履歷時次'}[r.time_role] || '來源時間';
}
function badges(r) {
    let result = `<span class="badge ${categoryOf(r)}">${CATEGORIES[categoryOf(r)].label}</span>`;
    const labels = [];
    if (r.status === 'anticipated') labels.push('預期影響');
    if (r.temporal_pattern === 'intermittent') labels.push('間歇性');
    else if (r.temporal_pattern === 'onset') labels.push('僅列起始時間');
    else if (r.time_type === 'continuous') labels.push('連續時段');
    else if (r.time_type === 'multiple') labels.push('分離時次');
    if (r.time_precision === 'approximate') labels.push('約略時間');
    if (r.uncertainty) labels.push('原文含可能性／調查中');
    if ((r.sources || []).length > 1) labels.push(`已整合 ${r.sources.length} 份來源`);
    return result + labels.map(t => `<span class="badge status">${escapeHtml(t)}</span>`).join('');
}
function scopeText(r) {
    const parts = [];
    if (r.bands?.length) parts.push('頻道 ' + r.bands.join('、'));
    if (r.regions?.length) parts.push(r.regions.join('、'));
    if (r.services?.length) parts.push(r.services.join('、'));
    if (r.products?.length) parts.push(...r.products.filter(p => !(r.services || []).includes(p)));
    return parts.join(' · ');
}
function countLabel(r) {
    const c = categoryOf(r);
    if (c === 'notice') return '公告 1 則';
    if (c === 'change') return '變更 1 次';
    if (c === 'quality') return `異常紀錄 ${getEventCount(r)} 則`;
    return `休止 ${getEventCount(r)} 次`;
}
function renderDetails(r) {
    const c = categoryOf(r);
    let html = `<div class="event-details"><p class="prose">${escapeHtml(r.event_tw || r.event_jp)}</p>`;
    if (['source_retained', 'partial'].includes(r.translation_status)) html += '<p class="notice-box">部分或全部描述尚無對應繁中翻譯，保留來源原文。</p>';
    if (r.memo_tw || r.memo) html += `<p class="prose"><strong>原因／備註：</strong>${escapeHtml(r.memo_tw || r.memo)}</p>`;
    const scope = scopeText(r);
    if (scope) html += `<p class="scope"><strong>影響範圍：</strong>${escapeHtml(scope)}</p>`;
    html += `<p class="small">${escapeHtml(countLabel(r))} · ${timeRole(r)}。${currentMode === 'TW' && r.time_role !== 'observation' ? '此類時間保留來源 UTC，不減 10 分鐘。' : ''}</p>`;
    if (c === 'quality' && numberOrNull(r.covered_slot_count) > 1) html += `<p class="notice-box">休止履歷所列時段涵蓋 <strong>${r.covered_slot_count} 個 10 分鐘時次</strong>（含首末時次）；實際欠配數及各頻道受影響筆數未確定。</p>`;
    if (c === 'pause') html += `<p class="small">休止觀測時次：${getObservationCount(r) === null ? '來源未確定' : getObservationCount(r) + ' 個'}。${r.fd || r.reg ? `來源標記：F.D. ${escapeHtml(r.fd || '—')} / Reg ${escapeHtml(r.reg || '—')}。` : ''}</p>`;
    if (r.temporal_pattern === 'intermittent') html += '<p class="notice-box">上列是間歇性異常的涵蓋期間，不代表期間內每個時次都受影響。</p>';
    if ((r.excluded_dates || []).length) html += `<p class="small">排除日期（日）：${escapeHtml(r.excluded_dates.join('、'))}</p>`;
    if ((r.affected_dates_iso || []).length > 1 && r.time_type === 'point') html += `<details><summary class="small">實際休止日期</summary><p class="small">${escapeHtml(getDisplayDates(r, currentMode).join('、'))}</p></details>`;
    if (r.service_intervals?.length) {
        html += '<h3>各服務記載時段（UTC）</h3><div class="table-scroll"><table><thead><tr><th>服務</th><th>來源時間</th><th>依據</th></tr></thead><tbody>';
        for (const s of r.service_intervals) html += `<tr><td>${escapeHtml(s.service)}</td><td>${formatInterval(s, {time_role: 'distribution', time_precision: r.time_precision}, 'JMA')}</td><td>${s.basis === 'explicit' ? '內文明列' : '沿用事件標題；未另列服務起迄'}</td></tr>`;
        html += '</tbody></table></div>';
    }
    if (r.merge_basis) html += `<p class="small">整合依據：${escapeHtml(r.merge_basis)}</p>`;
    if (r.revised_dates_jp?.length) html += `<h3>修訂前日期（不另計事件）</h3><p class="small">${escapeHtml(r.revised_dates_jp.join('；'))}</p>`;
    html += '<h3>來源與原文</h3>';
    for (const s of r.sources || []) {
        const name = s.kind === 'pause_history' ? '觀測休止履歷' : s.section === 'change' ? '事件日誌 · 處理方式變更' : '事件日誌 · 品質低下履歷';
        html += `<div class="source">${safeLink(s.url, name)}<p class="small prose">原始日期／時間：${escapeHtml([s.date_raw, s.time_raw].filter(Boolean).join(' · '))}</p>`;
        if (currentMode === 'TW' && s.time_role === 'observation' && s.start_utc) html += `<p class="small">觀測時次對齊：${renderRecordTime({...r, ...s, intervals: null}, 'TW')}</p>`;
        html += `<details><summary class="small">查看日文原文</summary><p class="prose" lang="ja">${escapeHtml(s.description_jp)}</p></details></div>`;
    }
    if (r.attachments?.length) html += `<h3>相關文件</h3><ul class="links">${r.attachments.map(a => `<li>${safeLink(a.url, a.title_tw || a.title_jp || '來源附件')}</li>`).join('')}</ul>`;
    const related = (r.related_events || []).map(link => allData().find(item => item.id === link.id)).filter(Boolean);
    if (related.length) {
        html += '<h3>同時段的其他記載</h3><p class="small">尚未確認為同一事件，保留分列。</p>';
        for (const item of related) html += `<button class="related" data-event="${escapeHtml(item.id)}" onclick="showRelated(this.dataset.event)">${escapeHtml((item.start_utc || '').slice(0, 10) + ' · ' + item.title_tw)}</button>`;
    }
    return html + '</div>';
}
function renderCard(r) {
    return `<details class="event-card" id="record-${escapeHtml(r.id)}"><summary class="event-summary"><div class="event-time">${renderRecordTime(r)}<div class="small">${timeRole(r)}</div></div><div>${badges(r)}<div class="event-title">${escapeHtml(r.title_tw || r.event_tw)}</div>${scopeText(r) ? `<div class="small">${escapeHtml(scopeText(r))}</div>` : ''}</div><span class="detail-toggle"></span></summary>${renderDetails(r)}</details>`;
}
function renderTable(rows) {
    return `<div class="table-scroll"><table class="compact"><thead><tr><th>來源日期／時間（UTC）</th><th>分類與事件（點擊展開詳情）</th><th>計數</th></tr></thead><tbody>${rows.map(r => `<tr><td class="event-time">${renderRecordTime(r)}<div>${timeRole(r)}</div></td><td><details id="record-${escapeHtml(r.id)}"><summary>${badges(r)}<div class="event-title">${escapeHtml(r.title_tw || r.event_tw)}</div></summary>${renderDetails(r)}</details></td><td>${countLabel(r)}</td></tr>`).join('')}</tbody></table></div>`;
}
function monthContent(rows) { return currentView === 'table' ? renderTable(rows) : rows.map(renderCard).join(''); }
function renderMonth(node) {
    if (node.open) {
        const body = el(`body-${node.dataset.month}`);
        if (!body.innerHTML) body.innerHTML = monthContent(visibleMonths.get(node.dataset.month) || []);
    }
}
function renderAccordionTable() {
    visibleMonths = new Map();
    const filtered = getFilteredData();
    for (const r of filtered) {
        const key = `${r.ad_year}-${String(r.month).padStart(2, '0')}`;
        if (!visibleMonths.has(key)) visibleMonths.set(key, []);
        visibleMonths.get(key).push(r);
    }
    const entries = [...visibleMonths.entries()].sort((a, b) => b[0].localeCompare(a[0]));
    el('records-accordion-container').innerHTML = entries.length ? entries.map(([key, rows], i) => {
        const year = Number(key.slice(0, 4));
        return `<details class="panel month" id="month-${key}" data-month="${key}" ontoggle="renderMonth(this)" ${i === 0 ? 'open' : ''}><summary>${key} <span class="small">民國 ${year - 1911} 年 · ${rows.length} 筆來源整合紀錄</span></summary><div class="month-body" id="body-${key}">${i === 0 ? monthContent(rows) : ''}</div></details>`;
    }).join('') : '<div class="panel empty">目前條件沒有紀錄。可調整年度、分類、原因或搜尋文字。</div>';
    el('table-title').textContent = `${currentCategory === 'all' ? '全部事件' : CATEGORIES[currentCategory].label} · ${filtered.length} 筆紀錄`;
}
function renderSummary() {
    const totals = summarizeRecords(getBaseData());
    el('summary-title').textContent = `向日葵${currentSat.slice(1)}號 · ${currentYearFilter === 'ALL' ? '歷年' : currentYearFilter + ' 年（民國 ' + (Number(currentYearFilter) - 1911) + ' 年）'}`;
    el('summary-cards').innerHTML = Object.entries(CATEGORIES).map(([key, c]) => `<div class="panel stat" style="--category-color:${c.color}"><h3>${c.label}</h3><strong>${totals[key].toLocaleString()}</strong><span class="unit">${c.unit}</span><p>${c.note}</p></div>`).join('');
}
function trendSeries() {
    const rows = getFilteredData();
    const keys = currentYearFilter === 'ALL' ? [...new Set(getBaseData().map(r => r.ad_year))].sort((a, b) => a - b) : Array.from({length: 12}, (_, i) => i + 1);
    return Object.entries(CATEGORIES).filter(([key]) => currentCategory === 'all' || currentCategory === key).map(([key, c]) => ({...c, key,
        labels: keys.map(n => String(n) + (currentYearFilter === 'ALL' ? '' : '月')),
        values: keys.map(n => summarizeRecords(rows.filter(r => (currentYearFilter === 'ALL' ? r.ad_year : r.month) === n))[key])}));
}
function updateTrendChart() {
    // Independent scales keep rare quality/change reports visible beside daily maintenance.
    el('trend-chart').innerHTML = trendSeries().map(s => {
        const width = Math.max(480, s.values.length * 58 + 30);
        const max = Math.max(1, ...s.values), step = (width - 30) / Math.max(1, s.values.length), bar = Math.min(35, step * .55);
        return `<div class="chart-row"><div><h3 style="color:${s.color}">${s.label}</h3><span class="small">單位：${s.unit}</span></div><svg style="min-width:${width}px" viewBox="0 0 ${width} 112" role="img" aria-label="${escapeHtml(s.label + '：' + s.labels.map((v, i) => v + ' ' + s.values[i] + s.unit).join('、'))}"><line x1="5" x2="${width - 5}" y1="80" y2="80" stroke="#dce3ec"/>${s.values.map((value, i) => {
            const x = 15 + step * i + step / 2, height = value / max * 51;
            return `<g><title>${s.labels[i]}：${value} ${s.unit}</title><rect x="${x - bar / 2}" y="${80 - height}" width="${bar}" height="${height}" rx="2" fill="${s.color}"/><text x="${x}" y="${74 - height}" text-anchor="middle" font-size="11" fill="#506078">${value}</text><text x="${x}" y="102" text-anchor="middle" font-size="11" fill="#68768c">${s.labels[i]}</text></g>`;
        }).join('')}</svg></div>`;
    }).join('');
}
function renderFilterChips() {
    el('pause-filters').hidden = !['all', 'pause'].includes(currentCategory);
    el('filter-chips').innerHTML = EVENT_TYPES.map((type, i) => `<button aria-pressed="${activeFilters.includes(type)}" onclick="toggleFilter(${i})">${type}</button>`).join('');
}
function toggleFilter(index) {
    const type = EVENT_TYPES[index];
    activeFilters = activeFilters.includes(type) ? activeFilters.filter(t => t !== type) : [...activeFilters, type];
    refreshUI();
}
function refreshUI() {
    renderFilterChips(); renderSummary(); renderAccordionTable(); updateTrendChart();
    el('category-tabs').innerHTML = [['all', {label: '全部'}], ...Object.entries(CATEGORIES)].map(([key, c]) => `<button aria-pressed="${currentCategory === key}" onclick="switchCategory('${key}')">${c.label}</button>`).join('');
    for (const sat of ['H9', 'H8']) el(`tab-${sat}`).setAttribute('aria-pressed', String(currentSat === sat));
    for (const mode of ['JMA', 'TW']) el(`btn-${mode.toLowerCase()}`).setAttribute('aria-pressed', String(currentMode === mode));
    for (const view of ['timeline', 'table']) el(`view-${view}`).setAttribute('aria-pressed', String(currentView === view));
    el('source-links').innerHTML = safeLink(`https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_${currentSat}.html`, 'JMA 觀測休止履歷') + ' · ' + safeLink(`https://www.data.jma.go.jp/mscweb/ja/oper/event_${currentSat}.html`, 'JMA 事件日誌');
}
function updateYearDropdown() {
    const years = [...new Set(allData().filter(r => r.satellite === currentSat).map(r => r.ad_year))].sort((a, b) => b - a);
    el('year-select').innerHTML = '<option value="ALL">全部年份</option>' + years.map(y => `<option value="${y}">${y} 年（民國 ${y - 1911} 年）</option>`).join('');
    el('year-select').value = currentYearFilter;
}
function switchSatellite(sat) { currentSat = sat; currentYearFilter = 'ALL'; updateYearDropdown(); refreshUI(); }
function switchCategory(category) { currentCategory = category; refreshUI(); }
function switchTimeMode(mode) { currentMode = mode; refreshUI(); }
function switchView(view) { currentView = view; refreshUI(); }
function showRelated(id) {
    const r = allData().find(item => item.id === id);
    if (!r) return;
    currentSat = r.satellite; currentYearFilter = String(r.ad_year); currentCategory = 'all'; searchQuery = '';
    el('search-input').value = ''; activeFilters = [...EVENT_TYPES]; updateYearDropdown(); refreshUI();
    const month = el(`month-${r.ad_year}-${String(r.month).padStart(2, '0')}`);
    month.open = true; renderMonth(month);
    const target = el(`record-${id}`);
    if (target) { target.open = true; target.classList.add('highlight'); target.scrollIntoView({behavior: 'smooth', block: 'center'}); }
}
document.addEventListener('DOMContentLoaded', async () => {
    try {
        await window.DATA_JS_READY;
        if (!allData().length) throw new Error('data.js 沒有可顯示的資料。');
        el('update-tag').textContent = `資料更新：${typeof LAST_UPDATED === 'undefined' ? '未註記' : LAST_UPDATED}`;
        updateYearDropdown(); refreshUI();
        el('source-status').innerHTML = (typeof SOURCE_STATS === 'undefined' ? [] : SOURCE_STATS).map(s => `<p>${safeLink(s.url, s.satellite + ' ' + (s.kind === 'event_log' ? '事件日誌' : '觀測休止履歷'))}：${Number(s.records)} 筆原始紀錄</p>`).join('');
    } catch (error) {
        el('update-tag').textContent = '資料載入失敗';
        el('records-accordion-container').innerHTML = `<div class="panel empty">${escapeHtml(error.message)}</div>`;
    }
});
