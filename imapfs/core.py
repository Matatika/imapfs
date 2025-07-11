"""IMAP filesystem."""

from __future__ import annotations

import fnmatch
import io
import itertools
from imaplib import IMAP4
from pathlib import Path
from typing import TYPE_CHECKING

from fsspec import AbstractFileSystem
from imap_tools import AND, MailBox
from imap_tools.errors import MailboxFolderSelectError
from typing_extensions import override

if TYPE_CHECKING:
    from imap_tools.message import MailMessage

FETCH_OPTIONS = {
    "charset",
    "limit",
    "mark_seen",
    "reverse",
    "headers_only",
    "bulk",
    "sort",
    "since",
}


class IMAPFileSystem(AbstractFileSystem):
    """IMAP filesystem."""

    @override
    def __init__(self, *args, **storage_options) -> None:
        super().__init__(*args, **storage_options)

        host = storage_options.pop("host")
        username = storage_options.pop("username")
        access_token = storage_options.pop("access_token", None)
        password = storage_options.pop("password", None)

        if not any((access_token, password)):
            msg = "Either 'access_token' or 'password' should be specified"
            raise ValueError(msg)

        self.mailbox = MailBox(host)

        if access_token:
            self.mailbox.xoauth2(username, access_token)
        else:
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

            self.mailbox.folder.set(self.mailbox.folder.get())

        folder_path = Path(self.mailbox.folder.get())

        if not (folder_path.is_relative_to(path) or (folder_path / "*").match(path)):
            try:
                msgs = self._get_messages(path, **fetch_kwargs)
                filename = None
            except MailboxFolderSelectError:
                parent, filename = self._split_path_last(path)

                if "/" not in parent:
                    raise

                msgs = self._get_messages(parent, **fetch_kwargs)

            msg_attachments = ((msg, att) for msg in msgs for att in msg.attachments)

            for msg, att in msg_attachments:
                if filename and not fnmatch.fnmatch(att.filename, filename):
                    continue

                resolved_path = Path(self.mailbox.folder.get(), msg.uid, att.filename)

                if resolved_path.is_relative_to(path) or resolved_path.match(path):
                    name = str(resolved_path)
                    details[name] = {
                        "name": name,
                        "size": att.size,
                        "type": "file",
                        "last_modified": msg.date,
                    }

            if filename and not details:
                raise FileNotFoundError(path)

        else:
            uids = self.mailbox.uids(
                AND(date_gte=fetch_kwargs.pop("since", None), all=True)
            )

            if fetch_kwargs.pop("reverse", False):
                uids = reversed(uids)

            limit = fetch_kwargs.pop("limit", None)

            for i, msg_id in enumerate(uids, start=1):
                if limit and i > limit:
                    break

                resolved_path = Path(self.mailbox.folder.get(), msg_id)

                if resolved_path.is_relative_to(path) or resolved_path.match(path):
                    name = str(resolved_path)
                    details[name] = {"name": name, "size": 0, "type": "directory"}

        return details

    @override
    def _open(self, path, **kwargs):
        fetch_kwargs = {k: v for k, v in kwargs.items() if k in FETCH_OPTIONS}

        att = self._get_attachment(path, **fetch_kwargs)
        return io.BytesIO(att.payload)

    @override
    def created(self, path, **kwargs):
        fetch_kwargs = {k: v for k, v in kwargs.items() if k in FETCH_OPTIONS}

        try:
            msg = next(
                self._get_messages(
                    path,
                    headers_only=fetch_kwargs.pop("headers_only", False),
                    **fetch_kwargs,
                )
            )
        except MailboxFolderSelectError:
            parent, filename = self._split_path_last(path)
            msg = next(
                self._get_messages(
                    parent,
                    headers_only=False,  # headers only does not fetch attachments
                    **fetch_kwargs,
                )
            )
            self._get_attachment_from_message(msg, filename)

        return msg.date

    @override
    def modified(self, path, **kwargs):
        return self.created(path, **kwargs)

    def _get_messages(self, path: str, **fetch_kwargs):
        path = path.strip("/")

        if "/" not in path:
            raise FileNotFoundError(path)

        parent, msg_id = self._split_path_last(path)
        self.mailbox.folder.set(parent)

        all_ = msg_id == "*"

        try:
            criteria = AND(
                date_gte=fetch_kwargs.pop("since", None),
                all=True if all_ else None,
                uid=msg_id if not all_ else None,
            )
        except TypeError as e:
            raise FileNotFoundError(path) from e

        try:
            msgs = self.mailbox.fetch(
                criteria,
                mark_seen=fetch_kwargs.pop("mark_seen", False),
                **fetch_kwargs,
            )
            msg = next(msgs, None)
        except IMAP4.error as e:
            raise FileNotFoundError(path) from e

        if msg:
            # do not immediately exhaust messages iterator
            return itertools.chain([msg], msgs)

        raise FileNotFoundError(path)

    def _get_attachment(self, path: str, **fetch_kwargs):
        path = path.strip("/")

        if "/" not in path:
            raise FileNotFoundError(path)

        parent, filename = self._split_path_last(path)
        msg = next(self._get_messages(parent, **fetch_kwargs))

        return self._get_attachment_from_message(msg, filename)

    def _get_attachment_from_message(self, msg: MailMessage, filename: str):
        att = next((att for att in msg.attachments if att.filename == filename), None)

        if att:
            return att

        raise FileNotFoundError(filename)

    @staticmethod
    def _split_path_last(path: str) -> list[str]:
        return path.rsplit("/", 1)
