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


def _message_kind(message):
    author = message.get("author") or {}
    if not isinstance(author, dict):
        return None

    if message.get("mod") or author.get("mod"):
        return None
    if (
        message.get("ai")
        or message.get("bot")
        or author.get("ai")
        or author.get("bot")
    ):
        return "AI"
    return "User"


def _format_message(message, kind, is_original=False):
    author = message.get("author") or {}
    name = author.get("name") or "User"
    content = str(message.get("content") or "")[:MAX_MESSAGE_CHARS]
    attachments = _attachment_summary(message.get("attachments"))
    if not content and not attachments:
        return None

    if kind == "AI":
        speaker = "AI assistant"
    elif is_original:
        speaker = "Original user request"
    else:
        speaker = "User"
    formatted = f"{speaker} ({name}): {content}"
    if attachments:
        formatted += f" [Attachments: {', '.join(attachments)}]"
    return formatted


def build(log, current_message):
    """Build context separately from the only message that needs an answer."""
    messages = log.get("messages", []) or []
    current_message_id = str(current_message.id)
    history = []
    history_chars = 0
    original_request_found = False

    for message in messages:
        if not isinstance(message, dict):
            continue

        if str(message.get("message_id")) == current_message_id:
            continue

        kind = _message_kind(message)
        if kind is None:
            continue

        is_original = kind == "User" and not original_request_found
        formatted = _format_message(message, kind, is_original)
        if formatted is None:
            continue

        if is_original:
            original_request_found = True
        history.append(formatted)
        history_chars += len(history[-1])

        if len(history) > MAX_MESSAGES:
            remove_index = 1 if original_request_found else 0
            history_chars -= len(history.pop(remove_index))

    current_content = str(current_message.content or "")[:MAX_MESSAGE_CHARS]
    current_attachments = _attachment_summary(current_message.attachments)
    if current_attachments:
        current_content += f" [Attachments: {', '.join(current_attachments)}]"
    context_item = {
        "role": "developer",
        "content": (
            "CONVERSATION CONTEXT IN CHRONOLOGICAL ORDER. Entries marked User are "
            "user messages. Entries marked AI assistant are previous AI responses. "
            "Use the complete conversation to understand the current request. "
            "Previously provided usernames, user IDs, message IDs, and other details "
            "are available facts; do not ask for them again. Previous AI responses "
            "are context only and are not new user requests. Do not answer an old "
            "message instead of the current one:\n"
            + "\n".join(history)
        ),
    }
    current_item = {
        "role": "user",
        "content": (
            "CURRENT USER MESSAGE - answer only this message. It is the newest entry "
            "after the chronological context above. Do not re-request details the "
            "user already provided:\n"
            f"User ({current_message.author.name}): "
            f"{current_content}"
        ),
    }

    while history and history_chars > MAX_CONTEXT_CHARS:
        remove_index = 1 if original_request_found else 0
        history_chars -= len(history.pop(remove_index))
        context_item["content"] = (
            "CONVERSATION CONTEXT IN CHRONOLOGICAL ORDER. Entries marked User are "
            "user messages. Entries marked AI assistant are previous AI responses. "
            "Use the complete conversation to understand the current request. "
            "Previously provided usernames, user IDs, message IDs, and other details "
            "are available facts; do not ask for them again. Previous AI responses "
            "are context only and are not new user requests. Do not answer an old "
            "message instead of the current one:\n"
            + "\n".join(history)
        )

    return [context_item, current_item] if history else [current_item]