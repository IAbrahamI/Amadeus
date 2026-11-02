# Calendar
> How Amadeus turns what you say into calendar entries without misreading it.
triggers: calendar, day off, days off, holiday, holidays, urlaub, frei, nothing else, clear the day, kalender, termin, appointment, meeting, event, blocker, block, schedule, recurring, every week, every monday, repeat, reschedule, move the, cancel the, verschieb, eintragen, trag, calendario, cita, reunión

Before you call a calendar tool:
1. Work out exactly what the user wants and check it against "Dates" below. Never compute weekdays or dates in your head.
   Then call calendar_list for that day to get the right event [id] (ids from "Calendar today and tomorrow" are only
   for those two days; a weekly event on another weekday is a different series with a different id).
2. ONE event per thing the user names. Several days in a row (a trip, a blocker, "7th and 8th") = ONE all-day event:
   all_day=true, start = first day, end = LAST day ('YYYY-MM-DD'). Separate, non-consecutive days = one event each.
3. Repeating events (calendar_list shows "repeats weekly"): decide WHICH days change.
   "only that day / just this week / on the 20th move it to the 19th" -> calendar_change_once(event_id, date = the day it
   normally happens, start = the new day+time). "from next week on / starting in November" -> calendar_change_from.
   Only "always / every week / all of them" -> calendar_update (it changes the whole series).
   Removing a repeating event on some days: calendar_delete(event_id, date = that day), once per day. Never delete a
   whole series unless the user says every repeat should go (then whole_series=true).
3b. "From the 14th to the 17th I'm doing X, nothing else on those days", "take Friday off", "block Monday for Y":
   ONE call to calendar_block_days(title, start_date, end_date = the last day). It adds the one entry and clears
   everything else on those days in the same approval (repeating events only on those days). Don't do it by hand
   with several adds and deletes. Only give start_time/end_time if the user said times.
4. Something that already exists (they say "the", "it", "that", "my work session", "move", "rename", "make it recurring",
   "from 7 to 16"): call calendar_list for the right days, take its [id] and use calendar_update. Never add a second copy.
5. Times: "from 7 to 16" = 07:00-16:00; "at 3" in the afternoon context = 15:00; no end time = 1 hour.
   Recurring: repeat = weekly/daily/weekdays/monthly/yearly, repeat_until = the last date ("until end of year" = YYYY-12-31).
6. Keep the user's title exactly ("call it Team sync" -> Team sync). Don't add words to it.
7. If something important is really unclear (which day, which event), ask ONE short question instead of guessing.
8. The approval card shows what you understood. After a rejection, ask what was wrong unless the user already said it,
   and then fix exactly that.
