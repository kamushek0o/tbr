### План (Пачка 3 — конструктор профилей, приоритетные правила, каталог программ и человечный UI)
1. `web/templates/partials/tab_tuner.html` — полный рефакторинг на человечный язык с подсказками `?`, динамическая панель профилей (`+ Новый`, `Клонировать`, `Имя/Иконка`, `Удалить`, `Сбросить стандартные`), приоритетный список и конструктор правил, плюс модалка выбора программ (чипы + каталог + умный список запущенных на ПК).
2. `web/static/tuner_ui.js` — CRUD профилей, глобальные настройки (`Частота проверки ПК`, `Профиль по умолчанию`, политика ручного выбора), телеметрия и обновление динамического бейджа в шапке.
3. `web/static/tuner_rules_ui.js` *(новый)* — приоритетная таблица правил (`↑`/`↓`), комбинированные условия (программы + расписание + нагрузка), управление чипами программ и каталог/пикер процессов.
4. `web/static/style.css` — стили чипов, кнопок подсказок `?`, строк приоритета правил и адаптив для мобильных экранов PWA.
5. `web/templates/index.html` — подключаем `tuner_rules_ui.js`.

---

#### `web/templates/partials/tab_tuner.html`
```html
<!-- Адаптивный авто-тюнер qBittorrent (ТЗ #58 Апгрейд) -->
<div class="card admin-only" id="tuner-main-card">
    <div class="row-between mb-8">
        <div class="row-gap" style="flex-wrap:wrap;">
            <div class="card-title" style="margin:0; white-space:nowrap;">🎛️ АВТО-ТЮНЕР qB</div>
            <span id="tuner-reason-badge" class="badge badge-pause">Выключен</span>
            <button id="tuner-btn-clear-ov" class="btn btn-secondary btn-xs hidden" onclick="clearTunerOverride()">🔄 Вернуть авто</button>
        </div>
        <div class="row-gap" style="flex-wrap:wrap;">
            <div id="tuner-mode-pills" class="row-gap" style="flex-wrap:wrap; gap:4px;"></div>
            <label class="row-gap pointer lbl-xs no-wrap" style="margin-left:4px;"><input type="checkbox" id="tuner-auto-chk" onchange="toggleTunerAutoSwitch()"> <b>Авто</b></label>
            <button class="btn btn-secondary btn-xs" onclick="restoreTunerBaseline()">♻️ Вернуть исходные настройки qB</button>
        </div>
    </div>

    <!-- Метрики в реальном времени -->
    <div class="tuner-telemetry-grid mb-10">
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap" id="tel-disk-title">Загрузка диска</div><div id="tel-disk" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Проц (другие прог.)</div><div id="tel-cpu" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Запас памяти (RAM)</div><div id="tel-ram" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Канал qB</div><div id="tel-chan" class="val-sm accent-txt">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Сеть (другие прог.)</div><div id="tel-net" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Пиров / Заполн.</div><div id="tel-slots" class="val-sm blue-txt">—</div></div>
    </div>

    <!-- Лента решений -->
    <div class="scroll-box mb-12" style="max-height:135px; border:1px solid var(--border); border-radius:6px;">
        <table>
            <thead><tr><th>Время</th><th>Профиль</th><th>Событие</th><th>Причина</th><th>Пиры</th></tr></thead>
            <tbody id="tuner-history-tbody"><tr><td colspan="5" class="center-msg">Нет событий</td></tr></tbody>
        </table>
    </div>

    <div class="tuner-columns-grid">
        <!-- Левая колонка: Конструктор профилей -->
        <div class="tuner-box">
            <div class="row-between mb-8" style="gap:6px;">
                <select id="tp-profile-select" class="form-control grow-1" style="font-weight:700;" onchange="selectTunerProfile(this.value)"></select>
                <div class="row-gap" style="gap:4px; flex-wrap:wrap;">
                    <button class="btn btn-secondary btn-xs" onclick="createNewTunerProfile()" title="Создать новый профиль">+ Новый</button>
                    <button class="btn btn-secondary btn-xs" onclick="cloneTunerProfile()" title="Клонировать текущий профиль">📋 Клон</button>
                    <button class="btn btn-secondary btn-xs" onclick="renameTunerProfile()" title="Переименовать / сменить иконку">✏️</button>
                    <button class="btn btn-danger btn-xs" onclick="deleteTunerProfile()" title="Удалить профиль">🗑️</button>
                </div>
            </div>
            <div class="row-between mb-8">
                <button class="btn btn-secondary btn-xs" onclick="resetBuiltinTunerPresets()">🔄 Сбросить стандартные</button>
                <button class="btn btn-xs" onclick="saveTunerProfile()">💾 Сохранить профиль</button>
            </div>

            <div class="tuner-section-title">ПИРЫ ОТДАЧИ (СЛОТЫ)</div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field"><span class="lbl-micro">Мин. пиров</span><input id="tp-mu-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Макс. пиров</span><input id="tp-mu-max" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Стартовых</span><input id="tp-mu-start" type="number" class="form-control tuner-num-input"></div>
            </div>

            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Макс. активных раздач</span>
                    <select id="tp-act-mode" class="form-control" onchange="syncTunerDisabledStates()">
                        <option value="keep">Не менять (эталон)</option>
                        <option value="range">Диапазон Min..Max</option>
                        <option value="fixed">Фиксированное число</option>
                    </select>
                </div>
                <div class="tuner-field" id="wrap-tp-act-min"><span class="lbl-micro">Min</span><input id="tp-act-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field" id="wrap-tp-act-max"><span class="lbl-micro">Max</span><input id="tp-act-max" type="number" class="form-control tuner-num-input"></div>
            </div>

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

            <div class="tuner-section-title">ЗАЩИТА ЖЕЛЕЗА И ИНТЕРНЕТА</div>
            <div class="tuner-guards-list mb-8">
                <div class="tuner-guard-row" id="guard-row-disk">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-disk-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Загрузка диска</span></label>
                    <div class="tuner-field" style="flex:1.5 1 120px; min-width:105px;"><span class="lbl-micro">Какой диск</span><select id="tp-g-disk-target" class="form-control" style="padding:4px 6px; font-size:11px;" onchange="syncTunerDisabledStates()"></select></div>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-disk-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Крит. %</span><input id="tp-g-disk-crit" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-disk-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
                <div class="tuner-guard-row" id="guard-row-cpu">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-cpu-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Проц (другие прог.)</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-cpu-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-cpu-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
                <div class="tuner-guard-row" id="guard-row-ram">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-ram-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Запас памяти</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Мин. % (тревога)</span><input id="tp-g-ram-min" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-ram-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
                <div class="tuner-guard-row" id="guard-row-net">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-net-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Сеть (другие прог.)</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-net-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-net-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>

            <details class="tuner-details">
                <summary>⚙️ Тонкие настройки пиров и задержек</summary>
                <div class="tuner-details-body">
                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">Пиров отдачи на раздачу (Min)</span><input id="tp-pt-up-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Пиров отдачи на раздачу (Max)</span><input id="tp-pt-up-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-pt-up-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто 28%</label>
                    </div>
                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">Соединений всего (Min)</span><input id="tp-mc-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Соединений всего (Max)</span><input id="tp-mc-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-mc-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто ×4</label>
                    </div>
                    <div class="tuner-fields-row mb-8">
                        <div class="tuner-field"><span class="lbl-micro">Соед. на раздачу (Min)</span><input id="tp-pt-con-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Соед. на раздачу (Max)</span><input id="tp-pt-con-max" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Пауза перед разгоном (с) <span class="tuner-help" onclick="alert(this.title)" title="Сколько ждать после снижения пиров, прежде чем снова пробовать повышать">?</span></span><input id="tp-cd-sec" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Шаг прибавления пиров</span><input id="tp-step-up" type="number" class="form-control tuner-num-input"></div>
                    </div>
                    <label class="row-gap pointer lbl-xs no-wrap"><input id="tp-yield-turtle" type="checkbox"> Не мешать ручному лимиту скорости в qB</label>
                </div>
            </details>
        </div>

        <!-- Правая колонка: Общие настройки + Приоритетные правила -->
        <div class="tuner-box">
            <div class="row-between mb-8">
                <span class="lbl-sm" style="margin:0; font-weight:700;">🧠 АВТОПЕРЕКЛЮЧЕНИЕ ПРОФИЛЕЙ</span>
                <button class="btn btn-xs" onclick="saveTunerGlobalSettings()">💾 Общие</button>
            </div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1"><span class="lbl-micro">Профиль по умолчанию</span><select id="tr-def-profile" class="form-control"></select></div>
                <div class="tuner-field"><span class="lbl-micro">Частота проверки ПК (сек) <span class="tuner-help" onclick="alert(this.title)" title="Как часто проверять запущенные игры и загрузку системы (2..30 сек)">?</span></span><input id="tr-poll-sec" type="number" min="2" max="30" class="form-control tuner-num-input" value="3"></div>
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Если я переключил вручную:</span>
                    <select id="tr-ov-policy" class="form-control">
                        <option value="2h">Уступать 2 часа</option>
                        <option value="until_window">До конца текущего окна</option>
                        <option value="until_rule">Пока не сработает правило</option>
                    </select>
                </div>
            </div>

            <div class="tuner-block-divider mb-8">
                <div class="row-between mb-6">
                    <span class="lbl-xs"><b>📋 Приоритет правил (сверху вниз):</b></span>
                    <button class="btn btn-xs" onclick="openNewRuleForm()">+ Добавить правило</button>
                </div>
                <div id="tuner-rules-list" class="col-gap scroll-box" style="max-height:190px; gap:6px;"></div>
            </div>

            <!-- Форма правила -->
            <div id="tuner-rule-editor" class="tuner-block-divider hidden">
                <div class="row-between mb-6">
                    <b id="tr-edit-title" class="lbl-xs accent-txt">Новое правило</b>
                    <button class="btn btn-secondary btn-xs" onclick="cancelTunerRuleEdit()">✕</button>
                </div>
                <div class="tuner-fields-row mb-8">
                    <div class="tuner-field grow-1"><span class="lbl-micro">Название правила</span><input id="tr-f-name" class="form-control" placeholder="Напр: Контра / Ночной турбо"></div>
                    <div class="tuner-field grow-1"><span class="lbl-micro">Целевой профиль</span><select id="tr-f-target" class="form-control"></select></div>
                </div>

                <div class="tuner-rule-cond mb-6">
                    <div class="row-between mb-6">
                        <label class="row-gap pointer lbl-xs"><input id="tr-f-proc-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> <b>🎮 Отслеживаемые программы</b></label>
                        <button type="button" class="btn btn-secondary btn-xs" onclick="openAppsPickerModal()">🔍 Выбрать программы</button>
                    </div>
                    <div id="tr-f-proc-chips" class="row-wrap" style="gap:4px;"></div>
                </div>

                <div class="tuner-rule-cond mb-6" id="tr-f-sched-box">
                    <label class="row-gap pointer lbl-xs mb-6"><input id="tr-f-sched-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> <b>⏰ Расписание по времени</b></label>
                    <div class="row-wrap mb-6" style="gap:6px;">
                        <input id="tr-f-sched-start" type="time" class="form-control" style="width:95px;" value="01:00">
                        <span>—</span>
                        <input id="tr-f-sched-end" type="time" class="form-control" style="width:95px;" value="08:00">
                    </div>
                    <div class="row-wrap" style="gap:6px;">
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="0" checked> Пн</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="1" checked> Вт</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="2" checked> Ср</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="3" checked> Чт</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="4" checked> Пт</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="5" checked> Сб</label>
                        <label class="lbl-xs"><input type="checkbox" class="tr-f-day" value="6" checked> Вс</label>
                    </div>
                </div>

                <div class="tuner-rule-cond mb-8" id="tr-f-ext-box">
                    <label class="row-gap pointer lbl-xs mb-6"><input id="tr-f-ext-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> <b>⚡ Нагрузка от других программ</b></label>
                    <div class="tuner-guard-row mb-6"><label class="lbl-xs tuner-guard-label no-wrap"><input id="tr-f-cpu-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> Проц %</label><div class="tuner-field"><span class="lbl-micro">Тревога</span><input id="tr-f-cpu-w" type="number" class="form-control tuner-num-input"></div><div class="tuner-field"><span class="lbl-micro">Возврат</span><input id="tr-f-cpu-r" type="number" class="form-control tuner-num-input"></div></div>
                    <div class="tuner-guard-row mb-6"><label class="lbl-xs tuner-guard-label no-wrap"><input id="tr-f-net-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> Сеть %</label><div class="tuner-field"><span class="lbl-micro">Тревога</span><input id="tr-f-net-w" type="number" class="form-control tuner-num-input"></div><div class="tuner-field"><span class="lbl-micro">Возврат</span><input id="tr-f-net-r" type="number" class="form-control tuner-num-input"></div></div>
                    <div class="tuner-guard-row mb-6"><label class="lbl-xs tuner-guard-label no-wrap"><input id="tr-f-ram-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> Память %</label><div class="tuner-field"><span class="lbl-micro">Мин.</span><input id="tr-f-ram-w" type="number" class="form-control tuner-num-input"></div><div class="tuner-field"><span class="lbl-micro">Возврат</span><input id="tr-f-ram-r" type="number" class="form-control tuner-num-input"></div></div>
                    <div class="tuner-guard-row"><label class="lbl-xs tuner-guard-label no-wrap"><input id="tr-f-disk-en" type="checkbox" onchange="syncRuleFormDisabledStates()"> Диск %</label><div class="tuner-field"><span class="lbl-micro">Тревога</span><input id="tr-f-disk-w" type="number" class="form-control tuner-num-input"></div><div class="tuner-field"><span class="lbl-micro">Возврат</span><input id="tr-f-disk-r" type="number" class="form-control tuner-num-input"></div></div>
                </div>

                <div class="tuner-fields-row mb-8">
                    <div class="tuner-field"><span class="lbl-micro">Ждать при запуске (сек)</span><input id="tr-f-enter" type="number" class="form-control tuner-num-input" value="10"></div>
                    <div class="tuner-field"><span class="lbl-micro">Ждать после закрытия (сек)</span><input id="tr-f-exit" type="number" class="form-control tuner-num-input" value="180"></div>
                </div>
                <div class="row-end"><button class="btn btn-secondary btn-xs" onclick="cancelTunerRuleEdit()">Отмена</button><button class="btn btn-xs" onclick="saveTunerRuleForm()">💾 Сохранить правило</button></div>
            </div>
        </div>
    </div>
</div>

<!-- Диалог дружелюбного выбора программ -->
<div id="tuner-apps-modal" class="modal-backdrop" onclick="if(event.target===this)closeAppsPickerModal()">
    <div class="modal" style="max-width:640px; max-height:86vh; display:flex; flex-direction:column;">
        <div class="row-between mb-8">
            <div class="card-title" style="margin:0;">🎮 ВЫБОР ПРОГРАММ ДЛЯ ОТСЛЕЖИВАНИЯ</div>
            <button class="btn btn-secondary btn-xs" onclick="closeAppsPickerModal()">Готово ✕</button>
        </div>
        <div id="apps-modal-selected" class="row-wrap mb-8" style="gap:4px;"></div>
        <div class="row-gap mb-8">
            <input id="apps-modal-search" class="form-control grow-1" placeholder="🔍 Поиск по названию (Counter-Strike, OBS, Photoshop)..." oninput="filterAppsCatalog()">
            <input id="apps-modal-manual" class="form-control" style="width:155px;" placeholder="Свой .exe вручную">
            <button class="btn btn-xs" onclick="addManualAppToRule()">+</button>
        </div>
        <div class="scroll-box" style="flex:1; max-height:52vh; border:1px solid var(--border); border-radius:6px; padding:8px;">
            <div class="lbl-xs accent-txt mb-6"><b>📚 Популярные программы (работает и с телефона):</b></div>
            <div id="apps-modal-catalog" class="col-gap mb-12" style="gap:8px;"></div>
            <div class="row-between mb-6" style="border-top:1px dashed var(--border); padding-top:8px;">
                <span class="lbl-xs blue-txt"><b>🖥️ Сейчас запущено на ПК:</b></span>
                <div class="row-gap">
                    <label class="lbl-xs pointer"><input id="apps-modal-sys" type="checkbox" onchange="loadRunningAppsForModal()"> Показать системные</label>
                    <button class="btn btn-secondary btn-xs" onclick="loadRunningAppsForModal()">🔄</button>
                </div>
            </div>
            <div id="apps-modal-running" class="row-wrap" style="gap:5px;"></div>
        </div>
    </div>
</div>
```

---

#### `web/static/tuner_ui.js`
```javascript
// web/static/tuner_ui.js
let _tunerProfiles = [];
let _tunerCurProfileId = 'performance';
let _tunerAvailableDisks = [];
let _tunerState = {};

function getProfileLabel(pid) {
    const p = _tunerProfiles.find(x => x.id === pid);
    return p ? `${p.icon} ${p.name}` : pid;
}

function syncTunerDisabledStates() {
    const setGroupState = (chkId, rowId, inputIds) => {
        const en = Boolean(document.getElementById(chkId)?.checked);
        document.getElementById(rowId)?.classList.toggle('tuner-row-disabled', !en);
        inputIds.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !en; });
    };

    setGroupState('tp-g-disk-en', 'guard-row-disk', ['tp-g-disk-target', 'tp-g-disk-warn', 'tp-g-disk-crit', 'tp-g-disk-rec']);
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
    const minEl = document.getElementById('tp-act-min'), maxEl = document.getElementById('tp-act-max');
    if (minEl) minEl.disabled = (actMode === 'keep');
    if (maxEl) maxEl.disabled = (actMode !== 'range');
    document.getElementById('wrap-tp-act-min')?.classList.toggle('tuner-row-disabled', actMode === 'keep');
    document.getElementById('wrap-tp-act-max')?.classList.toggle('tuner-row-disabled', actMode !== 'range');

    const ptUpAuto = Boolean(document.getElementById('tp-pt-up-auto')?.checked);
    ['tp-pt-up-min', 'tp-pt-up-max'].forEach(id => { const e = document.getElementById(id); if (e) e.disabled = ptUpAuto; });

    const mcAuto = Boolean(document.getElementById('tp-mc-auto')?.checked);
    ['tp-mc-min', 'tp-mc-max'].forEach(id => { const e = document.getElementById(id); if (e) e.disabled = mcAuto; });
}

function _renderProfileSelectors(activeMode) {
    const pills = document.getElementById('tuner-mode-pills');
    if (pills) {
        pills.innerHTML = `<button class="${activeMode === 'off' ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="setTunerMode('off')">Выкл</button>` +
            _tunerProfiles.map(p => `<button class="${activeMode === p.id ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="setTunerMode('${escapeHtml(p.id)}')">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</button>`).join('');
    }
    const selEdit = document.getElementById('tp-profile-select');
    if (selEdit) {
        selEdit.innerHTML = _tunerProfiles.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</option>`).join('');
        if (_tunerProfiles.some(p => p.id === _tunerCurProfileId)) selEdit.value = _tunerCurProfileId;
        else if (_tunerProfiles.length) _tunerCurProfileId = _tunerProfiles[0].id;
    }
    ['tr-def-profile', 'tr-f-target'].forEach(id => {
        const s = document.getElementById(id);
        if (!s) return;
        const cur = s.value;
        s.innerHTML = _tunerProfiles.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</option>`).join('');
        if (cur && _tunerProfiles.some(p => p.id === cur)) s.value = cur;
    });
}

function _updateDiskSelectorOptions(selectedVal) {
    const sel = document.getElementById('tp-g-disk-target');
    if (!sel) return;
    sel.innerHTML = '';
    sel.add(new Option('Авто (по раздачам)', ''));
    sel.add(new Option('Все диски (Max)', 'ALL'));
    _tunerAvailableDisks.forEach(d => sel.add(new Option(`${d.path} (${d.free_fmt} своб.)`, d.path)));
    sel.value = selectedVal || '';
}

async function loadTunerTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await refreshTunerState(true);
    if (typeof loadTunerRulesAndCatalog === 'function') await loadTunerRulesAndCatalog();
}

async function refreshTunerState(initEditors = false) {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/tuner/state');
        if (!res.ok) return;
        const d = await res.json();
        _tunerState = d.state || {};
        const tel = d.telemetry || {}, mode = _tunerState.mode || 'off';
        _tunerAvailableDisks = d.available_disks || [];
        if (Array.isArray(d.profiles)) _tunerProfiles = d.profiles;

        _renderProfileSelectors(mode);
        if (initEditors) {
            selectTunerProfile(_tunerCurProfileId);
            const pSec = document.getElementById('tr-poll-sec');
            if (pSec) pSec.value = _tunerState.poll_interval_sec || 3;
            const dSel = document.getElementById('tr-def-profile');
            if (dSel) dSel.value = _tunerState.default_profile_id || 'performance';
            const ovSel = document.getElementById('tr-ov-policy');
            if (ovSel) ovSel.value = _tunerState.manual_override_policy || '2h';
        }

        const chk = document.getElementById('tuner-auto-chk');
        if (chk) chk.checked = Boolean(_tunerState.auto_switch_enabled);

        const reason = d.switch_reason || _tunerState.last_reason || 'Выключен';
        const badge = document.getElementById('tuner-reason-badge');
        if (badge) {
            badge.textContent = reason;
            badge.className = mode === 'off' ? 'badge badge-pause' : 'badge badge-up';
        }
        const hb = document.getElementById('tuner-header-badge');
        if (hb) {
            hb.textContent = mode === 'off' ? '🎛️ Тюнер: Выкл' : `🎛️ ${getProfileLabel(mode)}`;
            hb.className = mode === 'off' ? 'badge badge-pause pointer admin-only' : 'badge badge-up pointer admin-only';
        }
        document.getElementById('tuner-btn-clear-ov')?.classList.toggle('hidden', !_tunerState.manual_override_mode);

        const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        setTxt('tel-disk-title', tel.monitored_disk_label ? `Загрузка диска (${tel.monitored_disk_label})` : 'Загрузка диска');
        setTxt('tel-disk', tel.psutil_available === false ? 'нет psutil' : `${tel.disk_busy ?? 0}%`);
        setTxt('tel-cpu', `${tel.cpu_ext ?? 0}%`);
        setTxt('tel-ram', `${tel.ram_free ?? 0}%`);
        setTxt('tel-chan', `${tel.channel_pct ?? 0}%`);
        setTxt('tel-net', `${tel.net_ext_pct ?? 0}%`);
        const curMu = (_tunerState.current_limits || {}).max_uploads || (_tunerState.baseline || {}).max_uploads || '—';
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
    const mode = auto_switch ? (_tunerState.default_profile_id || 'performance') : 'off';
    await api('/api/tuner/mode', 'POST', { mode, auto_switch, is_manual: false });
    refreshTunerState();
}

async function clearTunerOverride() {
    await api('/api/tuner/mode', 'POST', { mode: _tunerState.default_profile_id || 'performance', clear_override: true, is_manual: false });
    refreshTunerState();
}

async function restoreTunerBaseline() {
    if (!confirm('Выключить тюнер и вернуть исходные настройки qBittorrent?')) return;
    const res = await api('/api/tuner/restore_baseline', 'POST');
    alert((await res.json()).message || 'Готово');
    refreshTunerState();
}

async function saveTunerGlobalSettings() {
    const res = await api('/api/tuner/settings', 'POST', {
        poll_interval_sec: parseInt(document.getElementById('tr-poll-sec')?.value) || 3,
        default_profile_id: document.getElementById('tr-def-profile')?.value || 'performance',
        override_policy: document.getElementById('tr-ov-policy')?.value || '2h'
    });
    if (res.ok) { alert('✅ Общие настройки тюнера сохранены'); refreshTunerState(); }
}

function selectTunerProfile(pid) {
    _tunerCurProfileId = pid;
    const pObj = _tunerProfiles.find(x => x.id === pid);
    if (!pObj) return;
    const p = pObj.config || {}, g = p.guards || {};
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

    _updateDiskSelectorOptions(g.disk?.target_disk || '');
    sc('tp-g-disk-en', g.disk?.enabled); sv('tp-g-disk-warn', g.disk?.warn); sv('tp-g-disk-crit', g.disk?.crit); sv('tp-g-disk-rec', g.disk?.recover);
    sc('tp-g-cpu-en', g.cpu?.enabled); sv('tp-g-cpu-warn', g.cpu?.warn); sv('tp-g-cpu-rec', g.cpu?.recover);
    sc('tp-g-ram-en', g.ram?.enabled); sv('tp-g-ram-min', g.ram?.min_free); sv('tp-g-ram-rec', g.ram?.recover_free);
    sc('tp-g-net-en', g.net?.enabled); sv('tp-g-net-warn', g.net?.warn_pct); sv('tp-g-net-rec', g.net?.recover_pct);
    syncTunerDisabledStates();
}

function _collectProfileFormConfig() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    return {
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
            disk: { enabled: cb('tp-g-disk-en'), target_disk: document.getElementById('tp-g-disk-target')?.value || '', warn: iv('tp-g-disk-warn'), crit: iv('tp-g-disk-crit'), recover: iv('tp-g-disk-rec') },
            cpu:  { enabled: cb('tp-g-cpu-en'), warn: iv('tp-g-cpu-warn'), recover: iv('tp-g-cpu-rec') },
            ram:  { enabled: cb('tp-g-ram-en'), min_free: iv('tp-g-ram-min'), recover_free: iv('tp-g-ram-rec') },
            net:  { enabled: cb('tp-g-net-en'), warn_pct: iv('tp-g-net-warn'), recover_pct: iv('tp-g-net-rec') }
        }
    };
}

async function saveTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj) return;
    const res = await api('/api/tuner/profiles', 'POST', { id: pObj.id, name: pObj.name, icon: pObj.icon, config: _collectProfileFormConfig() });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles || []; _renderProfileSelectors(_tunerState.mode || 'off'); alert(`✅ Профиль «${pObj.name}» сохранён`); }
}

async function createNewTunerProfile() {
    const name = prompt('Название нового профиля:');
    if (!name || !name.trim()) return;
    const icon = prompt('Иконка (эмодзи):', '⚙️') || '⚙️';
    const res = await api('/api/tuner/profiles', 'POST', { is_new: true, name: name.trim(), icon: icon.trim(), config: _collectProfileFormConfig() });
    if (res.ok) { const d = await res.json(); _tunerProfiles = d.profiles; _tunerCurProfileId = d.profile.id; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

async function cloneTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    const name = prompt('Название копии профиля:', pObj ? `${pObj.name} (копия)` : 'Копия');
    if (!name || !name.trim()) return;
    const res = await api('/api/tuner/profiles', 'POST', { clone_from: _tunerCurProfileId, name: name.trim(), icon: pObj?.icon || '⚙️' });
    if (res.ok) { const d = await res.json(); _tunerProfiles = d.profiles; _tunerCurProfileId = d.profile.id; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

async function renameTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj) return;
    const name = prompt('Новое название профиля:', pObj.name);
    if (!name || !name.trim()) return;
    const icon = prompt('Иконка (эмодзи):', pObj.icon) || pObj.icon;
    const res = await api('/api/tuner/profiles', 'POST', { id: pObj.id, name: name.trim(), icon: icon.trim(), config: _collectProfileFormConfig() });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(pObj.id); }
}

async function deleteTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj || !confirm(`Удалить профиль «${pObj.name}»?\n(Если к нему привязаны правила автопереключения, они будут отключены)`)) return;
    const res = await api('/api/tuner/profiles', 'POST', { delete_id: pObj.id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.message || 'Ошибка удаления');
    _tunerProfiles = d.profiles;
    _tunerCurProfileId = _tunerProfiles[0]?.id || 'performance';
    _renderProfileSelectors(_tunerState.mode || 'off');
    selectTunerProfile(_tunerCurProfileId);
    if (typeof loadTunerRulesAndCatalog === 'function') loadTunerRulesAndCatalog();
}

async function resetBuiltinTunerPresets() {
    if (!confirm('Восстановить 5 стандартных пресетов («Турбо / Ночь», «Производительность», «Баланс», «Игровой», «Тихий минимум»)? Пользовательские профили останутся на месте.')) return;
    const res = await api('/api/tuner/profiles', 'POST', { reset_builtins: true });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

setInterval(() => {
    if (!document.hidden && (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin')) refreshTunerState(false);
}, 5000);
```

---

#### `web/static/tuner_rules_ui.js` *(новый файл)*
```javascript
// web/static/tuner_rules_ui.js
let _tunerRulesList = [];
let _editingRuleId = null;
let _editingRuleApps = [];
let _appsCatalog = [];
let _friendlyAppsMap = {};

async function loadTunerRulesAndCatalog() {
    const [rRes, cRes] = await Promise.all([api('/api/tuner/rules'), api('/api/tuner/catalog')]);
    if (rRes.ok) { _tunerRulesList = (await rRes.json()).rules || []; renderTunerRulesList(); }
    if (cRes.ok) {
        const c = await cRes.json();
        _appsCatalog = c.catalog || [];
        _friendlyAppsMap = c.friendly_map || {};
    }
}

function _formatRuleSummary(r) {
    const c = r.config || {}, parts = [];
    if (c.processes?.enabled && c.processes.names?.length) parts.push(`🎮 Программы (${c.processes.names.length})`);
    if (c.schedule?.enabled) parts.push(`⏰ ${c.schedule.start}–${c.schedule.end}`);
    if (c.external_load?.enabled) parts.push('⚡ Нагрузка ПК');
    return parts.join(' + ') || 'Нет условий';
}

function renderTunerRulesList() {
    const box = document.getElementById('tuner-rules-list');
    if (!box) return;
    if (!_tunerRulesList.length) {
        box.innerHTML = '<div class="center-msg lbl-xs muted-text">Правил пока нет. Нажмите «+ Добавить правило».</div>';
        return;
    }
    box.innerHTML = _tunerRulesList.map((r, idx) => `
        <div class="tuner-rule-row ${r.enabled ? '' : 'tuner-row-disabled'}" style="opacity:${r.enabled ? '1' : '0.5'};">
            <div class="row-gap" style="gap:6px; min-width:0; flex:1;">
                <span class="badge badge-pause">#${idx + 1}</span>
                <input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleTunerRuleEnabled(${r.id}, this.checked)" title="Вкл/Выкл">
                <div style="min-width:0; flex:1;">
                    <div style="font-size:12px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(r.name)} → <span class="accent-txt">${escapeHtml(getProfileLabel(r.target_profile_id))}</span></div>
                    <div class="lbl-micro">${escapeHtml(_formatRuleSummary(r))}</div>
                </div>
            </div>
            <div class="row-gap" style="gap:3px;">
                <button class="btn btn-secondary btn-xs" ${idx === 0 ? 'disabled' : ''} onclick="moveTunerRule(${r.id}, 'up')">⬆️</button>
                <button class="btn btn-secondary btn-xs" ${idx === _tunerRulesList.length - 1 ? 'disabled' : ''} onclick="moveTunerRule(${r.id}, 'down')">⬇️</button>
                <button class="btn btn-secondary btn-xs" onclick="editTunerRule(${r.id})">✏️</button>
                <button class="btn btn-danger btn-xs" onclick="deleteTunerRule(${r.id})">🗑️</button>
            </div>
        </div>
    `).join('');
}

function syncRuleFormDisabledStates() {
    const prEn = Boolean(document.getElementById('tr-f-proc-en')?.checked);
    document.getElementById('tr-f-proc-chips')?.classList.toggle('tuner-row-disabled', !prEn);

    const scEn = Boolean(document.getElementById('tr-f-sched-en')?.checked);
    document.getElementById('tr-f-sched-start').disabled = !scEn;
    document.getElementById('tr-f-sched-end').disabled = !scEn;
    document.querySelectorAll('.tr-f-day').forEach(d => { d.disabled = !scEn; });

    const exEn = Boolean(document.getElementById('tr-f-ext-en')?.checked);
    ['cpu', 'net', 'ram', 'disk'].forEach(k => {
        const chk = document.getElementById(`tr-f-${k}-en`);
        if (chk) chk.disabled = !exEn;
        const subEn = exEn && Boolean(chk?.checked);
        ['w', 'r'].forEach(s => { const inp = document.getElementById(`tr-f-${k}-${s}`); if (inp) inp.disabled = !subEn; });
    });
}

function _renderAppChipHtml(exe, removable = true) {
    const meta = _friendlyAppsMap[exe.toLowerCase()];
    const lbl = meta ? `${meta.icon} ${meta.name}` : `🖥️ ${exe}`;
    const btn = removable ? ` <b class="pointer" onclick="removeAppFromRule('${escapeHtml(exe)}')">×</b>` : '';
    return `<span class="tuner-chip">${escapeHtml(lbl)}${btn}</span>`;
}

function renderRuleAppChips() {
    const box = document.getElementById('tr-f-proc-chips');
    if (box) box.innerHTML = _editingRuleApps.length ? _editingRuleApps.map(e => _renderAppChipHtml(e, true)).join('') : '<span class="lbl-xs muted-text">Программы не выбраны</span>';
    const mBox = document.getElementById('apps-modal-selected');
    if (mBox) mBox.innerHTML = _editingRuleApps.map(e => _renderAppChipHtml(e, true)).join('');
}

function removeAppFromRule(exe) {
    _editingRuleApps = _editingRuleApps.filter(x => x.toLowerCase() !== exe.toLowerCase());
    renderRuleAppChips();
    filterAppsCatalog();
}

function toggleAppInRule(exe) {
    const low = exe.toLowerCase();
    if (_editingRuleApps.some(x => x.toLowerCase() === low)) _editingRuleApps = _editingRuleApps.filter(x => x.toLowerCase() !== low);
    else _editingRuleApps.push(exe);
    renderRuleAppChips();
    filterAppsCatalog();
}

function addManualAppToRule() {
    const inp = document.getElementById('apps-modal-manual');
    const val = (inp?.value || '').trim();
    if (!val) return;
    if (!_editingRuleApps.some(x => x.toLowerCase() === val.toLowerCase())) _editingRuleApps.push(val);
    inp.value = '';
    renderRuleAppChips();
}

function openNewRuleForm() {
    _editingRuleId = null;
    _editingRuleApps = [];
    document.getElementById('tr-edit-title').textContent = 'Новое правило';
    document.getElementById('tr-f-name').value = '';
    document.getElementById('tr-f-proc-en').checked = true;
    document.getElementById('tr-f-sched-en').checked = false;
    document.getElementById('tr-f-ext-en').checked = false;
    document.getElementById('tr-f-cpu-en').checked = true; document.getElementById('tr-f-cpu-w').value = 45; document.getElementById('tr-f-cpu-r').value = 25;
    document.getElementById('tr-f-net-en').checked = true; document.getElementById('tr-f-net-w').value = 25; document.getElementById('tr-f-net-r').value = 12;
    document.getElementById('tr-f-ram-en').checked = false; document.getElementById('tr-f-ram-w').value = 15; document.getElementById('tr-f-ram-r').value = 25;
    document.getElementById('tr-f-disk-en').checked = false; document.getElementById('tr-f-disk-w').value = 70; document.getElementById('tr-f-disk-r').value = 45;
    document.getElementById('tr-f-enter').value = 10; document.getElementById('tr-f-exit').value = 180;
    renderRuleAppChips();
    syncRuleFormDisabledStates();
    document.getElementById('tuner-rule-editor').classList.remove('hidden');
}

function editTunerRule(rid) {
    const r = _tunerRulesList.find(x => x.id === rid);
    if (!r) return;
    _editingRuleId = rid;
    const c = r.config || {}, pr = c.processes || {}, sc = c.schedule || {}, ex = c.external_load || {};
    _editingRuleApps = [...(pr.names || [])];
    document.getElementById('tr-edit-title').textContent = `Редактирование: ${r.name}`;
    document.getElementById('tr-f-name').value = r.name || '';
    document.getElementById('tr-f-target').value = r.target_profile_id || 'comfort';
    document.getElementById('tr-f-proc-en').checked = Boolean(pr.enabled);
    document.getElementById('tr-f-sched-en').checked = Boolean(sc.enabled);
    document.getElementById('tr-f-sched-start').value = sc.start || '01:00';
    document.getElementById('tr-f-sched-end').value = sc.end || '08:00';
    document.querySelectorAll('.tr-f-day').forEach(d => { d.checked = (sc.days || [0,1,2,3,4,5,6]).includes(parseInt(d.value)); });
    document.getElementById('tr-f-ext-en').checked = Boolean(ex.enabled);
    document.getElementById('tr-f-cpu-en').checked = Boolean(ex.cpu_enabled); document.getElementById('tr-f-cpu-w').value = ex.cpu_warn ?? 45; document.getElementById('tr-f-cpu-r').value = ex.cpu_recover ?? 25;
    document.getElementById('tr-f-net-en').checked = Boolean(ex.net_enabled); document.getElementById('tr-f-net-w').value = ex.net_warn_pct ?? 25; document.getElementById('tr-f-net-r').value = ex.net_recover_pct ?? 12;
    document.getElementById('tr-f-ram-en').checked = Boolean(ex.ram_enabled); document.getElementById('tr-f-ram-w').value = ex.ram_min_free ?? 15; document.getElementById('tr-f-ram-r').value = ex.ram_recover_free ?? 25;
    document.getElementById('tr-f-disk-en').checked = Boolean(ex.disk_enabled); document.getElementById('tr-f-disk-w').value = ex.disk_warn ?? 70; document.getElementById('tr-f-disk-r').value = ex.disk_recover ?? 45;
    document.getElementById('tr-f-enter').value = c.enter_sec ?? 10; document.getElementById('tr-f-exit').value = c.exit_sec ?? 180;
    renderRuleAppChips();
    syncRuleFormDisabledStates();
    document.getElementById('tuner-rule-editor').classList.remove('hidden');
}

function cancelTunerRuleEdit() {
    document.getElementById('tuner-rule-editor').classList.add('hidden');
}

async function saveTunerRuleForm() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const existing = _editingRuleId ? _tunerRulesList.find(x => x.id === _editingRuleId) : null;
    const payload = {
        id: _editingRuleId,
        name: document.getElementById('tr-f-name').value.trim() || 'Новое правило',
        enabled: existing ? Boolean(existing.enabled) : true,
        target_profile_id: document.getElementById('tr-f-target').value,
        config: {
            processes: { enabled: cb('tr-f-proc-en'), names: _editingRuleApps },
            schedule: { enabled: cb('tr-f-sched-en'), start: document.getElementById('tr-f-sched-start').value, end: document.getElementById('tr-f-sched-end').value, days: [...document.querySelectorAll('.tr-f-day:checked')].map(d => parseInt(d.value)) },
            external_load: {
                enabled: cb('tr-f-ext-en'),
                cpu_enabled: cb('tr-f-cpu-en'), cpu_warn: iv('tr-f-cpu-w'), cpu_recover: iv('tr-f-cpu-r'),
                net_enabled: cb('tr-f-net-en'), net_warn_pct: iv('tr-f-net-w'), net_recover_pct: iv('tr-f-net-r'),
                ram_enabled: cb('tr-f-ram-en'), ram_min_free: iv('tr-f-ram-w'), ram_recover_free: iv('tr-f-ram-r'),
                disk_enabled: cb('tr-f-disk-en'), disk_warn: iv('tr-f-disk-w'), disk_recover: iv('tr-f-disk-r'),
            },
            enter_sec: iv('tr-f-enter'), exit_sec: iv('tr-f-exit')
        }
    };
    const res = await api('/api/tuner/rules', 'POST', payload);
    if (res.ok) { _tunerRulesList = (await res.json()).rules; cancelTunerRuleEdit(); renderTunerRulesList(); }
}

async function toggleTunerRuleEnabled(rid, en) {
    const r = _tunerRulesList.find(x => x.id === rid);
    if (!r) return;
    const res = await api('/api/tuner/rules', 'POST', { id: r.id, name: r.name, enabled: en, target_profile_id: r.target_profile_id, config: r.config });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

async function moveTunerRule(rid, direction) {
    const res = await api('/api/tuner/rules', 'POST', { move_id: rid, direction });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

async function deleteTunerRule(rid) {
    if (!confirm('Удалить это правило?')) return;
    const res = await api('/api/tuner/rules', 'POST', { delete_id: rid });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

function openAppsPickerModal() {
    document.getElementById('apps-modal-search').value = '';
    document.getElementById('tuner-apps-modal').style.display = 'flex';
    renderRuleAppChips();
    filterAppsCatalog();
    loadRunningAppsForModal();
}

function closeAppsPickerModal() { document.getElementById('tuner-apps-modal').style.display = 'none'; }

function filterAppsCatalog() {
    const q = (document.getElementById('apps-modal-search')?.value || '').trim().toLowerCase();
    const box = document.getElementById('apps-modal-catalog');
    if (!box) return;
    box.innerHTML = _appsCatalog.map(grp => {
        const items = (grp.apps || []).filter(a => !q || a.name.toLowerCase().includes(q) || a.exe.toLowerCase().includes(q));
        if (!items.length) return '';
        return `<div><div class="lbl-micro mb-6">${grp.icon} ${escapeHtml(grp.category)}</div><div class="row-wrap" style="gap:4px;">` +
            items.map(a => {
                const active = _editingRuleApps.some(x => x.toLowerCase() === a.exe.toLowerCase());
                return `<button type="button" class="${active ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="toggleAppInRule('${escapeHtml(a.exe)}')">${a.icon} ${escapeHtml(a.name)}</button>`;
            }).join('') + '</div></div>';
    }).join('');
}

async function loadRunningAppsForModal() {
    const box = document.getElementById('apps-modal-running');
    if (!box) return;
    box.innerHTML = '<span class="lbl-xs muted-text">⏳ Читаю процессы ПК...</span>';
    const sys = document.getElementById('apps-modal-sys')?.checked ? '1' : '0';
    const res = await api(`/api/tuner/processes?system=${sys}`);
    if (!res.ok) return;
    const list = (await res.json()).processes || [];
    box.innerHTML = list.map(p => {
        const cnt = p.count > 1 ? ` ×${p.count}` : '';
        return `<button type="button" class="btn btn-secondary btn-xs" onclick="toggleAppInRule('${escapeHtml(p.exe)}')" title="${escapeHtml(p.exe)}">${escapeHtml(p.icon)} ${escapeHtml(p.label)} (${escapeHtml(p.exe)})${cnt}</button>`;
    }).join('') || '<span class="lbl-xs muted-text">Процессы не найдены</span>';
}
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
.tuner-field { display: flex; flex-direction: column; gap: 2px; flex: 1 1 72px; min-width: 70px; }
.tuner-num-input { padding: 5px 6px !important; font-size: 12px !important; text-align: center; }
.lbl-micro { font-size: 9.5px; color: var(--text-muted); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.no-wrap { white-space: nowrap !important; }
.align-end { align-items: flex-end !important; }
.tuner-help { display: inline-flex; justify-content: center; align-items: center; width: 14px; height: 14px; border-radius: 50%; background: var(--bg-panel); border: 1px solid var(--border); color: var(--info); font-size: 9px; font-weight: 800; cursor: pointer; margin-left: 2px; }
.tuner-chip { display: inline-flex; align-items: center; gap: 5px; background: var(--bg-panel); border: 1px solid var(--accent); color: var(--text); padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tuner-rule-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; background: rgba(0,0,0,0.18); padding: 7px 9px; border-radius: 6px; border: 1px solid var(--border); }
.tuner-rule-cond { background: rgba(0,0,0,0.14); padding: 8px; border-radius: 6px; border: 1px solid var(--border); }

.tuner-guards-list { display: flex; flex-direction: column; gap: 6px; border-top: 1px dashed var(--border); padding-top: 8px; }
.tuner-guard-row { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; background: rgba(0,0,0,0.15); padding: 6px 8px; border-radius: 6px; transition: opacity 0.2s; }
.tuner-guard-label { width: 128px; padding-bottom: 6px; flex-shrink: 0; display: inline-flex; align-items: center; gap: 6px; }
.tuner-row-disabled { opacity: 0.38 !important; }
.tuner-row-disabled input:not([type=checkbox]), .tuner-row-disabled select { pointer-events: none; background: rgba(0,0,0,0.2) !important; color: var(--text-muted) !important; }
.tuner-details { border-top: 1px dashed var(--border); padding-top: 8px; margin-top: 6px; }
.tuner-details summary { font-size: 11.5px; font-weight: 700; color: var(--info); cursor: pointer; user-select: none; padding: 4px 0; }
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
.val-lg { font-size: 18px; font-weight: 800; } .val-md { font-size: 15px; font-weight: 800; } .val-sm { font-size: 13px; font-weight: 700; margin-top: 3px; }
.accent-txt { color: var(--accent); } .purple-txt { color: #9b59b6; } .orange-txt { color: #e67e22; } .blue-txt { color: #3498db; }
.col-resizer { position: absolute; right: 0; top: 0; width: 6px; height: 100%; cursor: col-resize; user-select: none; }

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
    .tools-grid, .grid-2, .tuner-columns-grid { grid-template-columns: 1fr; }
    .tab-content { padding: 8px; }
    .tuner-guard-row { flex-direction: column; align-items: stretch; gap: 4px; }
    .tuner-guard-label { width: 100%; }
    .tuner-fields-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    .tuner-fields-row.align-end { grid-template-columns: 1fr; }
    body.mobile-cards-on .grid-cards, body.mobile-cards-on #analytics-charts-grid { grid-template-columns: 1fr !important; }
    body.mobile-cards-on .btn, body.mobile-cards-on .tab-btn { padding: 8px 10px; font-size: 12px; }
    body.mobile-cards-on #summary-table thead { display: none; }
    body.mobile-cards-on #summary-table, body.mobile-cards-on #summary-table tbody { display: block; width: 100%; }
    body.mobile-cards-on #summary-table tr { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; padding: 8px 10px; }
    body.mobile-cards-on #summary-table tr.selected { border-color: var(--accent); }
    body.mobile-cards-on #summary-table td { display: flex; flex-direction: column; gap: 2px; padding: 2px 0; border-bottom: none; white-space: normal; min-width: 0; }
    body.mobile-cards-on #summary-table td::before { content: attr(data-label); color: var(--text-muted); font-size: 10px; font-weight: 600; text-transform: uppercase; }
    body.mobile-cards-on #summary-table td[data-col="name"] { grid-column: 1 / -1; flex-direction: row; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-bottom: 2px; }
    body.mobile-cards-on #summary-table td[data-col="name"]::before { display: none; }
    body.mobile-cards-on #summary-table td[data-col="name"] strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
    body.mobile-cards-on #summary-table td[data-col="ratio"] { grid-column: 1 / -1; flex-direction: row; justify-content: space-between; align-items: center; background: rgba(46, 204, 113, 0.08); padding: 4px 8px; border-radius: 5px; }
}
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
<script src="/static/tuner_rules_ui.js?v={{ v }}"></script>
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

Закидывай в `patch.md`, прогоняй `python apply_patch.py`, проверяй `python v` и жми `Ctrl+F5` в браузере!
Теперь у тебя конструктор с 5 встроенными пресетами (+ свои любые), приоритетной лесенкой правил, частотой опроса ПК от 2 секунд, чипами с каталогом игр и 100% человечным UI без жаргона. Если что-то захочется подкрутить по месту — скидывай скрин или отзыв!