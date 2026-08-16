#!/usr/bin/env python3
"""
Lightweight iCalendar (.ics / webcal) fetcher & parser for Omarchy Calendar Plugin.
Fetches configured calendars from ~/.config/omarchy/calendars.json
and writes parsed events to ~/.local/state/omarchy/calendar-events.json
"""

import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor

CONFIG_PATH = os.path.expanduser("~/.config/omarchy/calendars.json")
STATE_DIR = os.path.expanduser("~/.local/state/omarchy")
OUTPUT_PATH = os.path.join(STATE_DIR, "calendar-events.json")
TRANSLATION_CACHE_PATH = os.path.join(STATE_DIR, "translation-cache.json")

USER_AGENT = "Mozilla/5.0 (compatible; OmarchyCalendar/1.0)"

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

_translation_cache = {}


def load_translation_cache():
    global _translation_cache
    if os.path.exists(TRANSLATION_CACHE_PATH):
        try:
            with open(TRANSLATION_CACHE_PATH, "r", encoding="utf-8") as f:
                _translation_cache = json.load(f)
        except Exception:
            _translation_cache = {}


def save_translation_cache():
    try:
        tmp_path = TRANSLATION_CACHE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_translation_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, TRANSLATION_CACHE_PATH)
    except Exception:
        pass


def has_korean(text):
    if not text:
        return False
    return any(
        (0xAC00 <= ord(c) <= 0xD7AF) or (0x1100 <= ord(c) <= 0x11FF) or (0x3130 <= ord(c) <= 0x318F)
        for c in text
    )


def translate_korean_to_english(text):
    if not text or not has_korean(text):
        return text

    if text in _translation_cache:
        return _translation_cache[text]

    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=ko&tl=en&dt=t&q=" + urllib.parse.quote(text)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = "".join([part[0] for part in data[0] if part[0]]).strip()
            if translated:
                _translation_cache[text] = translated
                return translated
    except Exception:
        pass

    return text



def ensure_config_exists():
    """Create a default sample config if it does not exist."""
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        sample = [
            {
                "name": "Google / Apple Calendar Example",
                "url": "",
                "color": "#4A90E2",
                "enabled": True,
            }
        ]
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)


def unfold_lines(raw_text):
    """Unfold lines in an iCalendar stream according to RFC 5545."""
    lines = []
    for line in raw_text.splitlines():
        if not line:
            continue
        if (line.startswith(" ") or line.startswith("\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def unescape_ical_text(val):
    if not val:
        return ""
    val = val.replace("\\n", "\n").replace("\\N", "\n")
    val = val.replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    return val.strip()


def parse_datetime_value(val_str, params=None):
    """
    Parse an iCal date or datetime string.
    Returns: (is_all_day: bool, dt: datetime)
    """
    val_str = val_str.strip()
    if params and "VALUE=DATE" in params:
        # e.g. 20260816
        try:
            d = datetime.strptime(val_str[:8], "%Y%m%d").date()
            return True, datetime(d.year, d.month, d.day, 0, 0, 0)
        except ValueError:
            pass

    if len(val_str) == 8 and val_str.isdigit():
        try:
            d = datetime.strptime(val_str, "%Y%m%d").date()
            return True, datetime(d.year, d.month, d.day, 0, 0, 0)
        except ValueError:
            pass

    # Try datetime formats: 20260816T143000Z or 20260816T143000
    cleaned = val_str.rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return False, datetime.strptime(cleaned[:15], fmt)
        except ValueError:
            pass

    return True, datetime.now()


def parse_rrule(rrule_str):
    """Parse a basic RRULE string into key-value pairs."""
    rule = {}
    for part in rrule_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.upper()] = v
    return rule


def expand_recurring_event(event, window_start, window_end):
    """
    Expands a recurring VEVENT within [window_start, window_end].
    """
    rrule = event.get("rrule")
    if not rrule:
        return [event]

    freq = rrule.get("FREQ", "").upper()
    interval = int(rrule.get("INTERVAL", 1))
    until_str = rrule.get("UNTIL")
    count_str = rrule.get("COUNT")
    byday = rrule.get("BYDAY", "")

    until_dt = None
    if until_str:
        _, until_dt = parse_datetime_value(until_str)
        if until_dt < window_start:
            return []

    max_count = int(count_str) if count_str and count_str.isdigit() else 500

    start_dt = event["start_dt"]
    end_dt = event["end_dt"]
    duration = end_dt - start_dt

    instances = []
    cur_dt = start_dt
    generated = 0

    target_weekdays = []
    if byday:
        for day_code in byday.split(","):
            code = day_code[-2:].upper()
            if code in WEEKDAYS:
                target_weekdays.append(WEEKDAYS.index(code))

    exdates = set(event.get("exdates", []))

    while generated < max_count and cur_dt <= window_end:
        if until_dt and cur_dt > until_dt:
            break

        if freq == "DAILY":
            match = True
        elif freq == "WEEKLY":
            if target_weekdays:
                match = cur_dt.weekday() in target_weekdays
            else:
                match = True
        elif freq == "MONTHLY":
            match = cur_dt.day == start_dt.day
        elif freq == "YEARLY":
            match = cur_dt.month == start_dt.month and cur_dt.day == start_dt.day
        else:
            match = True

        date_key = cur_dt.strftime("%Y-%m-%d")

        if match and cur_dt >= window_start and date_key not in exdates:
            inst = dict(event)
            inst["start_dt"] = cur_dt
            inst["end_dt"] = cur_dt + duration
            inst["date_key"] = date_key
            instances.append(inst)

        generated += 1

        # Advance cursor
        if freq == "DAILY":
            cur_dt += timedelta(days=interval)
        elif freq == "WEEKLY":
            if target_weekdays:
                cur_dt += timedelta(days=1)
            else:
                cur_dt += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            # Rough month addition
            month = cur_dt.month + interval
            year = cur_dt.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            day = min(cur_dt.day, 28)
            cur_dt = cur_dt.replace(year=year, month=month, day=day)
        elif freq == "YEARLY":
            cur_dt = cur_dt.replace(year=cur_dt.year + interval)
        else:
            break

        if cur_dt > window_end:
            break

    return instances


def parse_ics(content, cal_info, window_start, window_end):
    """
    Parses an ICS file string into structured events within the time window.
    """
    lines = unfold_lines(content)
    raw_events = []
    in_vevent = False
    current = {}

    for line in lines:
        if line == "BEGIN:VEVENT":
            in_vevent = True
            current = {"exdates": []}
            continue
        elif line == "END:VEVENT":
            if in_vevent and "DTSTART" in current:
                raw_events.append(current)
            in_vevent = False
            current = {}
            continue

        if not in_vevent:
            continue

        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key_part, val_part = parts[0], parts[1]

        # Key might have params like DTSTART;TZID=... or DTSTART;VALUE=DATE
        prop_parts = key_part.split(";")
        prop_name = prop_parts[0].upper()
        prop_params = prop_parts[1:] if len(prop_parts) > 1 else []

        if prop_name == "DTSTART":
            all_day, dt = parse_datetime_value(val_part, prop_params)
            current["DTSTART"] = dt
            current["all_day"] = all_day
        elif prop_name == "DTEND":
            _, dt = parse_datetime_value(val_part, prop_params)
            current["DTEND"] = dt
        elif prop_name == "SUMMARY":
            current["SUMMARY"] = unescape_ical_text(val_part)
        elif prop_name == "LOCATION":
            current["LOCATION"] = unescape_ical_text(val_part)
        elif prop_name == "DESCRIPTION":
            current["DESCRIPTION"] = unescape_ical_text(val_part)
        elif prop_name == "UID":
            current["UID"] = val_part.strip()
        elif prop_name == "RRULE":
            current["RRULE"] = parse_rrule(val_part)
        elif prop_name == "EXDATE":
            _, ex_dt = parse_datetime_value(val_part, prop_params)
            current["exdates"].append(ex_dt.strftime("%Y-%m-%d"))

    # Convert raw events to normalized event instances
    auto_translate = cal_info.get("translateKorean", True)
    normalized = []
    for raw in raw_events:
        start_dt = raw.get("DTSTART")
        if not start_dt:
            continue
        all_day = raw.get("all_day", False)
        end_dt = raw.get("DTEND", start_dt + (timedelta(days=1) if all_day else timedelta(hours=1)))
        if end_dt < start_dt:
            end_dt = start_dt

        title = raw.get("SUMMARY", "(Untitled Event)")
        location = raw.get("LOCATION", "")
        description = raw.get("DESCRIPTION", "")

        if auto_translate:
            title = translate_korean_to_english(title)
            location = translate_korean_to_english(location)

        evt = {
            "id": raw.get("UID", f"evt_{int(start_dt.timestamp())}"),
            "title": title,
            "location": location,
            "description": description,
            "calendar": cal_info.get("name", "Calendar"),
            "color": cal_info.get("color", "#4A90E2"),
            "all_day": all_day,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "date_key": start_dt.strftime("%Y-%m-%d"),
            "rrule": raw.get("RRULE"),
            "exdates": raw.get("exdates", []),
        }

        if evt["rrule"]:
            expanded = expand_recurring_event(evt, window_start, window_end)
            normalized.extend(expanded)
        else:
            if start_dt.strftime("%Y-%m-%d") not in evt["exdates"]:
                if window_start <= start_dt <= window_end or window_start <= end_dt <= window_end:
                    normalized.append(evt)

    return normalized



AUTH_FILE = os.path.join(STATE_DIR, "google-auth.json")


def get_google_access_token():
    """Retrieve or refresh Google OAuth2 access token."""
    if not os.path.exists(AUTH_FILE):
        return None
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            auth_data = json.load(f)

        now = time.time()
        if auth_data.get("access_token") and auth_data.get("expires_at", 0) > now + 60:
            return auth_data["access_token"]

        refresh_token = auth_data.get("refresh_token")
        client_id = auth_data.get("client_id")
        client_secret = auth_data.get("client_secret")

        if not refresh_token or not client_id or not client_secret:
            return None

        url = "https://oauth2.googleapis.com/token"
        payload = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            access_token = data.get("access_token")
            auth_data["access_token"] = access_token
            auth_data["expires_at"] = int(now) + data.get("expires_in", 3600)
            auth_data["updated_at"] = int(now)

            with open(AUTH_FILE, "w", encoding="utf-8") as f_out:
                json.dump(auth_data, f_out, indent=2)

            return access_token
    except Exception:
        return None


def fetch_google_api_calendar(cal_info, window_start, window_end):
    """Fetch events directly from Google Calendar API v3."""
    name = cal_info.get("name", "Google Calendar")
    cal_id = cal_info.get("googleCalendarId") or cal_info.get("calendarId")
    if not cal_id:
        return {"name": name, "color": cal_info.get("color", "#4A90E2"), "events": [], "status": "no_calendar_id", "count": 0}

    access_token = get_google_access_token()
    if not access_token:
        return {
            "name": name,
            "color": cal_info.get("color", "#4A90E2"),
            "events": [],
            "status": "auth_required: run google-auth.py",
            "count": 0,
        }

    encoded_cal_id = urllib.parse.quote(cal_id, safe="")
    time_min = window_start.strftime("%Y-%m-%dT00:00:00Z")
    time_max = window_end.strftime("%Y-%m-%dT23:59:59Z")

    params = urllib.parse.urlencode({
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "250",
    })

    url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_cal_id}/events?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "User-Agent": USER_AGENT,
    })

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])
        auto_translate = cal_info.get("translateKorean", True)
        events = []

        for item in items:
            start_info = item.get("start", {})
            end_info = item.get("end", {})

            if "date" in start_info:
                all_day = True
                d_str = start_info["date"]
                start_dt = datetime.strptime(d_str[:10], "%Y-%m-%d")
                end_dt = datetime.strptime(end_info.get("date", d_str)[:10], "%Y-%m-%d") if "date" in end_info else start_dt + timedelta(days=1)
            elif "dateTime" in start_info:
                all_day = False
                dt_str = start_info["dateTime"]
                cleaned = re.sub(r"[+-]\d\d:\d\d$", "", dt_str).rstrip("Z")
                start_dt = datetime.strptime(cleaned[:19], "%Y-%m-%dT%H:%M:%S")
                if "dateTime" in end_info:
                    end_cleaned = re.sub(r"[+-]\d\d:\d\d$", "", end_info["dateTime"]).rstrip("Z")
                    end_dt = datetime.strptime(end_cleaned[:19], "%Y-%m-%dT%H:%M:%S")
                else:
                    end_dt = start_dt + timedelta(hours=1)
            else:
                continue

            title = item.get("summary", "(Untitled Event)")
            location = item.get("location", "")
            description = item.get("description", "")

            if auto_translate:
                title = translate_korean_to_english(title)
                location = translate_korean_to_english(location)

            events.append({
                "id": item.get("id", f"evt_{int(start_dt.timestamp())}"),
                "title": title,
                "location": location,
                "description": description,
                "calendar": cal_info.get("name", "Google Calendar"),
                "color": cal_info.get("color", "#4A90E2"),
                "all_day": all_day,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "date_key": start_dt.strftime("%Y-%m-%d"),
                "rrule": None,
                "exdates": [],
            })

        return {
            "name": name,
            "color": cal_info.get("color", "#4A90E2"),
            "events": events,
            "status": "ok",
            "count": len(events),
        }
    except Exception as e:
        return {
            "name": name,
            "color": cal_info.get("color", "#4A90E2"),
            "events": [],
            "status": f"error: {str(e)}",
            "count": 0,
        }


def fetch_calendar_item(cal_info, window_start, window_end):
    if cal_info.get("googleCalendarId") or cal_info.get("calendarId"):
        return fetch_google_api_calendar(cal_info, window_start, window_end)
    else:
        return fetch_calendar(cal_info, window_start, window_end)


def fetch_calendar(cal_info, window_start, window_end):
    """Fetch single calendar from URL or local file."""
    name = cal_info.get("name", "Calendar")
    raw_url = cal_info.get("url", "").strip()

    if not raw_url:
        return {"name": name, "events": [], "status": "no_url"}

    # Convert webcal:// or webcals:// to https://
    if raw_url.startswith("webcal://"):
        url = "https://" + raw_url[9:]
    elif raw_url.startswith("webcals://"):
        url = "https://" + raw_url[10:]
    else:
        url = raw_url


    try:
        if url.startswith("file://") or url.startswith("/"):
            path = url[7:] if url.startswith("file://") else url
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        else:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=12) as resp:
                content = resp.read().decode("utf-8", errors="ignore")

        events = parse_ics(content, cal_info, window_start, window_end)
        return {
            "name": name,
            "color": cal_info.get("color", "#4A90E2"),
            "events": events,
            "status": "ok",
            "count": len(events),
        }
    except Exception as e:
        return {
            "name": name,
            "color": cal_info.get("color", "#4A90E2"),
            "events": [],
            "status": f"error: {str(e)}",
            "count": 0,
        }


def main():
    ensure_config_exists()
    os.makedirs(STATE_DIR, exist_ok=True)
    load_translation_cache()

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--save-config" and len(sys.argv) > 2:
            try:
                new_config = json.loads(sys.argv[2])
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(new_config, f, indent=2)
                print(json.dumps({"status": "success"}))
            except Exception as e:
                print(json.dumps({"status": "error", "message": str(e)}))
                sys.exit(1)
        elif arg == "--get-config":
            ensure_config_exists()
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                print(f.read())
            sys.exit(0)
        elif arg == "--auth-status":
            auth_ok = False
            if os.path.exists(AUTH_FILE):
                try:
                    with open(AUTH_FILE, "r", encoding="utf-8") as f:
                        auth_data = json.load(f)
                        if auth_data.get("refresh_token") and auth_data.get("client_id"):
                            auth_ok = True
                except Exception:
                    pass
            print(json.dumps({"authenticated": auth_ok}))
            sys.exit(0)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            calendars = json.load(f)
    except Exception as e:
        calendars = []

    # Time window: 45 days ago to 90 days in the future
    now = datetime.now()
    window_start = now - timedelta(days=45)
    window_end = now + timedelta(days=90)


    enabled_cals = [
        c for c in calendars
        if c.get("enabled", True) and (c.get("url") or c.get("googleCalendarId") or c.get("calendarId"))
    ]

    all_events = []
    cal_statuses = []

    if enabled_cals:
        with ThreadPoolExecutor(max_workers=min(8, len(enabled_cals))) as executor:
            futures = [
                executor.submit(fetch_calendar_item, c, window_start, window_end)
                for c in enabled_cals
            ]
            for f in futures:
                res = f.result()
                all_events.extend(res["events"])
                cal_statuses.append({
                    "name": res["name"],
                    "color": res["color"],
                    "status": res["status"],
                    "count": res["count"],
                })


    # Group events by date key ("YYYY-MM-DD")
    events_by_date = {}
    for evt in all_events:
        d_key = evt["date_key"]
        if d_key not in events_by_date:
            events_by_date[d_key] = []

        start_time_str = evt["start_dt"].strftime("%H:%M")
        end_time_str = evt["end_dt"].strftime("%H:%M")

        events_by_date[d_key].append({
            "id": evt["id"],
            "title": evt["title"],
            "calendar": evt["calendar"],
            "color": evt["color"],
            "allDay": evt["all_day"],
            "startTime": start_time_str if not evt["all_day"] else "All Day",
            "endTime": end_time_str if not evt["all_day"] else "",
            "location": evt["location"],
            "startIso": evt["start_dt"].isoformat(),
        })

    # Sort events in each day: All day events first, then chronological
    for d_key in events_by_date:
        events_by_date[d_key].sort(
            key=lambda x: (0 if x["allDay"] else 1, x["startTime"], x["title"])
        )

    auth_ok = False
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                auth_d = json.load(f)
                auth_ok = bool(auth_d.get("refresh_token") and auth_d.get("client_id"))
        except Exception:
            pass

    output_data = {
        "lastSynced": int(time.time()),
        "lastSyncedFormatted": now.strftime("%H:%M"),
        "totalEvents": len(all_events),
        "configuredCount": len(enabled_cals),
        "authenticated": auth_ok,
        "calendars": cal_statuses,
        "eventsByDate": events_by_date,
    }


    tmp_path = OUTPUT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    os.replace(tmp_path, OUTPUT_PATH)

    save_translation_cache()

    print(json.dumps({
        "status": "success",
        "totalEvents": len(all_events),
        "calendars": len(cal_statuses),
    }))



if __name__ == "__main__":
    main()
