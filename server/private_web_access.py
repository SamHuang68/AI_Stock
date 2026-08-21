#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Private Web ST access-request storage and server-rendered pages.

The request ledger contains personal contact data and therefore stays in the
private runtime ``data`` directory.  It never grants access by itself: an
Owner must still share the ST machine in Tailscale and deliver the Reader
credential through a separate secure channel.
"""
from __future__ import annotations

import copy
import html
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .atomic_store import atomic_write_json, load_json
except ImportError:  # pragma: no cover - gateway is also launched as a script
    from atomic_store import atomic_write_json, load_json


VALID_STATUSES = (
    "pending",
    "approved",
    "tailscale_invited",
    "active",
    "denied",
    "revoked",
)
STATUS_LABELS = {
    "pending": "待審核",
    "approved": "已核准",
    "tailscale_invited": "已送 Tailscale 邀請",
    "active": "已開通",
    "denied": "未核准",
    "revoked": "已撤銷",
}
PLATFORM_LABELS = {
    "iphone": "iPhone · Chrome",
    "windows": "Windows · Chrome",
    "both": "iPhone + Windows",
}
OPEN_STATUSES = {"pending", "approved", "tailscale_invited", "active"}
MAX_REQUESTS = 1000
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class AccessValidationError(ValueError):
    """A user-visible validation failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, *, field: str, minimum: int, maximum: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if _CONTROL_RE.search(text) or len(text) < minimum or len(text) > maximum:
        raise AccessValidationError(f"{field}格式不正確。")
    return text


def _clean_email(value: object, *, field: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise AccessValidationError(f"{field}格式不正確。")
    return email


def _safe_records(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return []
    rows = payload.get("requests")
    if not isinstance(rows, list):
        return []
    return [copy.deepcopy(row) for row in rows if isinstance(row, dict)]


class AccessRequestStore:
    """Thread-safe, crash-safe local ledger for access applications."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        payload = load_json(
            self.path,
            default={"version": 1, "requests": []},
            expected_type=dict,
        )
        return _safe_records(payload)

    def _save(self, rows: list[dict[str, Any]]) -> None:
        atomic_write_json(
            self.path,
            {"version": 1, "updatedAt": _now(), "requests": rows},
            backup=True,
            private=True,
        )

    def list_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._load()
        return sorted(rows, key=lambda row: str(row.get("createdAt") or ""), reverse=True)

    def create(
        self,
        *,
        display_name: object,
        contact_email: object,
        tailscale_email: object,
        platform: object,
        note: object = "",
    ) -> tuple[dict[str, Any], bool]:
        name = _clean_text(display_name, field="姓名／稱呼", minimum=2, maximum=60)
        contact = _clean_email(contact_email, field="聯絡信箱")
        tailscale = _clean_email(tailscale_email, field="Tailscale 登入信箱")
        platform_key = str(platform or "").strip().lower()
        if platform_key not in PLATFORM_LABELS:
            raise AccessValidationError("請選擇使用裝置。")
        note_text = " ".join(str(note or "").strip().split())
        if _CONTROL_RE.search(note_text) or len(note_text) > 500:
            raise AccessValidationError("補充說明不可超過 500 字。")

        with self._lock:
            rows = self._load()
            for row in rows:
                if (
                    str(row.get("tailscaleEmail") or "").casefold() == tailscale.casefold()
                    and str(row.get("status") or "") in OPEN_STATUSES
                ):
                    return copy.deepcopy(row), False
            if len(rows) >= MAX_REQUESTS:
                raise AccessValidationError("申請資料已達保存上限，請直接聯絡管理者。")
            stamp = datetime.now(timezone.utc)
            request_id = f"ST-{stamp:%Y%m%d}-{secrets.token_hex(3).upper()}"
            row: dict[str, Any] = {
                "id": request_id,
                "createdAt": stamp.isoformat(),
                "updatedAt": stamp.isoformat(),
                "displayName": name,
                "contactEmail": contact,
                "tailscaleEmail": tailscale,
                "platform": platform_key,
                "note": note_text,
                "adminNote": "",
                "status": "pending",
                "history": [{"status": "pending", "at": stamp.isoformat()}],
            }
            rows.append(row)
            self._save(rows)
            return copy.deepcopy(row), True

    def update_status(
        self,
        request_id: object,
        *,
        status: object,
        admin_note: object = "",
    ) -> dict[str, Any]:
        clean_id = str(request_id or "").strip().upper()
        if not re.fullmatch(r"ST-\d{8}-[A-F0-9]{6}", clean_id):
            raise AccessValidationError("申請編號格式不正確。")
        clean_status = str(status or "").strip().lower()
        if clean_status not in VALID_STATUSES:
            raise AccessValidationError("申請狀態不正確。")
        note = " ".join(str(admin_note or "").strip().split())
        if _CONTROL_RE.search(note) or len(note) > 300:
            raise AccessValidationError("管理備註不可超過 300 字。")

        with self._lock:
            rows = self._load()
            for row in rows:
                if str(row.get("id") or "").upper() != clean_id:
                    continue
                now = _now()
                previous = str(row.get("status") or "pending")
                row["status"] = clean_status
                row["adminNote"] = note
                row["updatedAt"] = now
                history = row.get("history")
                if not isinstance(history, list):
                    history = []
                    row["history"] = history
                if previous != clean_status:
                    history.append({"status": clean_status, "at": now})
                row["history"] = history[-24:]
                self._save(rows)
                return copy.deepcopy(row)
        raise AccessValidationError("找不到這筆申請。")


BASE_CSS = r"""
:root{--base:#060c14;--surface:#0b1724;--surface2:#102234;--line:rgba(151,190,219,.18);--text:#e8f2f7;--muted:#9bb0bf;--cyan:#11d2d0;--aqua:#71ece3;--gold:#f5c518;--copper:#c78a4b;--good:#43d9a3;--bad:#e27970;--radius:12px;--mono:"IBM Plex Mono",Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}html,body{min-height:100%;margin:0;background:radial-gradient(circle at 82% -10%,rgba(17,210,208,.11),transparent 30%),radial-gradient(circle at 10% 0,rgba(199,138,75,.09),transparent 28%),var(--base);color:var(--text);font-family:"Noto Sans TC","Microsoft JhengHei UI",sans-serif}body{padding:max(20px,env(safe-area-inset-top)) 16px max(28px,env(safe-area-inset-bottom))}.shell{width:min(1120px,100%);margin:auto}.topline{height:2px;background:linear-gradient(90deg,var(--cyan),transparent 70%);margin-bottom:16px}.nav{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-bottom:16px}.brand{display:flex;gap:11px;align-items:center;color:#fff;text-decoration:none;font-weight:800}.brand-mark{display:grid;place-items:center;width:36px;height:36px;border:1px solid rgba(17,210,208,.4);border-radius:8px;color:var(--cyan);font:800 13px var(--mono);background:#07131f}.navlinks{display:flex;gap:8px;flex-wrap:wrap}.navlinks a,.button{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:9px 13px;border:1px solid var(--line);border-radius:8px;background:rgba(16,34,52,.76);color:var(--text);text-decoration:none;font-weight:700;font-size:13px;cursor:pointer}.navlinks a.primary,.button.primary{border-color:rgba(17,210,208,.45);background:rgba(17,210,208,.12);color:var(--aqua)}:where(a,button,input,select,textarea):focus-visible{outline:2px solid var(--cyan);outline-offset:3px}.hero,.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(145deg,rgba(16,34,52,.91),rgba(7,19,31,.94));box-shadow:0 18px 50px rgba(0,0,0,.28)}.hero{padding:clamp(24px,5vw,48px);position:relative;overflow:hidden}.hero:after{content:"";position:absolute;right:-80px;top:-110px;width:310px;height:310px;border:1px solid rgba(17,210,208,.14);border-radius:50%;box-shadow:0 0 0 34px rgba(17,210,208,.025),0 0 0 72px rgba(17,210,208,.018)}.eyebrow{display:inline-flex;align-items:center;gap:8px;color:var(--aqua);font:700 11px var(--mono);letter-spacing:.12em;text-transform:uppercase}.eyebrow:before{content:"";width:28px;height:2px;background:var(--cyan)}h1{position:relative;z-index:1;margin:12px 0 10px;max-width:760px;font-size:clamp(30px,5vw,54px);line-height:1.14;font-weight:620;letter-spacing:-.025em}.lede{position:relative;z-index:1;max-width:700px;margin:0;color:#b9cad5;font-size:clamp(15px,1.8vw,18px);line-height:1.78}.panel{padding:22px;margin-top:14px}.panel h2{margin:0 0 8px;font-size:clamp(21px,3vw,29px);font-weight:620}.panel h3{margin:0 0 8px;font-size:18px}.panel p,.panel li{font-size:15px;line-height:1.72;color:#b8c8d4}.panel p{margin:7px 0}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;margin-top:14px}.card{grid-column:span 4;border:1px solid var(--line);border-radius:10px;background:rgba(7,19,31,.78);padding:18px;min-width:0}.card.wide{grid-column:span 6}.step-no{display:grid;place-items:center;width:32px;height:32px;border:1px solid rgba(17,210,208,.42);border-radius:8px;background:rgba(17,210,208,.09);color:var(--aqua);font:800 13px var(--mono);margin-bottom:13px}.flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:10px;margin-top:18px}.flow-node{min-height:112px;padding:15px;border:1px solid var(--line);border-radius:10px;background:#07131f}.flow-node strong{display:block;margin:8px 0 4px;font-size:16px}.flow-node small{color:var(--muted);line-height:1.55}.flow-arrow{color:var(--cyan);font:900 22px var(--mono)}.device{height:138px;border:1px solid rgba(113,236,227,.24);border-radius:12px;background:linear-gradient(160deg,#0b1b2b,#06101a);padding:13px;position:relative;overflow:hidden}.device .bar{height:14px;width:66%;border-radius:4px;background:rgba(113,236,227,.16);margin-bottom:11px}.device .screen{height:76px;border:1px solid rgba(151,190,219,.17);border-radius:7px;background:#07131f;padding:9px}.device .signal{height:7px;border-radius:3px;background:linear-gradient(90deg,var(--cyan) 0 72%,rgba(255,255,255,.08) 72%);margin:7px 0}.device .dot{position:absolute;right:14px;top:13px;width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 12px rgba(67,217,163,.65)}.callout{border-left:3px solid var(--copper);padding:12px 14px;background:rgba(199,138,75,.08);color:#e7cfb3;border-radius:0 7px 7px 0}.good{border-left-color:var(--good);background:rgba(67,217,163,.07);color:#c7f5e4}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.button.primary{min-height:46px;padding:11px 17px}.button.gold{border-color:rgba(245,197,24,.45);background:linear-gradient(135deg,#f5c518,#dca10b);color:#07101a}.footer{padding:22px 4px 6px;color:#6f8799;font-size:12px;line-height:1.6}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field{display:flex;flex-direction:column;gap:7px}.field.full{grid-column:1/-1}label{color:#c9d7e0;font-size:13px;font-weight:700}input,select,textarea{width:100%;min-height:46px;border:1px solid rgba(151,190,219,.25);border-radius:8px;background:#06111c;color:#f2f7fa;padding:10px 12px;font:500 16px inherit}textarea{min-height:100px;resize:vertical}input:focus,select:focus,textarea:focus{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(17,210,208,.09);outline:0}.error,.success{margin:14px 0;padding:13px 15px;border-radius:8px;border:1px solid rgba(226,121,112,.45);background:rgba(226,121,112,.09);color:#ffd2ce}.success{border-color:rgba(67,217,163,.42);background:rgba(67,217,163,.08);color:#c9f8e7}.consent{display:flex;gap:10px;align-items:flex-start}.consent input{width:18px;min-height:18px;margin-top:4px}.receipt{font:800 18px var(--mono);color:var(--aqua);letter-spacing:.04em}.metric-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.metric{padding:15px;border:1px solid var(--line);border-radius:9px;background:#07131f}.metric b{display:block;font:800 27px var(--mono);color:#fff}.metric span{font-size:12px;color:var(--muted)}.request-card{border:1px solid var(--line);border-radius:10px;background:#07131f;margin-top:12px;padding:17px}.request-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.request-head h3{margin:0;font-size:18px}.request-id{font:700 12px var(--mono);color:var(--aqua)}.status{display:inline-flex;padding:5px 8px;border:1px solid var(--line);border-radius:7px;font-size:12px;font-weight:800}.status-active{color:var(--good);border-color:rgba(67,217,163,.38);background:rgba(67,217,163,.08)}.status-denied,.status-revoked{color:#f0a39d;border-color:rgba(226,121,112,.4);background:rgba(226,121,112,.08)}.status-pending{color:#f4d675;border-color:rgba(245,197,24,.4);background:rgba(245,197,24,.07)}.detail-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin:15px 0}.detail{min-width:0}.detail span{display:block;font-size:11px;color:#6f8799;margin-bottom:4px}.detail strong{font-size:14px;color:#dbe7ee;overflow-wrap:anywhere}.admin-form{display:grid;grid-template-columns:180px 1fr auto;gap:10px;align-items:end}.admin-form .button{min-width:100px}.empty{padding:28px;text-align:center;color:var(--muted)}code{font-family:var(--mono);color:var(--aqua);overflow-wrap:anywhere}.docs a{color:var(--aqua)}
@media(max-width:760px){body{padding-left:12px;padding-right:12px}.nav{align-items:flex-start}.navlinks{justify-content:flex-end}.hero{padding:26px 20px}.hero:after{opacity:.45}.panel{padding:18px 16px}.card,.card.wide{grid-column:span 12}.flow{grid-template-columns:1fr}.flow-arrow{transform:rotate(90deg);text-align:center}.field-grid{grid-template-columns:1fr}.metric-row{grid-template-columns:1fr 1fr}.detail-grid{grid-template-columns:1fr 1fr}.admin-form{grid-template-columns:1fr}.request-head{flex-direction:column}.navlinks a{padding:8px 10px;font-size:12px}}
@media(max-width:390px){h1{font-size:34px}.metric-row,.detail-grid{grid-template-columns:1fr}.nav{display:block}.navlinks{margin-top:12px;justify-content:flex-start}.panel p,.panel li{font-size:15px}.button{width:100%}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important;animation:none!important}}
"""


def _esc(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


def _page(title: str, content: str, *, owner: bool = False) -> str:
    admin_link = '<a href="/gateway/admin">Owner 後台</a>' if owner else ""
    return f'''<!doctype html><html lang="zh-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_esc(title)}</title><style>{BASE_CSS}</style></head><body><main class="shell">
<div class="topline"></div><nav class="nav"><a class="brand" href="/gateway/login"><span class="brand-mark">ST</span><span>Stock Terminal</span></a>
<div class="navlinks"><a href="/gateway/help">連線教學</a><a href="/gateway/request-access">申請使用權</a>{admin_link}<a class="primary" href="/gateway/login">安全登入</a></div></nav>
{content}<footer class="footer">Private Web ST · Tailscale 私有連線 · 申請不等於自動開通<br>不會在申請資料或管理頁保存 ST 密碼、Tailscale 邀請連結或 API 金鑰。</footer>
</main></body></html>'''


def render_request_page(
    *,
    csrf: str,
    values: dict[str, object] | None = None,
    error: str = "",
    receipt: str = "",
    duplicate: bool = False,
) -> str:
    values = values or {}
    if receipt:
        notice = f'''<div class="success" role="status"><strong>{"已有進行中的申請" if duplicate else "申請已安全送出"}</strong><br>
申請編號：<span class="receipt">{_esc(receipt)}</span><br>申請不會自動取得權限；管理者完成審核、Tailscale 分享與 Reader 密碼交付後才算開通。</div>'''
    elif error:
        notice = f'<div class="error" role="alert">{_esc(error)}</div>'
    else:
        notice = ""
    selected = str(values.get("platform") or "")
    platform_options = "".join(
        f'<option value="{key}"{" selected" if selected == key else ""}>{label}</option>'
        for key, label in PLATFORM_LABELS.items()
    )
    content = f'''<section class="hero"><span class="eyebrow">ACCESS REQUEST · LOCAL REVIEW</span>
<h1>申請 Stock Terminal Reader 使用權</h1><p class="lede">這是 ST 權限申請，不是公開網站註冊。你必須先能透過 Tailscale 看到本頁；送出後仍需由 Owner 人工審核。</p></section>
<section class="panel"><h2>申請前先確認</h2><div class="flow"><div class="flow-node"><span class="step-no">01</span><strong>取得主機分享</strong><small>管理者先用 Tailscale 分享指定 ST 主機。</small></div><span class="flow-arrow">→</span><div class="flow-node"><span class="step-no">02</span><strong>送出 Reader 申請</strong><small>填寫可核對的聯絡與 Tailscale 帳號。</small></div><span class="flow-arrow">→</span><div class="flow-node"><span class="step-no">03</span><strong>人工開通</strong><small>Owner 審核後另行交付 Reader 密碼。</small></div></div>
<p class="callout">如果你目前完全連不到本頁，請先向管理者索取 Tailscale「分享裝置」邀請；ST 不使用 Funnel，也不公開暴露連接埠。</p></section>
<section class="panel"><h2>存取申請</h2><p>資料只存於 ST 主機本機，供 Owner 審核與撤銷追蹤。</p>{notice}
<form method="post" action="/gateway/request-access" autocomplete="on"><input type="hidden" name="csrf" value="{_esc(csrf, quote=True)}">
<div class="field-grid"><div class="field"><label for="display_name">姓名／稱呼</label><input id="display_name" name="display_name" maxlength="60" required autocomplete="name" value="{_esc(values.get('display_name'), quote=True)}"></div>
<div class="field"><label for="contact_email">聯絡信箱</label><input id="contact_email" name="contact_email" type="email" maxlength="254" required autocomplete="email" value="{_esc(values.get('contact_email'), quote=True)}"></div>
<div class="field"><label for="tailscale_email">Tailscale 登入信箱</label><input id="tailscale_email" name="tailscale_email" type="email" maxlength="254" required autocomplete="email" value="{_esc(values.get('tailscale_email'), quote=True)}"></div>
<div class="field"><label for="platform">預計使用裝置</label><select id="platform" name="platform" required><option value="">請選擇</option>{platform_options}</select></div>
<div class="field full"><label for="note">補充說明（選填，最多 500 字）</label><textarea id="note" name="note" maxlength="500" placeholder="例如：主要從 iPhone Chrome 使用">{_esc(values.get('note'))}</textarea></div>
<label class="consent field full"><input type="checkbox" name="consent" value="yes" required><span>我了解申請不等於自動開通，且不得轉傳 Tailscale 邀請或 Reader 密碼。</span></label></div>
<div class="actions"><button class="button gold" type="submit">送出待審核申請</button><a class="button" href="/gateway/help">先看完整圖文教學</a></div></form></section>'''
    return _page("申請 Stock Terminal 使用權", content)


def render_help_page(*, service_url: str) -> str:
    url = _esc(service_url)
    content = f'''<section class="hero"><span class="eyebrow">PRIVATE ACCESS PLAYBOOK</span><h1>手機與 Windows 外部連線圖文教學</h1>
<p class="lede">從 Tailscale 帳號、主機分享、VPN 連線到 ST Reader 登入，一次走完。教學以 iPhone Chrome 與 Windows Chrome 為準。</p>
<div class="actions"><a class="button gold" href="#iphone">iPhone Chrome</a><a class="button primary" href="#windows">Windows Chrome</a><a class="button" href="#owner">Owner 管理流程</a></div></section>
<section class="panel"><h2>先理解兩道門</h2><div class="flow"><div class="flow-node"><span class="step-no">A</span><strong>Tailscale 私網</strong><small>只分享 ST 主機，不把整個網路公開。</small></div><span class="flow-arrow">→</span><div class="flow-node"><span class="step-no">B</span><strong>ST Reader 權限</strong><small>Owner 審核申請，再以另一管道交付密碼。</small></div><span class="flow-arrow">→</span><div class="flow-node"><span class="step-no">C</span><strong>開啟市場終端</strong><small>Chrome 使用完整 HTTPS 網址。</small></div></div><p class="callout">兩道門缺一不可。Tailscale 顯示已連線，不代表 ST Reader 已開通；ST 密碼正確，也不能繞過 Tailscale。</p></section>
<section class="panel" id="account"><span class="eyebrow">STEP 0 · ACCOUNT</span><h2>Tailscale 帳號與 ST 申請</h2><div class="grid"><article class="card"><span class="step-no">01</span><h3>準備登入信箱</h3><p>使用 Google、Microsoft、Apple 或管理者允許的 SSO 帳號登入 Tailscale。申請 ST 時填寫同一個 Tailscale 登入信箱，方便核對。</p></article><article class="card"><span class="step-no">02</span><h3>接受指定主機分享</h3><p>Owner 從 Tailscale Machines 頁分享 ST 主機。只接受你認得的邀請，邀請連結應視同密碼。</p></article><article class="card"><span class="step-no">03</span><h3>送出 ST Reader 申請</h3><p>連上 Tailscale 後開啟「申請使用權」。Owner 在 ST 後台核准後，才會另外提供 Reader 密碼。</p></article></div><div class="actions"><a class="button primary" href="/gateway/request-access">開啟 ST 使用權申請</a><a class="button" href="https://tailscale.com/docs/features/sharing">Tailscale 官方分享說明</a></div></section>
<section class="panel" id="iphone"><span class="eyebrow">IPHONE · CHROME</span><h2>iPhone 第一次連線</h2><div class="grid"><article class="card wide"><div class="device"><span class="dot"></span><div class="bar"></div><div class="screen"><strong>Tailscale</strong><div class="signal"></div><small>VPN · Connected</small></div></div><h3>1. 安裝並允許 VPN</h3><p>從 App Store 安裝 Tailscale，點「Get Started」，允許 iOS 加入 VPN 設定，再用收到分享邀請的帳號登入。</p></article><article class="card wide"><div class="device"><span class="dot"></span><div class="bar"></div><div class="screen"><strong>Chrome</strong><div class="signal"></div><small>{url}</small></div></div><h3>2. 用 Chrome 開完整網址</h3><p>確認 Tailscale 顯示 Connected，再用 Chrome 開 <code>{url}</code>。不要加 18432／18434／18435，也不要改成 HTTP。</p></article><article class="card wide"><span class="step-no">03</span><h3>申請與登入</h3><p>尚未取得 Reader 時先送出申請；收到核准通知後，登入身分選 Reader，輸入管理者透過另一安全管道交付的密碼。</p></article><article class="card wide"><span class="step-no">04</span><h3>日後直接開啟</h3><p>一般 Chrome 分頁會保留簽章登入。只有清除本站 Cookie／網站資料，或管理者輪替密碼時才需要重新登入。</p></article></div><div class="actions"><a class="button" href="https://tailscale.com/docs/install/ios">Tailscale 官方 iOS 安裝說明</a></div></section>
<section class="panel" id="windows"><span class="eyebrow">WINDOWS · CHROME</span><h2>Windows 第一次連線</h2><div class="grid"><article class="card"><span class="step-no">01</span><h3>安裝 Tailscale</h3><p>下載官方 Windows 安裝程式。完成後從系統匣找到 Tailscale 圖示。</p></article><article class="card"><span class="step-no">02</span><h3>登入並接受分享</h3><p>右鍵系統匣圖示選 Log in，用收到分享邀請的帳號登入並接受 ST 主機。</p></article><article class="card"><span class="step-no">03</span><h3>Chrome 開啟 ST</h3><p>確認 Tailscale 已連線，再開 <code>{url}</code>，選 Reader 並輸入 ST 存取密碼。</p></article></div><div class="actions"><a class="button" href="https://tailscale.com/docs/install/windows">Tailscale 官方 Windows 安裝說明</a></div></section>
<section class="panel" id="owner"><span class="eyebrow">OWNER RUNBOOK</span><h2>管理者開通一位 Reader</h2><ol><li>先取得對方的 Tailscale 登入信箱。</li><li>在 Tailscale <b>Machines</b> 頁找到 ST 主機，從動作選單使用 <b>Share</b>，建議以 Email 發出單人邀請。</li><li>對方接受並連線後，請他從 ST 登入頁送出使用權申請。</li><li>Owner 登入 <code>/gateway/admin</code>，核對帳號、裝置與需求，依序標記「已核准 → 已送邀請 → 已開通」。</li><li>Reader 密碼用不同於邀請的安全管道交付；不要貼進後台備註、Email 主旨或截圖。</li></ol><div class="actions"><a class="button primary" href="/gateway/admin">開啟 Owner 後台</a><a class="button" href="https://console.tailscale.com/admin/machines">開啟 Tailscale Machines</a></div><p class="callout good">ST 後台只管理審核狀態，不保存 Tailscale API 金鑰，也不會自動操作你的 tailnet。</p></section>
<section class="panel docs"><span class="eyebrow">TROUBLESHOOTING</span><h2>連不上或黑畫面</h2><div class="grid"><article class="card wide"><h3>完全打不開網址</h3><ul><li>確認邀請已接受，且 Tailscale 帳號正確。</li><li>確認 VPN 為 Connected；切換 Wi-Fi／行動網路後可重新連一次。</li><li>只用完整 <code>https://…ts.net/</code> 網址。</li></ul></article><article class="card wide"><h3>登入後空白</h3><ul><li>關閉該 ST 分頁，重新從完整網址開啟。</li><li>開 <code>/gateway/health</code>，應看到 <code>"ok":true</code>。</li><li>記下發生時間、裝置與 Chrome 版本交給管理者。</li></ul></article></div><p>官方參考：<a href="https://tailscale.com/docs/reference/inviting-vs-sharing">邀請使用者與分享裝置的差異</a>、<a href="https://tailscale.com/docs/features/sharing">分享裝置</a>。</p></section>'''
    return _page("Stock Terminal 外部連線教學", content)


def _format_when(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "—"


def render_admin_page(
    *,
    requests: list[dict[str, Any]],
    csrf: str,
    mode: str,
    instance_id: str,
    notice: str = "",
    error: str = "",
) -> str:
    counts = {status: 0 for status in VALID_STATUSES}
    for row in requests:
        status = str(row.get("status") or "pending")
        if status in counts:
            counts[status] += 1
    cards = []
    for row in requests:
        request_id = _esc(row.get("id"))
        status = str(row.get("status") or "pending")
        options = "".join(
            f'<option value="{key}"{" selected" if key == status else ""}>{label}</option>'
            for key, label in STATUS_LABELS.items()
        )
        note = _esc(row.get("note")) or "—"
        admin_note = _esc(row.get("adminNote"), quote=True)
        cards.append(f'''<article class="request-card"><div class="request-head"><div><div class="request-id">{request_id}</div><h3>{_esc(row.get('displayName'))}</h3></div><span class="status status-{_esc(status)}">{_esc(STATUS_LABELS.get(status, status))}</span></div>
<div class="detail-grid"><div class="detail"><span>聯絡信箱</span><strong>{_esc(row.get('contactEmail'))}</strong></div><div class="detail"><span>Tailscale 帳號</span><strong>{_esc(row.get('tailscaleEmail'))}</strong></div><div class="detail"><span>裝置</span><strong>{_esc(PLATFORM_LABELS.get(str(row.get('platform')), '—'))}</strong></div><div class="detail"><span>申請時間</span><strong>{_esc(_format_when(row.get('createdAt')))}</strong></div><div class="detail"><span>補充說明</span><strong>{note}</strong></div><div class="detail"><span>最後更新</span><strong>{_esc(_format_when(row.get('updatedAt')))}</strong></div></div>
<form class="admin-form" method="post" action="/gateway/admin/action"><input type="hidden" name="csrf" value="{_esc(csrf, quote=True)}"><input type="hidden" name="request_id" value="{request_id}"><div class="field"><label for="status-{request_id}">狀態</label><select id="status-{request_id}" name="status">{options}</select></div><div class="field"><label for="note-{request_id}">管理備註（勿貼密碼／邀請連結）</label><input id="note-{request_id}" name="admin_note" maxlength="300" value="{admin_note}"></div><button class="button primary" type="submit">更新</button></form></article>''')
    feedback = f'<div class="success" role="status">{_esc(notice)}</div>' if notice else f'<div class="error" role="alert">{_esc(error)}</div>' if error else ""
    request_html = "".join(cards) if cards else '<div class="empty">目前沒有申請資料。</div>'
    content = f'''<section class="hero"><span class="eyebrow">OWNER CONTROL · NO SECRETS</span><h1>Private Web 存取管理</h1><p class="lede">集中審核 Reader 申請、追蹤 Tailscale 分享與撤銷狀態。這裡不顯示也不保存 Owner／Reader 密碼。</p></section>
<section class="panel"><div class="request-head"><div><span class="eyebrow">SERVICE STATUS</span><h2>連線與申請概況</h2></div><span class="status status-active">Gateway · {_esc(mode)}</span></div><div class="metric-row"><div class="metric"><b>{counts['pending']}</b><span>待審核</span></div><div class="metric"><b>{counts['approved'] + counts['tailscale_invited']}</b><span>開通處理中</span></div><div class="metric"><b>{counts['active']}</b><span>已開通</span></div><div class="metric"><b>{counts['denied'] + counts['revoked']}</b><span>未核准／已撤銷</span></div></div><p>Instance：<code>{_esc(instance_id or 'local')}</code></p><div class="actions"><a class="button primary" href="https://console.tailscale.com/admin/machines">Tailscale Machines</a><a class="button" href="/gateway/help#owner">開通操作手冊</a><a class="button" href="/">回到 ST</a></div><p class="callout">後台狀態是工作紀錄，不會自動分享或撤銷 Tailscale 裝置。真正的網路權限仍以 Tailscale Machines 為準。</p></section>
<section class="panel"><span class="eyebrow">ACCESS LEDGER</span><h2>申請清單</h2>{feedback}{request_html}</section>'''
    return _page("Stock Terminal Owner 後台", content, owner=True)
