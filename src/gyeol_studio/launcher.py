"""Double-click entry point: start the server, open the browser, keep a small window with the app's state.

* http on this PC (``http://127.0.0.1:<port>``) — browsers treat localhost as secure, so the microphone works;
* https on the LAN (``https://<pc address>:<https_port>``) for phones on the same Wi-Fi, with a local certificate
  (``certs.py``); the plain http port also answers on the LAN, but only to hand out the certificate and to redirect
  to https.

If the app is already running, a second double-click only opens the browser.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import multiprocessing
import os
import sys
import threading
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

from . import __version__
from .settings import Layout, load_settings, save_settings, settings_path

log = logging.getLogger("gyeol_studio")


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as r:  # noqa: S310 - localhost
            return "version" in json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _setup_logging(layout: Layout) -> None:
    layout.logs.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(layout.logs / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)


class Runner:
    """The uvicorn listeners (one asyncio loop in a thread) and the background workers."""

    def __init__(self, settings, *, console: bool):
        import uvicorn

        from .server import create_app, start_background

        self.settings = settings
        self.layout = Layout(settings.data_dir)
        self.layout.ensure()
        https_info = {}
        ssl = None
        host = "0.0.0.0" if settings.lan else "127.0.0.1"
        port = settings.port
        while not _port_free(host, port) and port < settings.port + 20:
            port += 2
        self.port = port
        if settings.lan:
            try:
                from .certs import ensure_server_cert, lan_addresses

                addrs = lan_addresses()
                crt, key = ensure_server_cert(addrs)
                hport = settings.https_port if port == settings.port else port + 1
                ssl = (str(crt), str(key), hport)
                https_info = {"port": hport, "addresses": addrs, "http_port": port}
            except Exception:  # noqa: BLE001 - phones are optional; the PC keeps working without https
                log.exception("https setup failed")
        self.app = create_app(settings, https_info=https_info)
        self.state = self.app.state.studio
        self.state.restart_hook = self.request_restart
        self.restart_requested = False
        start_background(self.state)
        cfgs = [uvicorn.Config(self.app, host=host, port=port, log_level="warning", access_log=False, lifespan="off")]
        if ssl:
            cfgs.append(uvicorn.Config(self.app, host="0.0.0.0", port=ssl[2], ssl_certfile=ssl[0], ssl_keyfile=ssl[1], log_level="warning",
                                       access_log=False, lifespan="off"))
        self.servers = [uvicorn.Server(c) for c in cfgs]
        for s in self.servers:
            s.install_signal_handlers = lambda: None  # signals are handled by the main thread
        self.thread = threading.Thread(target=self._serve, daemon=True, name="uvicorn")
        self.done = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def _serve(self) -> None:
        async def run():
            await asyncio.gather(*(s.serve() for s in self.servers))

        try:
            asyncio.run(run())
        finally:
            self.done.set()

    def start(self) -> bool:
        from .server import wait_for_port

        self.thread.start()
        return wait_for_port("127.0.0.1", self.port, timeout=30)

    def stop(self) -> None:
        for s in self.servers:
            s.should_exit = True
        self.done.wait(10)
        if self.state.workers:
            self.state.workers.stop()

    def request_restart(self) -> None:
        self.restart_requested = True
        threading.Timer(0.5, self._quit_cb).start()

    _quit_cb = staticmethod(lambda: None)


def _restart_process() -> None:
    args = [sys.executable] + ([] if getattr(sys, "frozen", False) else ["-m", "gyeol_studio"]) + [a for a in sys.argv[1:] if a != "--no-browser"]
    args.append("--no-browser")
    import subprocess

    subprocess.Popen(args, close_fds=True)  # noqa: S603 - restarts this same program


def _fatal(message: str, *, console: bool) -> None:
    """Startup failed: say what happened and what to do — in a dialog, since the packaged app has no console."""
    print(message, file=sys.stderr)
    log.error("startup failed: %s", message)
    if console:
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("gyeol 스튜디오", message)
        root.destroy()
    except Exception:  # noqa: BLE001 - no display: the message went to stderr and the log
        pass


def _startup_message(exc: BaseException, data_dir: str) -> str:
    from .messages import korean_reason

    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, PermissionError) or "Permission denied" in text or "Errno 13" in text or "read-only" in text.lower():
        return f"데이터 폴더({data_dir})에 저장할 수 없어서 시작하지 못했어요. 폴더 권한을 확인하거나, 설정 파일에서 다른 폴더를 지정해 주세요."
    if "No space left" in text or "Errno 28" in text:
        return "저장 공간이 부족해서 시작하지 못했어요. 디스크 공간을 비운 뒤 다시 실행해 주세요."
    known = korean_reason(text)
    if known == korean_reason(""):  # nothing specific: point to the log the team can read
        known = "PC를 다시 시작한 뒤에도 같으면, 아래 내용과 데이터 폴더의 logs/app.log 파일을 개발팀에 보내 주세요."
    return f"gyeol 스튜디오를 시작하지 못했어요. {known}\n\n({text[:300]})"


def _tk_window(runner: Runner) -> bool:
    """A small status window (closing it quits the app).  Returns False when Tk is not available."""
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001 - no display
        return False
    root.title("gyeol 스튜디오")
    root.geometry("380x200")
    root.resizable(False, False)
    tk.Label(root, text="gyeol 스튜디오가 실행 중이에요", font=("", 13, "bold")).pack(pady=(18, 4))
    tk.Label(root, text="브라우저에서 앱을 쓰세요. 이 창을 닫으면 앱이 꺼져요.", fg="#555").pack()
    tk.Label(root, text=runner.url, fg="#0a58ca").pack(pady=(4, 10))
    row = tk.Frame(root)
    row.pack()
    tk.Button(row, text="브라우저 열기", width=12, command=lambda: webbrowser.open(runner.url)).pack(side="left", padx=4)
    tk.Button(row, text="휴대폰 연결", width=12, command=lambda: webbrowser.open(runner.url + "#/connect")).pack(side="left", padx=4)
    tk.Button(row, text="끝내기", width=8, command=root.destroy).pack(side="left", padx=4)

    def quit_from_restart():
        root.after(0, root.destroy)

    runner._quit_cb = quit_from_restart
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return True


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    ap = argparse.ArgumentParser(prog="gyeol-studio", description="gyeol 스튜디오 실행")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않아요")
    ap.add_argument("--console", action="store_true", help="창 없이 터미널에서 실행해요")
    ap.add_argument("--data-dir", help="데이터 폴더 (이번 실행만)")
    ap.add_argument("--port", type=int, help="http 포트 (이번 실행만)")
    ap.add_argument("--no-lan", action="store_true", help="휴대폰 접속(https)을 끄고 이 PC에서만 열어요")
    ap.add_argument("--version", action="version", version=f"gyeol-studio {__version__}")
    args = ap.parse_args(argv)
    first_run = not settings_path().exists()
    settings = load_settings()
    if first_run:
        save_settings(settings)
    if args.data_dir:
        settings.data_dir = os.environ["GYEOL_STUDIO_DATA"] = os.path.abspath(args.data_dir)
    if args.port:
        settings.port, settings.https_port = args.port, args.port + 1
    if args.no_lan:
        settings.lan = False
    if _already_running(settings.port):
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{settings.port}/")
        print("gyeol 스튜디오가 이미 실행 중이에요. 브라우저를 열었어요.")
        return 0
    try:
        _setup_logging(Layout(settings.data_dir))
        log.info("starting gyeol-studio %s, data %s", __version__, settings.data_dir)
        runner = Runner(settings, console=args.console)
    except Exception as exc:  # noqa: BLE001 - shown to the person instead of a silent exit
        log.exception("startup failed")
        _fatal(_startup_message(exc, settings.data_dir), console=args.console)
        return 1
    if not runner.start():
        _fatal("앱 서버를 시작하지 못했어요. 다른 프로그램이 같은 포트를 쓰고 있을 수 있어요. PC를 다시 시작한 뒤 다시 실행해 주세요.",
               console=args.console)
        runner.stop()
        return 1
    if settings.open_browser and not args.no_browser:
        webbrowser.open(runner.url)
    print(f"gyeol 스튜디오가 실행 중이에요: {runner.url}")
    if runner.state.https_info:
        h = runner.state.https_info
        for a in h.get("addresses", []):
            print(f"  휴대폰(같은 와이파이): https://{a}:{h['port']}/")
    shown = False if args.console else _tk_window(runner)
    if not shown:
        print("끝내려면 이 창에서 Ctrl+C를 누르세요.")
        try:
            while runner.thread.is_alive() and not runner.restart_requested:
                runner.done.wait(0.5)
        except KeyboardInterrupt:
            pass
    runner.stop()
    if runner.restart_requested:
        _restart_process()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
