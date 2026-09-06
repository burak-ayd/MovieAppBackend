from rich.console import Console
from rich.style import Style
from contextlib import suppress
from asyncio    import get_event_loop
from pathlib    import Path
from shutil     import rmtree
from traceback  import format_exc
import os, platform
        
konsol = Console(log_path = False,)

def bellek_temizle():
    with suppress(Exception):
        [alt_dizin.unlink() for alt_dizin in Path(".").rglob("*.py[coi]")]
    with suppress(Exception):
        [alt_dizin.rmdir()  for alt_dizin in Path(".").rglob("__pycache__")]
    with suppress(Exception):
        [rmtree(alt_dizin)  for alt_dizin in Path(".").rglob("*.build")]
    with suppress(Exception):
        [alt_dizin.unlink() for alt_dizin in Path(".").rglob("*.bak")]

bellek_temizle()

def cikis_yap(_print=True):
    with suppress(RuntimeError):
        loop = get_event_loop()
    with suppress(RuntimeError, UnboundLocalError):
        if loop.is_running():
            # with suppress(RuntimeError):
            #     loop.run_until_complete(loop.shutdown_asyncgens())
            with suppress(RuntimeError):
                loop.stop()
            with suppress(RuntimeError):
                loop.close()

    if _print:
        konsol.print("\n\n")
        konsol.log("[bold purple]Çıkış Yapıldı..")

    bellek_temizle()
    os._exit(0)