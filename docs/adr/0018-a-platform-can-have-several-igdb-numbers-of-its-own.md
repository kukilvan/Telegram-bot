# A platform of the tracker can have several IGDB numbers of its own

Status: accepted

Stage 6.5 adds Meta Quest. IGDB has no single Quest platform: it writes a game for Meta Quest 3 (471, Quest 3S included), Meta Quest 2 (386) and the first Oculus Quest (384), and most upcoming games have a date only for Quest 2 (`.scratch/6-5-meta-quest/answers/recent_quest_games.json`). In the Meta store it is one app for every headset. IGDB also writes the PC version of a VR game as SteamVR (163), not as PC (6): Beat Saber, Red Matter 2 and Thief VR have no 6; 2,758 games have SteamVR without PC. Until now a platform of the tracker had one IGDB number of its own and at most one older platform (backward compatibility, «версия для PS4»).

The owner decided (2026-11-28, spec section 0 of stage 6.5): **a platform has one or more own IGDB numbers** (`PlatformInfo.igdb_ids`). Meta Quest has 471, 386 and 384; ПК has 6 and 163. Among the own numbers, the date that ends earliest is the platform's own date (equal ends — the narrower one; «не объявлена» loses), with no text about a version. The older platform is still compared with that own date as before.

Considered and rejected:
- **The older headsets as older platforms of Meta Quest**, with «(версия для Quest 2)» in the row: most cards of new games would carry the text, and it says nothing, since the store app is the same.
- **SteamVR out of ПК** (as the description assumed, believing IGDB writes VR games as PC): VR games with a PC version would have no ПК row, no PC release messages and no Steam prices. The owner chose SteamVR as ПК.
- **Rift (385), Windows Mixed Reality (161), Oculus VR (162), Go (387)** as own numbers: a dead PC store, a dead headset family, a record of the old Oculus store and a dead headset (spec 1.2).

## Consequences

- The table of `app/tracker/platforms.py` stays the one place (rule 6 of `docs/coding-standards.md`): the dates, the line of a suggestion (each label once), `has_platform`, the date outside the country and `older_tells` read `igdb_ids`.
- Cancelled means no own number has a `full` or `early` record: ПК with 6 cancelled and a SteamVR date is not cancelled.
- **Any IGDB number added to the table later** is unknown to the snapshots already stored: their `platforms` and `releases` hold only the numbers known then. So every snapshot stores `known` (the numbers of the table when it was taken; a snapshot without the key knew `6, 48, 49, 130, 167, 169, 508`), and the events of a poll compare the new snapshot restricted to the old one's `known` (`GameState.seen_as`). The first poll after a number is added only records its dates; from the second poll everything is compared.
