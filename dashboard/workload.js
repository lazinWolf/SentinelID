const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const num = value => value == null ? '—' : Number(value).toLocaleString('en-GB');
const fixed = (value, digits = 4) => value == null ? '—' : Number(value).toFixed(digits);
const dayDate = value => value ? new Intl.DateTimeFormat('en-GB', {day:'numeric', month:'short', year:'numeric', timeZone:'UTC'}).format(new Date(value.slice(0, 10) + 'T00:00:00Z')) : '—';
const stamp = value => value ? dayDate(value) + ' · ' + value.slice(11, 16) : '—';
const human = value => String(value ?? '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ');
const badge = value => `<span class="badge ${esc(value)}">${esc(human(value))}</span>`;
const scoreCell = score => `<span class="score"><span class="mono">${fixed(score)}</span><span class="score-meter" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, Number(score) * 100))}%"></i></span></span>`;
let summary, view = 'pipeline', page = 0, caseId = null, caseData = null, caseTab = 'overview', offset = 0;
let exampleId = null, exampleRun = null, lastFocus = null, caseRequest = 0, listRequest = 0;
let demo = null, demoTimer = null, demoPlaying = false, demoRequest = 0, demoLoading = false;

async function api(path, data) {
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
}
function table(headers, rows, empty = 'No records to display.') {
  if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
  return '<table><thead><tr>' + headers.map(h => '<th scope="col">' + esc(h) + '</th>').join('') + '</tr></thead><tbody>' + rows.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
}
function message(error) {
  const target = !$('drawer').hidden && $('case-error') ? $('case-error') : $('error');
  target.hidden = false;
  target.textContent = error.message || String(error);
}
function clearError() { $('error').hidden = true; }
function switchView(next) {
  if (next !== 'demo') stopDemo();
  view = next;
  document.querySelectorAll('[data-view]').forEach(button => {
    const active = button.dataset.view === next;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    $(button.dataset.view + '-view').hidden = !active;
  });
  if (next === 'demo' && !demo) loadDemo(0);
  if (next === 'cases') loadCases();
}
function stat(label, value, note) {
  return `<div class="stat"><span class="stat-label">${esc(label)}</span><strong>${esc(value)}</strong><span class="stat-note">${esc(note)}</span></div>`;
}
async function refresh() {
  try {
    const previousRun = summary?.run?.id;
    summary = await api('summary');
    clearError();
    const run = summary.run, p = summary.pipeline, selection = summary.selection;
    if (run?.id !== previousRun && demo) { stopDemo(); demo = null; if (view === 'demo') loadDemo(0); }
    $('records-count').textContent = num(run?.events_processed);
    $('scores-count').textContent = num(summary.scored_identity_days);
    $('cases-count').textContent = num(summary.case_count);
    $('days-count').textContent = num(summary.closed_days);
    $('nav-case-count').textContent = num(summary.case_count);
    $('service-state').textContent = summary.running ? 'Replay running' : run?.status === 'completed' ? 'Completed run' : run ? 'Replay paused' : 'Awaiting data';
    $('service-state').classList.toggle('running', summary.running);
    $('service-state').classList.remove('error');
    $('history-spec').textContent = `${p.reference_days}-day reference`;
    $('input-spec').textContent = `${p.input_names.length || '—'} transformed inputs`;
    $('gate-spec').textContent = `Score ≥ ${fixed(p.gate)}`;
    $('budget-spec').textContent = `${p.queue.daily_budget} per day`;
    $('model-spec').textContent = selection.scorer === 'REP_RF' ? 'Random Forest' : selection.scorer;
    $('runtime').innerHTML = run ? `<strong>${esc(summary.running ? 'Processing originals' : human(run.status))}</strong><span class="tag">${fixed(100 * run.events_processed / run.events_total, 1)}%</span>` : '<strong>No operational run yet</strong>';
    $('progress').value = run ? 100 * run.events_processed / run.events_total : 0;
    $('run-description').textContent = run ? `${num(run.events_processed)} of ${num(run.events_total)} original records committed${summary.last_scored_day ? ' · last scored day ' + dayDate(summary.last_scored_day) : ' · history warm-up before November'}.` : 'Set up the real data and model, then start the original-event replay.';
    $('policy-facts').innerHTML = `<dt>Detector</dt><dd>${esc(selection.scorer)} · ${p.input_names.length} inputs</dd><dt>Score gate</dt><dd class="mono">${fixed(p.gate, 6)} · ${esc(selection.gate)}</dd><dt>Admission budget</dt><dd>${p.queue.daily_budget} / dataset day at ${String(p.queue.decision_hour).padStart(2,'0')}:00</dd><dt>Cooldown / expiry</dt><dd>${p.queue.cooldown_days} days / ${p.queue.backlog_days} days</dd><dt>Personal reference</dt><dd>${p.reference_days} endpoints · ${p.reference_lag_days}-day lag</dd><dt>Run ID</dt><dd class="mono">${esc(run?.id || 'Not started')}</dd>`;
    $('start').disabled = !summary.ready || summary.running || run?.status === 'completed';
    $('new').disabled = !summary.ready || summary.running;
    $('pause').disabled = !summary.running;
    if (summary.error || summary.readiness_error) message(Error(summary.error || summary.readiness_error));
    renderResults();
    await loadCases();
    if (exampleRun !== run?.id) {
      exampleRun = run?.id; exampleId = null; $('example-case').disabled = true;
      if (run) {
        const examples = await api('cases?search=EDB0714');
        exampleId = examples.rows[0]?.case_id || null;
        $('example-case').disabled = !exampleId;
      }
    }
  } catch (error) {
    $('service-state').textContent = 'Service unavailable';
    $('service-state').classList.add('error');
    message(error);
  }
}
function renderResults() {
  const rows = summary.validation?.frontier || [];
  const rf = rows.find(r => r.selected), other = rows.find(r => r.system === 'C_IF/fit/max_cooldown/1');
  $('result-cards').innerHTML = rf ? stat('RF timely incident reach', `${rf.timely_incidents} / ${rf.incidents_available}`, 'Retained evidence within 72 hours') + stat('RF current-positive yield', `${fixed(100 * rf.current_positive_reviews / rf.reviews, 1)}%`, `${rf.current_positive_reviews} of ${rf.reviews} investigations`) + stat('RF actual admissions', num(rf.reviews), 'One daily admission budget') + stat('IF timely incident reach', `${other.timely_incidents} / ${other.incidents_available}`, `${other.reviews} actual admissions`) : '';
  $('results').innerHTML = table(['System', 'Daily cap', 'Admissions', 'Current-positive', 'Context-positive', 'Timely incidents'], rows.map(r => [r.selected ? '<strong>Random Forest</strong><small>Supervised · selected baseline</small>' : '<strong>Isolation Forest</strong><small>Unsupervised comparator</small>', num(r.capacity), num(r.reviews), num(r.current_positive_reviews), num(r.context_positive_reviews), `${r.timely_incidents} / ${r.incidents_available}`]));
  $('status').textContent = summary.verdict ? 'Improvement not established under the declared criterion: RF used 31 investigations versus IF’s 30. Higher observed reach came with one extra admission. November is consumed retrospective evidence.' : 'Saved evaluation results are unavailable.';
}
async function loadCases() {
  const request = ++listRequest;
  try {
    const result = await api('cases?' + new URLSearchParams({search:$('search').value, status:$('filter').value, offset:page * 20}));
    if (request !== listRequest) return;
    if (page && page * 20 >= result.total) { page = Math.max(0, Math.ceil(result.total / 20) - 1); return loadCases(); }
    $('case-total').textContent = `${num(result.total)} investigations`;
    $('cases').innerHTML = table(['Identity', 'Admitted · dataset time', 'Detector score', 'Retained records', 'Review status'], result.rows.map(c => [`<button class="case-link" data-case="${esc(c.case_id)}" aria-label="Inspect ${esc(c.identity_id)} admitted ${esc(dayDate(c.decision_time))}">${esc(c.identity_id)}</button><small>${esc(c.detector)}</small>`, esc(stamp(c.decision_time)), scoreCell(c.score), num(c.evidence_total), badge(c.review.status)]), 'No investigations match this filter. Cases appear once replay reaches November scoring.');
    $('page').textContent = result.total ? `${page * 20 + 1}–${Math.min((page + 1) * 20, result.total)} of ${num(result.total)}` : '0 investigations';
    $('previous').disabled = page === 0;
    $('next').disabled = (page + 1) * 20 >= result.total;
  } catch (error) { message(error); }
}

async function loadDemo(step) {
  const request = ++demoRequest;
  demoLoading = true;
  $('demo-play').disabled = true;
  if (!demo) {
    $('demo-unavailable').hidden = false;
    $('demo-unavailable').textContent = 'Loading the committed score and decision trace…';
  }
  try {
    const result = await api('demo?' + new URLSearchParams({step}));
    if (request !== demoRequest) return;
    $('demo-unavailable').hidden = result.available;
    $('demo-content').hidden = !result.available;
    if (!result.available) { $('demo-unavailable').textContent = result.reason; stopDemo(); return; }
    demo = result;
    renderDemo();
  } catch (error) { stopDemo(); message(error); }
  finally { if (request === demoRequest) { demoLoading = false; $('demo-play').disabled = false; } }
}
function renderDemo() {
  const f = demo.frame;
  $('demo-phase').textContent = f.drain ? 'Queue drain · no new scores' : `Scoring day ${f.step + 1} of 30`;
  $('demo-date').textContent = dayDate(f.day);
  $('demo-decision').textContent = `Recorded decision: ${stamp(f.decision_time)} · dataset time`;
  $('demo-range').max = demo.steps - 1;
  $('demo-range').value = f.step;
  $('demo-prev').disabled = f.step === 0;
  $('demo-next').disabled = f.step === demo.steps - 1;
  $('demo-timeline').innerHTML = demo.timeline.map((t, index) => `<button class="day-button ${index === f.step ? 'selected' : ''} ${t.drain ? 'drain' : ''}" data-step="${index}" aria-label="Replay ${esc(dayDate(t.day))}" ${index === f.step ? 'aria-current="step"' : ''} title="${esc(dayDate(t.day))}: ${t.scored} scored, ${t.gate_passed} offers">${t.drain ? 'D' + (index - 29) : index + 1}</button>`).join('');
  const stages = [['Eligible scores', num(f.scored), 'Recorded identity-days'], ['Pass detector gate', num(f.gate_passed), `${num(f.below_gate)} below the frozen gate`], ['Waiting in queue', num(f.pending.length), `${num(f.reasons.cooldown || 0)} cooldown · ${num(f.reasons.expired || 0)} expired`], ['Investigations admitted', num(f.admissions.length), `${num(f.cumulative_admissions)} cumulative admissions`]];
  $('demo-stages').innerHTML = stages.map(([label, value, note]) => `<div class="demo-stage"><h3>${esc(label)}</h3><strong>${esc(value)}</strong><p>${esc(note)}</p></div>`).join('');
  $('demo-gate').textContent = `score ≥ ${fixed(demo.gate)}`;
  const suppressed = new Set(f.actions.filter(a => a.reason === 'cooldown').map(a => a.identity_id));
  const merged = new Set(f.actions.filter(a => a.reason === 'merged').map(a => a.identity_id));
  $('demo-offers').innerHTML = table(['Identity', 'Detector score', 'Offer handling'], f.offers.map(o => [esc(o.identity_id), scoreCell(o.score), badge(suppressed.has(o.identity_id) ? 'cooldown' : merged.has(o.identity_id) ? 'merged' : 'queued')]), f.drain ? 'Queue drain: no new identity-day scores.' : 'No scores passed the frozen gate on this day.');
  $('demo-pending-count').textContent = `${f.pending.length} pending`;
  $('demo-pending').innerHTML = table(['Identity', 'Maximum score', 'First scoring day', 'Merged days'], f.pending.map(c => [esc(c.identity_id), fixed(c.score), esc(dayDate(c.day)), num(c.days.length)]), 'No candidates waiting after this decision.');
  const explanations = {admitted:'Admitted within the daily budget', budget_wait:'Waits for a later decision', expired:'Exceeded pending expiry', cooldown:'Suppressed after a recent admission', merged:'Merged with the pending identity'};
  $('demo-actions').innerHTML = f.actions.length ? f.actions.map(a => `<div class="decision-item"><span class="mono">${esc(a.identity_id)}</span>${badge(a.reason)}<small>${esc(explanations[a.reason] || human(a.reason))}</small></div>`).join('') : '<div class="empty">No queue actions recorded for this decision.</div>';
  $('demo-admitted').innerHTML = f.admissions.length ? f.admissions.map(c => `<div class="admitted-card"><span class="eyebrow">Committed investigation</span><strong>${esc(c.identity_id)}</strong><p>Score ${fixed(c.score)} · ${num(c.evidence_total)} retained original records</p><button class="button primary" data-case="${esc(c.case_id)}">Inspect this investigation →</button></div>`).join('') : '<div class="empty">No investigation admitted at this decision.</div>';
  $('demo-measurements').innerHTML = f.sample_measurements.map(o => `<div class="sample"><strong class="mono">${esc(o.identity_id)}</strong> · ${esc(human(o.role))} · score ${fixed(o.score)}<p>USB connections: ${num(o.counts.usb || 0)} · File copies: ${num(o.counts.copy || 0)} · After-hours logons: ${num(o.counts.after_hours || 0)}</p><p>28-day USB reference mean: ${fixed(o.reference.details.usb_change_1.reference_mean, 2)} · Copy reference mean: ${fixed(o.reference.details.copy_change_1.reference_mean, 2)}</p></div>`).join('') || '<p>No new scoring measurements during queue drain.</p>';
}
function stopDemo() {
  demoPlaying = false;
  clearTimeout(demoTimer);
  $('demo-play').textContent = 'Play';
  $('demo-play').setAttribute('aria-pressed', 'false');
}
function playDemo() {
  if (demoPlaying) { stopDemo(); return; }
  if (!demo || demoLoading) return;
  demoPlaying = true;
  $('demo-play').textContent = 'Pause playback';
  $('demo-play').setAttribute('aria-pressed', 'true');
  const tick = async () => {
    if (!demoPlaying) return;
    if (demo.frame.step >= demo.steps - 1) { stopDemo(); return; }
    await loadDemo(demo.frame.step + 1);
    if (demoPlaying) demoTimer = setTimeout(tick, Number($('demo-speed').value));
  };
  demoTimer = setTimeout(tick, Number($('demo-speed').value));
}
function jumpDemo(step) { stopDemo(); loadDemo(Number(step)); }

function closeCase() {
  caseId = null;
  caseRequest++;
  $('drawer').hidden = true;
  $('backdrop').hidden = true;
  document.body.classList.remove('modal-open');
  document.querySelectorAll('body>header,body>nav,body>main').forEach(e => { e.inert = false; });
  if (lastFocus?.isConnected && lastFocus.getClientRects().length) lastFocus.focus();
  else $('tab-cases').focus();
}
async function openCase(id) {
  stopDemo();
  lastFocus = document.activeElement;
  caseId = id; offset = 0; caseTab = 'overview';
  await inspectCase();
}
async function inspectCase() {
  const id = caseId, request = ++caseRequest;
  try {
    const result = await api('case?' + new URLSearchParams({id, offset}));
    if (request !== caseRequest || id !== caseId) return;
    caseData = result;
    $('title').textContent = result.case.identity_id;
    $('drawer').hidden = false; $('backdrop').hidden = false;
    document.body.classList.add('modal-open');
    document.querySelectorAll('body>header,body>nav,body>main').forEach(e => { e.inert = true; });
    renderCase();
    $('close').focus();
  } catch (error) { message(error); }
}
const countFields = {usb:'USB connections', copy:'File copies', logon:'Logons', after_hours:'After-hours logons', external_email:'External emails', message_bytes:'Message bytes', attachments:'Attachments', http:'HTTP visits'};
const featureLabels = {usb:'USB', copy:'File copy', usb_active:'USB active days', logon:'Logon', after_hours:'After-hours logon', external_email:'External email', message_bytes:'Message bytes', attachments:'Attachments', http:'HTTP'};
function inputLabel(field) {
  const parts = field.split(':');
  const key = parts[parts.length - 1];
  const match = key.match(/^(.*)_change_(\d)$/);
  if (match) return `${featureLabels[match[1]] || human(match[1])} change · ${match[2]} day${match[2] === '1' ? '' : 's'}` + (parts[0] === 'magnitude' && match[2] === '3' ? ' (historical target)' : '');
  return human(key);
}
function renderCase() {
  const r = caseData, c = r.case, ev = r.evidence_summary;
  $('case-content').innerHTML = `<p id="case-error" class="error" role="alert" hidden></p><p class="case-info">${esc(human(r.observations[0]?.role || 'Unknown role'))} · admitted ${esc(stamp(c.decision_time))}${badge(r.review.status)}</p><div class="case-summary"><div><small>Detector score</small><strong>${fixed(c.score)}</strong></div><div><small>Frozen gate</small><strong>${fixed(c.threshold)}</strong></div><div><small>Original evidence</small><strong>${num(r.evidence_total)}</strong></div><div><small>Scoring days merged</small><strong>${num(c.days.length)}</strong></div></div><div class="case-tabs" role="tablist" aria-label="Investigation panels">${[['overview','Decision'],['measurements','Measurements'],['evidence','Original records'],['review','Review history']].map(([key,label]) => `<button class="nav ${key === caseTab ? 'active' : ''}" role="tab" data-case-tab="${key}" id="case-tab-${key}" aria-controls="case-${key}" aria-selected="${key === caseTab}" tabindex="${key === caseTab ? 0 : -1}">${label}</button>`).join('')}</div><section id="case-overview" role="tabpanel" aria-labelledby="case-tab-overview" ${caseTab !== 'overview' ? 'hidden' : ''}><div class="panel"><h2>Admission record</h2><dl class="facts"><dt>Identity</dt><dd class="mono">${esc(c.identity_id)}</dd><dt>Model / contract</dt><dd>${esc(c.model_version)}<small class="mono"> · ${esc(c.feature_contract)}</small></dd><dt>Decision time</dt><dd>${esc(stamp(c.decision_time))} · dataset time</dd><dt>Score gate</dt><dd>${fixed(c.score)} ≥ ${fixed(c.threshold)}</dd><dt>Queue policy</dt><dd>${esc(human(c.queue_version))} · maximum pending score</dd><dt>Retained evidence</dt><dd>${num(ev.current_records)} triggering records + ${num(ev.context_records)} prior-context records</dd><dt>Reopened case</dt><dd>${c.reopening ? esc(human(c.reopening_reason)) : 'No'}</dd></dl><p class="note">Aggregate evidence supports inspection; exact forest-to-event attribution is not computed. A score above the gate is not a confirmed attack.</p></div><div class="panel"><h2>Score history before admission</h2><div class="table-wrap">${table(['Scoring day','Detector score'], c.score_history.map(h => [esc(dayDate(h.day)),scoreCell(h.score)]))}</div><details><summary>Full admission audit</summary><pre>${esc(JSON.stringify({case_id:c.case_id, model_version:c.model_version, feature_contract:c.feature_contract, calibration_version:c.calibration_version, queue_version:c.queue_version, preceding_case:c.preceding_case, new_qualifying_ids:c.new_qualifying_ids, presented_families:c.presented_families},null,2))}</pre></details></div></section><section id="case-measurements" role="tabpanel" aria-labelledby="case-tab-measurements" ${caseTab !== 'measurements' ? 'hidden' : ''}><div class="panel"><div class="measurement-days"><label for="measurement-day">Scoring day</label><select id="measurement-day">${r.observations.map((o,i) => `<option value="${i}" ${o.day === c.priority_day ? 'selected' : ''}>${esc(dayDate(o.day))}</option>`).join('')}</select></div><div id="measurement-content"></div></div></section><section id="case-evidence" role="tabpanel" aria-labelledby="case-tab-evidence" ${caseTab !== 'evidence' ? 'hidden' : ''}><div class="panel"><h2>Original source records</h2><div class="evidence-sources">${Object.entries(ev.sources).map(([source,count]) => `<span class="tag">${esc(source)} · ${num(count)}</span>`).join('')}</div><p class="note">Retrieved from the original CSV by event ID and byte offset. Current scoring records and prior rolling context are labelled separately.</p><div id="evidence-content"></div></div></section><section id="case-review" role="tabpanel" aria-labelledby="case-tab-review" ${caseTab !== 'review' ? 'hidden' : ''}><div class="panel"><h2>Versioned analyst feedback</h2><p class="note">Human dispositions and notes are separate from benchmark truth. Saving creates a real local review version.</p><div class="review-form"><div class="two-col"><label>Status<select id="reviewstatus">${['new','in_review','resolved','dismissed'].map(x => `<option value="${x}" ${r.review.status === x ? 'selected' : ''}>${esc(human(x))}</option>`).join('')}</select></label><label>Disposition<select id="disposition">${['unreviewed','benign','suspicious','confirmed','needs_context'].map(x => `<option value="${x}" ${r.review.disposition === x ? 'selected' : ''}>${esc(human(x))}</option>`).join('')}</select></label></div><label>Review note<textarea id="note" maxlength="4000">${esc(r.review.note || '')}</textarea></label><button class="button primary" id="save">Save review version</button><p id="saved" class="saved" role="status"></p></div><h2 style="margin-top:24px">Previous versions</h2><div id="review-history">${renderReviewHistory(r.review_history)}</div></div></section>`;
  renderMeasurements();
  renderEvidence();
  $('measurement-day').onchange = renderMeasurements;
  $('save').onclick = saveReview;
}
function renderMeasurements() {
  const o = caseData.observations[Number($('measurement-day').value)];
  if (!o) { $('measurement-content').innerHTML = '<p class="empty">No committed measurements are available.</p>'; return; }
  const daily = Object.entries(countFields).map(([key,label]) => {
    const changeKey = key + '_change_1', ref = o.reference.details[changeKey];
    return [esc(label),num(o.counts[key] || 0),fixed(ref?.reference_mean,2),fixed(o.features[changeKey],3),fixed(o.percentiles[changeKey],3)];
  });
  $('measurement-content').innerHTML = `<h2>Daily behavior against personal history</h2><p class="note" style="margin:0 0 15px">Reference: ${esc(dayDate(o.reference.start))} to ${esc(dayDate(o.reference.end_exclusive))} (exclusive), with a seven-day lag. Signed percentile is centered around zero.</p><div class="table-wrap">${table(['Measurement','Current day','Reference mean / day','Change magnitude','Signed percentile'],daily)}</div><h2 style="margin-top:24px">Actual transformed model inputs</h2><p class="note" style="margin:0 0 15px">These ${Object.keys(o.transformed_inputs).length} values went into the frozen RF. Magnitude and novelty use log1p; percentiles retain their sign. Values are not feature importances.</p><div class="table-wrap input-table">${table(['Input','Transformation','Value supplied to model'],Object.entries(o.transformed_inputs).map(([key,value]) => [`<span class="field-label">${esc(inputLabel(key))}</span><span class="field-id">${esc(key)}</span>`,key.startsWith('percentile:') ? 'Signed percentile' : 'log1p',fixed(value,5)]))}</div><details><summary>Reference, percentile and peer audits</summary><p>Peer measurements are inspection context, not inputs to this selected RF. The historical three-day USB/copy magnitude uses today and five/six days ago; this saved contract remains unchanged.</p><pre>${esc(JSON.stringify({reference:o.reference,percentile_reference:o.percentile_reference,peer_features:o.peer_features,peer_reference:o.peer_reference,metadata_month:o.metadata_month},null,2))}</pre></details>`;
}
function eventDescription(event) {
  const f = event.original;
  if (event.source === 'email') return `${f.activity || 'Email'} → ${(f.to || '').split(';').slice(0,2).join('; ')}${f.to?.split(';').length > 2 ? ' …' : ''}`;
  return f.activity || f.filename || f.url || event.source;
}
function renderEvidence() {
  const r = caseData;
  $('evidence-content').innerHTML = `<div class="pagination"><span>${r.evidence_total ? offset + 1 : 0}–${Math.min(offset + 50, r.evidence_total)} of ${num(r.evidence_total)}</span><button id="evprev" class="button" ${offset === 0 ? 'disabled' : ''}>Previous records</button><button id="evnext" class="button" ${offset + 50 >= r.evidence_total ? 'disabled' : ''}>Next records</button></div><div class="table-wrap event-table" style="margin-top:12px">${table(['Dataset time / source','Relationship','Activity / original fields'],r.events.map(e => [`<span class="event-time">${esc(stamp(e.timestamp))}</span><small>${esc(e.source)} · ${esc(e.original.user)} · ${esc(e.original.pc)}</small>`,e.relationship === 'current scoring period' ? '<span class="badge admitted">Current scoring period</span>' : '<span class="badge">Prior rolling context</span>',`<div class="event-resource">${esc(eventDescription(e))}</div><details><summary>Original fields · row ${num(e.row_number)}</summary><pre>${esc(JSON.stringify({event_id:e.event_id,source_file:e.source_file,offset:e.offset,original:e.original},null,2))}</pre></details>`]))}</div>`;
  $('evprev').onclick = () => loadEvidence(offset - 50);
  $('evnext').onclick = () => loadEvidence(offset + 50);
}
async function loadEvidence(nextOffset) {
  const id = caseId;
  try {
    $('evprev').disabled = true; $('evnext').disabled = true;
    const result = await api('case?' + new URLSearchParams({id, offset:nextOffset}));
    if (id !== caseId) return;
    offset = nextOffset; caseData.events = result.events;
    renderEvidence();
  } catch (error) { renderEvidence(); message(error); }
}
function renderReviewHistory(history) {
  return history.length ? history.map(r => `<div class="review-log"><strong>Version ${r.version}</strong> ${badge(r.status)}<small>${esc(r.actor)} · ${esc(stamp(r.created))}</small><p>${esc(r.note || 'No note recorded.')}</p><small>Disposition: ${esc(human(r.disposition))}</small></div>`).join('') : '<p class="note">No saved review versions yet.</p>';
}
async function saveReview() {
  const id = caseId;
  $('save').disabled = true;
  try {
    const result = await api('review',{id,version:caseData.review.version,status:$('reviewstatus').value,disposition:$('disposition').value,note:$('note').value});
    if (id !== caseId) return;
    caseData.review = result.review;
    $('saved').textContent = `Saved review version ${result.review.version}.`;
    $('review-history').innerHTML = renderReviewHistory(result.review_history);
    loadCases();
  } catch (error) { message(error); }
  finally { if (id === caseId) $('save').disabled = false; }
}
function selectCaseTab(name) {
  caseTab = name;
  document.querySelectorAll('[data-case-tab]').forEach(button => {
    const active = button.dataset.caseTab === name;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
    button.tabIndex = active ? 0 : -1;
    $('case-' + button.dataset.caseTab).hidden = !active;
  });
}
function presentationMode() {
  const enabled = document.body.classList.toggle('presentation');
  $('present').setAttribute('aria-pressed',String(enabled));
  $('present').textContent = enabled ? 'Exit presentation' : 'Presentation mode';
}
function tabKeys(event, selector, action) {
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  const buttons = [...event.target.closest('[role=tablist]').querySelectorAll(selector)];
  const index = buttons.indexOf(event.target);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
  event.preventDefault(); action(buttons[next]); buttons[next].focus();
}

document.addEventListener('click', event => {
  const caseButton = event.target.closest('[data-case]');
  if (caseButton) openCase(caseButton.dataset.case);
  const dayButton = event.target.closest('[data-step]');
  if (dayButton) jumpDemo(dayButton.dataset.step);
  const panelButton = event.target.closest('[data-case-tab]');
  if (panelButton) selectCaseTab(panelButton.dataset.caseTab);
});
document.querySelectorAll('[data-view]').forEach(button => {
  button.onclick = () => switchView(button.dataset.view);
  button.onkeydown = event => tabKeys(event,'[data-view]', b => switchView(b.dataset.view));
});
document.addEventListener('keydown', event => {
  if (event.target.matches('[data-case-tab]')) tabKeys(event,'[data-case-tab]', b => selectCaseTab(b.dataset.caseTab));
  if (!$('drawer').hidden) {
    if (event.key === 'Escape') { event.preventDefault(); closeCase(); }
    if (event.key === 'Tab') {
      const focusable = [...$('drawer').querySelectorAll('button:not(:disabled),input,select,textarea,summary,[tabindex="0"]')].filter(e => e.tabIndex >= 0 && e.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  if (event.key.toLowerCase() === 'p' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.target.closest('input,select,textarea,[contenteditable]')) presentationMode();
});
$('close').onclick = closeCase;
$('backdrop').onclick = closeCase;
$('present').onclick = presentationMode;
$('open-demo').onclick = () => switchView('demo');
$('example-case').onclick = () => { switchView('cases'); openCase(exampleId); };
$('demo-play').onclick = playDemo;
$('demo-reset').onclick = () => jumpDemo(0);
$('demo-prev').onclick = () => jumpDemo(Math.max(0,demo.frame.step - 1));
$('demo-next').onclick = () => jumpDemo(Math.min(demo.steps - 1,demo.frame.step + 1));
let scrubTimer;
$('demo-range').oninput = () => { stopDemo(); clearTimeout(scrubTimer); scrubTimer = setTimeout(() => jumpDemo($('demo-range').value),100); };
['new','start','pause'].forEach(action => { $(action).onclick = async () => {
  $(action).disabled = true;
  try { await api(action,{}); await refresh(); } catch (error) { message(error); $(action).disabled = false; }
}; });
$('refresh').onclick = refresh;
$('previous').onclick = () => { page--; loadCases(); };
$('next').onclick = () => { page++; loadCases(); };
let searchTimer;
$('search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page = 0; loadCases(); },180); };
$('filter').onchange = () => { page = 0; loadCases(); };
setInterval(() => { if ($('drawer').hidden && !demoPlaying) refresh(); },5000);
refresh();
