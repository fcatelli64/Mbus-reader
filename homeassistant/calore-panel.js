/*
 * Pannello "Calore" per Home Assistant: pagina principale + una pagina per
 * contabilizzatore, pensato per smartphone. Nessuna dipendenza esterna.
 *
 * Installazione: vedi README ("Pannello per smartphone").
 * Aggiungendo ?demo all'indirizzo mostra dati di esempio.
 */

const SUFFIX = {
  energy: "energia",
  power: "potenza",
  flow: "portata",
  t_in: "temperatura_mandata",
  t_out: "temperatura_ritorno",
};

const WEATHER = {
  "clear-night": ["🌙", "Sereno"], cloudy: ["☁️", "Nuvoloso"], fog: ["🌫️", "Nebbia"],
  hail: ["🌨️", "Grandine"], lightning: ["🌩️", "Temporale"],
  "lightning-rainy": ["⛈️", "Temporale"], partlycloudy: ["⛅", "Poco nuvoloso"],
  pouring: ["🌧️", "Pioggia forte"], rainy: ["🌦️", "Pioggia"], snowy: ["❄️", "Neve"],
  "snowy-rainy": ["🌨️", "Nevischio"], sunny: ["☀️", "Sereno"], windy: ["💨", "Ventoso"],
  "windy-variant": ["💨", "Ventoso"], exceptional: ["⚠️", "Allerta"],
};

const ICON = {
  home: '<path d="M3 11.2 12 3l9 8.2V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" fill="currentColor" stroke="none"/>',
  building: '<path d="M5 21V8l7-4 7 4v13M3 21h18M9 11h2M13 11h2M9 15h2M13 15h2M11 21v-3h2v3"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  heat: '<path d="M7 4c-2 3 2 5 0 8s2 5 0 8M12 4c-2 3 2 5 0 8s2 5 0 8M17 4c-2 3 2 5 0 8s2 5 0 8"/>',
  flow: '<path d="M3 8c3-3 5 3 9 0s6 3 9 0M3 13c3-3 5 3 9 0s6 3 9 0M3 18c3-3 5 3 9 0s6 3 9 0"/>',
  thermo: '<path d="M12 3a2 2 0 0 0-2 2v9.5a4 4 0 1 0 4 0V5a2 2 0 0 0-2-2z"/><circle cx="12" cy="17" r="1.6" fill="currentColor"/>',
  snow: '<path d="M12 2v20M3.3 7l17.4 10M20.7 7 3.3 17M12 6l-2-2M12 6l2-2M12 18l-2 2M12 18l2 2"/>',
  calendar: '<path d="M4 6h16v14H4zM4 10h16M8 3v4M16 3v4"/>',
  lock: '<path d="M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3"/>',
};
const icon = (name, cls = "") =>
  `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[name]}</svg>`;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, digits = 0) =>
  v == null || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("it-IT", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: "always" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const MONTHS = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"];

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 3, 4, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

const STYLE = `
:host{display:block;height:100vh;height:100dvh;overflow-y:auto;box-sizing:border-box;
  background:linear-gradient(180deg,#dcefff 0%,#eaf5ff 45%,#dbeeff 100%);
  color:#0f1b3d;font-family:Roboto,"Segoe UI",system-ui,sans-serif;
  -webkit-tap-highlight-color:transparent;
  padding:calc(env(safe-area-inset-top) + 14px) 14px calc(env(safe-area-inset-bottom) + 18px)}
*{box-sizing:border-box}
#root{max-width:520px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.card{background:#fff;border-radius:20px;padding:16px 18px;box-shadow:0 2px 10px rgba(40,90,150,.10)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.ic{width:26px;height:26px;flex:none}
h1{font-size:26px;margin:0;font-weight:800;display:flex;align-items:center;gap:10px}
h1 .ic{width:34px;height:34px;color:#3d6f9e}
h2{font-size:24px;margin:8px 4px 0;font-weight:800}
.muted{color:#55617a}
.center{text-align:center}
.date{font-size:15px;font-weight:500}
.clock{font-size:44px;font-weight:800;line-height:1.1;margin-top:4px}
.weather{display:flex;align-items:center;justify-content:center;gap:10px}
.weather .emo{font-size:40px;line-height:1}
.weather .t{font-size:25px;font-weight:800;line-height:1.15;white-space:nowrap}
.small{font-size:13px}
.big{font-size:52px;font-weight:800;line-height:1.1;margin:4px 0}
.label{font-size:19px;font-weight:700}
.status{display:flex;align-items:center;gap:8px;font-weight:700;font-size:17px}
.heat{color:#f97316}.cool{color:#2b8cf0}.idle{color:#7a869c}
.tile{display:flex;flex-direction:column;align-items:center;gap:6px;padding:18px 10px 14px;
  cursor:pointer;border:0;font:inherit;color:inherit;width:100%}
.tile:active{transform:scale(.97)}
.tile .ic.b{width:52px;height:52px;color:#3d5f80}
.tile{position:relative}
.tile .n{font-size:21px;font-weight:800;text-align:center;padding:0 16px;line-height:1.15}
.tile>.ic.go{position:absolute;right:10px;top:50%;margin-top:-10px;width:20px;height:20px;color:#3d6f9e}
.tile.off{background:rgba(255,255,255,.35);border:2px dashed #a9b7c9;box-shadow:none;color:#7b8798;cursor:default}
.tile.off .ic.b{color:#7b8798}
.tile .pw{font-size:13px;color:#55617a}
.head{display:flex;align-items:center;gap:12px}
.head button{background:none;border:0;padding:6px;color:inherit;cursor:pointer;display:flex}
.head .ic{width:30px;height:30px}
.head .t{font-size:26px;font-weight:800;line-height:1.1}
.badge{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:16px}
.dot{width:10px;height:10px;border-radius:50%;background:#22c55e}
.dot.off{background:#ef4444}
.datebar{display:flex;align-items:center;gap:14px;font-size:18px}
.datebar .ic{color:#3d5f80}
.datebar .h{margin-left:auto;font-size:24px;font-weight:800;padding-left:16px;border-left:1.5px solid #d5dce6}
.metric{display:flex;align-items:center;gap:12px;padding:14px}
.metric .ic{width:32px;height:32px;color:#3d5f80}
.metric .sep{align-self:stretch;width:1.5px;background:#d5dce6}
.metric .k{font-size:14.5px;line-height:1.2}
.metric .v{font-size:22px;font-weight:800;margin-top:4px;white-space:nowrap}
.energy{display:grid;grid-template-columns:1fr 1fr;margin-top:12px}
.energy.one{grid-template-columns:1fr}
.energy>div{display:flex;align-items:center;gap:12px}
.energy>div+div{border-left:1.5px solid #d5dce6;padding-left:14px}
.energy .ic{width:34px;height:34px}
.energy .v{font-size:22px;font-weight:800;white-space:nowrap}
.chart{width:100%;height:auto;display:block;margin-top:6px}
.chart text{font-size:11px;fill:#55617a;font-family:inherit}
.legend{display:flex;justify-content:center;gap:22px;font-size:13px;margin-top:4px}
.legend i{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:6px}
.empty{padding:26px 0;text-align:center;color:#7a869c;font-size:14px}
.homebtn{background:#2f4a6b;color:#fff;border:0;border-radius:16px;padding:16px;font:inherit;
  font-size:20px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer}
.foot{text-align:center;font-size:13px;color:#55617a}
@media(max-width:360px){.clock{font-size:38px}.big{font-size:44px}.metric .v,.energy .v{font-size:19px}}
`;

class CalorePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById("root");
    this._config = {};
    this._page = null;
    this._charts = {};
    this._sig = "";
    this._demo = new URLSearchParams(window.location.search).has("demo");
    this._root.addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-go]");
      if (el) this._go(el.dataset.go);
    });
  }

  // ---- proprietà impostate da Home Assistant
  set panel(p) {
    this._panel = p;
    this._config = (p && p.config) || {};
    if (this._config.demo) this._demo = true;
    this._update();
  }
  set route(r) {
    const page = ((r && r.path) || "").replace(/^\/+|\/+$/g, "") || "";
    if (page !== (this._page || "")) {
      this._page = page || null;
      this.scrollTop = 0;
      this._update();
    }
  }
  set hass(h) {
    this._hass = h;
    this._update();
  }
  set narrow(_) {}

  connectedCallback() {
    this._timer = setInterval(() => this._update(), 20000);
    this._update();
  }
  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ---- dati
  get _meters() {
    return this._config.meters || [];
  }
  _entity(m, key) {
    if (m.entities && m.entities[key]) return m.entities[key];
    return SUFFIX[key] ? `sensor.${m.id}_${SUFFIX[key]}` : null;
  }
  _state(m, key) {
    const id = this._entity(m, key);
    return id && this._hass ? this._hass.states[id] : undefined;
  }
  _num(m, key) {
    if (this._demo) return this._demoValue(m, key);
    const st = this._state(m, key);
    if (!st) return null;
    let v = parseFloat(st.state);
    if (Number.isNaN(v)) return null;
    if (key === "power" && (st.attributes.unit_of_measurement || "W") === "W") v /= 1000;
    return v;
  }
  _online(m) {
    if (this._demo) return true;
    const st = this._state(m, "power");
    return !!st && st.state !== "unavailable";
  }
  _demoValue(m, key) {
    const i = Math.max(0, this._meters.indexOf(m));
    const wob = Math.sin(Date.now() / 60000 + i);
    return {
      power: [3.2, 2.4, 1.9, 4.1, 2.8, 3.2, 1.0][i % 7] + wob * 0.1,
      flow: 0.42 - i * 0.03,
      t_in: 42.5 + i,
      t_out: 35.9 + i * 0.6,
      energy: 1248 + i * 310,
      cooling: 386 + i * 45,
    }[key];
  }
  _mode(m) {
    const p = Math.abs(this._num(m, "power") || 0);
    if (p < 0.05) return "idle";
    const a = this._num(m, "t_in"), b = this._num(m, "t_out");
    return a != null && b != null && a < b ? "cool" : "heat";
  }

  _go(page) {
    this._page = page || null;
    this.scrollTop = 0;
    if (this._panel && this._panel.url_path) {
      const base = `/${this._panel.url_path}`;
      window.history.pushState(null, "", (page ? `${base}/${page}` : base) + window.location.search);
      window.dispatchEvent(new CustomEvent("location-changed"));
    }
    this._update();
  }

  // ---- grafici (statistiche a lungo termine di Home Assistant)
  async _loadCharts(m) {
    const slot = (this._charts[m.id] = this._charts[m.id] || {});
    if (slot.loading || (slot.at && Date.now() - slot.at < 300000)) return;
    slot.loading = true;
    try {
      const now = new Date();
      const months = [];
      for (let k = 5; k >= 0; k--) months.push(new Date(now.getFullYear(), now.getMonth() - k, 1));
      const key = (d) => `${d.getFullYear()}-${d.getMonth()}`;
      let heat = {}, cool = {}, power = [];
      if (this._demo) {
        const h = [4, 3, 3, 48, 175, 250], c = [262, 280, 224, 78, 0, 0];
        months.forEach((d, i) => { heat[key(d)] = h[i]; cool[key(d)] = c[i]; });
        for (let i = 0; i <= 288; i++) {
          const t = now.getTime() - (288 - i) * 300000;
          const hr = new Date(t).getHours() + new Date(t).getMinutes() / 60;
          const bump = (c0, w, a) => a * Math.exp(-((hr - c0) ** 2) / (2 * w * w));
          power.push([t, 0.7 + bump(19, 1.8, 4.5) + bump(11.5, 1.3, 4.5) + bump(16.5, 1.5, 1.8)]);
        }
      } else if (this._hass) {
        const eHeat = this._entity(m, "energy"), eCool = this._entity(m, "cooling");
        const ePow = this._entity(m, "power");
        const [mon, pw] = await Promise.all([
          this._hass.callWS({
            type: "recorder/statistics_during_period", start_time: months[0].toISOString(),
            statistic_ids: [eHeat, eCool].filter(Boolean), period: "month",
            types: ["change"], units: { energy: "kWh" },
          }),
          this._hass.callWS({
            type: "recorder/statistics_during_period",
            start_time: new Date(now.getTime() - 24 * 3600000).toISOString(),
            statistic_ids: [ePow], period: "5minute", types: ["mean"], units: { power: "kW" },
          }),
        ]);
        const fill = (rows, out) =>
          (rows || []).forEach((r) => { out[key(new Date(r.start))] = Math.max(0, r.change || 0); });
        fill(mon[eHeat], heat);
        if (eCool) fill(mon[eCool], cool);
        power = (pw[ePow] || []).filter((r) => r.mean != null)
          .map((r) => [new Date(r.start).getTime(), Math.abs(r.mean)]);
      }
      slot.data = { months, heat, cool, power, key };
      slot.at = Date.now();
    } catch (err) {
      console.error("calore-panel: statistiche non disponibili", err);
      slot.at = Date.now() - 240000; // riprova tra un minuto
    } finally {
      slot.loading = false;
      this._update(true);
    }
  }

  _powerChart(points) {
    if (!points || points.length < 2) return `<div class="empty">Nessun dato nelle ultime 24 ore</div>`;
    const W = 340, H = 150, L = 26, R = 10, T = 14, B = 22;
    const t1 = Date.now(), t0 = t1 - 24 * 3600000;
    const max = niceMax(Math.max(...points.map((p) => p[1])));
    const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const pts = points.filter((p) => p[0] >= t0).map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`);
    if (pts.length < 2) return `<div class="empty">Nessun dato nelle ultime 24 ore</div>`;
    const first = pts[0].split(",")[0], last = points[points.length - 1];
    let grid = "";
    for (let k = 0; k <= 4; k++) {
      const v = (max * k) / 4;
      grid += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e9f1"/>` +
        `<text x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${fmt(v, Number.isInteger(max / 4) ? 0 : 1)}</text>`;
    }
    const tick = new Date(t0);
    tick.setMinutes(0, 0, 0);
    tick.setHours(tick.getHours() + 1);
    for (; tick.getTime() <= t1; tick.setHours(tick.getHours() + 1)) {
      if (tick.getHours() % 4) continue;
      const tx = x(tick.getTime());
      grid += `<line x1="${tx}" x2="${tx}" y1="${T}" y2="${H - B}" stroke="#eef2f7"/>` +
        `<text x="${tx}" y="${H - 6}" text-anchor="middle">${String(tick.getHours()).padStart(2, "0")}</text>`;
    }
    const lx = x(last[0]), ly = y(last[1]);
    return `<div class="small muted">kW</div>
      <svg class="chart" viewBox="0 0 ${W} ${H}">${grid}
      <polygon points="${first},${H - B} ${pts.join(" ")} ${lx.toFixed(1)},${H - B}" fill="rgba(43,140,240,.16)"/>
      <polyline points="${pts.join(" ")}" fill="none" stroke="#2b8cf0" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${lx}" cy="${ly}" r="3.6" fill="#2b8cf0"/></svg>`;
  }

  _energyChart(d, hasCool) {
    const vals = d.months.map((m) => [d.heat[d.key(m)] || 0, hasCool ? d.cool[d.key(m)] || 0 : 0]);
    const top = Math.max(...vals.flat());
    if (!(top > 0)) return `<div class="empty">Nessun consumo registrato finora</div>`;
    const W = 340, H = 160, L = 30, R = 6, T = 10, B = 22;
    const max = niceMax(top);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const slotW = (W - L - R) / 6, bw = hasCool ? slotW * 0.3 : slotW * 0.5;
    let out = "";
    for (let k = 0; k <= 3; k++) {
      const v = (max * k) / 3;
      out += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e9f1"/>` +
        `<text x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
    }
    vals.forEach(([h, c], i) => {
      const cx = L + slotW * (i + 0.5);
      const bar = (v, x0, color) =>
        v > 0 ? `<rect x="${x0}" y="${y(v)}" width="${bw}" height="${Math.max(1.5, H - B - y(v))}" rx="2" fill="${color}"/>` : "";
      out += hasCool ? bar(h, cx - bw - 1, "#fb923c") + bar(c, cx + 1, "#2b8cf0") : bar(h, cx - bw / 2, "#fb923c");
      out += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${MONTHS[d.months[i].getMonth()]}</text>`;
    });
    const legend = hasCool
      ? `<div class="legend"><span><i style="background:#fb923c"></i>Riscaldamento</span><span><i style="background:#2b8cf0"></i>Raffrescamento</span></div>`
      : "";
    return `<div class="small muted">kWh</div><svg class="chart" viewBox="0 0 ${W} ${H}">${out}</svg>${legend}`;
  }

  // ---- pagine
  _home(now) {
    const hass = this._hass, cfg = this._config;
    const date = cap(now.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
    const time = now.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    const wid = cfg.weather || (hass && Object.keys(hass.states).find((k) => k.startsWith("weather.")));
    const w = hass && wid ? hass.states[wid] : null;
    let weather = "";
    if (this._demo || w) {
      const [emo, text] = this._demo ? WEATHER.sunny : WEATHER[w.state] || ["🌡️", w.state];
      const a = this._demo ? { temperature: 15.2, humidity: 80, wind_speed: 18, wind_speed_unit: "km/h" } : w.attributes;
      const extra = [
        a.humidity != null ? `Umidità ${fmt(a.humidity)}%` : "",
        a.wind_speed != null ? `Vento ${fmt(a.wind_speed)} ${a.wind_speed_unit || "km/h"}` : "",
      ].filter(Boolean).join(" · ");
      weather = `<div class="card"><div class="weather"><div class="emo">${emo}</div><div>
        <div class="label" style="font-size:17px">${esc(text)}</div>
        <div class="t">${fmt(a.temperature, 1)} °C</div></div></div>
        <div class="small muted center" style="margin-top:6px">${esc(extra)}</div></div>`;
    }
    const total = this._meters.reduce((s, m) => s + Math.abs(this._num(m, "power") || 0), 0);
    const modes = this._meters.map((m) => this._mode(m));
    const heat = modes.filter((x) => x === "heat").length, cool = modes.filter((x) => x === "cool").length;
    const mode = heat + cool === 0 ? "idle" : heat >= cool ? "heat" : "cool";
    const label = { heat: "Riscaldamento attivo", cool: "Raffrescamento attivo", idle: "Impianto fermo" }[mode];
    const tiles = this._meters.map((m) => {
      const p = this._num(m, "power");
      return `<button class="card tile" data-go="${esc(m.id)}">${icon("building", "b")}
        <div class="n">${esc(m.name)}</div>${icon("chevron", "go")}
        <div class="pw">${this._online(m) ? (p == null ? "—" : `${fmt(Math.abs(p), 1)} kW`) : "non disponibile"}</div></button>`;
    });
    if (tiles.length % 2) tiles.push(`<div class="card tile off">${icon("lock", "b")}<div class="n">Non attivo</div><div class="pw">&nbsp;</div></div>`);
    return `<h1>${icon("home")}${esc(cfg.title || "Home")}</h1>
      <div class="${weather ? "row" : ""}">
        <div class="card center"><div class="date">${date}</div><div class="clock">${time}</div></div>${weather}
      </div>
      <div class="card"><div class="label">Potenza termica totale</div>
        <div class="big">${fmt(total, 1)} kW</div>
        <div class="status ${mode}">${icon(mode === "cool" ? "snow" : "heat")}${label}</div>
        <div class="muted" style="margin-top:6px">Somma dei ${this._meters.length} contabilizzatori</div></div>
      <h2>${esc(cfg.group_title || "Condomini")}</h2>
      <div class="row">${tiles.join("")}</div>
      <div class="foot">Aggiornato alle ${time}${this._demo ? " · Dati di esempio" : ""}</div>`;
  }

  _detail(m, now) {
    this._loadCharts(m);
    const date = cap(now.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
    const time = now.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    const online = this._online(m);
    const metric = (ic, k, v) => `<div class="card metric">${icon(ic)}<div class="sep"></div><div><div class="k">${k}</div><div class="v">${v}</div></div></div>`;
    const p = this._num(m, "power");
    const hasCool = this._demo || !!this._entity(m, "cooling");
    const energy = this._num(m, "energy"), cooling = hasCool ? this._num(m, "cooling") : null;
    const data = (this._charts[m.id] || {}).data;
    const st = this._state(m, "power");
    const upd = this._demo || !st ? time : new Date(st.last_updated).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    return `<div class="head"><button data-go="" aria-label="Indietro">${icon("back")}</button>
        <div><div class="t">${esc(m.name)}</div><div class="muted">Contabilizzatore</div></div>
        <div class="badge"><span class="dot ${online ? "" : "off"}"></span>${online ? "Online" : "Offline"}</div></div>
      <div class="card datebar">${icon("calendar")}<span>${date}</span><span class="h">${time}</span></div>
      <div class="row">
        ${metric("flow", "Portata", `${fmt(this._num(m, "flow"), 2)} m³/h`)}
        ${metric("heat", "Potenza istantanea", `${fmt(p == null ? null : Math.abs(p), 1)} kW`)}
        ${metric("thermo", "Temperatura ingresso", `${fmt(this._num(m, "t_in"), 1)} °C`)}
        ${metric("thermo", "Temperatura uscita", `${fmt(this._num(m, "t_out"), 1)} °C`)}
      </div>
      <div class="card"><div class="label">Energia consumata</div><div class="muted">Letture cumulative</div>
        <div class="energy ${hasCool ? "" : "one"}">
          <div><span class="heat">${icon("heat")}</span><div><div class="muted">Riscaldamento</div><div class="v">${fmt(energy)} kWh</div></div></div>
          ${hasCool ? `<div><span class="cool">${icon("snow")}</span><div><div class="muted">Raffrescamento</div><div class="v">${fmt(cooling)} kWh</div></div></div>` : ""}
        </div></div>
      <div class="card"><div class="label">Potenza · ultime 24 ore</div>
        ${data ? this._powerChart(data.power) : `<div class="empty">Caricamento…</div>`}</div>
      <div class="card"><div class="label">Energia · ultimi 6 mesi</div>
        ${data ? this._energyChart(data, hasCool) : `<div class="empty">Caricamento…</div>`}</div>
      <div class="foot">Ultimo aggiornamento ${upd}${this._demo ? " · Dati di esempio" : ""}</div>
      <button class="homebtn" data-go="">${icon("home")}Home</button>`;
  }

  _update(force) {
    if (!this.isConnected) return;
    const now = new Date();
    const m = this._page && this._meters.find((x) => x.id === this._page);
    // ridisegna solo se cambia qualcosa che si vede
    let sig = `${this._page}|${now.getHours()}:${now.getMinutes()}|${this._demo}|${this._meters.length}`;
    if (this._hass && !this._demo) {
      const ids = [];
      for (const x of m ? [m] : this._meters)
        for (const k of ["power", "flow", "t_in", "t_out", "energy", "cooling"]) ids.push(this._entity(x, k));
      const wid = this._config.weather || Object.keys(this._hass.states).find((k) => k.startsWith("weather."));
      if (!m && wid) ids.push(wid);
      for (const id of ids) {
        const st = id && this._hass.states[id];
        sig += `|${st ? st.state + st.last_updated : ""}`;
      }
    }
    if (!force && sig === this._sig) return;
    this._sig = sig;
    if (!this._meters.length) {
      this._root.innerHTML = `<div class="card">Nessun contabilizzatore configurato: aggiungi <b>meters</b> alla configurazione del pannello.</div>`;
      return;
    }
    this._root.innerHTML = m ? this._detail(m, now) : this._home(now);
  }
}

if (!customElements.get("calore-panel")) customElements.define("calore-panel", CalorePanel);
