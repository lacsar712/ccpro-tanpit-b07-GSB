import { LitElement, css, html } from "lit";
import { api } from "./api.js";

// 七日放液台：独立只读专页。只发 GET，不能改坑态、不能登记酸碱。
export class SevenDayDrains extends LitElement {
  static properties = {
    data: { type: Object },
    err: { type: String },
    loading: { type: Boolean },
  };

  static styles = css`
    :host { display: block; font-family: "KaiTi", serif; color: #2b2118; }
    .wrap { max-width: 880px; margin: 0 auto; padding: 0 16px 50px; }
    .hint { color: #6b5a48; font-size: 0.92em; }
    .total { font-size: 1.25em; margin: 16px 0 8px; }
    .total strong { font-size: 1.5em; color: #5f6f4a; }
    table { border-collapse: collapse; margin: 12px 0; width: 100%; max-width: 420px; }
    th, td { border: 1px solid #cbb9a3; padding: 8px 14px; text-align: center; }
    th { background: #efe7db; }
    tr.today td { background: #f3efe6; font-weight: bold; }
    button { font: inherit; padding: 8px 10px; }
    .err { color: #9b1c1c; }
  `;

  constructor() {
    super();
    this.data = null;
    this.err = "";
    this.loading = false;
  }

  connectedCallback() {
    super.connectedCallback();
    // 每次进入本页组件都会被重建，此处必拉最新台账，看板不会冻住。
    this.load();
  }

  async load() {
    this.loading = true;
    this.err = "";
    try {
      this.data = await api("/api/drains/seven-day");
    } catch (e) {
      this.err = e.message;
    } finally {
      this.loading = false;
    }
  }

  render() {
    if (!this.data) {
      return html`<div class="wrap"><p>${this.err || "装载七日台账…"}</p>${this.err ? html`<p class="err">${this.err}</p>` : ""}</div>`;
    }
    return html`
      <div class="wrap">
        <h2>七日放液台</h2>
        <p class="hint">按服务器日历统计「成功拨到已放液」的次数：${this.data.start} 至 ${this.data.end}（含今天，共七天）。本页只读。</p>
        <p class="total">七日合计：<strong>${this.data.total}</strong> 次</p>
        <table>
          <thead><tr><th>日期</th><th>放液次数</th></tr></thead>
          <tbody>
            ${this.data.days.map(
              (d) => html`<tr class=${d.date === this.data.today ? "today" : ""}>
                <td>${d.date}${d.date === this.data.today ? "（今天）" : ""}</td>
                <td>${d.count}</td>
              </tr>`
            )}
          </tbody>
        </table>
        <button @click=${() => this.load()} ?disabled=${this.loading}>${this.loading ? "刷新中…" : "刷新"}</button>
        ${this.err ? html`<p class="err">${this.err}</p>` : ""}
      </div>
    `;
  }
}

customElements.define("seven-day-drains", SevenDayDrains);
