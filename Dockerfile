FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
CMD ["python", "-m", "drive_audit.server"]
