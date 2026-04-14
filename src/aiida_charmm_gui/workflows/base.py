"""Generic WorkChain for submitting, polling, and downloading CHARMM-GUI jobs."""

from __future__ import annotations

import io
import tarfile
import tempfile
import time
from pathlib import Path

import requests
from aiida import orm
from aiida.engine import ExitCode, WorkChain, while_

from aiida_charmm_gui.client import DEFAULT_TOKEN_FILE, CharmmGuiClient

# /api/check_status returns free-form strings like "running quick_bilayer".
# Only "done" is the success terminal state; anything that is not "done" and
# does not start with "running" or "pending" is treated as an error.
_SUCCESS_STATUS = "done"
_RUNNING_PREFIXES = ("running", "pending", "submitted")


class CharmmGuiWorkChain(WorkChain):
    """Submit a job to a CHARMM-GUI module endpoint, poll until completion, and store results.

    The workflow has three steps:
      1. ``submit_job``   — POST parameters to the module endpoint, store the jobid.
      2. ``check_job_status`` (looped) — poll /api/check_status until the job is done or failed.
      3. ``download_results`` — fetch the .tgz archive and store it as ``FolderData``.

    Authentication relies on a cached token produced by ``aiida-charmm-gui login``.
    The login step is intentionally outside AiiDA provenance.

    .. note::
        ``poll_interval`` causes a ``time.sleep()`` inside the daemon worker.
        For long-running jobs, consider pausing the WorkChain externally and
        resuming it on a schedule instead.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.input(
            "submission_url",
            valid_type=orm.Str,
            help="Full URL of the module submission endpoint (e.g. https://charmm-gui.org/api/quick_bilayer).",
        )
        spec.input(
            "parameters",
            valid_type=orm.Dict,
            help="Parameters sent as form data in the POST body.",
        )
        spec.input(
            "token_file",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str(str(DEFAULT_TOKEN_FILE)),
            help="Path to the cached token file written by ``aiida-charmm-gui login``.",
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
            cls.submit_job,
            while_(cls.job_not_done)(
                cls.check_job_status,
            ),
            cls.download_results,
        )

        spec.output("jobid", valid_type=orm.Str, help="CHARMM-GUI job identifier.")
        spec.output("results", valid_type=orm.FolderData, help="Unpacked job output archive.")

        spec.exit_code(300, "ERROR_SUBMISSION_FAILED", message="Job submission failed.")
        spec.exit_code(301, "ERROR_JOB_FAILED", message="Remote job finished with error status.")
        spec.exit_code(302, "ERROR_DOWNLOAD_FAILED", message="Failed to download job results.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _client(self) -> CharmmGuiClient:
        """Instantiate a client from the token file input.

        A new instance is created each time so the WorkChain remains
        serialisable across daemon checkpoints.
        """
        return CharmmGuiClient(token_file=Path(self.inputs.token_file.value))

    # ------------------------------------------------------------------
    # Outline steps
    # ------------------------------------------------------------------

    def submit_job(self) -> ExitCode | None:
        """POST parameters to the submission endpoint and store the jobid."""
        try:
            data = self._client().submit(
                url=self.inputs.submission_url.value,
                parameters=self.inputs.parameters.get_dict(),
            )
        except requests.RequestException as exc:
            self.report(f"Submission request failed: {exc}")
            return self.exit_codes.ERROR_SUBMISSION_FAILED

        if not data.get("submitted"):
            self.report(f"Server did not confirm submission: {data}")
            return self.exit_codes.ERROR_SUBMISSION_FAILED

        jobid = data["jobid"]
        self.ctx.jobid = jobid
        self.ctx.job_status = "pending"
        self.out("jobid", orm.Str(jobid).store())
        self.report(f"Submitted job {jobid} (modules: {data.get('modules', 'unknown')}).")

    def job_not_done(self) -> bool:
        """Return True while the job has not reached a terminal state."""
        return self.ctx.job_status != _SUCCESS_STATUS

    def check_job_status(self) -> ExitCode | None:
        """Poll /api/check_status and update ``ctx.job_status``."""
        try:
            data = self._client().check_status(self.ctx.jobid)
        except requests.RequestException as exc:
            # Transient network error — log and retry on the next iteration.
            self.report(f"Status check failed (will retry): {exc}")
            time.sleep(self.inputs.poll_interval.value)
            return

        status = data.get("status", "unknown")
        self.ctx.job_status = status
        self.report(f"Job {self.ctx.jobid} status: {status}.")

        is_running = status == _SUCCESS_STATUS or status.startswith(_RUNNING_PREFIXES)
        if not is_running:
            self.report(f"Job failed. Last output:\n{data.get('lastOutLines', '(none)')}")
            return self.exit_codes.ERROR_JOB_FAILED

        if status != _SUCCESS_STATUS:
            time.sleep(self.inputs.poll_interval.value)

    def download_results(self) -> ExitCode | None:
        """Download the .tgz archive and store it as ``FolderData``.

        CHARMM-GUI may take some time to package the archive after the job
        reports ``done``. If the response is not a valid gzip file, the
        download is retried every 60 seconds up to ``download_timeout``.
        """
        retry_interval = 60
        timeout = self.inputs.download_timeout.value
        elapsed = 0

        while True:
            try:
                content = self._client().download(self.ctx.jobid)
            except requests.RequestException as exc:
                self.report(f"Download failed: {exc}")
                return self.exit_codes.ERROR_DOWNLOAD_FAILED

            try:
                folder = orm.FolderData()
                with tempfile.TemporaryDirectory() as tmpdir:
                    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                        tar.extractall(path=tmpdir, filter="data")
                    folder.put_object_from_tree(tmpdir)
                self.out("results", folder.store())
                self.report(f"Results stored for job {self.ctx.jobid}.")
                return
            except tarfile.ReadError:
                if elapsed >= timeout:
                    self.report(f"Archive not ready after {timeout}s — giving up.")
                    return self.exit_codes.ERROR_DOWNLOAD_FAILED
                self.report(f"Archive not ready yet, retrying in {retry_interval}s ({elapsed}s elapsed).")
                time.sleep(retry_interval)
                elapsed += retry_interval
