import asyncio
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _CogFileHandler(FileSystemEventHandler):
    def __init__(self, bot, loop: asyncio.AbstractEventLoop):
        self._bot      = bot
        self._loop     = loop
        self._debounce = 1.5  # editors often emit 2+ events per save
        self._last: dict[str, float] = {}

    def _to_cog_name(self, path: str) -> str | None:
        p = Path(path)
        if p.suffix != ".py" or p.stem == "__init__":
            return None
        return f"cogs.{p.stem}"

    def on_modified(self, event):
        if event.is_directory:
            return
        cog = self._to_cog_name(event.src_path)
        if not cog:
            return
        self._dispatch(cog, Path(event.src_path).name)

    def on_created(self, event):
        if event.is_directory:
            return
        cog = self._to_cog_name(event.src_path)
        if not cog:
            return
        self._dispatch(cog, Path(event.src_path).name)

    def _dispatch(self, cog: str, filename: str):
        now = time.monotonic()
        if now - self._last.get(filename, 0) < self._debounce:
            return
        self._last[filename] = now
        asyncio.run_coroutine_threadsafe(
            self._reload(cog, filename), self._loop
        )

    async def _reload(self, cog: str, filename: str):
        try:
            if cog in self._bot.extensions:
                await self._bot.reload_extension(cog)
                print(f"[watcher] ✓ reloaded {filename}")
            else:
                await self._bot.load_extension(cog)
                print(f"[watcher] ✓ loaded   {filename}")
        except Exception as exc:
            print(f"[watcher] ✗ {filename}: {exc}")


def start_watcher(bot, loop: asyncio.AbstractEventLoop) -> Observer:
    """
    Start a background observer that reloads or loads any cog whose
    source file is saved.  No static list needed — all .py files in
    cogs/ are watched automatically.
    """
    observer = Observer()
    observer.schedule(_CogFileHandler(bot, loop), path="cogs", recursive=False)
    observer.start()
    print("[watcher] watching cogs/")
    return observer
