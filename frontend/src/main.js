import { LitElement, css, html } from "lit";

const TOKEN_KEY = "tanpit_token";
const LABELS = { fill: "注液", tanning: "鞣制中", drained: "已放液" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && path !== "/api/auth/login") {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new CustomEvent("tanpit-unauth"));
    throw new Error("登录已失效，请重新登录");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function currentRoute() {
  return window.location.hash === "#/drains" ? "drains" : "yard";
}

function formatLocal(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* 顶栏 + 路由外壳：在「坑位场地图」与「七日放液台」两个独立专页间切换 */
class TanApp extends LitElement {
  static properties = {
    ready: { type: Boolean },
    route: { type: String },
    username: { type: String },
    password: { type: String },
    err: { type: String },
  };

  static styles = css`
    :host { display: block; font-family: "KaiTi", serif; color: #2b2118; }
    .wrap { max-width: 880px; margin: 0 auto; padding: 28px 16px 50px; }
    .topbar { display: flex; align-items: center; gap: 18px; border-bottom: 2px solid #8a5a2b; padding-bottom: 10px; margin-bottom: 18px; }
    .topbar .brand { font-size: 1.25em; font-weight: bold; margin-right: auto; }
    .topbar a { color: #6b4420; text-decoration: none; padding: 6px 10px; border-radius: 6px; }
    .topbar a.active { background: #8a5a2b; color: #fff; }
    label { display: block; margin: 8px 0; }
    input, button { font: inherit; padding: 8px 10px; margin: 4px 6px 4px 0; }
    .err { color: #9b1c1c; }
    .hint { color: #6b5a48; font-size: 0.92em; }
  `;

  constructor() {
    super();
    this.ready = Boolean(localStorage.getItem(TOKEN_KEY));
    this.route = currentRoute();
    this.username = "admin";
    this.password = "123456";
    this.err = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._onHash = () => (this.route = currentRoute());
    this._onUnauth = () => {
      this.ready = false;
      this.err = "登录已失效，请重新登录";
    };
    window.addEventListener("hashchange", this._onHash);
    window.addEventListener("tanpit-unauth", this._onUnauth);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hashchange", this._onHash);
    window.removeEventListener("tanpit-unauth", this._onUnauth);
  }

  async login(e) {
    e.preventDefault();
    this.err = "";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: this.username, password: this.password }),
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      this.ready = true;
      window.location.hash = "#/yard";
      this.route = "yard";
    } catch (ex) {
      this.err = ex.message;
    }
  }

  logout() {
    localStorage.removeItem(TOKEN_KEY);
    this.ready = false;
  }

  render() {
    if (!this.ready) {
      return html`<div class="wrap">
        <h1>南冈鞣场</h1>
        <form @submit=${this.login} autocomplete="off">
          <label>用户名
            <input name="username" autocomplete="off" .value=${this.username} @input=${(e) => (this.username = e.target.value)} />
          </label>
          <label>密码
            <input name="password" type="password" autocomplete="off" .value=${this.password} @input=${(e) => (this.password = e.target.value)} />
          </label>
          <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
          <button>登录</button>
        </form>
        ${this.err ? html`<p class="err">${this.err}</p>` : ""}
      </div>`;
    }
    return html`<div class="wrap">
      <nav class="topbar">
        <span class="brand">南冈鞣场</span>
        <a class=${this.route === "yard" ? "active" : ""} href="#/yard">坑位场地图</a>
        <a class=${this.route === "drains" ? "active" : ""} href="#/drains">七日放液台</a>
        <button @click=${this.logout}>退出</button>
      </nav>
      ${this.route === "drains" ? html`<tan-drains></tan-drains>` : html`<tan-yard></tan-yard>`}
    </div>`;
  }
}

/* 坑位场地图：可登记酸碱、拨坑态（唯一写入口） */
class TanYard extends LitElement {
  static properties = {
    board: { state: true },
    picked: { state: true },
    ph: { state: true },
    err: { state: true },
  };

  static styles = css`
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
    .pit { min-height: 110px; border-radius: 8px; color: #fff; cursor: pointer; border: 0; }
    .pit.sel { outline: 3px solid #2b2118; }
    .fill { background: #6d8f9e; }
    .tanning { background: #8a5a2b; }
    .drained { background: #5f6f4a; }
    .err { color: #9b1c1c; }
    .hint { color: #6b5a48; font-size: 0.92em; }
    input, button { font: inherit; padding: 8px 10px; margin: 4px 6px 4px 0; }
  `;

  constructor() {
    super();
    this.board = null;
    this.picked = null;
    this.ph = "4.2";
    this.err = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this.refresh();
  }

  async refresh() {
    try {
      this.board = await api("/api/board");
      if (this.picked) {
        this.picked = this.board.pits.find((p) => p.id === this.picked.id) || this.board.pits[0];
      }
    } catch (e) {
      this.err = e.message;
    }
  }

  async writePh() {
    this.err = "";
    try {
      this.picked = await api(`/api/pits/${this.picked.id}/samples`, {
        method: "POST",
        body: JSON.stringify({ ph: Number(this.ph) }),
      });
      await this.refresh();
    } catch (ex) {
      this.err = ex.message;
    }
  }

  async setStatus(status) {
    this.err = "";
    try {
      this.picked = await api(`/api/pits/${this.picked.id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await this.refresh();
    } catch (ex) {
      this.err = ex.message;
      await this.refresh();
    }
  }

  render() {
    if (!this.board) return html`${this.err ? html`<p class="err">${this.err}</p>` : "装载坑位…"}`;
    return html`
      <p>${this.board.village} · 点坑登记浸液酸碱度；放液须最近读数 3.5～5.0</p>
      <div class="grid">
        ${this.board.pits.map(
          (p) => html`<button class="pit ${p.status}${this.picked?.id === p.id ? " sel" : ""}" @click=${() => (this.picked = p)}>
            <strong>${p.code}</strong><br />${LABELS[p.status]}
          </button>`
        )}
      </div>
      ${this.picked
        ? html`<section>
            <h3>${this.picked.code} · ${LABELS[this.picked.status]}</h3>
            <p>最近酸碱度：${this.picked.latestPh ?? "无"} · ${this.picked.sampleCount} 次</p>
            <input .value=${this.ph} @input=${(e) => (this.ph = e.target.value)} />
            <button @click=${this.writePh}>登记酸碱度</button>
            <div>
              <button @click=${() => this.setStatus("fill")}>注液</button>
              <button @click=${() => this.setStatus("tanning")}>鞣制中</button>
              <button @click=${() => this.setStatus("drained")}>已放液</button>
            </div>
            <p class="hint">拨成已放液后，到「七日放液台」对账，看板数即成功放液笔数。</p>
          </section>`
        : ""}
      ${this.err ? html`<p class="err">${this.err}</p>` : ""}
    `;
  }
}

/* 七日放液台：独立只读专页。只展示服务器日历近七天内成功放液事件，
   不能改坑态、不能改酸碱；数字不看场地图当前已放液坑数。
   每次进入本页都重新拉取，不会冻在旧值。 */
class TanDrains extends LitElement {
  static properties = {
    data: { state: true },
    err: { state: true },
  };

  static styles = css`
    .count-card { background: #f3ece2; border: 1px solid #d8c6ad; border-radius: 10px; padding: 18px 22px; margin-bottom: 18px; }
    .count-card .num { font-size: 3em; font-weight: bold; color: #5f6f4a; line-height: 1.1; }
    .count-card .sub { color: #6b5a48; }
    table { border-collapse: collapse; width: 100%; margin-top: 8px; }
    th, td { border-bottom: 1px solid #e0d3bf; padding: 7px 9px; text-align: left; }
    th { background: #f3ece2; }
    .daily { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin: 10px 0 18px; }
    .day { background: #faf6ef; border: 1px solid #e0d3bf; border-radius: 8px; padding: 8px 6px; text-align: center; }
    .day .d { font-size: 0.82em; color: #6b5a48; }
    .day .n { font-size: 1.5em; font-weight: bold; }
    .readonly { color: #6b5a48; font-size: 0.92em; margin: 6px 0 16px; }
    .err { color: #9b1c1c; }
    button { font: inherit; padding: 8px 10px; }
  `;

  constructor() {
    super();
    this.data = null;
    this.err = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
  }

  async load() {
    this.err = "";
    this.data = null;
    try {
      this.data = await api("/api/drains/seven-day");
    } catch (e) {
      this.err = e.message;
    }
  }

  render() {
    if (this.err) return html`<p class="err">${this.err}</p>`;
    if (!this.data) return html`对账中…`;
    return html`
      <h2>七日放液台</h2>
      <p class="readonly">只读专页 · 服务器日历 ${this.data.timezone} · ${this.data.daily[0].date} 至 ${
        this.data.daily[6].date
      } · 此处不能改坑态、不能改酸碱</p>
      <div class="count-card">
        <div class="num">${this.data.count}</div>
        <div class="sub">近七天成功放液次数（只加算成功拨到「已放液」的笔数）</div>
      </div>
      <div class="daily">
        ${this.data.daily.map(
          (d) => html`<div class="day"><div class="d">${d.date.slice(5)}</div><div class="n">${d.count}</div></div>`
        )}
      </div>
      <h3>放液流水</h3>
      <table>
        <thead><tr><th>坑号</th><th>放液时刻</th><th>操作人</th></tr></thead>
        <tbody>
          ${this.data.events.length
            ? this.data.events.map(
                (ev) => html`<tr><td>${ev.pit}</td><td>${formatLocal(ev.drainedAt)}</td><td>${ev.operator || "—"}</td></tr>`
              )
            : html`<tr><td colspan="3">近七天暂无成功放液</td></tr>`}
        </tbody>
      </table>
      <p><button @click=${() => this.load()}>重新对账</button></p>
    `;
  }
}

customElements.define("tan-app", TanApp);
customElements.define("tan-yard", TanYard);
customElements.define("tan-drains", TanDrains);
