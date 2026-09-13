// Run the actual dashboard functions against the generated production catalog.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
    if (!elements.has(id)) elements.set(id, {
        innerHTML: '', textContent: '', value: '', hidden: false, dataset: {},
        setAttribute() {}, classList: {add() {}}, scrollIntoView() {}
    });
    return elements.get(id);
}
const context = vm.createContext({URL, document: {addEventListener() {}, getElementById: element}});
for (const file of ['data.js', 'dashboard.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context);
const evaluate = code => vm.runInContext(code, context);

evaluate(`currentSat='H8'; currentYearFilter='2020'; currentCategory='quality'; refreshUI();
    const outage=allData().find(r=>r.satellite==='H8'&&r.start_utc==='2020-03-23T19:30:00Z');`);
const card = evaluate('renderCard(outage)');
for (const text of ['2020-03-23', '2020-03-24', '19:30', '02:50', 'P118', 'P018', '45 個 10 分鐘時次',
    '實際欠配數及各頻道受影響筆數未確定', 'HimawariCast', 'HimawariCloud', '20:30', '地面系統故障', '已整合 2 份來源']) assert.ok(card.includes(text), text);
assert.equal(evaluate('getObservationCount(outage)'), null);
assert.equal(evaluate('getFilteredData().length'), 5);
// March also contains the March 21 image defect, which is only in the event log.
assert.equal(evaluate(`trendSeries()[0].values[2]`), 2);
// Summary keeps the satellite/year scope while category/search/reason filters affect the records.
const summary = element('summary-cards').innerHTML;
evaluate(`searchQuery='HimawariCloud'; activeFilters=[]; refreshUI()`);
assert.equal(element('summary-cards').innerHTML, summary);
assert.ok(evaluate('getFilteredData().length') > 0);
assert.equal(element('pause-filters').hidden, true);
evaluate(`searchQuery=''; activeFilters=[...EVENT_TYPES]; currentMode='TW'`);
assert.match(evaluate('renderRecordTime(outage)'), /19:30/);
assert.doesNotMatch(evaluate('renderRecordTime(outage)'), /19:20/);
assert.match(evaluate('renderDetails(outage)'), /19:20/); // only the history-specific alignment
assert.match(evaluate('renderDetails(outage)'), /02:40/);
assert.match(evaluate('renderDetails(outage)'), /20:30/); // per-service periods stay in UTC
assert.equal(evaluate(`getDisplayDates({time_role:'observation', time_type:'continuous', start_utc:'2026-01-01T00:00:00Z',end_utc:'2026-01-01T00:10:00Z'},'TW').join(',')`), '2025-12-31,2026-01-01');
assert.match(evaluate(`renderRecordTime({time_role:'observation',start_utc:'2026-01-01T00:00:00Z'},'TW')`), /2025-12-31 23:50/);
assert.match(evaluate(`renderRecordTime({time_role:'observation',time_precision:'hour',start_utc:'2026-01-01T20:00:00Z'},'TW')`), /20 時 UTC/);
assert.match(evaluate(`renderRecordTime({time_role:'announcement',start_utc:'2025-10-12T13:00:00Z'},'TW')`), /13:00/);
assert.match(evaluate(`renderRecordTime({time_role:'effective',start_utc:'2025-12-16T07:00:00Z'},'TW')`), /07:00/);
assert.match(evaluate(`renderRecordTime({time_role:'observation',time_type:'open_range',start_utc:'2026-01-01T20:00:00Z'},'TW')`), /未列結束時間/);
const recurring = evaluate(`renderRecordTime({time_role:'observation',time_type:'recurring_range',start_utc:'2026-01-01T10:00:00Z',end_utc:'2026-01-01T10:20:00Z',occurrence_dates_iso:['2026-01-01','2026-01-03']},'TW')`);
assert.match(recurring, /2026-01-03/);
assert.match(recurring, /反覆休止/);
assert.match(recurring, /10:10/);

evaluate(`currentSat='H9';currentYearFilter='2025';currentMode='JMA';currentCategory='notice';refreshUI()`);
const notices = evaluate(`getFilteredData().map(renderCard).join('')`);
assert.match(notices, /改由向日葵8號接替向日葵9號進行觀測/);
assert.match(notices, /預期影響/);
assert.equal(evaluate(`getFilteredData().length`), 3);
assert.equal(evaluate(`summarizeRecords(getFilteredData()).quality`), 0);
assert.equal(evaluate(`getEventCount({event_count:0})`), 0);
assert.equal(evaluate(`getEventCount({event_count:null})`), 0);
assert.equal(evaluate(`getObservationCount({observation_count:0})`), 0);
assert.equal(evaluate(`getObservationCount({observation_count:null})`), null);

evaluate(`currentCategory='change';refreshUI()`);
const changes = evaluate(`getFilteredData().map(renderCard).join('')`);
assert.equal(evaluate('getFilteredData().length'), 2);
assert.match(changes, /2025-12-16 07:00 UTC/);
assert.match(changes, /修訂前日期（不另計事件）/);
assert.match(changes, /2025年10月21日/);
assert.match(changes, /生效時間/);
assert.doesNotMatch(changes, /受影響觀測/);
assert.ok(evaluate(`trendSeries()[0].values[11]===1&&trendSeries()[0].values[9]===0`));
evaluate(`currentSat='H9';currentYearFilter='2023';currentCategory='quality';refreshUI();
    const discrete=allData().find(r=>r.satellite==='H9'&&r.start_utc==='2023-02-02T07:10:00Z');`);
assert.match(evaluate('renderRecordTime(discrete)'), /另一次時次/);
assert.doesNotMatch(evaluate('renderRecordTime(discrete)'), /～/);
assert.match(evaluate('renderCard(discrete)'), /分離時次/);
evaluate(`switchView('table')`);
assert.match(evaluate('renderTable([discrete])'), /<table class="compact">/);
assert.match(evaluate('renderTable([discrete])'), /來源與原文/);
// Lazy months render when opened; this checks more than the initially expanded month.
evaluate(`renderMonth({open:true,dataset:{month:'2023-02'}})`);
assert.match(element('body-2023-02').innerHTML, /07:50/);
evaluate(`searchQuery='definitely-no-such-event';refreshUI()`);
assert.match(element('records-accordion-container').innerHTML, /沒有紀錄/);

// Source text and links are never trusted as executable markup.
assert.doesNotMatch(evaluate(`renderRecordTime({time_raw:'<img src=x onerror=alert(1)>'})`), /<img/);
assert.equal(evaluate(`safeLink('javascript:alert(1)','<img>')`), '&lt;img&gt;');
assert.doesNotMatch(evaluate(`renderDetails({...discrete,event_tw:'<script>alert(1)</script>',attachments:[{url:'javascript:alert(1)',title_tw:'x'}]})`), /<script>|href="javascript/);
assert.match(evaluate(`renderDetails({...discrete,translation_status:'partial'})`), /保留來源原文/);
console.log('Frontend regressions passed: categories, counts, sources, ranges, channel recovery, revisions, translations, both views, filtering, UTC alignment, and escaping.');
