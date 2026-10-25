FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY demo_fixture.json ./
EXPOSE 8891
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8891"]