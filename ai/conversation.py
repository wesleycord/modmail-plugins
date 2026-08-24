import mimetypes
from pathlib import PurePath


MAX_MESSAGES = 200
MAX_CONTEXT_CHARS = 24000
MAX_MESSAGE_CHARS = 4000


def _attachment_summary(attachments):
    summaries = []
    for attachment in attachments or []:
        if isinstance(attachment, dict):
            name = attachment.get("filename") or attachment.get("name")
            file_type = attachment.get("content_type") or attachment.get("type")
        else:
            name = getattr(attachment, "filename", None) or getattr(
                attachment, "name", None
            )
            file_type = getattr(attachment, "content_type", None) or getattr(
                attachment, "type", None
            )

        if not name:
            name = "unnamed attachment"
        if not file_type:
            file_type = mimetypes.guess_type(str(name))[0] or PurePath(
                str(name)
            ).suffix.lstrip(".") or "unknown file type"

        summaries.append(f"{name} ({file_type})")

    return summaries


def build(log, current_message):
    """Build context separately from the only message that needs an answer."""
    messages = log.get("messages", [])
    current_message_id = str(current_message.id)
    history = []
    history_is_ai = []
    history_is_original = []
    history_chars = 0
    original_request_found = False

    for message in messages[-MAX_MESSAGES:]:
        if str(message.get("message_id")) == current_message_id:
            continue

        content = message.get("content") or ""
        attachments = _attachment_summary(message.get("attachments"))

        if not content and not attachments:
            continue

        author = message.get("author", {})
        name = author.get("name", "User")
        is_staff = author.get("mod", False)
        is_ai = author.get("bot", False) or author.get("ai", False)
        is_original = not is_staff and not is_ai and not original_request_found
        if is_original:
            original_request_found = True
        content = content[:MAX_MESSAGE_CHARS]

        speaker = (
            "Original user request"
            if is_original
            else "AI"
            if is_ai
            else "Staff"
            if is_staff
            else "User"
        )
        history.append(
            f"{speaker} ({name}): {content[:MAX_MESSAGE_CHARS]}"
        )
        if attachments:
            history[-1] += f" [Attachments: {', '.join(attachments)}]"
        history_is_ai.append(is_ai)
        history_is_original.append(is_original)
        history_chars += len(history[-1])

    current_content = current_message.content[:MAX_MESSAGE_CHARS]
    current_attachments = _attachment_summary(current_message.attachments)
    if current_attachments:
        current_content += f" [Attachments: {', '.join(current_attachments)}]"
    context_item = {
        "role": "developer",
        "content": (
            "CONVERSATION CONTEXT. The original user request is marked clearly. "
            "Use it with the later messages to resolve the user's issue. "
            "Do not answer an old message instead of the current one:\n"
            + "\n".join(history)
        ),
    }
    current_item = {
        "role": "user",
        "content": (
            "CURRENT USER MESSAGE - answer only this message:\n"
            f"User ({current_message.author.name}): "
            f"{current_content}"
        ),
    }

    while history and history_chars > MAX_CONTEXT_CHARS:
        remove_index = next(
            (index for index, is_ai in enumerate(history_is_ai) if is_ai),
            next(
                (
                    index
                    for index, is_original in enumerate(history_is_original)
                    if not is_original
                ),
                0,
            ),
        )
        history_chars -= len(history.pop(remove_index))
        history_is_ai.pop(remove_index)
        history_is_original.pop(remove_index)
        context_item["content"] = (
            "CONVERSATION CONTEXT. The original user request is marked clearly. "
            "Use it with the later messages to resolve the user's issue. "
            "Do not answer an old message instead of the current one:\n"
            + "\n".join(history)
        )

    return [context_item, current_item] if history else [current_item]