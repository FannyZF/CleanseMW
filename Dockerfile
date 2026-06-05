FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=19933

EXPOSE 19933

CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:19933", "--workers", "1", "--timeout", "300", "--preload"]
