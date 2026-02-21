"""Training pipeline orchestrator."""

from __future__ import annotations

from typing import Any, Iterable

from autocapture.training.datasets import Dataset, dataset_from_items
from autocapture.training.dpo import run_dpo
from autocapture.training.lora import run_lora


class TrainingPipeline:
    def __init__(self, method: str = "lora") -> None:
        self.method = method

    def run(
        self,
        *,
        dataset: Dataset | Iterable[Any],
        params: dict[str, Any] | None = None,
        output_dir: str = "artifacts/training",
        run_id: str | None = None,
        created_at: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        data = dataset if isinstance(dataset, Dataset) else dataset_from_items(dataset)
        if self.method == "dpo":
            return run_dpo(
                data,
                params=params,
                output_dir=output_dir,
                run_id=run_id,
                created_at=created_at,
                dry_run=dry_run,
            )
        return run_lora(
            data,
            params=params,
            output_dir=output_dir,
            run_id=run_id,
            created_at=created_at,
            dry_run=dry_run,
        )


def create_training_pipeline(plugin_id: str) -> TrainingPipeline:
    return TrainingPipeline()
