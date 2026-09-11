"""Isolated task worker: stopping it also stops pending AI/Komga requests."""
import json
import sys
from tools.task_lock_policy import task_lock_options


def main():
    import web_backend
    request = json.load(sys.stdin)
    task = request["task"]
    targets = task.get("card_ids") or []
    function = request["function"]
    if function == "card_collage_refresh":
        web_backend._refresh_card_collages(targets)
    elif function == "metadata_correction":
        web_backend._translate_task_libraries(targets, task.get("fields", []),
                                             correction=[value for value in task.get("operations", []) if value != "include_locked"],
                                             filter_terms=task.get("filter_terms", ""),
                                             filter_regex=bool(task.get("filter_regex", False)),
                                             include_volumes=bool(task.get("include_volumes", True)), **task_lock_options(task))
    elif function == "summary_translation":
        web_backend._translate_task_libraries(targets, task.get("fields") or ["summary"],
                                             include_volumes=bool(task.get("include_volumes", True)), **task_lock_options(task))
    else:
        raise ValueError("Unknown task function")


if __name__ == "__main__":
    main()
