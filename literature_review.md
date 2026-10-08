# SentinelID: literature review and research positioning

Prepared October 7, 2026. Scope: the current rolled-back application in `/home/dividh/Desktop/openai/prj4`, rather than the optional-module experiments previously discussed.

## 1. Purpose and current project boundary

This review selects ten principal papers spanning data, behavioral context, anomaly detection, supervised detection, temporal/graph learning, analyst interaction and evaluation. An additional foundational Random Forest reference supports the deployed algorithm. The selection is a focused narrative review, not a systematic or exhaustive survey.

SentinelID currently replays five CERT r4.2 sources chronologically, constructs eligible identity-day measurements, scores a frozen Random Forest, and admits evidence-backed cases through a threshold, merging, budget, cooldown and expiry policy. It retains resumable operational state, original-record pointers and versioned reviews. Its 33 deployed inputs combine personal percentiles, change magnitudes and novelty. Peer measurements support inspection, not deployed scoring. The application does not currently implement learned relevance ranking, neural/graph detection or feedback-driven retraining.

The current saved November comparison is RF: 31 investigations, 21 current-positive, 23 context-positive, 9/11 timely incidents; historical C_IF: 30, 3, 5, 2/11. Formal matched-cost improvement remains unestablished. November is consumed, CERT is synthetic, and two validation incidents recur in fitting. The known three-day magnitude chronology defect remains in the preserved deployed contract. These limitations belong in the methodology and discussion rather than being omitted from the literature positioning. Local evidence: [README](/home/dividh/Desktop/openai/prj4/README.md), [configuration](/home/dividh/Desktop/openai/prj4/config.json), [results](/home/dividh/Desktop/openai/prj4/results.json).

## 2. Selection map

| Ref. | Paper | Principal use in this project | Comparison status |
| --- | --- | --- | --- |
| [1] | Glasser & Lindauer, 2013 | Dataset rationale and realism limits | Data foundation |
| [2] | Eldardiry et al., 2013 | Peer-relative change and cross-domain context | Conceptual comparator; different data/protocol |
| [3] | Liu, Ting & Zhou, 2008 | Isolation Forest mechanism | Implemented algorithm family; original paper is not a CERT benchmark |
| [4] | Le, Zincir-Heywood & Heywood, 2020 | Supervised workflow, granularity and delays | Candidate implementation baseline |
| [5] | Le & Zincir-Heywood, 2021 | Unsupervised representations, ensembles and budgets | Closest candidate unsupervised baseline |
| [6] | Tuor et al., 2017 | Online temporal learning and analyst explanations | Future method baseline; CERT release differs |
| [7] | Cai et al., 2024, LAN | Graph/sequence modeling and hybrid learning | Future method baseline; scoring unit differs |
| [8] | Das et al., 2016 | Feedback-guided anomaly discovery | Future ranking/feedback baseline |
| [9] | Arp et al., 2022 | Security-ML validity and operational evaluation | Methodological reference |
| [10] | Saito & Rehmsmeier, 2015 | Imbalance-aware evaluation | Metric reference |

No published headline result in this table is presently a controlled numerical comparison with SentinelID. “Candidate baseline” means suitable for a future reproduction or clearly named adaptation under a shared protocol.

## 3. Critical review of the ten papers

### [1] Glasser and Lindauer (2013): data generation and its limits

Joshua Glasser and Brian Lindauer. **Bridging the Gap: A Pragmatic Approach to Generating Insider Threat Data.** IEEE Security and Privacy Workshops, pp. 98–104. DOI: 10.1109/SPW.2013.37. [Conference paper](https://www.ieee-security.org/TC/SPW2013/papers/data/5017a098.pdf).

The authors explain synthetic insider data generation and the tradeoff between controllable ground truth and realistic human behavior. Their central caution is that detecting generator-defined anomalies does not establish that the same behavior indicates malicious intent in a real organization.

**Relation to SentinelID:** this is the primary justification for using CERT while limiting generalization claims. Replaying original benchmark records preserves their provenance; it does not make them real organizational telemetry. The project can demonstrate engineering correctness and benchmark detection without claiming production validity. This paper supplies a limitation we inherit, not a weakness we have overcome.

### [2] Eldardiry et al. (2013): peer context and multi-domain inconsistency

Hoda Eldardiry, Evgeniy Bart, Juan Liu, John Hanley, Bob Price and Oliver Brdiczka. **Multi-Domain Information Fusion for Insider Threat Detection.** IEEE Security and Privacy Workshops. DOI: 10.1109/SPW.2013.14. [Conference paper](https://www.ieee-security.org/TC/SPW2013/papers/data/5017a045.pdf).

This work combines behavioral domains, learns peer groups through clustering, and models unusual changes using cluster transitions. It evaluates synthetic data and real organizational background data, both containing injected anomalies. Its peer-relative approach distinguishes a change unusual for a person's peers from a change that accompanies ordinary work transitions.

**Relation to SentinelID:** organizational peer comparison and domain fusion have established precedent. Our team/role grouping is inspectable but is not equivalent to learned behavioral peers. The real-background experiment is a useful realism reference, although injected attacks are not confirmed naturally occurring incidents. Any future reproduction requires access to compatible data and an explicit grouping protocol.

### [3] Liu, Ting and Zhou (2008): Isolation Forest

Fei Tony Liu, Kai Ming Ting and Zhi-Hua Zhou. **Isolation Forest.** ICDM, pp. 413–422. DOI: 10.1109/ICDM.2008.17. [Author-hosted paper](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf).

Isolation Forest identifies observations that require shorter average paths through randomly partitioned trees. The original evaluation studies anomaly detection and computation across benchmark datasets; it is not evidence of CERT insider detection performance.

**Relation to SentinelID:** IF is a legitimate label-free algorithm baseline. Our results test whether isolation scores produce useful cases after feature construction and queue admission. Poor outcomes in this implementation do not invalidate IF universally. Large negative-labelled changes can still be statistically unusual; the gap between anomaly and malicious relevance must be evaluated rather than assumed away. The deployed application currently uses RF, while IF results remain a historical comparison.

### [4] Le, Zincir-Heywood and Heywood (2020): supervised detection at different granularities

Duc C. Le, Nur Zincir-Heywood and Malcolm I. Heywood. **Analyzing Data Granularity Levels for Insider Threat Detection Using Machine Learning.** IEEE TNSM 17(1), pp. 30–44. DOI: 10.1109/TNSM.2020.2967721. [Author manuscript](https://web.cs.dal.ca/~lcd/pubs/TNSM2020.pdf).

The study compares LR, RF, neural networks and XGBoost across temporal granularities. Its main restricted-label setting uses CERT r5.2, with further cross-version analysis. It reports instance/user outcomes, scenario breakdowns and delays, including selected outcomes of up to 85% malicious-user detection at 0.78% FPR. These are setting-specific results, not a single universal operating point.

**Relation to SentinelID:** this is a close supervised workflow reference and a useful RF baseline candidate. It already goes beyond accuracy and random-split classification. Our additional question is how scores interact with a causal case queue. Its user detection percentage cannot be compared directly with our timely incident reach.

### [5] Le and Zincir-Heywood (2021): historical representations and unsupervised ensembles

Duc C. Le and Nur Zincir-Heywood. **Anomaly Detection for Insider Threats Using Unsupervised Ensembles.** IEEE TNSM 18(2), pp. 1152–1164. DOI: 10.1109/TNSM.2021.3071928. [Author manuscript](https://web.cs.dal.ca/~lcd/pubs/TNSM2021.pdf).

This study evaluates autoencoders, IF, LODA and LOF using temporal representations including percentiles and differences, ensemble schemes, and investigation-budget curves. It covers CERT and additional datasets. Its abstract reports 60% malicious-user detection at a 0.1% investigation budget in its evaluated settings; budgeted sample selection is not a causal case queue.

**Relation to SentinelID:** this is the closest reference for our unsupervised research and historical behavioral representation. Percentiles and change encoding are prior ideas, not our invention. Future comparison should reconstruct a declared representation and scoring protocol before routing it through the same queue. Different label units, users, periods and budget definitions prevent direct headline comparison.

### [6] Tuor et al. (2017): online unsupervised temporal modeling

Aaron Tuor, Samuel Kaplan, Brian Hutchinson, Nicole Nichols and Sean Robinson. **Deep Learning for Unsupervised Insider Threat Detection in Structured Cybersecurity Data Streams.** 2017. [Author paper](https://fw.cs.wwu.edu/~hutchib2/papers/aics17_insiderthreat.pdf); [arXiv record](https://arxiv.org/abs/1710.00811).

The authors model structured daily activity with deep and recurrent networks, score departures from predicted behavior, and decompose scores into feature contributions. Their CERT v6.2 evaluation uses a chronological development/test division. The best model's labelled threat activity has a mean anomaly percentile of 95.53; this is neither 95.53% recall nor investigation precision.

**Relation to SentinelID:** daily modeling, online processing and analyst-oriented explanations already exist in the literature. Our evidence pointers and measurement views provide traceability, but do not constitute neural-style feature attribution. A future temporal model should compete with the frozen scorer under the same evidence and admission policy, with its training-label access specified.

### [7] Cai et al. (2024): LAN, sequence/graph learning and hybrid supervision

Xiangrui Cai, Yang Wang, Sihan Xu, Hao Li, Ying Zhang, Zheli Liu and Xiaojie Yuan. **LAN: Learning Adaptive Neighbors for Real-Time Insider Threat Detection.** arXiv:2403.09209, version 2. [Full manuscript](https://arxiv.org/html/2403.09209v2). This review cites the arXiv manuscript, without asserting a separate publication venue.

LAN combines activity sequences, learned graph relationships and hybrid self-supervised/supervised learning. It trains/validates on 2010 activity and tests on January–June 2011. On r4.2, its real-time table reports AUC 0.9369 and DR@5% 0.6832. That budget concerns activities; a separate post-hoc configuration has different results.

**Relation to SentinelID:** it motivates later relational or sequence modules. Our daily next-morning decisions have different latency from activity-level detection. The paper explicitly considers investigation budgets, so claiming it ignores workload would be inaccurate. A future adaptation needs event-to-case mapping and causal graph construction before numerical comparison.

### [8] Das et al. (2016): analyst feedback and discovery under budget

Shubhomoy Das, Weng-Keen Wong, Thomas Dietterich, Alan Fern and Andrew Emmott. **Incorporating Expert Feedback into Active Anomaly Discovery.** ICDM. [Author paper](https://web.engr.oregonstate.edu/~tgd/publications/das-wong-dietterich-fern-emmott-incorporating-expert-feedback-into-active-anomaly-discovery-icdm2016.pdf).

Active Anomaly Discovery adjusts ensemble scoring using expert feedback and evaluates anomalies found during a limited number of queries. The studied implementation uses LODA and generic anomaly datasets. Budget-aware discovery is therefore an established research objective, not a novel consequence of our pipeline.

**Relation to SentinelID:** versioned reviews provide an engineering starting point, but the current application stores feedback without learning from it. Future comparison must charge each queried case, distinguish unreviewed from benign, and respect verdict availability. A retrospectively trained relevance model would not automatically reproduce interactive AAD. Discovery gains must be measured through the feedback loop.

### [9] Arp et al. (2022): research validity in security machine learning