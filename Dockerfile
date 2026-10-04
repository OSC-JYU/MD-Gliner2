# GLiNER2 requires Python 3.10+
FROM python:3.11-slim

WORKDIR /app

# CPU by default; set DEVICE=cuda at runtime on GPU hosts (requires a CUDA-enabled torch install)
ENV DEVICE=cpu \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/models \
    GLINER_MODEL=fastino/gliner2.5-multi-v1

# Create output directory for generated gliner.json files
RUN mkdir -p /app/output

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# The model is part of the image: downloaded once at build time, so the service starts without
# network access and every container of a version runs the same model.
RUN python -c "import os; from gliner2 import AutoExtractor; AutoExtractor.from_pretrained(os.environ['GLINER_MODEL'])" \
 && rm -rf /app/models/xet
ENV HF_HUB_OFFLINE=1

# Copy the application code
COPY api.py md_storage.py service.json ./
COPY help/index.md ./help/index.md

# uid 1000, as in the compose stack
RUN chown -R 1000:1000 /app/output
USER 1000

# Expose the port the app runs on
EXPOSE 9010

# Command to run the application
CMD ["python", "api.py"]
