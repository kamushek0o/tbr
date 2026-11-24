### План (Пачка 3 — UI адаптивного авто-тюнера, профили, правила, телеметрия)
1. `web/templates/partials/tab_tuner.html` *(новый)* — панель управления режимами, живая телеметрия, лента решений `tuner_history`, конструктор профилей и правил автопереключения.
2. `web/templates/partials/tab_automation.html` — подключаем `tab_tuner.html` во вкладке Автопилота.
3. `web/templates/index.html` — добавляем индикатор тюнера `#tuner-header-badge` в шапку и подключаем `tuner_ui.js`.
4. `web/static/tuner_ui.js` *(новый)* — вся логика UI тюнера, живой поллинг телеметрии и мастер выбора процессов.
5. `web/static/automation.js` — вызов `loadTunerTab()` при открытии вкладки Автопилота.

---

#### `web/templates/partials/tab_tuner.html` *(новый файл)*
```html
<!-- Адаптивный авто-тюнер qBittorrent (ТЗ #58) -->
<div class="card admin-only" id="tuner-main-card">
    <div class="row-between mb-8">
        <div class="row-gap" style="flex-wrap:wrap;">
            <div class="card-title" style="margin:0;">🎛️ АДАПТИВНЫЙ АВТО-ТЮНЕР qBITTORRENT</div>
            <span id="tuner-reason-badge" class="badge badge-pause">Выключен</span>
            <button id="tuner-btn-clear-ov" class="btn btn-secondary btn-xs hidden" onclick="clearTunerOverride()">🔄 Вернуть авто</button>
        </div>
        <div class="row-gap" style="flex-wrap:wrap;">
            <button id="tuner-btn-off" class="btn btn-secondary btn-xs" onclick="setTunerMode('off')">Выкл</button>
            <button id="tuner-btn-comfort" class="btn btn-secondary btn-xs" onclick="setTunerMode('comfort')">🛋️ Комфорт</button>
            <button id="tuner-btn-performance" class="btn btn-secondary btn-xs" onclick="setTunerMode('performance')">🚀 Производ.</button>
            <label class="row-gap pointer lbl-xs" style="margin-left:4px;"><input type="checkbox" id="tuner-auto-chk" onchange="toggleTunerAutoSwitch()"> <b>Авто</b></label>
            <button class="btn btn-secondary btn-xs" onclick="restoreTunerBaseline()" title="Откатить лимиты qB к эталону">♻️ Эталон</button>
        </div>
    </div>

    <div class="grid-cards mb-10" style="grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));">
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">Диск I/O</div><div id="tel-disk" class="val-sm">—</div></div>
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">Чужой CPU</div><div id="tel-cpu" class="val-sm">—</div></div>
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">RAM своб.</div><div id="tel-ram" class="val-sm">—</div></div>
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">Канал qB</div><div id="tel-chan" class="val-sm accent-txt">—</div></div>
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">Чужая сеть</div><div id="tel-net" class="val-sm">—</div></div>
        <div style="background:var(--bg-input); padding:7px; border-radius:6px;"><div class="lbl-xs muted-text">Слоты / Заполн.</div><div id="tel-slots" class="val-sm blue-txt">—</div></div>
    </div>

    <div class="scroll-box mb-12" style="max-height:150px; border:1px solid var(--border); border-radius:6px;">
        <table>
            <thead><tr><th>Время</th><th>Режим</th><th>Событие</th><th>Причина</th><th>Слоты</th></tr></thead>
            <tbody id="tuner-history-tbody"><tr><td colspan="5" class="center-msg">Нет событий</td></tr></tbody>
        </table>
    </div>

    <div class="grid-2" style="gap:12px;">
        <div style="background:var(--bg-input); padding:10px; border-radius:6px; border:1px solid var(--border);">
            <div class="row-between mb-8">
                <div class="row-gap">
                    <button id="tp-tab-performance" class="btn btn-xs" onclick="selectTunerProfileTab('performance')">🚀 Производительность</button>
                    <button id="tp-tab-comfort" class="btn btn-secondary btn-xs" onclick="selectTunerProfileTab('comfort')">🛋️ Комфорт</button>
                </div>
                <div class="row-gap">
                    <button class="btn btn-secondary btn-xs" onclick="resetTunerProfile()">Сброс</button>
                    <button class="btn btn-xs" onclick="saveTunerProfile()">💾 Профиль</button>
                </div>
            </div>
            <div class="grid-3 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">Слоты Min</label><input id="tp-mu-min" type="number" class="form-control"></div>
                <div><label class="lbl-xs">Слоты Max</label><input id="tp-mu-max" type="number" class="form-control"></div>
                <div><label class="lbl-xs">Старт</label><input id="tp-mu-start" type="number" class="form-control"></div>
            </div>
            <div class="grid-3 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">На торр. Min</label><input id="tp-pt-up-min" type="number" class="form-control"></div>
                <div><label class="lbl-xs">На торр. Max</label><input id="tp-pt-up-max" type="number" class="form-control"></div>
                <label class="row-gap pointer lbl-xs" style="align-self:end; padding-bottom:6px;"><input id="tp-pt-up-auto" type="checkbox"> Авто 28%</label>
            </div>
            <div class="grid-3 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">Соед. Min</label><input id="tp-mc-min" type="number" class="form-control"></div>
                <div><label class="lbl-xs">Соед. Max</label><input id="tp-mc-max" type="number" class="form-control"></div>
                <label class="row-gap pointer lbl-xs" style="align-self:end; padding-bottom:6px;"><input id="tp-mc-auto" type="checkbox"> Авто ×4</label>
            </div>
            <div class="grid-2 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">Connec/torr Min..Max</label><div class="row-gap"><input id="tp-pt-con-min" type="number" class="form-control"><input id="tp-pt-con-max" type="number" class="form-control"></div></div>
                <div><label class="lbl-xs">max_active_uploads</label><div class="row-gap"><select id="tp-act-mode" class="form-control"><option value="keep">Не менять</option><option value="range">Диапазон</option><option value="fixed">Фикс</option></select><input id="tp-act-min" type="number" class="form-control" style="width:55px;"><input id="tp-act-max" type="number" class="form-control" style="width:55px;"></div></div>
            </div>
            <div class="grid-3 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">Цель канала %</label><div class="row-gap"><input id="tp-ch-min" type="number" class="form-control"><input id="tp-ch-max" type="number" class="form-control"></div></div>
                <div><label class="lbl-xs">Потолок Up % (0=∞)</label><input id="tp-up-pct" type="number" class="form-control"></div>
                <div><label class="lbl-xs">Потолок DL % (0=∞)</label><input id="tp-dl-pct" type="number" class="form-control"></div>
            </div>
            <div class="row-wrap mb-8" style="gap:6px;">
                <label class="row-gap pointer lbl-xs"><input id="tp-sq-en" type="checkbox"> Ужимать Up/DL %:</label>
                <input id="tp-sq-up" type="number" class="form-control" style="width:55px;">
                <input id="tp-sq-dl" type="number" class="form-control" style="width:55px;">
                <span class="lbl-xs">Кулдаун(с):</span><input id="tp-cd-sec" type="number" class="form-control" style="width:62px;">
                <span class="lbl-xs">Шаг+:</span><input id="tp-step-up" type="number" class="form-control" style="width:52px;">
                <label class="row-gap pointer lbl-xs"><input id="tp-yield-turtle" type="checkbox"> Уступать «Черепахе»</label>
            </div>
            <div class="col-gap" style="font-size:11px; border-top:1px dashed var(--border); padding-top:6px;">
                <div class="row-gap"><label style="width:95px;"><input id="tp-g-disk-en" type="checkbox"> Диск %</label><input id="tp-g-disk-warn" type="number" class="form-control" title="Тревога"><input id="tp-g-disk-crit" type="number" class="form-control" title="Крит"><input id="tp-g-disk-rec" type="number" class="form-control" title="Возврат"></div>
                <div class="row-gap"><label style="width:95px;"><input id="tp-g-cpu-en" type="checkbox"> Чужой CPU %</label><input id="tp-g-cpu-warn" type="number" class="form-control" title="Тревога"><input id="tp-g-cpu-rec" type="number" class="form-control" title="Возврат"></div>
                <div class="row-gap"><label style="width:95px;"><input id="tp-g-ram-en" type="checkbox"> Своб. RAM %</label><input id="tp-g-ram-min" type="number" class="form-control" title="Мин."><input id="tp-g-ram-rec" type="number" class="form-control" title="Возврат"></div>
                <div class="row-gap"><label style="width:95px;"><input id="tp-g-net-en" type="checkbox"> Чужая сеть %</label><input id="tp-g-net-warn" type="number" class="form-control" title="Тревога"><input id="tp-g-net-rec" type="number" class="form-control" title="Возврат"></div>
            </div>
        </div>

        <div style="background:var(--bg-input); padding:10px; border-radius:6px; border:1px solid var(--border);">
            <div class="row-between mb-8">
                <span class="lbl-sm" style="margin:0;">🧠 ПРАВИЛА АВТОПЕРЕКЛЮЧЕНИЯ</span>
                <button class="btn btn-xs" onclick="saveTunerRules()">💾 Правила</button>
            </div>
            <div class="grid-2 mb-8" style="gap:6px;">
                <div><label class="lbl-xs">Режим по умолчанию:</label><select id="tr-def-mode" class="form-control"><option value="performance">Производительность</option><option value="comfort">Комфорт</option></select></div>
                <div><label class="lbl-xs">Ручной Override:</label><select id="tr-ov-policy" class="form-control"><option value="2h">На 2 часа</option><option value="until_schedule">До смены расписания</option><option value="until_process_exit">До закрытия процесса</option></select></div>
            </div>
            <div class="mb-8" style="border-top:1px dashed var(--border); padding-top:6px;">
                <div class="row-between mb-8"><span class="lbl-xs"><b>⏰ Расписание (переход ч/з полночь поддерживается):</b></span><button class="btn btn-secondary btn-xs" onclick="addTunerScheduleRow()">+ Окно</button></div>
                <div id="tr-sched-list" class="col-gap" style="max-height:95px; overflow-y:auto;"></div>
            </div>
            <div class="mb-8" style="border-top:1px dashed var(--border); padding-top:6px;">
                <div class="row-between mb-8">
                    <label class="row-gap pointer lbl-xs"><input id="tr-proc-en" type="checkbox"> <b>🎮 Процессы (Watchlist)</b></label>
                    <div class="row-gap"><select id="tr-proc-mode" class="form-control" style="padding:2px; font-size:11px;"><option value="comfort">→ Комфорт</option><option value="performance">→ Производ.</option></select><button class="btn btn-secondary btn-xs" onclick="loadRunningProcessesPicker()">🖥️ Процессы ПК</button></div>
                </div>
                <input id="tr-proc-names" class="form-control mb-8" placeholder="cs2.exe, dota2.exe, obs64.exe">
                <div id="tr-proc-picker" class="hidden row-wrap mb-8" style="max-height:80px; overflow-y:auto; gap:4px;"></div>
                <div class="row-gap lbl-xs"><span>Вход(с):</span><input id="tr-proc-enter" type="number" class="form-control" style="width:60px;"><span>Возврат(с):</span><input id="tr-proc-exit" type="number" class="form-control" style="width:65px;"></div>
            </div>
            <div style="border-top:1px dashed var(--border); padding-top:6px;">
                <div class="row-between mb-8">
                    <label class="row-gap pointer lbl-xs"><input id="tr-ext-en" type="checkbox"> <b>⚡ Внешняя нагрузка</b></label>
                    <select id="tr-ext-mode" class="form-control" style="width:115px; padding:2px; font-size:11px;"><option value="comfort">→ Комфорт</option><option value="performance">→ Производ.</option></select>
                </div>
                <div class="grid-3 mb-8" style="gap:4px;">
                    <div><label class="lbl-xs">CPU Вход/Вых</label><div class="row-gap"><input id="tr-ext-cpu-w" type="number" class="form-control"><input id="tr-ext-cpu-r" type="number" class="form-control"></div></div>
                    <div><label class="lbl-xs">Сеть% Вх/Вых</label><div class="row-gap"><input id="tr-ext-net-w" type="number" class="form-control"><input id="tr-ext-net-r" type="number" class="form-control"></div></div>
                    <div><label class="lbl-xs">RAM Мин/Возв</label><div class="row-gap"><input id="tr-ext-ram-w" type="number" class="form-control"><input id="tr-ext-ram-r" type="number" class="form-control"></div></div>
                </div>
                <div class="row-gap lbl-xs"><span>Вход(с):</span><input id="tr-ext-enter" type="number" class="form-control" style="width:60px;"><span>Возврат(с):</span><input id="tr-ext-exit" type="number" class="form-control" style="width:65px;"></div>
            </div>
        </div>
    </div>
</div>
```

---

#### `web/templates/partials/tab_automation.html`
```html
<!-- TAB 5: Автопилот -->
    <div id="tab-automation" class="tab-content col-wide">
        <div class="card">
            <div class="row-between mb-10">
                <div class="card-title" style="margin-bottom:0;" data-i18n="card_automation">🤖 АВТОПИЛОТ И УВЕДОМЛЕНИЯ (TELEGRAM / DISCORD)</div>
                <span id="auto-status-msg" class="lbl-xs accent-txt"></span>
            </div>
            <div class="grid-2 mb-10">
                <div class="autostart-box" style="margin-bottom:0;">
                    <label class="row-gap pointer" style="font-size:13px; font-weight:700;">
                        <input type="checkbox" id="auto-enabled"> <span data-i18n="auto_enable">Включить фоновый автопилот</span>
                    </label>
                    <div class="row-gap">
                        <span class="lbl-xs muted-text" data-i18n="auto_interval">Раз в (мин):</span>
                        <input type="number" id="auto-interval" class="form-control" style="width:70px;" min="1" max="1440" value="5">
                    </div>
                </div>
                <div class="row-gap" style="justify-content: flex-end; flex-wrap:wrap;">
                    <button class="btn btn-secondary" onclick="runAutopilotDryRun()">🧪 Прогнать вхолостую</button>
                    <button class="btn btn-secondary" onclick="testNotifications()" data-i18n="btn_test">🔔 Тест</button>
                    <button class="btn btn-secondary" onclick="runAutomationNow()" data-i18n="btn_run_now">⚡ Проверить сейчас</button>
                    <button class="btn" onclick="saveAutomationSettings()" data-i18n="btn_save">💾 Сохранить</button>
                </div>
            </div>

            <div class="card mb-10" style="background:var(--bg-input); border:1px solid var(--border); padding:8px 12px;">
                <div class="lbl-sm mb-6" style="color:var(--warning); font-weight:700;">🚨 СИСТЕМНЫЕ АЛЕРТЫ И РЕАНИМАЦИЯ (TG / DISCORD)</div>
                <div class="row-wrap" style="gap:14px;">
                    <div class="row-gap">
                        <span class="lbl-xs">Алерт, если на диске меньше:</span>
                        <input type="number" id="auto-alert-disk" class="form-control" style="width:80px;" placeholder="0" min="0" step="5">
                        <span class="lbl-xs muted-text">GiB (0 = выкл, гистерезис +5 GiB)</span>
                    </div>
                    <label class="row-gap pointer lbl-xs">
                        <input type="checkbox" id="auto-alert-qb"> Алерт при отвале WebUI qBittorrent (> 2.5 мин)
                    </label>
                    <label class="row-gap pointer lbl-xs">
                        <input type="checkbox" id="auto-recheck-io"> Авто-перепроверка при ошибках диска (I/O, макс. 1 попытка -> тег io-error)
                    </label>
                </div>
            </div>

            <div class="grid-3 mb-10">
                <div class="form-group">
                    <label class="row-between"><span data-i18n="lbl_tg_token">Telegram Bot Token:</span><button type="button" class="btn btn-secondary btn-xs" onclick="openBotGuide('tg')">?</button></label>
                    <input type="password" id="auto-tg-token" class="form-control" placeholder="123456:ABC-DEF...">
                </div>
                <div class="form-group">
                    <label data-i18n="lbl_tg_chat">Telegram Chat ID:</label>
                    <input type="text" id="auto-tg-chat" class="form-control" placeholder="123456789">
                </div>
                <div class="form-group">
                    <label class="row-between"><span data-i18n="lbl_discord">Discord Webhook URL:</span><button type="button" class="btn btn-secondary btn-xs" onclick="openBotGuide('discord')">?</button></label>
                    <input type="password" id="auto-discord" class="form-control" placeholder="https://discord.com/api/webhooks/...">
                </div>
            </div>

            <div class="card" style="background:var(--bg-input); border:1px solid var(--border); padding:10px 12px;">
                <div class="row-between mb-8">
                    <span class="lbl-sm" style="margin:0; color:var(--info); font-weight:700;">🌙 «ТИХИЙ ЧАС» (DND) И ДАЙДЖЕСТ В БОТОВ</span>
                    <button class="btn btn-secondary btn-xs" onclick="saveDndDigestSchedule()">💾 Сохранить расписание</button>
                </div>
                <div class="grid-2" style="gap:12px;">
                    <div>
                        <label class="row-gap pointer lbl-xs mb-8">
                            <input type="checkbox" id="dnd-enabled"> <b>Включить «Тихий час»</b> (критические тревоги пробивают)
                        </label>
                        <div class="row-gap mb-8" style="gap:6px;">
                            <span class="lbl-xs">С:</span><input type="time" id="dnd-start" class="form-control" style="width:100px;" value="23:00">
                            <span class="lbl-xs">До:</span><input type="time" id="dnd-end" class="form-control" style="width:100px;" value="08:00">
                        </div>
                        <div class="row-wrap" style="gap:6px;">
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="0" checked> Пн</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="1" checked> Вт</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="2" checked> Ср</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="3" checked> Чт</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="4" checked> Пт</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="5" checked> Сб</label>
                            <label class="lbl-xs"><input type="checkbox" class="dnd-day-chk" value="6" checked> Вс</label>
                        </div>
                    </div>
                    <div>
                        <label class="lbl-sm">Авто-дайджест статистики:</label>
                        <div class="row-wrap" style="gap:6px;">
                            <select id="digest-mode" class="form-control" style="width:140px;">
                                <option value="off">Выключен</option><option value="daily">Ежедневно</option><option value="weekly">Еженедельно</option>
                            </select>
                            <input type="number" id="digest-hour" class="form-control" style="width:65px;" min="0" max="23" value="21" title="Час отправки">
                            <select id="digest-weekday" class="form-control" style="width:95px;">
                                <option value="0">Пн</option><option value="1">Вт</option><option value="2">Ср</option>
                                <option value="3">Чт</option><option value="4">Пт</option><option value="5">Сб</option><option value="6" selected>Вс</option>
                            </select>
                        </div>
                        <div class="lbl-xs muted-text mt-10">Если ПК был выключен, бот дошлёт сводку при старте.</div>
                    </div>
                </div>
            </div>
        </div>

        {% include 'partials/tab_tuner.html' %}
        {% include 'partials/tab_auto_extras.html' %}

        <div id="rule-form-card" class="card">
            <div id="rule-form-title" class="card-title" data-i18n="card_add_rule">➕ ДОБАВИТЬ ПРАВИЛО</div>
            <div class="row-wrap mb-8">
                <div class="grow-1"><label class="lbl-sm" data-i18n="lbl_rule_name">Название:</label><input type="text" id="rule-name" class="form-control" placeholder="Напр: Стоп после 2.0x и 14 дней" data-i18n-ph="rule_name_ph"></div>
                <div style="width:140px;"><label class="lbl-sm">Метрика времени:</label><select id="rule-time-mode" class="form-control"><option value="seeding_time">Время сида</option><option value="time_active">Время актива</option></select></div>
                <div style="width:95px;"><label class="lbl-sm" data-i18n="lbl_rule_ratio">Мин. Ratio:</label><input type="number" step="0.1" min="0" id="rule-ratio" class="form-control" placeholder="2.0"></div>
                <div style="width:95px;"><label class="lbl-sm" data-i18n="lbl_rule_days">Мин. дней:</label><input type="number" step="0.5" min="0" id="rule-days" class="form-control" placeholder="14"></div>
                <div style="width:170px;">
                    <label class="lbl-sm">Мин. отдано:</label>
                    <div class="row-gap">
                        <input type="number" step="0.1" min="0" id="rule-up-val" class="form-control" placeholder="500">
                        <select id="rule-up-unit" class="form-control" style="width:76px;"><option value="MiB">MiB</option><option value="GiB" selected>GiB</option><option value="TiB">TiB</option></select>
                    </div>
                </div>
            </div>
            <div class="row-wrap mb-10">
                <div style="width:320px;">
                    <label class="lbl-sm">Средняя скорость (окно W мин):</label>
                    <div class="row-gap">
                        <select id="rule-speed-op" class="form-control" style="width:75px;"><option value="">выкл</option><option value=">=">&gt;=</option><option value="<">&lt;</option></select>
                        <input type="number" step="0.1" min="0" id="rule-speed-val" class="form-control" placeholder="100">
                        <select id="rule-speed-unit" class="form-control" style="width:82px;"><option value="KiB">KiB/s</option><option value="MiB">MiB/s</option></select>
                        <input type="number" min="1" max="10080" id="rule-speed-win" class="form-control" style="width:70px;" value="60" title="Окно W в минутах">
                    </div>
                </div>
                <div style="width:130px;"><label class="lbl-sm" data-i18n="lbl_rule_tag">Повесить тег:</label><input type="text" id="rule-tag" class="form-control" placeholder="done (опц.)" data-i18n-ph="rule_tag_ph"></div>
                <div style="width:130px;"><label class="lbl-sm">Снять тег:</label><input type="text" id="rule-remove-tag" class="form-control" placeholder="active (опц.)"></div>
                <div class="row-gap" style="align-self:flex-end; padding-bottom: 4px;">
                    <label class="row-gap pointer lbl-xs"><input type="checkbox" id="rule-pause"> <span data-i18n="chk_pause">⏸️ Пауза</span></label>
                    <label class="row-gap pointer lbl-xs"><input type="checkbox" id="rule-notify" checked> <span data-i18n="chk_notify">📣 Уведомить</span></label>
                    <button id="btn-rule-submit" class="btn" onclick="submitAutomationRule()" data-i18n="btn_add">➕ Добавить</button>
                    <button id="btn-rule-cancel" class="btn btn-secondary hidden" onclick="cancelEditRule()" data-i18n="btn_cancel">Отмена</button>
                </div>
            </div>
            <div class="scroll-box" style="max-height: 260px;">
                <table>
                    <thead><tr><th data-i18n="th_rule_name">Название</th><th data-i18n="th_rule_cond">Условие</th><th data-i18n="th_rule_act">Действия</th><th data-i18n="th_rule_status">Статус</th><th data-i18n="th_rule_ctrl">Управление</th></tr></thead>
                    <tbody id="rules-tbody"><tr><td colspan="5" class="center-msg" data-i18n="no_rules">Нет правил</td></tr></tbody>
                </table>
            </div>
        </div>

        <div class="card" id="tagging-rules-card">
            <div class="card-title">🏷️ ПРАВИЛА АВТО-ТЕГИРОВАНИЯ (ПО ТРЕКЕРУ ИЛИ ПУТИ)</div>
            <div class="row-wrap mb-10" style="gap:8px;">
                <input type="text" id="tag-rule-name" class="form-control" style="width:160px;" placeholder="Название (опц.)">
                <select id="tag-rule-field" class="form-control" style="width:155px;"><option value="tracker">URL трекера содержит</option><option value="save_path">Путь содержит</option></select>
                <input type="text" id="tag-rule-pattern" class="form-control grow-1" placeholder="Напр: rutracker или D:\Games">
                <input type="text" id="tag-rule-target" class="form-control" style="width:130px;" placeholder="Целевой тег">
                <button class="btn" onclick="addTaggingRule()">➕ Добавить</button>
            </div>
            <div class="scroll-box" style="max-height: 200px;">
                <table>
                    <thead><tr><th>Название</th><th>Условие</th><th>Тег</th><th>Статус</th><th>Управление</th></tr></thead>
                    <tbody id="tagging-rules-tbody"><tr><td colspan="5" class="center-msg">Загрузка...</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>
```

---

#### `web/templates/index.html`
```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="csrf-token" content="{{ csrf_token }}">
    <meta name="theme-color" content="#1a1a20">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="manifest" href="/manifest.json">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <title>tbr PRO — Швейцарский нож qBittorrent</title>
    <link rel="stylesheet" href="/static/style.css?v={{ v }}">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
</head>
<body>
<header>
    <div class="row-gap">
        <svg class="logo-svg" viewBox="0 0 48 48" fill="none">
            <rect width="48" height="48" rx="10" fill="#1A1A20"/>
            <path d="M26 6L12 26H24L20 42L36 22H24L26 6Z" fill="#2ECC71" stroke="#2ECC71" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span class="logo-text">tbr PRO</span>
        <span id="qb-status-badge" class="badge badge-pause pointer" onclick="toggleQbPower()" data-i18n="qb_loading">⏳ qB...</span>
        <span id="tuner-header-badge" class="badge badge-pause pointer admin-only" onclick="switchTab('automation')" title="Адаптивный авто-тюнер qB">🎛️ Тюнер: Выкл</span>
        <button id="update-available-badge" class="btn btn-xs hidden" style="background:var(--warning); color:#000;" onclick="openUpdateModal(false)">⬆️ Доступно обновление</button>
    </div>
    <div class="nav-tabs">
        <button class="tab-btn active" data-tab="torrents" onclick="switchTab('torrents')" data-i18n="tab_torrents">⚡ Раздачи</button>
        <button class="tab-btn" data-tab="merger" onclick="switchTab('merger')" data-i18n="tab_merger">🔀 Подменщик</button>
        <button class="tab-btn" data-tab="summary" onclick="switchTab('summary')" data-i18n="tab_summary">📊 Сводка</button>
        <button class="tab-btn" data-tab="analytics" onclick="switchTab('analytics')" data-i18n="tab_analytics">📈 Аналитика</button>
        <button class="tab-btn" data-tab="automation" onclick="switchTab('automation')" data-i18n="tab_automation">🤖 Автопилот</button>
        <button class="tab-btn" data-tab="tools" onclick="switchTab('tools')" data-i18n="tab_tools">🛠️ Инструменты</button>
    </div>
    <div class="row-gap">
        <button class="btn btn-secondary" title="Палитра команд (Ctrl+K)" onclick="openCommandPalette()">🔍 Ctrl+K</button>
        <button id="btn-smart-freeze" class="btn btn-secondary admin-only" title="Заморозить/возобновить только активные раздачи" onclick="toggleSmartFreeze()">❄️ Заморозка</button>
        <button id="btn-snooze-timer" class="btn btn-secondary admin-only" title="Таймер сна для торрентов" onclick="openSnoozeModal()">😴 Сон</button>
        <button id="btn-panic-killswitch" class="btn btn-danger admin-only" title="Экстренная остановка всех раздач (на мобильном удерживайте 2с)" onclick="onPanicBtnClick()">🚨 Экстренная пауза</button>
        <button class="btn btn-secondary" title="Обновить текущую вкладку" onclick="refreshActiveTab()">↻</button>
        <button id="lang-toggle-btn" class="btn btn-secondary" onclick="toggleLang()">🌐 RU</button>
        <button class="btn btn-secondary" onclick="openCustomizeModal()">🎨 Оформление</button>
        <button class="btn btn-secondary" title="Сменить свой пароль" onclick="changeSelfPassword()">🔑</button>
        <button class="btn btn-secondary admin-only" onclick="openSettingsModal()" data-i18n="btn_settings">⚙️ Настройки</button>
        <button class="btn btn-secondary admin-only" onclick="restartQb()" data-i18n="btn_restart_qb">🔄 Перезапуск qB</button>
        {% if auth_enabled %}
        <a href="/logout" class="btn btn-danger" data-i18n="btn_logout">🚪 Выйти</a>
        {% endif %}
    </div>
</header>

<main>
    <div id="tab-torrents" class="tab-content active">
        <div class="torrent-left">
            <div class="table-toolbar">
                <input type="text" id="search-box" class="search-input" placeholder="🔍 Поиск раздач..." data-i18n-ph="search_ph" oninput="filterTorrents()">
                <select id="filter-tag-select" class="form-control" style="width:120px; font-size:12px;" onchange="filterTorrents()"><option value="">Все теги</option></select>
                <select id="filter-tracker-select" class="form-control" style="width:130px; font-size:12px;" onchange="filterTorrents()"><option value="">Все трекеры</option></select>
                <select id="filter-tracker-err-select" class="form-control" style="width:165px; font-size:12px;" onchange="filterTorrents()">
                    <option value="">Проблемы с трекерами</option><option value="any">⚠️ Любая ошибка</option>
                    <option value="unregistered">🚫 Не зарегистрирована</option><option value="auth">🔑 Ошибка passkey/авторизации</option>
                    <option value="timeout">⏱️ Превышен таймаут</option><option value="other">❓ Прочие ошибки</option>
                </select>
                <button class="btn btn-xs admin-only" onclick="openPreflightModal()">➕ Добавить</button>
                <button class="btn btn-secondary admin-only" onclick="scanDeadTorrents()" data-i18n="btn_scan_dead">🩺 Мёртвые</button>
                <button class="btn btn-secondary" onclick="loadTorrents(true)" data-i18n="btn_refresh">🔄</button>
            </div>
            <div id="saved-views-bar" class="row-wrap" style="padding:5px 12px; border-bottom:1px solid var(--border); gap:6px;"></div>
            <div id="bulk-actions-bar" class="row-between hidden" style="background:var(--bg-input); padding:6px 12px; border-bottom:1px solid var(--border);">
                <span class="lbl-xs">Выбрано раздач: <b id="bulk-selected-count" class="accent-txt">0</b></span>
                <div class="row-gap" style="gap:6px;">
                    <button class="btn btn-secondary btn-xs" onclick="bulkTorrentAction('stop')">⏸️ Пауза</button>
                    <button class="btn btn-secondary btn-xs" onclick="bulkTorrentAction('start')">▶️ Пуск</button>
                    <button class="btn btn-secondary btn-xs" onclick="bulkTorrentAction('addTags')">🏷️ +Тег</button>
                    <button class="btn btn-secondary btn-xs" onclick="bulkTorrentAction('removeTags')">✂️ -Тег</button>
                </div>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th style="width:28px;"><input type="checkbox" onchange="toggleSelectAllVisible(this)" title="Выбрать все видимые"></th>
                            <th onclick="sortTable('name')"><span data-i18n="th_name">Имя раздачи</span> <span id="sort-icon-name"></span></th>
                            <th onclick="sortTable('size')"><span data-i18n="th_size">Размер</span> <span id="sort-icon-size"></span></th>
                            <th onclick="sortTable('uploaded')"><span data-i18n="th_uploaded">Отдано</span> <span id="sort-icon-uploaded"></span></th>
                            <th onclick="sortTable('ratio')"><span data-i18n="th_ratio">Ratio</span> <span id="sort-icon-ratio"></span></th>
                            <th onclick="sortTable('health_score')"><span>💎 Ценность</span> <span id="sort-icon-health_score"></span></th>
                            <th onclick="sortTable('state')"><span data-i18n="th_state">Состояние</span> <span id="sort-icon-state"></span></th>
                            <th onclick="sortTable('save_path')"><span data-i18n="th_path">Путь</span> <span id="sort-icon-save_path"></span></th>
                        </tr>
                    </thead>
                    <tbody id="torrents-tbody"><tr><td colspan="8" class="center-msg" data-i18n="loading_torrents">Загрузка раздач...</td></tr></tbody>
                </table>
            </div>
        </div>
        <div class="torrent-right">
            <div class="card">
                <div class="card-title" data-i18n="card_selected">ВЫБРАННАЯ РАЗДАЧА</div>
                <div id="selected-title" class="muted-text" style="margin-bottom: 10px; overflow:hidden; text-overflow:ellipsis;" data-i18n="select_left">Выберите раздачу слева</div>
                <div class="grid-3 mb-10">
                    <button class="btn btn-secondary admin-only" onclick="torrentAction('stop')" data-i18n="btn_pause">⏸️ Пауза</button>
                    <button class="btn btn-secondary admin-only" onclick="torrentAction('start')" data-i18n="btn_start">▶️ Пуск</button>
                    <button class="btn btn-secondary admin-only" onclick="torrentAction('setForceStart')" data-i18n="btn_force">⚡ Форс</button>
                </div>
                <button class="btn w-full center-btn mb-8" onclick="goToAnalyticsWithTorrent()" data-i18n="btn_forecast">🔮 Рассчитать прогноз</button>
                <button class="btn btn-secondary w-full center-btn mb-8" onclick="openTorrentInspectorModal()">🔬 Пиры, заметки и файлы</button>
                <div class="grid-2 mb-8">
                    <button class="btn btn-secondary center-btn admin-only" onclick="openTargetModal()">🎯 Цель</button>
                    <button class="btn btn-secondary center-btn admin-only" onclick="openExpirationModal()">⏳ Срок</button>
                </div>
                <div class="grid-2 mb-8">
                    <button class="btn btn-secondary center-btn admin-only" onclick="toggleSelectedSniper()">📡 Маячок</button>
                    <button class="btn btn-secondary center-btn admin-only" onclick="enqueueSelectedRecheck()">💽 Речек (очер.)</button>
                </div>
                <button class="btn btn-danger w-full center-btn admin-only" onclick="deleteSelectedTorrent()">🗑️ Удалить раздачу</button>
            </div>
            <div class="card danger-border admin-only">
                <div class="card-title" style="color: var(--danger);" data-i18n="card_seedbox">УПРАВЛЕНИЕ ВСЕМ СИДБОКСОМ</div>
                <p class="muted-text mb-10" data-i18n="seedbox_desc">Остановить или запустить все раздачи в клиенте:</p>
                <div class="col-gap">
                    <button class="btn btn-danger w-full center-btn" onclick="globalTorrentAction('stop')" data-i18n="btn_pause_all">⏸️ ОСТАНОВИТЬ ВСЕ</button>
                    <button class="btn w-full center-btn" onclick="globalTorrentAction('start')" data-i18n="btn_resume_all">▶️ ВОЗОБНОВИТЬ ВСЕ</button>
                </div>
            </div>
        </div>
    </div>

    <div id="tab-merger" class="tab-content col-center">
        <div id="smart-match-card" class="card mb-12">
            <div class="row-between mb-8">
                <div class="card-title" style="margin:0;">✨ НАЙДЕНЫ КАНДИДАТЫ НА ОБЪЕДИНЕНИЕ (SMART MATCH)</div>
                <button class="btn btn-secondary btn-xs" onclick="loadSmartMatchCandidates()">🔎 Обновить подбор</button>
            </div>
            <div id="smart-match-list" class="col-gap" style="max-height:160px; overflow-y:auto; font-size:12px;"><span class="muted-text">Поиск похожих раздач...</span></div>
        </div>
        <div class="card">
            <div class="card-title" data-i18n="card_merger">🔄 ПОДМЕНЩИК РАЗДАЧ (.FASTRESUME)</div>
            <p class="muted-text mb-10" data-i18n="merger_desc">qBittorrent выгружается перед подменой и перезапускается автоматически — бенкод не пострадает.</p>
            <div class="form-group"><label data-i18n="lbl_old_tor">1. Исходная раздача (старая):</label><select id="merger-old" class="form-control" onchange="onMergerSelectionChange()"></select></div>
            <div class="form-group"><label data-i18n="lbl_new_tor">2. Целевая раздача (приёмник):</label><select id="merger-new" class="form-control" onchange="onMergerSelectionChange()"></select></div>
            <div class="form-group"><label>3. Режим переноса статистики:</label><select id="merger-mode" class="form-control" onchange="updateMergerCalcPreview()"><option value="add" selected>➕ Сложить (рекомендуется, если на цели уже есть отдача)</option><option value="replace">🔄 Заменить (переписать статистику цели начисто)</option></select></div>
            <div id="merger-calc-preview" class="card mb-8" style="background:var(--bg-input); padding:8px 12px; border-radius:6px; border:1px solid var(--border);"><div class="row-between"><span class="lbl-xs">Итоговый расчёт отдачи:</span><b id="merger-calc-txt" class="accent-txt">—</b></div></div>
            <div id="merger-dup-warn" class="lbl-xs hidden mb-8" style="color:var(--warning); background:rgba(243,156,18,0.12); padding:6px 10px; border-radius:6px; border:1px solid rgba(243,156,18,0.3);">⚠️ Внимание: эти раздачи уже объединялись ранее!</div>
            <div class="form-group"><label data-i18n="lbl_del_mode">4. Исходная раздача после переноса:</label><select id="merger-delete-mode" class="form-control" onchange="onMergerDeleteModeChange()"><option value="none" data-i18n="del_mode_none">Не удалять (оставить всё)</option><option value="safe" data-i18n="del_mode_safe">Удалить всё (безопасно: с проверкой путей)</option><option value="force" data-i18n="del_mode_force">Удалить всё (принудительно: файлы с диска)</option></select></div>
            <div id="merger-force-warn" class="lbl-xs hidden" style="color: var(--danger); margin-bottom: 8px;" data-i18n="del_force_warn">⚠️ ОПАСНО: принудительный режим удалит файлы с диска, даже если пути исходника и получателя совпадают!</div>
            <div class="grid-2 mt-10"><button id="btn-merger-diff" class="btn btn-secondary w-full center-btn" onclick="openTorrentDiffModal()">🔍 Сравнить файлы раздач</button><button class="btn w-full center-btn" onclick="runMerger()" data-i18n="btn_merge">🚀 ПЕРЕНЕСТИ СТАТИСТИКУ</button></div>
        </div>
        <div class="card mt-12"><div class="card-title" data-i18n="card_op_log">ЛОГ ОПЕРАЦИИ</div><div id="merger-log" class="terminal" data-i18n="ready">Готов к работе...</div></div>
    </div>

    <div id="tab-summary" class="tab-content col-wide">
        <div class="grid-cards mb-12">
            <div class="card"><div class="lbl-sm" data-i18n="sum_count">Раздач:</div><div id="sum-count" class="val-lg">-</div></div>
            <div class="card"><div class="lbl-sm" data-i18n="sum_size">Общий объем:</div><div id="sum-size" class="val-lg">-</div></div>
            <div class="card"><div class="lbl-sm" data-i18n="sum_uploaded">Всего отдано:</div><div id="sum-uploaded" class="val-lg accent-txt">-</div></div>
            <div class="card"><div class="lbl-sm" data-i18n="sum_1h">Сумма за 1 час:</div><div id="sum-global-hour" class="val-md purple-txt">-</div><div id="sum-global-hour-speed" class="lbl-xs purple-txt">-</div><div id="sum-global-hour-note" class="lbl-xs muted-text"></div></div>
            <div class="card"><div class="lbl-sm" data-i18n="sum_day">Объем в день:</div><div id="sum-global-day" class="val-md orange-txt">-</div><div id="sum-global-day-speed" class="lbl-xs orange-txt">-</div></div>
            <div class="card"><div class="lbl-sm" data-i18n="sum_ratio_h">Ratio/ч (всего / 24ч):</div><div id="sum-ratio-h" class="val-sm blue-txt">-</div></div>
        </div>
        <div id="summary-equivalents-bar" class="card mb-12 hidden" style="padding:8px 12px; font-size:12px;"></div>
        <div class="card row-wrap mb-12">
            <div class="grow-1"><label class="lbl-sm" data-i18n="lbl_search">Поиск:</label><input type="text" id="sum-filter-search" class="form-control" placeholder="Фильтр..." data-i18n-ph="filter_ph" oninput="applySummaryFilters()"></div>
            <div style="width:110px"><label class="lbl-sm" data-i18n="lbl_min_ratio">Мин. Ratio:</label><input type="number" step="0.5" id="sum-filter-ratio" class="form-control" oninput="applySummaryFilters()"></div>
            <div style="width:130px"><label class="lbl-sm" data-i18n="lbl_min_up">Мин. отдано (ГБ):</label><input type="number" id="sum-filter-uploaded" class="form-control" oninput="applySummaryFilters()"></div>
            <div class="row-gap" style="align-self:flex-end; flex-wrap:wrap;">
                <button id="btn-live-filter" class="btn btn-secondary" onclick="toggleSummaryLiveFilter()">📡 Прямой эфир</button>
                <button id="btn-last-seed-filter" class="btn btn-secondary" onclick="toggleSummaryLastSeedFilter()">🛡️ Последний сид</button>
                <button class="btn btn-secondary" onclick="sortSummary('health_score')">💎 По ценности</button>
                <button class="btn btn-secondary" onclick="loadSummary(true)" data-i18n="btn_refresh">🔄 Обновить</button>
                <button id="btn-toggle-mobile-cards" class="btn btn-secondary" onclick="toggleMobileCardsMode()">📋 Таблица</button>
                <div style="position:relative;"><button class="btn btn-secondary" onclick="toggleSummaryColsMenu()">🧱 Столбцы</button><div id="summary-cols-menu" class="card hidden" style="position:absolute; right:0; top:34px; z-index:50; min-width:160px;"></div></div>
                <button class="btn btn-secondary" onclick="resetSummaryFilters()" data-i18n="btn_reset">Сброс</button>
                <button class="btn" onclick="exportFilteredSummaryCSV()" data-i18n="btn_export_csv">📥 Экспорт выборки</button>
            </div>
        </div>
        <div id="summary-table-wrap" class="card flex-scroll"><table id="summary-table"><thead id="summary-thead"><tr id="summary-thead-row"></tr></thead><tbody id="summary-tbody"></tbody></table></div>
    </div>

    {% include 'partials/tab_analytics.html' %}
    {% include 'partials/tab_automation.html' %}
    {% include 'partials/tab_tools.html' %}
</main>

<footer class="app-footer">
    <a href="{{ releases_url }}" target="_blank" class="version-pill" title="Открыть релизы на GitHub">⚡ tbr PRO v{{ app_version }}</a>
    <a href="/kiosk" target="_blank" class="btn btn-secondary btn-xs">🖥️ Режим Киоск</a>
    <span id="autopilot-freeze-badge" class="badge badge-stall hidden">❄️ Автопилот заморожен</span>
    <button class="btn btn-secondary btn-xs admin-only" onclick="openUpdateModal(true)">🔄 Ченджлог и обновление</button>
</footer>

{% include 'partials/modals.html' %}

<div id="dry-run-modal" class="modal-backdrop"><div class="modal" style="max-width:740px; max-height:85vh; display:flex; flex-direction:column;">
    <div class="row-between mb-8"><div class="card-title" style="margin:0;">🧪 ПЕСОЧНИЦА АВТОПИЛОТА (DRY-RUN)</div><button class="btn btn-secondary btn-xs" onclick="document.getElementById('dry-run-modal').style.display='none'">✕</button></div>
    <div id="dry-run-summary" class="lbl-xs muted-text mb-8">—</div>
    <div class="scroll-box" style="flex:1; max-height:55vh; border:1px solid var(--border); border-radius:6px;">
        <table><thead><tr><th>Раздача / Правило</th><th>Ratio</th><th>Отдано</th><th>Планируемые действия</th></tr></thead><tbody id="dry-run-tbody"></tbody></table>
    </div>
</div></div>

<div id="qb-diff-modal" class="modal-backdrop"><div class="modal" style="max-width:780px; max-height:85vh; display:flex; flex-direction:column;">
    <div class="row-between mb-8"><div class="card-title" style="margin:0;">🔍 DIFF КОНФИГОВ qBITTORRENT</div><button class="btn btn-secondary btn-xs" onclick="document.getElementById('qb-diff-modal').style.display='none'">✕</button></div>
    <div class="row-wrap mb-8" style="gap:6px;">
        <select id="qb-diff-a" class="form-control grow-1" onchange="runQbConfigDiff()"></select>
        <select id="qb-diff-b" class="form-control grow-1" onchange="runQbConfigDiff()"></select>
        <select id="qb-diff-file" class="form-control" style="width:160px;" onchange="runQbConfigDiff()"><option>qBittorrent.ini</option><option>qBittorrent.conf</option><option>categories.json</option><option>watched_folders.json</option></select>
    </div>
    <pre id="qb-diff-out" class="terminal" style="height:320px; color:var(--text);">—</pre>
</div></div>

<div id="onboarding-modal" class="modal-backdrop"><div class="modal" style="max-width:480px;">
    <div class="card-title">🚀 МАСТЕР ПЕРВОГО ЗАПУСКА tbr PRO</div>
    <div id="onb-step-1"><p class="muted-text mb-10">Шаг 1/4: Автопоиск qBittorrent и окружения</p><div id="onb-probe-status" class="card mb-10" style="background:var(--bg-input); font-size:12px;">Проверка...</div><div class="row-between"><button class="btn btn-secondary" onclick="finishOnboarding(true)">Пропустить</button><button class="btn" onclick="_setOnbStep(2)">Далее →</button></div></div>
    <div id="onb-step-2" class="hidden"><p class="muted-text mb-10">Шаг 2/4: Подключение к WebUI qBittorrent</p><div class="grid-2 mb-8"><input id="onb-qb-ip" class="form-control" placeholder="IP"><input id="onb-qb-port" class="form-control" placeholder="Порт"></div><div class="grid-2 mb-10"><input id="onb-qb-user" class="form-control" placeholder="Логин (admin)"><input id="onb-qb-pass" type="password" class="form-control" placeholder="Пароль"></div><div class="row-between"><button class="btn btn-secondary" onclick="_setOnbStep(1)">← Назад</button><button class="btn" onclick="_setOnbStep(3)">Далее →</button></div></div>
    <div id="onb-step-3" class="hidden"><p class="muted-text mb-10">Шаг 3/4: Диски и потолок канала</p><div class="form-group"><label>Основной диск:</label><select id="onb-disk" class="form-control"></select></div><div class="form-group"><label>Потолок канала (Мбит/с):</label><input id="onb-mbps" type="number" class="form-control" value="1000"></div><div class="row-between"><button class="btn btn-secondary" onclick="_setOnbStep(2)">← Назад</button><button class="btn" onclick="_setOnbStep(4)">Далее →</button></div></div>
    <div id="onb-step-4" class="hidden"><p class="muted-text mb-12">Шаг 4/4: Всё готово к взлёту! Нажмите «Завершить», чтобы сохранить параметры и начать работу.</p><div class="row-between"><button class="btn btn-secondary" onclick="_setOnbStep(3)">← Назад</button><button class="btn" onclick="finishOnboarding(false)">✅ Завершить</button></div></div>
</div></div>

<script src="/static/common.js?v={{ v }}"></script>
<script src="/static/i18n_ru.js?v={{ v }}"></script>
<script src="/static/i18n_en.js?v={{ v }}"></script>
<script src="/static/i18n.js?v={{ v }}"></script>
<script src="/static/settings.js?v={{ v }}"></script>
<script src="/static/profiles.js?v={{ v }}"></script>
<script src="/static/customizer.js?v={{ v }}"></script>
<script src="/static/torrents_merger.js?v={{ v }}"></script>
<script src="/static/torrents.js?v={{ v }}"></script>
<script src="/static/summary.js?v={{ v }}"></script>
<script src="/static/analytics_logs.js?v={{ v }}"></script>
<script src="/static/analytics_insights.js?v={{ v }}"></script>
<script src="/static/smart_calc.js?v={{ v }}"></script>
<script src="/static/analytics_charts_render.js?v={{ v }}"></script>
<script src="/static/analytics.js?v={{ v }}"></script>
<script src="/static/tuner_ui.js?v={{ v }}"></script>
<script src="/static/automation.js?v={{ v }}"></script>
<script src="/static/system_tools.js?v={{ v }}"></script>
<script src="/static/merger_tools.js?v={{ v }}"></script>
<script src="/static/timers_ui.js?v={{ v }}"></script>
<script src="/static/palette_targets.js?v={{ v }}"></script>
<script src="/static/social_ui.js?v={{ v }}"></script>
<script src="/static/safety_ui.js?v={{ v }}"></script>
<script src="/static/hygiene_ui.js?v={{ v }}"></script>
<script src="/static/phase3_ui.js?v={{ v }}"></script>
<script src="/static/phase4_ui.js?v={{ v }}"></script>
<script src="/static/hardcore_ui.js?v={{ v }}"></script>
</body>
</html>
```

---

#### `web/static/tuner_ui.js` *(новый файл)*
```javascript
// web/static/tuner_ui.js
let _tunerProfiles = {};
let _tunerCurProfile = 'performance';
let _tunerRules = {};

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
            `).join('') : '<tr><td colspan="5" class="center-msg">Событий пока нет</td></tr>';
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
    sv('tr-def-mode', _tunerRules.default_mode || 'performance'); sv('tr-ov-policy', _tunerRules.override_policy || '2h');
    const pr = _tunerRules.processes || {}, ex = _tunerRules.external_load || {};
    sc('tr-proc-en', pr.enabled); sv('tr-proc-mode', pr.target_mode || 'comfort');
    sv('tr-proc-names', (pr.names || []).join(', ')); sv('tr-proc-enter', pr.enter_sec); sv('tr-proc-exit', pr.exit_sec);
    sc('tr-ext-en', ex.enabled); sv('tr-ext-mode', ex.target_mode || 'comfort');
    sv('tr-ext-cpu-w', ex.cpu_warn); sv('tr-ext-cpu-r', ex.cpu_recover);
    sv('tr-ext-net-w', ex.net_warn_pct); sv('tr-ext-net-r', ex.net_recover_pct);
    sv('tr-ext-ram-w', ex.ram_min_free); sv('tr-ext-ram-r', ex.ram_recover_free);
    sv('tr-ext-enter', ex.enter_sec); sv('tr-ext-exit', ex.exit_sec);
    renderTunerSchedules();
}

function renderTunerSchedules() {
    const box = document.getElementById('tr-sched-list');
    if (!box) return;
    const list = _tunerRules.schedules || [];
    box.innerHTML = list.map((s, idx) => `
        <div class="row-gap" style="gap:4px;">
            <input type="time" class="form-control" style="width:92px;" value="${escapeHtml(s.start)}" onchange="_tunerRules.schedules[${idx}].start=this.value">
            <span>—</span>
            <input type="time" class="form-control" style="width:92px;" value="${escapeHtml(s.end)}" onchange="_tunerRules.schedules[${idx}].end=this.value">
            <select class="form-control grow-1" onchange="_tunerRules.schedules[${idx}].mode=this.value"><option value="performance" ${s.mode==='performance'?'selected':''}>Производ.</option><option value="comfort" ${s.mode==='comfort'?'selected':''}>Комфорт</option></select>
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

#### `web/static/automation.js`
```javascript
// web/static/automation.js
let currentRules = [];
let editingRuleId = null;

function openBotGuide(type) {
    const modal = document.getElementById('bot-guide-modal');
    const title = document.getElementById('bot-guide-title');
    const body = document.getElementById('bot-guide-body');
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');

    if (type === 'tg') {
        title.textContent = isEn ? '📱 How to set up Telegram Bot' : '📱 Как подключить Telegram-бота';
        body.innerHTML = isEn ? `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Open <b>@BotFather</b> in Telegram, send <code>/newbot</code>, choose a name and copy the <b>Bot Token</b>.</li>
                <li>Open your new bot and press <b>Start</b> (or send any message).</li>
                <li>Open <b>@userinfobot</b> (or <b>@getmyid_bot</b>) to get your numeric <b>Chat ID</b>.</li>
                <li>Paste Token &amp; Chat ID here, click <b>Save</b> and press <b>Test</b>.</li>
            </ol>
        ` : `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Найди в Telegram <b>@BotFather</b>, отправь <code>/newbot</code>, задай имя и скопируй <b>Bot Token</b>.</li>
                <li>Зайди в своего нового бота и нажми <b>Запустить (Start)</b>.</li>
                <li>Напиши боту <b>@userinfobot</b> (или <b>@getmyid_bot</b>), чтобы узнать свой цифровой <b>Chat ID</b>.</li>
                <li>Вставь Token и Chat ID сюда, нажми <b>Сохранить</b> и проверь кнопкой <b>Тест</b>.</li>
            </ol>
        `;
    } else {
        title.textContent = isEn ? '💬 How to create a Discord Webhook' : '💬 Как создать Discord Webhook';
        body.innerHTML = isEn ? `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Open your Discord server → <b>Channel Settings</b> (gear icon on any text channel).</li>
                <li>Go to <b>Integrations</b> → <b>Webhooks</b> → <b>New Webhook</b>.</li>
                <li>Click <b>Copy Webhook URL</b>.</li>
                <li>Paste the URL here, click <b>Save</b> and press <b>Test</b>.</li>
            </ol>
        ` : `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Открой свой сервер Discord → <b>Настройки канала</b> (шестерёнка рядом с нужным каналом).</li>
                <li>Перейди в <b>Интеграции</b> → <b>Вебхуки</b> → <b>Новый вебхук</b>.</li>
                <li>Нажми <b>Копировать URL вебхука</b>.</li>
                <li>Вставь ссылку сюда, нажми <b>Сохранить</b> и проверь кнопкой <b>Тест</b>.</li>
            </ol>
        `;
    }
    modal.style.display = 'flex';
}

function closeBotGuide() {
    document.getElementById('bot-guide-modal').style.display = 'none';
}

async function loadAutomation() {
    const res = await api('/api/automation');
    const d = await res.json();
    const s = d.settings || {};

    document.getElementById('auto-enabled').checked = Boolean(s.enabled);
    document.getElementById('auto-interval').value = s.interval || 5;
    document.getElementById('auto-tg-token').value = '';
    document.getElementById('auto-tg-token').placeholder = s.has_tg_token ? t('token_set_ph') : '123456:ABC-DEF...';
    document.getElementById('auto-tg-chat').value = s.tg_chat_id || '';
    document.getElementById('auto-discord').value = '';
    document.getElementById('auto-discord').placeholder = s.has_discord ? t('webhook_set_ph') : 'https://discord.com/api/webhooks/...';

    const diskInp = document.getElementById('auto-alert-disk');
    if (diskInp) diskInp.value = s.alert_disk_gib || '';
    const qbChk = document.getElementById('auto-alert-qb');
    if (qbChk) qbChk.checked = Boolean(s.alert_qb_down);
    const recheckChk = document.getElementById('auto-recheck-io');
    if (recheckChk) recheckChk.checked = Boolean(s.auto_recheck_enabled);

    currentRules = d.rules || [];
    renderRules(currentRules);
    if (typeof loadDndDigestAndTagging === 'function') loadDndDigestAndTagging();
    if (typeof loadTunerTab === 'function') loadTunerTab();
}

function _fmtBytesBinary(b) {
    if (!b || b <= 0) return '';
    if (b >= 1024 ** 4) return `${(b / (1024 ** 4)).toFixed(2).replace(/\.00$/, '')} TiB`;
    if (b >= 1024 ** 3) return `${(b / (1024 ** 3)).toFixed(2).replace(/\.00$/, '')} GiB`;
    return `${(b / (1024 ** 2)).toFixed(2).replace(/\.00$/, '')} MiB`;
}

function _fmtSpeedBinary(bps) {
    if (!bps || bps <= 0) return '';
    if (bps >= 1024 ** 2) return `${(bps / (1024 ** 2)).toFixed(2).replace(/\.00$/, '')} MiB/s`;
    return `${(bps / 1024).toFixed(1).replace(/\.0$/, '')} KiB/s`;
}

function renderRules(rules) {
    const tbody = document.getElementById('rules-tbody');
    tbody.innerHTML = '';
    if (!rules.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="center-msg">${t('no_rules')}</td></tr>`;
        return;
    }
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
    const frag = document.createDocumentFragment();
    rules.forEach(r => {
        const conds = [];
        if (r.min_ratio > 0) conds.push(`Ratio >= ${r.min_ratio}x`);
        if (r.min_seed_days > 0) {
            const tmLbl = r.time_mode === 'time_active' ? (isEn ? 'Active' : 'Актив') : (isEn ? 'Seed' : 'Сид');
            conds.push(`${tmLbl} >= ${r.min_seed_days} ${t('rule_days_unit')}`);
        }
        if (r.min_uploaded_bytes > 0) conds.push(`${isEn ? 'Up' : 'Отдано'} >= ${_fmtBytesBinary(r.min_uploaded_bytes)}`);
        if (r.speed_op && r.speed_bytes > 0) {
            conds.push(`${isEn ? 'AvgSpd' : 'СрСкор'} ${r.speed_op} ${_fmtSpeedBinary(r.speed_bytes)} (${r.speed_window_min || 60}m)`);
        }

        const acts = [];
        if (r.action_pause) acts.push(t('chk_pause'));
        if (r.action_tag) acts.push(`🏷️ +${r.action_tag}`);
        if (r.action_remove_tag) acts.push(`✂️ -${r.action_remove_tag}`);
        if (r.notify) acts.push(t('rule_bot'));

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${escapeHtml(r.name)}</strong></td>
            <td style="white-space:normal;">${escapeHtml(conds.join(t('rule_and')))}</td>
            <td style="white-space:normal;">${escapeHtml(acts.join(', ') || '—')}</td>
            <td><span class="badge ${r.enabled ? 'badge-up' : 'badge-pause'}">${r.enabled ? t('rule_on') : t('rule_off')}</span></td>
            <td class="row-gap">
                <button class="btn btn-secondary btn-xs" onclick="editRule(${r.id})">✏️</button>
                <button class="btn btn-secondary btn-xs" onclick="toggleRule(${r.id})">${r.enabled ? t('rule_off') : t('rule_on')}</button>
                <button class="btn btn-danger btn-xs" onclick="deleteRule(${r.id})">🗑️</button>
            </td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

function editRule(id) {
    const r = currentRules.find(x => x.id === id);
    if (!r) return;

    editingRuleId = id;
    document.getElementById('rule-name').value = r.name || '';
    document.getElementById('rule-time-mode').value = r.time_mode || 'seeding_time';
    document.getElementById('rule-ratio').value = r.min_ratio > 0 ? r.min_ratio : '';
    document.getElementById('rule-days').value = r.min_seed_days > 0 ? r.min_seed_days : '';

    const upBytes = r.min_uploaded_bytes || 0;
    if (upBytes >= 1024 ** 4) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 4)).toFixed(3);
        document.getElementById('rule-up-unit').value = 'TiB';
    } else if (upBytes >= 1024 ** 3) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 3)).toFixed(3);
        document.getElementById('rule-up-unit').value = 'GiB';
    } else if (upBytes > 0) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 2)).toFixed(2);
        document.getElementById('rule-up-unit').value = 'MiB';
    } else {
        document.getElementById('rule-up-val').value = '';
        document.getElementById('rule-up-unit').value = 'GiB';
    }

    document.getElementById('rule-speed-op').value = r.speed_op || '';
    const spBytes = r.speed_bytes || 0;
    if (spBytes >= 1024 ** 2) {
        document.getElementById('rule-speed-val').value = +(spBytes / (1024 ** 2)).toFixed(3);
        document.getElementById('rule-speed-unit').value = 'MiB';
    } else if (spBytes > 0) {
        document.getElementById('rule-speed-val').value = +(spBytes / 1024).toFixed(2);
        document.getElementById('rule-speed-unit').value = 'KiB';
    } else {
        document.getElementById('rule-speed-val').value = '';
        document.getElementById('rule-speed-unit').value = 'KiB';
    }
    document.getElementById('rule-speed-win').value = r.speed_window_min || 60;

    document.getElementById('rule-tag').value = r.action_tag || '';
    document.getElementById('rule-remove-tag').value = r.action_remove_tag || '';
    document.getElementById('rule-pause').checked = Boolean(r.action_pause);
    document.getElementById('rule-notify').checked = Boolean(r.notify);

    document.getElementById('rule-form-title').textContent = t('card_edit_rule', { id });
    document.getElementById('btn-rule-submit').textContent = t('btn_save');
    document.getElementById('btn-rule-cancel').classList.remove('hidden');
    document.getElementById('rule-form-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function cancelEditRule() {
    editingRuleId = null;
    document.getElementById('rule-name').value = '';
    document.getElementById('rule-time-mode').value = 'seeding_time';
    document.getElementById('rule-ratio').value = '';
    document.getElementById('rule-days').value = '';
    document.getElementById('rule-up-val').value = '';
    document.getElementById('rule-up-unit').value = 'GiB';
    document.getElementById('rule-speed-op').value = '';
    document.getElementById('rule-speed-val').value = '';
    document.getElementById('rule-speed-unit').value = 'KiB';
    document.getElementById('rule-speed-win').value = 60;
    document.getElementById('rule-tag').value = '';
    document.getElementById('rule-remove-tag').value = '';
    document.getElementById('rule-pause').checked = false;
    document.getElementById('rule-notify').checked = true;

    document.getElementById('rule-form-title').textContent = t('card_add_rule');
    document.getElementById('btn-rule-submit').textContent = t('btn_add');
    document.getElementById('btn-rule-cancel').classList.add('hidden');
}

async function saveAutomationSettings() {
    const payload = {
        enabled: document.getElementById('auto-enabled').checked,
        interval: parseInt(document.getElementById('auto-interval').value) || 5,
        alert_disk_gib: parseInt(document.getElementById('auto-alert-disk')?.value || 0) || 0,
        alert_qb_down: document.getElementById('auto-alert-qb')?.checked || false,
        auto_recheck_enabled: document.getElementById('auto-recheck-io')?.checked || false,
        tg_token: document.getElementById('auto-tg-token').value.trim(),
        tg_chat_id: document.getElementById('auto-tg-chat').value.trim(),
        discord_webhook: document.getElementById('auto-discord').value.trim()
    };
    const res = await api('/api/automation/settings', 'POST', payload);
    const d = await res.json();
    if (!res.ok) return alert(d.error || t('save_err'));
    document.getElementById('auto-status-msg').textContent = d.message;
    loadAutomation();
}

async function testNotifications() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = t('auto_testing');
    const res = await api('/api/automation/test', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
    if (!d.success) alert(d.message);
}

async function runAutomationNow() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = t('auto_checking');
    const res = await api('/api/automation/run_now', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
}

async function submitAutomationRule() {
    const upVal = parseFloat(document.getElementById('rule-up-val').value) || 0;
    const upUnit = document.getElementById('rule-up-unit').value;
    const upMult = upUnit === 'TiB' ? (1024 ** 4) : (upUnit === 'GiB' ? (1024 ** 3) : (1024 ** 2));

    const spVal = parseFloat(document.getElementById('rule-speed-val').value) || 0;
    const spUnit = document.getElementById('rule-speed-unit').value;
    const spMult = spUnit === 'MiB' ? (1024 ** 2) : 1024;

    const payload = {
        name: document.getElementById('rule-name').value.trim(),
        time_mode: document.getElementById('rule-time-mode').value,
        min_ratio: parseFloat(document.getElementById('rule-ratio').value) || 0,
        min_seed_days: parseFloat(document.getElementById('rule-days').value) || 0,
        min_uploaded_bytes: upVal > 0 ? Math.round(upVal * upMult) : 0,
        speed_op: document.getElementById('rule-speed-op').value,
        speed_bytes: spVal > 0 ? (spVal * spMult) : 0,
        speed_window_min: parseInt(document.getElementById('rule-speed-win').value) || 60,
        action_tag: document.getElementById('rule-tag').value.trim(),
        action_remove_tag: document.getElementById('rule-remove-tag').value.trim(),
        action_pause: document.getElementById('rule-pause').checked,
        notify: document.getElementById('rule-notify').checked
    };

    let url = '/api/automation/rules';
    if (editingRuleId !== null) {
        url = '/api/automation/rules/update';
        payload.id = editingRuleId;
    }

    try {
        const res = await api(url, 'POST', payload);
        const d = await res.json();
        if (!res.ok || d.success === false) {
            return alert(d.error || `HTTP ${res.status}`);
        }
        cancelEditRule();
        loadAutomation();
    } catch (e) {
        alert(e.message);
    }
}

function addAutomationRule() {
    return submitAutomationRule();
}

async function toggleRule(id) {
    await api('/api/automation/rules/toggle', 'POST', { id });
    loadAutomation();
}

async function deleteRule(id) {
    if (!confirm(t('rule_del_confirm'))) return;
    if (editingRuleId === id) cancelEditRule();
    await api('/api/automation/rules/delete', 'POST', { id });
    loadAutomation();
}
```

---

Закидывай Пачку 3, прогоняй `pip install psutil` (или `pip install -r requirements.txt`) и запускай `python v` для проверки всех импортов! Если всё зелёное — тестируем в бою!