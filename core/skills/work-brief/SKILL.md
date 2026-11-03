---
name: work-brief
description: "Turns a request for the work side (one Claude Code run) into a clear task that shares only what it needs."
metadata:
  triggers: "work agent, work agents, work team, claude code, send to work, continue project, delegate, hand off, let the team, arbeitsauftrag, an die agenten"
---
# Work brief

Before calling send_to_work:
1. Write the task as a short brief:
   - **Goal**: what should exist when they are done (one or two sentences).
   - **Details**: requirements, constraints, examples, the format of the result (file, text, code, length).
   - **Done when**: how the user will check it.
2. Share ONLY what the task needs. Replace people with their role ("the user", "the landlord", "a colleague").
   NEVER write names, addresses, phone numbers, emails, account numbers, health or money details into the brief, not even
   to say they should not be used: just leave them out. If the task truly cannot be done without one, ask the user first.
   Never paste whole emails or notes; summarize the needed part.
   Example: "remind me to follow up with my landlord Mr. Becker at Hauptstr. 5" → "remind the user weekly to follow up with
   their landlord about an unresolved heating issue".
3. If something important is missing (deadline, format, audience), ask the user one short question first.
4. Then call send_to_work with the brief and a short project name (its folder in the projects folder; an existing name continues there). The user sees exactly what leaves the PC and approves it.
