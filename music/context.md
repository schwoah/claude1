# music selection — context

Living document. Append freely. Skill-worthy patterns get promoted once they stabilize.

## objective

Depth, not breadth. Identify hidden trends — unexpected commonalities between
seemingly orthogonal signals. Selection is ultimately an art; keep the human in
the loop and preserve room for discovery in the association process itself.

## operating principles

- **Downweight popular.** Canon-adjacent items co-occur with everything and collapse similarity lists toward the mean. Scarcity logic (as in `discarce.py`) applied to edges, not just releases.
- **Disagreement as signal.** When two orthogonal lenses converge on an obscure item, something is up. When graphs that *should* agree don't, that's also interesting. Don't collapse to one score.
- **Lens choice > ranking.** Traversal primitive is "from this seed, walk via <edge type>", not "give me similar tracks". The user picks the lens.
- **Vinyl existence is +ev on its own.** Someone decided it was worth pressing.
- **Domain-expert vendors > generalist vendors.** A store that lives in one pocket (funk, kwaito, northern soul) concentrates more curator signal than a broad catalog.

## seeds

> My collection and wantlist go here. Exports from Discogs (CSV) live in `music/seeds/` when added.

- [ ] export Discogs collection
- [ ] export Discogs wantlist
- [ ] starter list of "canonical personal favorites" (20–50 releases that define taste axes)

## trusted sources

Signal strength noted per source. Signal is relative to *how concentrated the curation is* — not absolute quality.

### tier 1 — high domain expertise, curated

- **lighthouserecords.jp** — very strong. Has a "house recommended" listing worth scraping separately.
- **earcave.com** — very strong. Specialty: funk, Baltimore house. Has house recommendations.
- **la casa tropical** — specialty: kwaito.
- **specific eBay sellers** — e.g. high-volume northern soul movers. (Names to add as identified.)
- **Discogs lists / users** — specific users and lists to be enumerated below.

### tier 2 — broad catalog, weaker per-item signal but useful coverage

- **juno.co.uk**
- **deejay.de**

### tier 3 — navigation / dig tools (not indicators by themselves)

- **bandcamp** — weak as a per-item signal, but important for navigating new + vinyl digs. `supported by` lists are the piece closest to tier-1 signal here.

### discogs-specific sub-sources

- Want/have ratio (already wired: `discarce.py`).
- Specific user wantlists / collections — TBD list below.
- Specific lists — TBD list below.

#### trusted discogs users
<!-- add: username — why trusted, genre pocket if any -->

#### trusted discogs lists
<!-- add: list URL — curator, theme -->

## lenses (edge types)

Status: `live` = already ingestable, `easy` = low effort next, `later` = bolt on when needed.

- `live` — **scarcity (want/have)** via `discarce.py`
- `live` — **list membership** via `discarce_list.py`
- `easy` — **credits graph** (producer, engineer, mixer, session players) from Discogs release JSON
- `easy` — **label / sub-label** co-membership, extractable from what's already scraped
- `easy` — **vendor house-recommended** lists (lighthouse, earcave, etc.) — curator-weighted within a vendor
- `easy` — **specific-user wantlist expansion** — collector-weighted co-want
- `later` — **DJ-set / radio tracklists** (NTS archive, dublab, 1001tracklists)
- `later` — **sample / cover / interpolation** (WhoSampled, SecondHandSongs)
- `later` — **bandcamp `supported by`** collector graph
- `later` — **audio embeddings** (CLAP / MULE / MFCC+tempo+key) — mostly as disagreement detector
- `later` — **lyrics** (Genius, MusicBrainz) — low priority, genre-dependent

## biases / heuristics I've noticed

<!-- append as they become conscious -->

## open questions

- How to weight vendor house-recs vs individual collector wantlists when they disagree?
- What's the right UI for "surface adjacencies without ranking"? CLI per-lens? TUI with lens toggle?
- How to capture ephemeral signals (a mix heard once, a recommendation in conversation) without losing them?
