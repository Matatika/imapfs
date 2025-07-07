"""IMAP filesystem."""

from __future__ import annotations

from fsspec import AbstractFileSystem
from imapclient import IMAPClient
from typing_extensions import override


class IMAPFileSystem(AbstractFileSystem):
    """IMAP filesystem."""

    @override
    def __init__(self, *args, **storage_options) -> None:
        super().__init__(*args, **storage_options)

        host = storage_options.pop("host")
        username = storage_options.pop("username")
        password = storage_options.pop("password")

        self.client = IMAPClient(host)
        self.client.login(username, password)

    @override
    def ls(self, path: str, detail=True, **kwargs):
        path = path.strip("/")

        folders = self.client.list_folders(path)

        details = {
            name: {"name": name, "size": 0, "type": "directory"}
            for (*_, name) in folders
        }

        if path:
            self.client.select_folder(path)

            for msg_id in self.client.search():
                details[msg_id] = {"name": msg_id, "size": 0, "type": "directory"}

        return list(details.values() if detail else details.keys())

    @override
    def __enter__(self) -> None:
        return self

    @override
    def __exit__(self, *args) -> None:
        self.client.logout()
