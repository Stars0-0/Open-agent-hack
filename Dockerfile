FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/logs

ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "run.py"]
