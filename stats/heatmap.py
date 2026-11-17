from datetime import date, timedelta

LEVELS = (
    (0, 0),
    (2, 1),
    (4, 2),
    (6, 3),
)

MONTH_NAMES = ('янв.', 'февр.', 'март', 'апр.', 'май', 'июнь',
               'июль', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.')

MONTH_NAMES_GENITIVE = (
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
)


def level_for(count: int) -> int:
    if count <= 0:
        return 0
    for threshold, level in LEVELS:
        if count <= threshold:
            return level
    return 4


def build_heatmap(counts: dict[date, int], weeks: int = 53, today=None) -> dict:
    today = today or date.today()
    last_monday = today - timedelta(days=today.weekday())
    first_monday = last_monday - timedelta(weeks=weeks - 1)

    columns = []
    for week_offset in range(weeks):
        monday = first_monday + timedelta(weeks=week_offset)
        days = []
        for day_offset in range(7):
            day = monday + timedelta(days=day_offset)
            count = counts.get(day, 0)
            days.append({
                'date': day,
                'date_label': (
                    f'{day.day} {MONTH_NAMES_GENITIVE[day.month - 1]} '
                    f'{day.year} г.'
                ),
                'count': count,
                'level': level_for(count),
                'in_future': day > today,
            })
        columns.append(days)

    month_labels = []
    previous_month = None
    for index, days in enumerate(columns):
        month = days[0]['date'].month
        if month != previous_month:
            starts_month = days[0]['date'].day <= 7
            if index > 0 or starts_month:
                month_labels.append({
                    'index': index,
                    'name': MONTH_NAMES[month - 1],
                })
        previous_month = month

    rows = []
    for day_offset in range(7):
        rows.append([week[day_offset] for week in columns])

    return {
        'columns': columns,
        'rows': rows,
        'column_indexes': list(range(weeks)),
        'month_labels': month_labels,
        'month_label_at': {m['index']: m['name'] for m in month_labels},
        'today': today,
    }
