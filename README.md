# SF6 Tracker

A local Street Fighter 6 ranked tracker. It pulls your ranked battle log from Capcom's
Buckler's Boot Camp, keeps every match in a local database (Buckler itself only shows
about your last 100), and shows your stats in a browser dashboard.

- **Overview**: win rate, record, round win rate, net LP/MR, current streak, rank and
  progress for every character, rolling win-rate trend, recent form, best and worst matchups.
- **Rank**: LP over time with division lines, MR over time with Master tier lines, LP/MR
  gained and lost per match, per day or per session, and every promotion and demotion.
- **Matchups**: win rate against every opponent character, plus round win rate and net LP.
- **Sessions**: play sessions, win rate after wins vs after losing streaks (tilt check),
  win rate by match number in a session and by time of day, longest streaks.
- **Opponents**: win rate vs opponents above, level with and below your rank (LP divisions or
  MR gap), by opponent league, and repeat opponents ("rivals").
- **Rounds**: round win rate, comeback rate, deciding-round win rate, match scores,
  win rate by round, and how you win and lose rounds (KO, Super Art, Critical Art,
  Overdrive, chip, time over, perfect).
- **Matches**: full match log, and a form to log matches by hand.

Every chart has a **Table** button with the same numbers. Filters at the top (date range,
character) apply to every tab.

## Run it

Needs Python 3.10+ and nothing else (no packages to install).

```bash
cd ~/Projects/sf6-tracker
python3 -m sf6tracker
```

Then open <http://localhost:8765> in your browser (from Windows too, if this runs in WSL).
Your data lives in `data/` (`tracker.db` plus `config.json`, which holds your Buckler cookie).

Try it with generated data first, without touching your real data:

```bash
python3 -m sf6tracker --data data-demo demo
python3 -m sf6tracker --data data-demo serve --port 8766
```

## Getting your matches in

Open the **Sync** tab.

1. **User code.** Paste your Buckler profile URL or the number at its end
   (`streetfighter.com/6/buckler/profile/<user code>`).
2. **Cookie sync (one click, or automatic).** Log in to Buckler in your browser, press F12,
   open the Network tab, reload, click the first request and copy the whole `Cookie` request
   header (or just the `buckler_id` cookie). Paste it, save, press **Sync now**. You can turn
   on auto sync every 10 to 60 minutes while the tracker runs. Cookies expire after a few weeks.
3. **Browser collector (if Capcom blocks cookie sync).** Drag the **SF6 Tracker: collect**
   button to your bookmarks bar, open Buckler while logged in, and click it. It reads your
   ranked battle log inside your own browser tab and sends it to the tracker. If the browser
   blocks that, it downloads a JSON file you can import on the Sync tab. On Chrome you may be
   asked to allow the page to reach devices on your local network; allow it.
4. **By hand.** The Matches tab has a form for matches Buckler missed.

Sync at least once per play session: Buckler only keeps your most recent matches.
From the command line: `python3 -m sf6tracker sync` or `python3 -m sf6tracker import file.json`.

## How the numbers are worked out

- **Ranked only.** Only matches Buckler marks as Ranked Match are stored.
- **LP and MR are per character**, so every rating change is computed against your previous
  match on the same character.
- **Before or after?** Buckler's battle log lists LP/MR at match time but doesn't say whether
  that's before or after the match. The tracker works it out from your own history (does the
  rating move with the result of the earlier match or the later one?) and shows what it found
  under Sync → Settings, where you can override it. If values are pre-match, your most recent
  match's change appears once you've played the next one.
- **Gaps.** A jump bigger than a single match can produce (600 LP, 120 MR), for example after
  missing a sync or an MR season reset, is not counted as a gain or loss.
- **Sessions** split after 30 idle minutes (change it in Settings).
- **Rank tables**: divisions from Rookie 1 (0 LP) to Master (25,000 LP); Master tiers at
  1,600 (High), 1,700 (Grand) and 1,800 MR (Ultimate). Legend (top 500) isn't derivable from MR.
- **Round finish codes** follow the community mapping used by other Buckler tools:
  1 KO, 2 chip KO, 3 time over, 4 draw, 5 Overdrive, 6 Super Art, 7 Critical Art, 8 Perfect.

Buckler has no official API. If Capcom changes the site, sync may break until the parser
in `sf6tracker/buckler.py` is updated. Your stored history is never lost.

## Privacy

The server only listens on this computer and only answers requests addressed to localhost.
Your cookie is stored in `data/config.json` (readable only by you), is never sent to the
browser page, and is sent only to streetfighter.com.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
