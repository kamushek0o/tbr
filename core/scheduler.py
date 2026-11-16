# core/scheduler.py
import time
import datetime
import threading
from utils.config import cfg
from utils.helpers import write_error_log

ALLOWED_INTERVALS = (
    1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60,
    120, 180, 240, 360, 480, 720, 1440
)
MIN_DELTA_SEC = 60


def normalize_interval(val):
    try:
        iv = int(val)
        if iv in ALLOWED_INTERVALS:
            return iv
    except (ValueError, TypeError):
        pass
    return 60


def compute_next_slot(now_ts, interval_min):
    dt = datetime.datetime.fromtimestamp(now_ts)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    t_now = (dt - midnight).total_seconds()
    period = 60 * interval_min
    slot_sec = (int(t_now // period) + 1) * period
    next_dt = midnight + datetime.timedelta(seconds=slot_sec)
    return next_dt.timestamp()


class SnapshotScheduler:
    def __init__(self, db, on_record_fn, on_csv_fn):
        self.db = db
        self.on_record_fn = on_record_fn
        self.on_csv_fn = on_csv_fn
        self._running = False
        self._thread = None
        self._wake_event = threading.Event()
        self._last_csv_hour = None
        self._last_downsample_ts = 0.0

    def notify_interval_changed(self):
        self._wake_event.set()

    def _should_export_csv(self, now_dt, interval_min):
        if interval_min >= 60:
            return True
        cur_hour_key = now_dt.strftime('%Y%m%d_%H')
        if self._last_csv_hour != cur_hour_key:
            self._last_csv_hour = cur_hour_key
            return True
        return False

    def _maybe_downsample(self, now_ts):
        if now_ts - self._last_downsample_ts >= 21600:  # раз в 6 часов
            self._last_downsample_ts = now_ts
            self.db.downsample_old_snapshots()

    def start(self, get_summaries_fn):
        if self._running:
            return
        self._running = True

        def loop():
            try:
                self.db.downsample_old_snapshots()
                self._last_downsample_ts = time.time()
                sums = get_summaries_fn()
                if sums:
                    recorded = self.on_record_fn(sums, min_delta_sec=MIN_DELTA_SEC)
                    if recorded or self._last_csv_hour is None:
                        self._last_csv_hour = datetime.datetime.now().strftime('%Y%m%d_%H')
                        self.on_csv_fn(sums)
            except Exception as e:
                write_error_log("Ошибка начального замера планировщика", e)

            cur_interval = normalize_interval(cfg.getint('Snapshot_Interval_Min', 60))
            t_next = compute_next_slot(time.time(), cur_interval)

            while self._running:
                now_ts = time.time()
                new_interval = normalize_interval(cfg.getint('Snapshot_Interval_Min', 60))
                if new_interval != cur_interval:
                    cur_interval = new_interval
                    t_next = compute_next_slot(now_ts, cur_interval)

                if now_ts >= t_next:
                    try:
                        sums = get_summaries_fn()
                        if sums:
                            self.on_record_fn(sums, min_delta_sec=MIN_DELTA_SEC)
                            if self._should_export_csv(datetime.datetime.now(), cur_interval):
                                self.on_csv_fn(sums)
                        self._maybe_downsample(time.time())
                    except Exception as e:
                        write_error_log("Ошибка циклического замера планировщика", e)

                    # Пересчёт строго от текущего времени (без догоняющих вызовов после сна)
                    t_next = compute_next_slot(time.time(), cur_interval)
                    continue

                wait_sec = max(0.5, min(60.0, t_next - now_ts))
                self._wake_event.wait(timeout=wait_sec)
                self._wake_event.clear()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def flush_on_exit(self, get_summaries_fn):
        self._running = False
        self._wake_event.set()
        try:
            last_ts = self.db.get_last_snapshot_ts()
            now_ts = time.time()
            if last_ts is None or (now_ts - last_ts) >= MIN_DELTA_SEC:
                sums = get_summaries_fn()
                if sums:
                    self.on_record_fn(sums, min_delta_sec=MIN_DELTA_SEC)
        except Exception as e:
            write_error_log("Ошибка финального среза при выходе", e)