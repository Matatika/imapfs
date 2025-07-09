"""IMAP filesystem tests."""

import csv
import io
import os
import uuid
import warnings
from datetime import datetime, timezone
from email.message import EmailMessage
from smtplib import SMTP

import pytest
from dotenv import load_dotenv
from imap_tools import MailBox
from imapfs.core import IMAPFileSystem

TEST_FOLDER_NAME = f"imapfs-{uuid.uuid4()}"
TEST_SUBFOLDER_NAME = f"{TEST_FOLDER_NAME}/subfolder"

TEST_FOLDER = {"name": TEST_FOLDER_NAME, "size": 0, "type": "directory"}
TEST_SUBFOLDER = {"name": TEST_SUBFOLDER_NAME, "size": 0, "type": "directory"}

INBOX_NAME = "INBOX"
INBOX_FOLDER = {"name": INBOX_NAME, "size": 0, "type": "directory"}


load_dotenv()


@pytest.fixture(scope="session")
def fs():
    fs = IMAPFileSystem(
        host=os.getenv("IMAP_HOST"),
        username=os.getenv("IMAP_USERNAME"),
        password=os.getenv("IMAP_PASSWORD"),
    )

    with fs.mailbox:
        yield fs


@pytest.fixture(scope="session")
def imap_mailbox(fs: IMAPFileSystem):
    return fs.mailbox


@pytest.fixture(scope="session")
def smtp_client():
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    with SMTP(host, 587) as client:
        client.starttls()
        client.login(username, password)
        yield client


@pytest.fixture(scope="session")
def test_message_search_criteria(smtp_client: SMTP):
    return "FROM {from_} TO {to} SINCE {since}".format(
        from_=smtp_client.user,
        to=os.getenv("IMAP_USERNAME"),
        since=datetime.now(tz=timezone.utc).date().strftime(r"%d-%b-%Y"),
    )


@pytest.fixture(scope="session", autouse=True)
def create_test_folders(imap_mailbox: MailBox):
    imap_mailbox.folder.create(TEST_FOLDER_NAME)
    imap_mailbox.folder.create(TEST_SUBFOLDER_NAME)


@pytest.fixture(scope="session", autouse=True)
def send_message(smtp_client: SMTP):
    msg = EmailMessage()
    msg["Subject"] = "imapfs test email"
    msg["From"] = smtp_client.user
    msg["To"] = os.getenv("IMAP_USERNAME")
    msg.set_content(TEST_FOLDER_NAME)

    rows = [
        {"id": 0, "name": "user0", "email": "user0@test.com"},
        {"id": 1, "name": "user1", "email": "user1@test.com"},
        {"id": 2, "name": "user2", "email": "user2@test.com"},
        {"id": 3, "name": "user3", "email": "user3@test.com"},
        {"id": 4, "name": "user4", "email": "user4@test.com"},
    ]

    for i in range(3):
        buf = io.StringIO()

        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

        data = io.BytesIO(buf.getvalue().encode("utf-8")).getvalue()

        msg.add_attachment(
            data,
            maintype="text",
            subtype="csv",
            filename=f"test_{i}.csv",
        )

    smtp_client.send_message(msg)

    return msg


@pytest.fixture(scope="session", autouse=True)
def delete_test_messages(imap_mailbox: MailBox, test_message_search_criteria):
    yield

    folders = imap_mailbox.folder.list()
    trash_flagged = [f.name for f in folders if r"\Trash" in f.flags]

    imap_mailbox.folder.set(INBOX_NAME)

    if (num_trash := len(trash_flagged)) == 1:
        trash = trash_flagged[0]

        msg_ids = imap_mailbox.uids(test_message_search_criteria)
        imap_mailbox.move(msg_ids, trash)

        imap_mailbox.folder.set(trash)
    else:
        warnings.warn(
            f"Found {num_trash} folders with the `Trash` flag, so will not move any "
            "test messages; attempting expunge regardless",
            stacklevel=1,
        )

    msg_ids = imap_mailbox.uids(test_message_search_criteria)

    imap_mailbox.delete(msg_ids)

    imap_mailbox.folder.delete(TEST_FOLDER_NAME)
    imap_mailbox.folder.delete(TEST_SUBFOLDER_NAME)


@pytest.fixture
def move_to_test_folder(imap_mailbox: MailBox, test_message_search_criteria):
    imap_mailbox.folder.set(INBOX_NAME)
    inbox_msg_id = imap_mailbox.uids(test_message_search_criteria)[0]
    imap_mailbox.move(inbox_msg_id, TEST_FOLDER_NAME)

    imap_mailbox.folder.set(TEST_FOLDER_NAME)
    folder_msg_id = imap_mailbox.uids(test_message_search_criteria)[0]

    yield folder_msg_id

    imap_mailbox.folder.set(TEST_FOLDER_NAME)
    imap_mailbox.move(folder_msg_id, INBOX_NAME)


@pytest.fixture
def move_to_test_subfolder(imap_mailbox: MailBox, test_message_search_criteria):
    imap_mailbox.folder.set(INBOX_NAME)
    inbox_msg_id = imap_mailbox.uids(test_message_search_criteria)[0]
    imap_mailbox.move(inbox_msg_id, TEST_SUBFOLDER_NAME)

    imap_mailbox.folder.set(TEST_SUBFOLDER_NAME)
    subfolder_msg_id = imap_mailbox.uids(test_message_search_criteria)[0]

    yield subfolder_msg_id

    imap_mailbox.folder.set(TEST_SUBFOLDER_NAME)
    imap_mailbox.move(subfolder_msg_id, INBOX_NAME)


@pytest.mark.parametrize("path", ["", "/"], ids=["empty string", "single slash"])
def test_ls_root(fs: IMAPFileSystem, path):
    objects = fs.ls(path)

    assert INBOX_FOLDER in objects
    assert TEST_FOLDER in objects


@pytest.mark.parametrize(
    "path",
    [
        TEST_FOLDER_NAME,
        f"/{TEST_FOLDER_NAME}",
        f"{TEST_FOLDER_NAME}/",
        f"/{TEST_FOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_folder(fs: IMAPFileSystem, move_to_test_folder, path):
    objects = fs.ls(path)

    assert objects == [
        TEST_FOLDER,
        TEST_SUBFOLDER,
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}",
            "size": 0,
            "type": "directory",
        },
    ]


def test_ls_folder_glob(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/*"
    objects = fs.ls(path)

    assert objects == [
        TEST_SUBFOLDER,
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}",
            "size": 0,
            "type": "directory",
        },
    ]


@pytest.mark.parametrize(
    "path",
    [
        TEST_FOLDER_NAME,
        f"/{TEST_FOLDER_NAME}",
        f"{TEST_FOLDER_NAME}/",
        f"/{TEST_FOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_folder_no_detail(fs: IMAPFileSystem, move_to_test_folder, path):
    objects = fs.ls(path, detail=False)

    assert objects == [
        TEST_FOLDER_NAME,
        TEST_SUBFOLDER_NAME,
        f"{TEST_FOLDER_NAME}/{move_to_test_folder}",
    ]


@pytest.mark.parametrize(
    "path",
    [
        TEST_SUBFOLDER_NAME,
        f"/{TEST_SUBFOLDER_NAME}",
        f"{TEST_SUBFOLDER_NAME}/",
        f"/{TEST_SUBFOLDER_NAME}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_subfolder(fs: IMAPFileSystem, move_to_test_subfolder, path):
    objects = fs.ls(path)

    assert objects == [
        TEST_SUBFOLDER,
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}",
            "size": 0,
            "type": "directory",
        },
    ]


def test_ls_subfolder_glob(fs: IMAPFileSystem, move_to_test_subfolder):
    path = f"{TEST_SUBFOLDER_NAME}/*"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}",
            "size": 0,
            "type": "directory",
        },
    ]


def test_ls_folder_message(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{path}/test_0.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{path}/test_1.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{path}/test_2.csv",
            "size": 135,
            "type": "file",
        },
    ]


def test_ls_folder_message_glob(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/*"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_1.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_2.csv",
            "size": 135,
            "type": "file",
        },
    ]


def test_ls_folder_message_no_detail(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}"
    objects = fs.ls(path, detail=False)

    assert objects == [f"{path}/test_0.csv", f"{path}/test_1.csv", f"{path}/test_2.csv"]


def test_ls_subfolder_message(fs: IMAPFileSystem, move_to_test_subfolder):
    path = f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{path}/test_0.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{path}/test_1.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{path}/test_2.csv",
            "size": 135,
            "type": "file",
        },
    ]

def test_ls_subfolder_message_glob(fs: IMAPFileSystem, move_to_test_subfolder):
    path = f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/*"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_0.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_1.csv",
            "size": 135,
            "type": "file",
        },
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_2.csv",
            "size": 135,
            "type": "file",
        },
    ]


@pytest.mark.parametrize(
    "path",
    [
        str(uuid.uuid4()),
        f"/{uuid.uuid4()}",
        f"{uuid.uuid4()}/",
        f"/{uuid.uuid4()}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_folder_not_found(fs: IMAPFileSystem, path):
    with pytest.raises(FileNotFoundError):
        fs.ls(path)


@pytest.mark.parametrize(
    "path",
    [
        f"{uuid.uuid4()}/{uuid.uuid4()}",
        f"/{uuid.uuid4()}/{uuid.uuid4()}",
        f"{uuid.uuid4()}/{uuid.uuid4()}/",
        f"/{uuid.uuid4()}/{uuid.uuid4()}/",
    ],
    ids=[
        "no leading/trailing slash",
        "leading slash",
        "trailing slash",
        "leading/trailing slash",
    ],
)
def test_ls_subfolder_not_found(fs: IMAPFileSystem, path):
    with pytest.raises(FileNotFoundError):
        fs.ls(path)


def test_ls_folder_message_not_found(fs: IMAPFileSystem):
    uint32_max = 2**32 - 1
    path = f"{TEST_FOLDER_NAME}/{uint32_max}"

    with pytest.raises(FileNotFoundError):
        fs.ls(path)


def test_ls_folder_message_malformed_id(fs: IMAPFileSystem):
    with pytest.raises(FileNotFoundError):
        fs.ls(f"{TEST_FOLDER_NAME}/{uuid.uuid4()}")


def test_ls_folder_message_attachment(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv"
    objects = fs.ls(path)

    assert objects == [{"name": f"{path}/test_0.csv", "size": 135, "type": "file"}]


def test_ls_folder_message_glob_attachment(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/*/test_0.csv"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv",
            "size": 135,
            "type": "file",
        }
    ]


def test_ls_subfolder_message_attachment(fs: IMAPFileSystem, move_to_test_subfolder):
    path = f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_0.csv"
    objects = fs.ls(path)

    assert objects == [{"name": f"{path}/test_0.csv", "size": 135, "type": "file"}]

def test_ls_subfolder_message_glob_attachment(
    fs: IMAPFileSystem,
    move_to_test_subfolder,
):
    path = f"{TEST_SUBFOLDER_NAME}/*/test_0.csv"
    objects = fs.ls(path)

    assert objects == [
        {
            "name": f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_0.csv",
            "size": 135,
            "type": "file",
        }
    ]


def test_ls_folder_message_attachment_not_found(
    fs: IMAPFileSystem,
    move_to_test_folder,
):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/{uuid.uuid4()}"

    with pytest.raises(FileNotFoundError):
        fs.ls(path)


def test_cat_folder_message_attachment(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv"
    content = fs.cat(path)

    assert content
    assert isinstance(content, bytes)

    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(content))))

    assert rows == [
        {"id": "0", "name": "user0", "email": "user0@test.com"},
        {"id": "1", "name": "user1", "email": "user1@test.com"},
        {"id": "2", "name": "user2", "email": "user2@test.com"},
        {"id": "3", "name": "user3", "email": "user3@test.com"},
        {"id": "4", "name": "user4", "email": "user4@test.com"},
    ]


def test_cat_subfolder_message_attachment(fs: IMAPFileSystem, move_to_test_subfolder):
    path = f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}/test_0.csv"
    content = fs.cat(path)

    assert content
    assert isinstance(content, bytes)

    rows = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(content))))

    assert rows == [
        {"id": "0", "name": "user0", "email": "user0@test.com"},
        {"id": "1", "name": "user1", "email": "user1@test.com"},
        {"id": "2", "name": "user2", "email": "user2@test.com"},
        {"id": "3", "name": "user3", "email": "user3@test.com"},
        {"id": "4", "name": "user4", "email": "user4@test.com"},
    ]


def test_cat_folder_message_attachment_not_found(
    fs: IMAPFileSystem,
    move_to_test_folder,
):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/{uuid.uuid4()}"

    with pytest.raises(FileNotFoundError):
        fs.cat(path)


def test_cat_subfolder_message_attachment_not_found(
    fs: IMAPFileSystem,
    move_to_test_subfolder,
):
    path = f"{TEST_SUBFOLDER_NAME}/{move_to_test_subfolder}"

    with pytest.raises(FileNotFoundError):
        fs.cat(path)


def test_read_text_folder_message_attachment(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv"
    text = fs.read_text(path)

    assert text
    assert isinstance(text, str)

    rows = list(csv.DictReader(io.StringIO(text)))

    assert rows == [
        {"id": "0", "name": "user0", "email": "user0@test.com"},
        {"id": "1", "name": "user1", "email": "user1@test.com"},
        {"id": "2", "name": "user2", "email": "user2@test.com"},
        {"id": "3", "name": "user3", "email": "user3@test.com"},
        {"id": "4", "name": "user4", "email": "user4@test.com"},
    ]


@pytest.mark.parametrize(
    "path",
    [
        TEST_FOLDER_NAME,
        TEST_SUBFOLDER_NAME,
    ],
    ids=[
        "folder",
        "subfolder",
    ],
)
def test_created_folder(fs: IMAPFileSystem, path):
    with pytest.raises(FileNotFoundError):
        fs.created(path)


def test_created_folder_message(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}"
    created = fs.created(path)

    assert created.date() == datetime.now(tz=timezone.utc).date()


def test_created_folder_message_attachment(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/test_0.csv"
    created = fs.created(path)

    assert created.date() == datetime.now(tz=timezone.utc).date()


def test_created_folder_message_not_found(fs: IMAPFileSystem):
    uint32_max = 2**32 - 1
    path = f"{TEST_FOLDER_NAME}/{uint32_max}"

    with pytest.raises(FileNotFoundError):
        fs.created(path)


def test_created_folder_message_attachment_message_not_found(fs: IMAPFileSystem):
    uint32_max = 2**32 - 1
    path = f"{TEST_FOLDER_NAME}/{uint32_max}/test_0.csv"

    with pytest.raises(FileNotFoundError):
        fs.created(path)


def test_created_folder_message_attachment_not_found(
    fs: IMAPFileSystem,
    move_to_test_folder,
):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}/{uuid.uuid4()}"

    with pytest.raises(FileNotFoundError):
        fs.created(path)


def test_modified_folder_message(fs: IMAPFileSystem, move_to_test_folder):
    path = f"{TEST_FOLDER_NAME}/{move_to_test_folder}"
    modified = fs.modified(path)

    assert modified.date() == datetime.now(tz=timezone.utc).date()

    created = fs.created(path)

    assert modified == created
