from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def _chat_channel(order_id: int) -> str:
    return f"chat:{order_id}"


class ChatConnectionManager:
    """
    Per-process registry of chat WebSocket connections, fanned out via Redis
    pub/sub so multiple workers stay in sync.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
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

    async def publish(self, order_id: int, event: dict[str, Any]) -> None:
        redis = get_redis()
        await redis.publish(_chat_channel(order_id), json.dumps(event, default=str))

    async def _broadcast_local(self, order_id: int, message: str) -> None:
        async with self._lock:
            targets = list(self._connections.get(order_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(order_id, ws)

    async def _listen(self, order_id: int) -> None:
        redis = get_redis()
        channel = _chat_channel(order_id)
        async with redis.pubsub() as pubsub:
            await pubsub.subscribe(channel)
            try:
                async for raw in pubsub.listen():
                    if raw["type"] != "message":
                        continue
                    async with self._lock:
                        still_connected = bool(self._connections.get(order_id))
                    if not still_connected:
                        break
                    await self._broadcast_local(order_id, raw["data"])
            except Exception as exc:
                logger.warning("Chat pubsub listener error for order %s: %s", order_id, exc)
            finally:
                async with self._lock:
                    self._subscribed.discard(order_id)


chat_manager = ChatConnectionManager()
