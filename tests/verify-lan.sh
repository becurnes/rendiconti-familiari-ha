#!/usr/bin/env bash
set -euo pipefail

# Reuse the 1.4.0 upgrade fixture, including the pre-existing SQLite database.
docker stop rendiconti-app
docker rm rendiconti-app
docker volume create rendiconti-test-tls
docker run --rm -i --entrypoint sh -v rendiconti-test-data:/data \
  -v rendiconti-test-tls:/fixture rendiconti-test -s <<'FIXTURE'
set -eu
umask 077
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=rendiconti.test \
  -addext subjectAltName=DNS:rendiconti.test \
  -keyout /fixture/lan-privkey.pem -out /fixture/lan-fullchain.pem >/dev/null 2>&1
cat > /fixture/lan-users.htpasswd <<'USERS'
tester:$2b$10$6Z.xKK0ma69xNhB9cLPYTufHdXrh0cWdoQFFc2fP5Z0a2Q9NHemom
USERS
cat > /data/options.json <<'OPTIONS'
{"utente_autorizzato":"titolare","lan_https":true,"lan_hostname":"rendiconti.test","lan_ipv4":"172.30.32.3/32"}
OPTIONS
FIXTURE

docker run -d --name rendiconti-app --network rendiconti-test-net --ip 172.30.32.10 \
  -v rendiconti-test-data:/data -v rendiconti-test-tls:/config:ro rendiconti-test

request() {
  local source="$1"
  shift
  docker run --rm --network rendiconti-test-net --ip "$source" \
    -v rendiconti-test-tls:/fixture:ro --entrypoint /usr/bin/curl rendiconti-test \
    --retry 5 --retry-connrefused --retry-delay 1 --max-time 8 --silent --show-error \
    --resolve rendiconti.test:8443:172.30.32.10 --cacert /fixture/lan-fullchain.pem "$@"
}

url=https://rendiconti.test:8443
allowed=172.30.32.3
fixture_login=tester:password-finta-ci-2026
status=$(request "$allowed" -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 401
status=$(request "$allowed" -o /dev/null -w '%{http_code}' 'http://rendiconti.test:8443/')
test "$status" = 400
status=$(request "$allowed" -u tester:password-errata -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 401
request "$allowed" -u "$fixture_login" -f "$url/api/month?month=2026-10" | \
  python3 -c 'import json, sys; d=json.load(sys.stdin); assert "openBanking" not in d and d["expenses"][0]["cents"] == 999'
status=$(request 172.30.32.4 -u "$fixture_login" -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 403
common=(-u "$fixture_login" -H 'Content-Type: application/json' -H 'X-Rendiconti: 1' -o /dev/null -w '%{http_code}')
status=$(request "$allowed" "${common[@]}" -H "Origin: $url" --data '{"raw":"Data;Descrizione;Importo\n05/10/2026;Test;-12,00"}' "$url/api/bank")
test "$status" = 200
status=$(request "$allowed" "${common[@]}" -H 'Origin: https://other.test' --data '{"raw":"Data;Descrizione;Importo"}' "$url/api/bank")
test "$status" = 403
status=$(request "$allowed" "${common[@]}" -H "Origin: $url" --data '{"action":"status"}' "$url/api/open-banking")
test "$status" = 404

docker run --rm --network rendiconti-test-net --ip 172.30.32.2 --entrypoint /usr/bin/curl \
  rendiconti-test --max-time 5 -fsS -H 'X-Remote-User-Name: titolare' \
  'http://172.30.32.10:8099/api/month?month=2026-10' | \
  python3 -c 'import json, sys; assert "openBanking" not in json.load(sys.stdin)'

# Reuse the existing volume to verify the HTTP listener and the registered expense.
docker rm -f rendiconti-app
docker run --rm -i --entrypoint sh -v rendiconti-test-data:/data rendiconti-test -s <<'FIXTURE'
set -eu
cat > /data/options.json <<'OPTIONS'
{"utente_autorizzato":"titolare","lan_http":true,"lan_http_ip":"172.30.32.10","lan_ipv4":"172.30.32.0/28","lan_http_password":"fixture-http-password-2026"}
OPTIONS
FIXTURE
docker run -d --name rendiconti-app --network rendiconti-test-net --ip 172.30.32.10 \
  -v rendiconti-test-data:/data rendiconti-test
http_request() {
  local source="$1"
  shift
  docker run --rm --network rendiconti-test-net --ip "$source" --entrypoint /usr/bin/curl \
    rendiconti-test --retry 5 --retry-connrefused --retry-delay 1 --max-time 8 --silent --show-error "$@"
}

url=http://172.30.32.10:8100
login=rendiconti:fixture-http-password-2026
status=$(http_request "$allowed" -o /dev/null -w '%{http_code}' "$url/api/month?month=2026-10")
test "$status" = 401
status=$(http_request "$allowed" -u rendiconti:errata -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 401
http_request "$allowed" -u "$login" -f "$url/api/month?month=2026-10" | \
  python3 -c 'import json, sys; d=json.load(sys.stdin); assert "openBanking" not in d and d["expenses"][0]["cents"] == 999'
status=$(http_request 172.30.32.18 -u "$login" -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 403
status=$(http_request "$allowed" -u "$login" -H 'Host: other.test:8100' -o /dev/null -w '%{http_code}' "$url/")
test "$status" = 403
common=(-u "$login" -H 'Content-Type: application/json' -H 'X-Rendiconti: 1' -o /dev/null -w '%{http_code}')
status=$(http_request "$allowed" "${common[@]}" -H "Origin: $url" --data '{"raw":"Data;Descrizione;Importo\n05/10/2026;Test;-12,00"}' "$url/api/bank")
test "$status" = 200
status=$(http_request "$allowed" "${common[@]}" -H 'Origin: http://other.test' --data '{"raw":"Data;Descrizione;Importo"}' "$url/api/bank")
test "$status" = 403
status=$(http_request "$allowed" "${common[@]}" -H "Origin: $url" --data '{"action":"status"}' "$url/api/open-banking")
test "$status" = 404
http_request 172.30.32.2 -fsS -H 'X-Remote-User-Name: titolare' \
  'http://172.30.32.10:8099/api/month?month=2026-10' | \
  python3 -c 'import json, sys; assert "openBanking" not in json.load(sys.stdin)'
