# Locus

**Where does the milestone land across thousands of possible futures, what really drives it, and which links can be broken to win time back?**

**Live app:** https://8begpzao4qkmdjthwx2f4r.streamlit.app

*Why "Locus":* in geometry a locus is the set of all points that satisfy a condition; here it is the set of dates on which first fire can land once everything it depends on is true.

Most schedule tools answer "what is the status?". Locus answers the questions a project controls lead or delivery PM actually gets asked in the room:

- *"Will we make first fire in January?"* → a probability, not a single date
- *"What is driving it?"* → Criticality Index across thousands of simulated futures
- *"What if productivity is poor across the whole site?"* → common risks that move many items together, and what removing each one is worth
- *"Why don't we just start X early to win time?"* → the gain, how often that link really drives the milestone, and what breaking it costs
- *"Where does the delay come from: design, equipment, permits or the site?"* → the gap between the plan and the simulated futures, split by source
- *"How late can the transformer arrive / the drawings be issued / the site be handed over?"* → latest acceptable dates, back-calculated from the milestone
- *"Piling starts a month late: how much later is first fire, and how much of that is weather?"* → the same late start simulated without and with ten years of station weather; the gap is what weather adds
- *"What if the plum rain stops the site for a week?"* → what a lost week costs at each point of the schedule, with weather that comes in spells

The reference model is a **generic single-shaft CCGT** (GT, generator and ST on one shaft; HRSG without bypass stack), one unit, in Taiwan, utility-owned, main equipment from overseas makers, from site handover and the start-of-works approval, through construction of the turbine hall, HRSG and stack, mechanical completion and commissioning, to **GT first fire**.

> The reference plant is fictional. It is built from general engineering practice and public sources and does not describe any real project.

## The app

| Page | Question it answers |
|---|---|
| Start here | The story: what is simulated, what the plan says, what the simulated futures say, where the delay comes from (by source), what the analysis supports (five actions with evidence and trade-offs), and three what-ifs |
| Guide | How to read every page, in English or Traditional Chinese (switch at the top) |
| Summary | One finding per page, each one sentence and one number |
| Milestone confidence | How likely is the plan date, why does it miss, and how much contingency is needed? |
| What drives the date | Which items drive the milestone, and how often? Items that are always critical together are merged into one row; click a bar for its predecessors |
| Common risks | Which risk that slows many items at once costs the most, and what is removing it worth? |
| Win time back | Which proposals gain time, how often their link really drives, and what they cost |
| Reviews and latest dates | Which reviews apply, and how late can deliveries, drawings, the site handover and submissions be? |
| Late-start cost | How far does a late start move first fire without weather and with weather? The gap is the headline finding |
| Weather risk | Which activities face strong wind or heavy rain in their window (warnings), what does a forced stoppage cost at each date, and does it matter that bad weather comes in spells? |
| Assumptions and sources | Every input with its source grade |

Settings live in the sidebar, in the order a first-time reader needs them; the rest is collapsed. Changing a setting does not recalculate; press **Run** to update every page.

**Delays to test.** Site handover (notice to proceed), the start-of-works approval, design deliverables (piling, foundation and steel IFC, the overseas maker's certified foundation drawings, the steel shop drawings) and steel fabrication are on time by default: design is followed closely up to IFC, and a utility owner rarely hands over late. Practice differs between companies, so each one takes a delay in days, alone or together. The plan keeps its dates; the simulation carries the delays, and every page shows what they cost.

**Weather is a switch.** *Apply weather to the schedule* is **off by default**: weather is then shown as warnings (possible impacts) and no date changes. Switch it on to let rain and wind stop weather-sensitive work. The thresholds and other weather settings sit in the collapsed *Weather parameters* panel; each one shows its source and verification status, also listed on the Assumptions and sources page.

## Design: first principles, then context

The model separates *why* something must happen from *how it happens to be done here*:

| Layer | Content | Where it lives | Changes when |
|---|---|---|---|
| L0 Physical invariants | Cause and effect that cannot be broken (no heat sink, no vacuum) | `links` with `type: physical` | Almost never |
| L1 Technology | Configuration decides which invariants apply (single-shaft: vacuum before first fire) | plant file | Per plant type |
| L2 Jurisdiction and owner | Reviews, inspections, permits | `rules_*.yaml` | Per country, owner, era |
| L3 Site | Weather, geology (pile type) | `weather_*.yaml`, plant parameters | Per site |
| L4 Project | Durations, crews, sequencing choices | plant file | Per project |

Swap a rule pack to change jurisdiction; swap a weather table to change site; the engine does not change.

### Every link has a type

| Type | Meaning | Can it be broken? |
|---|---|---|
| physical | Physical cause and effect | No |
| regulatory | Required by law or the grid operator | No, but preparation can start earlier |
| means | The invariant holds, the means can change (a certified crane is one way to get lifting capacity) | Yes, by switching means |
| contractual | Agreed between parties | Negotiable |
| resource | Crew, sequence or practice choice | Yes, field can adjust |
| logistics | Space, access, crane stands, haul routes | Yes, with re-planning |

Breakable links carry a `relax` entry: the alternative logic, the **proposal** as it is said on site, and **what it costs**. Breaking a link trades schedule risk for another risk; the app shows both.

### Five kinds of uncertainty

Weather (rain for civil work, wind for heavy lifts, in multi-day spells), productivity, supply (external arrivals, including design deliverables and the site handover), and **reviews** (inspections and permits: long-tailed, and adding people does not make them faster). A rule engine reads asset attributes (e.g. a fixed crane of 3 t or more) and inserts the applicable reviews automatically, each with its legal basis.

The fifth is **common risks** (risk drivers): one event that slows many items at once, such as site-wide low productivity or a supply-chain disruption. Each has a chance of occurring, a size (a factor on durations or days added), and the items it applies to. In one simulated future every affected item gets the same size, so their delays move together instead of cancelling out.

## Method

- **Monte Carlo, vectorised across iterations** (NumPy). 1,000 iterations of the 80-node network run in under 0.01 s.
- **Calendar-aware weather** (when weather is applied): weather-sensitive work consumes *workable* days; a day is lost with the probability for its calendar month.
- **Weather spells**: bad weather comes in runs. A two-state Markov chain makes a lost day more likely after a lost day, with the monthly **mean spell length** as its parameter and the transition out of workable days tuned so the long-run share of lost days stays exactly the table value. Spells regroup lost days; they do not add any. With independent days a lost week is almost impossible (0.25⁷ ≈ 1 in 16,000); with the Xinwu record, a week or more of consecutive rain days appears in about one simulated future in ten.
- **Weather switch**: weather is a scenario flag. Off (the default), weather is shown as warnings only and no date changes; on, rain and wind stop weather-sensitive work under the weather parameters. Both modes use the same random numbers, so the difference is weather alone. Without weather the network is max-plus with fixed durations, so a late start can never pass through more than one-for-one (tested); only weather can amplify it.
- **Headline finding** (default parameters, seed 42, 5,000 iterations): a four-week late start moves P50 first fire by 12 days without weather and 19 days with the station weather; a twelve-week late start by 56 and 72 days. Weather adds 7 and 16 days to those late starts here, without amplifying them beyond one-for-one.
- **Forced-stoppage stress test**: every weather-sensitive activity loses a window of days (default 7) on top of the simulated weather; sweeping the window across the schedule shows when a lost week bites and when float absorbs it.
- **Why the plan misses, by mechanism** (Milestone confidence): the single-number plan takes four best cases at once. Removing them one at a time on the same random numbers splits the gap exactly: deliveries at their average delay instead of the planned day (+23 days), durations at their average instead of the most likely (+15), merge bias, the simulated average of the latest converging path against a single pass of average paths (+7), and common risks (+37 on the average; on P80 they add about 53, because they also widen the spread), which take the plan to the simulated average (+82); the spread up to P80 adds 35, for 117 days of contingency. That is why the plan date is met in about 8 of 5,000 futures (default parameters, weather off, seed 42, 5,000 iterations).
- **Where the delay comes from, by source** (Start here): each source is left out in turn, on the same random numbers, with its items exactly as planned: *if only this source went to plan, how much earlier would first fire be on average?* No order has to be chosen. With the same settings: equipment and materials +15 days, site construction +14, commissioning +9, permits and inspections +3, common risks +37, site handover and design 0 (on time by default); what the sources add together beyond their own bars, the combined effect (merge bias), is +4, for the same simulated average (+82). Each step is shown rounded to the nearest day and the merge-bias step takes the rounding remainder, so the steps add up exactly and the same raw value (common risks, for example) shows the same number in both splits.
- **What the analysis supports** (Start here): five actions computed from the current run, each with its evidence and trade-off: commit to the P80 date; put mitigation on the largest source and the costliest common risk; track the items with the least float against the P80 date (a second backward pass with P80 as the target); use the proposals that win time; protect the site start.
- **Mechanical completion**: commissioning to first fire starts once the turbine hall, the HRSG and the stack are built and their E&I is complete; every Gate A, B and C item follows it and power receipt (tested in every simulated future). Mechanical completion drives first fire in about 94% of futures, so turning systems over area by area, before all E&I is done, is the proposal that wins most time (+26 days at P50), at the cost of construction and commissioning side by side in the same building.
- **Criticality Index**: share of futures in which a node is on the driving path, traced back from the milestone through the link that actually set each start.
- **Common Random Numbers**: every scenario reuses the same random draws, so differences come from the logic change only. Each node draws from its own stream, keyed by its id, so adding or removing a node never changes the draws of any other node.
- **Sized weather horizon**: the simulation keeps only as many days of weather as the plan can reach (a pessimistic plan with every input at its 99.9th percentile, plus the late-start experiment, plus 25%), about 4.6 years for the reference plant with the default settings instead of 10. Weather draws are fixed per calendar day, so the horizon changes memory, never results. 5,000 iterations need about 70 MB.
- **Latest dates**: a backward pass against the target gives each node's latest finish per future; the reported date holds in 80% of futures (adjustable).
- **Distributions**: triangular for work, lognormal (median and P90) for reviews, whose waiting times have long right tails.
- **Common risks**: one occurrence draw and one size draw per risk per iteration, from their own random stream, shared by every item the risk applies to. Work = sampled duration × product of factors + sum of added days. The attribution re-runs the same futures with one risk removed (what mitigation is worth) and with one risk alone. With the four illustrative risks, P80 moves about 53 days later without weather and 59 days later with the station weather (default parameters, 5,000 iterations).

## Data and provenance

Every input carries a grade, visible in the app:

- **A**: law text or official data
- **B**: industry or public documents
- **C**: explicit assumption or practitioner estimate

Items added by a rule show two grades, process / duration (for example A/C).

### Weather data

**Every result is a simulation that demonstrates the method; it is not a forecast.**

資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務（測站：新屋 467050，期間 2016–2025），依政府資料開放授權條款第 1 版使用，經作者加工計算。

The weather table (`config/weather_cwa_xinwu.yaml`) is the author's processing of ten years of daily records from one north-west coastal station; it is not a CWA product and implies no endorsement by CWA. The reference plant remains fictional; the station only supplies a realistic climate.

| Item | Detail |
|---|---|
| Station, period | Xinwu 新屋 (467050), 2016-01-01 to 2025-12-31, daily records |
| Coverage | Precipitation 100% of days; maximum 10-min wind at least 98.4% in every year (station note: works 2020-01-01 to 2020-02-15) |
| Weather switch | **Off by default**: weather is shown as warnings (possible impacts) and not applied to the schedule. The user can switch it on; the Late-start cost page always shows both modes |
| Rain | Daily precipitation ≥ threshold (default 10 mm; options 5–30 mm) stops rain-sensitive (civil and outdoor) work when weather is applied. Author's assumption, no standard cited |
| Wind | Daily maximum 10-minute mean wind: warning threshold (default 10 m/s, about 139 days a year) and stoppage threshold (default 16 m/s, about 1 day a year); options 8–20 m/s. **Legal basis pending verification.** With weather applied, the share of windy spells that stop work and 0–10 remobilisation days are user settings (assumptions). Gust factor 1.71 (149 hourly observations, 2024) converts thresholds to gust values for display only |
| Cross-check | Monthly counts of rain ≥ 10 mm days and 10-min wind ≥ 10 m/s days match the CWA yearly reports in 120 of 120 months |

Reproduce: `scripts/cwa_download.py` (one-time, throttled download: at least 2 s between requests, retries with backoff, skips files already present; raw files stay in `data/raw/`, which git ignores), then `scripts/build_weather_table.py`.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Tests:

```bash
pip install -r requirements-dev.txt
pytest
```

## Using it on a real P6 schedule

Locus reads YAML, not XER, so a real schedule needs one conversion step. What maps directly:

| Locus | From a P6 export (XER tables) |
|---|---|
| Activities: id, name, most-likely duration | `TASK`: `task_code`, `task_name`, remaining or original duration (hours converted to days with the calendar's hours per day) |
| Links: FS / SS with lag | `TASKPRED`: `pred_type` `PR_FS` / `PR_SS`, `lag_hr_cnt`. FF and SF links need to be restated as FS or SS; Locus does not model them yet |
| Groups | `PROJWBS` (WBS) or activity codes |
| External inputs (deliveries, drawings, handover) | Milestones with constraints or no predecessors |
| Weather-sensitive work | The calendar or an activity code that marks outdoor civil work and lifts |

What P6 does not hold and a planner has to add, which is where the judgement is: the ranges (minimum, most likely, maximum) from a risk workshop or history, the common risks and what they touch, the **type** of every link that matters (physical, regulatory, means, contractual, resource, logistics), and for each breakable link the proposal as said on site and what breaking it costs. A converter for the first table is on the roadmap; the second part stays a planner's job.

## Known limitations

- Beyond weather and the common risks in the plant file, activity durations are drawn independently of each other. The shipped risks are illustrative; a real project needs its own risk register behind them.
- Rain and wind are drawn independently of each other, so a typhoon that stops both is not a joint event. Resampling whole historical years of CWA daily records would capture that.
- Wind is measured at the station anemometer (about 10 m above ground); wind at crane working height is stronger. Daily maxima include night-time hours: on about 30% of days with 10-min wind ≥ 10 m/s the maximum fell outside 07:00–18:00, so warnings can overstate windy working days.
- One weather station for the whole site; rain is taken to stop civil and outdoor work only (indoor work continues once the envelope is closed, which is usual but not certain).
- Design, procurement and transport are not expanded; each design deliverable and major package is one arrival with a delay spread (design and site handover: a fixed delay the user sets, on time by default).
- The split by source measures each source alone; how much they add together is shown as one combined bar, not attributed to individual sources.
- Linear assets (tunnels) are split into segments with access logic, not simulated in 4D.
- Resource levelling is not modelled; crew conflicts appear only as `resource` links.
- Rules marked `pending` (wastewater permit, pressure-equipment inspection) are listed but not inserted until verified.
- Durations are illustrative. The value is in the structure and the questions it answers, not the specific dates.

## Project layout

```
app.py                      Streamlit entry: sidebar settings, explicit Run, navigation
views/                      one page per question
locus/
  distributions.py          inverse-CDF sampling (enables common random numbers)
  model.py                  network, common risks, delay sources, validation, topological order
  rules.py                  rule engine and review templates
  weather.py                monthly table -> daily probabilities, spell transitions, weather rule
  weather_stats.py          monthly shares and spell lengths from daily records
  cwa_loader.py             parser for CWA CODiS station reports
  simulate.py               Monte Carlo engine, driving path, backward pass
  analysis.py               decision outputs
  labels.py                 all UI wording
  help.py                   in-app guide loader
config/
  reference_plant.yaml      activities, external inputs (site handover, design, equipment), typed links,
                            delay sources, common risks, assets
  rules_taiwan.yaml         L2 rule pack (Taiwan, utility-owned)
  weather_cwa_xinwu.yaml    weather table built from CWA CODiS records (Xinwu 新屋 467050)
scripts/
  cwa_download.py           one-time, throttled CODiS download
  build_weather_table.py    daily records -> weather table
docs/help_en.md, help_zh.md in-app guide, English and Traditional Chinese
tests/                      pytest: engine against brute-force references and invariants, weather
                            statistics, CODiS parser, licence wording, plan gap and split by source,
                            every page under Streamlit AppTest (data/raw/ is never committed)
```
