Reconciled review of the 10,000-unit cycle count: what didn't match, why, and the fix for each category. {color="gray"}
Mixed audience: ops reads the impact, the floor team reads the fix. {color="gray"}
<table_of_contents/>
- **Source**: WMS export
- **Period**: Q3 2026
- **Site**: DC-West
- **Owner**: Inventory Ops
## Overview
*Reconciled review of the 10,000-unit Q3 cycle count.* {color="gray"}
- **Count date**: 2026-07-09 14:22 UTC
- **Units expected**: 10,000
- **Method**: `full cycle count`
- **Mode**: strict
<empty-block/>
- **Matched cleanly**: 8,500 (85.0%) <span color="green_bg">▲ +3%</span> {color="green"}
- **Floor: fixable**: 1,100 (11.0%) <span color="yellow_bg">Floor</span> {color="yellow"}
	Miscounts + mislabeled bins we can correct. {color="gray"}
- **Vendor: escalate**: 400 (4.0%) <span color="green_bg">▼ −90</span> <span color="red_bg">Vendor</span> {color="red"}
- **Count status**: HEALTHY {color="purple"}
- **Total units**: 10,000 {color="gray"}
<empty-block/>
- **Matched cleanly**: 85.0%, 8,500 units {color="green"}
- **Floor-fixable**: 11.0%, 1,100 {color="yellow"}
- **Vendor**: 4.0%, 400 {color="red"}
The count reconciles exactly: every unit lands in one bucket and the counts sum to the expected total. Reconciliation is a **hard gate**: a page that does not balance *will not build*. The old ~~bin \> 12~~ scan rule is under review; see the [method](https://example.com/runbook).
Percentages are of the 10,000-unit total. Counts were verified against the shelf, not estimated. {color="gray"}
Every bin label now ends in a <span underline="true">check digit</span>. The cold room logged H$`_{\text{2}}`$O condensation on 3 of 10$`^{\text{2}}`$ shelves, so its scans run twice; C++ tooling and \~2 days of rescans are out of scope.
Zone C is <span color="red">behind schedule</span>, its recount is <span color="yellow_bg">due Friday</span>, and the <span color="purple"><span color="blue_bg">vendor lots</span></span> stay open until the supplier replies.
### Count pipeline
```mermaid
flowchart LR
    s1["1: Scan"]:::info
    s2["2: Reconcile"]:::accent
    s3["3: Flag"]:::warning
    s4["4: Fix"]:::success
    s5["5: Recount"]
    s1 --> s2
    s2 --> s3
    s3 --> s4
    s4 --> s5
    s5 -.-> s1
    classDef accent fill:#f3e8fd,stroke:#8430ce,color:#1f2328
    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328
    classDef success fill:#e6f4ea,stroke:#1e8e3e,color:#1f2328
    classDef warning fill:#fef7e0,stroke:#b06000,color:#1f2328
```
- **Flag** <span color="blue_bg">System</span>
### Discrepancy resolution across teams
<table fit-page-width="true" header-row="true" header-column="true">
	<tr>
		<td>**Lane**</td>
		<td>**Detect<br>In-house**</td>
		<td>**Investigate**</td>
		<td>**Resolve**</td>
		<td>**Escalate<br>Vendor claim**</td>
	</tr>
	<tr>
		<td>**Floor**</td>
		<td>✅ **1** Recount bin</td>
		<td>⏸️ **2b** Re-label</td>
		<td></td>
		<td></td>
	</tr>
	<tr>
		<td>**System**</td>
		<td></td>
		<td>🔵 **2a** Check scan log</td>
		<td>⚪ **3** Reconcile</td>
		<td></td>
	</tr>
	<tr>
		<td>**Vendor**</td>
		<td></td>
		<td></td>
		<td></td>
		<td>⛔ **4** Escalate short-ship</td>
	</tr>
</table>
✅ done · 🔵 current · ⚪ todo · ⛔ blocked · ⏸️ deferred {color="gray"}
<callout icon="⚠️" color="yellow_bg">
	**Action needed before the next count**
	The `bin > 12` scan rule skipped 260 valid units in overflow aisles. Confirm the rule with the site lead before re-counting.
</callout>
<callout icon="📏" color="blue_bg">
	Counts below are per distinct discrepancy class, not per unit.
</callout>
## Discrepancies & fixes
<details>
<summary>Legend: badges used on this page</summary>
	- <span color="yellow_bg">Floor</span> Fixable on the floor before the next count.
	- <span color="blue_bg">System</span> Defect in the scanning/labeling pipeline.
	- <span color="red_bg">Vendor</span> Depends on the vendor to resolve.
</details>
<table fit-page-width="true" header-row="true">
	<colgroup>
		<col width="196">
		<col width="49">
		<col width="71">
		<col width="196">
		<col width="196">
	</colgroup>
	<tr>
		<td>**Discrepancy**</td>
		<td>**Risk**</td>
		<td>**Units**</td>
		<td>**What the problem is**</td>
		<td>**Proposed fix**</td>
	</tr>
	<tr color="gray_bg">
		<td>**Floor: fixable (1,100)**</td>
		<td></td>
		<td></td>
		<td></td>
		<td></td>
	</tr>
	<tr color="yellow_bg">
		<td>Double-counted units <span color="yellow_bg">Floor</span><br>Skipped, bin \> 12: 260<br>Same-window re-scan: 340</td>
		<td color="yellow_bg">🟡</td>
		<td>600 (6.0% of total)</td>
		<td>The same pallet is scanned twice when a picker re-enters an aisle within the count window.</td>
		<td>De-duplicate on the pallet ID (`pallet_id`) before totalling; keep the most recent scan.</td>
	</tr>
	<tr color="blue_bg">
		<td>Mislabeled bin codes <span color="blue_bg">System</span></td>
		<td color="yellow_bg">🟡</td>
		<td>500 (5.0% of total)</td>
		<td>Scanner assumed 5-digit bin codes; 9-digit codes were truncated and failed the lookup.</td>
		<td>Widen the scanner to accept 9-digit codes; re-scan the 500 truncated bins from the raw log.</td>
	</tr>
	<tr color="gray_bg">
		<td>**Vendor: escalation (400)**</td>
		<td></td>
		<td></td>
		<td></td>
		<td></td>
	</tr>
	<tr color="red_bg">
		<td>Short shipment <span color="red_bg">Vendor</span></td>
		<td color="red_bg">🔴</td>
		<td>400 (4.0% of total)</td>
		<td>The vendor's ASN listed 400 units that never arrived on the dock, so they can't be counted.</td>
		<td>Escalated to the vendor (ticket `OPS-1234`); hold the line until a corrected ASN arrives.</td>
	</tr>
	<tr color="gray_bg">
		<td>**Correctly counted: no action (0)**</td>
		<td></td>
		<td></td>
		<td></td>
		<td></td>
	</tr>
	<tr>
		<td>*none*</td>
		<td></td>
		<td></td>
		<td></td>
		<td></td>
	</tr>
</table>
**Discrepancies by owner**: <span color="yellow_bg">Floor</span> 1 · <span color="blue_bg">System</span> 1 · <span color="red_bg">Vendor</span> 1
Reconciles: 1,500 + 8,500 matched cleanly = 10,000. {color="gray"}
## Count progress
- **Zone A**: ██████████ 100.0% {color="blue"}
- **Zone B**: █████████░ 92.0% {color="green"}
- **Zone C**: █████████░ 85.0% {color="yellow"}
- **Overflow**: ░░░░░░░░░░ 4.0% {color="red"}
<table fit-page-width="true" header-row="true">
	<colgroup>
		<col width="177">
		<col width="89">
		<col color="yellow_bg" width="88">
		<col width="354">
	</colgroup>
	<tr>
		<td>**Zone**</td>
		<td>**Counted**</td>
		<td>**Variance**</td>
		<td>**Note**</td>
	</tr>
	<tr>
		<td>Zone A</td>
		<td>3,100</td>
		<td>0</td>
		<td>Matched the system count.</td>
	</tr>
	<tr>
		<td>Zone B</td>
		<td>2,760</td>
		<td>12</td>
		<td>Two mislabeled bins, re-scanned.</td>
	</tr>
	<tr color="red_bg">
		<td>Overflow</td>
		<td>120</td>
		<td>260</td>
		<td>Skipped by the `bin > 12` rule.</td>
	</tr>
</table>
**Affects**: <span color="green_bg">inventory</span> <span color="blue_bg">scan-app</span> <span color="purple_bg">DC-West</span>
## Verification
- ✅ Reconciliation gate passes (10,000 = 10,000).
- ✅ De-dup validated on a 1,000-pallet sample.
- 🔵 Overflow bins being re-counted by hand right now.
- ⚪ Overflow re-scan scheduled for the next count.
- ❌ Vendor short-ship: blocked, cannot count.
- ⛔ Vendor escalation awaiting `OPS-1234` response.
### Follow-up checklist
- [x] Confirm the `bin > 12` scan rule with the site lead.
- [ ] Ship the 9-digit bin-code widening behind the scan flag.
	- [ ] Stage on the pilot aisle first.
	- [ ] Watch the mis-scan rate for one shift before widening.
- [ ] Re-run the count and re-verify reconciliation.
#### Sign-off and rollback
- **Owner**: Inventory Ops. **@site-lead** signs off each fix.
- **Rollback**: Re-disable the scan flag; the widened bins fall back to the 5-digit read.
---
<callout icon="🎤" color="gray_bg">
	**For the read-out**
	Lead with the reconciliation gate: it is the one number leadership tracks.
</callout>
### Re-count procedure, from step iv
- iv. Freeze inbound moves in the overflow aisles.
- v. Re-scan every bin with the widened reader.
	- i. Start with the aisles that held the 260 skipped units.
- vi. Re-run reconciliation and compare against the first count.
### Decisions
- ☑️ De-duplicate on the pallet ID and keep the most recent scan.
- ☑️ Hold the vendor line until a corrected ASN arrives.
- ❓ Whether overflow aisles get a count window of their own.
## Rollout
- ✅ **2026-06-30**: Initial full count
	12,400 units scanned; 88% matched clean.
- ✅ **2026-07-02**: Root-caused the double-count bug
	Lexical tiebreak in `dedupe.ts`.
- 🔵 **2026-07-09**: Fix drafted, awaiting re-count
	Placeholder-aware ordering; recovers 1,140 units.
- ⚪ **next count**: Re-verify reconciliation
## Method
Counts come from the scan-stage audit log, grouped by discrepancy reason. The reconciliation query and the de-dup fix are below.
A zone's drift is $`d = \frac{|c - e|}{e}`$, where $`c`$ is the counted units and $`e`$ the expected units; the page reports the mean over the $`n`$ zones, with $`\sigma`$ as its spread.
$$
\bar{d} = \frac{1}{n} \sum_{i=1}^{n} \frac{|c_i - e_i|}{e_i}
$$
`reconciliation.sql`
```sql
SELECT reason, count(*) AS n
FROM count_audit
WHERE cycle_id = 'Q3-2026'
GROUP BY reason
ORDER BY n DESC;
```
`dedupe.ts · tiebreak fix`
```diff
function pickWinner(a, b) {
-  return a.code.localeCompare(b.code);
+  if (isPlaceholder(a) !== isPlaceholder(b))
+    return isPlaceholder(a) ? 1 : -1;
+  return a.code.localeCompare(b.code);
}
```
*Image: Fig 1: discrepancy volume by zone (embedded as a data: URI; skaldr embeds images, it does not generate charts).* {color="gray"}
> These bins are aggregate lots, so we can't split `AGG-07` into individual SKUs from the dock scan alone.<br>*Floor lead, ticket OPS-1234*
## At a glance
<columns>
	<column ratio="33">
		<callout icon="📌" color="purple_bg">
			- **Matched cleanly**: 8,500 (85.0%) {color="green"}
			- **Needs work**: 1,500 (15.0%) {color="yellow"}
		</callout>
	</column>
	<column ratio="67">
		<callout icon="💡" color="blue_bg">
			**Reading this section**
			The cards on the left summarise; the panels below break down count progress and checks side by side.
		</callout>
		- **Zone C**: █████████░ 88.0% {color="yellow"}
		<empty-block/>
		- ✅ Reconciliation gate passes.
		- ⛔ Awaiting `OPS-1234`.
	</column>
</columns>
## Appendix: discrepancy-reason raw counts {toggle="true"}
	*updated 18 Jul 2026* {color="gray"}
	- Double-count (same-window re-scan): 340
	- Double-count (bin \> 12 skip): 260
	- Mislabeled bin code (9-digit truncation): 500
	- Short shipment (vendor): 400
	Raw counts are pre-aggregation and exclude the 8,500 cleanly-matched units. {color="gray"}
	<details>
	<summary>How the raw counts were pulled</summary>
		One pass over the scan-stage audit log for cycle `Q3-2026`, grouped by the reason code each scanner attached.
		- Scans with no reason code count as matched.
		- A pallet scanned in two aisles counts once, under its first aisle.
	</details>
## Counts at a glance
**Clean vs discrepant units by zone**
<table fit-page-width="true" header-row="true">
	<tr>
		<td>**Series**</td>
		<td>**Zone A**</td>
		<td>**Zone B**</td>
		<td>**Zone C**</td>
		<td>**Zone D**</td>
	</tr>
	<tr color="green_bg">
		<td>Clean</td>
		<td>2,100</td>
		<td>1,850</td>
		<td>2,320</td>
		<td>2,230</td>
	</tr>
	<tr color="red_bg">
		<td>Discrepant</td>
		<td>180</td>
		<td>340</td>
		<td>90</td>
		<td>210</td>
	</tr>
</table>
**Open discrepancies over the count window**
```mermaid
xychart-beta
    x-axis ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5"]
    line [1500, 1180, 760, 410, 150]
```
<table fit-page-width="true" header-row="true">
	<tr>
		<td>**Series**</td>
		<td>**Day 1**</td>
		<td>**Day 2**</td>
		<td>**Day 3**</td>
		<td>**Day 4**</td>
		<td>**Day 5**</td>
	</tr>
	<tr>
		<td>Open</td>
		<td>1,500</td>
		<td>1,180</td>
		<td>760</td>
		<td>410</td>
		<td>150</td>
	</tr>
</table>
**How discrepancies resolved**
```mermaid
pie
    "Fixed on floor" : 900
    "System defect" : 760
    "Vendor" : 400
```
<table fit-page-width="true" header-row="true">
	<tr>
		<td>**Slice**</td>
		<td>**Value**</td>
		<td>**Share**</td>
	</tr>
	<tr color="green_bg">
		<td>Fixed on floor</td>
		<td>900</td>
		<td>44%</td>
	</tr>
	<tr color="yellow_bg">
		<td>System defect</td>
		<td>760</td>
		<td>37%</td>
	</tr>
	<tr color="red_bg">
		<td>Vendor</td>
		<td>400</td>
		<td>19%</td>
	</tr>
	<tr>
		<td>**Total**</td>
		<td>**2,060**</td>
		<td></td>
	</tr>
</table>
## Count methods compared
<table fit-page-width="true" header-row="true" header-column="true">
	<tr>
		<td></td>
		<td>**★ Full cycle**</td>
		<td>**Sampling**</td>
		<td>**Continuous**</td>
	</tr>
	<tr>
		<td>**Catches every bin**</td>
		<td color="green_bg">✓</td>
		<td color="red_bg">✗</td>
		<td color="green_bg">✓</td>
	</tr>
	<tr>
		<td>**Effort**</td>
		<td color="red_bg">high</td>
		<td color="green_bg">low</td>
		<td color="yellow_bg">medium</td>
	</tr>
	<tr>
		<td>**Reconciles exactly**</td>
		<td color="green_bg">✓</td>
		<td color="red_bg">✗</td>
		<td color="red_bg">✗</td>
	</tr>
	<tr>
		<td>**Disrupts picking**</td>
		<td color="green_bg">✓</td>
		<td color="red_bg">✗</td>
		<td color="green_bg">✓</td>
	</tr>
</table>
## Readiness by zone
- <span color="yellow_bg">Floor</span>: 7 (43.8%) {color="yellow"}
- <span color="blue_bg">System</span>: 2 (12.5%) {color="blue"}
- <span color="red_bg">Vendor</span>: 2 (12.5%) {color="red"}
	Awaiting the vendor's corrected ASN. {color="gray"}
<table fit-page-width="true" header-row="true" header-column="true">
	<tr>
		<td></td>
		<td>**Scanned**</td>
		<td>**Reconciled**</td>
		<td>**Re-labeled**</td>
		<td>**Signed off**</td>
	</tr>
	<tr>
		<td>**Zone A**</td>
		<td color="yellow_bg">Floor</td>
		<td color="yellow_bg">Floor</td>
		<td color="yellow_bg">Floor</td>
		<td color="yellow_bg">Floor</td>
	</tr>
	<tr>
		<td>**Zone B**</td>
		<td color="yellow_bg">Floor</td>
		<td color="yellow_bg">Floor</td>
		<td color="blue_bg">System</td>
		<td></td>
	</tr>
	<tr>
		<td>**Zone C**</td>
		<td color="yellow_bg">Floor</td>
		<td color="blue_bg">System</td>
		<td color="gray_bg">n/a</td>
		<td></td>
	</tr>
	<tr>
		<td>**Overflow**</td>
		<td color="red_bg">Vendor</td>
		<td color="red_bg">Vendor</td>
		<td></td>
		<td></td>
	</tr>
</table>
<tabs>
	<tab icon="⚠️">
		Floor
		- Re-label the Zone B bins the scanner misread.
		- Recount Zone C by hand before sign-off.
	</tab>
	<tab icon="💡">
		System
		Widen the bin-code field to nine digits, then rescan the 500 truncated bins from the raw log.
	</tab>
	<tab icon="🛑">
		Vendor
		<callout icon="🛑" color="red_bg">
			Overflow stays unreconciled until the vendor sends a corrected ASN for the short shipment.
		</callout>
	</tab>
</tabs>
## Where the count comes from
```mermaid
flowchart LR
    hub["Reconciled count"]:::accent
    s1["Handheld scans<br>per-aisle, live"]:::info
    s2["Fixed-reader gates"]:::info
    s3["Manual recount<br>overflow aisles only"]:::warning
    s1 --> hub
    s2 --> hub
    s3 --> hub
    classDef accent fill:#f3e8fd,stroke:#8430ce,color:#1f2328
    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328
    classDef warning fill:#fef7e0,stroke:#b06000,color:#1f2328
```
## How to run the recount
1. **Freeze the aisle and pull the expected list** *before any scanning* {color="blue"}
	Lock the aisle in the WMS so no picks land mid-count, then export the expected units.
	- One row per bin, with the expected quantity.
	- Flag overflow bins (`bin > 12`): they take the manual path.
2. **Scan every bin twice, reconcile on the pallet ID** {color="purple"}
	Two independent passes; de-duplicate on `pallet_id` so a same-window re-scan can't double-count.
	`reconcile`
	```
	counted = dedupe(scans, key="pallet_id")
	assert sum(counted) == expected
	```
3. **Escalate anything that still won't balance** {color="yellow"}
	<callout icon="⚠️" color="yellow_bg">
		A residual gap is a vendor short-ship, not a miscount. Open a ticket; don't force the numbers.
	</callout>
## Pulling a bin from the WMS yourself
The counts above come from the export, but a disputed bin is quicker to settle against the live API. Fill in your own warehouse and token, copy the command, and run it. What you type stays in your browser tab and is never written back into this page.
**Read one bin's expected quantity**
**Values you supply**
- `{{warehouse}}` warehouse code: for example NW-04
- `{{bin}}` bin: for example A-17-3
- `{{token}}` API token: a secret, supply your own
<tabs>
	<tab icon="✅">
		a bin that balances
		```bash
		curl -i -X GET \
		  -H 'Authorization: Bearer {{token}}' \
		  -H 'Accept: application/json' \
		  'https://wms.example.com/v2/warehouses/{{warehouse}}/bins/{{bin}}'
		```
		**Recorded response**: 200 OK
		```http
		content-type: application/json

		{
		  "bin": "A-17-3",
		  "expected": 48,
		  "counted": 48,
		  "lastCount": "2026-07-14T09:12:00Z"
		}
		```
		<callout icon="✅" color="green_bg">
			**Verdict**: Expected and counted agree, so the bin needs no recount.
		</callout>
	</tab>
	<tab icon="✅">
		an overflow bin
		```bash
		curl -i -X GET \
		  -H 'Authorization: Bearer {{token}}' \
		  -H 'Accept: application/json' \
		  'https://wms.example.com/v2/warehouses/{{warehouse}}/bins/{{bin}}'
		```
		**Recorded response**: 200 OK
		```http
		content-type: application/json

		{
		  "bin": "A-17-9",
		  "expected": 120,
		  "counted": 96,
		  "overflow": true
		}
		```
		<callout icon="✅" color="green_bg">
			**Verdict**: A 24-unit gap on a bin flagged `overflow: true`. These take the manual path rather than a rescan, because the fixed readers cannot see past bin 12.
		</callout>
	</tab>
	<tab icon="⚠️">
		a bin the token cannot read
		```bash
		curl -i -X GET \
		  -H 'Accept: application/json' \
		  'https://wms.example.com/v2/warehouses/{{warehouse}}/bins/{{bin}}'
		```
		**Recorded response**: 401 Unauthorized
		```http
		content-type: application/json

		{
		  "error": "missing_credentials",
		  "message": "This endpoint requires a bearer token."
		}
		```
		<callout icon="⚠️" color="yellow_bg">
			**Verdict**: The same call with the authorization header removed, recorded so the shape of a refusal is recognisable when it turns up unexpectedly.
		</callout>
	</tab>
</tabs>
Overflow bins are the one place the export and the WMS disagree by design. The command below pulls every flagged bin with its gap already worked out. The team's secrets wrapper supplies the token, so there is nothing to fill in: copy it, run it, compare.
**Every overflow bin in one warehouse**
<tabs>
	<tab icon="⚠️">
		NW-04, the finding
		```bash
		vault-run --env prod -- sh -c 'curl -s -H "Authorization: Bearer $WMS_TOKEN" "https://wms.example.com/v2/warehouses/NW-04/bins?overflow=true"' | jq -c 'map({bin, gap: (.expected - .counted)})'
		```
		*The `jq` computes the gap per bin, so a bin the export double-counted shows up as a negative number.* {color="gray"}
		**Recorded output**
		```json
		[
		  {
		    "bin": "A-17-9",
		    "gap": 24
		  },
		  {
		    "bin": "C-02-1",
		    "gap": 2
		  }
		]
		```
		<callout icon="⚠️" color="yellow_bg">
			**Verdict**: Two overflow bins short, 26 units between them, matching the manual-path queue.
		</callout>
	</tab>
	<tab icon="✅">
		NW-02, the control
		```bash
		vault-run --env prod -- sh -c 'curl -s -H "Authorization: Bearer $WMS_TOKEN" "https://wms.example.com/v2/warehouses/NW-02/bins?overflow=true"' | jq -c 'map({bin, gap: (.expected - .counted)})'
		```
		*The `jq` computes the gap per bin, so a bin the export double-counted shows up as a negative number.* {color="gray"}
		**Recorded output**
		```json
		[
		  {
		    "bin": "B-11-4",
		    "gap": 0
		  }
		]
		```
		<callout icon="✅" color="green_bg">
			**Verdict**: A warehouse with fixed readers past bin 12 balances, so the gap is the readers, not the export.
		</callout>
	</tab>
</tabs>
## Reconciling a bin against the live system
The bin lookup above assumes you already hold a token. Getting one is its own call, so the two together are the shape worth recording: exchange the key for a session token, then spend it.
**Session token, then a bin lookup**
**Values you supply**
- `{{warehouse}}` warehouse code: for example NW-04
- `{{api_key}}` API key: a secret, supply your own
**Step 1 of 2: Exchange the API key for a session token**, captures `session_token` from `$.token`
*200*
```bash
curl -i -X POST \
  -H 'Content-Type: application/json' \
  --data '{"key":"{{api_key}}","scope":"inventory.read"}' \
  'https://wms.example.com/v2/sessions'
```
**Recorded response**: 200 OK
```http
content-type: application/json

{
  "token": "sess_8f21c4…",
  "expiresIn": 900
}
```
<callout icon="✅" color="green_bg">
	**Verdict**: Tokens last fifteen minutes, so a long recount needs this step again partway through.
</callout>
**Step 2 of 2: Read the bins that did not balance**
<tabs>
	<tab icon="✅">
		with the token
		```bash
		curl -i -X GET \
		  -H 'Authorization: Bearer {{session_token}}' \
		  -H 'Accept: application/json' \
		  'https://wms.example.com/v2/warehouses/{{warehouse}}/bins?status=variance'
		```
		**Recorded response**: 200 OK
		```http
		content-type: application/json
		x-total-count: 3

		{
		  "bins": [
		    { "bin": "A-17-9", "expected": 120, "counted": 96, "overflow": true },
		    { "bin": "C-02-1", "expected": 30, "counted": 28 }
		  ]
		}
		```
		<callout icon="✅" color="green_bg">
			**Verdict**: The same three bins the discrepancy table above accounts for, read straight from the system rather than from the export.
		</callout>
	</tab>
	<tab icon="⚠️">
		once the token has expired
		```bash
		curl -i -X GET \
		  -H 'Authorization: Bearer {{session_token}}' \
		  -H 'Accept: application/json' \
		  'https://wms.example.com/v2/warehouses/{{warehouse}}/bins?status=variance'
		```
		**Recorded response**: 401 Unauthorized
		```http
		content-type: application/json

		{
		  "error": "token_expired",
		  "message": "Start a new session."
		}
		```
		<callout icon="⚠️" color="yellow_bg">
			**Verdict**: Fifteen minutes after step 1. Worth recording beside the success, because a recount that runs long hits this rather than a data problem.
		</callout>
	</tab>
</tabs>
<callout icon="📝" color="gray_bg">
	**Before the next count**
	- [x] Confirm the `bin > 12` rule with the site lead
	- [ ] Re-label the 9-digit bins in aisle C
	- [ ] Book the vendor call for the short shipment
</callout>
## Sources
Method definitions follow the warehouse counting SOP \[1\]; the discrepancy thresholds come from the Q2 reconciliation audit [\[2\]](https://example.com/q2-audit).
- \[1\] *Warehouse Counting SOP*, rev. 7, §3 Cycle vs sampling.
- \[2\] Q2 Reconciliation Audit, p. 12. [source](https://example.com/q2-audit)
WMS export · Q3 2026 · updated 18 Jul 2026 · Reconciles: 1,500 + 8,500 matched cleanly = 10,000. {color="gray"}
