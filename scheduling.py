from datetime import date, timedelta


def calculate_schedule(interval_days, ease_factor, repetitions, grade, today=None):
    interval_days = int(interval_days)
    ease_factor = float(ease_factor)
    repetitions = int(repetitions)
    today = today or date.today()

    if grade == "again":
        repetitions = 0
        interval_days = 1
    else:
        repetitions += 1
        if repetitions == 1:
            interval_days = 1
        elif repetitions == 2:
            interval_days = 6
        else:
            interval_days = max(1, int(round(interval_days * ease_factor)))

    delta = {
        "again": -0.2,
        "hard": -0.15,
        "good": 0.0,
        "easy": 0.15,
    }.get(grade, 0.0)
    ease_factor = max(1.3, ease_factor + delta)
    next_due = today + timedelta(days=interval_days)

    return {
        "interval_days": interval_days,
        "ease_factor": ease_factor,
        "repetitions": repetitions,
        "next_due": next_due,
    }
