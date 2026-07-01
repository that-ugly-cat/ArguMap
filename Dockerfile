FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# `static` must exist for StaticFiles mount; `data` holds the SQLite DB.
# Created here as a safety net in case the dirs are absent from the build context.
RUN mkdir -p data static

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
