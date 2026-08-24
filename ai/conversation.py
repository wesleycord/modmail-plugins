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


def _is_user_message(message):
    author = message.get("author") or {}
    if not isinstance(author, dict):
        return False

    return not (
        message.get("bot")
        or message.get("ai")
        or author.get("bot")
        or author.get("ai")
        or author.get("mod")
    )


def _format_user_message(message, is_original):
    author = message.get("author") or {}
    name = author.get("name") or "User"
    content = str(message.get("content") or "")[:MAX_MESSAGE_CHARS]
    attachments = _attachment_summary(message.get("attachments"))
    if not content and not attachments:
        return None

    speaker = "Original user request" if is_original else "User"
    formatted = f"{speaker} ({name}): {content}"
    if attachments:
        formatted += f" [Attachments: {', '.join(attachments)}]"
    return formatted


def build(log, current_message):
    """Build context separately from the only message that needs an answer."""
    messages = log.get("messages", []) or []
    current_message_id = str(current_message.id)
    history = []
    history_is_original = []
    history_chars = 0
    original_request_found = False

    for message in messages:
        if not isinstance(message, dict):
            continue

        if str(message.get("message_id")) == current_message_id:
            continue

        if not _is_user_message(message):
            continue

        formatted = _format_user_message(message, not original_request_found)
        if formatted is None:
            continue

        is_original = not original_request_found
        if is_original:
            original_request_found = True
        history.append(formatted)
        history_is_original.append(is_original)
        history_chars += len(history[-1])

        if len(history) > MAX_MESSAGES:
            remove_index = next(
                (
                    index
                    for index, is_original in enumerate(history_is_original)
                    if not is_original
                ),
                0,
            )
            history_chars -= len(history.pop(remove_index))
            history_is_original.pop(remove_index)

    current_content = str(current_message.content or "")[:MAX_MESSAGE_CHARS]
    current_attachments = _attachment_summary(current_message.attachments)
    if current_attachments:
        current_content += f" [Attachments: {', '.join(current_attachments)}]"
    context_item = {
        "role": "developer",
        "content": (
            "CONVERSATION CONTEXT. The original user request is marked clearly. "
            "Treat every included user message as available information and use "
            "it with the later messages to resolve the user's issue. This includes "
            "usernames, user IDs, message IDs, and other details already provided. "
            "Never ask the user to provide a detail again when it appears here. "
            "Do not answer an old message instead of the current one:\n"
            + "\n".join(history)
        ),
    }
    current_item = {
        "role": "user",
        "content": (
            "CURRENT USER MESSAGE - answer only this message. Use the conversation "
            "context above and do not re-request details the user already provided:\n"
            f"User ({current_message.author.name}): "
            f"{current_content}"
        ),
    }

    while history and history_chars > MAX_CONTEXT_CHARS:
        remove_index = next(
            (
                index
                for index, is_original in enumerate(history_is_original)
                if not is_original
            ),
            0,
        )
        history_chars -= len(history.pop(remove_index))
        history_is_original.pop(remove_index)
        context_item["content"] = (
            "CONVERSATION CONTEXT. The original user request is marked clearly. "
            "Treat every included user message as available information and use "
            "it with the later messages to resolve the user's issue. This includes "
            "usernames, user IDs, message IDs, and other details already provided. "
            "Never ask the user to provide a detail again when it appears here. "
            "Do not answer an old message instead of the current one:\n"
            + "\n".join(history)
        )

    return [context_item, current_item] if history else [current_item]