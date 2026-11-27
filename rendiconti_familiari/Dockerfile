FROM python:3.13-alpine3.24@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e
RUN apk add --no-cache openssl=3.5.9-r1 libcrypto3=3.5.9-r1 libssl3=3.5.9-r1 \
    curl=8.23.0-r0 libcurl=8.23.0-r0 nginx=1.30.8-r0 \
    && addgroup -S -g 10001 rendiconti \
    && adduser -S -D -H -u 10001 -G rendiconti rendiconti
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt
COPY bootstrap.py server.py openbanking.py lan_https.py lan-nginx.conf index.html app.js style.css ./
EXPOSE 8099 8443
CMD ["python3", "-I", "-B", "-u", "/app/bootstrap.py"]
