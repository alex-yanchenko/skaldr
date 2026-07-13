# Changelog

## [0.6.0](https://github.com/alex-yanchenko/skaldr/compare/v0.5.0...v0.6.0) (2026-07-13)


### Features

* **cli:** add --embed for publishing to a claude.ai Artifact ([#11](https://github.com/alex-yanchenko/skaldr/issues/11)) ([a0f271b](https://github.com/alex-yanchenko/skaldr/commit/a0f271b3b7b3dbc16ac832ee231107e4bfb4bd32))
* **print:** expand collapsibles and scale down for PDF ([#12](https://github.com/alex-yanchenko/skaldr/issues/12)) ([967d06b](https://github.com/alex-yanchenko/skaldr/commit/967d06b9d891d7f03951202cad9afe8577960ca1))


### Documentation

* **guide:** explain the code block's diff mode ([#14](https://github.com/alex-yanchenko/skaldr/issues/14)) ([667981d](https://github.com/alex-yanchenko/skaldr/commit/667981d0112e3a72c6ea840fdca53bd9eee56b36))
* **readme:** lead with install + usage; add Homebrew; catch up with 0.5.0 ([#10](https://github.com/alex-yanchenko/skaldr/issues/10)) ([d5ab808](https://github.com/alex-yanchenko/skaldr/commit/d5ab808ac9732f4a34ea8b4c3d13181ff563a21e))

## [0.5.0](https://github.com/alex-yanchenko/skaldr/compare/v0.4.1...v0.5.0) (2026-07-13)


### Features

* **badges:** attach badges to cards, timeline entries, and flow nodes ([#5](https://github.com/alex-yanchenko/skaldr/issues/5)) ([0e4417a](https://github.com/alex-yanchenko/skaldr/commit/0e4417ac250b87adaef659c55fe53e5c4da54bec))
* **emphasis:** row tone and grid-cell emphasis panels ([#6](https://github.com/alex-yanchenko/skaldr/issues/6)) ([227876b](https://github.com/alex-yanchenko/skaldr/commit/227876b6d2a0b212e825ea204f0ead79e57ce841))
* **flow:** add directional flow block and advertise the block palette ([#3](https://github.com/alex-yanchenko/skaldr/issues/3)) ([6e19167](https://github.com/alex-yanchenko/skaldr/commit/6e1916780802d87504a46080be95e1f0a408bc3d))
* **meta:** add an opt-in hero header (meta.hero) ([#8](https://github.com/alex-yanchenko/skaldr/issues/8)) ([73b0197](https://github.com/alex-yanchenko/skaldr/commit/73b01973a958a03335017b8a17c66f7cae086d9d))
* **table:** add an indicator column kind (colour-only status dot) ([#7](https://github.com/alex-yanchenko/skaldr/issues/7)) ([e619d56](https://github.com/alex-yanchenko/skaldr/commit/e619d5671275d7424538617df9c42b23b872b340))


### Bug Fixes

* **ci:** don't enforce uv.lock on release-please PRs ([#9](https://github.com/alex-yanchenko/skaldr/issues/9)) ([121e07b](https://github.com/alex-yanchenko/skaldr/commit/121e07bcd50f088b03ec5e0da633ac0ec63240c6))

## [0.4.1](https://github.com/alex-yanchenko/skaldr/compare/v0.4.0...v0.4.1) (2026-07-11)


### Bug Fixes

* **readme:** link both rendered samples (sales + warehouse) ([#1](https://github.com/alex-yanchenko/skaldr/issues/1)) ([150011f](https://github.com/alex-yanchenko/skaldr/commit/150011f7460d5dc2591ae95c4a533458a105e900))

## [0.4.0](https://github.com/alex-yanchenko/skaldr/compare/v0.3.3...v0.4.0) (2026-07-10)


### Features

* single authoring guide as an installable Claude skill; prune design docs ([#29](https://github.com/alex-yanchenko/skaldr/issues/29)) ([f50b5a2](https://github.com/alex-yanchenko/skaldr/commit/f50b5a256375d8fae6fd3faf79cbd7189c94061b))

## [0.3.3](https://github.com/alex-yanchenko/skaldr/compare/v0.3.2...v0.3.3) (2026-07-10)


### Bug Fixes

* --refresh the PyPI readiness poll (release-time brew push) ([#32](https://github.com/alex-yanchenko/skaldr/issues/32)) ([9ac7e5a](https://github.com/alex-yanchenko/skaldr/commit/9ac7e5a1ef38fdff5d2fd972972366b64eebef17))

## [0.3.2](https://github.com/alex-yanchenko/skaldr/compare/v0.3.1...v0.3.2) (2026-07-10)


### Bug Fixes

* wait for PyPI before regenerating the brew formula (+ manual re-sync) ([#30](https://github.com/alex-yanchenko/skaldr/issues/30)) ([a00f2ce](https://github.com/alex-yanchenko/skaldr/commit/a00f2ce7116a5799aca74961a4bafcdda013dc26))

## [0.3.1](https://github.com/alex-yanchenko/skaldr/compare/v0.3.0...v0.3.1) (2026-07-10)


### Documentation

* drop stale draft references in release.yml comments ([#27](https://github.com/alex-yanchenko/skaldr/issues/27)) ([22e0bff](https://github.com/alex-yanchenko/skaldr/commit/22e0bfffdc464f8f8fce33be2e6e37c117522c19))

## [0.3.0](https://github.com/alex-yanchenko/skaldr/compare/v0.2.0...v0.3.0) (2026-07-10)


### Features

* --enums and --styles overrides keeping the controlled-vocabulary guarantee ([#5](https://github.com/alex-yanchenko/skaldr/issues/5)) ([74b85d0](https://github.com/alex-yanchenko/skaldr/commit/74b85d0c62adadc4f9f806db68f489b952f9d42e))
* auto % of total per count; DRAFTED legend allows business-only proposals ([7ca2e8d](https://github.com/alex-yanchenko/skaldr/commit/7ca2e8d1ffad8ceb5162b3dbf677f96577b84bdf))
* blocks content model + renderer for the full v1 component set ([#12](https://github.com/alex-yanchenko/skaldr/issues/12)) ([a6514e9](https://github.com/alex-yanchenko/skaldr/commit/a6514e91777c9a564c854182e69addd858672311))
* bounded 6-column grid block with depth-2 nesting [M6b] ([#17](https://github.com/alex-yanchenko/skaldr/issues/17)) ([1cee5de](https://github.com/alex-yanchenko/skaldr/commit/1cee5de2020a78c8845202f2a24d1b2121f38dae))
* **controls:** hidable corner menu with theme + width switchers ([#23](https://github.com/alex-yanchenko/skaldr/issues/23)) ([16610e1](https://github.com/alex-yanchenko/skaldr/commit/16610e1207576c16162d3ebf284f74341cf20c8b))
* data-driven generator for issues & fixes review pages ([92552f5](https://github.com/alex-yanchenko/skaldr/commit/92552f53718e64b8d63cee7bd25afebd015fcc78))
* **design:** dark mode via theme-aware light-dark() palette ([#22](https://github.com/alex-yanchenko/skaldr/issues/22)) ([8b0b9a0](https://github.com/alex-yanchenko/skaldr/commit/8b0b9a02ccb14a3f2d7fb8f964e2babd3cd796f4))
* **design:** soft-shadow panel family + contained-card table ([#21](https://github.com/alex-yanchenko/skaldr/issues/21)) ([cd7cc8a](https://github.com/alex-yanchenko/skaldr/commit/cd7cc8a2c59da5b57aa232e3840d649798b03b59))
* legend group explaining the two fix-detail labels ([f90003d](https://github.com/alex-yanchenko/skaldr/commit/f90003d7ca97f0b3a6a682ee690a54240f305700))
* **meta:** page width modes — default/wide/full [M6a] ([#16](https://github.com/alex-yanchenko/skaldr/issues/16)) ([f972f9c](https://github.com/alex-yanchenko/skaldr/commit/f972f9ce47869c95bcdef5ac97c53c2e50951389))
* **security:** lock down every page with a Content-Security-Policy meta ([#24](https://github.com/alex-yanchenko/skaldr/issues/24)) ([d0bdc16](https://github.com/alex-yanchenko/skaldr/commit/d0bdc16c7ef7cc437729e0f4771d8fbd410a24bd))
* split legend into titled issue-type and fix-status groups ([570f274](https://github.com/alex-yanchenko/skaldr/commit/570f2748e3abeff78e70621e6a3acfaddd632cfa))
* **table:** proportional column width weights [M6c] ([#18](https://github.com/alex-yanchenko/skaldr/issues/18)) ([5ca06a5](https://github.com/alex-yanchenko/skaldr/commit/5ca06a565e6c5084f111a9f1b273f50483c2ba13))
* TO_WORK note replaces the 'not drafted' placeholder when present ([11ec975](https://github.com/alex-yanchenko/skaldr/commit/11ec9757a2175502223fc1e44788ffe5c62252bb))


### Bug Fixes

* darken fix-column text for readability ([1f74705](https://github.com/alex-yanchenko/skaldr/commit/1f747057ee22580aec92cd6de50b2ab7803c9227))
* **release:** refresh uv.lock on the release pr so --locked ci passes ([#7](https://github.com/alex-yanchenko/skaldr/issues/7)) ([4409117](https://github.com/alex-yanchenko/skaldr/commit/440911709dbca4f0f605df911741eabedf07f6c2))
* valid image data-URI, meter alignment in narrow cells, per-page skaldr credit ([#20](https://github.com/alex-yanchenko/skaldr/issues/20)) ([3800275](https://github.com/alex-yanchenko/skaldr/commit/3800275b1fbda8edda3a3c4616022b70ec67e391))


### Documentation

* authoring guide [M5] ([#14](https://github.com/alex-yanchenko/skaldr/issues/14)) ([8b3cef9](https://github.com/alex-yanchenko/skaldr/commit/8b3cef93542cf9d8f2ef5026b9e58d5f09697db1))
* **design:** bounded grid layout + page width modes [M6] ([#15](https://github.com/alex-yanchenko/skaldr/issues/15)) ([81d8f6f](https://github.com/alex-yanchenko/skaldr/commit/81d8f6f187123f1f12cb9753ef9e95713f8f6596))
* **schema:** describe every content-file field + enforcing test [M5] ([#13](https://github.com/alex-yanchenko/skaldr/issues/13)) ([d45bec3](https://github.com/alex-yanchenko/skaldr/commit/d45bec38e1de697befccfb3954da418e107de930))
* skaldr v1 component & visual spec + rendered reference ([#11](https://github.com/alex-yanchenko/skaldr/issues/11)) ([d4d416c](https://github.com/alex-yanchenko/skaldr/commit/d4d416cbd4d8358451fcb9ecae5a3414ee769397))
* skaldr v1 design and handover document ([#8](https://github.com/alex-yanchenko/skaldr/issues/8)) ([81bffc9](https://github.com/alex-yanchenko/skaldr/commit/81bffc98b4e34fa9d9ce91bbe12039dd37c4e9a8))

## [0.2.0](https://github.com/alex-yanchenko/skaldr/compare/v0.1.0...v0.2.0) (2026-07-10)


### Features

* --enums and --styles overrides keeping the controlled-vocabulary guarantee ([#5](https://github.com/alex-yanchenko/skaldr/issues/5)) ([74b85d0](https://github.com/alex-yanchenko/skaldr/commit/74b85d0c62adadc4f9f806db68f489b952f9d42e))
* auto % of total per count; DRAFTED legend allows business-only proposals ([7ca2e8d](https://github.com/alex-yanchenko/skaldr/commit/7ca2e8d1ffad8ceb5162b3dbf677f96577b84bdf))
* blocks content model + renderer for the full v1 component set ([#12](https://github.com/alex-yanchenko/skaldr/issues/12)) ([a6514e9](https://github.com/alex-yanchenko/skaldr/commit/a6514e91777c9a564c854182e69addd858672311))
* bounded 6-column grid block with depth-2 nesting [M6b] ([#17](https://github.com/alex-yanchenko/skaldr/issues/17)) ([1cee5de](https://github.com/alex-yanchenko/skaldr/commit/1cee5de2020a78c8845202f2a24d1b2121f38dae))
* data-driven generator for issues & fixes review pages ([92552f5](https://github.com/alex-yanchenko/skaldr/commit/92552f53718e64b8d63cee7bd25afebd015fcc78))
* legend group explaining the two fix-detail labels ([f90003d](https://github.com/alex-yanchenko/skaldr/commit/f90003d7ca97f0b3a6a682ee690a54240f305700))
* **meta:** page width modes — default/wide/full [M6a] ([#16](https://github.com/alex-yanchenko/skaldr/issues/16)) ([f972f9c](https://github.com/alex-yanchenko/skaldr/commit/f972f9ce47869c95bcdef5ac97c53c2e50951389))
* split legend into titled issue-type and fix-status groups ([570f274](https://github.com/alex-yanchenko/skaldr/commit/570f2748e3abeff78e70621e6a3acfaddd632cfa))
* **table:** proportional column width weights [M6c] ([#18](https://github.com/alex-yanchenko/skaldr/issues/18)) ([5ca06a5](https://github.com/alex-yanchenko/skaldr/commit/5ca06a565e6c5084f111a9f1b273f50483c2ba13))
* TO_WORK note replaces the 'not drafted' placeholder when present ([11ec975](https://github.com/alex-yanchenko/skaldr/commit/11ec9757a2175502223fc1e44788ffe5c62252bb))


### Bug Fixes

* darken fix-column text for readability ([1f74705](https://github.com/alex-yanchenko/skaldr/commit/1f747057ee22580aec92cd6de50b2ab7803c9227))
* **release:** refresh uv.lock on the release pr so --locked ci passes ([#7](https://github.com/alex-yanchenko/skaldr/issues/7)) ([4409117](https://github.com/alex-yanchenko/skaldr/commit/440911709dbca4f0f605df911741eabedf07f6c2))


### Documentation

* authoring guide [M5] ([#14](https://github.com/alex-yanchenko/skaldr/issues/14)) ([8b3cef9](https://github.com/alex-yanchenko/skaldr/commit/8b3cef93542cf9d8f2ef5026b9e58d5f09697db1))
* **design:** bounded grid layout + page width modes [M6] ([#15](https://github.com/alex-yanchenko/skaldr/issues/15)) ([81d8f6f](https://github.com/alex-yanchenko/skaldr/commit/81d8f6f187123f1f12cb9753ef9e95713f8f6596))
* **schema:** describe every content-file field + enforcing test [M5] ([#13](https://github.com/alex-yanchenko/skaldr/issues/13)) ([d45bec3](https://github.com/alex-yanchenko/skaldr/commit/d45bec38e1de697befccfb3954da418e107de930))
* skaldr v1 component & visual spec + rendered reference ([#11](https://github.com/alex-yanchenko/skaldr/issues/11)) ([d4d416c](https://github.com/alex-yanchenko/skaldr/commit/d4d416cbd4d8358451fcb9ecae5a3414ee769397))
* skaldr v1 design and handover document ([#8](https://github.com/alex-yanchenko/skaldr/issues/8)) ([81bffc9](https://github.com/alex-yanchenko/skaldr/commit/81bffc98b4e34fa9d9ce91bbe12039dd37c4e9a8))
