FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY frontend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY frontend/app.py ./app.py
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
