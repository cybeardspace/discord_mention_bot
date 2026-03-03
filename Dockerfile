FROM python:3.12-slim

# Prevent Python from writing .pyc and buffer logs less
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy bot code
COPY mention_policy_bot.py /app/mention_policy_bot.py

# Config will be stored in /data (a mounted volume)
# Our script reads CONFIG_FILE="config.json" from its working directory,
# so we set working dir to /data and call the script from /app.
WORKDIR /data

CMD ["python", "/app/mention_policy_bot.py"]