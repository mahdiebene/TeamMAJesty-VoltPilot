FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/mahdiebene/TeamMAJesty-VoltPilot"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8080 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /srv/gridwise
COPY requirements.txt requirements-lock.txt /srv/gridwise/
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /srv/gridwise/requirements-lock.txt \
    && useradd --system --uid 10001 --create-home gridwise
COPY --chown=gridwise:gridwise app /srv/gridwise/app
COPY --chown=gridwise:gridwise frontend/index.html /srv/gridwise/frontend/index.html
COPY --chown=gridwise:gridwise frontend/assets /srv/gridwise/frontend/assets
USER gridwise
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health',timeout=2)"
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-access-log"]