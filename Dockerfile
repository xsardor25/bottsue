FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
# Brauzerlarni tizim darajasida o'rnatish
RUN playwright install chromium --with-deps
CMD ["python", "main.py"]
