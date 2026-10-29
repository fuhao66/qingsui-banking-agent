FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY entrypoint.sh ./
RUN pip install --no-cache-dir .

RUN addgroup --system app && adduser --system --ingroup app app
RUN chmod +x /app/entrypoint.sh && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
