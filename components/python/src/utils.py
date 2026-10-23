"""
Utility functions for the voice agent pipeline.

This module provides helper functions for working with async iterators
and other common operations across the voice agent system.
"""

import asyncio
import re
from typing import Any, AsyncIterator, TypeVar


T = TypeVar("T")

# Text up to the last sentence end and the space after it. A sentence end
# needs the space, so a chunk that ends in "2." waits to see if "5" follows.
SENTENCE_END = re.compile(r"^.*[.!?]\s+", re.DOTALL)
# A long first sentence delays the first audio, so a clause end also sends
# the text once enough has collected. The shared Cartesia context keeps the
# prosody even across the split.
CLAUSE_END = re.compile(r"^.*[,;:]\s+", re.DOTALL)
MIN_CLAUSE_CHARS = 30


def split_speakable(text: str) -> tuple[str, str]:
    """Split agent text into the part ready to speak and the rest to keep."""
    match = SENTENCE_END.match(text)
    if not match and len(text) >= MIN_CLAUSE_CHARS:
        match = CLAUSE_END.match(text)
    if not match:
        return "", text
    return match.group(0), text[match.end() :]


async def merge_async_iters(*aiters: AsyncIterator[T]) -> AsyncIterator[T]:
    """
    Merge multiple async iterators into a single async iterator.

    This function takes any number of async iterators and yields items from all
    of them as they become available, in the order they are produced. This is
    useful for combining multiple event streams (e.g., STT chunks, agent chunks,
    TTS chunks) into a single unified stream for processing.

    The function uses a queue-based approach with producer tasks for each input
    iterator. All iterators are consumed concurrently, and items are yielded as
    soon as any iterator produces them. The merged iterator completes only after
    all input iterators have been exhausted.

    Args:
        *aiters: Variable number of async iterators to merge.

    Yields:
        Items from any of the input iterators, in the order they become
        available.

    Example:
        >>> async def iter1():
        ...     yield 1
        ...     yield 2
        >>> async def iter2():
        ...     yield "a"
        ...     yield "b"
        >>> async for item in merge_async_iters(iter1(), iter2()):
        ...     print(item)  # Could print: 1, 'a', 2, 'b' (order may vary)
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    sentinel = object()

    async def producer(aiter: AsyncIterator[Any]) -> None:
        async for item in aiter:
            await queue.put(item)
        await queue.put(sentinel)

    async with asyncio.TaskGroup() as tg:
        for aiter in aiters:
            tg.create_task(producer(aiter))

        finished = 0
        while finished < len(aiters):
            item = await queue.get()
            if item is sentinel:
                finished += 1
            else:
                yield item
