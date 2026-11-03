FROM python:3.12-slim
WORKDIR /worker
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vendor/postprocess ./postprocess
COPY vendor/evaluation_pipeline ./evaluation_pipeline
COPY vendor/LICENSE vendor/THIRD_PARTY_NOTICES.md ./licenses/
COPY worker.py .
COPY layout.py .
COPY tests ./tests
RUN useradd --uid 10001 --create-home worker && mkdir -p /home/worker/.paddlex /home/worker/.cache && chown -R worker:worker /home/worker
USER worker
ENV PYTHONUNBUFFERED=1
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
CMD ["python", "worker.py"]
