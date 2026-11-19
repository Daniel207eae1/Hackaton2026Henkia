FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.165.0 uvicorn==0.54.0 pydantic==2.14.4
WORKDIR /app
COPY app.py .
RUN useradd --uid 10002 sim
USER sim
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
