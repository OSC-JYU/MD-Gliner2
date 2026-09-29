# GLiNER2 requires Python 3.10+
FROM python:3.11-slim

WORKDIR /app

# CPU by default; set DEVICE=cuda at runtime on GPU hosts (requires a CUDA-enabled torch install)
ENV DEVICE=cpu

# Create output directory for generated gliner.json files
RUN mkdir -p /app/output

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY api.py service.json ./
COPY help/index.md ./help/index.md

# Expose the port the app runs on
EXPOSE 9010

# Command to run the application
CMD ["python", "api.py"]
