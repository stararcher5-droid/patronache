FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY continut ./continut
# Totul ce se schimbă la rulare stă în /srv/data: baza SQLite și conținutul
# editat din admin (copiat din imagine la prima pornire, dacă volumul e gol).
ENV PATRONACHE_DB=/srv/data/patronache.db \
    PATRONACHE_CONTINUT=/srv/data/continut
VOLUME ["/srv/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
