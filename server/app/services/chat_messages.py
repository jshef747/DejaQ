from __future__ import annotations


def _get(message: object, key: str) -> object:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def extract_pipeline_inputs(messages: list[object]) -> tuple[str, list[dict], str | None]:
    user_query = ""
    for message in reversed(messages):
        if _get(message, "role") == "user":
            content = _get(message, "content")
            user_query = content if isinstance(content, str) else ""
            break

    system_parts = [
        str(_get(message, "content"))
        for message in messages
        if _get(message, "role") == "system" and isinstance(_get(message, "content"), str)
    ]
    system_prompt = "\n".join(system_parts) if system_parts else None

    last_user_idx = -1
    for index in reversed(range(len(messages))):
        if _get(messages[index], "role") == "user":
            last_user_idx = index
            break

    history = [
        {"role": _get(message, "role"), "content": _get(message, "content")}
        for message in messages[:last_user_idx]
        if _get(message, "role") in ("user", "assistant")
    ]

    return user_query, history, system_prompt
