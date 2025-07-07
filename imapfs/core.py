"""IMAP filesystem."""

from __future__ import annotations

from fsspec import AbstractFileSystem
from imap_tools import MailBox
from typing_extensions import override


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
        path = path.strip("/")

        folders = self.mailbox.folder.list(path)

        details = {
            f.name: {"name": f.name, "size": 0, "type": "directory"} for f in folders
        }

        if path:
            self.mailbox.folder.set(path)

            for msg_id in self.mailbox.uids():
                details[msg_id] = {"name": msg_id, "size": 0, "type": "directory"}

        return list(details.values() if detail else details.keys())
