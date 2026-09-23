import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const fmt = value => new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', timeZone: 'UTC' });

function Chart({ rows, keys, colors, height = 236 }) {
  const width = 960, left = 34, right = 14, top = 16, bottom = 34;
  const x = i => left + (i / Math.max(rows.length - 1, 1)) * (width - left - right);
  const y = value => top + (1 - value) * (height - top - bottom);
  const path = key => rows.map((row, i) => row[key] == null ? null : `${i === 0 || rows[i - 1][key] == null ? 'M' : 'L'}${x(i).toFixed(1)},${y(row[key]).toFixed(1)}`).filter(Boolean).join(' ');
  return <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="График мощности 0–1">
    {[0, .25, .5, .75, 1].map(v => <g key={v}><line className="grid" x1={left} x2={width-right} y1={y(v)} y2={y(v)} /><text className="axis" x="0" y={y(v)+4}>{v.toFixed(2)}</text></g>)}
    {keys.map((key, i) => <path key={key} d={path(key)} fill="none" stroke={colors[i]} strokeWidth="2.5" strokeLinejoin="round" />)}
    {[0, Math.floor((rows.length-1)/2), rows.length-1].map(i => rows[i] && <text key={i} className="axis" x={x(i)} y={height-7} textAnchor={i===0?'start':i===rows.length-1?'end':'middle'}>{fmt(rows[i].time)}</text>)}
  </svg>;
}

function App() {
  const [data, setData] = useState(null), [error, setError] = useState('');
  const [theme, setTheme] = useState(localStorage.getItem('windagent-theme') || 'dark');
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('windagent-theme', theme); }, [theme]);
  useEffect(() => { fetch('/data/dashboard.json').then(r => { if (!r.ok) throw Error('Данные не экспортированы'); return r.json(); }).then(setData).catch(e => setError(e.message)); }, []);
  const revision = useMemo(() => {
    if (!data) return [];
    const first = new Map(data.revision.first.forecast.map(r => [r.target_time_utc, Number(r.point)]));
    return data.revision.second.forecast.filter(r => first.has(r.target_time_utc)).map(r => ({ time: r.target_time_utc, first: first.get(r.target_time_utc), second: Number(r.point) }));
  }, [data]);
  const trace = data?.revision.second.trace || [];
  return <div className="app">
    <header><div className="identity"><span className="mark">W</span><div><strong>Windagent</strong><small>Localhosters · HackAlem AI</small></div></div><button className="theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}</button></header>
    <main><div className="eyebrow">ПРОГНОЗ ВЭС · ИССЛЕДОВАНИЕ</div><h1>Каждый прогноз имеет<br/><em>время и источник</em></h1><p className="intro">Два выпуска 31 января 2026 года. Система ждёт публикации нового прогноза погоды, пересчитывает мощность и сохраняет причину решения.</p>
      {error && <div className="notice">{error}. Запустите <code>make dashboard</code>.</div>}
      {!data && !error && <div className="loading">Загружаем сохранённые выпуски…</div>}
      {data && <>
        <div className="metrics"><div><span>Январь · T1 · 5 дней</span><strong>{data.dev.mae.toFixed(3)}</strong><small>MAE, нормализованная мощность</small></div><div><span>Сопоставленных часов</span><strong>{data.dev.coverage}</strong><small>факт SCADA × Previous Runs</small></div><div><span>Пересчёт</span><strong>06Z → 12Z</strong><small>12Z разрешён после 20:00 UTC</small></div></div>
        <section><div className="section-top"><div><span className="eyebrow">01 / ПРОВЕРКА МОДЕЛИ</span><h2>Прогноз и факт</h2></div><div className="legend"><i style={{background:'var(--forecast)'}}/> v0 <i style={{background:'var(--actual)'}}/> SCADA</div></div><p>15–19 января 2026 · T1 · Previous Runs day1. Этот срез показывает поведение v0, не является полной оценкой Jan 2026.</p><Chart rows={data.dev.rows} keys={['forecast','actual']} colors={['var(--forecast)','var(--actual)']}/></section>
        <section><div className="section-top"><div><span className="eyebrow">02 / ПОВТОРНЫЙ ВЫПУСК</span><h2>Как изменился прогноз</h2></div><div className="legend"><i style={{background:'var(--prior)'}}/> 18:00 · 06Z <i style={{background:'var(--forecast)'}}/> 20:00 · 12Z</div></div><p>Один и тот же целевой час T1 в двух выпусках. 12Z ран был ещё недоступен в 19:00 UTC.</p><Chart rows={revision} keys={['first','second']} colors={['var(--prior)','var(--forecast)']}/><div className="note">{data.revision.second.decision.reason} · архив Open-Meteo Single Runs · модель mos-curve-v0</div></section>
        <section><div className="section-top"><div><span className="eyebrow">03 / РЕШЕНИЯ АГЕНТА</span><h2>Трейс пересчёта</h2></div><span className="chip">{trace.length} шагов</span></div><div className="trace">{trace.map(row => <div className="trace-row" key={row.step}><span>{String(row.step).padStart(2,'0')}</span><strong>{row.tool}</strong><code>{row.decision}</code><small>{typeof row.result_summary === 'object' ? JSON.stringify(row.result_summary) : row.result_summary}</small></div>)}</div></section>
        <footer>Данные: SCADA организаторов, Open-Meteo ECMWF IFS · Время всех выпусков UTC · Нормализованная мощность 0–1</footer>
      </>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
