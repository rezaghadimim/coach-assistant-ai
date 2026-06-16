FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Flush stdout immediately so logs appear live in `docker compose logs -f`
ENV PYTHONUNBUFFERED=1

# Persist coaching data outside the container image
VOLUME ["/app/data", "/app/docs/knowledge"]

EXPOSE 8000

CMD ["python", "main.py"]
