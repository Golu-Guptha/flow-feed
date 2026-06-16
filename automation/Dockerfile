FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create sessions directory
RUN mkdir -p sessions

EXPOSE 5000

CMD ["python", "worker.py"]
