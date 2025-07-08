"""IMAP filesystem."""

from __future__ import annotations

from imaplib import IMAP4

from fsspec import AbstractFileSystem
from imap_tools import MailBox
from imap_tools.errors import MailboxFolderSelectError
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
        try:
            details = self._ls(path)
        except (MailboxFolderSelectError, IMAP4.error) as e:
            raise FileNotFoundError(path) from e
        except StopIteration:
            raise FileNotFoundError(path) from None

        return list(details.values() if detail else details.keys())

    def _ls(self, path: str):
        path = path.strip("/")

        folders = self.mailbox.folder.list(path)

        details = {
            f.name: {"name": f.name, "size": 0, "type": "directory"} for f in folders
        }

        if not path:
            return details

        try:
            self.mailbox.folder.set(path)
            msg_id = None
        except MailboxFolderSelectError:
            if "/" not in path:
                raise

            folder, msg_id = path.rsplit("/", 1)

        if msg_id:
            self.mailbox.folder.set(folder)
            msg = next(self.mailbox.fetch(f"UID {msg_id}", mark_seen=False))

            for att in msg.attachments:
                details[att.filename] = {
                    "name": att.filename,
                    "size": att.size,
                    "type": "file",
                }

        else:
            for msg_id in self.mailbox.uids():
                details[msg_id] = {"name": msg_id, "size": 0, "type": "directory"}

        return details
