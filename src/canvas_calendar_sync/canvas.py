from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .config import BASE_URL, CANVAS_KEYCHAIN_ACCOUNT, CANVAS_KEYCHAIN_SERVICE

ALLOWED_PLANNER_TYPES = {"assessment_request", "discussion_topic", "peer_review_sub_assignment", "planner_note", "quiz", "sub_assignment"}
MAX_PAGES = 1000
MAX_RETRIES = 3


class CanvasError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None, cause_type: str | None = None):
        super().__init__(message)
        self.code, self.status, self.cause_type = code, status, cause_type


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_url: str | None


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None


def rfc3339(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def retry_delay(attempt: int) -> float:
    return float(min(2 ** attempt, 8))


def keychain_token(
    runner: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    command_runner = runner or subprocess.run
    last_type = "SecurityCommandFailed"
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = command_runner(
                ["/usr/bin/security", "find-generic-password", "-a", CANVAS_KEYCHAIN_ACCOUNT, "-s", CANVAS_KEYCHAIN_SERVICE, "-w"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            token = result.stdout.strip()
            if not result.returncode and token:
                return token
        except (OSError, subprocess.SubprocessError, TimeoutError) as error:
            last_type = type(error).__name__
        if attempt < MAX_RETRIES:
            sleeper(retry_delay(attempt))
    raise CanvasError(
        "missing_token",
        "Canvas token is unavailable in macOS Keychain after bounded retries.",
        cause_type=last_type,
    )


def parse_next_link(value: str | None) -> str | None:
    for part in (value or "").split(","):
        if re.search(r";\s*rel\s*=\s*\"?next\"?", part, re.I):
            match = re.search(r"<([^>]+)>", part)
            return match.group(1) if match else None
    return None


class CanvasClient:
    def __init__(self, token: str, opener: Callable[..., Any] = urllib.request.urlopen, sleeper: Callable[[float], None] = time.sleep):
        if not token:
            raise ValueError("empty Canvas token")
        self.token, self.opener, self.sleeper = token, opener, sleeper

    @staticmethod
    def validate_url(url: str) -> None:
        parsed, origin = urllib.parse.urlparse(url), urllib.parse.urlparse(BASE_URL)
        if parsed.scheme != "https" or parsed.netloc != origin.netloc:
            raise CanvasError("unsafe_pagination_url", "Canvas returned a pagination URL outside its HTTPS origin.")

    def request_page(self, url: str) -> Page:
        self.validate_url(url)
        for attempt in range(MAX_RETRIES + 1):
            request = urllib.request.Request(url, headers={"Accept": "application/json+canvas-string-ids", "Authorization": f"Bearer {self.token}", "User-Agent": "CanvasCalendarSync/1.0"})
            try:
                with self.opener(request, timeout=30) as response:
                    raw, link = response.read(), response.headers.get("Link")
            except urllib.error.HTTPError as error:
                status = int(error.code)
                if (status == 429 or status in {408, 500, 502, 503, 504}) and attempt < MAX_RETRIES:
                    retry = error.headers.get("Retry-After") if error.headers else None
                    try: delay = float(retry) if retry else float(2 ** attempt)
                    except ValueError: delay = float(2 ** attempt)
                    self.sleeper(min(max(delay, 0), 30)); continue
                codes = {401: ("unauthorized", "Canvas rejected the Keychain token."), 403: ("forbidden", "Canvas denied a required endpoint."), 429: ("throttled", "Canvas throttling retries were exhausted.")}
                code, message = codes.get(status, ("canvas_http_error", f"Canvas returned HTTP {status}."))
                raise CanvasError(code, message, status, cause_type="HTTPError") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead, http.client.RemoteDisconnected, ssl.SSLError, OSError) as error:
                if attempt < MAX_RETRIES:
                    self.sleeper(retry_delay(attempt)); continue
                raise CanvasError(
                    "transport_error",
                    "Canvas HTTPS transport retries were exhausted.",
                    cause_type=type(error).__name__,
                ) from None
            try: payload = json.loads(raw.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CanvasError("malformed_response", "Canvas returned invalid JSON.") from None
            if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
                raise CanvasError("malformed_response", "Canvas returned an unexpected collection shape.")
            next_url = parse_next_link(link)
            if next_url: self.validate_url(next_url)
            return Page(payload, next_url)
        raise AssertionError("unreachable")

    def get_all(self, path: str, params: Iterable[tuple[str, str]] = ()) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(list(params), doseq=True)
        url = urllib.parse.urljoin(BASE_URL, path.lstrip("/")) + (f"?{query}" if query else "")
        seen, result = set(), []
        for _ in range(MAX_PAGES):
            if url in seen: raise CanvasError("pagination_loop", "Canvas pagination repeated a page URL.")
            seen.add(url); page = self.request_page(url); result.extend(page.items)
            if not page.next_url: return result
            url = page.next_url
        raise CanvasError("pagination_limit", "Canvas pagination exceeded the safety limit.")

    def probe(self) -> None:
        self.get_all("/api/v1/courses", (("enrollment_state", "active"), ("enrollment_type", "student"), ("per_page", "1")))


def clean(value: Any, fallback: str) -> str:
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else fallback


def submitted(value: Any) -> bool:
    if not isinstance(value, Mapping): return False
    workflow = str(value.get("workflow_state", "")).lower()
    return (bool(workflow) and workflow not in {"unsubmitted", "new"}) or any(bool(value.get(k)) for k in ("graded", "submitted", "needs_grading", "with_feedback"))


def make_item(source_key: str, course: Mapping[str, Any], item_type: str, item_id: str, title: str, due: dt.datetime, url: str, is_submitted: bool, updated: str | None) -> dict[str, Any]:
    course_id = str(course["id"]); course_name = clean(course.get("name"), f"Course {course_id}"); course_code = clean(course.get("course_code"), course_name)
    due_at, end_at = rfc3339(due), rfc3339(due + dt.timedelta(minutes=15))
    calendar_title = f"[Canvas] {course_code} — {title} due"
    description = f"Course: {course_name}\nCanvas: {url}\nSynced automatically from NUS Canvas."
    material = {"calendarTitle": calendar_title, "calendarDescription": description, "dueAt": due_at, "eventEndAt": end_at}
    return {"sourceKey": source_key, "courseId": course_id, "courseName": course_name, "courseCode": course_code, "itemType": item_type, "itemId": item_id, "title": title, "dueAt": due_at, "eventEndAt": end_at, "htmlUrl": url, "submitted": is_submitted, "sourceUpdatedAt": updated, "calendarTitle": calendar_title, "calendarDescription": description, "fingerprint": hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def normalize_assignment(item: Mapping[str, Any], course: Mapping[str, Any], now: dt.datetime) -> dict[str, Any] | None:
    if item.get("published") is False or str(item.get("workflow_state", "")).lower() in {"deleted", "unpublished"}: return None
    due, course_id, item_id = parse_time(item.get("due_at")), str(course.get("id", "")), str(item.get("id", ""))
    if not due or due <= now or not course_id or not item_id: return None
    types = {str(x) for x in item.get("submission_types", [])}
    kind = "quiz" if "online_quiz" in types else "discussion_topic" if "discussion_topic" in types else "external_tool" if "external_tool" in types else "assignment"
    url = urllib.parse.urljoin(BASE_URL, str(item.get("html_url") or ""))
    return make_item(f"canvas:{course_id}:assignment:{item_id}", course, kind, item_id, clean(item.get("name"), f"Assignment {item_id}"), due, url, submitted(item.get("submission")), item.get("updated_at") if isinstance(item.get("updated_at"), str) else None)


def normalize_planner(item: Mapping[str, Any], courses: Mapping[str, Mapping[str, Any]], assignment_ids: set[tuple[str, str]], now: dt.datetime) -> dict[str, Any] | None:
    kind, p = str(item.get("plannable_type", "")).lower(), item.get("plannable")
    if kind not in ALLOWED_PLANNER_TYPES or not isinstance(p, Mapping) or str(p.get("workflow_state", "")).lower() in {"deleted", "unpublished"}: return None
    course_id = str(item.get("course_id") or p.get("course_id") or "")
    nested = p.get("assignment") if isinstance(p.get("assignment"), Mapping) else {}
    assignment_id = str(p.get("assignment_id") or nested.get("id") or "")
    if course_id not in courses or (assignment_id and (course_id, assignment_id) in assignment_ids): return None
    due = next((t for t in (parse_time(p.get(k)) for k in ("due_at", "todo_date", "peer_review_due_at", "review_due_at")) if t), None) or parse_time(nested.get("due_at"))
    item_id = str(item.get("plannable_id") or p.get("id") or "")
    if not due or due <= now or not item_id: return None
    url = urllib.parse.urljoin(BASE_URL, str(item.get("html_url") or ""))
    return make_item(f"canvas:{course_id}:{kind}:{item_id}", courses[course_id], kind, item_id, clean(p.get("title") or p.get("name"), f"{kind} {item_id}"), due, url, submitted(item.get("submissions")), p.get("updated_at") if isinstance(p.get("updated_at"), str) else None)


def discover(client: CanvasClient, now: dt.datetime | None = None) -> dict[str, Any]:
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    raw = client.get_all("/api/v1/courses", (("enrollment_state", "active"), ("enrollment_type", "student"), ("include[]", "term"), ("per_page", "100")))
    courses = {str(x["id"]): x for x in raw if x.get("id") is not None}
    normalized, assignment_ids = {}, set()
    for course_id, course in courses.items():
        assignments = client.get_all(f"/api/v1/courses/{urllib.parse.quote(course_id, safe='')}/assignments", (("include[]", "submission"), ("override_assignment_dates", "true"), ("order_by", "due_at"), ("per_page", "100")))
        for assignment in assignments:
            aid = str(assignment.get("id", ""))
            if aid: assignment_ids.add((course_id, aid))
            if found := normalize_assignment(assignment, course, current): normalized[found["sourceKey"]] = found
    end = current + dt.timedelta(days=550)
    term_ends = [parse_time(x.get("term", {}).get("end_at")) for x in courses.values() if isinstance(x.get("term"), Mapping)]
    if valid := [x for x in term_ends if x]: end = max(end, max(valid) + dt.timedelta(days=31))
    planner = client.get_all("/api/v1/planner/items", (("start_date", rfc3339(current)), ("end_date", rfc3339(end)), ("per_page", "100")))
    for raw_item in planner:
        if found := normalize_planner(raw_item, courses, assignment_ids, current): normalized.setdefault(found["sourceKey"], found)
    items = sorted(normalized.values(), key=lambda x: (x["dueAt"], x["sourceKey"]))
    return {"schemaVersion": 1, "generatedAt": rfc3339(current), "canvasBaseUrl": BASE_URL, "courseCount": len(courses), "itemCount": len(items), "items": items}
