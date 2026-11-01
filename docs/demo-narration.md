# Demo narration (for a voice-over)

Plain-language script for `docs/images/demo-live.mp4` (42 s). Times are from the real recording.
Paste each block into ElevenLabs (suggested: calm, neutral voice, stability ~50%, speed 0.95-1.0), or use the SSML-free text as is.

## English

| Time | What you see | Say |
|---|---|---|
| 0:00 | `cat app.py`, failing test | "Here is a small shop program with a bug: the total is off by one. A test fails." |
| 0:06 | `aegis run …` | "Now we hand the fix to an AI agent, but through Aegis. The agent works on a copy of the project, with your passwords, keys and other folders hidden, and with the internet switched off." |
| 0:13 | agent output, report scrolls | "The agent fixes the bug. But a hidden instruction in the project tells it to steal your secret keys. This is called prompt injection. It reads the keys, and gets fake ones. It tries to send them to a stranger's server: blocked. It tries to plant a command in your shell startup file: blocked." |
| 0:19 | `TRIPWIRE` in the report | "Because the agent touched the fake keys, Aegis raises a tripwire: this agent was hijacked." |
| 0:21 | `aegis diff` | "Nothing has changed in your real project yet. You see exactly what the agent wants to change: one line." |
| 0:30 | `aegis apply`, then `y` | "Because the run looked suspicious, Aegis asks you twice before it applies anything. You review, you say yes." |
| 0:34 | test passes, `grep` prints 0 | "The bug is fixed, the test passes, and your shell file was never touched. The agent got the job done without getting your computer." |

One-line summary for the end: "Aegis Jail MCP: give AI agents a task, not your whole computer."

## Polski

| Czas | Na ekranie | Lektor |
|---|---|---|
| 0:00 | `cat app.py`, test nie przechodzi | "To mały program sklepu z błędem: suma jest za duża o jeden. Test się wywala." |
| 0:06 | `aegis run …` | "Naprawę zlecamy agentowi AI, ale przez Aegis. Agent pracuje na kopii projektu. Twoje hasła, klucze i inne foldery są ukryte, a internet wyłączony." |
| 0:13 | wyjście agenta, raport | "Agent naprawia błąd. Ale ukryta w projekcie instrukcja każe mu ukraść Twoje klucze. To się nazywa prompt injection. Agent czyta klucze i dostaje podróbki. Próbuje wysłać je na obcy serwer: zablokowane. Próbuje dopisać polecenie do pliku startowego powłoki: zablokowane." |
| 0:19 | `TRIPWIRE` | "Skoro agent dotknął fałszywych kluczy, Aegis podnosi alarm: ten agent został przejęty." |
| 0:21 | `aegis diff` | "W Twoim prawdziwym projekcie nic się jeszcze nie zmieniło. Widzisz dokładnie, co agent chce zmienić: jedna linijka." |
| 0:30 | `aegis apply`, potem `y` | "Ponieważ przebieg wyglądał podejrzanie, Aegis pyta, zanim cokolwiek zastosuje. Przeglądasz i zatwierdzasz." |
| 0:34 | test przechodzi, `grep` wypisuje 0 | "Błąd naprawiony, test przechodzi, a Twój plik powłoki nie został ruszony. Agent wykonał zadanie, nie dostając Twojego komputera." |

Zakończenie: "Aegis Jail MCP: daj agentom AI zadanie, a nie cały komputer."
