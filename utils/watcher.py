import asyncio
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# Maps "auto_mod.py" → "cogs.auto_mod" etc.
def _build_cog_map(cogs: list[str]) -> dict[str, str]:
    return {cog.split(".")[-1] + ".py": cog for cog in cogs}


class _CogFileHandler(FileSystemEventHandler):
    def __init__(self, bot, loop: asyncio.AbstractEventLoop, cog_map: dict[str, str]):
        self._bot     = bot
        self._loop    = loop
        self._cog_map = cog_map
        self._last_reload: dict[str, float] = {}
        self._debounce = 1.5  # seconds — editors often emit 2+ events per save

    def on_modified(self, event):
        if event.is_directory:
            return

        filename = Path(event.src_path).name
        cog_name = self._cog_map.get(filename)
        if not cog_name:
            return

        # Debounce
        now = time.monotonic()
        if now - self._last_reload.get(filename, 0) < self._debounce:
            return
        self._last_reload[filename] = now

        asyncio.run_coroutine_threadsafe(self._reload(cog_name, filename), self._loop)

    async def _reload(self, cog_name: str, filename: str):
        try:
            await self._bot.reload_extension(cog_name)
            print(f"[watcher] ✓ {filename}")
        except Exception as exc:
            print(f"[watcher] ✗ {filename}: {exc}")


def start_watcher(bot, loop: asyncio.AbstractEventLoop, cogs: list[str]) -> Observer:
    """
    Start a background file-system observer that reloads a cog whenever
    its source file is modified.  Returns the Observer so the caller can
    stop it on shutdown.
    """
    cog_map  = _build_cog_map(cogs)
    handler  = _CogFileHandler(bot, loop, cog_map)
    observer = Observer()
    observer.schedule(handler, path="cogs", recursive=False)
    observer.start()
    print(f"[watcher] Watching cogs/ — {len(cog_map)} cog(s) tracked")
    return observer
