# Use official Python 3.11 slim image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files, knowledge base, and data fixtures
COPY . .

# Run unit tests and evaluation suite on container build
RUN python -m unittest discover tests && python eval.py

# Default entrypoint runs CLI interface
ENTRYPOINT ["python", "cli.py"]
