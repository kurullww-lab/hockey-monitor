FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=10000
CMD ["python", "d.py"]
