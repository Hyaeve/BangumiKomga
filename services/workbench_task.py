"""Run selected-series corrections in the existing isolated task executor."""
import json
import sys


def main():
    import web_backend as backend
    request = json.load(sys.stdin)
    action = request["action"]
    backend._translate_task_libraries(
        [request["card"]], fields=request["fields"],
        correction=[action] if action in {"simplify", "extract_title"} else None,
        include_volumes=False, lock_completed=action == "summary_translation",
        series_ids=request["series_ids"],
    )


if __name__ == "__main__":
    main()
