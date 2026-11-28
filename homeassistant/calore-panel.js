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
  // ingressi impulsi del contabilizzatore (contatori acqua dell'appartamento)
  water_hot: "acqua_calda",
  water_cold: "acqua_fredda",
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
  battery: '<path d="M3 8h15v8H3zM18 10.5h2.5v3H18"/>',
  alert: '<path d="M12 4 2.5 20h19zM12 10v5M12 17.6v.2"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  heat: '<path d="M7 4c-2 3 2 5 0 8s2 5 0 8M12 4c-2 3 2 5 0 8s2 5 0 8M17 4c-2 3 2 5 0 8s2 5 0 8"/>',
  flow: '<path d="M3 8c3-3 5 3 9 0s6 3 9 0M3 13c3-3 5 3 9 0s6 3 9 0M3 18c3-3 5 3 9 0s6 3 9 0"/>',
  thermo: '<path d="M12 3a2 2 0 0 0-2 2v9.5a4 4 0 1 0 4 0V5a2 2 0 0 0-2-2z"/><circle cx="12" cy="17" r="1.6" fill="currentColor"/>',
  snow: '<path d="M12 2v20M3.3 7l17.4 10M20.7 7 3.3 17M12 6l-2-2M12 6l2-2M12 18l-2 2M12 18l2 2"/>',
  calendar: '<path d="M4 6h16v14H4zM4 10h16M8 3v4M16 3v4"/>',
  lock: '<path d="M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3"/>',
  chart: '<path d="M4 20h16M7 16v-5M12 16V7M17 16v-8"/>',
  drop: '<path d="M12 3s-6 6.6-6 11a6 6 0 0 0 12 0c0-4.4-6-11-6-11z"/>',
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
  padding:calc(env(safe-area-inset-top) + 4px) 12px calc(env(safe-area-inset-bottom) + 12px)}
*{box-sizing:border-box}
#root{max-width:520px;margin:0 auto;display:flex;flex-direction:column;gap:12px}
.card{background:#fff;border-radius:20px;padding:16px 18px;box-shadow:0 2px 10px rgba(40,90,150,.10)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.ic{width:26px;height:26px;flex:none}
h1{font-size:26px;margin:0;font-weight:800;display:flex;align-items:center;gap:10px}
h1 .ic{width:34px;height:34px;color:#3d6f9e}
h2{font-size:21px;margin:4px 4px -2px;font-weight:800}
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
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.tile{display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:3px;
  padding:10px 3px 8px;border-radius:14px;cursor:pointer;border:0;font:inherit;color:inherit;
  width:100%;min-width:0}
.tile:active{transform:scale(.96)}
.tile .ic.b{width:28px;height:28px;color:#3d5f80}
.tile .n{font-size:13px;font-weight:800;text-align:center;line-height:1.15;
  overflow-wrap:anywhere;min-height:30px;display:flex;align-items:center}
.tile.off{background:rgba(255,255,255,.35);border:1.5px dashed #a9b7c9;box-shadow:none;color:#7b8798;cursor:default}
.tile.off .ic.b{color:#7b8798}
.tile .pw{font-size:11.5px;color:#55617a;white-space:nowrap}
.tile{position:relative}
.tile .st{position:absolute;top:4px;right:4px;display:flex}
.tile .st .ic{width:15px;height:15px;stroke-width:2.6}
.tile.ok{background:#22c55e;box-shadow:0 2px 10px rgba(40,90,150,.18)}
.tile.warn{background:#fbbf24;box-shadow:0 2px 10px rgba(40,90,150,.18)}
.tile.ok,.tile.warn,.tile.ok .pw,.tile.warn .pw,.tile.ok .ic.b,.tile.warn .ic.b{color:#0b1530}
.tile.err{background:#b91c1c;box-shadow:0 2px 10px rgba(40,90,150,.18)}
.tile.err,.tile.err .pw,.tile.err .ic.b{color:#fff}
.keys{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 14px;font-size:12px;color:#55617a}
.keys i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:-2px}
.keys .ic{width:13px;height:13px;margin-right:3px;vertical-align:-2px;stroke-width:2.4;color:#0f1b3d}
.health{display:flex;flex-direction:column;gap:10px;margin-top:10px}
.health>div{display:flex;align-items:center;gap:12px}
.health .ic{width:26px;height:26px}
.health .k{font-size:13.5px;color:#55617a;line-height:1.2}
.health .v{font-size:17px;font-weight:700;line-height:1.25}
.c-ok{color:#15803d}.c-warn{color:#a16207}.c-err{color:#b91c1c}.c-off{color:#7a869c}
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
.homebtn{position:sticky;bottom:calc(env(safe-area-inset-bottom) + 8px);z-index:2;box-shadow:0 4px 14px rgba(20,45,80,.35);background:#2f4a6b;color:#fff;border:0;border-radius:16px;padding:13px;font:inherit;
  font-size:20px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer}
.foot{text-align:center;font-size:13px;color:#55617a}
.total{display:flex;align-items:center;gap:12px}
.total>div{flex:1;min-width:0}
.yearbtn{flex:none;display:flex;flex-direction:column;align-items:center;gap:4px;border:0;cursor:pointer;
  background:#eaf3fd;color:#2f4a6b;border-radius:16px;padding:12px 12px 10px;font:inherit;font-size:13px;font-weight:700}
.yearbtn .ic{width:30px;height:30px}
.yearbtn:active{transform:scale(.96)}
.mini{padding:12px 14px}
.mini .k{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:700}
.mini .k .ic{width:22px;height:22px}
.mini .k .mo{font-weight:500;color:#55617a}
.mini .v{font-size:24px;font-weight:800;margin-top:4px;white-space:nowrap}
.water{color:#0ea5b7}
.yearnav{display:flex;align-items:center;justify-content:center;gap:18px;font-size:22px;font-weight:800}
.yearnav button{background:#fff;border:0;border-radius:12px;width:40px;height:40px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;color:#2f4a6b;box-shadow:0 2px 8px rgba(40,90,150,.10)}
.yearnav button:disabled{opacity:.35;cursor:default}
.yearnav .ic{width:24px;height:24px}
.flip{transform:scaleX(-1)}
.sum{font-size:14px;margin-top:2px}
@media(max-width:360px){.clock{font-size:38px}.big{font-size:44px}.metric .v,.energy .v,.mini .v{font-size:19px}}
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
    this._month = {};
    this._years = {};
    this._year = new Date().getFullYear();
    this._sig = "";
    this._demo = new URLSearchParams(window.location.search).has("demo");
    this._root.addEventListener("click", (ev) => {
      const yr = ev.target.closest("[data-year]");
      if (yr && !yr.disabled) {
        this._year = parseInt(yr.dataset.year, 10);
        this._update(true);
        return;
      }
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
    if (key === "cooling") {
      // presente solo sui contatori caldo/freddo
      const id = `sensor.${m.id}_energia_raffrescamento`;
      return this._hass && this._hass.states[id] ? id : null;
    }
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
  // stato di salute: "off" non collegato, "ok", "warn" batteria scarica, "err" errore
  _health(m) {
    const i = Math.max(0, this._meters.indexOf(m));
    if (this._demo) {
      const battery = i === 3 || i === 6, errors = i === 6 ? ["Errore temporaneo"] : [];
      return { level: errors.length ? "err" : battery ? "warn" : "ok", battery, days: 3650 + i * 40, errors };
    }
    const hs = (this._hass && this._hass.states) || {};
    const on = (suffix) => (hs[`binary_sensor.${m.id}_${suffix}`] || {}).state === "on";
    const num = (suffix) => {
      const st = hs[`sensor.${m.id}_${suffix}`];
      const v = st ? parseFloat(st.state) : NaN;
      return Number.isNaN(v) ? null : v;
    };
    const known = !!hs[`binary_sensor.${m.id}_batteria_scarica`];
    const errors = [];
    if (on("errore_permanente")) errors.push("Errore permanente");
    if (on("errore_temporaneo")) errors.push("Errore temporaneo");
    const flags = num("flag_di_errore");
    if (flags) errors.push(`Codice errore ${flags}`);
    const battery = known ? on("batteria_scarica") : null;
    const level = !this._online(m) ? "off" : errors.length ? "err" : battery ? "warn" : "ok";
    return { level, battery, days: num("tempo_di_accensione"), errors };
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
      water_hot: 41.27 + i * 3.1,
      water_cold: 96.84 + i * 5.7,
    }[key];
  }
  // lettura del contatore meccanico = totale impulsi + scostamento iniziale (config)
  _waterReading(m, key) {
    // lettura allineata al contatore fisico, se il servizio la pubblica
    const aligned = !this._demo && this._hass && this._hass.states[`number.${m.id}_${SUFFIX[key]}_lettura_reale`];
    if (aligned && !Number.isNaN(parseFloat(aligned.state))) return parseFloat(aligned.state);
    const v = this._num(m, key);
    if (v == null) return null;
    const off = (m.water_offset || {})[key === "water_hot" ? "hot" : "cold"] || 0;
    return v + off;
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

  async _stats(ids, start, end) {
    ids = ids.filter(Boolean);
    if (!ids.length || !this._hass) return {};
    const msg = {
      type: "recorder/statistics_during_period", start_time: start.toISOString(),
      statistic_ids: ids, period: "month", types: ["change"],
      units: { energy: "kWh", volume: "m³" },
    };
    if (end) msg.end_time = end.toISOString();
    return this._hass.callWS(msg);
  }

  // consumi del mese in corso, per contatore
  async _loadMonth() {
    const s = this._month;
    if (s.loading || (s.at && Date.now() - s.at < 300000)) return;
    s.loading = true;
    try {
      const now = new Date();
      const keys = ["energy", "cooling", "water_hot", "water_cold"];
      const per = {};
      if (this._demo) {
        this._meters.forEach((m, i) => {
          per[m.id] = { energy: 180 + i * 25, cooling: 0, water_hot: 1.8 + i * 0.2, water_cold: 3.9 + i * 0.4 };
        });
      } else {
        const start = new Date(now.getFullYear(), now.getMonth(), 1);
        const ids = this._meters.flatMap((m) => keys.map((k) => this._entity(m, k)));
        const res = await this._stats(ids, start);
        for (const m of this._meters) {
          per[m.id] = {};
          for (const k of keys) {
            const rows = res[this._entity(m, k)];
            per[m.id][k] = rows && rows.length ? rows.reduce((t, r) => t + Math.max(0, r.change || 0), 0) : null;
          }
        }
      }
      s.data = per;
      s.at = Date.now();
    } catch (err) {
      console.error("calore-panel: consumi mensili non disponibili", err);
      s.at = Date.now() - 240000;
    } finally {
      s.loading = false;
      this._update(true);
    }
  }

  // consumi mese per mese di un anno, sommati su tutti i contatori
  async _loadYear(year) {
    const s = (this._years[year] = this._years[year] || {});
    const current = year === new Date().getFullYear();
    if (s.loading || (s.at && (!current || Date.now() - s.at < 600000))) return;
    s.loading = true;
    try {
      const out = { heat: Array(12).fill(0), cool: Array(12).fill(0), hot: Array(12).fill(0), cold: Array(12).fill(0) };
      const has = { heat: false, cool: false, hot: false, cold: false };
      if (this._demo) {
        out.heat = [610, 520, 380, 150, 20, 0, 0, 0, 0, 90, 340, 560];
        out.cool = [0, 0, 0, 0, 40, 210, 330, 300, 120, 0, 0, 0];
        out.hot = [14, 13, 14, 12, 11, 9, 8, 6, 10, 12, 13, 15];
        out.cold = [30, 28, 31, 30, 33, 38, 42, 35, 32, 30, 29, 31];
        Object.keys(has).forEach((k) => (has[k] = true));
      } else {
        const map = { energy: "heat", cooling: "cool", water_hot: "hot", water_cold: "cold" };
        const pairs = this._meters.flatMap((m) => Object.keys(map).map((k) => [this._entity(m, k), map[k]]))
          .filter(([id]) => id);
        const res = await this._stats(pairs.map(([id]) => id), new Date(year, 0, 1), new Date(year + 1, 0, 1));
        for (const [id, series] of pairs) {
          for (const r of res[id] || []) {
            const d = new Date(r.start);
            if (d.getFullYear() !== year) continue;
            out[series][d.getMonth()] += Math.max(0, r.change || 0);
            has[series] = true;
          }
        }
      }
      s.data = { ...out, has };
      s.at = Date.now();
    } catch (err) {
      console.error("calore-panel: consumi annuali non disponibili", err);
      s.at = Date.now() - 540000;
    } finally {
      s.loading = false;
      this._update(true);
    }
  }

  // istogramma di 12 mesi, serie impilate
  _yearChart(series, unit, digits = 0) {
    const tot = Array.from({ length: 12 }, (_, i) => series.reduce((t, s) => t + (s.values[i] || 0), 0));
    const top = Math.max(...tot);
    if (!(top > 0)) return `<div class="empty">Nessun consumo registrato in questo anno</div>`;
    const W = 340, H = 160, L = 32, R = 4, T = 10, B = 22;
    const max = niceMax(top);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const slotW = (W - L - R) / 12, bw = slotW * 0.62;
    let out = "";
    for (let k = 0; k <= 4; k++) {
      const v = (max * k) / 4;
      out += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e9f1"/>` +
        `<text x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${fmt(v, Number.isInteger(max / 4) ? 0 : 1)}</text>`;
    }
    for (let i = 0; i < 12; i++) {
      const cx = L + slotW * (i + 0.5);
      let base = 0;
      for (const s of series) {
        const v = s.values[i] || 0;
        if (v > 0) {
          const y0 = y(base), y1 = y(base + v);
          out += `<rect x="${(cx - bw / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1.5, y0 - y1).toFixed(1)}" rx="1.5" fill="${s.color}"/>`;
        }
        base += v;
      }
      out += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${MONTHS[i].charAt(0)}</text>`;
    }
    const legend = series.length > 1
      ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("")}</div>`
      : "";
    const sum = tot.reduce((a, b) => a + b, 0);
    return `<div class="sum muted">Totale anno: <b>${fmt(sum, digits)} ${unit}</b></div>
      <div class="small muted">${unit}</div><svg class="chart" viewBox="0 0 ${W} ${H}">${out}</svg>${legend}`;
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
    const label = { heat: "Riscaldamento attivo totale", cool: "Raffrescamento attivo totale", idle: "Impianto fermo" }[mode];
    this._loadMonth();
    const md = this._month.data;
    const sumOf = (k) => {
      if (!md) return null;
      const v = this._meters.map((m) => (md[m.id] || {})[k]).filter((x) => x != null);
      return v.length ? v.reduce((a, b) => a + b, 0) : null;
    };
    const eHeat = sumOf("energy"), eCool = sumOf("cooling");
    const wHot = sumOf("water_hot"), wCold = sumOf("water_cold");
    const wTot = wHot == null && wCold == null ? null : (wHot || 0) + (wCold || 0);
    const month = now.toLocaleDateString("it-IT", { month: "short" }).replace(".", "");
    const wait = md ? "—" : "…";
    const tiles = this._meters.map((m) => {
      const p = this._num(m, "power");
      const level = this._health(m).level;
      // lo stato non è affidato al solo colore: ogni riquadro ha anche un simbolo
      const mark = { ok: "check", warn: "battery", err: "alert" }[level];
      return `<button class="card tile ${level === "off" ? "" : level}" data-go="${esc(m.id)}">${mark ? `<span class="st">${icon(mark)}</span>` : ""}${icon("building", "b")}
        <div class="n">${esc(m.name)}</div>
        <div class="pw">${this._online(m) ? (p == null ? "—" : `${fmt(Math.abs(p), 1)} kW`) : "n.d."}</div></button>`;
    });
    while (tiles.length % 4) tiles.push(`<div class="card tile off">${icon("lock", "b")}<div class="n">Non attivo</div><div class="pw">&nbsp;</div></div>`);
    return `<h1>${icon("home")}${esc(cfg.title || "Home")}</h1>
      <div class="${weather ? "row" : ""}">
        <div class="card center"><div class="date">${date}</div><div class="clock">${time}</div></div>${weather}
      </div>
      <div class="card total"><div><div class="label">Potenza termica totale</div>
        <div class="big">${fmt(total, 1)} kW</div>
        <div class="status ${mode}">${icon(mode === "cool" ? "snow" : "heat")}${label}</div></div>
        <button class="yearbtn" data-go="annuale" aria-label="Consumi annuali">${icon("chart")}Annuale</button></div>
      <div class="row">
        <div class="card mini"><div class="k"><span class="heat">${icon("heat")}</span>Energia<span class="mo">· ${month}</span></div>
          <div class="v">${eHeat == null ? wait : `${fmt(eHeat)} kWh`}</div>
          ${eCool > 0 ? `<div class="small muted">Raffrescamento ${fmt(eCool)} kWh</div>` : `<div class="small muted">Riscaldamento</div>`}</div>
        <div class="card mini"><div class="k"><span class="water">${icon("drop")}</span>Acqua<span class="mo">· ${month}</span></div>
          <div class="v">${wTot == null ? wait : `${fmt(wTot, 2)} m³`}</div>
          <div class="small muted">Calda ${fmt(wHot, 2)} · Fredda ${fmt(wCold, 2)} m³</div></div>
      </div>
      <h2>${esc(cfg.group_title || "Condomini")}</h2>
      <div class="tiles">${tiles.join("")}</div>
      <div class="keys"><span><i style="background:#22c55e"></i>${icon("check")}Regolare</span><span><i style="background:#fbbf24"></i>${icon("battery")}Batteria scarica</span><span><i style="background:#b91c1c"></i>${icon("alert")}Errore</span><span><i style="background:#fff;box-shadow:inset 0 0 0 1px #c3cedb"></i>Non collegato</span></div>
      <div class="foot">Aggiornato alle ${time}${this._demo ? " · Dati di esempio" : ""}</div>`;
  }

  _healthCard(m) {
    const h = this._health(m);
    const row = (ic, cls, k, v) => `<div><span class="${cls}">${icon(ic)}</span><div><div class="k">${k}</div><div class="v ${cls}">${v}</div></div></div>`;
    const battery = h.battery == null
      ? row("battery", "c-off", "Batteria", "Stato non disponibile")
      : h.battery ? row("battery", "c-warn", "Batteria", "Scarica")
        : row("battery", "c-ok", "Batteria", "Regolare");
    let age = "";
    if (h.days != null) {
      const years = Math.floor(h.days / 365.25), months = Math.floor((h.days - years * 365.25) / 30.44);
      const span = [years ? `${years} ${years === 1 ? "anno" : "anni"}` : "", months ? `${months} ${months === 1 ? "mese" : "mesi"}` : ""].filter(Boolean).join(" e ");
      age = row("calendar", "", "In funzione da", `${fmt(h.days)} giorni${span ? ` (${span})` : ""}`);
    }
    const errors = h.level === "off" && !h.errors.length
      ? row("alert", "c-off", "Errori", "Contabilizzatore non collegato")
      : h.errors.length ? row("alert", "c-err", "Errori", h.errors.map(esc).join("<br>"))
        : row("check", "c-ok", "Errori", "Nessuno");
    return `<div class="card"><div class="label">Stato del contabilizzatore</div><div class="health">${battery}${age}${errors}</div></div>`;
  }

  _detail(m, now) {
    this._loadCharts(m);
    this._loadMonth();
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
      ${this._healthCard(m)}
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
      <div class="card"><div class="label">Acqua · ${now.toLocaleDateString("it-IT", { month: "long" })}</div>
        <div class="muted">Consumo del mese e lettura del contatore</div>
        <div class="energy">
          ${["water_hot", "water_cold"].map((k) => {
            const md = (this._month.data || {})[m.id] || {};
            const r = this._waterReading(m, k);
            return `<div><span class="${k === "water_hot" ? "heat" : "water"}">${icon("drop")}</span><div>
              <div class="muted">${k === "water_hot" ? "Calda" : "Fredda"}</div>
              <div class="v">${fmt(md[k], 2)} m³</div>
              <div class="small muted">Contatore ${fmt(r, 2)} m³</div></div></div>`;
          }).join("")}
        </div></div>
      <div class="card"><div class="label">Potenza · ultime 24 ore</div>
        ${data ? this._powerChart(data.power) : `<div class="empty">Caricamento…</div>`}</div>
      <div class="card"><div class="label">Energia · ultimi 6 mesi</div>
        ${data ? this._energyChart(data, hasCool) : `<div class="empty">Caricamento…</div>`}</div>
      <div class="foot">Ultimo aggiornamento ${upd}${this._demo ? " · Dati di esempio" : ""}</div>
      <button class="homebtn" data-go="">${icon("home")}Home</button>`;
  }

  _yearPage(now) {
    const year = this._year, thisYear = now.getFullYear();
    this._loadYear(year);
    const d = (this._years[year] || {}).data;
    const card = (title, body) => `<div class="card"><div class="label">${title}</div>${body}</div>`;
    const loading = `<div class="empty">Caricamento…</div>`;
    let charts = loading + loading + loading;
    if (d) {
      charts =
        card(`<span class="heat">Riscaldamento</span> · energia`,
          this._yearChart([{ name: "Riscaldamento", color: "#fb923c", values: d.heat }], "kWh")) +
        card(`<span class="cool">Raffrescamento</span> · energia`,
          d.has.cool || this._demo
            ? this._yearChart([{ name: "Raffrescamento", color: "#2b8cf0", values: d.cool }], "kWh")
            : `<div class="empty">Nessun dato di raffrescamento</div>`) +
        card(`<span class="water">Acqua</span> · consumo`,
          this._yearChart([
            { name: "Calda", color: "#fb923c", values: d.hot },
            { name: "Fredda", color: "#0ea5b7", values: d.cold },
          ], "m³", 1));
    }
    return `<div class="head"><button data-go="" aria-label="Indietro">${icon("back")}</button>
        <div><div class="t">Consumi annuali</div><div class="muted">Totale dei ${this._meters.length} contabilizzatori</div></div></div>
      <div class="yearnav">
        <button data-year="${year - 1}" aria-label="Anno precedente">${icon("chevron", "flip")}</button>
        <span>${year}</span>
        <button data-year="${year + 1}" aria-label="Anno successivo" ${year >= thisYear ? "disabled" : ""}>${icon("chevron")}</button>
      </div>
      ${charts}
      <div class="foot">Valori mensili dalle statistiche di Home Assistant${this._demo ? " · Dati di esempio" : ""}</div>
      <button class="homebtn" data-go="">${icon("home")}Home</button>`;
  }

  _update(force) {
    if (!this.isConnected) return;
    const now = new Date();
    const m = this._page && this._meters.find((x) => x.id === this._page);
    // ridisegna solo se cambia qualcosa che si vede
    let sig = `${this._page}|${this._year}|${now.getHours()}:${now.getMinutes()}|${this._demo}|${this._meters.length}`;
    if (this._hass && !this._demo) {
      const ids = [];
      for (const x of m ? [m] : this._meters)
        for (const k of ["power", "flow", "t_in", "t_out", "energy", "cooling", "water_hot", "water_cold"]) ids.push(this._entity(x, k));
      for (const x of this._meters) {
        for (const k of ["batteria_scarica", "errore_permanente", "errore_temporaneo"]) ids.push(`binary_sensor.${x.id}_${k}`);
        ids.push(`sensor.${x.id}_flag_di_errore`, `sensor.${x.id}_tempo_di_accensione`);
      }
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
    this._root.innerHTML = this._page === "annuale" ? this._yearPage(now) : m ? this._detail(m, now) : this._home(now);
  }
}

if (!customElements.get("calore-panel")) customElements.define("calore-panel", CalorePanel);
