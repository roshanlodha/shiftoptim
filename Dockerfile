FROM python:3.10-slim

# Install system dependencies (libgomp1 is required by Google OR-Tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy application files
COPY . .

# Expose port
EXPOSE 10000

# Seed database and start the app
CMD ["sh", "-c", "python3 -m webapp.seed && gunicorn --bind 0.0.0.0:10000 webapp.wsgi:app"]
