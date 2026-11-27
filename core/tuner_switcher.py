# core/tuner_switcher.py
import time
import datetime
from core.tuner_telemetry import telemetry_collector


def _parse_hhmm_min(val):
    try:
        p = str(val or '00:00').strip().split(':')
        return int(p[0]) * 60 + int(p[1])
    except Exception:
        return 0


def _match_schedule_block(sched, now_dt):
    days = sched.get('days', [0, 1, 2, 3, 4, 5, 6])
    sh = _parse_hhmm_min(sched.get('start', '00:00'))
    eh = _parse_hhmm_min(sched.get('end', '00:00'))
    if sh == eh:
        return False
    cur_min = now_dt.hour * 60 + now_dt.minute
    wd = now_dt.weekday()
    if sh < eh:
        return (wd in days) and (sh <= cur_min < eh)
    return ((wd in days) and cur_min >= sh) or ((((wd - 1) % 7) in days) and cur_min < eh)


def _match_rule_instant(rule_cfg, running_map, telemetry, now_dt):
    """Оценка условий правила прямо сейчас: (hit_enter, all_recovered, reason_detail)."""
    pr = rule_cfg.get('processes') or {}
    sc = rule_cfg.get('schedule') or {}
    ex = rule_cfg.get('external_load') or {}

    has_any = False
    reasons = []

    if pr.get('enabled'):
        watched = [str(x).strip().lower() for x in (pr.get('names') or []) if str(x).strip()]
        if not watched:
            return False, True, ''
        has_any = True
        hit_proc = next((running_map[w] for w in watched if w in running_map), None)
        if not hit_proc:
            return False, True, ''
        reasons.append(f"запущен {hit_proc}")

    if sc.get('enabled'):
        has_any = True
        if not _match_schedule_block(sc, now_dt):
            return False, True, ''
        reasons.append(f"окно {sc.get('start')}–{sc.get('end')}")

    if ex.get('enabled'):
        checks_any = False
        hit_warn = False
        all_rec = True
        ex_parts = []

        if ex.get('cpu_enabled'):
            checks_any = True
            if telemetry['cpu_ext'] >= float(ex.get('cpu_warn', 45)):
                hit_warn = True
                ex_parts.append(f"CPU {telemetry['cpu_ext']}%")
            if telemetry['cpu_ext'] > float(ex.get('cpu_recover', 25)):
                all_rec = False

        if ex.get('net_enabled'):
            checks_any = True
            if telemetry['net_ext_pct'] >= float(ex.get('net_warn_pct', 25)):
                hit_warn = True
                ex_parts.append(f"Сеть {telemetry['net_ext_pct']}%")
            if telemetry['net_ext_pct'] > float(ex.get('net_recover_pct', 12)):
                all_rec = False

        if ex.get('ram_enabled'):
            checks_any = True
            if telemetry['ram_free'] < float(ex.get('ram_min_free', 15)):
                hit_warn = True
                ex_parts.append(f"RAM {telemetry['ram_free']}%")
            if telemetry['ram_free'] < float(ex.get('ram_recover_free', 25)):
                all_rec = False

        if ex.get('disk_enabled'):
            checks_any = True
            if telemetry['disk_busy'] >= float(ex.get('disk_warn', 70)):
                hit_warn = True
                ex_parts.append(f"Диск {telemetry['disk_busy']}%")
            if telemetry['disk_busy'] > float(ex.get('disk_recover', 45)):
                all_rec = False

        if not checks_any:
            return False, True, ''
        has_any = True
        if not hit_warn:
            return False, all_rec, ''
        reasons.append(', '.join(ex_parts))

    if not has_any:
        return False, True, ''
    return True, False, ' + '.join(reasons)


class AutoSwitchEngine:
    def __init__(self):
        self._rule_states = {}  # { rule_id: {seen_since, clear_since, active, detail} }
        self._override_baseline_rule_id = None

    def mark_manual_override(self, current_active_rule_id):
        self._override_baseline_rule_id = current_active_rule_id or 0

    def evaluate(self, state, rules, profiles_map, telemetry):
        now = time.time()
        dt_now = datetime.datetime.now()

        need_procs = any((r.get('config') or {}).get('processes', {}).get('enabled') for r in rules if r.get('enabled'))
        running_map = telemetry_collector.get_running_exe_map() if need_procs else {}

        active_ids = set()
        winner = None

        for r in rules:
            rid = r['id']
            if not r.get('enabled') or r.get('target_profile_id') not in profiles_map:
                self._rule_states.pop(rid, None)
                continue

            active_ids.add(rid)
            rst = self._rule_states.setdefault(rid, {'seen_since': None, 'clear_since': None, 'active': False, 'detail': ''})
            rcfg = r.get('config') or {}
            hit, rec_ok, detail = _match_rule_instant(rcfg, running_map, telemetry, dt_now)
            enter_sec = max(2, int(rcfg.get('enter_sec', 10) or 10))
            exit_sec = max(5, int(rcfg.get('exit_sec', 180) or 180))

            if hit:
                rst['clear_since'] = None
                rst['detail'] = detail
                if rst['seen_since'] is None:
                    rst['seen_since'] = now
                if (now - rst['seen_since']) >= enter_sec:
                    rst['active'] = True
            else:
                rst['seen_since'] = None
                if rst['active']:
                    if rec_ok:
                        if rst['clear_since'] is None:
                            rst['clear_since'] = now
                        if (now - rst['clear_since']) >= exit_sec:
                            rst['active'] = False
                            rst['detail'] = ''
                    else:
                        rst['clear_since'] = None

            if rst['active'] and winner is None:
                winner = (r, rst['detail'])

        for stale in list(self._rule_states.keys()):
            if stale not in active_ids:
                del self._rule_states[stale]

        winner_rule_id = winner[0]['id'] if winner else 0

        # Приоритет 1: Ручной выбор пользователя
        ov_mode = state.get('manual_override_mode') or ''
        ov_until = float(state.get('manual_override_until') or 0)
        ov_pol = state.get('manual_override_policy') or '2h'
        override_active = False

        if ov_mode in profiles_map:
            if ov_pol == '2h' and now < ov_until:
                override_active = True
            elif ov_pol == 'until_window' and winner_rule_id == (self._override_baseline_rule_id or 0):
                override_active = True
            elif ov_pol == 'until_rule' and (winner_rule_id == 0 or winner_rule_id == (self._override_baseline_rule_id or 0)):
                override_active = True

        if override_active:
            p_obj = profiles_map[ov_mode]
            if ov_pol == '2h':
                left_m = max(1, int((ov_until - now) // 60))
                lbl = f"Ручной выбор: {p_obj['icon']} {p_obj['name']} (ещё {left_m}м)"
            else:
                lbl = f"Ручной выбор: {p_obj['icon']} {p_obj['name']}"
            return ov_mode, lbl, True, winner_rule_id

        # Приоритет 2: Первое сверху сработавшее правило
        if winner:
            r_win, det = winner
            pid = r_win['target_profile_id']
            p_obj = profiles_map[pid]
            reason = f"Авто → {p_obj['icon']} {p_obj['name']} ({r_win['name']}: {det})"
            return pid, reason, False, r_win['id']

        # Приоритет 3: Профиль по умолчанию
        def_id = state.get('default_profile_id') or 'performance'
        if def_id not in profiles_map:
            def_id = next(iter(profiles_map.keys()), 'performance')
        p_def = profiles_map[def_id]
        return def_id, f"Авто → {p_def['icon']} {p_def['name']} (по умолчанию)", False, 0


auto_switch_engine = AutoSwitchEngine()
