"""Scrape the CodEge task bank (codege.ru) into an import JSON for django_hw.

Usage:
    python scripts/scrape_codege.py --out codege_export --login
    python scripts/scrape_codege.py --out codege_export

The first run opens Chrome so you can log in manually; the session is stored in
``~/.codege_auth.json``. Task texts are decoded from the site's obfuscation,
correct answers are collected through the practice-exam generator (it does not
modify progress), and files/images are downloaded into ``<out>/files`` and
``<out>/images``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://codege.ru"
LOGIN_URL = f"{BASE_URL}/login"
TASK_BANK_URL = f"{BASE_URL}/api/task-bank"
GENERATE_URL = f"{BASE_URL}/api/practice-exam/generate"
DEFAULT_AUTH = Path.home() / ".codege_auth.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
REQUEST_TIMEOUT = 120

LOCAL = threading.local()


def log(message: str) -> None:
    print(message, flush=True)


def load_session(auth_path: Path) -> requests.Session:
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for cookie in state.get("cookies", []):
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return session


def session_is_valid(session: requests.Session) -> bool:
    try:
        response = session.get(
            TASK_BANK_URL,
            params={"examType": "EGE", "page": 1, "limit": 1},
            timeout=30,
        )
    except requests.RequestException:
        return False
    return response.status_code == 200 and "json" in response.headers.get(
        "content-type", "",
    ).lower()


def interactive_login(auth_path: Path) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    log("Открываю Chrome для входа в codege.ru...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        log("Войдите в аккаунт. Жду до 10 минут...")
        deadline_ms = 10 * 60 * 1000
        elapsed = 0
        authenticated = False
        while elapsed < deadline_ms:
            try:
                page.wait_for_url(
                    re.compile(r"^https?://codege\.ru/(?!login)"),
                    timeout=5_000,
                )
            except PlaywrightTimeoutError:
                elapsed += 5_000
                continue
            page.wait_for_timeout(2_000)
            if "/login" in page.url:
                continue
            page.goto(f"{BASE_URL}/task-bank", wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            if "/login" not in page.url:
                authenticated = True
                break
        if not authenticated:
            browser.close()
            raise SystemExit("Вход не выполнен за 10 минут.")
        context.storage_state(path=str(auth_path))
        browser.close()
    log(f"Сессия сохранена: {auth_path}")


def ensure_session(auth_path: Path, force_login: bool) -> requests.Session:
    if force_login or not auth_path.exists():
        interactive_login(auth_path)
    session = load_session(auth_path)
    if not session_is_valid(session):
        log("Сохранённая сессия недействительна, нужен вход.")
        interactive_login(auth_path)
        session = load_session(auth_path)
        if not session_is_valid(session):
            raise SystemExit("Не удалось авторизоваться на codege.ru.")
    return session


def decode_task_text(value: str) -> str:
    if not value or not value.startswith("\u00a7"):
        return value or ""
    raw = base64.b64decode(value[1:])
    return bytes(((byte - 42) & 255) for byte in raw).decode("utf-8", "replace")


def decode_encoded_keys(encoded: str) -> list:
    if not encoded:
        return []
    try:
        raw = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        log(f"  Не удалось декодировать ключи: {exc}")
        return []
    keys = []
    for item in raw:
        if isinstance(item, str):
            try:
                keys.append(json.loads(item))
            except ValueError:
                keys.append(item)
        else:
            keys.append(item)
    return keys


def fetch_task_list(session: requests.Session, raw_dir: Path, refresh: bool) -> dict:
    path = raw_dir / "tasks.json"
    if path.exists() and not refresh:
        log(f"Загружаю список задач из кэша: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    log("Загружаю список задач...")
    tasks: dict[str, dict] = {}
    page = 1
    total = None
    while True:
        response = session.get(
            TASK_BANK_URL,
            params={"examType": "EGE", "page": page, "limit": 50},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        total = payload.get("total", total)
        for task in payload.get("tasks", []):
            tasks[str(task["kompegeTaskId"])] = task
        log(f"  страница {page}: всего {len(tasks)} из {total}")
        if not payload.get("tasks") or len(tasks) >= (total or 0):
            break
        page += 1
        time.sleep(0.15)

    path.write_text(
        json.dumps(tasks, ensure_ascii=False), encoding="utf-8",
    )
    log(f"Список задач сохранён: {path} ({len(tasks)} задач)")
    return tasks


def split_tokens(text: str) -> list[str]:
    text = (text or "").replace("\\n", "\n")
    return [token for token in re.split(r"\s+", text) if token]


def answer_values(key_info, field_count: int) -> list[str]:
    if not isinstance(key_info, dict):
        return []
    raw = key_info.get("key")
    if raw is None:
        return []
    if field_count and field_count > 1:
        sub_keys = key_info.get("subKeys")
        if sub_keys:
            values = [str(raw).strip()]
            for item in sub_keys:
                values.extend(split_tokens(str(item)))
            return [value for value in values if value]
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return split_tokens(str(raw))
    text = str(raw).replace("\\n", " ").strip()
    return [text] if text else []


def normalize_number(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number >= 100:
        number %= 100
    return number


def collect_answers(
    session: requests.Session,
    tasks: dict[str, dict],
    raw_dir: Path,
    refresh: bool,
    numbers: set[int] | None = None,
) -> dict[str, dict]:
    path = raw_dir / "answers.json"
    collected: dict[str, dict] = {}
    if path.exists() and not refresh:
        log(f"Загружаю ответы из кэша: {path}")
        collected = json.loads(path.read_text(encoding="utf-8"))

    by_number: dict[int, list[str]] = {}
    for task_id, task in tasks.items():
        number = task.get("number")
        if number is None:
            continue
        number = int(number)
        if numbers and normalize_number(number) not in numbers:
            continue
        by_number.setdefault(number, []).append(task_id)

    for number in sorted(by_number):
        target = set(by_number[number])
        missing = target - set(collected)
        if not missing:
            continue
        log(f"Ответы: задание {number}, нужно {len(missing)} из {len(target)}")
        average_bytes = 4_000
        rounds = 0
        while missing and rounds < 8:
            repeats = max(
                10,
                math.ceil(len(target) / 5 * (math.log(max(len(target), 2)) + 1)),
            )
            max_by_size = max(5, int(MAX_RESPONSE_BYTES / (average_bytes * 5)))
            repeats = min(repeats, max_by_size, 800)
            payload = {
                "examType": "EGE",
                "selections": [
                    {"number": number, "count": 5, "difficulty": "all"}
                    for _ in range(repeats)
                ],
            }
            started = time.time()
            try:
                response = session.post(
                    GENERATE_URL, json=payload, timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                log(f"  ошибка генератора: {exc}")
                time.sleep(2)
                rounds += 1
                continue
            body = response.json()
            generated = body.get("tasks", [])
            keys = decode_encoded_keys(body.get("encodedKeys", ""))
            if generated:
                average_bytes = max(200, len(response.content) / len(generated))
            new = 0
            for task, key in zip(generated, keys):
                task_id = str(task.get("kompegeTaskId"))
                if task_id not in target or task_id in collected:
                    continue
                collected[task_id] = {
                    "key": key,
                    "field_count": task.get("fieldCount"),
                    "field_labels": task.get("fieldLabels"),
                    "field_group_size": task.get("fieldGroupSize"),
                    "field_is_table": task.get("fieldIsTable"),
                }
                new += 1
            missing = target - set(collected)
            rounds += 1
            log(
                f"  {repeats} выборок: +{new}, осталось {len(missing)}, "
                f"{len(response.content) / 1024 / 1024:.1f} МБ, "
                f"{time.time() - started:.1f}с",
            )
            time.sleep(0.3)
        if missing:
            log(f"  Не найдены ответы для {len(missing)} задач задания {number}")
        path.write_text(
            json.dumps(collected, ensure_ascii=False), encoding="utf-8",
        )
    return collected


def fetch_detail(session: requests.Session, task_id: str) -> dict:
    try:
        response = session.get(
            f"{BASE_URL}/api/task-bank/{task_id}", timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {}


def collect_subtask_text(task: dict) -> str:
    parts = []
    for sub in task.get("subTask") or []:
        text = sub.get("text") or ""
        if not text.strip():
            continue
        number = sub.get("number")
        header = f"Задание {number}." if number else ""
        parts.append(f"{header}\n{text}".strip())
    return "\n\n".join(parts)


def sniff_extension(name: str, url: str, content: bytes, content_type: str) -> str:
    url_path = "" if url.startswith("data:") else urlparse(url).path
    for candidate in (name, url_path):
        if not candidate:
            continue
        suffix = Path(candidate).suffix.lower()
        if suffix and suffix not in (".bin", ".php", ".asp", ".aspx"):
            return suffix
    if content_type:
        subtype = content_type.split("/")[-1].split(";")[0].strip().lower()
        if subtype in ("png", "jpeg", "jpg", "gif", "webp"):
            return "." + ("jpg" if subtype == "jpeg" else subtype)
        if subtype in ("plain", "text"):
            return ".txt"
    if content.startswith(b"PK\x03\x04"):
        if b"mimetype" in content[:4000]:
            if b"opendocument.text" in content[:4000]:
                return ".odt"
            if b"opendocument.spreadsheet" in content[:4000]:
                return ".ods"
        return ".zip"
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"GIF8"):
        return ".gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if "image" in content_type:
        return ".png"
    return ".txt"


def safe_name(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^\w.\- ()]+", "_", name, flags=re.UNICODE).strip()
    return (name or "file")[:120]


def build_thread_session(cookies) -> requests.Session:
    session = getattr(LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
            )
        LOCAL.session = session
    return session


def download_media(
    session: requests.Session,
    tasks: dict[str, dict],
    out_dir: Path,
    raw_dir: Path,
    refresh: bool,
    workers: int,
    numbers: set[int] | None = None,
) -> dict:
    media_path = raw_dir / "media.json"
    media: dict[str, dict] = {}
    if media_path.exists() and not refresh:
        log(f"Загружаю карту файлов из кэша: {media_path}")
        media = json.loads(media_path.read_text(encoding="utf-8"))

    jobs: dict[str, dict] = {}

    def add_job(url: str, name: str, kind: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        if url.startswith("data:"):
            jobs.setdefault(url, {"url": url, "name": "", "kind": kind})
            return
        if url.startswith("/"):
            absolute = BASE_URL + url
        else:
            absolute = urljoin(BASE_URL, url)
        if absolute in media or absolute in jobs:
            return
        jobs[absolute] = {
            "url": absolute,
            "name": safe_name(name) if name else "",
            "kind": kind,
        }

    for task in tasks.values():
        number = task.get("number")
        if numbers and (
            number is None or normalize_number(number) not in numbers
        ):
            continue
        for entry in task.get("files") or []:
            add_job(entry.get("url", ""), entry.get("name", ""), "file")
        for image in BeautifulSoup(
            decode_task_text(task.get("text", "")), "html.parser",
        ).find_all("img"):
            add_job(image.get("src") or image.get("data-src") or "", "", "image")
        for sub in task.get("subTask") or []:
            for image in BeautifulSoup(
                sub.get("text") or "", "html.parser",
            ).find_all("img"):
                add_job(
                    image.get("src") or image.get("data-src") or "", "", "image",
                )

    if not jobs:
        return media

    log(f"Скачиваю файлы и картинки: {len(jobs)}")
    (out_dir / "files").mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    cookies = [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        }
        for cookie in session.cookies
    ]
    lock = threading.Lock()
    counter = {"done": 0, "failed": 0}

    def fetch(job: dict) -> tuple[str, dict | None]:
        content_type = ""
        if job["url"].startswith("data:"):
            header, _, data = job["url"].partition(",")
            content_type = header[5:].split(";")[0]
            try:
                if ";base64" in header:
                    content = base64.b64decode(data)
                else:
                    content = requests.utils.unquote_to_bytes(data)
            except ValueError as exc:
                with lock:
                    counter["failed"] += 1
                return job["url"], {"error": str(exc)}
            response_url = job["url"]
        else:
            thread_session = build_thread_session(cookies)
            try:
                response = thread_session.get(job["url"], timeout=REQUEST_TIMEOUT)
                if response.status_code == 404 and job["url"].startswith(BASE_URL):
                    alternate = "https://kompege.ru" + job["url"][len(BASE_URL):]
                    response = thread_session.get(
                        alternate, timeout=REQUEST_TIMEOUT,
                    )
                response.raise_for_status()
            except requests.RequestException as exc:
                with lock:
                    counter["failed"] += 1
                return job["url"], {"error": str(exc)}
            content = response.content
            content_type = response.headers.get("content-type", "")
            response_url = response.url
        name = job["name"]
        extension = sniff_extension(
            name, response_url, content, content_type,
        )
        digest = hashlib.sha1(content).hexdigest()
        if job["kind"] == "image":
            filename = f"images/{digest[:16]}{extension}"
            original_name = ""
        else:
            base = Path(name).stem if name else digest[:12]
            filename = f"files/{digest[:12]}_{safe_name(base)}{extension}"
            original_name = name or (Path(urlparse(job["url"]).path).name)
            if original_name and Path(original_name).suffix.lower() in (
                ".bin", ".php", ".asp", ".aspx",
            ):
                original_name = str(Path(original_name).with_suffix(extension))
            elif original_name and not Path(original_name).suffix:
                original_name += extension
        (out_dir / filename).write_bytes(content)
        with lock:
            counter["done"] += 1
            if counter["done"] % 100 == 0:
                log(f"  скачано {counter['done']} из {len(jobs)}")
        return job["url"], {
            "file": filename,
            "name": original_name,
            "kind": job["kind"],
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for url, result in pool.map(fetch, jobs.values()):
            if result is not None:
                media[url] = result

    media_path.write_text(
        json.dumps(media, ensure_ascii=False), encoding="utf-8",
    )
    log(f"Готово: скачано {counter['done']}, ошибок {counter['failed']}")
    return media


BLOCK_TAGS = (
    "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "ul", "ol", "pre", "blockquote", "section",
)


def html_to_text(html: str, media: dict, image_keys: dict) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    for image in soup.find_all("img"):
        src = image.get("src") or image.get("data-src") or ""
        if src.startswith("data:"):
            absolute = src
        elif src.startswith("/"):
            absolute = BASE_URL + src
        else:
            absolute = urljoin(BASE_URL, src)
        entry = media.get(absolute)
        if entry and entry.get("file"):
            key = f"img_{hashlib.sha1(absolute.encode()).hexdigest()[:12]}"
            image_keys[key] = entry["file"]
            image.replace_with(f"[[img:{key}]]")
        else:
            image.decompose()

    for sup in soup.find_all("sup"):
        text = sup.get_text(" ", strip=True)
        sup.replace_with(f"^{text}")
    for sub in soup.find_all("sub"):
        text = sub.get_text(" ", strip=True)
        sub.replace_with(f"_{text}")

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.append(" | ")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.append("\n")
    for item in soup.find_all("li"):
        item.insert_before("• ")

    text = soup.get_text("")
    text = text.replace("\xa0", " ").replace("\r\n", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    lines = [line.rstrip(" |") for line in lines]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_export(
    tasks: dict[str, dict],
    answers: dict[str, dict],
    media: dict,
    out_dir: Path,
    numbers: set[int] | None,
    max_per_number: int | None,
    session: requests.Session | None = None,
) -> dict:
    grouped: dict[int, list[dict]] = {}
    for task in tasks.values():
        number = normalize_number(task.get("number"))
        if number is None:
            continue
        if numbers and number not in numbers:
            continue
        grouped.setdefault(number, []).append(task)

    topics = []
    entries = []
    image_keys: dict[str, str] = {}
    missing_answers = []

    for number in sorted(grouped):
        topic_name = f"Задание {number}"
        topics.append({"name": topic_name, "order": number})
        items = sorted(grouped[number], key=lambda item: item["kompegeTaskId"])
        if max_per_number:
            items = items[:max_per_number]
        for task in items:
            task_id = str(task["kompegeTaskId"])
            info = answers.get(task_id) or {}
            if not info and session is not None:
                detail = fetch_detail(session, task_id)
                info = {
                    "key": detail.get("key"),
                    "field_count": detail.get("fieldCount"),
                    "field_labels": detail.get("fieldLabels"),
                    "field_group_size": detail.get("fieldGroupSize"),
                    "field_is_table": detail.get("fieldIsTable"),
                }
            field_count = info.get("field_count") or 1
            values = answer_values(info.get("key"), field_count)
            if not values:
                missing_answers.append(int(task_id))

            body_parts = [decode_task_text(task.get("text", ""))]
            subtasks = collect_subtask_text(task)
            body_html = "\n\n".join(part for part in body_parts if part)
            if subtasks:
                body_html = f"{body_html}\n\n{subtasks}"
            body = html_to_text(body_html, media, image_keys)

            attachments = []
            files = task.get("files") or []
            for entry in files:
                url = entry.get("url", "")
                absolute = (
                    BASE_URL + url if url.startswith("/") else urljoin(BASE_URL, url)
                )
                media_entry = media.get(absolute) or {}
                if media_entry.get("file"):
                    attachments.append({
                        "file": media_entry["file"],
                        "original_name": (
                            media_entry.get("name")
                            or entry.get("name")
                            or Path(media_entry["file"]).name
                        ),
                    })

            task_images = []
            for key in dict.fromkeys(
                re.findall(r"\[\[img:(img_[0-9a-f]+)\]\]", body),
            ):
                if key in image_keys:
                    task_images.append({
                        "key": key, "file": image_keys[key],
                    })

            task_type = "gap" if field_count and field_count > 1 else "text"
            entry = {
                "external_id": int(task_id),
                "number": number,
                "topic": topic_name,
                "comment": task.get("comment") or "",
                "difficulty": task.get("difficulty"),
                "field_count": field_count,
                "field_labels": info.get("field_labels") or [],
                "field_group_size": info.get("field_group_size") or 0,
                "field_is_table": bool(info.get("field_is_table")),
                "type": task_type,
                "body": body,
                "url": (
                    f"{BASE_URL}/task-bank/{task_id}"
                    f"?examType=EGE&number={number}"
                ),
                "attachments": attachments,
                "images": task_images,
            }
            if task_type == "gap":
                gaps = values[:field_count]
                entry["gaps"] = gaps + [""] * (field_count - len(gaps))
            else:
                entry["correct_answer"] = values[0] if values else ""
            entry["missing_answer"] = not values
            entries.append(entry)

    missing_answers = [
        entry["external_id"] for entry in entries if entry["missing_answer"]
    ]
    export = {
        "source": "codege.ru",
        "exported_at": datetime.now().astimezone().isoformat(),
        "bank": {
            "name": "CodEge ЕГЭ",
            "description": "База задач ЕГЭ по информатике с codege.ru",
        },
        "topics": topics,
        "tasks": entries,
        "stats": {
            "total": len(entries),
            "missing_answers": missing_answers,
        },
    }
    (out_dir / "export.json").write_text(
        json.dumps(export, ensure_ascii=False), encoding="utf-8",
    )
    report = [
        "Источник: codege.ru",
        f"Всего задач: {len(entries)}",
        f"Без ответа: {len(missing_answers)}",
        f"Файлов/картинок в media: {len(media)}",
    ]
    if missing_answers:
        report.append("ID без ответа: " + ", ".join(map(str, missing_answers)))
    (out_dir / "report.txt").write_text("\n".join(report), encoding="utf-8")
    log("\n".join(report))
    return export


def parse_numbers(value: str | None) -> set[int] | None:
    if not value:
        return None
    numbers: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            numbers.update(range(int(start), int(end) + 1))
        else:
            numbers.add(int(part))
    return numbers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="codege_export", help="Папка для результата",
    )
    parser.add_argument(
        "--auth", default=str(DEFAULT_AUTH), help="Путь к файлу сессии",
    )
    parser.add_argument(
        "--login", action="store_true", help="Принудительно войти заново",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Игнорировать кэш",
    )
    parser.add_argument(
        "--numbers", help="Номера задач, например 1-27 или 5,6,7",
    )
    parser.add_argument(
        "--max-per-number", type=int, help="Ограничить число задач на номер",
    )
    parser.add_argument(
        "--skip-media", action="store_true", help="Не скачивать файлы",
    )
    parser.add_argument(
        "--workers", type=int, default=6, help="Потоков для скачивания",
    )
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    auth_path = Path(args.auth).expanduser()

    session = ensure_session(auth_path, args.login)
    tasks = fetch_task_list(session, raw_dir, args.refresh)
    if not tasks:
        raise SystemExit("Список задач пуст — проверьте вход на codege.ru.")

    numbers = parse_numbers(args.numbers)
    answers = collect_answers(
        session, tasks, raw_dir, args.refresh, numbers,
    )

    media: dict = {}
    if not args.skip_media:
        media = download_media(
            session, tasks, out_dir, raw_dir, args.refresh, args.workers,
            numbers,
        )

    build_export(
        tasks, answers, media, out_dir, numbers, args.max_per_number, session,
    )
    log(f"Экспорт готов: {out_dir / 'export.json'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
