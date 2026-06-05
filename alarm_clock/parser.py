"""
Time string parser.

Design decisions
----------------
1. We try multiple format strings in order rather than a single canonical format.
   Reason: users don't read docs before typing. Accepting "2:30 PM", "2:30PM",
   "14:30", and "09:00" all without friction is a product decision that costs
   nothing in correctness and meaningfully improves usability.

2. We do NOT use dateutil.parser.parse().
   Reason: dateutil silently accepts ambiguous strings ("monday", "yesterday",
   "next week") and returns a datetime that may have nothing to do with what the
   user meant. We want to fail loudly on anything that isn't recognisably a
   time-of-day. Explicit format strings give us that control.

3. The returned time always has second=0, microsecond=0.
   Reason: the alarm resolution is one minute. Preserving sub-minute precision
   from the input (e.g., "14:30:45") would create the expectation that the alarm
   fires at exactly :45, which the scheduler does not support.

4. Error messages name the exact input and give concrete examples.
   Reason: "invalid time" is useless. Telling the user what we accept helps
   them fix the problem without consulting documentation.
"""

from __future__ import annotations

from datetime import datetime, time

# Formats attempted in order. More specific (and more commonly used) first.
_FORMATS: list[str] = [
    "%I:%M %p",  # 2:30 PM  / 02:30 PM
    "%I:%M%p",  # 2:30PM   / 02:30PM
    "%H:%M:%S",  # 14:30:00 (seconds accepted but discarded)
    "%H:%M",  # 14:30
    "%I %p",  # 2 PM
    "%I%p",  # 2PM
]


def parse_time(value: str) -> time:
    """
    Parse a time string into a :class:`datetime.time` object.

    Accepted formats::

        14:30       24-hour, no seconds
        14:30:00    24-hour, with seconds (seconds are discarded)
        2:30 PM     12-hour with space before meridiem
        2:30PM      12-hour without space
        2 PM        Hour-only, 12-hour
        2PM         Hour-only, no space

    Args:
        value: A string representing a time of day.

    Returns:
        A :class:`datetime.time` with second and microsecond set to 0.

    Raises:
        ValueError: If ``value`` is empty, whitespace-only, or cannot be parsed
                    as a recognisable time-of-day.

    Examples::

        >>> parse_time("14:30")
        datetime.time(14, 30)
        >>> parse_time("2:30 PM")
        datetime.time(14, 30)
        >>> parse_time("9:00 AM")
        datetime.time(9, 0)
    """
    if not value or not value.strip():
        raise ValueError(
            "Time string must not be empty. "
            "Expected formats: '14:30', '2:30 PM', '9:00 AM'."
        )

    cleaned = value.strip()

    for fmt in _FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.time().replace(second=0, microsecond=0)
        except ValueError:
            continue

    raise ValueError(
        f"Cannot parse {value!r} as a time. "
        f"Accepted formats: HH:MM (24h), H:MM AM/PM (12h). "
        f"Examples: '14:30', '07:00', '2:30 PM', '9 AM'."
    )
