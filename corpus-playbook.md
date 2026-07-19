# Corpus Playbook: Building the First 1,000-Album Foundation

**For: one person, one laptop, nights and weekends. No infrastructure.**

---

## 1. The unit of measure

Your unit is the **album**, technically the MusicBrainz **release group** (the abstract album, not a specific pressing). Every album row must carry a release-group MBID once verified. Artists get their own MBIDs. Tracks are deliberately excluded until a real need appears.

Why album is right: descriptors (mood, sonic traits, scene) are coherent at album level, it is the unit critics and fans reason in, and it keeps the corpus at 1,000 rows instead of 12,000.

---

## 2. The data architecture (what you actually create)

```
music-corpus/                  <- one git repo, this is the whole "database"
├── data/
│   ├── seed_albums.csv        <- the anchor list (provided). You edit this.
│   ├── descriptors.csv        <- your manual mood/sonic/scene annotations. You edit this.
│   └── vocab.csv              <- controlled vocabulary of allowed tags. You edit this.
├── build/
│   └── corpus.db              <- SQLite, generated. You never edit this by hand.
├── exports/
│   └── corpus.jsonl           <- generated export for LLM pipelines. Never hand-edited.
└── build_corpus.py            <- the script (provided). Run it after every CSV change.
```

**Roles of each format:**

| Format | Role | You edit it? |
|---|---|---|
| CSV | Source of truth, curation surface. Opens in Excel/Sheets/VS Code. | Yes, constantly |
| SQLite (`corpus.db`) | Query layer. What your future API reads. Rebuilt from CSVs anytime. | Never |
| JSONL | Export/interchange for LLM pipelines (one JSON object per line). | Never |

**Google Sheets:** acceptable as a friendlier editor for `descriptors.csv` (share it with your two friends for collaborative annotation). Workflow: edit in Sheets → File > Download > CSV → drop into `data/` → rerun script. If you work solo, editing the CSV in VS Code with Claude Code is fewer steps.

**Rules that keep the data clean:**
1. Nothing enters `corpus.db` without resolving to a MusicBrainz MBID (the script enforces this and writes failures to `unresolved.csv` for you to fix or discard).
2. Descriptors only come from `vocab.csv`. If a mood isn't in the vocabulary, add it to the vocabulary first, deliberately. Controlled vocabulary = agents can filter on stable enums later.
3. CSVs live in git. Every commit is a corpus version. That's your entire backup and versioning system, free.

---

## 3. Foundation vs. inference (your instinct, formalized)

Every album carries `corpus_status`:

- **core** — verified facts + your hand-written descriptors. Target: ~300 of the 1,000.
- **extended** — verified facts from MusicBrainz, no descriptors yet. Target: ~700.
- **stub** — known to exist, not yet ingested.

The future API reasons confidently over `core`, factually over `extended`, and *labels anything beyond as inferred*. You never need to map everything. The foundation's job is to make inference cheap and honest, not unnecessary.

---

## 4. Allocation: how the 1,000 breaks down

Quotas force the spread across decades, regions, and phases you asked for. Adjust freely, but if you don't set quotas the corpus will collapse into UK-1991-shoegaze because that's where the gravity is.

| # | Bucket | Era span | Quota | Expansion levers (labels / scenes / people) |
|---|---|---|---|---|
| A | UK post-punk, first wave | 1978–1984 | 110 | Factory, Rough Trade, 4AD (early), Fast Product; producer **Martin Hannett**; Manchester/Leeds/Liverpool scenes |
| B | Goth & darkwave, first wave | 1980–1990 | 80 | Beggars Banquet, Anagram/Cherry Red goth reissues; **Batcave club (London)** cohort |
| C | Dream pop / 4AD ethereal | 1983–1996 | 90 | 4AD roster; producers **Robin Guthrie, John Fryer**; This Mortal Coil orbit |
| D | Shoegaze, first wave | 1988–1995 | 100 | Creation, Too Pure, Dedicated; producers **Alan Moulder, Flood**; Thames Valley scene |
| E | US noise/dream/proto | 1985–1995 | 55 | Slumberland, Sub Pop fringe; Boston (Swirlies, Drop Nineteens) and LA (Medicine) pockets |
| F | Slowcore / sadcore | 1990–2005 | 85 | Kranky, Sub Pop, Up Records; Duluth / SF / Texas (Bedhead) pockets |
| G | Trip-hop / Bristol | 1991–2000 | 65 | Mo'Wax, Wild Bunch lineage; producer **Nellee Hooper**; Bristol soundsystem culture |
| H | Ambient pop / space rock bridges | 1987–2002 | 60 | Kranky, Rugby (Spacemen 3) lineage; Talk Talk post-rock hinge |
| I | Coldwave & European wave | 1980–1992 | 55 | French coldwave (Lively Art), Factory Benelux, German NDW-dark fringe |
| J | Latin American post-punk & darkwave | 1985–2026 | 60 | Mexico City rock en tu idioma dark fringe; modern Tijuana/Monterrey/São Paulo scenes; **your #1 research gap and #1 differentiation opportunity** |
| K | Japanese & Asian shoegaze/dream pop | 1996–2026 | 45 | Japanese shoegaze circuit, Korean bedroom-gaze (Parannoul wave); mostly Bandcamp-era, thin in MusicBrainz — manual work |
| L | 2000s revival (post-punk revival + nu-gaze) | 2001–2011 | 85 | Matador, Labrador (Sweden), Captured Tracks early |
| M | Modern wave | 2012–2026 | 120 | Sacred Bones, Dais, Captured Tracks, Felte; Minsk/Belarus wave; TikTok-era shoegaze revival — **this is where you beat every LLM's training cutoff** |
| N | Feeders & bridges (jangle, C86, dark synthpop) | 1983–2012 | 90 | Sarah Records, él, Mute (dark synth side); JAMC hinge between buckets A and D |
| | **Total** | | **1,000** | |

**Decade check (approximate resulting spread):** 1978–89: ~300 · 1990–99: ~330 · 2000–11: ~170 · 2012–26: ~200. That is a real historical spectrum, not a nostalgia dump.

---

## 5. How to get from 170 anchors to 1,000

1. **Verify anchors (day one).** Run `python build_corpus.py resolve`. Fix or discard anything in `unresolved.csv`. You now have ~165 verified core candidates.
2. **Label-roster expansion (weeks 1–3).** Run `python build_corpus.py expand --label "4AD"` (then Factory, Creation, Sacred Bones, Kranky, Projekt, Captured Tracks, Dais, Slumberland, Sarah Records...). The script pulls each label's albums from MusicBrainz into `candidates.csv`. You skim and mark `keep` / `skip` — this is fast, pleasurable work for you specifically, ~100 decisions an evening.
3. **Fill the hard buckets manually (weeks 2–5).** Buckets J and K won't fall out of label rosters. Method: Bandcamp tag pages (read, don't scrape), scene blogs, YouTube channel rabbit holes; add rows to `seed_albums.csv` by hand; the resolver verifies them. Expect some to be missing from MusicBrainz entirely — those stay `stub` with a note, which is honest.
4. **Descriptor pass on the core 300 (ongoing).** Pick the ~300 albums you know best across all buckets, annotate in `descriptors.csv` using only `vocab.csv` terms, 3–6 moods + 2–4 sonic traits + 1–2 scenes each. ~2 minutes per album you know well; ~10 hours total. Optionally run `python build_corpus.py lastfm-suggest` to print Last.fm's crowd tags per album as *suggestions you approve or reject* (sandbox use only; don't bake raw Last.fm data into anything commercial).
5. **Rebuild anytime.** `python build_corpus.py build` regenerates `corpus.db` and `corpus.jsonl` from the CSVs in seconds.

Effort estimate to a full 1,000 with 300 core: **30–40 hours spread over 4–6 weeks.** The bottleneck is your judgment, which is the point — that judgment is the product.

---

## 6. Starter controlled vocabulary (edit freely, keep it small)

- **Moods (pick ~30–40 max):** nocturnal, anxious, elegant, icy, warm, mournful, euphoric, menacing, hypnotic, tender, desolate, romantic, dissociative, defiant, hazy, claustrophobic, weightless, yearning, sinister, serene, feverish, resigned, wired, oceanic
- **Sonic traits (~25):** reverb-drenched, drum-machine-driven, wall-of-guitar, whispered-vocals, baritone-vocals, motorik, sparse, cavernous, tape-saturated, string-laden, bass-led, chorused-guitar, glacial-tempo, blown-out, crystalline, lo-fi, widescreen, dubby, jangling, droning
- **Scenes (~15):** manchester-postpunk, thames-valley-shoegaze, bristol-triphop, 4ad-ethereal, batcave-goth, french-coldwave, duluth-slowcore, sarah-indiepop, cdmx-dark, belarus-wave, korean-bedroom-gaze, tiktok-gaze-revival, factory-benelux, creation-orbit, kranky-ambient

Each term eventually gets a one-line definition. Agents need stable enums; listeners need poetry. You are writing for agents that will speak to listeners, so the terms should be both.
