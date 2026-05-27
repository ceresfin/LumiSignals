"""IBKR Client Portal API websocket client.

Replaces HTTP polling of order/fill state with a push-based stream so the
sync loop can react in ~200ms instead of ~10s. Built on top of IBeam's
proxy at wss://localhost:5000/v1/api/ws.

Wire format notes captured from live IBeam probe (see scoping doc):

  Auth        cookie-based. POST /v1/api/tickle returns Set-Cookie:
              x-sess-uuid=...; connect WS with the same cookie. No
              text-message session handshake — that path returns
              {"error":"Topic unknown ...","code":1}.

  Greeting    server immediately sends three frames:
                {"topic":"system","success":<user>,"isFT":true,"isPaper":true}
                {"topic":"act","args":{"accounts":[...], ...}}
                {"topic":"sts","args":{"connected":true,"authenticated":true,...}}

  Heartbeat   {"topic":"system","hb":<unix ms>} every ~10s.

  Subscribe   send the literal text "sor+{}" / "str+{}" / "spl+{}".
              Subscription accepted silently (no ack frame).

Keepalive: WS *and* /tickle are both required; tickle every 60s in a
parallel task, the WS keeps its own ping_interval. Dropping either kills
the session.

Reconnect: there is no message replay on the server side, so on every
reconnect the caller should HTTP-fetch full state (positions + open
orders) and rebuild whatever derived state it cares about, *then* resume
streaming. The caller passes a `on_resync` callback we invoke after each
successful (re)connect for exactly that.

This module is pure I/O — no business logic. The caller registers an
`on_event` callback that receives parsed-JSON frames; what to do with
them (update a position ledger, mark order status, etc.) lives elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from typing import Awaitable, Callable, Iterable, Optional

import requests
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict], Awaitable[None]]
ResyncCallback = Callable[[], Awaitable[None]]


class IBKRWebSocketClient:
    """Long-lived websocket client with auto-reconnect.

    Usage:
        client = IBKRWebSocketClient(
            base_url="https://localhost:5000/v1/api",
            topics=["sor+{}", "str+{}"],
            on_event=handle_event,
            on_resync=rebuild_state_from_http,
        )
        await client.run()  # blocks forever; cancel the task to stop

    `on_event` is invoked for every non-heartbeat frame. `on_resync` is
    invoked once on initial connect and once after every successful
    reconnect — the caller should refetch full state via HTTP there.
    """

    def __init__(
        self,
        base_url: str,
        topics: Iterable[str],
        on_event: EventCallback,
        on_resync: Optional[ResyncCallback] = None,
        tickle_interval: int = 60,
        backoff_start: float = 1.0,
        backoff_cap: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        ) + "/ws"
        self.tickle_url = self.base_url + "/tickle"
        self.topics = list(topics)
        self.on_event = on_event
        self.on_resync = on_resync
        self.tickle_interval = tickle_interval
        self.backoff_start = backoff_start
        self.backoff_cap = backoff_cap
        # IBeam exposes a self-signed cert on localhost; CPAPI auth handles
        # security and the local hop is trusted.
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE
        self._stop = asyncio.Event()
        self._connected = False

    def stop(self) -> None:
        self._stop.set()

    @property
    def connected(self) -> bool:
        return self._connected

    def _tickle_sync(self) -> dict[str, str]:
        """POST /tickle and return the cookies. Synchronous because we
        only do this once per (re)connect; not worth pulling in aiohttp."""
        r = requests.post(self.tickle_url, data="", verify=False, timeout=5)
        r.raise_for_status()
        return r.cookies.get_dict()

    async def _tickle_loop(self) -> None:
        """Keep the CPAPI session alive while the WS is open. Without this
        the gateway drops the session after ~5min and the WS goes dead
        with no obvious error frame."""
        while not self._stop.is_set():
            try:
                await asyncio.sleep(self.tickle_interval)
                # Best-effort; if it fails, the connect loop will reconnect
                # when the WS dies anyway.
                await asyncio.to_thread(self._tickle_sync)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("tickle failed (will retry): %s", e)

    async def _consume(self, ws) -> None:
        """Read frames until the connection closes. Heartbeats are
        swallowed silently; everything else goes to on_event."""
        async for raw in ws:
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8")
                except Exception:
                    continue
            try:
                msg = json.loads(raw)
            except Exception:
                logger.debug("non-JSON frame: %r", raw[:200])
                continue
            # Heartbeats arrive every ~10s and are pure noise to the caller.
            if msg.get("topic") == "system" and "hb" in msg:
                continue
            try:
                await self.on_event(msg)
            except Exception as e:
                logger.exception("on_event handler raised: %s", e)

    async def _connect_once(self) -> None:
        """One connect attempt. Caller wraps with backoff."""
        cookies = self._tickle_sync()
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {"Cookie": cookie_header}

        logger.info("WS connecting %s", self.ws_url)
        async with websockets.connect(
            self.ws_url,
            ssl=self._ssl_ctx,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=15,
            close_timeout=5,
        ) as ws:
            self._connected = True
            logger.info("WS open — subscribing %s", self.topics)
            for sub in self.topics:
                await ws.send(sub)

            tickler = asyncio.create_task(self._tickle_loop())
            try:
                if self.on_resync:
                    # Fire-and-log; if rebuild fails the next reconcile
                    # tick will catch it. Don't block streaming.
                    try:
                        await self.on_resync()
                    except Exception:
                        logger.exception("on_resync callback failed")
                await self._consume(ws)
            finally:
                tickler.cancel()
                try:
                    await tickler
                except asyncio.CancelledError:
                    pass
                self._connected = False

    async def run(self) -> None:
        """Run forever — reconnect with exponential backoff on any failure.
        Cancel the task or call .stop() to exit cleanly."""
        backoff = self.backoff_start
        while not self._stop.is_set():
            try:
                await self._connect_once()
                # Clean close (server hung up or local stop) → reset backoff
                backoff = self.backoff_start
                if self._stop.is_set():
                    break
                logger.warning("WS closed cleanly; reconnecting in %.1fs", backoff)
            except ConnectionClosed as e:
                logger.warning("WS dropped (%s); reconnect in %.1fs", e, backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("WS connect failed: %s; retry in %.1fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.backoff_cap)
