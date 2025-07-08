"""IMAP filesystem."""

from __future__ import annotations

import io
from imaplib import IMAP4

from fsspec import AbstractFileSystem
from imap_tools import MailBox
from imap_tools.errors import MailboxFolderSelectError
from typing_extensions import override

FETCH_OPTIONS = {
    "charset",
    "limit",
    "mark_seen",
    "reverse",
    "headers_only",
    "bulk",
    "sort",
}


class IMAPFileSystem(AbstractFileSystem):
    """IMAP filesystem."""

    @override
    def __init__(self, *args, **storage_options) -> None:
        super().__init__(*args, **storage_options)

        host = storage_options.pop("host")
        username = storage_options.pop("username")
        password = storage_options.pop("password")

        self.mailbox = MailBox(host)
        self.mailbox.login(username, password)

    @override
    def ls(self, path: str, detail=True, **kwargs):
        fetch_kwargs = {k: v for k, v in kwargs.items() if k in FETCH_OPTIONS}

        try:
            details = self._ls(path, **fetch_kwargs)
        except (MailboxFolderSelectError, IMAP4.error) as e:
            raise FileNotFoundError(path) from e

        return list(details.values() if detail else details.keys())

    def _ls(self, path: str, **fetch_kwargs):
        path = path.strip("/")

        folders = self.mailbox.folder.list(path)

        details = {
            f.name: {"name": f.name, "size": 0, "type": "directory"} for f in folders
        }

        if not path:
            return details

        try:
            self.mailbox.folder.set(path)
        except MailboxFolderSelectError:
            if "/" not in path:
                raise

        if self.mailbox.folder.get() != path:
            try:
                msg = self._get_message(path, **fetch_kwargs)
                filename = None
            except MailboxFolderSelectError:
                parent, filename = self._split_path_last(path)

                if "/" not in parent:
                    raise

                msg = self._get_message(parent, **fetch_kwargs)

            for att in msg.attachments:
                if filename and filename != att.filename:
                    continue

                name = f"{path}/{att.filename}"
                details[name] = {
                    "name": name,
                    "size": att.size,
                    "type": "file",
                }

            if filename and not details:
                raise FileNotFoundError(path)

        else:
            for msg_id in self.mailbox.uids():
                name = f"{path}/{msg_id}"
                details[name] = {
                    "name": name,
                    "size": 0,
                    "type": "directory",
                }

        return details

    @override
    def _open(self, path, **kwargs):
        fetch_kwargs = {k: v for k, v in kwargs.items() if k in FETCH_OPTIONS}

        att = self._get_attachment(path, **fetch_kwargs)
        return io.BytesIO(att.payload)

    def _get_message(self, path: str, **fetch_kwargs):
        if "/" not in path:
            raise FileNotFoundError(path)

        parent, msg_id = self._split_path_last(path)
        self.mailbox.folder.set(parent)

        try:
            msg = next(
                self.mailbox.fetch(f"UID {msg_id}", mark_seen=False, **fetch_kwargs),
                None,
            )
        except IMAP4.error as e:
            raise FileNotFoundError(path) from e

        if msg:
            return msg

        raise FileNotFoundError(path)

    def _get_attachment(self, path: str, **fetch_kwargs):
        if "/" not in path:
            raise FileNotFoundError(path)

        parent, filename = self._split_path_last(path)
        msg = self._get_message(parent, **fetch_kwargs)
        att = next((att for att in msg.attachments if att.filename == filename), None)

        if att:
            return att

        raise FileNotFoundError(path)

    @staticmethod
    def _split_path_last(path: str) -> list[str]:
        return path.rsplit("/", 1)
