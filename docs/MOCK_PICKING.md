# Mock picking system (stand-in for KFX / AutoStore)

For proofs of concept, before the real picking system is reachable:

```
WMS ──► inbound SOFTBOT (http_to_signal) ──► signal ──► outbound SOFTBOT (signal_to_http) ──► mock picking system
                                                                                               answers 200, shows message
```

`tools/mock_picking/server.py` (standard library only) accepts what a `signal_to_http` SOFTBOT sends and
answers like a healthy system: any **POST** on **any path** gets `200 {"accepted": true, ...}`. Every message
is listed, newest first, at **http://localhost:9100/**.

## Run it

With Docker Compose it starts together with the WMS (`docker compose up --build`), on port **9100**.
Or run it on its own:
```
python tools/mock_picking/server.py --port 9100
```

## Point the outbound SOFTBOT at it

In the outbound SOFTBOT's `<edge tech>HttpConfig` secret, set `BaseUrl` to the mock's address. Keep your
`OutboundPostUrlPath` (e.g. `/kfx/orders`): the mock accepts every path and shows it.

| SOFTBOT platform runs… | BaseUrl |
|---|---|
| on the same PC as Docker | `http://localhost:9100` (or `http://host.docker.internal:9100` from inside a container) |
| on another machine in your network | `http://<this PC's IP>:9100` (`ipconfig` shows it; allow port 9100 in Windows Firewall) |
| in the cloud (SVT-hosted) | the tunnel's public address, see below |

Authentication: anything is accepted and displayed (none, `ApiKey` header, `Basic`, `OAuth2`). For
`AuthType: OAuth2` set `LoginUrl` to `<BaseUrl>/token`: the mock issues client-credentials tokens there.
To *require* a credential, start it with `--api-key <key>` or `--basic user:password`.

## Cloud-hosted SOFTBOT platform: the tunnel

A cloud platform can't reach `localhost` on your PC. Docker Compose includes a Cloudflare quick tunnel
(free, no account, outbound connection only, so no router or firewall changes are needed) that gives the
mock a public HTTPS address.

1. Put a key in `.env` (project folder), so strangers can't post to or read the mock:
   `MOCK_PICKING_API_KEY=<long random string>`
2. Start everything **with the tunnel profile** (still one terminal):
   `docker compose --profile tunnel up --build -d`
3. Get the public address:
   `docker compose logs tunnel` and look for `https://<random-words>.trycloudflare.com`
4. In the outbound SOFTBOT's `<edge tech>HttpConfig` secret:
   `"BaseUrl": "https://<random-words>.trycloudflare.com", "AuthType": "ApiKey", "PasswordHeaderName": "x-api-key", "PasswordHeaderFormatString": "${password}"`
   and put the key in the `<edge tech>Password` secret.
5. Watch messages arrive at `http://localhost:9100/?key=<key>`.

The quick-tunnel address **changes every time the tunnel restarts**, so update `BaseUrl` after a restart.
For a fixed address use a named Cloudflare tunnel (free Cloudflare account + your own domain) or an ngrok
static domain. A corporate network may block tunnels; if `docker compose logs tunnel` shows connection
errors, try another network or ask IT.

## Testing failure handling

- `?status=503` on the URL path (e.g. `OutboundPostUrlPath: /kfx/orders?status=503`) returns that status,
  which exercises the SOFTBOT's retry (401, 429, 5xx) and fault (other 4xx/5xx) paths.
- `--status 500` makes every message fail; `--delay 30` makes every reply slow (timeout testing).
- `GET /_messages` returns the messages as JSON; `DELETE /_messages` clears them.
