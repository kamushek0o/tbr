# core/tuner_engine.py
import json
import time
import threading
from utils.config import cfg
from utils.helpers import write_log, write_error_log
from core.qb_api import (
    detect_qbittorrent_port, check_qb_api_alive, get_live_torrent_info,
    get_transfer_info, get_qb_preferences, set_qb_preferences
)
from core.tuner_db import (
    ALLOWED_PREFS_KEYS, get_tuner_state, update_tuner_state,
    get_tuner_profiles_map, list_switch_rules, add_tuner_history
)
from core.tuner_telemetry import telemetry_collector
from core.tuner_switcher import auto_switch_engine


def _pct_to_bps(pct, max_chan_bps):
    p = max(0, int(pct or 0))
    if p <= 0 or p >= 100:
        return 0
    return max(1024, int(max_chan_bps * (p / 100.0)))


def _compute_derived_limits(max_up, prof, max_chan_bps, squeezed=False, act_up_val=None, baseline=None):
    mu = max(int(prof.get('max_uploads_min', 4)), min(int(prof.get('max_uploads_max', 150)), int(max_up)))
    if prof.get('per_torrent_up_auto', True):
        pt_up = max(int(prof.get('per_torrent_up_min', 2)), min(int(prof.get('per_torrent_up_max', 40)), int(round(mu * 0.28))))
    else:
        pt_up = int(prof.get('per_torrent_up_max', 15))

    if prof.get('max_connec_auto', True):
        mc = max(int(prof.get('max_connec_min', 16)), min(int(prof.get('max_connec_max', 600)), mu * 4))
    else:
        mc = int(prof.get('max_connec_max', 200))

    pt_con = max(int(prof.get('per_torrent_connec_min', 8)), min(int(prof.get('per_torrent_connec_max', 150)), int(round(mc * 0.22))))

    if squeezed and prof.get('squeeze_enabled'):
        up_lim = _pct_to_bps(prof.get('squeeze_up_pct', 40), max_chan_bps)
        dl_lim = _pct_to_bps(prof.get('squeeze_dl_pct', 40), max_chan_bps)
    else:
        up_lim = _pct_to_bps(prof.get('up_limit_pct', 0), max_chan_bps)
        dl_lim = _pct_to_bps(prof.get('dl_limit_pct', 0), max_chan_bps)

    res = {
        'max_uploads': mu, 'max_uploads_per_torrent': pt_up,
        'max_connec': mc, 'max_connec_per_torrent': pt_con,
        'up_limit': up_lim, 'dl_limit': dl_lim,
    }
    act_mode = prof.get('active_uploads_mode', 'keep')
    if act_mode == 'fixed':
        res['max_active_uploads'] = int(prof.get('active_uploads_min', 10))
    elif act_mode == 'range':
        if act_up_val is not None:
            res['max_active_uploads'] = max(int(prof.get('active_uploads_min', 3)), min(int(prof.get('active_uploads_max', 20)), int(act_up_val)))
        else:
            res['max_active_uploads'] = int(prof.get('active_uploads_max', 15))
    elif baseline and 'max_active_uploads' in baseline:
        res['max_active_uploads'] = int(baseline['max_active_uploads'])
    return res


def _evaluate_guards(prof, tel):
    g = prof.get('guards') or {}
    warn, crit, green = [], False, True

    d = g.get('disk') or {}
    if d.get('enabled'):
        if tel['disk_busy'] >= float(d.get('warn', 80)):
            warn.append(f"Диск {tel['disk_busy']}%")
        if tel['disk_busy'] >= float(d.get('crit', 95)):
            crit = True
        if tel['disk_busy'] > float(d.get('recover', 50)):
            green = False

    c = g.get('cpu') or {}
    if c.get('enabled'):
        if tel['cpu_ext'] >= float(c.get('warn', 70)):
            warn.append(f"Проц {tel['cpu_ext']}%")
        if tel['cpu_ext'] >= 95.0:
            crit = True
        if tel['cpu_ext'] > float(c.get('recover', 45)):
            green = False

    r = g.get('ram') or {}
    if r.get('enabled'):
        if tel['ram_free'] < float(r.get('min_free', 15)):
            warn.append(f"RAM своб. {tel['ram_free']}%")
        if tel['ram_free'] < max(5.0, float(r.get('min_free', 15)) * 0.5):
            crit = True
        if tel['ram_free'] < float(r.get('recover_free', 25)):
            green = False

    n = g.get('net') or {}
    if n.get('enabled'):
        if tel['net_ext_pct'] >= float(n.get('warn_pct', 30)):
            warn.append(f"Сеть {tel['net_ext_pct']}%")
        if tel['net_ext_pct'] > float(n.get('recover_pct', 15)):
            green = False

    return warn, crit, green


class AdaptiveTunerEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._warn_streak = 0
        self._last_step_down_ts = 0.0
        self._last_step_up_ts = 0.0
        self._last_telemetry = {}
        self._last_switch_reason = ''

    def get_live_snapshot(self):
        return {
            'state': get_tuner_state(),
            'telemetry': dict(self._last_telemetry),
            'switch_reason': self._last_switch_reason
        }

    def _capture_baseline_if_needed(self, ip, port, st):
        if st.get('dirty_flag') and st.get('baseline'):
            return st['baseline']
        prefs = get_qb_preferences(ip, port)
        if not prefs:
            return None
        base = {k: int(prefs[k]) for k in ALLOWED_PREFS_KEYS if k in prefs and prefs[k] is not None}
        update_tuner_state(baseline_json=json.dumps(base), dirty_flag=1)
        return base

    def restore_baseline(self, reason='Возврат исходных настроек qB'):
        st = get_tuner_state()
        base = st.get('baseline') or {}
        if not st.get('dirty_flag') or not base:
            update_tuner_state(mode='off', dirty_flag=0, active_rule_id=0, last_reason=reason, current_limits_json='{}')
            return True, 'Исходные настройки qB не требовали отката'

        ip, port = detect_qbittorrent_port(cfg.config)
        if port and check_qb_api_alive(ip, port):
            if set_qb_preferences(ip, port, base):
                update_tuner_state(mode='off', dirty_flag=0, active_rule_id=0, last_reason=reason, current_limits_json=json.dumps(base))
                add_tuner_history('off', 'restore', reason, self._last_telemetry, (st.get('current_limits') or {}).get('max_uploads', 0), base.get('max_uploads', 0))
                write_log('automation', f"Авто-тюнер: {reason}")
                return True, 'Исходные настройки qB восстановлены'
        return False, 'qBittorrent недоступен для восстановления настроек'

    def set_mode(self, new_mode, auto_switch=None, is_manual=True, override_policy=None, clear_override=False):
        with self._lock:
            st = get_tuner_state()
            profiles = get_tuner_profiles_map()
            upd = {}
            if auto_switch is not None:
                upd['auto_switch_enabled'] = 1 if auto_switch else 0
            if clear_override:
                upd['manual_override_until'] = 0
                upd['manual_override_mode'] = ''

            if new_mode == 'off':
                upd.update({'mode': 'off', 'manual_override_until': 0, 'manual_override_mode': '', 'active_rule_id': 0})
                update_tuner_state(**upd)
                return self.restore_baseline('Выключен пользователем')

            if new_mode not in profiles:
                return False, 'Профиль не найден'

            if is_manual and (upd.get('auto_switch_enabled', st.get('auto_switch_enabled'))):
                pol = override_policy or st.get('manual_override_policy') or '2h'
                upd['manual_override_policy'] = pol
                upd['manual_override_mode'] = new_mode
                upd['manual_override_until'] = (time.time() + 7200) if pol == '2h' else 0
                auto_switch_engine.mark_manual_override(st.get('active_rule_id', 0))

            p_obj = profiles[new_mode]
            upd['mode'] = new_mode
            upd['current_limits_json'] = '{}'
            upd['last_reason'] = f"Профиль «{p_obj['icon']} {p_obj['name']}»"
            update_tuner_state(**upd)
            self._warn_streak = 0
            return True, f"Активный профиль: {p_obj['name']}"

    def _apply_if_changed(self, ip, port, cur_limits, new_limits, mode, ev_type, reason):
        if not any(cur_limits.get(k) != v for k, v in new_limits.items()):
            return False
        if set_qb_preferences(ip, port, new_limits):
            old_slots = cur_limits.get('max_uploads', 0)
            new_slots = new_limits.get('max_uploads', 0)
            update_tuner_state(current_limits_json=json.dumps(new_limits), last_action_ts=time.time(), last_reason=reason)
            add_tuner_history(mode, ev_type, reason, self._last_telemetry, old_slots, new_slots)
            write_log('automation', f"Авто-тюнер [{mode}] {ev_type}: {reason} (слоты {old_slots}->{new_slots})")
            return True
        return False

    def _tick(self):
        ip, port = detect_qbittorrent_port(cfg.config)
        qb_up = check_qb_api_alive(ip, port) if port else False
        live = get_live_torrent_info(ip, port) if qb_up else {}
        tr = get_transfer_info(ip, port) if qb_up else {}
        st = get_tuner_state()
        profiles = get_tuner_profiles_map()
        mode = st.get('mode')
        if mode != 'off' and mode not in profiles:
            mode = st.get('default_profile_id') or next(iter(profiles.keys()), 'off')

        prof_obj = profiles.get(mode) or profiles.get(st.get('default_profile_id', 'performance')) or {}
        prof = prof_obj.get('config', {})
        target_disk = prof.get('guards', {}).get('disk', {}).get('target_disk', '')
        cur_slots = int((st.get('current_limits') or {}).get('max_uploads') or (st.get('baseline') or {}).get('max_uploads') or 20)

        tel = telemetry_collector.collect(live, tr, cur_slots, target_disk=target_disk)
        self._last_telemetry = tel

        if not qb_up:
            return
        if st.get('mode') == 'off':
            if st.get('dirty_flag'):
                self.restore_baseline('Восстановление исходных настроек qB')
            return
        if time.time() < cfg.getint('Panic_Active_Until', 0):
            update_tuner_state(last_reason='Пауза: активен Panic Killswitch')
            return

        base = self._capture_baseline_if_needed(ip, port, st)
        if base is None:
            return

        if st.get('auto_switch_enabled'):
            rules = list_switch_rules()
            sw_pid, sw_reason, _, win_rid = auto_switch_engine.evaluate(st, rules, profiles, tel)
            self._last_switch_reason = sw_reason
            if sw_pid in profiles and sw_pid != mode:
                mode = sw_pid
                prof = profiles[mode]['config']
                update_tuner_state(mode=mode, active_rule_id=win_rid, current_limits_json='{}', last_reason=sw_reason)
                add_tuner_history(profiles[mode]['name'], 'auto_switch', sw_reason, tel, cur_slots, cur_slots)
                self._warn_streak = 0
                st['current_limits'] = {}
            elif win_rid != st.get('active_rule_id'):
                update_tuner_state(active_rule_id=win_rid)
        else:
            self._last_switch_reason = ''

        if prof.get('yield_to_turtle', True) and tr.get('use_alt_speed_limits'):
            update_tuner_state(last_reason='Не мешает ручному лимиту скорости в qB')
            return

        cur_limits = st.get('current_limits') or {}
        p_label = profiles.get(mode, {}).get('name', mode)
        if not cur_limits:
            init_lim = _compute_derived_limits(prof.get('max_uploads_start', 25), prof, tel['max_channel_bps'], baseline=base)
            self._apply_if_changed(ip, port, {}, init_lim, p_label, 'start', f"Включён профиль «{p_label}»")
            return

        now = time.time()
        poll_sec = max(2, min(30, int(st.get('poll_interval_sec') or 3)))
        req_streak = 3 if poll_sec <= 4 else 2
        warn_list, is_crit, all_green = _evaluate_guards(prof, tel)
        self._warn_streak = (self._warn_streak + 1) if warn_list else 0

        if self._warn_streak >= req_streak and (now - self._last_step_down_ts) >= 18.0:
            self._last_step_down_ts = now
            old_mu = int(cur_limits.get('max_uploads', prof.get('max_uploads_start', 20)))
            step_d = max(5, int(round(old_mu * 0.2)))
            new_mu = max(int(prof.get('max_uploads_min', 4)), old_mu - step_d)
            act_up = cur_limits.get('max_active_uploads')
            if is_crit and prof.get('active_uploads_mode') == 'range' and act_up is not None:
                act_up = max(int(prof.get('active_uploads_min', 3)), int(act_up) - 2)
            new_lim = _compute_derived_limits(new_mu, prof, tel['max_channel_bps'], squeezed=True, act_up_val=act_up, baseline=base)
            cd = max(20, int(prof.get('cooldown_sec', 150)))
            update_tuner_state(cooldown_until=now + cd)
            self._apply_if_changed(ip, port, cur_limits, new_lim, p_label, 'step_down', f"Защита: {', '.join(warn_list)}")
            return

        if (now - self._last_step_up_ts) >= 90.0 and now >= float(st.get('cooldown_until') or 0):
            if all_green and tel['channel_pct'] < float(prof.get('channel_target_min', 80)) and tel['slots_fill_pct'] >= 75.0:
                self._last_step_up_ts = now
                old_mu = int(cur_limits.get('max_uploads', prof.get('max_uploads_start', 20)))
                step_u = max(1, int(prof.get('step_up_size', 4)))
                new_mu = min(int(prof.get('max_uploads_max', 150)), old_mu + step_u)
                act_up = cur_limits.get('max_active_uploads')
                if prof.get('active_uploads_mode') == 'range' and act_up is not None:
                    act_up = min(int(prof.get('active_uploads_max', 15)), int(act_up) + 1)
                new_lim = _compute_derived_limits(new_mu, prof, tel['max_channel_bps'], squeezed=False, act_up_val=act_up, baseline=base)
                self._apply_if_changed(ip, port, cur_limits, new_lim, p_label, 'step_up', f"Разгон (канал {tel['channel_pct']}%, пиры {tel['slots_fill_pct']}%)")

    def start(self):
        if self._running:
            return
        self._running = True

        def loop():
            time.sleep(3)
            st = get_tuner_state()
            if st.get('dirty_flag') and st.get('mode') == 'off':
                self.restore_baseline('Восстановление исходных настроек при старте tbr')
            while self._running:
                try:
                    self._tick()
                except Exception as e:
                    write_error_log("AdaptiveTunerEngine tick", e)
                poll_sec = max(2, min(30, int(get_tuner_state().get('poll_interval_sec') or 3)))
                for _ in range(poll_sec):
                    if not self._running:
                        return
                    time.sleep(1)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_and_restore(self):
        self._running = False
        st = get_tuner_state()
        if st.get('dirty_flag'):
            self.restore_baseline('Штатный откат при выходе tbr')


tuner_engine = AdaptiveTunerEngine()
