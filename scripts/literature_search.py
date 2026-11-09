#!/usr/bin/env python3
"""Reproducible literature retrieval from PubMed (NCBI E-utilities). No citation is typed by hand:
every record cited in docs/LITERATURE_REVIEW.md must exist in docs/literature/records.json (PMID + DOI).

    python scripts/literature_search.py              # runs every query in QUERIES
    python scripts/literature_search.py --show       # prints a compact list of retrieved records

Uses the system curl (/usr/bin/curl) because the anaconda curl lacks OpenSSL here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "literature"
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

QUERIES = {
    "adaptive_aerosol_delivery": '"adaptive aerosol delivery"',
    "breath_synchronized": '(breath-actuated OR breath-synchronized OR breath-triggered OR "breath enhanced") AND (nebulizer OR nebuliser OR inhaler) AND aerosol',
    "release_timing": '(aerosol OR drug) AND (release OR pulse OR injection) AND (timing OR "release time") AND (inhalation OR inspiration) AND (deposition OR "lung dose") AND (model OR simulation OR CFD)',
    "dead_space_timing": '"dead space" AND aerosol AND (timing OR bolus OR "inhaled volume" OR "end of inspiration") AND deposition',
    "deposition_transfer_fn": '(particle OR aerosol) AND deposition AND ("transfer function" OR "Green\'s function" OR superposition OR "impulse response") AND (lung OR airway)',
    "transient_release_cfd": '(CFD OR "computational fluid dynamics") AND particle AND ("injection time" OR "release time" OR "time of injection" OR "time of release") AND (airway OR lung OR inhal*)',
    "controlled_inhalation": '("controlled inhalation" OR AKITA OR "inhalation volume" OR "volume-triggered") AND aerosol AND deposition',
    "aerosol_bolus": '"aerosol bolus" AND (deposition OR dispersion) AND lung',
    "bolus_timing_depth": '(bolus OR "pulsed") AND aerosol AND ("volumetric lung depth" OR "penetration volume" OR "inhaled volume") AND deposition',
    "cfd_targeted_release": '(computational fluid dynamics OR CFD) AND ("targeted drug delivery" OR "targeted delivery") AND aerosol AND (release OR injection) AND airway',
    "cfd_release_position": '("release position" OR "release map" OR "controlled release" OR "particle release") AND inhal* AND (CFD OR "computational fluid dynamics")',
    "cfd_waveform_transient": '(CFD OR "computational fluid dynamics") AND aerosol AND deposition AND ("breathing waveform" OR "transient inhalation" OR "inhalation waveform" OR "breathing pattern") AND airway',
    "robust_uncertainty": '(uncertainty OR "robust optimization" OR "uncertainty quantification" OR variability) AND aerosol AND deposition AND (CFD OR "computational fluid dynamics") AND airway',
    "patient_specific": '"patient-specific" AND aerosol AND deposition AND (CFD OR "computational fluid dynamics") AND airway',
    "surrogate_reduced_order": '(surrogate OR "reduced-order" OR "machine learning" OR "response surface") AND particle AND deposition AND (CFD OR "computational fluid dynamics") AND (airway OR lung)',
    "stenosis_deposition": '(stenosis OR narrowing OR constriction OR obstruction) AND (CFD OR "computational fluid dynamics") AND particle deposition AND (bronch* OR airway)',
    "bifurcation_impaction": '(bifurcation) AND (impaction OR deposition) AND aerosol AND ("Stokes number") AND airway',
    "double_bifurcation_experiment": '("double bifurcation" OR "bifurcating airway model" OR "sequentially bifurcating") AND (deposition) AND (aerosol OR particle) AND (experiment* OR measured)',
    "smart_inhaler_timing": '(inhaler) AND (timing OR synchroni*) AND (actuation OR release) AND (inhalation) AND (deposition OR "lung dose")',
    "optimization_inhalation": '(optimization OR optimisation) AND (inhalation OR inhaled) AND (particle size OR "aerodynamic diameter") AND deposition AND (model OR simulation)',
}


def get(url: str) -> str:
    for attempt in range(4):
        r = subprocess.run(["/usr/bin/curl", "-s", "--max-time", "60", url], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        time.sleep(2 + attempt * 2)
    raise RuntimeError(f"failed: {url}")


def search(term: str, retmax: int = 40) -> tuple[int, list[str]]:
    q = urllib.parse.urlencode({"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json", "sort": "relevance"})
    js = json.loads(get(BASE + "esearch.fcgi?" + q))["esearchresult"]
    return int(js["count"]), js["idlist"]


def fetch(pmids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(pmids), 100):
        q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids[i:i + 100]), "retmode": "xml"})
        root = ET.fromstring(get(BASE + "efetch.fcgi?" + q))
        for art in root.findall(".//PubmedArticle"):
            med = art.find("MedlineCitation")
            a = med.find("Article")
            title = "".join(a.find("ArticleTitle").itertext()) if a.find("ArticleTitle") is not None else ""
            abst = " ".join("".join(t.itertext()) for t in a.findall("Abstract/AbstractText"))
            authors = []
            for au in a.findall("AuthorList/Author"):
                ln, ini = au.findtext("LastName"), au.findtext("Initials")
                if ln:
                    authors.append(f"{ln} {ini or ''}".strip())
            year = (a.findtext("Journal/JournalIssue/PubDate/Year") or
                    (a.findtext("Journal/JournalIssue/PubDate/MedlineDate") or "")[:4])
            doi = ""
            for idn in art.findall("PubmedData/ArticleIdList/ArticleId"):
                if idn.get("IdType") == "doi":
                    doi = idn.text or ""
            out.append({"pmid": med.findtext("PMID"), "title": title, "authors": authors, "year": year,
                        "journal": a.findtext("Journal/Title") or "", "volume": a.findtext("Journal/JournalIssue/Volume") or "",
                        "pages": a.findtext("Pagination/MedlinePgn") or "", "doi": doi, "abstract": abst})
        time.sleep(0.4)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--retmax", type=int, default=40)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    recf = OUT / "records.json"
    if a.show:
        recs = json.loads(recf.read_text())
        for r in sorted(recs.values(), key=lambda r: r["year"]):
            print(f"{r['pmid']:>9} {r['year']} {r['authors'][0] if r['authors'] else '?':18.18} {r['title'][:110]}  [{','.join(r['topics'])}]")
        return
    recs: dict[str, dict] = json.loads(recf.read_text()) if recf.exists() else {}
    log = {}
    for topic, term in QUERIES.items():
        n, ids = search(term, a.retmax)
        log[topic] = {"query": term, "total_hits": n, "retrieved": ids, "date": time.strftime("%Y-%m-%d")}
        new = [i for i in ids if i not in recs]
        for r in fetch(new):
            r["topics"] = []
            recs[r["pmid"]] = r
        for i in ids:
            if i in recs and topic not in recs[i]["topics"]:
                recs[i]["topics"].append(topic)
        print(f"{topic:30s} hits {n:6d}  retrieved {len(ids)}")
        time.sleep(0.5)
    recf.write_text(json.dumps(recs, indent=1))
    (OUT / "search_log.json").write_text(json.dumps(log, indent=1))
    print(f"[ok] {len(recs)} unique records -> {recf.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
