Primary source (canonical): https://dumps.wikimedia.org/wikidatawiki/entities/
This is the official home. You want latest-all.json.gz. The most recent one is from March 17-18, 2026, weighing in at about 142 GB gzipped Wikimedia. The catch: Wikimedia rate-limits downloaders and caps per-IP connections to 3 Wikimedia, so expect ~4-5 MB/s. That's roughly 8-10 hours for the full dump.
Faster alternatives:

Academic Torrents — a torrent for wikidata-20240101-all.json.gz is available on academictorrents.com Wikidata, though that's an older snapshot. Torrents are useful because mirrors can be added as web seeds to boost speed.
Wikimedia mirrors — the official mirrors don't have the per-IP cap Wikimedia. The freemirror.org mirror in Canada hosts recent dumps. Check dumps.wikimedia.freemirror.org for availability.

Practical recommendation for wikistash: Use wget -c against the canonical URL for the .json.gz — the -c flag gives you resume support, which you'll want for a 142GB file. The bz2 variant is smaller (~93GB) but much slower to decompress during streaming, which matters for the dump loader. Go with gzip.
For the CLI, something like:
wikistash load --download latest --languages en
that handles the fetch + filter + ingest in one shot would be the dream UX. The dump loader can stream-filter during decompression so you never need 142GB of local disk for the raw file — just the filtered DuckDB at the end.