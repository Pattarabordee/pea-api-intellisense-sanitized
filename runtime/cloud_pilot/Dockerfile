FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    AIS_NOTIFICATION_MODE=shadow \
    AIS_ETR_DB=/data/ais_etr.sqlite

WORKDIR /app

COPY ais_etr /app/ais_etr
COPY AGENTS.md README_AIS_ETR_MVP.md /app/

RUN mkdir -p /data /app/runtime

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3); body=json.loads(r.read().decode()); raise SystemExit(0 if body.get('production_send') == 'blocked' else 1)"

CMD ["python", "-m", "ais_etr", "ais-inbound-api", "--host", "0.0.0.0", "--port", "8090", "--requests-output", "/data/ais_inbound_requests.jsonl", "--callbacks-output", "/data/ais_inbound_callbacks.jsonl", "--no-callback-post"]
