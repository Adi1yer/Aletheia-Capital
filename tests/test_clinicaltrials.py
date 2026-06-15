"""Tests for ClinicalTrials.gov v2 study parsing and search term cleaning."""

from src.biotech.clinicaltrials import _study_to_trial, clean_company_term
from src.biotech.readout_window import trial_phase_number


def test_clean_company_term_strips_legal_suffix_and_comma():
    # The legal suffix + comma collapses CT.gov results (96 -> 3), so it must go.
    assert clean_company_term("Alnylam Pharmaceuticals, Inc.") == "Alnylam Pharmaceuticals"
    assert clean_company_term("ACADIA Pharmaceuticals Inc.") == "ACADIA Pharmaceuticals"
    assert clean_company_term("Some Biotech Co., Ltd.") == "Some Biotech"


def test_clean_company_term_keeps_plain_name():
    assert clean_company_term("Apogee Therapeutics") == "Apogee Therapeutics"


def test_clean_company_term_empty_falls_back():
    assert clean_company_term("") == ""


def test_study_to_trial_reads_phase_from_design_module():
    # API v2 exposes phases under designModule, not identificationModule.
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT123", "briefTitle": "A trial"},
            "statusModule": {
                "overallStatus": "RECRUITING",
                "primaryCompletionDateStruct": {"date": "2026-07"},
            },
            "designModule": {"phases": ["PHASE3"]},
        }
    }
    trial = _study_to_trial(study)
    assert trial is not None
    assert trial.phase == "PHASE3"
    assert trial_phase_number(trial) == 3
    assert trial.primary_completion_date == "2026-07"


def test_study_to_trial_combined_phases():
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT999"},
            "designModule": {"phases": ["PHASE1", "PHASE2"]},
        }
    }
    trial = _study_to_trial(study)
    assert trial is not None
    assert trial.phase == "PHASE1,PHASE2"
    assert trial_phase_number(trial) == 2
