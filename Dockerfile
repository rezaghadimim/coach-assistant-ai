FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist coaching data outside the container image
VOLUME ["/app/data", "/app/docs/knowledge"]

EXPOSE 8000

CMD ["python", "main.py"]
