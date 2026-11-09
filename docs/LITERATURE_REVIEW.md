# Literature review and research gap

**Method.** Retrieval was scripted (`scripts/literature_search.py`) against PubMed through the NCBI
E-utilities API. Queries, hit counts and retrieved PMIDs are in `docs/literature/search_log.json`; the
full records (title, authors, journal, year, DOI, abstract) are in `docs/literature/records.json`
(364 unique records, retrieved 2026-11-05). Every work cited below is in that file and was assessed
**from its abstract only**; full texts were not read. The general web-search tool was unavailable
in this session.

**Coverage limit.** PubMed indexes only part of the engineering literature (e.g. *Journal of Aerosol
Science*, *Physics of Fluids*, *Powder Technology* are incompletely covered). The gap statement at
the end is therefore *"not found in the retrieved records"*, not a claim that no such work exists. Before
writing the manuscript, the research team should repeat the key searches in Scopus or Web of Science
and Google Scholar, and read the full texts of the closest works (marked ★).

## 1. Closest prior work

| Work (PMID) | What it does | Overlap with this project |
|---|---|---|
| ★ Ostrovski, Dorfman, Mezhericher, Kassinos et al. 2019, *Flow Turbul. Combust.* 102:73 (30956537) | In silico CFD, multi-generation airway tree. A short pulsed aerosol bolus is released; the clean-air volume inhaled behind it is tracked to set the depth reached ("Inhaled Volume Tracking"), followed by a breath hold. Particle size 1–10 µm. | **Release timing chosen by inhaled volume** is established. |
| ★ Heller-Algazi, Nof, Das, Bhardwaj et al. 2020, *Clin. Biomech.* 80:105138 (32798812) | "In silico optimization" of the Inhaled Volume Tracking manoeuvre for upper-airway targeting, 1–40 µm, upright and supine. | **CFD-based optimization of pulse timing and particle size** for regional targeting is established (single manoeuvre, per their abstract). |
| ★ Poorbahrami, Mummy, Fain, Oakes 2019, *J. Appl. Physiol.* 127:1720 (31513445) | Patient-specific CFD (2 healthy, 4 asthmatic). Particles released throughout inhalation; each particle's release time is recorded with its fate. Releasing during fast vs slow inhalation shifts central vs peripheral deposition. | **Release-time → fate mapping from a continuous-release run** has been used, as analysis. |
| ★ Farghadan, Coletti, Arzani 2019, *Comput. Biol. Med.* 115:103497 (31630028) | Patient-specific unsteady CFD. A "destination map" connects each particle's final location to its initial location **and injection time**; Lagrangian coherent structures explain its sensitivity to injection time. | **Injection-time destination maps** exist (used for understanding and source inversion). |
| Longest, Azimi, Hindle 2014, *J. Aerosol Med. Pulm. Drug Deliv.* 27:371 (24299500) | Infant ventilation: aerosol released over the full inhalation vs only the first half; first-half release cut exhaled dose about 4×. In vitro + CFD + whole-lung model. | Timing effect (early vs continuous release) demonstrated. |
| Adaptive Aerosol Delivery (I-neb, HaloLite): Denyer et al. 2004 (16296727), 2010 (20373904); Hardaker & Hatley 2010 (20373905); Nikander et al. 2010 (20373908) | Device that monitors breathing and pulses aerosol during the early part of inspiration. | **Breath-synchronised pulsed release is in clinical devices.** |
| Controlled inhalation (AKITA-type): Bennett 2005 (16296800); Brand et al. 2005 (15741773); Fischer et al. 2009 (20156730); Bourke et al. 2022 (35174574) | Devices control inspiratory flow/volume and deliver a defined aerosol bolus. | Volume-controlled bolus delivery established clinically. |
| Bennett, Scheuch, Zeman et al. 1998, *J. Appl. Physiol.* 85:685 (9688747) | Bolus inhaled to a set volumetric front depth; deposition depends on anatomic dead space. | Physical basis: whether a bolus reaches a region depends on volume inhaled after it relative to airway volume. |
| Talaat, Si, Xi 2022, *Pharmaceuticals* 15 (35056118) | LES of MDI actuation timing relative to inhalation and its effect on regional dose. | Release timing in CFD. |
| Chiang et al. 2026, *Int. J. Pharm.* (42815655) | Breath-synchronised smart nebulizer (acoustic detection, release only on inhalation). | Device-side synchronisation. |

## 2. Optimization, surrogates and variability

| Work (PMID) | Relevance |
|---|---|
| Khaksar et al. 2024 (38869656) | CFD-DPM + genetic algorithm to maximise bronchial deposition over diameter, shape factor, velocity. Single-condition optimisation. |
| Ling et al. 2026 (42213572) | Deep reinforcement learning + CFD vs response-surface method for DPI/particle parameters. |
| Chen et al. 2021 (33689824) | Taguchi + response-surface analysis of microparticle deposition. |
| Kolanjiyil & Kleinstreuer 2016 (27810625) | Computationally efficient whole-lung model (3-D upper airway + 1-D lumped lower airways). |
| Poorbahrami & Oakes 2019 (29395490); Borojeni et al. 2023 (36678786); Kolewe et al. 2023 (37523076); Yang et al. 2024 (38541730) | Inter-subject variability / uncertainty quantification of deposition. |
| Rajaraman et al. 2020 (32346183) | Deposition in asthmatic subjects with and without airway narrowing. |

None of these (per abstract) selects release timing to be **robust across breathing waveforms and narrowing
severities**, or reports performance on **held-out conditions not used for selection**.

## 3. Benchmark candidates (experimental / analytical)

| Work (PMID) | Use |
|---|---|
| Comer, Kleinstreuer, Hyun, Kim 2000, *J. Biomech. Eng.* 122:152 (10834155) | CFD of double-bifurcation models (3–7 µm, Stk 0.037–0.23, Re 500–2000) reported to agree with experimental data in the same geometry. The underlying experimental data set is the natural benchmark; it must be obtained from the full papers. |
| Zierenberg et al. 2013, *Math. Med. Biol.* 30:131 (22378463) | Asymptotic carina-impaction model, De ≈ (1.867 S_c^1.78 − 0.016) sin(βπ/2) for 0 < S_c < 0.4 at large Re. Requires the paper's definition of the critical Stokes number S_c; analytical, not experimental. |
| Sonnenberg et al. 2021, *Ann. Biomed. Eng.* 49:812 (32959135) | 3-D-printed symmetric bifurcating tree, ~3 µm droplets, regional deposition by weighing; reproducible bench data. |
| Longest & Vinchurkar 2007 (16533511); Tian et al. 2015 (25944585) | Validation of CFD deposition against experiments / in vivo data. |

**Status: no experimental benchmark has been run.** The data tables needed are in full texts not available
here. This is an external dependency (see `validation/08_experimental_benchmark/README.md`).

## 4. What is and is not new for this project

**Not new (do not claim):**
1. Choosing release timing by inspired volume (Ostrovski 2019; Heller-Algazi 2020; AAD/controlled-inhalation devices).
2. Showing that release timing changes deposition (Longest 2014; Poorbahrami 2019; Talaat 2022).
3. Recording particle release time with fate to build a release-time → fate map (Farghadan 2019; Poorbahrami 2019).
4. CFD + optimisation of particle size / inhalation parameters for a single condition (Heller-Algazi 2020; Khaksar 2024; Ling 2026).

**Candidate contribution (narrower, not found in the retrieved records):**
1. **Robust selection** of pulse placement and particle size that maximises worst-case (or lower-tail)
   delivery **past an airway narrowing** across a set of breathing waveforms and narrowing severities,
   compared head-to-head with continuous release and single-condition optimisation.
2. **Pre-specified train/test separation**, with evaluation on held-out breathing and airway conditions.
3. **Use of the release-time response map as a verified surrogate**: one continuous-release, one-way-coupled
   run per condition predicts any flow-proportional pulse schedule by superposition. The novelty is not the
   map itself (prior work above) but (a) stating the exact conditions under which superposition is exact,
   (b) quantifying its error against independent direct pulse simulations, and (c) the cost reduction that
   makes the robust optimisation affordable.

Whether the narrowed contribution is publishable depends on (i) the full-text check of the ★ works and
(ii) whether the timing effect in this model is large enough to matter (`docs/TIMING_FEASIBILITY.md`).
