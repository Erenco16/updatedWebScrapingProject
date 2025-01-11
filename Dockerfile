# Use a lightweight Python image
FROM python:3.9-slim

# Set the working directory
WORKDIR /src

# Install system dependencies for Selenium, Chromium, and netcat
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    chromium \
    chromium-driver \
    netcat-openbsd \
    libglib2.0-0 \
    libnss3 \
    libgconf-2-4 \
    libfontconfig1 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 && \
    apt-get clean

# Ensure the ChromeDriver binary is in the default PATH
RUN ln -s /usr/bin/chromium-driver /usr/local/bin/chromedriver

# Copy requirements file and install Python dependencies
COPY requirements.txt /src/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY src/ /src/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV webdriver.chrome.driver="/usr/bin/chromedriver"

# Command to run the application
CMD ["python", "main.py"]
