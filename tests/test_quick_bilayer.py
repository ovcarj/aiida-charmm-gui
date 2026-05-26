"""Tests for QuickBilayerWorkChain helper functions."""

from __future__ import annotations

import pytest
from aiida_charmm_gui.workflows.quick_bilayer import (
    _build_quick_bilayer_parameters,
    _validate_quick_bilayer_inputs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _protein_custom(**overrides):
    """Valid: protein system with explicit lipid composition."""
    return {
        "upper": "DOPC:POPC=1:1",
        "lower": "DOPC:POPC=1:1",
        "membtype": None,
        "jobid_pdb": "job123",
        "membrane_only": False,
        **overrides,
    }


def _membrane_preset(**overrides):
    """Valid: membrane-only system with preset type."""
    return {
        "upper": None,
        "lower": None,
        "membtype": "PMm",
        "jobid_pdb": None,
        "membrane_only": True,
        **overrides,
    }


def _default_build_kwargs(**overrides):
    return {
        "upper": None,
        "lower": None,
        "membtype": "PMm",
        "jobid_pdb": None,
        "membrane_only": True,
        "margin": 20.0,
        "wdist": 22.5,
        "ion_conc": 0.15,
        "ion_type": "NaCl",
        "prot_projection_upper": False,
        "prot_projection_lower": False,
        "ppm": False,
        "topology_in": True,
        "heteroatoms": False,
        "clone_job": False,
        **overrides,
    }


# ---------------------------------------------------------------------------
# _validate_quick_bilayer_inputs — valid combinations
# ---------------------------------------------------------------------------


def test_validate_protein_custom_lipids():
    assert _validate_quick_bilayer_inputs(**_protein_custom()) is None


def test_validate_protein_preset():
    assert _validate_quick_bilayer_inputs(**_protein_custom(upper=None, lower=None, membtype="PMm")) is None


def test_validate_membrane_only_custom_lipids():
    assert _validate_quick_bilayer_inputs(**_membrane_preset(upper="DOPC=1", lower="POPC=1", membtype=None)) is None


def test_validate_membrane_only_preset():
    assert _validate_quick_bilayer_inputs(**_membrane_preset()) is None


# ---------------------------------------------------------------------------
# _validate_quick_bilayer_inputs — invalid combinations
# ---------------------------------------------------------------------------


def test_validate_upper_without_lower():
    assert _validate_quick_bilayer_inputs(**_protein_custom(lower=None)) is not None


def test_validate_lower_without_upper():
    assert _validate_quick_bilayer_inputs(**_protein_custom(upper=None)) is not None


def test_validate_no_lipid_spec():
    assert _validate_quick_bilayer_inputs(**_protein_custom(upper=None, lower=None, membtype=None)) is not None


def test_validate_both_custom_and_preset():
    assert _validate_quick_bilayer_inputs(**_protein_custom(membtype="PMm")) is not None


def test_validate_no_protein_spec():
    assert _validate_quick_bilayer_inputs(**_protein_custom(jobid_pdb=None)) is not None


def test_validate_both_jobid_and_membrane_only():
    assert _validate_quick_bilayer_inputs(**_protein_custom(membrane_only=True)) is not None


# ---------------------------------------------------------------------------
# _build_quick_bilayer_parameters
# ---------------------------------------------------------------------------


def test_build_membrane_only_preset_keys():
    params = _build_quick_bilayer_parameters(**_default_build_kwargs())
    assert params["membtype"] == "PMm"
    assert "upper" not in params
    assert "lower" not in params
    assert params["membrane_only"] == "true"
    assert "jobid" not in params


def test_build_protein_custom_lipids_keys():
    kwargs = _default_build_kwargs(
        upper="DOPC=1", lower="POPC=1", membtype=None, jobid_pdb="job42", membrane_only=False
    )
    params = _build_quick_bilayer_parameters(**kwargs)
    assert params["upper"] == "DOPC=1"
    assert params["lower"] == "POPC=1"
    assert "membtype" not in params
    assert params["jobid"] == "job42"
    assert "membrane_only" not in params


def test_build_margin_included():
    params = _build_quick_bilayer_parameters(**_default_build_kwargs(margin=15.0))
    assert params["margin"] == 15.0


def test_build_api_field_names():
    """Verify that AiiDA-friendly input names are mapped to the correct API field names."""
    params = _build_quick_bilayer_parameters(**_default_build_kwargs(ion_conc=0.1, ion_type="KCl", topology_in=False))
    assert "Ion_conc" in params
    assert params["Ion_conc"] == pytest.approx(0.1)
    assert "Ion_type" in params
    assert params["Ion_type"] == "KCl"
    assert "topologyIn" in params
    assert params["topologyIn"] is False


def test_build_optional_booleans_present():
    kwargs = _default_build_kwargs(
        prot_projection_upper=True,
        prot_projection_lower=True,
        ppm=True,
        heteroatoms=True,
        clone_job=True,
    )
    params = _build_quick_bilayer_parameters(**kwargs)
    assert params["prot_projection_upper"] is True
    assert params["prot_projection_lower"] is True
    assert params["ppm"] is True
    assert params["heteroatoms"] is True
    assert params["clone_job"] is True
