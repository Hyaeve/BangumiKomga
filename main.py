import os
import subprocess
import sys
import threading
import time
import runpy

from web_backend import start_web_server
from services.media_policy import scrape_enabled


def main():
    server = start_web_server()
    print("BangumiKomga Web UI: http://0.0.0.0:15600")

    # A fresh container must remain usable before credentials are configured.
    # Once config.py exists, keep the original service modes available.
    config_file = os.path.join(os.path.dirname(__file__), "config", "config.py")

    def service_bootstrap():
        """Restart the scraper worker whenever Web configuration changes."""
        workers = []
        signature = None
        while True:
            try:
                if not os.path.exists(config_file):
                    time.sleep(2)
                    continue
                stat = os.stat(config_file)
                current_signature = (stat.st_mtime_ns, stat.st_size)
                workers_stopped = workers and any(worker.poll() is not None for worker in workers)
                if not workers or workers_stopped or current_signature != signature:
                    for worker in workers:
                        if worker.poll() is not None:
                            continue
                        worker.terminate()
                        try:
                            worker.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            worker.kill()
                            worker.wait(timeout=3)
                    config = runpy.run_path(config_file)
                    servers = config.get("KOMGA_SERVERS", []) or []
                    configured_cards = [card for card in config.get("KOMGA_LIBRARY_LIST", []) or [] if scrape_enabled(card)]
                    card_server_ids = {str(item.get("SERVER_ID")) for item in configured_cards if item.get("SERVER_ID")}
                    server_ids = [str(server.get("id")) for server in servers if str(server.get("id")) in card_server_ids]
                    worker_targets = server_ids or ([""] if configured_cards and not servers else [])
                    workers = []
                    for index, server_id in enumerate(worker_targets):
                        command = [sys.executable, "-m", "services.runtime_service"]
                        if server_id:
                            command.extend(["--server-id", server_id])
                        if index == 0:
                            command.append("--with-archive")
                        workers.append(subprocess.Popen(command, cwd=os.path.dirname(__file__)))
                    if not workers:
                        workers.append(subprocess.Popen(
                            [sys.executable, "-m", "services.runtime_service", "--archive-only"],
                            cwd=os.path.dirname(__file__),
                        ))
                    signature = current_signature
                    print(f"BangumiKomga 刮削服务已加载最新配置，共 {len(workers)} 个监听实例")
            except Exception as exc:
                print(f"BangumiKomga 服务重载失败: {exc}")
            time.sleep(2)

    threading.Thread(target=service_bootstrap, name="ServiceBootstrap", daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
