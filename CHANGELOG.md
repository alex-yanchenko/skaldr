# Changelog

## [1.4.0](https://github.com/alex-yanchenko/skaldr/compare/v1.3.3...v1.4.0) (2026-07-22)


### Features

* **cli:** --check (validate without rendering) and --emit-json (normalised model) ([#71](https://github.com/alex-yanchenko/skaldr/issues/71)) ([e2e91bb](https://github.com/alex-yanchenko/skaldr/commit/e2e91bb0d7eb5b38e3e4b04d7094287db6a5142f))
* **freshness:** per-section and document updated: stamps for living docs ([#73](https://github.com/alex-yanchenko/skaldr/issues/73)) ([1eb4640](https://github.com/alex-yanchenko/skaldr/commit/1eb46408a1706dde2895b6e3fafb00321d6e1b7b))
* **models:** !include for shared YAML fragments (relative paths, cycle detection) ([#72](https://github.com/alex-yanchenko/skaldr/issues/72)) ([bdab59d](https://github.com/alex-yanchenko/skaldr/commit/bdab59d0d68540b9d215651307033625dbd72f91))
* **swimlane:** lane/column ids + column sub-captions (string-or-object addressing) ([#69](https://github.com/alex-yanchenko/skaldr/issues/69)) ([ec2f9d6](https://github.com/alex-yanchenko/skaldr/commit/ec2f9d68232d2d0d7241e0deb56116cedf170b27))
* **swimlane:** per-step value on the ticket + totals-row refinements ([#66](https://github.com/alex-yanchenko/skaldr/issues/66)) ([1420889](https://github.com/alex-yanchenko/skaldr/commit/14208891580cc25b64e245d7e589b07a994bf5da))
* **swimlane:** step dependencies via id + depends_on, shown as a "needs N" marker ([#68](https://github.com/alex-yanchenko/skaldr/issues/68)) ([73a2f72](https://github.com/alex-yanchenko/skaldr/commit/73a2f724d6fb938d5abf7714c04fc0a1f762c9fa))
* **swimlane:** sum step values into per-column, per-lane and per-group totals ([#65](https://github.com/alex-yanchenko/skaldr/issues/65)) ([5b18ce2](https://github.com/alex-yanchenko/skaldr/commit/5b18ce27c3ed3c82a2937bf6e767c788d5216cdd))
* **table:** badge column placement:cell — chips in their own labelled column ([#70](https://github.com/alex-yanchenko/skaldr/issues/70)) ([7de24f7](https://github.com/alex-yanchenko/skaldr/commit/7de24f7843e4cfe82b1de151e0543a22e2f80ee3))
* **table:** render blank lines in rich/text cells as paragraph breaks ([#75](https://github.com/alex-yanchenko/skaldr/issues/75)) ([734d05c](https://github.com/alex-yanchenko/skaldr/commit/734d05ca3c502011e592f6bfbaa86b18175526a3))
* **table:** rollup — counts rows by a badge column into a derived summary strip ([#74](https://github.com/alex-yanchenko/skaldr/issues/74)) ([576538e](https://github.com/alex-yanchenko/skaldr/commit/576538ef461aa33aa7a0c46f52f54cc804e5e965))


### Bug Fixes

* **swimlane:** stop the cap-separator poke firing against ungrouped columns ([#63](https://github.com/alex-yanchenko/skaldr/issues/63)) ([c462bde](https://github.com/alex-yanchenko/skaldr/commit/c462bdeac9317677935e0662ea46c5d80279b2b0))

## [1.3.3](https://github.com/alex-yanchenko/skaldr/compare/v1.3.2...v1.3.3) (2026-07-21)


### Bug Fixes

* **swimlane:** surgical corner, cap separators, square frame edge at caps ([#61](https://github.com/alex-yanchenko/skaldr/issues/61)) ([9ab90d4](https://github.com/alex-yanchenko/skaldr/commit/9ab90d41d15e471eae0f6ccfd78f02b9434916a8))

## [1.3.2](https://github.com/alex-yanchenko/skaldr/compare/v1.3.1...v1.3.2) (2026-07-21)


### Bug Fixes

* **swimlane:** roomier ticket cells + drop the empty gutter/header corner ([#59](https://github.com/alex-yanchenko/skaldr/issues/59)) ([98a3f2b](https://github.com/alex-yanchenko/skaldr/commit/98a3f2b5989cacbebc8d5d5d69d07f7f44ab812e))

## [1.3.1](https://github.com/alex-yanchenko/skaldr/compare/v1.3.0...v1.3.1) (2026-07-21)


### Bug Fixes

* **swimlane:** columns fill available width instead of sitting at 150px ([#57](https://github.com/alex-yanchenko/skaldr/issues/57)) ([41f11bc](https://github.com/alex-yanchenko/skaldr/commit/41f11bc7b45c7756927e549e4249e3510399a7ac))

## [1.3.0](https://github.com/alex-yanchenko/skaldr/compare/v1.2.0...v1.3.0) (2026-07-21)


### Features

* **blocks:** add a per-block span width primitive ([#55](https://github.com/alex-yanchenko/skaldr/issues/55)) ([e83d83b](https://github.com/alex-yanchenko/skaldr/commit/e83d83b343f6a23bbd3597c3432c1ae9a14631fd))

## [1.2.0](https://github.com/alex-yanchenko/skaldr/compare/v1.1.0...v1.2.0) (2026-07-20)


### Features

* **swimlane:** named column axis + optional milestone group overlay ([#53](https://github.com/alex-yanchenko/skaldr/issues/53)) ([66e7c65](https://github.com/alex-yanchenko/skaldr/commit/66e7c6527a5e8719c6e9d3f430bcc5569177a180))


### Bug Fixes

* **release:** retry Homebrew formula generation to survive PyPI propagation races ([#51](https://github.com/alex-yanchenko/skaldr/issues/51)) ([806b676](https://github.com/alex-yanchenko/skaldr/commit/806b6761d65f84b9eabc8ef2c6607582d08d89e6))

## [1.1.0](https://github.com/alex-yanchenko/skaldr/compare/v1.0.1...v1.1.0) (2026-07-17)


### Features

* **badge_row:** group chips into labelled gutter rows ([#48](https://github.com/alex-yanchenko/skaldr/issues/48)) ([31697f2](https://github.com/alex-yanchenko/skaldr/commit/31697f2e9e6392534fb647ffab4d54518852c66c))
* **comparison:** per-column polarity to flip ✓/✗ colour for present-is-bad attributes ([#45](https://github.com/alex-yanchenko/skaldr/issues/45)) ([340670b](https://github.com/alex-yanchenko/skaldr/commit/340670b9f1310ae1b91570231bca69f9cbd79751))
* **flow:** let a step carry a few detail points, not just a one-liner ([#46](https://github.com/alex-yanchenko/skaldr/issues/46)) ([ea93e34](https://github.com/alex-yanchenko/skaldr/commit/ea93e348248fabf5e4e29f169d6ce41937c4ca51))
* **range:** a bar sized by numeric span, for date windows / coverage ([#47](https://github.com/alex-yanchenko/skaldr/issues/47)) ([bbf63f9](https://github.com/alex-yanchenko/skaldr/commit/bbf63f9578f81523370ec71024148a5a4cbc8eee))
* **skill:** make skaldr the default for report-shaped docs, with a markdown-destination boundary ([#50](https://github.com/alex-yanchenko/skaldr/issues/50)) ([49936e6](https://github.com/alex-yanchenko/skaldr/commit/49936e679b609328396693ff79fd478d52a39a0b))
* **status_list:** add a 'current' state for in-progress items ([#41](https://github.com/alex-yanchenko/skaldr/issues/41)) ([5495698](https://github.com/alex-yanchenko/skaldr/commit/5495698c8f95f42ef8f0df948a6957cee8f0a33b))
* **swimlane:** a lane-by-time matrix for multi-track processes ([#49](https://github.com/alex-yanchenko/skaldr/issues/49)) ([87dbadd](https://github.com/alex-yanchenko/skaldr/commit/87dbaddc5ba774774f75456646ae94cc51662472))
* **tones:** unify the tone and badge-colour vocabularies into one 8-colour palette ([#44](https://github.com/alex-yanchenko/skaldr/issues/44)) ([b5f77b9](https://github.com/alex-yanchenko/skaldr/commit/b5f77b925a6c70a529fdcda5df74ec24af6cf499))


### Bug Fixes

* **comparison:** make the highlighted column read as a panel in light theme ([#42](https://github.com/alex-yanchenko/skaldr/issues/42)) ([ae29870](https://github.com/alex-yanchenko/skaldr/commit/ae2987040385cdff1895ea1172702e62f2095ed1))

## [1.0.1](https://github.com/alex-yanchenko/skaldr/compare/v1.0.0...v1.0.1) (2026-07-16)


### Bug Fixes

* **theme:** unlayer box-sizing + body surface so an embedding host can't strand the theme ([#39](https://github.com/alex-yanchenko/skaldr/issues/39)) ([d8a2b46](https://github.com/alex-yanchenko/skaldr/commit/d8a2b464d16220336ae0afc232062db6f124cad2))

## [1.0.0](https://github.com/alex-yanchenko/skaldr/compare/v0.8.0...v1.0.0) (2026-07-15)


### ⚠ BREAKING CHANGES

* **width:** meta.width is removed. A report YAML that sets meta.width now fails the build (Meta forbids extra keys). Width is a reader-only control on the rendered page; drop meta.width from any existing spec.

### Bug Fixes

* **theme:** move color-scheme outside [@layer](https://github.com/layer) so the theme survives an embedding host ([#36](https://github.com/alex-yanchenko/skaldr/issues/36)) ([4e4067b](https://github.com/alex-yanchenko/skaldr/commit/4e4067b02fd138aa10cd6f7e3ba24d50b1e3ffd4))
* **walkthrough:** uniform step numerals, brighter in dark theme, tone as a step accent ([#34](https://github.com/alex-yanchenko/skaldr/issues/34)) ([45a69e8](https://github.com/alex-yanchenko/skaldr/commit/45a69e82ad74b4a2da12c624302c6a5a48875b5d))


### Code Refactoring

* **width:** make page width a reader-only control, not an author field ([#35](https://github.com/alex-yanchenko/skaldr/issues/35)) ([26496e9](https://github.com/alex-yanchenko/skaldr/commit/26496e944f7c5dc4827d98dfdf51dc67412ef73d))

## [0.8.0](https://github.com/alex-yanchenko/skaldr/compare/v0.7.0...v0.8.0) (2026-07-14)


### Features

* **cards:** add an optional KPI delta chip beside the value ([#28](https://github.com/alex-yanchenko/skaldr/issues/28)) ([fb29bdd](https://github.com/alex-yanchenko/skaldr/commit/fb29bdd1b9080cae4351461a756461b81707c809))
* **chart:** add a chart block — bar/line/donut as render-time inline SVG ([#25](https://github.com/alex-yanchenko/skaldr/issues/25)) ([2f8e7da](https://github.com/alex-yanchenko/skaldr/commit/2f8e7da4f45a18b2e2803bee01116965ce0db943))
* **comparison:** add a feature-matrix block (options × features) ([#29](https://github.com/alex-yanchenko/skaldr/issues/29)) ([ec65e98](https://github.com/alex-yanchenko/skaldr/commit/ec65e988f640b473b37637cc16107012ff80e8fe))
* **fan:** add a fan block for one-to-many convergence/divergence ([#31](https://github.com/alex-yanchenko/skaldr/issues/31)) ([d783042](https://github.com/alex-yanchenko/skaldr/commit/d783042e9fa73b00a72ca259b366f2aab500fde5))
* **references:** add a references block with inline [^key] citations ([#30](https://github.com/alex-yanchenko/skaldr/issues/30)) ([70cfd4a](https://github.com/alex-yanchenko/skaldr/commit/70cfd4a3177cda96272284ef7a4d667b9e69d8c4))
* **walkthrough:** add a walkthrough block — numbered steps with per-step detail columns ([#32](https://github.com/alex-yanchenko/skaldr/issues/32)) ([ca0a7e0](https://github.com/alex-yanchenko/skaldr/commit/ca0a7e02894b295c7454c5b0b66dd438af5fca6f))

## [0.7.0](https://github.com/alex-yanchenko/skaldr/compare/v0.6.0...v0.7.0) (2026-07-14)


### Features

* **cli:** --pdf renders a ready-to-share PDF via a headless browser ([#18](https://github.com/alex-yanchenko/skaldr/issues/18)) ([665edd9](https://github.com/alex-yanchenko/skaldr/commit/665edd9ccaa78e46d84b400b048c61ec14fef194))
* **print:** scale print/PDF to 0.75 for document density ([#19](https://github.com/alex-yanchenko/skaldr/issues/19)) ([1d47c82](https://github.com/alex-yanchenko/skaldr/commit/1d47c8281cc3f06257067f53081cfc509a661938))


### Bug Fixes

* **embed:** keep the corner controls + scripts, carry the title ([#15](https://github.com/alex-yanchenko/skaldr/issues/15)) ([ff84354](https://github.com/alex-yanchenko/skaldr/commit/ff8435438e626b03b8d9e85bb3a024861ea59579))
* **pdf:** correct --pdf output ordering, section expansion, and browser discovery ([#21](https://github.com/alex-yanchenko/skaldr/issues/21)) ([4917ed0](https://github.com/alex-yanchenko/skaldr/commit/4917ed00de5306c0286267fe0d119c8f317cf97d))
* **print:** keep headers with their content and stack flows vertically ([#20](https://github.com/alex-yanchenko/skaldr/issues/20)) ([c9de36a](https://github.com/alex-yanchenko/skaldr/commit/c9de36a563a80e10f8e20ae6327a023786c18d46))
* **print:** keep table groups together, break code across pages, restyle code/diff ([#22](https://github.com/alex-yanchenko/skaldr/issues/22)) ([136e914](https://github.com/alex-yanchenko/skaldr/commit/136e91481867e02e0edc8bcd1b7eec28a636d1f9))
* **print:** readable PDF — colours, unsplit rows, repeating headers ([#16](https://github.com/alex-yanchenko/skaldr/issues/16)) ([6175c84](https://github.com/alex-yanchenko/skaldr/commit/6175c8490f9034fdf29feadb0df87426fd4c7735))


### Code Refactoring

* **styles:** modernise CSS — cascade layers, nesting, logical properties ([#23](https://github.com/alex-yanchenko/skaldr/issues/23)) ([cd82051](https://github.com/alex-yanchenko/skaldr/commit/cd82051f0148b2804225d79d5935ab2670ed8808))

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
