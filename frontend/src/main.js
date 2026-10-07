import { LitElement, css, html } from "lit";
import { keyed } from "lit/directives/keyed.js";
import { api, TOKEN_KEY } from "./api.js";
import "./drains-board.js";

const LABELS = { fill: "注液", tanning: "鞣制中", drained: "已放液" };

class TanYard extends LitElement {
  static properties = {
    board: { type: Object },
    picked: { type: Object },
    ph: { type: String },
    err: { type: String },
  };

  static styles = css`
    :host { display: block; font-family: "KaiTi", serif; color: #2b2118; }
    .wrap { max-width: 880px; margin: 0 auto; padding: 0 16px 50px; }
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
    .pit { min-height: 110px; border-radius: 8px; color: #fff; cursor: pointer; border: 0; }
    .fill { background: #6d8f9e; }
    .tanning { background: #8a5a2b; }
    .drained { background: #5f6f4a; }
    .err { color: #9b1c1c; }
    .hint { color: #6b5a48; font-size: 0.92em; }
    label { display: block; margin: 8px 0; }
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
    }
  }

  render() {
    if (!this.board) return html`<div class="wrap">${this.err || "装载坑位…"}</div>`;
    return html`<div class="wrap">
      <h2>${this.board.yard} · 坑位场地图</h2>
      <p class="hint">${this.board.village} · 点坑登记浸液酸碱度；放液须最近读数 3.5～5.0</p>
      <div class="grid">
        ${this.board.pits.map(
          (p) => html`<button class="pit ${p.status}" @click=${() => (this.picked = p)}>
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
          </section>`
        : ""}
      ${this.err ? html`<p class="err">${this.err}</p>` : ""}
    </div>`;
  }
}

customElements.define("tan-yard", TanYard);

class TanApp extends LitElement {
  static properties = {
    ready: { type: Boolean },
    view: { type: String },
    err: { type: String },
    username: { type: String },
    password: { type: String },
  };

  static styles = css`
    :host { display: block; font-family: "KaiTi", serif; color: #2b2118; }
    .wrap { max-width: 880px; margin: 0 auto; padding: 28px 16px 50px; }
    nav { display: flex; gap: 4px; border-bottom: 2px solid #8a5a2b; max-width: 880px; margin: 0 auto; padding: 12px 16px 0; }
    nav a { padding: 8px 18px; text-decoration: none; color: #6b5a48; border: 1px solid transparent; border-bottom: none; border-radius: 6px 6px 0 0; }
    nav a.on { background: #efe7db; border-color: #cbb9a3; color: #2b2118; font-weight: bold; }
    .err { color: #9b1c1c; }
    .hint { color: #6b5a48; font-size: 0.92em; }
    label { display: block; margin: 8px 0; }
    input, button { font: inherit; padding: 8px 10px; margin: 4px 6px 4px 0; }
  `;

  constructor() {
    super();
    this.ready = Boolean(localStorage.getItem(TOKEN_KEY));
    this.view = location.hash === "#drains" ? "drains" : "map";
    this.err = "";
    this.username = "admin";
    this.password = "123456";
    this._onHash = () => {
      this.view = location.hash === "#drains" ? "drains" : "map";
    };
  }

  connectedCallback() {
    super.connectedCallback();
    addEventListener("hashchange", this._onHash);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    removeEventListener("hashchange", this._onHash);
  }

  go(view, event) {
    event.preventDefault();
    const hash = view === "drains" ? "#drains" : "";
    if (location.hash !== hash) location.hash = hash;
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
    } catch (ex) {
      this.err = ex.message;
    }
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
    return html`
      <nav>
        <a href="#" class=${this.view === "map" ? "on" : ""} @click=${(e) => this.go("map", e)}>坑位场地图</a>
        <a href="#drains" class=${this.view === "drains" ? "on" : ""} @click=${(e) => this.go("drains", e)}>七日放液台</a>
      </nav>
      ${keyed(
        this.view,
        this.view === "drains" ? html`<seven-day-drains></seven-day-drains>` : html`<tan-yard></tan-yard>`
      )}`;
  }
}

customElements.define("tan-app", TanApp);
