# core/tuner_switcher.py
import time
import datetime
from core.tuner_telemetry import list_running_processes


def _parse_hhmm_min(val):
    try:
        p = str(val or '00:00').strip().split(':')
        return int(p[0]) * 60 + int(p[1])
    except Exception:
        return 0


def _match_schedule(schedules, now_dt=None):
    dt = now_dt or datetime.datetime.now()
    cur_min = dt.hour * 60 + dt.minute
    wd = dt.weekday()
    for idx, s in enumerate(schedules or []):
        if not isinstance(s, dict):
            continue
        days = s.get('days', [0, 1, 2, 3, 4, 5, 6])
        sh = _parse_hhmm_min(s.get('start', '00:00'))
        eh = _parse_hhmm_min(s.get('end', '00:00'))
        mode = s.get('mode', 'performance')
        if mode not in ('performance', 'comfort') or sh == eh:
            continue
        hit = False
        if sh < eh:
            hit = (wd in days) and (sh <= cur_min < eh)
        else:
            hit = ((wd in days) and cur_min >= sh) or ((((wd - 1) % 7) in days) and cur_min < eh)
        if hit:
            return mode, f"Расписание ({s.get('start')}–{s.get('end')})", idx
    return None, '', -1


class AutoSwitchEngine:
    def __init__(self):
        self._proc_seen_since = None
        self._proc_clear_since = None
        self._proc_active = False
        self._proc_matched_name = ''

        self._ext_enter_since = None
        self._ext_clear_since = None
        self._ext_active = False
        self._ext_reason = ''
        self._last_sched_idx = -1

    def evaluate(self, state, rules, telemetry):
        now = time.time()
        dt_now = datetime.datetime.now()

        # 1. Проверка процессов (нужна и для приоритета 2, и для политики override 'until_process_exit')
        proc_cfg = rules.get('processes') or {}
        watched = {str(x).strip().lower() for x in (proc_cfg.get('names') or []) if str(x).strip()}
        matched_proc = ''
        if proc_cfg.get('enabled') and watched:
            running_low = {n.lower(): n for n in list_running_processes()}
            for w in watched:
                if w in running_low:
                    matched_proc = running_low[w]
                    break

        if matched_proc:
            self._proc_clear_since = None
            self._proc_matched_name = matched_proc
            if self._proc_seen_since is None:
                self._proc_seen_since = now
            enter_sec = max(5, int(proc_cfg.get('enter_sec', 15) or 15))
            if (now - self._proc_seen_since) >= enter_sec:
                self._proc_active = True
        else:
            self._proc_seen_since = None
            if self._proc_active:
                if self._proc_clear_since is None:
                    self._proc_clear_since = now
                exit_sec = max(10, int(proc_cfg.get('exit_sec', 180) or 180))
                if (now - self._proc_clear_since) >= exit_sec:
                    self._proc_active = False
                    self._proc_matched_name = ''

        # 2. Проверка внешней нагрузки
        ext_cfg = rules.get('external_load') or {}
        if ext_cfg.get('enabled'):
            hit_warn = (
                telemetry['cpu_ext'] >= float(ext_cfg.get('cpu_warn', 45)) or
                telemetry['net_ext_pct'] >= float(ext_cfg.get('net_warn_pct', 25)) or
                telemetry['ram_free'] < float(ext_cfg.get('ram_min_free', 15))
            )
            all_rec = (
                telemetry['cpu_ext'] <= float(ext_cfg.get('cpu_recover', 25)) and
                telemetry['net_ext_pct'] <= float(ext_cfg.get('net_recover_pct', 12)) and
                telemetry['ram_free'] >= float(ext_cfg.get('ram_recover_free', 25))
            )
            if hit_warn:
                self._ext_clear_since = None
                if self._ext_enter_since is None:
                    self._ext_enter_since = now
                if (now - self._ext_enter_since) >= max(5, int(ext_cfg.get('enter_sec', 30) or 30)):
                    self._ext_active = True
                    self._ext_reason = f"Внешняя нагрузка (CPU {telemetry['cpu_ext']}%, Сеть {telemetry['net_ext_pct']}%)"
            else:
                self._ext_enter_since = None
                if self._ext_active and all_rec:
                    if self._ext_clear_since is None:
                        self._ext_clear_since = now
                    if (now - self._ext_clear_since) >= max(10, int(ext_cfg.get('exit_sec', 300) or 300)):
                        self._ext_active = False
                        self._ext_reason = ''
                elif self._ext_active and not all_rec:
                    self._ext_clear_since = None
        else:
            self._ext_active = False

        # 3. Расписание
        sched_mode, sched_reason, sched_idx = _match_schedule(rules.get('schedules'), dt_now)

        # 4. Приоритет 1: Ручное переопределение (Manual Override)
        ov_mode = state.get('manual_override_mode') or ''
        ov_until = float(state.get('manual_override_until') or 0)
        ov_policy = state.get('manual_override_policy') or '2h'
        override_active = False
        if ov_mode in ('performance', 'comfort'):
            if ov_policy == '2h' and now < ov_until:
                override_active = True
            elif ov_policy == 'until_schedule' and sched_idx == self._last_sched_idx:
                override_active = True
            elif ov_policy == 'until_process_exit' and self._proc_active:
                override_active = True

        self._last_sched_idx = sched_idx
        if override_active:
            left_m = max(1, int((ov_until - now) // 60)) if ov_policy == '2h' else 0
            lbl = f"Ручной режим ({left_m}м)" if ov_policy == '2h' else "Ручной режим (Override)"
            return ov_mode, lbl, True

        # 5. Приоритет 2..5
        if self._proc_active:
            t_m = proc_cfg.get('target_mode', 'comfort')
            return t_m, f"Авто → {t_m} (процесс {self._proc_matched_name})", False
        if self._ext_active:
            t_m = ext_cfg.get('target_mode', 'comfort')
            return t_m, f"Авто → {t_m} ({self._ext_reason})", False
        if sched_mode:
            return sched_mode, f"Авто → {sched_mode} ({sched_reason})", False

        def_m = rules.get('default_mode', 'performance')
        return def_m, f"Авто → {def_m} (по умолчанию)", False


auto_switch_engine = AutoSwitchEngine()