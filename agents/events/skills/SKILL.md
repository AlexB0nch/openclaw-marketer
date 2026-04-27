# Events Agent — Skills

## scrape_conferences
Запускает сбор конференций со всех источников.
Вызов: POST /api/v1/events/scrape
Результат: список ConferenceEvent с полями name, url, start_date, cfp_deadline, topics.

## filter_relevant
Оценивает релевантность каждой конференции для каждого продукта через Claude Haiku.
Порог: 50/100. Обновляет статус в БД на "relevant".
Вызов: POST /api/v1/events/filter

## get_calendar
Возвращает предстоящие события.
Вызов: GET /api/v1/events/calendar?status=relevant&days_ahead=90

## send_digest
Формирует и отправляет ежемесячный дайджест администратору в Telegram.
Вызов: POST /api/v1/events/digest/send

## generate_abstract
Генерирует черновик заявки спикера для события и продукта.
Вызов: POST /api/v1/events/abstract/{event_id}?product=ai_assistant
Результат: текст заявки 200-400 слов на русском языке.

## Callback-обработчики Telegram

- `events_draft:{id}` — сгенерировать черновик заявки
- `events_skip:{id}` — пометить событие как пропущенное
- `events_apply:{id}` — ЗАГЛУШКА: зарегистрировать заявку (отправка вручную)
- `events_reject:{id}` — отклонить заявку
