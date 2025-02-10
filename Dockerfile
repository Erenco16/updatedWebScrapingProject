FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app/src

# Install system dependencies for Selenium, Chromium, and netcat
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip chromium chromium-driver netcat-openbsd \
    libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 \
    libx11-xcb1 libxcomposite1 libxcursor1 libxi6 libxtst6 \
    libxrandr2 libasound2 libpangocairo-1.0-0 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 && \
    rm -rf /var/lib/apt/lists/*

# Ensure the ChromeDriver binary is in the default PATH
RUN ln -s /usr/bin/chromium-driver /usr/local/bin/chromedriver

# Copy requirements and install dependencies
COPY requirements.txt /app/src/
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the `src/` directory contents into `/app/src/`
COPY src/ /app/src/

# Add the wait-for-it.sh script for service readiness
COPY wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV webdriver.chrome.driver="/usr/bin/chromedriver"

# Run the application
CMD ["bash", "/wait-for-it.sh", "selenium-hub", "4444", "--", "python", "/app/src/main.py"]
