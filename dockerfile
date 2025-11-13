FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY secret_santa.py .

EXPOSE 8501

CMD ["streamlit", "run", "secret_santa.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]