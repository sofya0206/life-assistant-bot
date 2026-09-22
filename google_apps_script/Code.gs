/**
 * Бесплатный шлюз между life-assistant-bot и Google Calendar.
 * Выполняется от имени владельца скрипта; биллинг Google Cloud не нужен.
 */

function doGet() {
  return json_({ok: true, service: 'life-assistant-calendar'});
}

function doPost(e) {
  try {
    const p = JSON.parse(e.postData.contents || '{}');
    const expected = PropertiesService.getScriptProperties().getProperty('API_SECRET');
    if (!expected || p.secret !== expected) throw new Error('Unauthorized');

    if (p.action === 'list') return json_({ok: true, events: listEvents_(p)});
    if (p.action === 'create') return json_({ok: true, event: createEvent_(p)});
    if (p.action === 'move') return json_({ok: true, event: moveEvent_(p)});
    if (p.action === 'delete') {
      deleteEvent_(p);
      return json_({ok: true});
    }
    throw new Error('Unknown action: ' + p.action);
  } catch (err) {
    return json_({ok: false, error: String(err && err.message || err)});
  }
}

function calendars_(ids) {
  if (!ids || !ids.length) return CalendarApp.getAllCalendars();
  return ids.map(function(id) {
    return id === 'primary' ? CalendarApp.getDefaultCalendar() : CalendarApp.getCalendarById(id);
  }).filter(Boolean);
}

function listEvents_(p) {
  const start = new Date(p.start);
  const end = new Date(p.end);
  let result = [];
  calendars_(p.calendar_ids).forEach(function(cal) {
    cal.getEvents(start, end).forEach(function(ev) {
      result.push(eventJson_(cal, ev));
    });
  });
  result.sort(function(a, b) { return a.start.localeCompare(b.start); });
  return result;
}

function createEvent_(p) {
  const cal = p.calendar_id === 'primary'
    ? CalendarApp.getDefaultCalendar()
    : CalendarApp.getCalendarById(p.calendar_id);
  if (!cal) throw new Error('Calendar not found: ' + p.calendar_id);
  const ev = cal.createEvent(p.title, new Date(p.start), new Date(p.end), {
    description: p.description || ''
  });
  return eventJson_(cal, ev);
}

function splitEventId_(value) {
  const parts = String(value).split('||');
  if (parts.length !== 2) throw new Error('Invalid event id');
  return {calendarId: decodeURIComponent(parts[0]), eventId: decodeURIComponent(parts[1])};
}

function findEvent_(value) {
  const ids = splitEventId_(value);
  const cal = ids.calendarId === 'primary'
    ? CalendarApp.getDefaultCalendar()
    : CalendarApp.getCalendarById(ids.calendarId);
  if (!cal) throw new Error('Calendar not found');
  const ev = cal.getEventById(ids.eventId);
  if (!ev) throw new Error('Event not found');
  return {cal: cal, ev: ev};
}

function moveEvent_(p) {
  const found = findEvent_(p.event_id);
  found.ev.setTime(new Date(p.start), new Date(p.end));
  return eventJson_(found.cal, found.ev);
}

function deleteEvent_(p) {
  findEvent_(p.event_id).ev.deleteEvent();
}

function eventJson_(cal, ev) {
  const allDay = ev.isAllDayEvent();
  return {
    id: encodeURIComponent(cal.getId()) + '||' + encodeURIComponent(ev.getId()),
    title: ev.getTitle() || '(без названия)',
    start: (allDay ? ev.getAllDayStartDate() : ev.getStartTime()).toISOString(),
    end: (allDay ? ev.getAllDayEndDate() : ev.getEndTime()).toISOString(),
    all_day: allDay,
    calendar_id: cal.getId(),
    calendar_name: cal.getName()
  };
}

function json_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
