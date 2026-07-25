// views.js — hash router + the Tree / River / Reports / Observability /
// Test Lab pages. Additive layer over app.js: the original UI is the
// "overview" view and keeps running untouched; other views fetch on entry.
// Charts use the vendored echarts (static/vendor/echarts.common.min.js).
(() => {
  'use strict';

  const VIEWS = ['overview', 'tree', 'river', 'reports', 'observability', 'testlab'];
  const roots = {};
  document.querySelectorAll('[data-view-root]').forEach((el) => {
    roots[el.dataset.viewRoot] = el;
  });
  const tabs = document.querySelectorAll('.page-tab');
  let current = 'overview';
  let obsTimer = null;

  // ---- router ----------------------------------------------------------
  function viewFromHash() {
    const h = (location.hash || '#overview').slice(1).split('/')[0];
    return VIEWS.includes(h) ? h : 'overview';
  }

  function show(view) {
    current = view;
    for (const [name, el] of Object.entries(roots)) {
      el.classList.toggle('hidden', name !== view);
    }
    tabs.forEach((t) => t.classList.toggle('active', t.dataset.view === view));
    if (obsTimer) { clearInterval(obsTimer); obsTimer = null; }
    if (view === 'tree') loadTree();
    if (view === 'river') loadRiver();
    if (view === 'reports') loadReports();
    if (view === 'observability') {
      loadObservability();
      obsTimer = setInterval(loadObservability, 5000);
    }
    if (view === 'testlab') loadTestlab();
  }

  window.addEventListener('hashchange', () => show(viewFromHash()));

  document.querySelectorAll('.view-refresh').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.refresh;
      if (target === 'tree') loadTree();
      else if (target === 'river') loadRiver();
      else if (target === 'reports') loadReports();
      else if (target === 'observability') loadObservability();
      else if (target === 'testlab') loadTestlab();
    });
  });

  async function fetchText(url) {
    const r = await fetch(url);
    const body = await r.text();
    if (!r.ok) throw new Error(`${r.status}: ${body.slice(0, 300)}`);
    return body;
  }
  async function fetchJson(url, opts) {
    const r = await fetch(url, opts);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `${r.status}`);
    return body;
  }
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---- tree / river ----------------------------------------------------
  async function loadTree() {
    const pre = document.getElementById('tree-pre');
    try { pre.textContent = await fetchText('/api/tree'); }
    catch (e) { pre.textContent = `tree unavailable — ${e.message}`; }
  }
  async function loadRiver() {
    const pre = document.getElementById('river-pre');
    try { pre.textContent = await fetchText('/api/river'); }
    catch (e) { pre.textContent = `river unavailable — ${e.message}\n(the river renderer needs the evo-myworld repo root on PYTHONPATH)`; }
  }

  // ---- reports ---------------------------------------------------------
  let scoreChart = null;
  let outcomeChart = null;
  const chartTheme = {
    textStyle: { fontFamily: 'JetBrains Mono, monospace', color: '#a1a1aa' },
    backgroundColor: 'transparent'
  };
  const AXIS = {
    axisLine: { lineStyle: { color: '#262629' } },
    axisLabel: { color: '#71717a', fontSize: 10 },
    splitLine: { lineStyle: { color: '#1c1c1f' } }
  };

  async function loadReports() {
    const statsEl = document.getElementById('report-stats');
    try {
      const rep = await fetchJson('/api/report');
      const s = rep.stats || {};
      const by = s.by_status || {};
      statsEl.innerHTML = [
        stat('Best score', fmtScore(s.best_score), s.best_id || ''),
        stat('Baseline', fmtScore(s.baseline), 'first committed'),
        stat('Experiments', s.total ?? 0, `${by.committed || 0} committed`),
        stat('Frontier', s.frontier ?? 0, 'open branches'),
        stat('Failed', by.failed || 0, `${by.discarded || 0} discarded · ${by.pruned || 0} pruned`),
        stat('Metric', esc(rep.metric || ''), esc(rep.project || ''))
      ].join('');

      const series = (rep.series || []).filter((p) => p.score != null);
      if (!scoreChart) scoreChart = echarts.init(document.getElementById('report-score-chart'), null, { renderer: 'canvas' });
      scoreChart.setOption({
        ...chartTheme,
        grid: { left: 55, right: 20, top: 20, bottom: 30 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#1b1b1f', borderColor: '#262629',
          textStyle: { color: '#fafafa', fontSize: 11 },
          formatter: (ps) => ps.map((p) => {
            const d = series[p.dataIndex];
            return `<b>${esc(d.id)}</b> · ${fmtScore(d.score)} · ${esc(d.status)}<br>${esc(d.hypothesis)}`;
          }).join('<hr style="border-color:#262629">')
        },
        xAxis: { type: 'category', data: series.map((p) => p.id), ...AXIS },
        yAxis: { type: 'value', scale: true, ...AXIS },
        series: [{
          type: 'line', data: series.map((p) => p.score),
          lineStyle: { color: '#FF6A2A', width: 2 },
          itemStyle: {
            color: (p) => ({ committed: '#22c55e', failed: '#ef4444', active: '#a855f7' }[series[p.dataIndex]?.status] || '#71717a')
          },
          symbolSize: 7
        }]
      });

      const order = ['committed', 'active', 'pending', 'evaluated', 'failed', 'discarded', 'pruned', 'invalidated'];
      const colors = { committed: '#22c55e', active: '#a855f7', pending: '#f59e0b', evaluated: '#3b82f6', failed: '#ef4444', discarded: '#71717a', pruned: '#52525b', invalidated: '#3f3f46' };
      const data = order.filter((k) => by[k]).map((k) => ({ name: k, value: by[k], itemStyle: { color: colors[k] } }));
      if (!outcomeChart) outcomeChart = echarts.init(document.getElementById('report-outcome-chart'), null, { renderer: 'canvas' });
      outcomeChart.setOption({
        ...chartTheme,
        tooltip: { backgroundColor: '#1b1b1f', borderColor: '#262629', textStyle: { color: '#fafafa', fontSize: 11 } },
        series: [{
          type: 'pie', radius: ['45%', '72%'], data,
          label: { color: '#a1a1aa', fontSize: 11, formatter: '{b} {c}' },
          itemStyle: { borderColor: '#0a0a0c', borderWidth: 2 }
        }]
      });

      const rows = (rep.top || []).map((t, i) => `
        <tr>
          <td class="mono">${i + 1}</td>
          <td class="mono copy-chip" data-copy="${esc(t.id)}">${esc(t.id)}</td>
          <td class="mono score">${fmtScore(t.score)}</td>
          <td class="mono">${esc(t.parent || '')}</td>
          <td>${esc(t.hypothesis || '')}</td>
        </tr>`).join('');
      document.getElementById('report-top-table').innerHTML = rows
        ? `<table><thead><tr><th>#</th><th>id</th><th>score</th><th>parent</th><th>hypothesis</th></tr></thead><tbody>${rows}</tbody></table>`
        : '<div class="testlab-empty">no committed experiments yet</div>';
    } catch (e) {
      statsEl.innerHTML = `<div class="testlab-empty">report unavailable — ${esc(e.message)}</div>`;
    }
  }

  function stat(label, value, sub) {
    return `<div class="report-stat"><div class="label">${esc(label)}</div><div class="value">${value ?? '--'}</div><div class="sub">${esc(sub)}</div></div>`;
  }
  function fmtScore(v) {
    if (v == null) return '--';
    const n = Number(v);
    return Math.abs(n) >= 1000 ? n.toFixed(0) : n.toPrecision(4);
  }

  // ---- observability ---------------------------------------------------
  let obsSelected = null;

  async function loadObservability() {
    const grid = document.getElementById('obs-panels');
    try {
      const [graph, active] = await Promise.all([
        fetchJson('/api/graph'), fetchJson('/api/active').catch(() => [])
      ]);
      const activeIds = new Set(Array.isArray(active) ? active.map((a) => a.id || a) : []);
      const nodes = Object.values(graph.nodes || {}).filter((n) => n.id !== 'root');
      nodes.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));

      const cards = nodes.slice(0, 24).map((n) => {
        const st = activeIds.has(n.id) ? 'active' : (n.effective_status || n.status || 'pending');
        return `
        <div class="obs-card ${obsSelected === n.id ? 'selected' : ''}" data-exp="${esc(n.id)}">
          <div class="obs-id"><span class="obs-dot ${esc(st)}"></span><span class="copy-chip" data-copy="${esc(n.id)}">${esc(n.id)}</span>
            <span style="margin-left:auto;color:var(--text-4);font-size:10px">${esc(st)}</span></div>
          <div class="obs-hyp">${esc((n.hypothesis || '').slice(0, 140))}</div>
          <div class="obs-meta">score ${fmtScore(n.score)} · parent ${esc(n.parent || '—')}</div>
        </div>`;
      }).join('');
      grid.innerHTML = cards || '<div class="testlab-empty">no experiments yet</div>';
      document.getElementById('obs-updated').textContent = `updated ${new Date().toLocaleTimeString()} · ${activeIds.size} active`;

      grid.querySelectorAll('.obs-card').forEach((card) => {
        card.addEventListener('click', (ev) => {
          if (ev.target.closest('.copy-chip')) return;   // copy, don't select
          obsSelected = card.dataset.exp;
          grid.querySelectorAll('.obs-card').forEach((c) => c.classList.toggle('selected', c === card));
          loadObsTail(obsSelected);
        });
      });
      if (obsSelected) loadObsTail(obsSelected);
    } catch (e) {
      grid.innerHTML = `<div class="testlab-empty">observability unavailable — ${esc(e.message)}</div>`;
    }
  }

  async function loadObsTail(expId) {
    const pre = document.getElementById('obs-tail');
    document.getElementById('obs-tail-target').textContent = expId;
    try {
      const files = await fetchJson(`/api/node/${encodeURIComponent(expId)}/logs`);
      const list = Array.isArray(files) ? files : (files.files || []);
      if (!list.length) { pre.textContent = '(no log files for this experiment)'; return; }
      const biggest = list.reduce((a, b) => ((b.size || 0) > (a.size || 0) ? b : a));
      const body = await fetchText(`/api/node/${encodeURIComponent(expId)}/log/${encodeURIComponent(biggest.name)}`);
      pre.textContent = body.length > 40000 ? `…${body.slice(-40000)}` : body;
      pre.scrollTop = pre.scrollHeight;
    } catch (e) {
      pre.textContent = `logs unavailable — ${e.message}`;
    }
  }

  // ---- test lab (Assembly Office bridge) -------------------------------
  let tlSelected = null;

  async function officeStatus() {
    const el = document.getElementById('office-status');
    try {
      await fetchJson('/api/office/api/health');
      el.className = 'office-status up';
      el.innerHTML = 'office: <b>connected</b>';
      return true;
    } catch {
      el.className = 'office-status down';
      el.innerHTML = 'office: <b>offline</b>';
      return false;
    }
  }

  async function loadTestlab() {
    const runsEl = document.getElementById('testlab-runs');
    const up = await officeStatus();
    if (!up) {
      runsEl.innerHTML = '<div class="testlab-empty">Assembly Office is offline — start it (assembly-office/start.sh or the desktop app), then refresh. Test runs are created and executed by the office\'s AI lanes.</div>';
      return;
    }
    try {
      const runs = await fetchJson('/api/office/api/runs');
      // Office /api/runs returns run names; keep the lab focused on its own
      // testlab-* runs (everything else still lives in the office UI).
      const list = (Array.isArray(runs) ? runs : (runs.runs || []))
        .filter((r) => String(r.run || r.id || r.name || r).startsWith('testlab-'));
      runsEl.innerHTML = list.length ? list.map((r) => {
        const id = r.run || r.id || r.name || String(r);
        return `<div class="testlab-run ${tlSelected === id ? 'selected' : ''}" data-run="${esc(id)}">
          <span class="mono">${esc(id)}</span>
          <span class="stage">${esc(r.stage || r.status || '')}</span>
          <span class="when">${esc(r.updated_at || r.created_at || '')}</span>
        </div>`;
      }).join('') : '<div class="testlab-empty">no runs yet — describe a test above and create one</div>';
      runsEl.querySelectorAll('.testlab-run').forEach((row) => {
        row.addEventListener('click', () => {
          tlSelected = row.dataset.run;
          runsEl.querySelectorAll('.testlab-run').forEach((x) => x.classList.toggle('selected', x === row));
          loadTestlabRun(tlSelected);
        });
      });
    } catch (e) {
      runsEl.innerHTML = `<div class="testlab-empty">runs unavailable — ${esc(e.message)}</div>`;
    }
  }

  async function loadTestlabRun(runId) {
    const pre = document.getElementById('testlab-output');
    document.getElementById('testlab-run-label').textContent = runId;
    try {
      const state = await fetchJson(`/api/office/api/run/${encodeURIComponent(runId)}/state`);
      let out = `run: ${runId}\n${JSON.stringify(state, null, 2)}`;
      // Surface the human-facing artifacts when present.
      for (const f of ['00-GOAL.md', 'plan.json']) {
        try {
          const body = await fetchText(`/api/office/api/run/${encodeURIComponent(runId)}/file?path=${encodeURIComponent(f)}`);
          out += `\n\n───── ${f} ─────\n${body}`;
        } catch { /* file not there yet */ }
      }
      pre.textContent = out;
    } catch (e) {
      pre.textContent = `state unavailable — ${e.message}`;
    }
  }

  document.getElementById('testlab-submit').addEventListener('click', async () => {
    const desc = document.getElementById('testlab-desc').value.trim();
    const errEl = document.getElementById('testlab-error');
    errEl.classList.add('hidden');
    if (!desc) {
      errEl.textContent = 'describe what you want tested first';
      errEl.classList.remove('hidden');
      return;
    }
    const nameInput = document.getElementById('testlab-name').value.trim();
    let name = nameInput || `testlab-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '')}`;
    if (!name.startsWith('testlab-')) name = `testlab-${name}`;   // keep lab runs findable
    const btn = document.getElementById('testlab-submit');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
      const prompt = [
        'TEST LAB REQUEST (from the evo dashboard).',
        'Turn this description into a concrete, runnable test: produce the test specification,',
        'the environment/fixtures needed to run it, and the runnable test files themselves.',
        'The final deliverable must include a way to execute the test and read a clear pass/fail output.',
        '',
        `DESCRIPTION:\n${desc}`
      ].join('\n');
      await fetchJson('/api/office/api/new-run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, prompt })
      });
      document.getElementById('testlab-desc').value = '';
      document.getElementById('testlab-name').value = '';
      tlSelected = name;
      await loadTestlab();
      await loadTestlabRun(name);
    } catch (e) {
      errEl.textContent = `create failed — ${e.message}`;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false; btn.textContent = 'Create test run';
    }
  });

  // ---- keyboard map ----------------------------------------------------
  // 1-6 switch pages (ignored while typing); r refreshes the current view.
  document.addEventListener('keydown', (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const tag = (document.activeElement?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable) return;
    const idx = Number(ev.key) - 1;
    if (idx >= 0 && idx < VIEWS.length) {
      location.hash = `#${VIEWS[idx]}`;
      ev.preventDefault();
    } else if (ev.key === 'r') {
      show(current);
      ev.preventDefault();
    }
  });

  // ---- boot ------------------------------------------------------------
  officeStatus();
  setInterval(officeStatus, 30000);
  show(viewFromHash());
})();
