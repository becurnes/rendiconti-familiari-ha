FROM python:3.13-alpine
RUN apk add --no-cache openssl ca-certificates
WORKDIR /app
COPY server.py openbanking.py index.html app.js style.css ./
EXPOSE 8099 8100
CMD ["python3", "-u", "server.py"]
