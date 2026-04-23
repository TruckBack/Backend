from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def _channel(order_id: int) -> str:
    return f"order:{order_id}:track"


class OrderTrackingManager:
    """
    Per-process registry of WebSocket connections, fanned out via Redis pub/sub
    so multiple workers stay in sync.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._pubsub_task: asyncio.Task[None] | None = None
        self._subscribed: set[int] = set()

    async def connect(self, order_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[order_id].add(websocket)
            need_subscribe = order_id not in self._subscribed
            if need_subscribe:
                self._subscribed.add(order_id)
        if need_subscribe:
            asyncio.create_task(self._listen(order_id))

    async def disconnect(self, order_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(order_id)
            if conns:
                conns.discard(websocket)
                if not conns:
                    self._connections.pop(order_id, None)

    async def publish(self, order_id: int, payload: dict[str, Any]) -> None:
        redis = get_redis()
        await redis.publish(_channel(order_id), json.dumps(payload, default=str))

    async def _broadcast_local(self, order_id: int, message: str) -> None:
        async with self._lock:
            targets = list(self._connections.get(order_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                conns = self._connections.get(order_id)
                if conns:
                    for ws in dead:
                        conns.discard(ws)

    async def _listen(self, order_id: int) -> None:
        redis = get_redis()
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(_channel(order_id))
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                await self._broadcast_local(order_id, data)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("PubSub listener crashed for order %s", order_id)
        finally:
            try:
                await pubsub.unsubscribe(_channel(order_id))
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass


tracking_manager = OrderTrackingManager()
