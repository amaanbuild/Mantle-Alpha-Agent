"""
Block monitor.

Continuously polls Mantle for new blocks, fetches Transfer/Swap logs, normalizes
them into :class:`ChainEvent` objects, runs whale detection, and forwards each
:class:`WhaleTransaction` to an injected async handler (the alert engine).

Cursor state (last processed block) is persisted to Redis when available so the
monitor resumes without gaps after a restart; otherwise it tracks in memory.

Design notes
------------
- The minimum whale gate is recomputed each cycle from the smallest active rule
  threshold, so the monitor self-tunes to what users actually track.
- All RPC failures are caught and retried on the next cycle; the loop never dies
  on a transient node error.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from backend.blockchain.abi import SWAP_V2_TOPIC, TRANSFER_TOPIC
from backend.blockchain.client import MantleClient, get_mantle_client
from backend.blockchain.events import EventNormalizer
from backend.blockchain.whale import WhaleDetector
from backend.config import settings
from backend.core.domain import WhaleTransaction
from backend.core.logging import get_logger

logger = get_logger(__name__)

WhaleHandler = Callable[[WhaleTransaction], Awaitable[None]]
ThresholdProvider = Callable[[], Awaitable[float]]

_REDIS_CURSOR_KEY = "monitor:last_block"


class BlockMonitor:
    """Polls Mantle blocks and emits whale transactions to a handler."""

    def __init__(
        self,
        on_whale: WhaleHandler,
        client: MantleClient | None = None,
        detector: WhaleDetector | None = None,
        min_threshold_provider: ThresholdProvider | None = None,
        redis_client=None,
    ) -> None:
        self.client = client or get_mantle_client()
        self.normalizer = EventNormalizer(self.client)
        self.detector = detector or WhaleDetector()
        self.on_whale = on_whale
        self._min_threshold_provider = min_threshold_provider
        self._redis = redis_client
        self._last_block: int | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Run the monitor loop until :meth:`stop` is called."""
        self._running = True
        self._stop_event.clear()
        logger.info("monitor.starting", rpc=self.client.rpc_url)

        if not await self.client.is_connected():
            logger.error("monitor.rpc_unreachable", rpc=self.client.rpc_url)

        await self._init_cursor()

        while self._running:
            try:
                await self.poll_once()
            except Exception as exc:  # never let the loop die
                logger.error("monitor.cycle_failed", error=str(exc))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=settings.BLOCK_POLL_INTERVAL
                )
            except TimeoutError:
                pass  # normal: poll interval elapsed
        logger.info("monitor.stopped")

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Core polling                                                        #
    # ------------------------------------------------------------------ #
    async def poll_once(self) -> int:
        """Process any new finalized blocks once. Returns #whales emitted."""
        head = await self.client.get_block_number()
        target = head - settings.BLOCK_CONFIRMATIONS
        if self._last_block is None:
            self._last_block = target - 1

        if target <= self._last_block:
            return 0  # nothing new yet

        from_block = self._last_block + 1
        # Cap batch size to avoid huge RPC responses during back-fill.
        to_block = min(target, from_block + settings.MAX_BLOCKS_PER_BATCH - 1)

        whales = await self._process_range(from_block, to_block)

        self._last_block = to_block
        await self._save_cursor(to_block)
        return whales

    async def _process_range(self, from_block: int, to_block: int) -> int:
        logger.debug("monitor.scanning", from_block=from_block, to_block=to_block)
        gate = await self._current_gate()

        # One get_logs call per event type keeps topic filters simple.
        logs: list[dict] = []
        for topic in (TRANSFER_TOPIC, SWAP_V2_TOPIC):
            try:
                batch = await self.client.get_logs(
                    from_block=from_block, to_block=to_block, topics=[topic]
                )
                logs.extend(batch)
            except Exception as exc:
                logger.warning("monitor.get_logs_failed", topic=topic, error=str(exc))

        emitted = 0
        for log in logs:
            event = await self.normalizer.normalize_log(log)
            if event is None:
                continue
            whale = await self.detector.evaluate(event, min_threshold_usd=gate)
            if whale is None:
                continue
            try:
                await self.on_whale(whale)
                emitted += 1
            except Exception as exc:
                logger.error("monitor.handler_failed", error=str(exc), tx=event.tx_hash)
        if emitted:
            logger.info(
                "monitor.range_done", from_block=from_block, to_block=to_block, whales=emitted
            )
        return emitted

    async def _current_gate(self) -> float:
        if self._min_threshold_provider is None:
            return settings.MIN_WHALE_THRESHOLD_USD
        try:
            return await self._min_threshold_provider()
        except Exception as exc:  # pragma: no cover - resilience
            logger.warning("monitor.threshold_provider_failed", error=str(exc))
            return settings.MIN_WHALE_THRESHOLD_USD

    # ------------------------------------------------------------------ #
    # Cursor persistence                                                  #
    # ------------------------------------------------------------------ #
    async def _init_cursor(self) -> None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(_REDIS_CURSOR_KEY)
                if raw is not None:
                    self._last_block = int(raw)
                    logger.info("monitor.cursor_restored", block=self._last_block)
                    return
            except Exception as exc:  # pragma: no cover
                logger.warning("monitor.cursor_restore_failed", error=str(exc))
        self._last_block = None  # will initialize to head-1 on first poll

    async def _save_cursor(self, block: int) -> None:
        if self._redis is not None:
            try:
                await self._redis.set(_REDIS_CURSOR_KEY, block)
            except Exception as exc:  # pragma: no cover
                logger.warning("monitor.cursor_save_failed", error=str(exc))
