FROM python:3.13-alpine
WORKDIR /app
COPY server.py index.html app.js style.css ./
EXPOSE 8099 8100
CMD ["python3", "-u", "server.py"]
