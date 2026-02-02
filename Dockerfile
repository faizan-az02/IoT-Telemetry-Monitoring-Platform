FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first 
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app source
COPY . /app

EXPOSE 5000

# In Docker we must bind 0.0.0.0 so port publishing works.
# Print ONLY the user-facing URL (localhost) to avoid confusion.
# We run Waitress programmatically so we can silence its default INFO banner.
CMD ["python", "-c", "import logging; logging.basicConfig(level=logging.ERROR); logging.getLogger('waitress').setLevel(logging.ERROR); from waitress import serve; from app import create_app; print('Open: http://localhost:5000', flush=True); serve(create_app(), host='0.0.0.0', port=5000)"]

