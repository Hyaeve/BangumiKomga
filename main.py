import os
import threading
import time

from web_backend import start_web_server


def main():
    server = start_web_server()
    print("BangumiKomga Web UI: http://0.0.0.0:15600")

    # A fresh container must remain usable before credentials are configured.
    # Once config.py exists, keep the original service modes available.
    config_file = os.path.join(os.path.dirname(__file__), "config", "config.py")

    def service_bootstrap():
        while not os.path.exists(config_file):
            time.sleep(2)
        try:
            from services.service_runner import run_service
            run_service()
        except Exception as exc:
            print(f"BangumiKomga 服务未启动: {exc}")

    threading.Thread(target=service_bootstrap, name="ServiceBootstrap", daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
