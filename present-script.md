# SentinelID: full presentation script

This is a complete, word-for-word script for the midterm demo. Read the **SAY** blocks aloud, in your own voice. Do the **DO** steps on screen as written. Anything in *italics* is a stage direction, not something to say.

- **Full run time:** about 14 minutes plus questions.
- **5-minute version:** read only the sections marked ✂️ **KEEP**, and use the short lines marked *(short)*.
- Every number below was checked against the saved run and the running dashboard.

---

## Contents

0. Setup and safety checklist
1. Opening and the problem
2. The dataset
3. The pipeline, stage by stage
4. How a behavior becomes numbers (features)
5. The model
6. The research protocol (why you can trust the numbers)
7. The investigation queue
8. Live demo
9. Results
10. Engineering that makes it trustworthy
11. Limitations and next steps
12. Closing
13. Full Q&A answers
14. Glossary
15. Quick-reference numbers

---

## 0. Setup and safety checklist

Run these tonight, and again 15 minutes before you present.

```bash
cd ~/Desktop/openai/prj4
.venv/bin/python -m unittest discover -s tests -q     # expect: Ran 25 tests ... OK
.venv/bin/python -m sentinelid verify                  # expect: model_checksum verified, original_sources present
.venv/bin/python -m sentinelid status                  # expect: completed, cursor 14143645, case_count 31
.venv/bin/python -m sentinelid serve                   # leave running; open http://127.0.0.1:8767/
```

- Always use `.venv/bin/python`. The system Python does not have `joblib`.
- On the dashboard, **Pipeline** must show 14,143,645 records, 18,772 identity-days and 31 investigations.
- Open **Day replay** once before you start. The first load takes a few seconds, then it is cached.
- Open a case (EDB0714) and expand one original record to confirm CSV fields appear.
- Press **P** (or click *Presentation mode*) and check the text is readable on the projector.
- Have `ARCHITECTURE.md` open in a second tab (the diagrams render on GitHub or in a VS Code preview).
- Optional, **only ahead of time** because it hashes about 12 GB: `.venv/bin/python -m sentinelid verify --sources`

**Never do these during the demo:**
- Do not click **Create new run** (under *Advanced* on the Pipeline tab). It switches the dashboard to a fresh run that rebuilds history from May.
- Do not click **Start / resume**. The run is already complete.
- Do not click **Save** on a review unless you call it "presentation feedback". Saving writes a real, permanent review version.

**Safe reset:** Day replay → **Reset** only moves the playback position. It deletes nothing.

**If the server will not start:** the port may be in use. Try `serve --port 8768`, or use the instance that is already running. If it still fails, present from `ARCHITECTURE.md` and `results.json` and skip section 8.

---

## 1. Opening and the problem ✂️ KEEP

*DO: Start on the Pipeline tab, or on a title slide. Say this slowly.*

**SAY:**

> Good morning, everyone. My project is called SentinelID. It is a system that tries to spot suspicious behavior by people who already have legitimate access, and then hands a security analyst a short, explained list of who to look at.
>
> Let me start with why this is hard. In most security incidents involving an insider, or an account that an attacker has taken over, nothing is technically wrong. The password is correct. The person is allowed to use the USB port. They are allowed to open those files and send those emails. A firewall or a login check sees nothing unusual, because the credentials are valid. What is unusual is the behavior: a person who normally plugs in a USB drive once a month suddenly does it every day, or who never emails outside the company suddenly sends large attachments to a new outside address.
>
> The second difficulty is volume. A company produces millions of log events. A security team can investigate only a handful of people a day. So the real question is not "can we find every anomaly?" That would drown the analysts in false alarms. The real question is: **given a fixed number of investigations per day, which identity should the analyst look at first, and what evidence can we show them?**
>
> That framing, ranking under a budget, drives every design decision in this project. SentinelID takes raw activity records, builds a behavioral history for each person, scores how unusual their day is compared with their own past, and then admits at most one investigation per day, each with the original log rows attached so the analyst can check the facts themselves.
>
> One important point before I go on: this is a research prototype built on a public benchmark. I will show promising results, but I will also tell you exactly what those results do not prove.

---

## 2. The dataset

**SAY:**

> The data comes from the CERT Insider Threat Test Dataset, release 4.2, published by the Software Engineering Institute at Carnegie Mellon. It is synthetic. I want to be clear about why. Real insider-threat data, with confirmed ground truth about who was malicious, essentially cannot be obtained, because organizations do not publish it. CERT solves that by simulating a company, generating realistic day-to-day activity for its employees, and then planting known malicious scenarios, such as someone stealing data before leaving the company. Because the planted scenarios are labelled, we can measure whether a detector finds them.
>
> We use five activity logs. **Logon** records when someone logs on or off a computer. **Device** records when a USB drive is connected. **File** records file copies. **Email** records messages, including the recipients, size and attachments. And **HTTP** records web browsing. On top of that, there is a monthly **LDAP** snapshot, which is the company directory. It tells us each person's role and team, for that specific month.
>
> In total, the project processes **14,143,645 events**, covering May 1 through November 30, 2010. The data is split into two non-overlapping pieces: May through mid-October, and mid-October through November. About 12 gigabytes sits on disk.
>
> A few things about how we handle the data are worth mentioning. First, setup downloads from a pinned public mirror, and every file has a recorded checksum and row count, so anyone who runs `setup` gets exactly the same bytes. Second, setup downloads only the date ranges the project needs, and it **never downloads the answer labels**. Third, the dataset's licence restricts redistribution, so the data is not in the Git repository. The repository contains only a manifest of where to get it and what it must look like.
>
> Finally, one subtle design decision: every piece of evidence in the system points back to a specific row in the original file, by its event ID and its byte position. So we never copy or rewrite the data. The original files have to stay byte-for-byte unchanged, and in return, every case can show the analyst the real row.

---

## 3. The pipeline, stage by stage ✂️ KEEP

*DO: Click the **Pipeline** tab. Point at the four counters, then at the six-stage strip.*

**SAY:**

> This is the pipeline view. The four numbers at the top are the totals from the completed run. **14,143,645 original records** were read and committed. From those, **18,772 identity-days** were scored. An identity-day is one person on one calendar day, and it is the unit the model scores. The system ended up admitting **31 investigations**. Notice the funnel: fourteen million events become eighteen thousand scores, which become thirty-one cases. That is a hit rate of about 0.17 percent, which is deliberate, because an analyst cannot read more.
>
> Underneath, there are six stages.
>
> **Stage one, ingest.** The five logs are merged into a single stream in strict time order. If a source ever goes backwards in time, the system rejects it rather than guess. Each person's role and team are taken from the directory snapshot for the same month as the event, never from a later month, so the system never uses future organization information to explain the past. Email attachments are checked against a strict schema.
>
> **Stage two, build history.** For every person, the system accumulates daily counts: how many USB connections, file copies, logons, after-hours logons, external emails, bytes sent, attachments, and web requests. It keeps a rolling window of that history.
>
> **Stage three, score behavior.** On the end of each day, the system compares each person's day against their own past and produces 33 numbers. A pre-trained Random Forest turns those 33 numbers into a single score between zero and one.
>
> **Stage four, apply the gate.** If the score is below a fixed threshold, about 0.4056, nothing happens. The score is still stored for audit, but it creates no candidate.
>
> **Stage five, admit cases.** Candidates that pass the gate compete for a limited number of slots. There is room for one admission per day. The queue merges repeat offers, enforces a cooldown, and expires stale candidates. I will explain that in detail shortly.
>
> **Stage six, inspect evidence.** Every admitted case is saved with its measurements and pointers to the original records, and an analyst can attach a versioned review.
>
> Two details that people often ask about. One: the system runs on dataset time, not the clock on this laptop, so a replay behaves identically whenever you run it. Two: there are also so-called peer features, which compare a person with their team. The system computes them and shows them for inspection, but the model I selected does not use them as inputs.

*(short)* "Fourteen million events become eighteen thousand daily scores, which become thirty-one investigations: one per day at most, each backed by the original log rows."

*Optional: switch to `ARCHITECTURE.md` and show the first flowchart for about 20 seconds, then come back.*

---

## 4. How a behavior becomes numbers (features)

**SAY:**

> The most important idea in the whole project is how we decide that a day is "unusual". We do not compare people to each other. We compare each person to **their own history**.
>
> Take USB use as an example. For one person on one day, we count their USB connections. Then we look at a reference period: the 28 days of that person's history, ending one week before today. For that reference period, we compute the mean and the spread. The unusualness is how far today's count is above the person's own average, measured in units of their normal spread. Concretely, the score is today's count minus the expected count, divided by the larger of three things: one, the person's standard deviation, or the square root of their average. That floor of one stops tiny numbers from producing wild ratios, and we only count increases, because a quiet day is not what we are hunting.
>
> Two choices here matter for trust. The first is the **seven-day lag**: the reference window ends a week before today. That prevents a slowly escalating attacker from contaminating their own baseline. If you steal data gradually, your own recent activity would otherwise make the behavior look normal. The second is that everything is **causal**: each feature uses only information that existed at that moment. Nothing from the future leaks in.
>
> We compute these changes for a set of behaviors. For USB and file copies, we look at one-day, three-day and seven-day windows. We also track how many of the last seven days included USB activity. For logons, after-hours logons, external emails, message size, attachments and web requests, we look at the single day. After-hours means before 7 a.m. or after 7 p.m. External email means any recipient outside the company domain.
>
> Then there are the **novelty** features, seven of them. These ask: is this new? Has the person logged on to a computer they never used before? Did they log on at an hour they have never logged on at, within an hour either side? How many new email recipients, new outside domains and new websites appeared today, and what share of today's activity do they represent?
>
> Now, the model receives each change measurement in two forms. One is the **signed percentile**: where today sits compared with the person's own history, scaled from minus a half to plus a half. It is bounded, so a huge spike and a medium spike can both look maxed out. The other is the **magnitude**: the raw size of the change, put through a logarithm. Magnitude keeps the information that the percentile loses when it saturates. Thirteen percentiles, thirteen magnitudes and seven novelty features give the 33 inputs.
>
> A person is only scored if they are **eligible**. They need at least 41 days of history, at least seven active days in the reference window, and some activity today. That means new accounts and long-idle accounts are not scored, because we cannot judge "unusual" without a baseline. About 918 people are eligible on a typical November day.

---

## 5. The model

**SAY:**

> The scoring model is a **Random Forest**: 100 decision trees, each limited to a depth of eight, with at least three samples per leaf, balanced class weights, and a fixed random seed of 42. It takes those 33 inputs and outputs a number between zero and one.
>
> I want to be precise about that number. It is **not a calibrated probability**. It is the raw output of a class-balanced forest, so it is best read as a ranking score: higher means more like the labelled malicious days the model saw in training. The system uses it to compare candidates, not to claim "this person is ninety-seven percent likely to be malicious."
>
> The forest was trained on **85,688 eligible identity-days** from June 8 through October 14. The model is stored as a single file, and its checksum is recorded in the configuration, so if the file ever changes, the system refuses to start.
>
> If we ask which inputs the forest relies on most, web activity stands out: the percentile and magnitude of the single-day HTTP change together carry about a third of the total importance. USB activity follows, across its one-day, three-day and seven-day windows. That is a useful sanity check: the planted scenarios in this dataset involve unusual web browsing and removable media, and the model has found those signals. But it is a statement about the forest overall. **The system does not tell you which individual event drove a particular score.** It shows the aggregate measurements and the real records, and leaves the interpretation to the analyst.
>
> I compared this model with an **Isolation Forest**, which is an unsupervised method. It looks for days that are statistically rare, without being told what malicious behavior looks like. It uses no labels at all, which makes it a natural baseline. I will show that comparison in a moment.

---

## 6. The research protocol (why you can trust the numbers) ✂️ KEEP

**SAY:**

> A model can look excellent if it has secretly seen the test data, so I want to explain the order of events.
>
> The work was done in chronological stages. First, two earlier **development blocks** were used to choose the feature representation, the score threshold and the queue policy. Second, the final model was **fitted** on June 8 to October 14. Third, from October 15 to 21 we ran a **label-free calibration check** on the threshold, which gave us diagnostics but was not the deployed threshold. Fourth, everything was **frozen**: the model, the threshold, and the queue rules. And only then did we score **November 1 to 30**, followed by a short queue drain.
>
> November was therefore evaluated exactly once, after the freeze. We never tuned on it. The success criteria were also written down before looking at the outcome, and I will come back to that, because it changes how I describe the result.
>
> The threshold that is actually deployed, about 0.4056, comes from the development phase, specifically the score level selected on the fitting data. The label-free alternatives were evaluated, but not chosen.
>
> All the earlier work, the training code, the rule-based detectors, the simulations, is preserved in a verified recovery archive of 1,313 files. The live application contains the operational half: replay, scoring, the queue, storage and the dashboard.

---

## 7. The investigation queue

**SAY:**

> Scoring alone does not produce investigations. If we opened a case for every score above the threshold, an analyst would be buried. So the second half of the system is a queue with a hard budget.
>
> Here are the rules. Each morning at 8 a.m., the system looks at the candidates waiting and admits **at most one**: the one with the highest score. That is the budget.
>
> Then there are three behaviors that keep the queue sensible. **Merging**: if the same person is flagged again while they are still waiting, we do not create a second candidate. We merge the new evidence into the existing one and keep the highest score. **Cooldown**: after we admit a person, any further candidates for them are suppressed for seven days, so one persistent person does not consume the analyst's attention every morning. **Expiry**: a candidate that has waited more than three days is dropped, because stale information is not worth an investigation slot.
>
> That budget has a real cost, and I will show it to you in the demo. When many people are flagged on the same day, only one gets the slot, and some of the others expire before their turn. That is a tradeoff between analyst workload and coverage, and the system makes the tradeoff visible instead of hiding it.

---

## 8. Live demo ✂️ KEEP

*DO: Switch to the browser. Make sure Presentation mode is on. Start on the **Day replay** tab.*

### 8.1 Introduce the playback

**SAY:**

> What you are about to see is a day-by-day replay of the real November run. I want to be exact about what that means. It is a **recorded-run playback**. It reads the scores and the queue decisions that the actual run already saved. It does not rescore anything, it does not insert fake events, and it does not write to the database. And when it loads, it rebuilds the queue from the recorded decisions and **checks that the result matches the stored queue**. If they disagreed, it would refuse to play.

*DO: Click **Reset**.*

### 8.2 November 1

*DO: Look at the first step (November 1).*

**SAY:**

> This is November 1. **918 identity-days** were eligible and scored. **Six** of them scored above the gate. The budget allows one admission, so the highest score wins: that is **EDB0714**, with a score of **0.9732**. The other five stay in the queue, waiting.
>
> Notice the decision is made at 8 a.m. the next morning, which is the standard decision time, so this admission is timestamped November 2.

*DO: Click **Next day →**.*

### 8.3 November 2

**SAY:**

> Now it is November 2. Nine identity-days passed the gate this time. Look at the decision trace. **EDB0714 appears again, with a high score, but it is suppressed. That is the cooldown.** We just opened a case on this person, so we do not open another one for seven days. **Two** new offers were merged into candidates that were already waiting, instead of creating duplicates. And **IUB0565** was admitted, with a score of 0.9427. Ten candidates are now waiting.

*DO: Click **Next day →** twice to reach November 4.*

### 8.4 November 4

**SAY:**

> Here is the cost of the budget. On November 4, **five candidates expired**. They had been waiting for more than three days, and they never got a slot. Twelve are still waiting, and **AAM0658** was admitted. This is exactly the tradeoff I described: a single daily slot protects the analyst, but some flagged people never get reviewed.

### 8.5 Play it through

*DO: Set **Pace** to 1s / day, click **Play**, let it run for about five seconds, and click **Pause**. Then drag the slider to the end.*

**SAY:**

> Played at speed, this is the whole month. Each frame shows the day's scoring, the offers that passed the gate, who is waiting, what the queue decided, and who was admitted. After November 30, there are **three extra steps** labelled drain, where the queue empties out without new scoring. By the final step, the running total is **31 admissions**. And remember: **Reset is read-only.** It just moves the display back to the start.

### 8.6 Open a case

*DO: Click **Reset**, then go to the **Pipeline** tab and click **Inspect EDB0714**. The drawer opens.*

**SAY:**

> Now let's look at the first case in detail. This is the investigation for EDB0714. There are four views.
>
> **Decision.** The score was 0.9732, against a gate of 0.4056. The scoring day was November 1, and it was admitted on November 2 at 8 a.m.

*DO: Click **Measurements**.*

> **Measurements.** This is the part I care most about, because it makes the score auditable. You can see the raw counts for the day, the person's own reference statistics from their lagged 28-day window, the signed percentiles, and the exact 33-value vector that went into the forest. An analyst does not have to trust the score. They can see the inputs.

*DO: Click **Original records**. Expand one record.*

> **Original records.** This case carries **115 retained records**: the events from the scoring day, plus the previous week of context. Each one is marked as either from the current scoring period or prior context. Let me open one. This is the actual row from the source CSV, with its event ID and its byte position in the file. The system re-checks the event ID when it reads the row, so it cannot point at the wrong line.
>
> I want to be careful about one claim. We show the aggregate measurements and the real records. We do **not** claim to know which of these 115 events made the forest raise its score. Exact event-level attribution is not computed.

*DO: Click **Review history**.*

> **Review history.** Analysts can record a status and a disposition, with a note. Every save creates a new version, and a stale edit is rejected, so two analysts cannot silently overwrite each other. This is feedback storage. It does not retrain the model. Also, the note on this particular case is an engineering quality-assurance note, not a finding that anyone was an attacker.

*DO: Do **not** click Save. Close the drawer.*

### 8.7 The same person, four times

*DO: Click the **Investigations** tab. Type `EDB0714` in the search box.*

**SAY:**

> One more interesting thing. Search for this person and you will see **four cases**: November 2, November 9, November 17 and November 25. Each one comes after the seven-day cooldown ended, and the supporting evidence grows from 115 records to 154. So this is not a one-off spike. It is a person whose behavior keeps standing out, and the queue handled that gracefully: one slot at a time, never flooding the analyst.
>
> The full list holds 31 cases. You can filter by review status. A fresh run starts every case as "new".

---

## 9. Results ✂️ KEEP

*DO: Click the **Benchmark results** tab.*

**SAY:**

> This tab shows the saved evaluation of the frozen November run, with the Random Forest against the Isolation Forest, at the same operating point: the same gate rule, the same queue policy, and the same one-admission-per-day budget.
>
> The Random Forest produced **31 investigations**. Of those, **21 contained a labelled malicious record in the period that triggered the case**, which is what we call "current-positive". That is a yield of about **68 percent**. With context included, 23 were positive. And it reached **9 of the 11 incidents** in time, meaning a relevant malicious record was admitted within 72 hours of that record.
>
> The Isolation Forest produced 30 investigations. Only **3** were current-positive, a yield of **10 percent**, and it reached **2 of the 11** incidents.
>
> So with one investigation a day, the supervised forest filled most of its slots with cases that really contained malicious activity, while the unsupervised baseline mostly did not.
>
> I also computed uncertainty. By resampling the 11 incident actors 2,000 times, the difference in timely coverage between the two systems is **0.64, with a 95 percent interval from 0.36 to 0.91**. That interval stays well above zero. But I want to flag that this is descriptive: it is one fixed detector, one calendar month, and it does not include the uncertainty from training or model selection.
>
> **Now the most important point of the presentation.** The official verdict stored with these results is: **"unchanged: improvement not established."**
>
> Why, if the numbers look so good? Because before looking at the result, I wrote down what would count as an improvement. The rule required that the new system cost *no more* investigations than the comparator, reach more incidents, have no lower yield, and have a confidence interval that excludes zero. The Random Forest used **31 investigations against 30**. It used one more. By the rule I set myself, it fails the cost condition.
>
> There are three more reasons for caution. The Random Forest **uses labels** in training and the Isolation Forest does not, so this is a comparison of two operational systems, not a proof that one method is better. **Two of the validation incidents also recur in the fitting data**, so the model may have seen similar patterns. And the data is **synthetic**, so these results say nothing yet about real organizations or about people the model has never seen.
>
> I also want to explain what "9 out of 11" means and does not mean. It is **incident coverage** under a timing rule. It is not classification accuracy. And it does not necessarily mean the incident was caught within 72 hours of its start; it means an admitted case contained a relevant malicious record within 72 hours of that record.
>
> I would rather say "promising, not established" than move the goalposts after the fact.

*(short)* "The Random Forest reached nine of eleven incidents with a 68 percent yield, against two of eleven and ten percent for the baseline. But it used one more investigation than my predeclared rule allowed, it uses labels, and the data is synthetic, so I report improvement as not established."

---

## 10. Engineering that makes it trustworthy

**SAY:**

> A few engineering decisions are worth a minute, because they make the results reproducible.
>
> **Atomic checkpoints.** A full replay takes a long time. So the system saves its work in batches. The scores, the cases and the position in the data are all written in a single database transaction. If the process crashes halfway through a batch, the batch is rolled back, and a restart continues from the last committed point. There is no half-written state.
>
> **One writer at a time.** A file lock prevents two processes from writing to the same run. And the run records a fingerprint of the configuration, so you cannot resume a run after changing the settings and silently mix results from two different experiments.
>
> **Immutable cases.** Once a case is admitted, it never changes. Analyst feedback is stored in a separate, append-only table with version numbers.
>
> **Deterministic queue.** Case identifiers are hashes, and ties between equal scores are broken in a fixed order, so running the replay again gives the same cases.
>
> **Self-checking playback.** As I mentioned, the day replay verifies that its reconstruction matches the stored queue.
>
> **A small footprint.** The whole thing is roughly 3,400 lines: a standard-library web server, SQLite, plain JavaScript, and 25 unit tests that run without the dataset. The continuous-integration workflow runs those tests on every push.

---

## 11. Limitations and next steps ✂️ KEEP

**SAY:**

> I want to be upfront about the limits.
>
> **The data is synthetic.** It has one month of evaluation and 11 incident actors. That is a small sample, and nothing here establishes how it would do on a real company or on people the model never saw.
>
> **The budget loses candidates.** As the replay showed, some flagged people expire before they reach the front of the queue.
>
> **There is no event-level explanation.** We show aggregates and the real records. We do not say which event drove the score.
>
> **There is a known defect that I kept on purpose.** The three-day USB and copy magnitude features were built using a slightly different time window from their matching percentile features. I documented it and kept it in the frozen model so that the saved results stay reproducible. A corrected version was trained separately on an experimental branch, and was not deployed.
>
> **It is a local prototype.** There is no login, no connection to a live identity system, and the saved state uses Python serialization, so it should only be loaded from a trusted source. Also, analyst feedback is stored, but it does not feed back into the model.
>
> **Next steps.** First, an independent evaluation on different time periods and different people, because that is what would really settle the question. Second, monitoring of source quality, so the system notices when a log feed goes silent. Third, faster replay resume, because today a restart rescans the data file. And fourth, better admission and evidence refresh, to reduce the candidates lost to expiry.

---

## 12. Closing ✂️ KEEP

**SAY:**

> To summarize. SentinelID takes fourteen million raw activity records and turns them into thirty-one investigations that are scored against each person's own history, limited by a realistic daily budget, backed by the original log rows, and open to analyst review. The pipeline is checkpointed, repeatable and auditable. The results are encouraging: the Random Forest reached nine of eleven planted incidents where the baseline reached two. But I have deliberately reported them as *not yet established*, because the cost rule was missed by one investigation, the data is synthetic, and independent validation is still needed.
>
> Thank you. I am happy to take questions.

---

## 13. Full Q&A answers

**Q: Is the Random Forest actually better than the Isolation Forest?**
> On this benchmark, it reached far more incidents, nine against two out of eleven, with a much higher yield. But I defined success in advance, and one requirement was that it not cost more investigations. It cost one more, 31 against 30. It also uses training labels while the Isolation Forest does not, and two validation incidents recur in the fitting data. So the honest statement is that it is promising and the improvement is not established.

**Q: Is 9 out of 11 the accuracy?**
> No. Accuracy is a classification measure. Nine out of eleven is incident coverage: an incident counts if a relevant malicious record was admitted within 72 hours of that record. Yield, which is 21 of 31, uses a different denominator, the investigations.

**Q: Did you use November's labels or future data in the model?**
> No. The features are lagged and causal, so they only use what was known at the time. The Random Forest was fitted on labels from before the freeze. November outcomes appear only in the saved results file, which the dashboard displays separately and does not feed back into scoring.

**Q: Why is the gate 0.4056 and not a calibrated value?**
> That threshold was selected during the earlier development phase from the fitting data. I also evaluated label-free alternatives from the October calibration week, and they are recorded in the model file, but I did not deploy them. Choosing a different gate now, after seeing November, would be tuning on the test set.

**Q: Why only one investigation a day?**
> It models a fixed analyst workload. It is also the main cost of the system, because candidates that wait more than three days expire. The playback shows five expiring on November 4, for example.

**Q: Why compute peer features if the model does not use them?**
> They are retained for inspection and audit, and they were explored in the research phase. The selected model uses only the 33 personal-history inputs.

**Q: Which behaviors does the model rely on?**
> Web activity, in both its percentile and magnitude forms, carries about a third of the model's importance. USB activity is next. That fits the planted scenarios, but it is an overall property of the forest. We do not compute event-level attribution for a single prediction.

**Q: Can a run be stopped and resumed?**
> Yes. Outputs and the checkpoint are saved in one transaction, so a restart picks up from the last committed batch. The unit tests check rollback and persistence, and a resume on the real data was checked during consolidation. Today's demo uses the completed run and does not do a fresh replay.

**Q: What does Reset do in the playback?**
> It only changes which day is displayed. It does not delete cases, create a run, or write anything.

**Q: Where are training, the rule-based detectors, and the simulations?**
> They are in a verified recovery archive of 1,313 files, which can be extracted separately, and corrected experiments are on the experimental branch. The live application deliberately uses the frozen baseline so the saved results stay reproducible.

**Q: Why does it only work on Linux?**
> Replay uses a POSIX file lock to guarantee a single writer. On Windows, run it inside WSL.

**Q: Can I run it myself?**
> Install the pinned dependencies from `requirements.txt` with Python 3.14, then run `setup --accept-data-license`. That downloads about 7 GB and needs about 15 GB free. Then `verify --sources`, `replay`, which is long but resumable, and `serve`. The unit tests need none of the data.

**Q: What would it take to be production-ready?**
> Independent validation on other data, live connectors to real log and identity systems, source-quality monitoring, authentication, faster replay seeking, and replacing the Python-serialized checkpoints with a safer format. It also needs a measurement of real analyst effort, because investigations are only a stand-in for cost here.

**Q: Why not just use anomaly detection and raise an alert for every anomaly?**
> Because an analyst can only review a few cases a day. Without a budget, the output would be an unusable flood. Treating it as ranking under a budget forces the system to prioritize and to make the cost of that prioritization visible.

**Q: Why does the same person show up four times?**
> After each seven-day cooldown, EDB0714 kept scoring high, and the evidence grew from 115 to 154 records. The queue admits them again only when the cooldown ends, which is the intended behavior for a persistent actor.

**Q: Is the dataset real?**
> No, it is synthetic, generated by CMU's Software Engineering Institute. The malicious scenarios are planted and labelled, which is why we can measure detection. The cost is that it may be easier or simpler than real organizations.

---

## 14. Glossary

| Term | Meaning |
| --- | --- |
| **Identity-day** | One person on one calendar day. This is the unit the model scores. |
| **Eligible** | The person has at least 41 days of history, at least 7 active reference days, and activity today. Otherwise they are not scored. |
| **Reference window** | The 28 days of a person's own history, ending 7 days before the scoring day. |
| **Lag** | The 7-day gap between the reference window and today, so recent behavior cannot hide a slow escalation. |
| **Causal** | A feature uses only information available at that time. No future data leaks in. |
| **Signed percentile** | Where today ranks against the person's own history, from −0.5 to +0.5. It keeps direction. |
| **Magnitude** | The raw size of a change (log-scaled). It keeps detail when percentiles saturate. |
| **Novelty feature** | A measure of something new: a new computer, hour, recipient, domain or website. |
| **Random Forest** | 100 depth-limited decision trees voting on a score. The selected supervised model. |
| **Isolation Forest** | An unsupervised method that scores how statistically rare a day is. The baseline here. |
| **Score** | The Random Forest output. It is a ranking number, **not** a calibrated probability. |
| **Gate** | The fixed score threshold (about 0.4056). Scores below it create no candidate. |
| **Candidate** | An identity-day that passed the gate and is waiting in the queue. |
| **Budget** | At most one admission per day, decided at 08:00 the next morning. |
| **Merging** | A repeat offer for a waiting person is combined into the existing candidate, keeping the highest score. |
| **Cooldown** | For 7 days after admission, new candidates for that person are suppressed. |
| **Expiry** | A candidate waiting more than 3 days is dropped. |
| **Drain** | Three extra decision days after November, so the queue can empty. |
| **Investigation / case** | An admitted candidate, saved with its measurements and evidence. One admission is not one incident. |
| **Evidence pointer** | The CSV file, byte offset, row number and event ID of an original record. |
| **Current-positive** | A labelled malicious record appears in the case's trigger period. |
| **Context-positive** | A labelled malicious record appears in the trigger period or the retained context. |
| **Yield** | Current-positive investigations divided by all investigations. |
| **Timely incident** | A relevant malicious record is admitted within 72 hours of that record. It is coverage, not accuracy. |
| **Frozen** | The model, gate and policy were fixed before November was scored. |
| **Checkpoint** | A saved snapshot (cursor, history, queue) committed atomically with the outputs. |
| **LDAP** | The company directory snapshot, giving role and team for each month. |
| **CERT r4.2** | The synthetic insider-threat benchmark from CMU's Software Engineering Institute. |

---

## 15. Quick-reference numbers

| Fact | Value |
| --- | --- |
| Original events processed | **14,143,645** |
| Date coverage | May 1 – Nov 30, 2010 |
| Activity sources | 5 (logon, device, file, email, http) + monthly LDAP |
| Scored identity-days | **18,772** (about 918 per day) |
| Scoring period | Nov 1–30, 2010, then 3 drain days |
| Investigations admitted | **31** |
| Model | Random Forest, 100 trees, depth 8, min leaf 3, seed 42 |
| Model inputs | **33** (13 percentile + 13 magnitude + 7 novelty) |
| Training rows | 85,688 eligible rows (Jun 8 – Oct 14) |
| Gate | ≈ **0.4056** (0.40562760…) |
| Queue | 1 admission/day at 08:00, 7-day cooldown, 3-day expiry |
| RF results | 31 investigations · 21 current-positive · 23 context-positive · **9 of 11** timely |
| IF results | 30 investigations · 3 current-positive · 5 context-positive · **2 of 11** timely |
| RF / IF yield | **67.7%** / **10%** |
| Timely coverage difference | 0.64, 95% CI [0.36, 0.91] (11 actors, 2,000 draws) |
| Verdict | **Unchanged: improvement not established** |
| Example case | EDB0714: score 0.9732, admitted Nov 2 08:00, 115 retained records; admitted again Nov 9, 17, 25 |
| Nov 1 | 918 scored · 6 above gate · EDB0714 admitted · 5 waiting |
| Nov 2 | 9 above gate · IUB0565 admitted · 2 merged · 1 cooldown · 10 waiting |
| Nov 4 | 5 expired · AAM0658 admitted · 12 waiting |
| Playback | 33 steps (30 scoring days + 3 drain) · 31 cumulative admissions |
| Unit tests | 25, all passing, no dataset needed |
| Recovery archive | 1,313 files, SHA-256 `05de10fc…9684f` |
