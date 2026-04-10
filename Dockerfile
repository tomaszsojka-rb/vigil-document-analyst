FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash vigil
USER vigil

COPY --chown=vigil:vigil app.py middleware.py foundry_client.py search_client.py doc_parser.py chunker.py gap_rules.py ./
COPY --chown=vigil:vigil agents/ ./agents/
COPY --chown=vigil:vigil routes/ ./routes/
COPY --chown=vigil:vigil rulesets/ ./rulesets/
COPY --chown=vigil:vigil static/ ./static/
COPY --chown=vigil:vigil agent.yaml ./

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/')" || exit 1

CMD ["python", "app.py"]
