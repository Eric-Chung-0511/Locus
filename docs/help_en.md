# Locus guide

<!-- section: start -->
## What this app does

Locus asks four questions that a planner or delivery PM hears in real meetings, and answers each with numbers you can trace:

1. How likely is first fire on the planned date, and how much contingency does the plan need?
2. What actually drives the date?
3. "Why don't we just start X early?" How much time does a proposal win, and what does it cost?
4. How late can a delivery arrive, or a permit application go in, and still protect the target?

It does this by simulating the project many times (each run is one *iteration*, one possible future). Durations, deliveries, reviews and weather vary from one future to the next, following the ranges in the plant file. The answers are shares of those futures, not single dates.

The reference plant is fictional: a generic single-shaft combined-cycle unit in Taiwan, from site handover to gas-turbine first fire. **Every result is a simulation that demonstrates the method; it is not a forecast.** Weather statistics come from ten years of daily records (2016–2025) of a CWA weather station in north-western Taiwan, named on Assumptions and sources, processed by the author (資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務，依政府資料開放授權條款第 1 版使用，經作者加工計算). A short status line under each page's headline says whether weather is applied; the full note and the data source are in small print at the bottom of every page.

Start with the **Start here** page: what is simulated, what the plan says, what the simulated futures say, where the delay comes from, and three what-ifs. The **Summary** page then gives one finding per page, each with a link to the page that explains it. Every page also has a collapsed panel, **How to read this page**, with the explanation for that page. The **English / 中文** switch at the top of this Guide sets the language of the guide, those panels and the metric tooltips; the rest of the app stays in English.

<!-- section: settings -->
## Settings (left sidebar)

Changing a setting does **not** recalculate. Press **Run** to update every page; until then a note under the button says the settings have changed.

| Setting | Meaning |
|---|---|
| Apply weather to the schedule | **Off by default.** Off: weather is shown as warnings only (possible impacts) and does not change any date. On: rain and wind stop weather-sensitive work under the weather parameters. The Late-start cost page always shows both. |
| Weather parameters (collapsed) | Weather table and station; rain stoppage threshold (mm/day); wind warning threshold and wind stoppage threshold (10-min mean, m/s); share of windy spells that stop work; remobilisation days after each wind stop (0–10); gust factor (display only: converts the wind thresholds to gust values). Every option is precomputed from the station record. Each setting's source and verification status is in its tooltip and on Assumptions and sources. |
| Station | The weather station within that table. |
| Delays to test (collapsed) | Days late for the site handover (notice to proceed), the start-of-works approval, each design deliverable (piling, foundation and steel IFC, the overseas maker's certified foundation drawings, the steel shop drawings) and steel fabrication. All are on time by default. Set one or several; the plan keeps its dates and the simulation carries the delays, so every page shows what they cost. |
| Site start (first piling) | Day 0 of the project. |
| Target first-fire date | The date you want to test. Defaults to the single-number plan date. |
| Advanced: Plant | The plant file: activities, deliveries, links and assets. |
| Advanced: Rule pack | The reviews, inspections and permits that apply in a jurisdiction. |
| Advanced: Random seed | Fixes the random futures. The same seed always gives the same results. |
| Advanced: Confidence for latest dates | Share of futures that a "latest acceptable date" must protect (default 80%). |
| Advanced: Late-start experiment | How many weeks of late start to test. |
| Weather parameters: Bad weather comes in spells | On: a lost day makes the next day more likely to be lost, using the mean spell lengths measured at the station. Off: every day is drawn independently. The share of days lost is the same either way. |
| Advanced: Weather stress test | Length of the forced stoppage tested on the Weather risk page (default 7 days). |
| Advanced: Common risks move many items together | On: apply the plant file's common risks, each of which can slow many items at once. Off: every duration varies independently. The Common risks page shows their cost either way. |
| Iterations | Number of simulated futures. The default, 5,000, gives the published figures; fewer runs faster. |

<!-- section: start_here -->
## Start here

The story in five steps, for a first-time reader.

1. **What is being simulated.** A generic single-shaft combined-cycle unit in Taiwan, one unit, utility owner, main equipment from overseas makers. The timeline shows the plan's phases in plain words, from site handover and design, through the turbine hall, the HRSG and the stack (each from piling to E&I or mechanical work), to power receipt and commissioning, which starts at mechanical completion. Bars span the first start to the last finish of each phase.
2. **What the plan says.** The single-number date a typical schedule produces: most-likely durations, deliveries on their planned day, average weather, nothing unexpected.
3. **What the simulated futures say.** The chance that the plan date holds, the date half of the futures reach (P50) and the date 80% reach (P80), with the curve behind them.
4. **Where the delay comes from.** The gap between the plan and the simulated average, split by source: site handover and start approval, design, equipment and materials, permits and inspections, site construction, commissioning, weather (when applied) and common risks. Each bar answers one question: *if only this source went exactly to plan, how much earlier would first fire be on average?* It is measured by re-running the same futures with that source's items as planned (most-likely durations, planned arrivals, no tested delay). The bars add up to less than the whole gap, because late sources compound: first fire waits for whichever converging path is latest, so fixing one source lets another path take over. That remainder is the last bar, **Combined effect (merge bias)**. Then grey is the simulated average, light blue the spread up to P80, and dark the contingency needed. Site handover and design are assumed on time and show 0 until you set a delay under **Delays to test**.
5. **What the analysis supports.** Five actions that follow from the numbers, each with its evidence, a link to the page that shows it and its trade-off: commit to the P80 date rather than the plan date; put mitigation effort on the largest source of delay and the costliest common risk; track the items with the least float against the P80 date (latest dates are computed with the P80 date as the target), including how far design can slip and how late the site can be handed over; use the proposals that win time and skip those that only move risk; protect the site start. They are computed from the current run, so they change with the settings. They show the reasoning on an illustrative plant, not a decision for a real project.
6. **What if.** Three comparisons that are already computed: the site start slips four weeks (for example a late handover or approval), weather is applied, and the costliest common risk is removed.

The page ends with how the numbers are checked, a short note on who built the tool, and links to every page.

The Milestone confidence page splits the same gap by mechanism (late deliveries, skewed durations, merge bias, common risks) for readers who know schedule risk analysis. Both splits end at the same simulated average and P80.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: summary -->
## Summary

The two-minute view. Each card states one finding in one sentence with its key number, and links to the page that explains it:

- **How likely is the plan date?** The chance that the single-number plan holds, its largest cause of delay, and the contingency needed to reach P80.
- **What drives the date?** The item or chain that drives first fire most often, and the share of driving-path links that cannot be broken.
- **What do common risks cost?** How many days risks that slow many items at once add to P80, and what removing the costliest is worth.
- **Can we win time back?** The best single proposal against all proposals together.
- **What is already too late?** The external input or review with the least margin against its latest acceptable date.
- **A late start, without and with weather** (first card, the headline finding): how far first fire moves after a four-week late start with weather off and with weather on. The gap is what weather adds.
- **Weather warnings:** the weather-sensitive activity most exposed in its planned window (strong wind for lifts, heavy rain for civil work), and whether weather is applied to the schedule.
- **What if bad weather stops the site?** The start date at which a forced stoppage of all weather-sensitive work costs first fire the most.

These findings are a simulation that demonstrates the method; they are not a forecast.

<!-- section: confidence -->
## Milestone confidence

**Question:** how likely is first fire on the plan date, and how much contingency does the plan need?

**How the numbers are produced.** The *single-number plan* uses most-likely durations, deliveries on their planned day and average weather: the way a typical P6 schedule produces one date. The simulation then runs the same network many times with durations, deliveries, reviews and weather drawn from their ranges.

**What you see.**

- **Chance of meeting the plan / target:** share of iterations that reach first fire on or before that date; the number under it is the count of futures. A chance of 0% is a real result, not an error: the single-number plan needs every item at its most-likely value at once. The target defaults to the plan date; the target's chance is shown only after you set a different **Target first-fire date** in the sidebar.
- **P50 / P80:** the date by which 50% / 80% of iterations have reached first fire.
- **Contingency needed:** P80 minus the plan date.
- **The curve:** for each date, the share of futures that have reached first fire by then. Vertical lines mark the plan (and target), P50 and P80.

**Why the plan misses (the bar chart).** The single-number plan takes four best cases at once. The chart removes them one at a time, in this order, and shows how many days each moves first fire:

1. **Deliveries arrive late.** The plan puts every delivery on its planned day, but delay ranges start at zero: a delivery can be late, never early. Each delivery is moved to its planned day plus its average delay.
2. **Durations skew late.** The plan uses the most-likely duration, but a job can overrun by more than it can underrun (60 / 75 / 100 days: most likely 75, average 78). Each duration is moved to its average.
3. **Merge bias.** Steps 1 and 2 still give one date from average paths. The simulation averages the *latest* of the converging paths in each future, which is later: first fire waits for whichever path happens to be late. With weather applied, this step also holds the spread of the weather, which the plan replaces by an average loss.
4. **Common risks.** Events that slow many items at once; the single-number plan does not carry them.

Together the four steps take the plan to the **simulated average** (grey). **Spread up to P80** (light blue) is the extra needed to cover 80% of futures instead of the average, and **P80: contingency needed** (dark) is the total. The steps are measured on the same random numbers and add up exactly; the days are rounded so that the steps shown add up to the totals shown. The steps interact, so another order would move a few days between them, never the total. The expander under the chart says what each step means and what a planner can do about it. The common-risks step is how far the risks move the *average*; the Common risks page reports how far they move *P80*, which is more, because risks also widen the spread.

This is also why the chance of meeting the plan can be 0%: the plan needs all four best cases in the same future, and with dozens of items that almost never happens.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: drivers -->
## What drives the date

**Question:** what actually drives first fire?

**How the numbers are produced.** In every iteration, the model traces back from first fire through the predecessor that actually set each item's start: the *driving path* of that future. The **Criticality Index** of an item is the share of iterations in which it is on that path. Unlike a single critical path, it shows that the critical path moves from one future to the next.

**What you see.**

- **Bars:** Criticality Index, highest first, at most ten rows. Colour shows the kind of uncertainty (weather, productivity, supply, review or permit).
- **Merged rows:** items that are always on the driving path together, such as a series chain (piling, then foundations, then steel), share one row labelled "first item … last item (n items)".
- **Click a bar** (or pick an item under the chart) to see what it waits for: each predecessor, the link type, the logic, why the link exists, and how often that link drives it.
- **What the driving path is made of:** share of driving-path links by type. **Hatched bars** are links that cannot be broken (physical and regulatory). The higher their share, the less room the site has to recover time by resequencing.
- **Expanders:** a map of where the risk sits by area and gate, and a table with every item.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: risks -->
## Common risks

**Question:** which risk that moves many items at once costs the most, and what is removing it worth?

**Why they matter.** Each activity's range is drawn independently, so in one future some items run late and others early, and much of it cancels out. Real projects also have *common risks*: one event that slows many items together. A tight labour market slows every construction crew; a shipping disruption delays every major package. Those delays do not cancel, so without them P80 and P90 are too optimistic.

**How the numbers are produced.** Each common risk in the plant file has:

- **Chance it occurs** in a given future (for example 50%).
- **Size when it occurs:** a factor on durations (× 1.00 to 1.25, most likely 1.08) or days added to durations or arrivals.
- **Applies to:** the items it affects, chosen by area, uncertainty type, kind or id.

In each future the risk either occurs or not, and when it does, **every item it applies to gets the same size**. That shared draw is what makes their delays move together. Risks that apply to the same item multiply (factors) or add (days).

**What you see.** Every number re-runs the same simulated futures with risks switched off or on:

- **P80 gain if removed:** how much earlier P80 first fire gets if this risk is eliminated and the others remain. This is what mitigating or insuring against it is worth.
- **P80 added on its own:** what the risk adds when it is the only common risk.
- The two differ, and neither adds up to the total, because risks interact: a delay costs only while its path drives first fire.
- **All common risks:** the total. Risks that can only delay also move P50, not only P80: they add expected delay as well as spread.

**Avoid counting a risk twice.** An activity's range should describe how the work varies when no common risk hits it. If the range already allows for, say, a poor labour market, the productivity risk counts it again.

The shipped risks are illustrative assumptions (grade C) for the method, not estimates for a real project.

<!-- section: recovery -->
## Win time back

**Question:** "Why don't we just start X early?" How much time does each proposal win, and what does it cost?

**How the numbers are produced.** Each *proposal* breaks one soft link (a link that the site, a contract or a change of means could change) and re-runs the **same** simulated futures. Because the random draws are identical (*common random numbers*), any difference comes from the logic change alone.

**What you see.**

- **Drives first fire today:** share of iterations in which that link is on the driving path before the change. A link that rarely drives first fire gains little when broken, because another path takes over.
- **P50 gain (days):** how much earlier P50 first fire becomes.
- **Change in chance:** change in the chance of meeting the target, in percentage points.
- **Cost or risk:** what breaking the link costs. Breaking a link trades schedule risk for another risk; both are shown.
- **Tested, no measurable effect:** proposals that move P50 by less than half a day and the chance by less than 0.1 percentage point. That result is useful too: their cost buys nothing today.
- **All proposals together:** every proposal applied at once. It usually gains more than the best single proposal, because shortening one path lets the next one take over; recovery needs a combination, and the costs add up as well. If even the combination gains little, the lever is outside the site logic: check the latest-dates page.

**What each gain assumes.** A proposal shortens one link and leaves everything upstream as simulated. It assumes that what the earlier work needs (drawings, approvals, materials) is already in place, so the gain is an upper bound. Only the main equipment and the design deliverables are modelled as arrivals, each as one arrival (no partial deliveries); other materials are not modelled. Design is on time by default; under *Delays to test* you can delay a design deliverable and the gains are recalculated with that delay. Design changes and problems found on site are risks, not prerequisites, and are not modelled separately.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: reviews -->
## Reviews and latest dates

**Question:** which reviews apply, and how late can a delivery arrive, a drawing be issued, the site be handed over or an application go in?

**How the numbers are produced.** The rule pack reads each asset's attributes (for example a fixed crane of 3 t or more) and inserts the reviews that apply, each with its legal basis. A backward pass from the target then gives, in every iteration, the latest finish each item can have without pushing first fire past the target.

**What you see.**

- **Latest acceptable date:** the latest finish that still protects the target in the chosen share of futures (default 80%), holding everything else as simulated. For deliveries, design deliverables and the site handover it is the latest arrival or issue. For a review with a planned submission day it is the latest submission (latest finish minus the P80 review time). For other reviews it is the latest completion.
- **Planned or expected:** the planned arrival or submission, or for other reviews the simulated P50 completion.
- **Margin:** latest minus planned or expected. **Negative (red line) means the plan or expectation is already too late** for the target.
- **Grade "A/C":** process grade / duration grade. For example, the process comes from law text (A) and the duration is a practitioner estimate (C).
- **Which reviews apply, and why:** the rule register. Rules pending verification are listed but not inserted into the network.

Note that the target defaults to the single-number plan date, which few futures meet, so many margins are negative by default. Move the target to test a committed date.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: late_start -->
## Late-start cost

**Question:** if the site starts late, does first fire move by the same amount, and how much does weather add?

**How the numbers are produced.** Every site-start activity is delayed by the chosen number of weeks, as if the site handover or the start-of-works approval came late, while deliveries and the calendar stay put. The same simulated futures are re-run for each delay, **twice**: once without weather and once with weather applied (under the weather parameters). This page shows both whatever the switch is set to, because the gap between them is the finding.

**What you see.**

- **Dotted line:** the delay passed through one-for-one.
- **Grey lines, without weather:** never above the dotted line. With fixed durations, a delay can pass through at most one-for-one; float elsewhere absorbs part of it.
- **Blue lines, with weather:** a later start moves weather-sensitive work into other months. Where those months are worse (monsoon wind for lifts, plum rain for civil work), first fire moves further; lines above the dotted line would mean the delay was amplified.
- **The headline:** the P50 shift for a four-week late start, without and with weather.

The result depends on the weather table and on the weather parameters. It is a simulation, not a forecast.

<!-- section: weather -->
## Weather risk

**Questions:** what if bad weather stops the site for a week? And does it matter that bad weather comes in spells?

**The stoppage curve.** Every weather-sensitive activity is stopped for the chosen number of days (default 7, under Advanced) from a given date, on top of the simulated weather, and the same simulated futures are re-run. This is repeated for a start date every two weeks while weather-sensitive work is running.

- **Near zero:** the work running then has float, or none is running. A lost week there costs nothing.
- **Near the dotted line:** the work running then drives first fire; the stoppage passes through.
- **Not exactly the stoppage length:** days the weather had already taken cost nothing extra, and the workable days lost are made up later, in whatever weather comes then, so a single future can lose more or less than the stoppage itself.
- **Futures delayed:** share of futures in which first fire moves at all.

**Warnings, and the switch.** Every page says under its headline whether weather is applied. With the switch off (the default), the tables below are **warnings only**: they show the weather each activity is likely to meet, and no date changes. With the switch on, the rain threshold and the wind stoppage threshold turn those days into lost days.

**Rain and wind.** *Rain:* a day at or above the rain threshold (10 mm by default) is lost for rain-sensitive work, which in the reference plant is civil and outdoor work (piling, foundations, tunnels). Indoor work carries on once the building envelope is closed, so it is not rain-sensitive; on a real site that is usually, not always, true.

*Wind:* strong wind does not always stop work, so there are two thresholds. At or above the **warning threshold** (10 m/s by default) a day is flagged; at or above the **stoppage threshold** (16 m/s by default) it stops wind-limited lifts, but only when weather is applied. The warnings table lists every wind-limited lift (turbine hall steel, roofing and cladding, pipe rack, and HRSG heavy lifts: casing, modules, piggyback panels, drums and steel) with its P50 window, the days of that window in the north-east monsoon season (October to March), and the expected number of days at or above each threshold. With weather applied, the share of windy spells that actually stop work and the remobilisation days after each stop (0–10) set how much the stoppage costs. Spell lengths, with and without remobilisation, come from the station record. Thresholds are on a 10-minute-mean basis at the station anemometer, about 10 m above ground: wind at crane height is stronger, and some daily maxima happen at night. The gust factor converts the thresholds to gust values for display only. The legal basis of both wind thresholds is still to be verified.

**Spells.** With independent days a whole lost week almost never happens (at 25% of days lost, seven in a row has a chance of 0.25⁷, about 1 in 16,000). Real weather comes in spells: a plum-rain front or a monsoon surge lasts several days. The weather table can give, per month, the **mean spell length**: the average number of consecutive lost days. The model then uses a two-state chain: whether a day is lost depends on whether the day before was lost, with the chance tuned so that the long-run share of days lost stays exactly the table value. Spells do not add lost days; they regroup them into runs.

The comparison table runs the same futures with and without spells. A lost week becomes possible where independent days make it almost impossible, and the spread of lost days per month widens. This comparison always applies weather, whatever the switch is set to. How much P80 moves depends on the plant: long weather-sensitive activities average spells out, and work with float absorbs them. The stoppage curve shows when a lost week does bite.

These results are a simulation that demonstrates the method; they are not a forecast.

<!-- section: assumptions -->
## Assumptions and sources

**Question:** where does every number come from?

Every item carries a **source grade**:

- **A:** law text or official data.
- **B:** industry or public documents.
- **C:** explicit assumption or practitioner estimate.

Items added by a rule show two grades, process / duration (for example "A/C"). Weather-sensitive durations are **working days**: a day is lost with the stoppage probability of its month. All other durations are calendar days. The links table lists every link, its type, whether it can be broken, the proposal if broken, and why it exists.

Results built on these inputs are a simulation that demonstrates the method; they are not a forecast.

<!-- section: glossary -->
## Glossary

- **Iteration:** one simulated future of the whole project.
- **Driving path:** in one iteration, the chain of items traced back from first fire through the predecessor that actually set each start.
- **Criticality Index:** share of iterations in which an item is on the driving path.
- **Hard link:** a link that cannot be broken. *Physical*: cause and effect (no heat sink, no vacuum). *Regulatory*: required by law or the grid operator; preparation can start earlier, but the step itself cannot be skipped.
- **Soft link:** a link that can be broken at a cost. *Means can change*: the requirement holds but the means can change (a temporary heavy lift instead of the certified crane). *Contractual*: agreed between parties, negotiable. *Resource or sequence*: a crew, sequence or practice choice. *Logistics or access*: space, access, crane stands, haul routes.
- **Merge bias:** first fire waits for the last of several converging paths, so its date is later than the most likely date of any single path.
- **Common random numbers:** every scenario reuses the same random draws, so differences between scenarios come from the logic change only.
- **Spell:** a run of consecutive days lost to weather. The mean spell length is the average length of those runs; with independent days it is 1 / (1 − share of days lost).
- **Weather switch:** *Apply weather to the schedule*. Off (default): weather is shown as warnings only. On: rain and wind stop weather-sensitive work under the weather parameters.
- **Warning and stoppage thresholds:** wind at or above the warning threshold is flagged; at or above the stoppage threshold it stops wind-limited lifts when weather is applied.
- **Remobilisation days:** days lost after a wind stop to restart work (re-rigging, checks, crew back on the lift).
- **Stoppage test:** a forced loss of every weather-sensitive working day in a window, on top of the simulated weather, to see what a lost week costs at each point of the schedule.
- **Common risk (risk driver):** one event that, when it occurs, slows many items at once by the same factor or number of days, so their delays move together instead of cancelling out.
- **Mechanical completion:** the turbine hall, the HRSG and the stack are built and their E&I is complete, and systems are turned over for commissioning. Every Gate A, B and C item starts after it (and after power receipt). Turning systems over area by area, before all E&I is done, is a proposal on Win time back.
- **Commissioning gates (Gate 0, A, B, C):** the author's own simplified grouping of generic commissioning logic: power receipt, condenser vacuum, gas turbine spin and first-fire items. They are not an industry, code or manufacturer standard, and real projects group and sequence commissioning differently. The model does not force Gate A before Gate B.
- **Notice to proceed (NTP) and site handover:** the owner's release of the site; no site work starts before it.
- **Start-of-works approval:** the approved application to start work on site; piling starts after it.
- **IFC (issued for construction):** a drawing released for building. For steel, IFC is followed by the fabricator's shop drawings and then fabrication, so steel design has to start early.
- **Combined effect (merge bias) on Start here:** what the sources cost together beyond the sum of their own bars. Each bar keeps one source to plan while everything else varies; together they cost more because first fire waits for the latest path.
- **Known limitation:** beyond weather and the common risks in the plant file, activity durations are drawn independently of each other. Dependence that no listed risk captures is not modelled.
