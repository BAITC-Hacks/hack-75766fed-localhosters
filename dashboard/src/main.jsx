import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const RATED_MW = 2.5;
const SCADA_OFFSET_H = 6;
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

// --- время: всё хранится в UTC, показываем по часам SCADA (UTC+6) -------------------------
const toScada = iso => new Date(new Date(iso).getTime() + SCADA_OFFSET_H * 3600e3);
const pad = n => String(n).padStart(2, '0');
const fmtDay = d => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
const fmtHM = d => `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
const fmtScada = iso => { const d = toScada(iso); return `${fmtDay(d)}, ${fmtHM(d)}`; };
const fmtUtc = iso => { const d = new Date(iso); return `${fmtDay(d)}, ${fmtHM(d)} UTC`; };
const num = (v, d = 3) => (v == null || Number.isNaN(v) ? '—' : v.toFixed(d));
const pct = v => (v == null ? '—' : `${v > 0 ? '+' : ''}${Math.round(v)}%`);

// --- данные -----------------------------------------------------------------------------------
const cache = {};
function load(name) {
  if (!cache[name]) cache[name] = fetch(`/data/${name}.json`).then(r => {
    if (!r.ok) throw new Error(`Нет данных ${name}.json — запустите make dashboard`);
    return r.json();
  });
  return cache[name];
}

function useJson(name) {
  const [state, setState] = useState({ data: null, error: '' });
  useEffect(() => {
    let live = true;
    load(name).then(data => live && setState({ data, error: '' }), e => live && setState({ data: null, error: e.message }));
    return () => { live = false; };
  }, [name]);
  return state;
}

/** Строки выпуска -> ряды для выбранной турбины или всей ВЭС (МВт). */
function seriesFor(issue, columns, turbine) {
  const ix = Object.fromEntries(columns.map((c, i) => [c, i]));
  return issue.rows.map(row => {
    const g = k => row[ix[k]];
    const base = { t: g('t'), lead: g('lead'), nlead: g('nlead'), ws: g('ws') };
    if (turbine === 'plant') {
      const a1 = g('t1_act'), a2 = g('t2_act');
      return { ...base, p50: RATED_MW * (g('t1_p50') + g('t2_p50')), p10: null, p90: null,
        act: a1 == null || a2 == null ? null : RATED_MW * (a1 + a2), flag: g('t1_flag') || g('t2_flag') };
    }
    return { ...base, p50: g(`${turbine}_p50`), p10: g(`${turbine}_p10`), p90: g(`${turbine}_p90`),
      act: g(`${turbine}_act`), flag: g(`${turbine}_flag`), med7: g(`${turbine}_med7`), last: g(`${turbine}_last`) };
  });
}

const mae = rows => {
  const ok = rows.filter(r => r.act != null);
  return ok.length ? ok.reduce((s, r) => s + Math.abs(r.p50 - r.act), 0) / ok.length : null;
};

// --- размер контейнера для графиков без масштабирования текста -------------------------------
function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

// --- график с общим курсором -------------------------------------------------------------------
function LineChart({ rows, series, band, height, yMax, yTicks, yFmt, hover, setHover, divider, label, xLabels = true, shade }) {
  const [ref, width] = useWidth();
  const m = { l: 44, r: 16, t: 14, b: xLabels ? 30 : 10 };
  const w = Math.max(width, 280), h = height;
  const n = rows.length;
  const x = i => m.l + (i / Math.max(n - 1, 1)) * (w - m.l - m.r);
  const y = v => m.t + (1 - v / yMax) * (h - m.t - m.b);
  const path = key => {
    let d = '', pen = false;
    rows.forEach((r, i) => {
      const v = r[key];
      if (v == null) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(Math.min(v, yMax)).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const bandPath = band && rows.every(r => r[band[0]] != null) ? (
    rows.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(r[band[1]]).toFixed(1)}`).join('') +
    rows.slice().reverse().map((r, k) => `L${x(n - 1 - k).toFixed(1)},${y(r[band[0]]).toFixed(1)}`).join('') + 'Z'
  ) : null;
  const pick = e => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * w;
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (w - m.l - m.r)) * (n - 1)))));
  };
  const onKey = e => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault(); e.stopPropagation();
      setHover(Math.max(0, Math.min(n - 1, (hover ?? -1) + (e.key === 'ArrowRight' ? 1 : -1))));
    }
    if (e.key === 'Escape') setHover(null);
  };
  const ticks = rows.map((r, i) => i).filter(i => toScada(rows[i].t).getUTCHours() % 6 === 0);
  return <div className="chart" ref={ref}>
    {width > 0 && <svg width={w} height={h} role="img" aria-label={label} tabIndex={0}
      onPointerMove={pick} onPointerLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)}>
      {shade != null && shade < n && <rect className="shade" x={x(shade) - (w - m.l - m.r) / (2 * (n - 1))} y={m.t} width={w - m.r - x(shade) + (w - m.l - m.r) / (2 * (n - 1))} height={h - m.t - m.b} />}
      {yTicks.map(v => <g key={v}><line className="grid" x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} />
        <text className="axis tabular" x={m.l - 8} y={y(v) + 4} textAnchor="end">{yFmt(v)}</text></g>)}
      {divider != null && <g><line className="divider" x1={x(divider)} x2={x(divider)} y1={m.t} y2={h - m.b} />
        {xLabels && <text className="axis" x={x(divider) + 6} y={m.t + 10}>сутки 2</text>}</g>}
      {bandPath && <path d={bandPath} className="band" />}
      {series.map(s => <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash || undefined} />)}
      {xLabels && ticks.map(i => {
        const d = toScada(rows[i].t);
        return <text key={i} className="axis tabular" x={x(i)} y={h - 8} textAnchor="middle">
          {d.getUTCHours() === 0 ? fmtDay(d) : fmtHM(d)}</text>;
      })}
      {hover != null && rows[hover] && <g className="cursor">
        <line x1={x(hover)} x2={x(hover)} y1={m.t} y2={h - m.b} />
        {series.map(s => rows[hover][s.key] != null &&
          <circle key={s.key} cx={x(hover)} cy={y(Math.min(rows[hover][s.key], yMax))} r="4" fill={s.color} />)}
      </g>}
    </svg>}
  </div>;
}

function Tooltip({ row, lines, unit }) {
  if (!row) return <div className="readout muted">Наведите на график или используйте ← → после клика по нему</div>;
  return <div className="readout">
    <div className="readout-time"><strong>{fmtScada(row.t)}</strong><span>UTC+6 · {fmtUtc(row.t)}</span></div>
    {lines.filter(l => l.value(row) != null).map(l => <div className="readout-row" key={l.label}>
      <i style={{ background: l.color }} className={l.dash ? 'dash' : ''} /><strong className="tabular">{l.value(row)}</strong><span>{l.label}</span>
    </div>)}
    <div className="readout-meta">
      {row.ws != null && <span>ветер NWP {num(row.ws, 1)} м/с</span>}
      {row.lead != null && <span>+{row.lead} ч от выпуска</span>}
      {row.nlead != null && <span>{row.nlead} ч от запуска прогноза погоды</span>}
      {row.flag && <span className="flag">SCADA: {FLAG_RU[row.flag] || row.flag}</span>}
    </div>
  </div>;
}

const FLAG_RU = { outage: 'простой', curtail: 'ограничение', icing: 'обледенение', frozen: 'залипший датчик',
  curve_resid: 'ниже кривой', t1_outage: 'простой T1' };

// --- лента выпусков ---------------------------------------------------------------------------
function IssueStrip({ issues, win, turbine, selected, onSelect }) {
  const values = issues.map(it => win === 'dev'
    ? (turbine === 'plant' ? (it.mae.t1.all + it.mae.t2.all) / 2 : it.mae[turbine].all)
    : it.energy_mwh_48h);
  const max = Math.max(...values.filter(v => v != null));
  const [tip, setTip] = useState(null);
  const listRef = useRef(null);
  useEffect(() => {
    // прокручиваем только саму ленту, не страницу
    const strip = listRef.current, el = strip?.children[selected];
    if (el) strip.scrollTo({ left: el.offsetLeft - strip.clientWidth / 2 + el.clientWidth / 2, behavior: 'smooth' });
  }, [selected, win]);
  return <div className="strip-wrap">
    <div className="strip-head">
      <span>{win === 'dev' ? 'MAE выпуска по фактам SCADA, ниже — лучше' : 'Прогноз выработки ВЭС за 48 ч, МВт·ч'}</span>
      <span className="muted">{tip != null ? `${fmtDay(toScada(issues[tip].issue_utc))} · ${win === 'dev' ? num(values[tip]) : num(values[tip], 1) + ' МВт·ч'}` : '← → переключают выпуски'}</span>
    </div>
    <div className="strip" ref={listRef} role="listbox" aria-label="Выпуски прогноза">
      {issues.map((it, i) => {
        const d = toScada(it.issue_utc);
        return <button key={it.issue_utc} role="option" aria-selected={i === selected}
          className={`day${i === selected ? ' on' : ''}${it.outside_test_from_lead === 0 ? ' outside' : ''}`}
          onClick={() => onSelect(i)} onPointerEnter={() => setTip(i)} onPointerLeave={() => setTip(null)}
          title={`Выпуск ${fmtScada(it.issue_utc)} (UTC+6)`}>
          <span className="bar"><span style={{ height: `${Math.max(6, (values[i] / max) * 100)}%` }} /></span>
          <span className="date tabular">{d.getUTCDate()}</span>
        </button>;
      })}
    </div>
  </div>;
}

// --- переключатель ---------------------------------------------------------------------------
function Segmented({ value, options, onChange, label }) {
  return <div className="seg" role="radiogroup" aria-label={label}>
    {options.map(o => <button key={o.value} role="radio" aria-checked={value === o.value}
      className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>)}
  </div>;
}

// --- трейс агента ------------------------------------------------------------------------------
const TOOL_RU = {
  read_memory: 'Память прошлых выпусков', get_clock: 'Часы и правило доступности', fetch_nwp_forecast: 'Архивный прогноз погоды',
  fetch_scada_history: 'История SCADA', check_data_quality: 'Проверка качества', prepare_features: 'Подготовка признаков',
  predict_power: 'Модель мощности', compare_with_previous: 'Сравнение с прошлым выпуском', save_forecast: 'Публикация прогноза',
  write_report: 'Отчёт', write_memory: 'Запись в память',
};
const pretty = v => (typeof v === 'string' ? v : JSON.stringify(v, null, 2));

function Trace({ run }) {
  const [step, setStep] = useState(0);
  useEffect(() => setStep(Math.min(step, (run?.trace.length || 1) - 1)), [run]); // eslint-disable-line
  if (!run) return <div className="notice">Для этого выпуска прогона агента нет.</div>;
  const s = run.trace[step];
  return <div className="trace">
    <ol className="steps">
      {run.trace.map((r, i) => <li key={r.step}>
        <button className={i === step ? 'on' : ''} onClick={() => setStep(i)}>
          <span className="n tabular">{pad(r.step)}</span>
          <span className="tool"><strong>{TOOL_RU[r.tool] || r.tool}</strong><code>{r.tool}</code></span>
          <span className={`decision ${r.decision === 'continue' ? '' : 'key'}`}>{r.decision}</span>
        </button>
      </li>)}
    </ol>
    <div className="step-detail" aria-live="polite">
      <div className="detail-head"><span className="eyebrow">Шаг {s.step} из {run.trace.length}</span><h3>{TOOL_RU[s.tool] || s.tool}</h3></div>
      <dl>
        <dt>Решение</dt><dd><code>{s.decision}</code> — {s.rationale}{s.model_id && <><br /><span className="muted">решал {s.model_id}{s.tokens ? ` · ${s.tokens.input} / ${s.tokens.output} токенов` : ''}{s.fallback_reason ? ` · откат: ${s.fallback_reason}` : ''}</span></>}</dd>
        <dt>Аргументы</dt><dd><pre>{pretty(s.args)}</pre></dd>
        <dt>Результат</dt><dd><pre>{pretty(s.result_summary)}</pre></dd>
      </dl>
    </div>
  </div>;
}

// --- приложение --------------------------------------------------------------------------------
function App() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('windagent-theme') || 'dark'; } catch { return 'dark'; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('windagent-theme', theme); } catch { /* private mode */ }
  }, [theme]);

  const [win, setWin] = useState('dev');
  const [turbine, setTurbine] = useState('t1');
  const [selected, setSelected] = useState({ dev: 14, test: 0 });
  const [hover, setHover] = useState(null);
  const [runKind, setRunKind] = useState('dayahead');
  const [decider, setDecider] = useState('llm');

  const index = useJson('index');
  const devData = useJson('dev');
  const testData = useJson('test');
  const agent = useJson('agent');
  const data = win === 'dev' ? devData.data : testData.data;
  const error = index.error || devData.error || testData.error;

  const issues = data?.issues || [];
  const idx = Math.min(selected[win], Math.max(issues.length - 1, 0));
  const issue = issues[idx];
  const select = useCallback(i => { setSelected(s => ({ ...s, [win]: i })); setHover(null); }, [win]);

  useEffect(() => {
    const onKey = e => {
      if (e.target.closest?.('svg, input, textarea')) return;
      if (e.key === 'ArrowRight') select(Math.min(idx + 1, issues.length - 1));
      if (e.key === 'ArrowLeft') select(Math.max(idx - 1, 0));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [idx, issues.length, select]);

  const rows = useMemo(() => (issue && data ? seriesFor(issue, data.columns, turbine) : []), [issue, data, turbine]);
  const day = issue ? toScada(issue.issue_utc).toISOString().slice(0, 10) : null;
  const runs = agent.data?.[win]?.[day];
  const llmRuns = win === 'test' ? agent.data?.llm_test?.[day] : null;
  const traceRuns = decider === 'llm' && llmRuns ? llmRuns : runs;
  const run = runs?.[runKind] || runs?.dayahead;
  const traceRun = traceRuns?.[runKind] || traceRuns?.dayahead;
  const plant = turbine === 'plant';
  const yMax = plant ? 2 * RATED_MW : 1;
  const yTicks = plant ? [0, 1.25, 2.5, 3.75, 5] : [0, 0.25, 0.5, 0.75, 1];
  const yFmt = v => (plant ? v.toFixed(v % 1 ? 2 : 0) : v.toFixed(2));
  const unit = plant ? 'МВт' : 'доля';
  const fmtV = v => (v == null ? null : plant ? `${v.toFixed(2)} МВт` : v.toFixed(3));

  // KPI
  const kpi = useMemo(() => {
    if (!issue) return [];
    if (win === 'dev') {
      const d1 = mae(rows.filter(r => r.lead <= 23)), d2 = mae(rows.filter(r => r.lead >= 24));
      const med = rows.filter(r => r.act != null && r.med7 != null);
      const medMae = med.length ? med.reduce((s, r) => s + Math.abs(r.med7 - r.act), 0) / med.length : null;
      const all = mae(rows);
      const k = plant ? '' : ' · доля от 2.5 МВт';
      return [
        { label: 'MAE, сутки 1', value: num(d1), note: `часы 1–24${k}` },
        { label: 'MAE, сутки 2', value: num(d2), note: `часы 25–48${k}` },
        { label: 'Медиана за 7 дней', value: plant ? '—' : num(medMae), note: 'бейзлайн на тех же часах' },
        { label: 'Выигрыш модели', value: plant || !medMae ? '—' : pct(100 * (medMae - all) / medMae), note: 'к бейзлайну, по MAE' },
      ];
    }
    const energy = rows.reduce((s, r) => s + (plant ? r.p50 : RATED_MW * r.p50), 0);
    const peak = Math.max(...rows.map(r => r.p50));
    const ws = rows.reduce((s, r) => s + (r.ws || 0), 0) / rows.length;
    const spread = plant ? null : rows.reduce((s, r) => s + (r.p90 - r.p10), 0) / rows.length;
    return [
      { label: 'Выработка за 48 ч', value: `${energy.toFixed(1)}`, note: `МВт·ч · ${plant ? 'вся ВЭС' : turbine.toUpperCase()}` },
      { label: 'Пиковая мощность', value: plant ? `${peak.toFixed(2)}` : peak.toFixed(2), note: plant ? 'МВт' : 'доля от 2.5 МВт' },
      { label: 'Средний ветер NWP', value: ws.toFixed(1), note: 'м/с на 100 м, ECMWF IFS' },
      { label: 'Ширина P10–P90', value: spread == null ? '—' : spread.toFixed(2), note: 'средняя неопределённость' },
    ];
  }, [issue, rows, win, plant, turbine]);

  // окно: метрики v0 vs бейзлайны
  const windowMetrics = useMemo(() => {
    const ms = index.data?.metrics || [];
    const tb = plant ? 'T1' : turbine.toUpperCase();
    const get = (model, block) => ms.find(m => m.model === model && m.turbine === tb && m.block === block)?.mae;
    const primary = index.data?.model?.key || 'v0';
    const names = { v1: 'Модель v1 (LightGBM + v0)', v0: 'Модель v0 (MOS + кривая)', median_7d: 'Медиана за 7 дней', last_value: 'Последнее значение' };
    const keys = [primary, ...(primary === 'v0' ? [] : ['v0']), 'median_7d', 'last_value'];
    return { tb, primary, rows: keys.map(k => ({ k, name: names[k] || k, h1: get(k, 'h1_24'), h2: get(k, 'h25_48'), all: get(k, 'all') }))
      .filter(r => r.all != null) };
  }, [index.data, turbine, plant]);

  // сцена пересчёта
  const revision = useMemo(() => {
    const a = runs?.dayahead, b = runs?.reissue;
    if (!a || !b || plant) return null;
    const key = turbine;
    const off = (new Date(b.issue_utc) - new Date(a.issue_utc)) / 3600e3;
    const pa = a.points[key], pb = b.points[key];
    if (!pa || !pb) return null;
    const out = pb.map((v, i) => ({ t: new Date(new Date(b.issue_utc).getTime() + i * 3600e3).toISOString(), lead: null,
      nlead: null, ws: null, prev: pa[i + off] ?? null, next: v }));
    const both = out.filter(r => r.prev != null);
    let maxI = 0; both.forEach((r, i) => { if (Math.abs(r.next - r.prev) > Math.abs(both[maxI].next - both[maxI].prev)) maxI = i; });
    return { a, b, rows: both, maxDelta: both.length ? both[maxI] : null };
  }, [runs, turbine, plant]);
  const [revHover, setRevHover] = useState(null);

  const download = () => {
    const name = index.data?.downloads?.test_hourly_csv;
    if (!name) return;
    const a = document.createElement('a');
    a.href = `/data/${name}`; a.download = name; a.click();
  };

  const loading = !index.data || !data;
  return <div className="app">
    <header>
      <div className="identity"><span className="mark">W</span><div><strong>Windagent</strong><small>Localhosters · HackAlem AI</small></div></div>
      <button className="ghost" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}</button>
    </header>

    <main>
      <div className="eyebrow">ВЭС «Нурлы» · 2 × 2.5 МВт · прогноз на 48 часов</div>
      <h1>Прогноз выработки на архивных <em>прогнозах погоды</em></h1>
      <p className="intro">Каждый выпуск использует только тот прогноз ECMWF, который был опубликован к моменту выпуска.
        Январь — проверка на фактических данных SCADA, февраль — тестовый период, факты скрыты организаторами.</p>

      {error && <div className="notice">{error}</div>}

      <div className="controls">
        <Segmented label="Период" value={win} onChange={w => { setWin(w); setHover(null); setRunKind('dayahead'); }} options={[
          { value: 'dev', label: 'Январь · проверка на фактах' }, { value: 'test', label: 'Февраль · тест' }]} />
        <Segmented label="Объект" value={turbine} onChange={t => { setTurbine(t); setHover(null); }} options={[
          { value: 't1', label: 'T1' }, { value: 't2', label: 'T2' }, { value: 'plant', label: 'ВЭС, МВт' }]} />
        <button className="ghost push" onClick={download} disabled={!index.data}>Скачать сабмит за февраль, CSV</button>
      </div>

      {loading && !error ? <Skeleton /> : issue && <div className="fade" key={win}>
        <IssueStrip issues={issues} win={win} turbine={turbine} selected={idx} onSelect={select} />

        <div className="issue-head">
          <div>
            <span className="eyebrow">Выпуск {idx + 1} из {issues.length}</span>
            <h2>{fmtScada(issue.issue_utc)} <span className="muted">UTC+6</span></h2>
            <p>{fmtUtc(issue.issue_utc)} · прогноз на {fmtDay(toScada(rows[0].t))} и {fmtDay(toScada(rows[24].t))}</p>
          </div>
          <div className="provenance">
            <span>Погода</span><strong>ECMWF IFS {fmtUtc(issue.run_init_utc).replace(' UTC', '')} UTC</strong>
            <small>опубликован {run ? fmtUtc(run.run_available_utc) : '—'} · до выпуска {run ? Math.round((new Date(issue.issue_utc) - new Date(run.run_available_utc)) / 3600e3) : '—'} ч</small>
          </div>
          <div className="nav">
            <button className="ghost" onClick={() => select(Math.max(idx - 1, 0))} disabled={idx === 0} aria-label="Предыдущий выпуск">←</button>
            <button className="ghost" onClick={() => select(Math.min(idx + 1, issues.length - 1))} disabled={idx === issues.length - 1} aria-label="Следующий выпуск">→</button>
          </div>
        </div>

        <div className="metrics">{kpi.map(k => <div key={k.label}><span>{k.label}</span><strong>{k.value}</strong><small>{k.note}</small></div>)}</div>

        <section>
          <div className="section-top">
            <div><span className="eyebrow">01 · Прогноз на 48 часов</span><h2>{win === 'dev' ? 'Прогноз и факт' : 'Прогноз мощности'}</h2></div>
            <div className="legend">
              <span><i className="line" style={{ background: 'var(--forecast)' }} />P50</span>
              {!plant && <span><i className="area" />P10–P90</span>}
              {win === 'dev' && <span><i className="line" style={{ background: 'var(--actual)' }} />факт SCADA</span>}
            </div>
          </div>
          <LineChart rows={rows} height={300} yMax={yMax} yTicks={yTicks} yFmt={yFmt} hover={hover} setHover={setHover}
            divider={24} band={plant ? null : ['p10', 'p90']} label={`Мощность, ${unit}`}
            shade={issue.outside_test_from_lead}
            series={[{ key: 'p50', color: 'var(--forecast)' }, ...(win === 'dev' ? [{ key: 'act', color: 'var(--actual)' }] : [])]} />
          <div className="subchart-label">Ветер по прогнозу ECMWF, 100 м, м/с</div>
          <LineChart rows={rows} height={96} yMax={Math.max(15, Math.ceil(Math.max(...rows.map(r => r.ws || 0)) / 5) * 5)}
            yTicks={[0, 10]} yFmt={v => v.toFixed(0)} hover={hover} setHover={setHover} divider={24} xLabels={false}
            label="Ветер NWP, м/с" series={[{ key: 'ws', color: 'var(--wind)' }]} />
          <Tooltip row={hover != null ? rows[hover] : null} unit={unit} lines={[
            { label: 'P50', color: 'var(--forecast)', value: r => fmtV(r.p50) },
            { label: 'P10–P90', color: 'var(--band-key)', value: r => (r.p10 == null ? null : `${r.p10.toFixed(2)}–${r.p90.toFixed(2)}`) },
            { label: 'факт SCADA', color: 'var(--actual)', value: r => (win === 'dev' ? fmtV(r.act) ?? 'нет данных' : null) },
          ]} />
          {issue.outside_test_from_lead === 0 && <p className="note">Последний выпуск (28 фев, 18:00 UTC) целиком попадает на 1–2 марта — за пределами тестового периода, в сабмит не входит.</p>}
        </section>

        <section>
          <div className="section-top">
            <div><span className="eyebrow">02 · Повторный расчёт</span><h2>Пришёл новый прогноз погоды</h2></div>
            {revision && <div className="legend">
              <span><i className="line dash" style={{ background: 'var(--prior)' }} />18:00 UTC · ран 06Z</span>
              <span><i className="line" style={{ background: 'var(--forecast)' }} />20:00 UTC · ран 12Z</span>
            </div>}
          </div>
          {win === 'dev' ? <p>Январь — окно проверки на фактах; в кеше только утренние раны 06Z, пересчёт показан на февральских выпусках. Переключитесь на «Февраль · тест».</p>
            : plant ? <p>Сравнение выпусков показывается по одной турбине — выберите T1 или T2.</p>
            : !revision ? <p>Для этого дня нет пары выпусков.</p> : <>
              <p>В 18:00 UTC агент выпустил прогноз на ране 06Z. Ран 12Z публикуется в 19:34 UTC — в 20:00 агент видит его, сравнивает с прошлым выпуском и публикует новую версию.</p>
              <div className="rev-stats">
                <div><span>Изменение ветра</span><strong className="tabular">{num(revision.b.comparison?.divergence_ms, 2)} м/с</strong><small>средний |Δ| по часам перекрытия</small></div>
                <div><span>Изменение мощности</span><strong className="tabular">{num(revision.b.comparison?.mean_abs_delta)}</strong><small>средний |Δ|, обе турбины</small></div>
                <div><span>Наибольший сдвиг за час</span><strong className="tabular">{revision.maxDelta ? pct(100 * (revision.maxDelta.next - revision.maxDelta.prev)).replace('%', ' п.п.') : '—'}</strong><small>{revision.maxDelta ? fmtScada(revision.maxDelta.t) : ''}</small></div>
                <div><span>Решение агента</span><strong>{revision.b.decision.publish ? 'опубликовать' : 'не публиковать'}</strong><small>{revision.b.decision.reason}</small></div>
              </div>
              <LineChart rows={revision.rows} height={220} yMax={1} yTicks={[0, 0.5, 1]} yFmt={v => v.toFixed(1)}
                hover={revHover} setHover={setRevHover} label="Два выпуска на одни и те же часы"
                series={[{ key: 'prev', color: 'var(--prior)', dash: '5 4' }, { key: 'next', color: 'var(--forecast)' }]} />
              <Tooltip row={revHover != null ? { ...revision.rows[revHover], ws: null } : null} lines={[
                { label: '18:00 · 06Z', color: 'var(--prior)', dash: true, value: r => num(r.prev) },
                { label: '20:00 · 12Z', color: 'var(--forecast)', value: r => num(r.next) },
                { label: 'разница', color: 'transparent', value: r => (r.prev == null ? null : `${r.next - r.prev > 0 ? '+' : ''}${(r.next - r.prev).toFixed(3)}`) },
              ]} />
            </>}
        </section>

        <section>
          <div className="section-top">
            <div><span className="eyebrow">03 · Решения агента</span><h2>Трейс выпуска</h2></div>
            <div className="controls-inline">
              {llmRuns && <Segmented label="Кто решает" value={decider} onChange={setDecider} options={[
                { value: 'llm', label: `LLM · ${llmRuns.dayahead?.decision?.model_id || 'OpenAI'}` }, { value: 'rules', label: 'Правила' }]} />}
              {win === 'test' && runs?.reissue && <Segmented label="Выпуск" value={runKind} onChange={setRunKind} options={[
                { value: 'dayahead', label: '18:00 UTC' }, { value: 'reissue', label: '20:00 UTC · пересчёт' }]} />}
            </div>
          </div>
          <p>Каждый выпуск проходит 11 шагов. Код считает прогноз, а решение — публиковать ли его и нужен ли пересчёт — принимает {llmRuns && decider === 'llm' ? 'LLM с объяснением для диспетчера; если ответ LLM не проходит проверку, решают правила' : 'детерминированный набор правил'}. Выберите шаг, чтобы увидеть входы и результат.</p>
          {traceRun?.decision && <div className="decision-card">
            <div><span>Решение</span><strong>{traceRun.decision.publish ? 'опубликовать' : 'не публиковать'} · <code>{traceRun.decision.reason}</code></strong></div>
            <p>{traceRun.decision.summary_ru}</p>
            <small>{traceRun.decision.planner === 'openai' ? `LLM ${traceRun.decision.model_id}` : 'правила'}{traceRun.decision.fallback_reason ? ` · откат на правила: ${traceRun.decision.fallback_reason}` : ''}{(() => { const t = traceRun.trace.find(s => s.tokens)?.tokens; return t ? ` · ${t.input} / ${t.output} токенов` : ''; })()}</small>
          </div>}
          <Trace run={traceRun} />
        </section>

        <section>
          <div className="section-top"><div><span className="eyebrow">04 · Точность за январь</span><h2>Модель против бейзлайнов</h2></div>
            <span className="chip">{windowMetrics.tb} · 31 выпуск · MAE</span></div>
          <p>Все 31 январский выпуск, те же правила доступности прогнозов, что и в феврале. MAE в долях от 2.5 МВт, ниже — лучше.</p>
          <div className="table-scroll"><table>
            <thead><tr><th>Модель</th><th className="num">Сутки 1</th><th className="num">Сутки 2</th><th className="num">48 часов</th></tr></thead>
            <tbody>{windowMetrics.rows.map(r => <tr key={r.k} className={r.k === windowMetrics.primary ? 'strong' : ''}>
              <td>{r.name}</td><td className="num tabular">{num(r.h1)}</td><td className="num tabular">{num(r.h2)}</td><td className="num tabular">{num(r.all)}</td></tr>)}</tbody>
          </table></div>
        </section>

        <details className="table-view">
          <summary>Таблица выпуска · 48 часов</summary>
          <div className="table-scroll"><table>
            <thead><tr><th>Время UTC+6</th><th className="num">+ч</th><th className="num">Ветер, м/с</th><th className="num">P10</th><th className="num">P50</th><th className="num">P90</th>{win === 'dev' && <th className="num">Факт</th>}</tr></thead>
            <tbody>{rows.map(r => <tr key={r.t}><td className="tabular">{fmtScada(r.t)}</td><td className="num tabular">{r.lead}</td><td className="num tabular">{num(r.ws, 1)}</td>
              <td className="num tabular">{num(r.p10)}</td><td className="num tabular">{plant ? r.p50.toFixed(2) : num(r.p50)}</td><td className="num tabular">{num(r.p90)}</td>
              {win === 'dev' && <td className="num tabular">{r.act == null ? '—' : plant ? r.act.toFixed(2) : num(r.act)}</td>}</tr>)}</tbody>
          </table></div>
        </details>
      </div>}
      <footer>SCADA организаторов · Open-Meteo Single Runs (ECMWF IFS 9 км, CC BY 4.0) · Время выпусков UTC, оси — часы SCADA UTC+6 · Модель {index.data?.model.version}{index.data?.model.blend ? ` (${Math.round(100 * index.data.model.blend.lightgbm_weight)}% LightGBM + ${Math.round(100 * index.data.model.blend.v0_weight)}% v0)` : ''}</footer>
    </main>
  </div>;
}

function Skeleton() {
  return <div className="skeleton" aria-busy="true" aria-label="Загрузка">
    <div className="sk strip-sk" /><div className="sk head-sk" />
    <div className="metrics">{[0, 1, 2, 3].map(i => <div key={i} className="sk tile-sk" />)}</div>
    <div className="sk chart-sk" />
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
