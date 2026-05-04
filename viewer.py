"""3D-viewer voor Bep-Project measurement.csv.

Gebruik:
    python viewer.py data/<run-folder>/measurement.csv
    python viewer.py data/<run-folder>/measurement.csv --metric V_pp
    python viewer.py data/<run-folder>/measurement.csv --unit steps

Default:
  - mm als motorN_mm-kolommen aanwezig en niet identiek 0
  - anders fallback naar stappen
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  registreert 3d-projection


METRICS = ["V_mean", "V_min", "V_max", "V_std", "V_pp"]
UNITS = ["auto", "mm", "steps"]


def load(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path, sep=";", decimal=",")


def resolve_unit(df: pd.DataFrame, unit: str) -> str:
    """Bepaal welke as-kolom we gebruiken: 'mm' of 'steps'."""
    if unit == "mm":
        return "mm"
    if unit == "steps":
        return "steps"
    has_mm = ("motor1_mm" in df.columns and "motor2_mm" in df.columns
              and (df["motor1_mm"].abs().sum() > 0 or df["motor2_mm"].abs().sum() > 0))
    return "mm" if has_mm else "steps"


def axis_columns(unit: str) -> tuple[str, str, str, str]:
    """(x_col, y_col, x_label, y_label) voor de gekozen unit."""
    if unit == "mm":
        return ("motor1_mm", "motor2_mm", "Motor 1 (mm)", "Motor 2 (mm)")
    return ("motor1", "motor2", "Motor 1 (stappen)", "Motor 2 (stappen)")


def reduce_per_position(df: pd.DataFrame, x_col: str, y_col: str,
                        metric: str) -> pd.DataFrame:
    """Gemiddelde van metric per (x, y)-punt — duplicaten aggregeren."""
    return df.groupby([x_col, y_col], as_index=False)[metric].mean()


def plot(df: pd.DataFrame, metric: str, unit: str, title: str) -> None:
    x_col, y_col, x_lbl, y_lbl = axis_columns(unit)
    grouped = reduce_per_position(df, x_col, y_col, metric)
    x = grouped[x_col].to_numpy()
    y = grouped[y_col].to_numpy()
    z = grouped[metric].to_numpy()

    fig = plt.figure(figsize=(12, 5))
    fig.suptitle(title)

    ax3d = fig.add_subplot(1, 2, 1, projection="3d")
    if len(grouped) >= 3:
        ax3d.plot_trisurf(x, y, z, cmap="viridis", linewidth=0.2)
    else:
        ax3d.scatter(x, y, z, c=z, cmap="viridis", s=40)
    ax3d.set_xlabel(x_lbl)
    ax3d.set_ylabel(y_lbl)
    ax3d.set_zlabel(metric)
    ax3d.set_title(f"3D-oppervlak — {metric}")

    ax2d = fig.add_subplot(1, 2, 2)
    sc = ax2d.scatter(x, y, c=z, cmap="viridis", s=40)
    ax2d.set_xlabel(x_lbl)
    ax2d.set_ylabel(y_lbl)
    ax2d.set_title(f"Heatmap — {metric}")
    fig.colorbar(sc, ax=ax2d, label=metric)

    fig.tight_layout()
    plt.show()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", type=Path, help="pad naar measurement.csv")
    p.add_argument("--metric", default="V_mean", choices=METRICS,
                   help="welke samenvattings-kolom als hoogte/kleur (default V_mean)")
    p.add_argument("--unit", default="auto", choices=UNITS,
                   help="as-eenheid: 'auto' (mm als gekalibreerd, anders steps), "
                        "'mm', of 'steps' (default auto)")
    args = p.parse_args()

    if not args.csv.exists():
        print(f"Niet gevonden: {args.csv}", file=sys.stderr)
        sys.exit(1)

    df = load(args.csv)
    if df.empty:
        print("CSV is leeg — geen data om te plotten.", file=sys.stderr)
        sys.exit(1)

    unit = resolve_unit(df, args.unit)
    x_col, y_col, _, _ = axis_columns(unit)
    n_x = df[x_col].nunique()
    n_y = df[y_col].nunique()
    print(
        f"{len(df)} rijen geladen — eenheid: {unit} — "
        f"{n_x} unieke X-posities, {n_y} unieke Y-posities."
    )
    if n_x < 2 or n_y < 2:
        print(
            "Waarschuwing: minder dan 2 unieke posities op een as — "
            "een 3D-oppervlak is dan niet betekenisvol.",
            file=sys.stderr,
        )

    plot(df, args.metric, unit, title=str(args.csv))


if __name__ == "__main__":
    main()
