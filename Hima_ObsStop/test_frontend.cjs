// Run with: node Hima_ObsStop/test_frontend.cjs
// Execute the actual page functions, using generated data and a small DOM stub.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const elements = new Map();
const element = id => {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', classList: { add() {}, remove() {}, contains() { return false; } }, getContext() { return {}; } });
    return elements.get(id);
};
const context = vm.createContext({
    document: { addEventListener() {}, getElementById: element },
    Chart: class { constructor(ctx, config) { this.config = config; } destroy() {} },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'data.js'), 'utf8'), context);
vm.runInContext(scripts.at(-1)[1], context);
const evaluate = expression => vm.runInContext(expression, context);

evaluate(`currentSat = 'H8'; currentYearFilter = '2020'; activeFilters = ['其他'];
    renderAccordionTable(); renderSummary(); updateTrendChart();`);
const outageTable = element('records-accordion-container').innerHTML;
assert.match(outageTable, /2020-03-23/);
assert.match(outageTable, /2020-03-24/);
assert.match(outageTable, /19:30/);
assert.match(outageTable, /02:50/);
assert.match(outageTable, /P118/);
assert.match(outageTable, /P018/);
assert.match(outageTable, /45/);
assert.match(outageTable, /連續時段/);
assert.match(outageTable, /地面系統故障/);
// Other also includes the February system maintenance (11 affected slots).
assert.match(element('summary-cards').innerHTML, /受影響觀測 56 筆/);
assert.equal(evaluate('myChart.config.data.datasets.at(-1).data[2]'), 1);

evaluate(`currentMode = 'TW'; renderAccordionTable();`);
assert.match(element('records-accordion-container').innerHTML, /19:20/);
assert.match(element('records-accordion-container').innerHTML, /02:40/);
assert.equal(evaluate(`getDisplayDates({time_type:'continuous', start_utc:'2026-01-01T00:00:00Z', end_utc:'2026-01-01T00:10:00Z'}, 'TW').join(',')`),
    '2025-12-31,2026-01-01');

evaluate(`currentSat = 'H9'; currentYearFilter = '2025'; currentMode = 'JMA'; activeFilters = [...EVENT_TYPES]; renderAccordionTable();`);
const noticeTable = element('records-accordion-container').innerHTML;
assert.match(noticeTable, /改由向日葵8號接替向日葵9號進行觀測/);
assert.match(noticeTable, /營運公告/);
assert.match(noticeTable, /查看向日葵8號觀測休止紀錄/);
assert.equal(evaluate(`getEventCount({event_count:0})`), 0);
assert.equal(evaluate(`getObservationCount({observation_count:0})`), 0);
assert.equal(evaluate(`getObservationCount({observation_count:null})`), null);
assert.equal(evaluate(`summarizeRecords([{record_type:'notice',event_count:1,observation_count:1}]).events`), 0);
assert.match(evaluate(`renderRecordTime({record_type:'notice',time_raw:'13:00 UTC(P079)'}, 'TW')`), /13:00/);
assert.match(evaluate(`renderRecordTime({time_precision:'hour',time_raw:'20UTC～23UTC'}, 'TW')`), /20UTC～23UTC/);
assert.match(evaluate(`parseAndConvertTime('04:10 UTC(P025)～04:40 UTC(P028)', 'JMA')`), /04:40/);
assert.ok(!evaluate(`parseAndConvertTime('<img src=x onerror=alert(1)>', 'JMA')`).includes('<img'));
console.log('Frontend regressions passed: interval endpoints/counts, filters/charts, UTC rollover, notices, translations, and escaping.');
