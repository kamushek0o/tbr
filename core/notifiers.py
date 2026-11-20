# core/notifiers.py
import json
import html
import urllib.request
from utils.config import cfg
from utils.helpers import write_error_log


def send_telegram(text_html):
    token = cfg.get('TG_Bot_Token', '').strip()
    chat_id = cfg.get('TG_Chat_ID', '').strip()
    if not token or not chat_id:
        return False, "Не задан токен или Chat ID"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        'chat_id': chat_id,
        'text': text_html,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.getcode() == 200, "Telegram: OK"
    except Exception as e:
        write_error_log("Telegram send error", e)
        return False, f"Telegram: {e}"


def send_discord(text_md):
    webhook = cfg.get('Discord_Webhook', '').strip()
    if not webhook:
        return False, "Не задан Discord Webhook"

    payload = json.dumps({'content': text_md[:1900]}).encode('utf-8')
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={'Content-Type': 'application/json', 'User-Agent': 'tbr-pro/3.2'}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.getcode() in (200, 204), "Discord: OK"
    except Exception as e:
        write_error_log("Discord send error", e)
        return False, f"Discord: {e}"


def _deliver_direct(title, lines):
    tg_msg = f"<b>{html.escape(title)}</b>\n" + "\n".join(html.escape(l) for l in lines)
    dc_msg = f"**{title}**\n" + "\n".join(lines)
    results = []
    if cfg.get('TG_Bot_Token', '').strip() and cfg.get('TG_Chat_ID', '').strip():
        _, res_tg = send_telegram(tg_msg)
        results.append(res_tg)
    if cfg.get('Discord_Webhook', '').strip():
        _, res_dc = send_discord(dc_msg)
        results.append(res_dc)
    return results


def notify_all(title, lines, critical=False, bundle=False):
    if not critical:
        try:
            from core.dnd_digest import is_dnd_active_now, queue_dnd_message
            if is_dnd_active_now():
                queue_dnd_message(title, lines)
                return ["DND: отложено в тихий час"]
        except Exception:
            pass
        if bundle or cfg.getboolean('Alert_Bundler_Enabled', True):
            try:
                from core.webhooks_bundler import queue_bundled_alert
                queue_bundled_alert(title, lines, _deliver_direct)
                return ["Bundled (45s)"]
            except Exception:
                pass

    return _deliver_direct(title, lines)


def test_notifications():
    has_tg = bool(cfg.get('TG_Bot_Token', '').strip() and cfg.get('TG_Chat_ID', '').strip())
    has_dc = bool(cfg.get('Discord_Webhook', '').strip())
    if not has_tg and not has_dc:
        return False, ["Не настроен ни Telegram, ни Discord."]
    res = notify_all("⚡ tbr PRO — Тест уведомлений", ["Связь настроена! Бот готов присылать отчёты."], critical=True)
    return True, res