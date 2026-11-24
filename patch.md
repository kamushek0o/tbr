По кайфу, запрос правильный — на мобиле и в PWA плотные цифровые панели без подписей быстро превращаются в ребус со стрелочками. 

### План
1. `web/templates/partials/tab_tuner.html` — переверстываем панель тюнера: добавляем микро-лейблы над каждым числовым полем («Тревога %», «Крит. %», «Возврат %», «От %», «До %», «Up %», «DL %», «Min», «Max»), запрещаем перенос заголовков (`white-space: nowrap`) и прячем второстепенные параметры в нативный аккордеон `<details>`.
2. `web/static/style.css` — добавляем стили для мини-полей `.tuner-field`, аккордеона `<details class="tuner-details">`, анимации выключения `.is-disabled`, убираем наезд стрелок спиннеров на цифры и настраиваем адаптивный перенос сетки для PWA/смартфонов.
3. `web/static/tuner_ui.js` — внедряем функцию `syncTunerDisabledStates()`, которая на лету вешает `disabled` и уводит в полупрозрачность поля отключённых ограничителей, «Ужимания», «Авто 28%», «Авто ×4» и `max_active_uploads: keep`.

---

#### `web/templates/partials/tab_tuner.html`
```html
<!-- Адаптивный авто-тюнер qBittorrent (ТЗ #58) -->
<div class="card admin-only" id="tuner-main-card">
    <div class="row-between mb-8">
        <div class="row-gap" style="flex-wrap:wrap;">
            <div class="card-title" style="margin:0; white-space:nowrap;">🎛️ АВТО-ТЮНЕР qB</div>
            <span id="tuner-reason-badge" class="badge badge-pause">Выключен</span>
            <button id="tuner-btn-clear-ov" class="btn btn-secondary btn-xs hidden" onclick="clearTunerOverride()">🔄 Вернуть авто</button>
        </div>
        <div class="row-gap" style="flex-wrap:wrap;">
            <button id="tuner-btn-off" class="btn btn-secondary btn-xs" onclick="setTunerMode('off')">Выкл</button>
            <button id="tuner-btn-comfort" class="btn btn-secondary btn-xs" onclick="setTunerMode('comfort')">🛋️ Комфорт</button>
            <button id="tuner-btn-performance" class="btn btn-secondary btn-xs" onclick="setTunerMode('performance')">🚀 Производ.</button>
            <label class="row-gap pointer lbl-xs" style="margin-left:4px; white-space:nowrap;"><input type="checkbox" id="tuner-auto-chk" onchange="toggleTunerAutoSwitch()"> <b>Авто</b></label>
            <button class="btn btn-secondary btn-xs" onclick="restoreTunerBaseline()" title="Откатить настройки qB к исходному эталону">♻️ Эталон</button>
        </div>
    </div>

    <!-- Метрики в реальном времени -->
    <div class="tuner-telemetry-grid mb-10">
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Диск I/O</div><div id="tel-disk" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Чужой CPU</div><div id="tel-cpu" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">RAM своб.</div><div id="tel-ram" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Канал qB</div><div id="tel-chan" class="val-sm accent-txt">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Чужая сеть</div><div id="tel-net" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Слоты / Заполн.</div><div id="tel-slots" class="val-sm blue-txt">—</div></div>
    </div>

    <!-- Лента решений -->
    <div class="scroll-box mb-12" style="max-height:140px; border:1px solid var(--border); border-radius:6px;">
        <table>
            <thead><tr><th>Время</th><th>Режим</th><th>Событие</th><th>Причина</th><th>Слоты</th></tr></thead>
            <tbody id="tuner-history-tbody"><tr><td colspan="5" class="center-msg">Нет событий</td></tr></tbody>
        </table>
    </div>

    <div class="tuner-columns-grid">
        <!-- Левая колонка: Профили -->
        <div class="tuner-box">
            <div class="row-between mb-8">
                <div class="row-gap">
                    <button id="tp-tab-performance" class="btn btn-xs" onclick="selectTunerProfileTab('performance')">🚀 Производительность</button>
                    <button id="tp-tab-comfort" class="btn btn-secondary btn-xs" onclick="selectTunerProfileTab('comfort')">🛋️ Комфорт</button>
                </div>
                <div class="row-gap">
                    <button class="btn btn-secondary btn-xs" onclick="resetTunerProfile()" title="Сбросить профиль к заводским">Сброс</button>
                    <button class="btn btn-xs" onclick="saveTunerProfile()">💾 Сохранить</button>
                </div>
            </div>

            <!-- Главные параметры слотов -->
            <div class="tuner-section-title">СЛОТЫ ОТДАЧИ (MAX_UPLOADS)</div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field"><span class="lbl-micro">Мин. слотов</span><input id="tp-mu-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Макс. слотов</span><input id="tp-mu-max" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Стартовые</span><input id="tp-mu-start" type="number" class="form-control tuner-num-input"></div>
            </div>

            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">max_active_uploads</span>
                    <select id="tp-act-mode" class="form-control" onchange="syncTunerDisabledStates()">
                        <option value="keep">Не менять (как в эталоне)</option>
                        <option value="range">Диапазон Min..Max</option>
                        <option value="fixed">Фиксированное число</option>
                    </select>
                </div>
                <div class="tuner-field" id="wrap-tp-act-min"><span class="lbl-micro">Min</span><input id="tp-act-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field" id="wrap-tp-act-max"><span class="lbl-micro">Max</span><input id="tp-act-max" type="number" class="form-control tuner-num-input"></div>
            </div>

            <!-- Скорость и канал -->
            <div class="tuner-section-title">ЦЕЛЬ КАНАЛА И СКОРОСТИ</div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field"><span class="lbl-micro">Цель канала (От %)</span><input id="tp-ch-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Цель канала (До %)</span><input id="tp-ch-max" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Потолок Up (0=∞)</span><input id="tp-up-pct" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Потолок DL (0=∞)</span><input id="tp-dl-pct" type="number" class="form-control tuner-num-input"></div>
            </div>

            <div class="tuner-fields-row mb-8 align-end">
                <label class="row-gap pointer lbl-xs no-wrap grow-1" style="padding-bottom:5px;">
                    <input id="tp-sq-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>Ужимать при перегрузе</b>
                </label>
                <div class="tuner-field" id="wrap-tp-sq-up"><span class="lbl-micro">Сжать Up %</span><input id="tp-sq-up" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field" id="wrap-tp-sq-dl"><span class="lbl-micro">Сжать DL %</span><input id="tp-sq-dl" type="number" class="form-control tuner-num-input"></div>
            </div>

            <!-- Ограничители железа -->
            <div class="tuner-section-title">ОГРАНИЧИТЕЛИ ЖЕЛЕЗА И СЕТИ</div>
            <div class="tuner-guards-list mb-8">
                <!-- Диск -->
                <div class="tuner-guard-row" id="guard-row-disk">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-disk-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Диск I/O</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-disk-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Крит. %</span><input id="tp-g-disk-crit" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-disk-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- CPU -->
                <div class="tuner-guard-row" id="guard-row-cpu">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-cpu-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Чужой CPU</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-cpu-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-cpu-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- RAM -->
                <div class="tuner-guard-row" id="guard-row-ram">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-ram-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Своб. RAM</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Мин. % (тревога)</span><input id="tp-g-ram-min" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-ram-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- Сеть -->
                <div class="tuner-guard-row" id="guard-row-net">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-net-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Чужая сеть</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-net-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-net-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>

            <!-- Аккордеон: Тонкие настройки -->
            <details class="tuner-details">
                <summary>⚙️ Тонкие настройки слотов и задержек</summary>
                <div class="tuner-details-body">
                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">На торрент (Min)</span><input id="tp-pt-up-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">На торрент (Max)</span><input id="tp-pt-up-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-pt-up-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто 28%</label>
                    </div>

                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">Соединений (Min)</span><input id="tp-mc-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Соединений (Max)</span><input id="tp-mc-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-mc-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто ×4</label>
                    </div>

                    <div class="tuner-fields-row mb-8">
                        <div class="tuner-field"><span class="lbl-micro">Connec/торр. (Min)</span><input id="tp-pt-con-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Connec/торр. (Max)</span><input id="tp-pt-con-max" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Кулдаун (сек)</span><input id="tp-cd-sec" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Шаг разгона (+слоты)</span><input id="tp-step-up" type="number" class="form-control tuner-num-input"></div>
                    </div>

                    <label class="row-gap pointer lbl-xs no-wrap">
                        <input id="tp-yield-turtle" type="checkbox"> Уступать ручной «Черепахе» в клиенте
                    </label>
                </div>
            </details>
        </div>

        <!-- Правая колонка: Правила автопереключения -->
        <div class="tuner-box">
            <div class="row-between mb-8">
                <span class="lbl-sm" style="margin:0; font-weight:700;">🧠 ПРАВИЛА АВТОПЕРЕКЛЮЧЕНИЯ</span>
                <button class="btn btn-xs" onclick="saveTunerRules()">💾 Сохранить</button>
            </div>

            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Режим по умолчанию</span>
                    <select id="tr-def-mode" class="form-control">
                        <option value="performance">Производительность</option>
                        <option value="comfort">Комфорт</option>
                    </select>
                </div>
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Политика Manual Override</span>
                    <select id="tr-ov-policy" class="form-control">
                        <option value="2h">На 2 часа</option>
                        <option value="until_schedule">До смены расписания</option>
                        <option value="until_process_exit">До закрытия процесса</option>
                    </select>
                </div>
            </div>

            <!-- Расписание -->
            <div class="tuner-block-divider mb-8">
                <div class="row-between mb-6">
                    <span class="lbl-xs"><b>⏰ Расписание (с переходом через полночь)</b></span>
                    <button class="btn btn-secondary btn-xs" onclick="addTunerScheduleRow()">+ Окно</button>
                </div>
                <div id="tr-sched-list" class="col-gap" style="max-height:110px; overflow-y:auto;"></div>
            </div>

            <!-- Процессы (Watchlist) -->
            <div class="tuner-block-divider mb-8" id="rules-box-proc">
                <div class="row-between mb-6">
                    <label class="row-gap pointer lbl-xs no-wrap"><input id="tr-proc-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>🎮 Процессы (Watchlist)</b></label>
                    <div class="row-gap">
                        <select id="tr-proc-mode" class="form-control" style="padding:2px 4px; font-size:11px;">
                            <option value="comfort">→ Комфорт</option>
                            <option value="performance">→ Производ.</option>
                        </select>
                        <button class="btn btn-secondary btn-xs" onclick="loadRunningProcessesPicker()">🖥️ Процессы ПК</button>
                    </div>
                </div>
                <input id="tr-proc-names" class="form-control mb-6" placeholder="cs2.exe, dota2.exe, obs64.exe">
                <div id="tr-proc-picker" class="hidden row-wrap mb-6" style="max-height:85px; overflow-y:auto; gap:4px;"></div>
                <div class="tuner-fields-row">
                    <div class="tuner-field"><span class="lbl-micro">Задержка входа (сек)</span><input id="tr-proc-enter" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Задержка выхода (сек)</span><input id="tr-proc-exit" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>

            <!-- Внешняя нагрузка -->
            <div class="tuner-block-divider" id="rules-box-ext">
                <div class="row-between mb-6">
                    <label class="row-gap pointer lbl-xs no-wrap"><input id="tr-ext-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>⚡ Активность чужих программ</b></label>
                    <select id="tr-ext-mode" class="form-control" style="width:115px; padding:2px 4px; font-size:11px;">
                        <option value="comfort">→ Комфорт</option>
                        <option value="performance">→ Производ.</option>
                    </select>
                </div>
                <div class="tuner-fields-row mb-6">
                    <div class="tuner-field"><span class="lbl-micro">CPU Вход %</span><input id="tr-ext-cpu-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">CPU Выход %</span><input id="tr-ext-cpu-r" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Сеть Вход %</span><input id="tr-ext-net-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Сеть Выход %</span><input id="tr-ext-net-r" type="number" class="form-control tuner-num-input"></div>
                </div>
                <div class="tuner-fields-row mb-6">
                    <div class="tuner-field"><span class="lbl-micro">RAM Мин. %</span><input id="tr-ext-ram-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">RAM Возвр. %</span><input id="tr-ext-ram-r" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Вход (сек)</span><input id="tr-ext-enter" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Выход (сек)</span><input id="tr-ext-exit" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>
        </div>
    </div>
</div>
```

---

#### `web/static/style.css`
```css
:root {
    --bg-main: #121214; --bg-panel: #1a1a20; --bg-input: #262630; --bg-hover: #22222a;
    --text: #ffffff; --text-muted: #95a5a6; --accent: #2ecc71; --th-bg: #1e1e26;
    --danger: #e74c3c; --warning: #f39c12; --info: #3498db; --border: #2a2a34;
    --app-font: 'Segoe UI', system-ui, sans-serif;
}
html, body { width: 100%; max-width: 100vw; overflow-x: hidden; }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: var(--app-font); }
body { background: var(--bg-main); color: var(--text); display: flex; flex-direction: column; min-height: 100vh; }

::-webkit-scrollbar { width: 7px; height: 7px; }
::-webkit-scrollbar-track { background: var(--bg-main); }
::-webkit-scrollbar-thumb { background: var(--bg-input); border-radius: 4px; border: 1px solid var(--border); }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

header { background: var(--bg-panel); padding: 10px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; width: 100%; max-width: 100vw; }
.logo-svg { width: 32px; height: 32px; filter: drop-shadow(0 0 6px rgba(46, 204, 113, 0.4)); }
.logo-text { font-size: 1.15rem; font-weight: 800; color: var(--accent); }

.nav-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
.tab-btn { background: transparent; border: none; color: var(--text-muted); padding: 7px 12px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; transition: 0.15s; }
.tab-btn:hover { background: var(--bg-input); color: var(--text); }
.tab-btn.active { background: var(--accent); color: #000; font-weight: 700; }

.btn { background: var(--accent); color: #000; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px; text-decoration: none; transition: 0.15s; }
.btn:hover { filter: brightness(1.1); }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-danger { background: var(--danger); color: #fff; }
.btn-secondary { background: var(--bg-input); color: var(--text); border: 1px solid var(--border); }
.btn-xs { padding: 4px 8px; font-size: 11px; }
.center-btn { justify-content: center; padding: 8px; }

#btn-panic-killswitch.holding { animation: panicPulse 0.4s infinite alternate; transform: scale(0.96); }
@keyframes panicPulse { from { box-shadow: 0 0 0 0 rgba(231,76,60,0.6); } to { box-shadow: 0 0 12px 4px rgba(231,76,60,0.9); } }

main { flex: 1; display: flex; flex-direction: column; width: 100%; max-width: 100vw; overflow-x: hidden; }
.tab-content { display: none; height: 100%; padding: 14px; overflow-y: auto; width: 100%; max-width: 100%; }
.tab-content.active { display: flex; gap: 14px; }
.col-center { flex-direction: column; max-width: 850px; margin: 0 auto; width: 100%; }
.col-wide { flex-direction: column; max-width: 1400px; margin: 0 auto; width: 100%; gap: 12px; }

.app-footer { background: var(--bg-panel); border-top: 1px solid var(--border); padding: 8px 16px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; width: 100%; }
.version-pill { color: var(--accent); font-weight: 700; text-decoration: none; padding: 3px 9px; background: var(--bg-input); border-radius: 6px; border: 1px solid var(--border); }
.version-pill:hover { filter: brightness(1.15); }
.tools-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; width: 100%; max-width: 100%; }

.heatmap-scroll { overflow-x: auto; padding-bottom: 6px; max-width: 100%; }
.heatmap-grid { display: grid; grid-template-rows: repeat(7, 12px); grid-auto-flow: column; grid-auto-columns: 12px; gap: 3px; width: max-content; }
.hm-cell { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
.hm-empty { background: transparent; }
.hm-l0 { background: var(--bg-input); border: 1px solid var(--border); }
.hm-l1 { background: rgba(46, 204, 113, 0.28); }
.hm-l2 { background: rgba(46, 204, 113, 0.52); }
.hm-l3 { background: rgba(46, 204, 113, 0.78); }
.hm-l4 { background: #2ecc71; }

.diff-row-exact td { background: rgba(46, 204, 113, 0.08); }
.diff-row-changed td { background: rgba(243, 156, 18, 0.12); }
.diff-row-removed td { background: rgba(231, 76, 60, 0.12); }
.diff-row-added td { background: rgba(52, 152, 219, 0.12); }

.torrent-left { flex: 3.5; display: flex; flex-direction: column; background: var(--bg-panel); border-radius: 8px; border: 1px solid var(--border); overflow: hidden; min-width: 0; }
.torrent-right { flex: 1; min-width: 280px; display: flex; flex-direction: column; gap: 12px; }
.table-toolbar { padding: 8px 12px; display: flex; gap: 8px; border-bottom: 1px solid var(--border); align-items: center; flex-wrap: wrap; }
.search-input { flex: 1; min-width: 140px; background: var(--bg-input); border: 1px solid var(--border); color: var(--text); padding: 7px 10px; border-radius: 6px; outline: none; font-size: 13px; }
.table-container { flex: 1; overflow: auto; min-height: 250px; max-width: 100%; }

table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }
th { background: var(--th-bg); color: var(--text-muted); padding: 9px 10px; position: sticky; top: 0; border-bottom: 2px solid var(--border); cursor: pointer; user-select: none; white-space: nowrap; font-size: 11.5px; }
th:hover { color: var(--accent); }
td { padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
tr:hover td { background: var(--bg-hover); }
tr.selected td { background: rgba(46, 204, 113, 0.15) !important; border-left: 3px solid var(--accent); }

.badge { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.badge-up { background: rgba(46, 204, 113, 0.15); color: #2ecc71; border: 1px solid rgba(46, 204, 113, 0.3); }
.badge-dl { background: rgba(52, 152, 219, 0.15); color: #3498db; border: 1px solid rgba(52, 152, 219, 0.3); }
.badge-pause { background: rgba(149, 165, 166, 0.15); color: #95a5a6; border: 1px solid rgba(149, 165, 166, 0.3); }
.badge-stall { background: rgba(243, 156, 18, 0.15); color: #f39c12; border: 1px solid rgba(243, 156, 18, 0.3); }
.badge-stop { background: rgba(231, 76, 60, 0.15); color: #e74c3c; border: 1px solid rgba(231, 76, 60, 0.3); }
.badge-force { background: rgba(230, 126, 34, 0.15); color: #e67e22; border: 1px solid rgba(230, 126, 34, 0.3); }
.badge-err { background: rgba(231, 76, 60, 0.25); color: #ff5252; border: 1px solid #ff5252; }

.card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px; width: 100%; max-width: 100%; }
.card-title { font-size: 12px; font-weight: 800; margin-bottom: 8px; color: var(--accent); letter-spacing: 0.5px; }
.danger-border { border-color: rgba(231, 76, 60, 0.4); }
.form-group { margin-bottom: 8px; }
.form-group label { display: block; font-size: 11px; color: var(--text-muted); margin-bottom: 4px; font-weight: 600; }
.form-control { width: 100%; background: var(--bg-input); border: 1px solid var(--border); color: var(--text); padding: 7px 10px; border-radius: 6px; outline: none; font-size: 13px; }

/* === АВТО-ТЮНЕР СТИЛИ === */
.tuner-columns-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 12px; width: 100%; }
.tuner-box { background: var(--bg-input); padding: 12px; border-radius: 6px; border: 1px solid var(--border); display: flex; flex-direction: column; }
.tuner-telemetry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
.tuner-stat-card { background: var(--bg-input); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); }
.tuner-section-title { font-size: 10.5px; font-weight: 800; color: var(--text-muted); letter-spacing: 0.5px; margin: 6px 0 4px; }
.tuner-block-divider { border-top: 1px dashed var(--border); padding-top: 8px; }
.tuner-fields-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; }
.tuner-field { display: flex; flex-direction: column; gap: 2px; flex: 1 1 70px; min-width: 68px; }
.tuner-num-input { padding: 5px 6px !important; font-size: 12px !important; text-align: center; }
.lbl-micro { font-size: 9.5px; color: var(--text-muted); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.no-wrap { white-space: nowrap !important; }
.align-end { align-items: flex-end !important; }

.tuner-guards-list { display: flex; flex-direction: column; gap: 6px; border-top: 1px dashed var(--border); padding-top: 8px; }
.tuner-guard-row { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; background: rgba(0,0,0,0.15); padding: 6px 8px; border-radius: 6px; transition: opacity 0.2s; }
.tuner-guard-label { width: 110px; padding-bottom: 6px; flex-shrink: 0; }
.tuner-row-disabled { opacity: 0.38 !important; }
.tuner-row-disabled input:not([type=checkbox]),
.tuner-row-disabled select { pointer-events: none; background: rgba(0,0,0,0.2) !important; color: var(--text-muted) !important; }

.tuner-details { border-top: 1px dashed var(--border); padding-top: 8px; margin-top: 6px; }
.tuner-details summary { font-size: 11.5px; font-weight: 700; color: var(--info); cursor: pointer; user-select: none; padding: 4px 0; }
.tuner-details summary:hover { color: var(--accent); }
.tuner-details-body { padding-top: 8px; display: flex; flex-direction: column; gap: 4px; }

.terminal { background: #0c0c0f; color: #2ecc71; font-family: 'Consolas', monospace; font-size: 12px; padding: 12px; border-radius: 6px; height: 170px; overflow-y: auto; white-space: pre-wrap; line-height: 1.45; border: 1px solid var(--border); }
.scroll-box { max-height: 220px; overflow-y: auto; }
.flex-scroll { flex: 1; overflow: auto; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: none; justify-content: center; align-items: center; z-index: 999; padding: 14px; }
.modal { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; width: 100%; max-width: 480px; padding: 18px; }
.autostart-box { background: var(--bg-input); padding: 10px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }

.login-body { justify-content: center; align-items: center; padding: 16px; }
.login-card { width: 100%; max-width: 380px; padding: 24px; text-align: center; }
.login-title { font-size: 1.5rem; font-weight: 800; color: var(--accent); margin-bottom: 8px; }
.alert-err { background: rgba(231, 76, 60, 0.2); border: 1px solid var(--danger); color: #ff6b6b; padding: 8px; border-radius: 6px; font-size: 12px; margin-bottom: 12px; }

.row-gap { display: flex; gap: 8px; align-items: center; }
.row-wrap { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.row-between { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.row-end { display: flex; justify-content: flex-end; gap: 8px; }
.col-gap { display: flex; flex-direction: column; gap: 8px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
.grid-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.grid-calc { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }

.w-full { width: 100%; } .grow-1 { flex: 1; min-width: 140px; }
.mb-6 { margin-bottom: 6px; } .mb-8 { margin-bottom: 8px; } .mb-10 { margin-bottom: 10px; } .mb-12 { margin-bottom: 12px; }
.mt-10 { margin-top: 10px; } .mt-12 { margin-top: 12px; }
.hidden { display: none !important; } .pointer { cursor: pointer; }
.center-msg { text-align: center; padding: 20px; color: var(--text-muted); }

.muted-text { font-size: 12px; color: var(--text-muted); }
.lbl-sm { display: block; font-size: 11px; color: var(--text-muted); margin-bottom: 3px; font-weight: 600; }
.lbl-xs { font-size: 11px; font-weight: 600; }
.val-lg { font-size: 18px; font-weight: 800; }
.val-md { font-size: 15px; font-weight: 800; }
.val-sm { font-size: 13px; font-weight: 700; margin-top: 3px; }
.accent-txt { color: var(--accent); } .purple-txt { color: #9b59b6; }
.orange-txt { color: #e67e22; } .blue-txt { color: #3498db; }

.col-resizer { position: absolute; right: 0; top: 0; width: 6px; height: 100%; cursor: col-resize; user-select: none; }
.col-resizer:hover { background: var(--accent); opacity: 0.6; }

@media (max-width: 900px) {
    .tab-content.active { flex-direction: column; overflow-y: auto; }
    .torrent-right { min-width: 100%; }
    body { height: auto; overflow-y: auto; }
    main { overflow: visible; }
}

@media (max-width: 768px) {
    header { padding: 8px 10px; }
    header .row-gap { width: 100%; justify-content: flex-start; flex-wrap: wrap; gap: 6px; }
    .nav-tabs { width: 100%; overflow-x: auto; flex-wrap: nowrap; padding-bottom: 4px; }
    .nav-tabs .tab-btn { flex: 0 0 auto; white-space: nowrap; }
    .tools-grid { grid-template-columns: 1fr; }
    .grid-2 { grid-template-columns: 1fr; }
    .tab-content { padding: 8px; }

    .tuner-columns-grid { grid-template-columns: 1fr; }
    .tuner-guard-row { flex-direction: column; align-items: stretch; gap: 4px; }
    .tuner-guard-label { width: 100%; }
    .tuner-fields-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    .tuner-fields-row.align-end { grid-template-columns: 1fr; }

    body.mobile-cards-on .grid-cards,
    body.mobile-cards-on #analytics-charts-grid {
        grid-template-columns: 1fr !important;
    }
    body.mobile-cards-on .btn, body.mobile-cards-on .tab-btn { padding: 8px 10px; font-size: 12px; }
    body.mobile-cards-on #summary-table thead { display: none; }
    body.mobile-cards-on #summary-table,
    body.mobile-cards-on #summary-table tbody { display: block; width: 100%; }
    body.mobile-cards-on #summary-table tr {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px 10px;
        background: var(--bg-input);
        border: 1px solid var(--border);
        border-radius: 8px;
        margin-bottom: 8px;
        padding: 8px 10px;
    }
    body.mobile-cards-on #summary-table tr.selected { border-color: var(--accent); }
    body.mobile-cards-on #summary-table td {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 2px 0;
        border-bottom: none;
        white-space: normal;
        min-width: 0;
    }
    body.mobile-cards-on #summary-table td::before {
        content: attr(data-label);
        color: var(--text-muted);
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
    }
    body.mobile-cards-on #summary-table td[data-col="name"] {
        grid-column: 1 / -1;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid var(--border);
        padding-bottom: 6px;
        margin-bottom: 2px;
    }
    body.mobile-cards-on #summary-table td[data-col="name"]::before { display: none; }
    body.mobile-cards-on #summary-table td[data-col="name"] strong {
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 13px;
    }
    body.mobile-cards-on #summary-table td[data-col="ratio"] {
        grid-column: 1 / -1;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
        background: rgba(46, 204, 113, 0.08);
        padding: 4px 8px;
        border-radius: 5px;
    }
}
```

---

#### `web/static/tuner_ui.js`
```javascript
// web/static/tuner_ui.js
let _tunerProfiles = {};
let _tunerCurProfile = 'performance';
let _tunerRules = {};

function syncTunerDisabledStates() {
    const setGroupState = (chkId, rowId, inputIds) => {
        const en = Boolean(document.getElementById(chkId)?.checked);
        const row = document.getElementById(rowId);
        if (row) row.classList.toggle('tuner-row-disabled', !en);
        inputIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = !en;
        });
    };

    setGroupState('tp-g-disk-en', 'guard-row-disk', ['tp-g-disk-warn', 'tp-g-disk-crit', 'tp-g-disk-rec']);
    setGroupState('tp-g-cpu-en', 'guard-row-cpu', ['tp-g-cpu-warn', 'tp-g-cpu-rec']);
    setGroupState('tp-g-ram-en', 'guard-row-ram', ['tp-g-ram-min', 'tp-g-ram-rec']);
    setGroupState('tp-g-net-en', 'guard-row-net', ['tp-g-net-warn', 'tp-g-net-rec']);

    const sqEn = Boolean(document.getElementById('tp-sq-en')?.checked);
    ['tp-sq-up', 'tp-sq-dl'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !sqEn;
        document.getElementById(`wrap-${id}`)?.classList.toggle('tuner-row-disabled', !sqEn);
    });

    const actMode = document.getElementById('tp-act-mode')?.value || 'keep';
    const minEl = document.getElementById('tp-act-min');
    const maxEl = document.getElementById('tp-act-max');
    if (minEl) minEl.disabled = (actMode === 'keep');
    if (maxEl) maxEl.disabled = (actMode !== 'range');
    document.getElementById('wrap-tp-act-min')?.classList.toggle('tuner-row-disabled', actMode === 'keep');
    document.getElementById('wrap-tp-act-max')?.classList.toggle('tuner-row-disabled', actMode !== 'range');

    const ptUpAuto = Boolean(document.getElementById('tp-pt-up-auto')?.checked);
    ['tp-pt-up-min', 'tp-pt-up-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = ptUpAuto;
    });

    const mcAuto = Boolean(document.getElementById('tp-mc-auto')?.checked);
    ['tp-mc-min', 'tp-mc-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = mcAuto;
    });

    const prEn = Boolean(document.getElementById('tr-proc-en')?.checked);
    ['tr-proc-mode', 'tr-proc-names', 'tr-proc-enter', 'tr-proc-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !prEn;
    });
    document.getElementById('rules-box-proc')?.classList.toggle('tuner-row-disabled', !prEn);

    const extEn = Boolean(document.getElementById('tr-ext-en')?.checked);
    ['tr-ext-mode', 'tr-ext-cpu-w', 'tr-ext-cpu-r', 'tr-ext-net-w', 'tr-ext-net-r', 'tr-ext-ram-w', 'tr-ext-ram-r', 'tr-ext-enter', 'tr-ext-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !extEn;
    });
    document.getElementById('rules-box-ext')?.classList.toggle('tuner-row-disabled', !extEn);
}

async function loadTunerTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await Promise.all([refreshTunerState(), loadTunerProfiles(), loadTunerRules()]);
}

async function refreshTunerState() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/tuner/state');
        if (!res.ok) return;
        const d = await res.json();
        const st = d.state || {}, tel = d.telemetry || {}, mode = st.mode || 'off';
        ['off', 'comfort', 'performance'].forEach(m => {
            const b = document.getElementById(`tuner-btn-${m}`);
            if (b) b.className = (m === mode) ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
        });
        const chk = document.getElementById('tuner-auto-chk');
        if (chk) chk.checked = Boolean(st.auto_switch_enabled);

        const reason = d.switch_reason || st.last_reason || 'Выключен';
        const badge = document.getElementById('tuner-reason-badge');
        if (badge) {
            badge.textContent = reason;
            badge.className = mode === 'off' ? 'badge badge-pause' : (mode === 'performance' ? 'badge badge-up' : 'badge badge-dl');
        }
        const hb = document.getElementById('tuner-header-badge');
        if (hb) {
            hb.textContent = mode === 'off' ? '🎛️ Тюнер: Выкл' : (mode === 'performance' ? '🚀 Тюнер: Произв.' : '🛋️ Тюнер: Комф.');
            hb.className = mode === 'off' ? 'badge badge-pause pointer admin-only' : (mode === 'performance' ? 'badge badge-up pointer admin-only' : 'badge badge-dl pointer admin-only');
        }
        document.getElementById('tuner-btn-clear-ov')?.classList.toggle('hidden', !st.manual_override_mode);

        const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        setTxt('tel-disk', tel.psutil_available === false ? 'нет psutil' : `${tel.disk_busy ?? 0}%`);
        setTxt('tel-cpu', `${tel.cpu_ext ?? 0}%`);
        setTxt('tel-ram', `${tel.ram_free ?? 0}%`);
        setTxt('tel-chan', `${tel.channel_pct ?? 0}%`);
        setTxt('tel-net', `${tel.net_ext_pct ?? 0}%`);
        const curMu = (st.current_limits || {}).max_uploads || (st.baseline || {}).max_uploads || '—';
        setTxt('tel-slots', `${curMu} (${tel.slots_fill_pct ?? 0}%)`);

        const tbody = document.getElementById('tuner-history-tbody');
        if (tbody) {
            const hist = d.history || [];
            tbody.innerHTML = hist.length ? hist.map(h => `
                <tr><td>${escapeHtml(h.time)}</td><td>${escapeHtml(h.mode)}</td><td><span class="badge badge-pause">${escapeHtml(h.event_type)}</span></td><td style="white-space:normal;">${escapeHtml(h.reason)}</td><td>${h.old_slots}→${h.new_slots}</td></tr>
            `).join('') : '<tr><td colspan="5" class="center-msg">Нет событий</td></tr>';
        }
    } catch (e) {}
}

async function setTunerMode(mode) {
    const res = await api('/api/tuner/mode', 'POST', { mode, is_manual: true });
    if (!res.ok) return alert((await res.json()).error || 'Ошибка');
    refreshTunerState();
}

async function toggleTunerAutoSwitch() {
    const auto_switch = document.getElementById('tuner-auto-chk')?.checked || false;
    const mode = auto_switch ? (_tunerRules.default_mode || 'performance') : 'off';
    await api('/api/tuner/mode', 'POST', { mode, auto_switch, is_manual: false });
    refreshTunerState();
}

async function clearTunerOverride() {
    await api('/api/tuner/mode', 'POST', { mode: _tunerRules.default_mode || 'performance', clear_override: true, is_manual: false });
    refreshTunerState();
}

async function restoreTunerBaseline() {
    if (!confirm('Выключить тюнер и восстановить эталонные настройки qBittorrent?')) return;
    const res = await api('/api/tuner/restore_baseline', 'POST');
    alert((await res.json()).message || 'Готово');
    refreshTunerState();
}

async function loadTunerProfiles() {
    const res = await api('/api/tuner/profiles');
    if (res.ok) { _tunerProfiles = (await res.json()).profiles || {}; selectTunerProfileTab(_tunerCurProfile); }
}

function selectTunerProfileTab(mode) {
    _tunerCurProfile = mode;
    document.getElementById('tp-tab-performance').className = mode === 'performance' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    document.getElementById('tp-tab-comfort').className = mode === 'comfort' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    const p = _tunerProfiles[mode] || {}, g = p.guards || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tp-mu-min', p.max_uploads_min); sv('tp-mu-max', p.max_uploads_max); sv('tp-mu-start', p.max_uploads_start);
    sv('tp-pt-up-min', p.per_torrent_up_min); sv('tp-pt-up-max', p.per_torrent_up_max); sc('tp-pt-up-auto', p.per_torrent_up_auto);
    sv('tp-mc-min', p.max_connec_min); sv('tp-mc-max', p.max_connec_max); sc('tp-mc-auto', p.max_connec_auto);
    sv('tp-pt-con-min', p.per_torrent_connec_min); sv('tp-pt-con-max', p.per_torrent_connec_max);
    sv('tp-act-mode', p.active_uploads_mode || 'keep'); sv('tp-act-min', p.active_uploads_min); sv('tp-act-max', p.active_uploads_max);
    sv('tp-ch-min', p.channel_target_min); sv('tp-ch-max', p.channel_target_max);
    sv('tp-up-pct', p.up_limit_pct); sv('tp-dl-pct', p.dl_limit_pct);
    sc('tp-sq-en', p.squeeze_enabled); sv('tp-sq-up', p.squeeze_up_pct); sv('tp-sq-dl', p.squeeze_dl_pct);
    sv('tp-cd-sec', p.cooldown_sec); sv('tp-step-up', p.step_up_size); sc('tp-yield-turtle', p.yield_to_turtle);
    sc('tp-g-disk-en', g.disk?.enabled); sv('tp-g-disk-warn', g.disk?.warn); sv('tp-g-disk-crit', g.disk?.crit); sv('tp-g-disk-rec', g.disk?.recover);
    sc('tp-g-cpu-en', g.cpu?.enabled); sv('tp-g-cpu-warn', g.cpu?.warn); sv('tp-g-cpu-rec', g.cpu?.recover);
    sc('tp-g-ram-en', g.ram?.enabled); sv('tp-g-ram-min', g.ram?.min_free); sv('tp-g-ram-rec', g.ram?.recover_free);
    sc('tp-g-net-en', g.net?.enabled); sv('tp-g-net-warn', g.net?.warn_pct); sv('tp-g-net-rec', g.net?.recover_pct);

    syncTunerDisabledStates();
}

async function saveTunerProfile() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const profile = {
        max_uploads_min: iv('tp-mu-min'), max_uploads_max: iv('tp-mu-max'), max_uploads_start: iv('tp-mu-start'),
        per_torrent_up_min: iv('tp-pt-up-min'), per_torrent_up_max: iv('tp-pt-up-max'), per_torrent_up_auto: cb('tp-pt-up-auto'),
        max_connec_min: iv('tp-mc-min'), max_connec_max: iv('tp-mc-max'), max_connec_auto: cb('tp-mc-auto'),
        per_torrent_connec_min: iv('tp-pt-con-min'), per_torrent_connec_max: iv('tp-pt-con-max'),
        active_uploads_mode: document.getElementById('tp-act-mode')?.value || 'keep',
        active_uploads_min: iv('tp-act-min'), active_uploads_max: iv('tp-act-max'),
        channel_target_min: iv('tp-ch-min'), channel_target_max: iv('tp-ch-max'),
        up_limit_pct: iv('tp-up-pct'), dl_limit_pct: iv('tp-dl-pct'),
        squeeze_enabled: cb('tp-sq-en'), squeeze_up_pct: iv('tp-sq-up'), squeeze_dl_pct: iv('tp-sq-dl'),
        cooldown_sec: iv('tp-cd-sec'), step_up_size: iv('tp-step-up'), yield_to_turtle: cb('tp-yield-turtle'),
        guards: {
            disk: { enabled: cb('tp-g-disk-en'), warn: iv('tp-g-disk-warn'), crit: iv('tp-g-disk-crit'), recover: iv('tp-g-disk-rec') },
            cpu:  { enabled: cb('tp-g-cpu-en'), warn: iv('tp-g-cpu-warn'), recover: iv('tp-g-cpu-rec') },
            ram:  { enabled: cb('tp-g-ram-en'), min_free: iv('tp-g-ram-min'), recover_free: iv('tp-g-ram-rec') },
            net:  { enabled: cb('tp-g-net-en'), warn_pct: iv('tp-g-net-warn'), recover_pct: iv('tp-g-net-rec') }
        }
    };
    const res = await api('/api/tuner/profiles', 'POST', { mode: _tunerCurProfile, profile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; alert(`✅ Профиль «${_tunerCurProfile}» сохранён`); }
}

async function resetTunerProfile() {
    if (!confirm(`Сбросить профиль «${_tunerCurProfile}» к заводским значениям?`)) return;
    const res = await api('/api/tuner/profiles', 'POST', { reset_mode: _tunerCurProfile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; selectTunerProfileTab(_tunerCurProfile); }
}

async function loadTunerRules() {
    const res = await api('/api/tuner/rules');
    if (!res.ok) return;
    _tunerRules = (await res.json()).rules || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tr-def-mode', _tunerRules.default_mode || 'performance');
    sv('tr-ov-policy', _tunerRules.override_policy || '2h');
    const pr = _tunerRules.processes || {}, ex = _tunerRules.external_load || {};
    sc('tr-proc-en', pr.enabled); sv('tr-proc-mode', pr.target_mode || 'comfort');
    sv('tr-proc-names', (pr.names || []).join(', ')); sv('tr-proc-enter', pr.enter_sec); sv('tr-proc-exit', pr.exit_sec);
    sc('tr-ext-en', ex.enabled); sv('tr-ext-mode', ex.target_mode || 'comfort');
    sv('tr-ext-cpu-w', ex.cpu_warn); sv('tr-ext-cpu-r', ex.cpu_recover);
    sv('tr-ext-net-w', ex.net_warn_pct); sv('tr-ext-net-r', ex.net_recover_pct);
    sv('tr-ext-ram-w', ex.ram_min_free); sv('tr-ext-ram-r', ex.ram_recover_free);
    sv('tr-ext-enter', ex.enter_sec); sv('tr-ext-exit', ex.exit_sec);

    renderTunerSchedules();
    syncTunerDisabledStates();
}

function renderTunerSchedules() {
    const box = document.getElementById('tr-sched-list');
    if (!box) return;
    const list = _tunerRules.schedules || [];
    box.innerHTML = list.map((s, idx) => `
        <div class="row-gap" style="gap:4px;">
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.start)}" onchange="_tunerRules.schedules[${idx}].start=this.value">
            <span>—</span>
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.end)}" onchange="_tunerRules.schedules[${idx}].end=this.value">
            <select class="form-control grow-1" style="padding:3px 4px;" onchange="_tunerRules.schedules[${idx}].mode=this.value">
                <option value="performance" ${s.mode==='performance'?'selected':''}>Производ.</option>
                <option value="comfort" ${s.mode==='comfort'?'selected':''}>Комфорт</option>
            </select>
            <button class="btn btn-danger btn-xs" onclick="_tunerRules.schedules.splice(${idx},1);renderTunerSchedules()">✕</button>
        </div>
    `).join('') || '<span class="lbl-xs muted-text">Окон расписания нет</span>';
}

function addTunerScheduleRow() {
    _tunerRules.schedules = _tunerRules.schedules || [];
    _tunerRules.schedules.push({ start: '01:00', end: '08:00', days: [0, 1, 2, 3, 4, 5, 6], mode: 'performance' });
    renderTunerSchedules();
}

async function loadRunningProcessesPicker() {
    const box = document.getElementById('tr-proc-picker');
    if (!box) return;
    box.classList.remove('hidden'); box.innerHTML = '<span class="lbl-xs muted-text">⏳ Сканирую процессы...</span>';
    const res = await api('/api/tuner/processes');
    if (!res.ok) return;
    const list = (await res.json()).processes || [];
    box.innerHTML = list.map(p => `<button type="button" class="btn btn-secondary btn-xs" onclick="appendProcessToWatchlist('${escapeHtml(p)}')">+ ${escapeHtml(p)}</button>`).join('');
}

function appendProcessToWatchlist(name) {
    const inp = document.getElementById('tr-proc-names');
    const cur = inp.value.split(',').map(x => x.trim()).filter(Boolean);
    if (!cur.some(x => x.toLowerCase() === name.toLowerCase())) { cur.push(name); inp.value = cur.join(', '); }
}

async function saveTunerRules() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const rules = {
        default_mode: document.getElementById('tr-def-mode')?.value || 'performance',
        override_policy: document.getElementById('tr-ov-policy')?.value || '2h',
        schedules: _tunerRules.schedules || [],
        processes: {
            enabled: cb('tr-proc-en'), target_mode: document.getElementById('tr-proc-mode')?.value || 'comfort',
            names: (document.getElementById('tr-proc-names')?.value || '').split(',').map(x => x.trim()).filter(Boolean),
            enter_sec: iv('tr-proc-enter'), exit_sec: iv('tr-proc-exit')
        },
        external_load: {
            enabled: cb('tr-ext-en'), target_mode: document.getElementById('tr-ext-mode')?.value || 'comfort',
            cpu_warn: iv('tr-ext-cpu-w'), cpu_recover: iv('tr-ext-cpu-r'),
            net_warn_pct: iv('tr-ext-net-w'), net_recover_pct: iv('tr-ext-net-r'),
            ram_min_free: iv('tr-ext-ram-w'), ram_recover_free: iv('tr-ext-ram-r'),
            enter_sec: iv('tr-ext-enter'), exit_sec: iv('tr-ext-exit')
        }
    };
    const res = await api('/api/tuner/rules', 'POST', { rules });
    if (res.ok) { _tunerRules = (await res.json()).rules; alert('✅ Правила автопереключения сохранены'); }
}

setInterval(() => {
    if (!document.hidden && (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin')) refreshTunerState();
}, 10000);
```

---

Копируй это сообщение в `patch.md`, накатывай через `python apply_patch.py`, обновляй страницу через `Ctrl+F5` и проверяй обновлённый тюнер:
- Все числовые поля теперь имеют свои микро-подписи.
- При снятии галки с ограничителя поля становятся полупрозрачными и выключаются (`disabled`).
- Второстепенные параметры компактно живут в аккордеоне `⚙️ Тонкие настройки слотов и задержек`.
- На мобилках и планшетах блоки красиво перестраиваются без горизонтального скролла!