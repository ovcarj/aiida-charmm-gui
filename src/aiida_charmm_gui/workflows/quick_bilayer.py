"""WorkChain for submitting CHARMM-GUI Quick Bilayer jobs."""

from __future__ import annotations

from aiida import orm
from aiida.engine import ExitCode, ToContext, WorkChain

from aiida_charmm_gui.client import DEFAULT_TOKEN_FILE
from aiida_charmm_gui.workflows.base import CharmmGuiWorkChain

QUICK_BILAYER_URL = "https://charmm-gui.org/api/quick_bilayer"


def _validate_quick_bilayer_inputs(
    upper: str | None,
    lower: str | None,
    membtype: str | None,
    jobid_pdb: str | None,
    membrane_only: bool,
) -> str | None:
    """Return an error message if inputs are inconsistent, else None."""
    has_upper = upper is not None
    has_lower = lower is not None
    has_custom = has_upper and has_lower
    has_preset = membtype is not None

    if has_upper != has_lower:
        return "Both 'upper' and 'lower' must be provided together."
    if not has_custom and not has_preset:
        return "Provide either 'upper'+'lower' or 'membtype' to specify the lipid composition."
    if has_custom and has_preset:
        return "'upper'/'lower' and 'membtype' are mutually exclusive."

    has_pdb = jobid_pdb is not None
    if membrane_only and has_pdb:
        return "'jobid_pdb' and 'membrane_only=True' are mutually exclusive."
    if not membrane_only and not has_pdb:
        return "Provide 'jobid_pdb' for a protein system, or set 'membrane_only' to True."

    return None


def _build_quick_bilayer_parameters(
    upper: str | None,
    lower: str | None,
    membtype: str | None,
    jobid_pdb: str | None,
    membrane_only: bool,
    margin: float,
    wdist: float,
    ion_conc: float,
    ion_type: str,
    prot_projection_upper: bool,
    prot_projection_lower: bool,
    ppm: bool,
    topology_in: bool,
    heteroatoms: bool,
    clone_job: bool,
) -> dict:
    """Build the form-data parameter dict for the Quick Bilayer API endpoint."""
    params: dict = {"margin": margin}

    if upper is not None:
        params["upper"] = upper
        params["lower"] = lower
    else:
        params["membtype"] = membtype

    if membrane_only:
        params["membrane_only"] = "true"
    else:
        params["jobid"] = jobid_pdb

    params["wdist"] = wdist
    params["Ion_conc"] = ion_conc
    params["Ion_type"] = ion_type
    params["prot_projection_upper"] = prot_projection_upper
    params["prot_projection_lower"] = prot_projection_lower
    params["ppm"] = ppm
    params["topologyIn"] = topology_in
    params["heteroatoms"] = heteroatoms
    params["clone_job"] = clone_job

    return params


class QuickBilayerWorkChain(WorkChain):
    """Submit a CHARMM-GUI Quick Bilayer job and store results.

    Validates Quick Bilayer-specific parameter combinations, then delegates to
    ``CharmmGuiWorkChain`` for submission, polling, and download.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)

        # --- lipid composition (mutually exclusive with membtype) ---
        spec.input(
            "upper",
            valid_type=orm.Str,
            required=False,
            help=(
                "Lipid composition for the upper leaflet (e.g. 'DOPC:POPC:CHL1=1:1:2'). "
                "Required unless 'membtype' is set."
            ),
        )
        spec.input(
            "lower",
            valid_type=orm.Str,
            required=False,
            help="Lipid composition for the lower leaflet. Required unless 'membtype' is set.",
        )
        spec.input(
            "membtype",
            valid_type=orm.Str,
            required=False,
            help="Preset membrane type (e.g. 'PMm', 'PMf', 'PMp'). Required unless 'upper'/'lower' are set.",
        )

        # --- protein / membrane-only (mutually exclusive) ---
        spec.input(
            "jobid_pdb",
            valid_type=orm.Str,
            required=False,
            help="Job ID from the PDB Reader module. Required unless 'membrane_only' is True.",
        )
        spec.input(
            "membrane_only",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Generate a membrane system without protein.",
        )

        # --- geometry ---
        spec.input("margin", valid_type=orm.Float, help="Box boundary margin in Å.")

        # --- optional parameters ---
        spec.input(
            "wdist",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(22.5),
            help="Z-length water boundary in Å.",
        )
        spec.input(
            "ion_conc",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.15),
            help="Ion concentration in M.",
        )
        spec.input(
            "ion_type",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str("NaCl"),
            help="Ion type (e.g. 'NaCl', 'KCl').",
        )
        spec.input(
            "prot_projection_upper",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Enable protein projection on upper leaflet.",
        )
        spec.input(
            "prot_projection_lower",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Enable protein projection on lower leaflet.",
        )
        spec.input(
            "ppm", valid_type=orm.Bool, required=False, default=lambda: orm.Bool(False), help="Enable PPM support."
        )
        spec.input(
            "topology_in",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(True),
            help="Include N-terminal (API field: topologyIn).",
        )
        spec.input(
            "heteroatoms",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Include hetero atoms.",
        )
        spec.input(
            "clone_job",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Copy job directory for multiple lipid compositions.",
        )

        # --- forwarded to CharmmGuiWorkChain ---
        spec.input(
            "token_file",
            valid_type=str,
            non_db=True,
            required=False,
            default=str(DEFAULT_TOKEN_FILE),
            help="Path to cached token file written by ``aiida-charmm-gui login``. Not stored in provenance.",
        )
        spec.input(
            "poll_interval",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(30),
            help="Seconds to wait between status checks.",
        )
        spec.input(
            "download_timeout",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(600),
            help="Maximum seconds to wait for the archive to become available after job completion.",
        )

        spec.outline(
            cls.validate_inputs,
            cls.submit_base_workflow,
            cls.collect_outputs,
        )

        spec.output("jobid", valid_type=orm.Str, help="CHARMM-GUI job identifier.")
        spec.output("results", valid_type=orm.FolderData, help="Unpacked job output archive.")

        spec.exit_code(400, "ERROR_INVALID_INPUTS", message="Input parameters are inconsistent.")

    def validate_inputs(self) -> ExitCode | None:
        """Check mutual-exclusion rules and fail fast before submitting."""
        error = _validate_quick_bilayer_inputs(
            upper=self.inputs.upper.value if "upper" in self.inputs else None,
            lower=self.inputs.lower.value if "lower" in self.inputs else None,
            membtype=self.inputs.membtype.value if "membtype" in self.inputs else None,
            jobid_pdb=self.inputs.jobid_pdb.value if "jobid_pdb" in self.inputs else None,
            membrane_only=self.inputs.membrane_only.value,
        )
        if error is not None:
            self.report(error)
            return self.exit_codes.ERROR_INVALID_INPUTS

    def _build_parameters_from_inputs(self) -> dict:
        return _build_quick_bilayer_parameters(
            upper=self.inputs.upper.value if "upper" in self.inputs else None,
            lower=self.inputs.lower.value if "lower" in self.inputs else None,
            membtype=self.inputs.membtype.value if "membtype" in self.inputs else None,
            jobid_pdb=self.inputs.jobid_pdb.value if "jobid_pdb" in self.inputs else None,
            membrane_only=self.inputs.membrane_only.value,
            margin=self.inputs.margin.value,
            wdist=self.inputs.wdist.value,
            ion_conc=self.inputs.ion_conc.value,
            ion_type=self.inputs.ion_type.value,
            prot_projection_upper=self.inputs.prot_projection_upper.value,
            prot_projection_lower=self.inputs.prot_projection_lower.value,
            ppm=self.inputs.ppm.value,
            topology_in=self.inputs.topology_in.value,
            heteroatoms=self.inputs.heteroatoms.value,
            clone_job=self.inputs.clone_job.value,
        )

    def submit_base_workflow(self):
        """Build parameters and submit ``CharmmGuiWorkChain`` as a child process."""
        base = self.submit(
            CharmmGuiWorkChain,
            submission_url=orm.Str(QUICK_BILAYER_URL),
            parameters=orm.Dict(self._build_parameters_from_inputs()),
            token_file=self.inputs.token_file,
            poll_interval=self.inputs.poll_interval,
            download_timeout=self.inputs.download_timeout,
        )
        return ToContext(base=base)

    def collect_outputs(self) -> ExitCode | None:
        """Pass outputs from the child ``CharmmGuiWorkChain`` through to this chain's outputs."""
        base = self.ctx.base
        if not base.is_finished_ok:
            self.report(f"Base workflow failed with exit status {base.exit_status}.")
            return base.exit_code
        self.out("jobid", base.outputs.jobid)
        self.out("results", base.outputs.results)
