FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV TBR_DATA_DIR=/data \
    TBR_BT_BACKUP=/bt_backup \
    PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "main.py", "--headless", "--host", "0.0.0.0", "--port", "5000"]