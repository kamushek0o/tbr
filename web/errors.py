# web/errors.py
from flask import request, jsonify, render_template
from werkzeug.exceptions import HTTPException
from utils.helpers import write_error_log

_ERROR_COPY = {
    400: ("Кривой запрос", "То ли CSRF протух, то ли JSON помялся по дороге. Обнови страницу и попробуй ещё раз."),
    403: ("Доступ закрыт", "Сюда пускают только с погонами Admin (или твой Viewer-токен упёрся в шлагбаум)."),
    404: ("Страница ушла в сид", "Такого маршрута в tbr PRO нет — возможно, он ушёл в DHT и не вернулся."),
    429: ("Притормози, ковбой", "Слишком много запросов подряд. Дай серверу отдышаться пару минут."),
    500: ("Внутри что-то хрустнуло", "Сервер поймал внутреннюю ошибку. Подробности аккуратно записаны в error.log — ничего лишнего наружу не утекло.")
}


def _wants_json():
    if request.path.startswith('/api/'):
        return True
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept and 'text/html' not in accept


def _render_error(code):
    safe_code = code if code in _ERROR_COPY else 500
    title, msg = _ERROR_COPY[safe_code]
    if _wants_json():
        return jsonify({'success': False, 'error': title, 'message': msg, 'code': safe_code}), safe_code
    return render_template('error.html', code=safe_code, title=title, message=msg), safe_code


def register_error_handlers(app):
    for code in (400, 403, 404, 429, 500):
        app.register_error_handler(code, lambda e, c=code: _render_error(c))

    @app.errorhandler(Exception)
    def handle_any_exception(e):
        if isinstance(e, HTTPException):
            return _render_error(e.code or 500)
        write_error_log("Flask HTTP 500", e)
        return _render_error(500)