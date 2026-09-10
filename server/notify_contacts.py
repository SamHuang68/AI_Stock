#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email 聯絡人通訊錄（僅 name+email，不含 SMTP 密鑰）。

檔案：data/notify_contacts.json（gitignore）。寄信仍走既有 POST /report-email。
"""
from __future__ import annotations

import html
import os
import re
import uuid
from typing import Any

try:
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
except ImportError:
    from atomic_store import StoreCorruptError, atomic_write_json, load_json

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTACTS_FILE = os.path.join(_BASE, 'data', 'notify_contacts.json')
MAX_CONTACTS = 40
MAX_RECIPIENTS = 20
MAX_NAME = 40
MAX_HTML = 400_000
_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
_ID_RE = re.compile(r'^c_[A-Za-z0-9]{6,24}$')


def is_email(value: str) -> bool:
    email = str(value or '').strip()
    return 3 < len(email) <= 254 and bool(_EMAIL_RE.fullmatch(email))


def wrap_text_html(text: str) -> str:
    body = html.escape(str(text or ''), quote=False)
    return (
        '<pre style="font-family:\'Noto Sans TC\',sans-serif;white-space:pre-wrap;'
        'line-height:1.65;font-size:14px">' + body + '</pre>'
    )


def mint_id() -> str:
    return 'c_' + uuid.uuid4().hex[:10]


def parse_recipients(value: Any) -> tuple[list[str], list[str]]:
    raw: list[str] = []
    if isinstance(value, str):
        raw = [part.strip() for part in value.replace(';', ',').split(',')]
    elif isinstance(value, (list, tuple)):
        raw = [str(part or '').strip() for part in value]
    else:
        return [], ['需有效收件者 email']
    emails: list[str] = []
    seen: set[str] = set()
    errors: list[str] = []
    for item in raw:
        if not item:
            continue
        if not is_email(item):
            errors.append('無效信箱：' + item[:80])
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(item)
        if len(emails) >= MAX_RECIPIENTS:
            break
    if not emails and not errors:
        errors.append('需有效收件者 email')
    return emails, errors


def sanitize(contacts: Any) -> tuple[list[dict[str, str]], list[str]]:
    if contacts is None:
        contacts = []
    if not isinstance(contacts, list):
        return [], ['contacts 必須是陣列']
    if len(contacts) > MAX_CONTACTS:
        return [], ['聯絡人最多 ' + str(MAX_CONTACTS) + ' 位']
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for idx, raw in enumerate(contacts):
        if not isinstance(raw, dict):
            errors.append('第 ' + str(idx + 1) + ' 筆格式錯誤')
            continue
        email = str(raw.get('email') or '').strip()
        if not is_email(email):
            errors.append('第 ' + str(idx + 1) + ' 筆信箱無效')
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        name = str(raw.get('name') or '').strip()[:MAX_NAME]
        if not name:
            name = email.split('@', 1)[0][:MAX_NAME]
        cid = str(raw.get('id') or '').strip()
        if not _ID_RE.fullmatch(cid):
            cid = mint_id()
        cleaned.append({'id': cid, 'name': name, 'email': email})
    return cleaned, errors


def load_contacts(path: str | None = None) -> list[dict[str, str]]:
    target = path or CONTACTS_FILE
    try:
        data = load_json(target, default={'contacts': []}, expected_type=dict)
    except StoreCorruptError:
        return []
    cleaned, _errors = sanitize((data or {}).get('contacts'))
    return cleaned


def save_contacts(contacts: list[dict[str, str]], path: str | None = None) -> list[dict[str, str]]:
    cleaned, errors = sanitize(contacts)
    if errors:
        raise ValueError('; '.join(errors))
    atomic_write_json(
        path or CONTACTS_FILE,
        {'contacts': cleaned},
        backup=True,
        private=True,
        indent=2,
    )
    return cleaned


def normalize_report_payload(body: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(body, dict):
        return {}, ['body 必須是物件']
    recips, errors = parse_recipients(body.get('to'))
    subject = str(body.get('subject') or 'Stock Terminal AI 報告').strip()[:180]
    if not subject:
        subject = 'Stock Terminal AI 報告'
    html_body = str(body.get('html') or '')
    text = str(body.get('text') or '')
    if not html_body:
        if not text.strip():
            errors.append('html 或 text 必填')
        else:
            html_body = wrap_text_html(text)
    if len(html_body) > MAX_HTML:
        errors.append('內容過長')
    payload = {'to': recips, 'subject': subject, 'html': html_body}
    return payload, errors
