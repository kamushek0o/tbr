# core/history_migrations.py
import os
import re
import csv
import json
import datetime
from utils.helpers import LOG_FOLDER, write_log, write_error_log

_DATE_COMMENT_RE = re.compile(r'^#\s*Дата выгрузки:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')
_FNAME_DATE_RE = re.compile(r'summary_hourly_(\d{8})_(\d{4})\.csv$', re.IGNORECASE)


def migrate_json_if_needed(get_conn_fn, old_json_file):
    if not os.path.exists(old_json_file):
        return
    try:
        with get_conn_fn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM snapshots")
            if cur.fetchone()[0] > 0:
                return

            write_log("summary", "Обнаружен старый summary_history.json. Начинаем миграцию в SQLite...")
            with open(old_json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list):
                for s in data:
                    ts = s.get('timestamp', 0)
                    dt = s.get('datetime', '')
                    tot_up = s.get('total_uploaded', 0)
                    tot_sz = s.get('total_size', 0)
                    count = s.get('count', 0)
                    torrents = s.get('torrents', {})

                    cur.execute(
                        "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count) VALUES (?, ?, ?, ?, ?)",
                        (ts, dt, tot_up, tot_sz, count)
                    )
                    snap_id = cur.lastrowid
                    if torrents and isinstance(torrents, dict):
                        rows = [(snap_id, str(h).lower(), int(up)) for h, up in torrents.items()]
                        cur.executemany(
                            "INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)",
                            rows
                        )

            conn.commit()
            write_log("summary", "Миграция JSON в SQLite успешно завершена.")

        bak_file = old_json_file + ".migrated"
        if not os.path.exists(bak_file):
            os.rename(old_json_file, bak_file)
    except Exception as e:
        write_error_log("Ошибка миграции summary_history.json в SQLite", e)


def migrate_old_csvs_if_needed(get_conn_fn, auto_folder):
    candidates = []
    for folder in (LOG_FOLDER, auto_folder):
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            low = fname.lower()
            if low.startswith('summary_hourly_') and low.endswith('.csv'):
                candidates.append(os.path.join(folder, fname))

    if not candidates:
        return

    imported = 0
    try:
        with get_conn_fn() as conn:
            cur = conn.cursor()
            for path in sorted(candidates):
                try:
                    with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        lines = f.readlines()

                    snap_dt_str = None
                    data_lines = []
                    for line in lines:
                        if line.startswith('#'):
                            m = _DATE_COMMENT_RE.match(line.strip())
                            if m:
                                snap_dt_str = m.group(1)
                        elif line.strip():
                            data_lines.append(line)

                    if not data_lines:
                        continue

                    if snap_dt_str:
                        snap_ts = datetime.datetime.strptime(snap_dt_str, '%Y-%m-%d %H:%M:%S').timestamp()
                    else:
                        mf = _FNAME_DATE_RE.search(os.path.basename(path))
                        if mf:
                            dt_obj = datetime.datetime.strptime(mf.group(1) + mf.group(2), '%Y%m%d%H%M')
                            snap_ts = dt_obj.timestamp()
                            snap_dt_str = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            snap_ts = os.path.getmtime(path)
                            snap_dt_str = datetime.datetime.fromtimestamp(snap_ts).strftime('%Y-%m-%d %H:%M:%S')

                    cur.execute("SELECT 1 FROM snapshots WHERE ABS(timestamp - ?) < 180 LIMIT 1", (snap_ts,))
                    if cur.fetchone():
                        continue

                    reader = csv.DictReader(data_lines, delimiter=';')
                    tor_rows = []
                    tot_up = 0
                    tot_sz = 0
                    for row in reader:
                        h_id = (row.get('Хэш') or row.get('hash_id') or '').strip().lstrip("'").lower()
                        if not h_id:
                            continue
                        try:
                            up = int(float(row.get('Отдано (байт)') or row.get('uploaded') or 0))
                            sz = int(float(row.get('Размер (байт)') or row.get('size') or 0))
                        except (ValueError, TypeError):
                            continue
                        tot_up += up
                        tot_sz += sz
                        tor_rows.append((h_id, up))

                    if not tor_rows:
                        continue

                    cur.execute(
                        "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count) VALUES (?, ?, ?, ?, ?)",
                        (snap_ts, snap_dt_str, tot_up, tot_sz, len(tor_rows))
                    )
                    snap_id = cur.lastrowid
                    cur.executemany(
                        "INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)",
                        [(snap_id, h, u) for h, u in tor_rows]
                    )
                    imported += 1
                except Exception as e:
                    write_error_log(f"Импорт старого CSV {os.path.basename(path)}", e)

            if imported > 0:
                conn.commit()
                write_log("summary", f"Импортировано старых почасовых CSV-снимков в SQLite: {imported}")
    except Exception as e:
        write_error_log("Ошибка _migrate_old_csvs_if_needed", e)