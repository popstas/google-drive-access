FROM python:3.12-slim
WORKDIR /app

# Copy dependency files first for better cache utilization
COPY pyproject.toml ./

# Install dependencies only from pyproject.toml (this layer is cached unless dependencies change)
# Extract dependencies from pyproject.toml and install them
RUN python -c "import tomllib, subprocess; f=open('pyproject.toml','rb'); data=tomllib.load(f); f.close(); subprocess.run(['pip', 'install', '--no-cache-dir'] + data['project']['dependencies'], check=True)"

# Copy source code (this layer will be invalidated when source changes)
COPY src/ ./src/
COPY pyproject.toml ./

# Install the package (fast since dependencies are already installed)
RUN pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "drive_audit.server"]
